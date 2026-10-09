"""Generic integrity-rule engine (plan §16).

Rules live in YAML (``integrity/rules/*.yaml``) and refer to survey
*concepts*; per-release concept maps (survey_rules.plfs_integrity and the
peer-group source profiles) resolve them to raw columns.  The engine never
changes a value: it lists violations with the rule, its version, its
documentary source and the observed values.  The same engine validates a
single submitted record (online use) and a whole prepared delivery (batch).

Rule lifecycle
--------------
Every rule carries an id, version, type, level (person / household),
severity (``error`` = hard, ``warning`` = soft), a source citation, an owner,
an approval status and at least one violating and one passing test case.
* Test cases are executed whenever rules are loaded; a rule whose own test
  cases fail is refused.
* Every rule — active or not — is dry-run on each batch, and the counts are
  written to ``rule_dry_run.json``.  A hard rule should show ~0 violations on
  released (post-scrutiny) data; otherwise its transcription is suspect.
* Only rules with ``approval_status: approved`` and ``active: true`` produce
  findings for supervisors.  Soft rules stay inactive until HSD activates them.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from peer_groups.config import SOURCE_PROFILES
from preprocessing.config import CONTRACTS
from survey_rules.plfs_integrity import HOUSEHOLD_CONCEPTS, PERSON_CONCEPTS, district_code_list, period_months
from survey_rules.schema import available_columns, read_parquet

RULES_DIRECTORY = Path(__file__).parent / "rules"
DEFAULT_RULES = RULES_DIRECTORY  # every *.yaml file in the directory
RULE_TYPES = {"allowed_values", "range", "required_when", "value_when", "not_value_when", "unique", "absent_when",
              "arithmetic", "lower_bound_sum", "exists_exactly", "count_matches", "references", "within_period"}
LEVELS = {"person", "household"}
SEVERITIES = {"error", "warning"}
APPROVAL = {"approved", "draft", "retired"}
FINDING_COLUMNS = ["source_observation_id", "level", "rule_id", "rule_version", "severity", "message", "source", "observed_values"]


class IntegrityFailure(RuntimeError):
    pass


def _fields(rule: dict[str, Any]) -> list[str]:
    """Every concept a rule reads (used to decide applicability)."""
    names: list[str] = []
    for key in ("field", "target"):
        if rule.get(key):
            names.append(rule[key])
    names += list(rule.get("fields", []))
    for term in rule.get("terms", []):
        names.append(term["field"])
        if "when" in term:
            names.append(term["when"]["field"])
    if "when" in rule:
        names.append(rule["when"]["field"])
    return list(dict.fromkeys(names))


def _validate_rule(rule: dict[str, Any], seen: set[str]) -> None:
    rule_id = rule.get("id")
    if rule.get("type") not in RULE_TYPES:
        raise IntegrityFailure(f"Rule {rule_id} has unsupported type {rule.get('type')}")
    if rule_id in seen:
        raise IntegrityFailure(f"Duplicate rule id {rule_id}")
    for key in ("version", "severity", "level", "message", "source", "owner", "approval_status"):
        if not rule.get(key):
            raise IntegrityFailure(f"Rule {rule_id} must declare {key}")
    if rule["severity"] not in SEVERITIES or rule["level"] not in LEVELS or rule["approval_status"] not in APPROVAL:
        raise IntegrityFailure(f"Rule {rule_id} has an invalid severity, level or approval status")
    tests = rule.get("tests") or []
    if not any(t.get("expect") == "violation" for t in tests) or not any(t.get("expect") == "pass" for t in tests):
        raise IntegrityFailure(f"Rule {rule_id} needs at least one violating and one passing test case")


def load_rules(path: Path = DEFAULT_RULES, *, run_tests: bool = True) -> dict[str, Any]:
    """Load, validate and self-test every rule in a YAML file or a directory of YAML files."""
    path = Path(path)
    files = sorted(path.glob("*.yaml")) if path.is_dir() else [path]
    rules, versions, seen = [], {}, set()
    for file in files:
        document = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        versions[file.name] = document.get("version")
        for rule in document.get("rules", []):
            _validate_rule(rule, seen)
            seen.add(rule["id"])
            rule.setdefault("active", rule["approval_status"] == "approved")
            rules.append(rule)
    document = {"version": "+".join(f"{name}:{version}" for name, version in versions.items()), "rules": rules,
                "content_sha256": hashlib.sha256(b"".join(f.read_bytes() for f in files)).hexdigest()}
    if run_tests:
        failures = run_rule_tests(document)
        if failures:
            raise IntegrityFailure(f"Rule test cases failed: {failures}")
    return document


def run_rule_tests(rules: dict[str, Any]) -> list[str]:
    """Execute every rule's own test cases; return a list of failures (empty when all pass)."""
    failures = []
    for rule in rules["rules"]:
        for number, case in enumerate(rule.get("tests", [])):
            if rule["level"] == "household":
                household = pd.DataFrame([{**{k: ("" if v is None else str(v)) for k, v in case.get("household", {}).items()}, "source_observation_id": "test|household"}])
                persons = pd.DataFrame([{k: ("" if v is None else str(v)) for k, v in p.items()} for p in case.get("persons", [])])
                if not persons.empty:
                    persons["household_key"] = "test|household"
                    household = add_person_aggregates(household.assign(household_key="test|household"), persons)
                frame = household
            else:
                records = case.get("records") or [case.get("record", {})]
                frame = pd.DataFrame([{**{k: ("" if v is None else str(v)) for k, v in record.items()}, "source_observation_id": f"test{i}"}
                                      for i, record in enumerate(records)])
            context = {k: ({tuple(map(str, item)) for item in v} if isinstance(v, list) else v) for k, v in case.get("context", {}).items()}
            violated = len(evaluate(frame, {"rules": [rule]}, context=context)) > 0
            if violated != (case.get("expect") == "violation"):
                failures.append(f"{rule['id']} case {number}")
    return failures


def concept_columns(release: str, observation: str) -> dict[str, str]:
    """Person concept -> raw column for one release, from the documented contracts and concept maps."""
    contract = next((c for c in CONTRACTS.values() if (c.release, c.observation) == (release, observation)), None)
    profile = SOURCE_PROFILES.get((release, observation))
    if contract is None or profile is None:
        raise IntegrityFailure(f"No documented contract for {release}/{observation}")
    mapping = {"record_key": "MoSPI_record_key", "person_serial": profile.person_serial_column, "age": contract.person_fields["age"],
               "cws_status": profile.context_columns["cws_status"], "household_link_status": "MoSPI_household_link_status"}
    for concept, target in (("earnings_salaried", "cws_earnings_salaried"), ("earnings_self_employed", "cws_earnings_self_employed"),
                            ("day7_hours", "day7_total_hours")):
        if target in profile.target_columns:
            mapping[concept] = profile.target_columns[target]
    mapping.update(PERSON_CONCEPTS.get((release, observation), {}))
    return mapping


def household_concept_columns(release: str, observation: str) -> dict[str, str]:
    mapping = {"household_key": "MoSPI_record_key", "state": "MoSPI_state", "quarter": "MoSPI_quarter"}
    if release == "2025":
        mapping["month"] = "MoSPI_month"
    mapping.update(HOUSEHOLD_CONCEPTS.get((release, observation), {}))
    return mapping


def _text(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("").str.strip()


def _number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(_text(series).replace("", np.nan), errors="coerce")


def _condition(frame: pd.DataFrame, when: dict[str, Any]) -> pd.Series:
    field = frame[when["field"]]
    mask = pd.Series(True, index=frame.index)
    if "in" in when:
        mask &= _text(field).isin([str(v) for v in when["in"]])
    if "not_in" in when:
        mask &= ~_text(field).isin([str(v) for v in when["not_in"]]) & _text(field).ne("")
    numeric = _number(field)
    if "min" in when:
        mask &= numeric.ge(when["min"])
    if "max" in when:
        mask &= numeric.le(when["max"])
    return mask.fillna(False)


def _matches(field: pd.Series, values: list[Any]) -> pd.Series:
    numeric_targets = [v for v in values if isinstance(v, (int, float))]
    text_match = _text(field).isin([str(v) for v in values])
    if numeric_targets:
        text_match |= _number(field).isin(numeric_targets)
    return text_match


def _term_sum(frame: pd.DataFrame, terms: list[dict[str, Any]]) -> pd.Series:
    total = pd.Series(0.0, index=frame.index)
    for term in terms:
        value = _number(frame[term["field"]]).fillna(0.0) * float(term.get("factor", 1.0))
        if "when" in term:
            value = value.where(_condition(frame, term["when"]), 0.0)
        total += value
    return total


def evaluate(frame: pd.DataFrame, rules: dict[str, Any], *, context: dict[str, Any] | None = None, include_inactive: bool = True) -> pd.DataFrame:
    """Return one row per (unit, violated rule).  ``frame`` uses concept names.

    ``context`` carries batch-level facts (release, code lists).  A rule whose
    concepts are absent is not applicable to this frame, never "passed".
    """
    context = context or {}
    out = []
    for rule in rules["rules"]:
        if not include_inactive and not (rule.get("active") and rule.get("approval_status") == "approved"):
            continue
        if rule.get("design_periods") and context.get("design_period") and context["design_period"] not in rule["design_periods"]:
            continue
        kind = rule["type"]
        needed = _fields(rule)
        if any(name not in frame for name in needed):
            continue
        present = _text(frame[rule["field"]]).ne("") if rule.get("field") else pd.Series(True, index=frame.index)
        condition = _condition(frame, rule["when"]) if "when" in rule else pd.Series(True, index=frame.index)
        if kind == "unique":
            key = frame[rule["fields"]].astype("string").agg("|".join, axis=1)
            violated = key.duplicated(keep=False)
        elif kind == "allowed_values":
            violated = present & ~_text(frame[rule["field"]]).isin([str(v) for v in rule["values"]])
        elif kind == "range":
            number = _number(frame[rule["field"]])
            outside = pd.Series(False, index=frame.index)
            if "min" in rule:
                outside |= number.lt(rule["min"]).fillna(False)
            if "max" in rule:
                outside |= number.gt(rule["max"]).fillna(False)
            violated = condition & present & outside
        elif kind == "required_when":
            violated = condition & ~present
        elif kind == "absent_when":
            violated = condition & present
        elif kind == "value_when":
            violated = condition & present & ~_matches(frame[rule["field"]], rule["values"])
        elif kind == "not_value_when":
            violated = condition & present & _matches(frame[rule["field"]], rule["values"])
        elif kind == "arithmetic":
            target = _number(frame[rule["target"]])
            expected = _term_sum(frame, rule["terms"])
            violated = condition & target.notna() & (target - expected).abs().gt(float(rule.get("tolerance", 0.0)) + 1e-9)
        elif kind == "lower_bound_sum":
            target = _number(frame[rule["target"]]).fillna(0.0)
            violated = condition & (target < _term_sum(frame, rule["terms"]) - float(rule.get("tolerance", 0.0)) - 1e-9)
        elif kind in ("exists_exactly", "count_matches"):
            count = _number(frame[rule["field"]])
            expected = float(rule["equals"]) if kind == "exists_exactly" else _number(frame[rule["target"]])
            violated = condition & count.notna() & pd.Series(expected, index=frame.index).notna() & count.ne(expected)
        elif kind == "references":
            codes = context.get(rule["code_list"])
            if codes is None:
                continue  # code list not supplied for this release: not applicable
            keys = list(zip(*[_text(frame[f]).str.zfill(int(w)) for f, w in zip(rule["fields"], rule.get("widths", [2] * len(rule["fields"])))]))
            violated = pd.Series([k not in codes for k in keys], index=frame.index) & frame[rule["fields"]].apply(lambda c: _text(c).ne("")).all(axis=1)
        elif kind == "within_period":
            dates = _text(frame[rule["field"]])
            month = pd.to_numeric(dates.str.slice(2, 4), errors="coerce")       # DDMMYYYY (Block 2 item 2)
            allowed = [period_months(context.get("release", ""), q, m) for q, m in zip(_text(frame.get("quarter", pd.Series("", index=frame.index))),
                                                                                          _text(frame.get("month", pd.Series("", index=frame.index))))]
            violated = pd.Series([bool(a) and pd.notna(m) and int(m) not in a for a, m in zip(allowed, month)], index=frame.index) & present
        else:  # pragma: no cover - guarded by load_rules
            continue
        violated = pd.Series(violated, index=frame.index).fillna(False).astype(bool)
        if not violated.any():
            continue
        hits = frame.loc[violated]
        observed = hits[[c for c in needed if c in hits]].astype("string").to_dict(orient="records")
        out.append(pd.DataFrame({"source_observation_id": hits["source_observation_id"].to_numpy(), "level": rule["level"], "rule_id": rule["id"],
                                 "rule_version": str(rule["version"]), "severity": rule["severity"], "message": rule["message"], "source": rule["source"],
                                 "observed_values": [json.dumps(o, ensure_ascii=False) for o in observed]}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=FINDING_COLUMNS)


def concept_frame(raw: pd.DataFrame, release: str, observation: str) -> pd.DataFrame:
    mapping = concept_columns(release, observation)
    frame = pd.DataFrame({concept: raw[column] for concept, column in mapping.items() if column in raw})
    serial = _text(frame["person_serial"]) if "person_serial" in frame else pd.Series("", index=raw.index)
    fallback = _text(raw["MoSPI_source_row"]) if "MoSPI_source_row" in raw else serial
    frame["source_observation_id"] = _text(raw["MoSPI_record_key"]).str.cat(serial.mask(serial.eq(""), fallback), sep="|person=")
    frame["household_key"] = _text(raw["MoSPI_record_key"])
    return frame


def add_person_aggregates(households: pd.DataFrame, persons: pd.DataFrame) -> pd.DataFrame:
    """Cross-level concepts: persons listed and heads (relation code 1) per household."""
    listed = persons.groupby("household_key").size().rename("persons_listed")
    heads = (_text(persons["relation"]).eq("1").groupby(persons["household_key"]).sum().rename("heads")
             if "relation" in persons else pd.Series(dtype=float, name="heads"))
    output = households.copy()
    output["persons_listed"] = output["household_key"].map(listed).fillna(0).astype(int).astype(str)
    if "relation" in persons:
        output["heads"] = output["household_key"].map(heads).fillna(0).astype(int).astype(str)
    return output


@dataclass(frozen=True)
class RunConfig:
    prepared_persons: Path
    output_root: Path
    rules_path: Path = DEFAULT_RULES
    run_id: str | None = None
    prepared_households: Path | None = None  # default: prepared_households.parquet beside the person file


def run(config: RunConfig) -> Path:
    started = time.perf_counter()
    prepared = Path(config.prepared_persons)
    meta = json.loads((prepared.parent / "run_metadata.json").read_text(encoding="utf-8"))
    release, observation = str(meta["release"]), str(meta["observation"])
    mapping = concept_columns(release, observation)
    columns = available_columns(prepared)
    # Concepts not collected in this release are simply absent (rules using them are not applicable);
    # the identity columns are required.
    raw = read_parquet(prepared, columns=["MoSPI_source_row", "MoSPI_record_key", mapping["person_serial"]],
                       optional=[c for c in mapping.values() if c in columns])
    rules = load_rules(config.rules_path)
    persons = concept_frame(raw, release, observation)
    context = {"release": release, "design_period": str(meta["design_period"]), "district_codes": district_code_list(release)}
    frames = {"person": persons}
    household_path = Path(config.prepared_households) if config.prepared_households else prepared.parent / "prepared_households.parquet"
    household_note = None
    if household_path.is_file():
        household_mapping = household_concept_columns(release, observation)
        household_columns = available_columns(household_path)
        raw_households = read_parquet(household_path, columns=["MoSPI_record_key"], optional=[c for c in household_mapping.values() if c in household_columns])
        households = pd.DataFrame({concept: raw_households[column] for concept, column in household_mapping.items() if column in raw_households})
        households["source_observation_id"] = _text(households["household_key"]) + "|household"
        frames["household"] = add_person_aggregates(households, persons)
    else:
        household_note = f"Household file not found ({household_path.name}); household-level rules not evaluated."
    all_findings = []
    for level, frame in frames.items():
        level_rules = {"rules": [r for r in rules["rules"] if r["level"] == level]}
        all_findings.append(evaluate(frame, level_rules, context=context))
    every = pd.concat(all_findings, ignore_index=True) if all_findings else pd.DataFrame(columns=FINDING_COLUMNS)
    active_ids = {r["id"] for r in rules["rules"] if r.get("active") and r["approval_status"] == "approved"}
    violations = every.loc[every["rule_id"].isin(active_ids)].reset_index(drop=True) if len(every) else every
    run_id = config.run_id or str(uuid.uuid4())
    destination = Path(config.output_root) / f"{release}_{observation}_{run_id}"
    destination.mkdir(parents=True, exist_ok=False)
    violations.to_parquet(destination / "integrity_violations.parquet", index=False)
    dry_run = []
    for rule in rules["rules"]:
        level_frame = frames.get(rule["level"])
        applicable = level_frame is not None and all(name in level_frame for name in _fields(rule)) and \
            (rule["type"] != "references" or context.get(rule.get("code_list")) is not None) and \
            not (rule.get("design_periods") and context["design_period"] not in rule["design_periods"])
        hits = every.loc[every["rule_id"].eq(rule["id"])] if len(every) else every
        dry_run.append({"rule_id": rule["id"], "version": str(rule["version"]), "level": rule["level"], "severity": rule["severity"], "type": rule["type"],
                        "approval_status": rule["approval_status"], "active": bool(rule.get("active")), "applicable_to_release": bool(applicable),
                        "units_checked": int(len(level_frame)) if level_frame is not None else 0, "violations": int(hits["source_observation_id"].nunique()) if len(hits) else 0,
                        "source": rule["source"]})
    (destination / "rule_dry_run.json").write_text(json.dumps({"release": release, "rule_set_version": rules["version"], "rule_set_sha256": rules["content_sha256"],
                                                               "rules": dry_run}, indent=2), encoding="utf-8")
    counts = violations.groupby(["rule_id", "severity", "level"]).size().rename("units").reset_index().to_dict(orient="records") if len(violations) else []
    report = {"records_checked": int(len(persons)), "households_checked": int(len(frames["household"])) if "household" in frames else 0,
              "rules": [{k: r[k] for k in ("id", "version", "type", "level", "severity", "message", "source", "approval_status")} | {"active": bool(r.get("active"))} for r in rules["rules"]],
              "rule_set_version": rules["version"], "rule_set_sha256": rules["content_sha256"], "violations": counts,
              "records_with_violations": int(violations["source_observation_id"].nunique()) if len(violations) else 0,
              "household_note": household_note, "runtime_seconds": round(time.perf_counter() - started, 1)}
    (destination / "integrity_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (destination / "run_metadata.json").write_text(json.dumps({"run_id": run_id, "release": release, "observation": observation,
                                                               "design_period": meta["design_period"], "input_preprocessing_run_id": meta["run_id"],
                                                               "rule_set_version": rules["version"], "rule_set_sha256": rules["content_sha256"],
                                                               "rules_path": str(config.rules_path)}, indent=2), encoding="utf-8")
    return destination


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Run documented integrity rules over a prepared PLFS delivery (never changes data).")
    parser.add_argument("--prepared-persons", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    print(run(RunConfig(args.prepared_persons, args.output_root, args.rules, args.run_id)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
