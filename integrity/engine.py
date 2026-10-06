"""Generic integrity-rule engine.

Rules live in YAML (``integrity/rules/*.yaml``) and refer to survey
*concepts*; a per-release concept map resolves them to raw columns.  The
engine never changes a value: it lists violations with the rule, its
documentary source and the observed values.  The same engine validates a
single submitted record (online use) and a whole prepared delivery (batch).
"""
from __future__ import annotations

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

DEFAULT_RULES = Path(__file__).parent / "rules" / "plfs_person_rules.yaml"
RULE_TYPES = {"allowed_values", "range", "required_when", "value_when", "not_value_when", "unique"}


class IntegrityFailure(RuntimeError):
    pass


def load_rules(path: Path = DEFAULT_RULES) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    seen = set()
    for rule in document.get("rules", []):
        if rule.get("type") not in RULE_TYPES:
            raise IntegrityFailure(f"Rule {rule.get('id')} has unsupported type {rule.get('type')}")
        if rule["id"] in seen:
            raise IntegrityFailure(f"Duplicate rule id {rule['id']}")
        if not rule.get("source"):
            raise IntegrityFailure(f"Rule {rule['id']} must cite its documentary source")
        seen.add(rule["id"])
    return document


def concept_columns(release: str, observation: str) -> dict[str, str]:
    """Concept -> raw column for one release, from the existing documented contracts."""
    contract = next((c for c in CONTRACTS.values() if (c.release, c.observation) == (release, observation)), None)
    profile = SOURCE_PROFILES.get((release, observation))
    if contract is None or profile is None:
        raise IntegrityFailure(f"No documented contract for {release}/{observation}")
    mapping = {"record_key": "MoSPI_record_key", "person_serial": profile.person_serial_column, "age": contract.person_fields["age"],
               "cws_status": profile.context_columns["cws_status"]}
    for concept, target in (("earnings_salaried", "cws_earnings_salaried"), ("earnings_self_employed", "cws_earnings_self_employed"),
                            ("day7_hours", "day7_total_hours")):
        if target in profile.target_columns:
            mapping[concept] = profile.target_columns[target]
    return mapping


def _text(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("").str.strip()


def _condition(frame: pd.DataFrame, when: dict[str, Any]) -> pd.Series:
    field = frame[when["field"]]
    mask = pd.Series(True, index=frame.index)
    if "in" in when:
        mask &= _text(field).isin([str(v) for v in when["in"]])
    if "not_in" in when:
        mask &= ~_text(field).isin([str(v) for v in when["not_in"]]) & _text(field).ne("")
    numeric = pd.to_numeric(field, errors="coerce")
    if "min" in when:
        mask &= numeric.ge(when["min"])
    if "max" in when:
        mask &= numeric.le(when["max"])
    return mask.fillna(False)


def _matches(field: pd.Series, values: list[Any]) -> pd.Series:
    numeric_targets = [v for v in values if isinstance(v, (int, float))]
    text_match = _text(field).isin([str(v) for v in values])
    if numeric_targets:
        text_match |= pd.to_numeric(field, errors="coerce").isin(numeric_targets)
    return text_match


def evaluate(frame: pd.DataFrame, rules: dict[str, Any]) -> pd.DataFrame:
    """Return one row per (record, violated rule).  ``frame`` uses concept names."""
    out = []
    for rule in rules["rules"]:
        kind = rule["type"]
        needed = rule.get("fields") or [rule["field"]] + ([rule["when"]["field"]] if "when" in rule else [])
        if any(name not in frame for name in needed):
            continue  # concept not collected in this release: the rule is not applicable, never "passed"
        if kind == "unique":
            key = frame[rule["fields"]].astype("string").agg("|".join, axis=1)
            violated = key.duplicated(keep=False)
        else:
            field = frame[rule["field"]]
            present = _text(field).ne("")
            condition = _condition(frame, rule["when"]) if "when" in rule else pd.Series(True, index=frame.index)
            if kind == "allowed_values":
                violated = present & ~_text(field).isin([str(v) for v in rule["values"]])
            elif kind == "range":
                number = pd.to_numeric(field, errors="coerce")
                outside = pd.Series(False, index=frame.index)
                if "min" in rule:
                    outside |= number.lt(rule["min"]).fillna(False)
                if "max" in rule:
                    outside |= number.gt(rule["max"]).fillna(False)
                violated = condition & present & outside
            elif kind == "required_when":
                violated = condition & ~present
            elif kind == "value_when":
                violated = condition & present & ~_matches(field, rule["values"])
            else:  # not_value_when
                violated = condition & present & _matches(field, rule["values"])
        violated = pd.Series(violated, index=frame.index).fillna(False).astype(bool)
        if not violated.any():
            continue
        hits = frame.loc[violated]
        observed = hits[[c for c in needed if c in hits]].astype("string").to_dict(orient="records")
        out.append(pd.DataFrame({"source_observation_id": hits["source_observation_id"].to_numpy(), "rule_id": rule["id"],
                                 "severity": rule["severity"], "message": rule["message"], "source": rule["source"],
                                 "observed_values": [json.dumps(o, ensure_ascii=False) for o in observed]}))
    columns = ["source_observation_id", "rule_id", "severity", "message", "source", "observed_values"]
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=columns)


def concept_frame(raw: pd.DataFrame, release: str, observation: str) -> pd.DataFrame:
    mapping = concept_columns(release, observation)
    frame = pd.DataFrame({concept: raw[column] for concept, column in mapping.items() if column in raw})
    serial = _text(frame["person_serial"]) if "person_serial" in frame else pd.Series("", index=raw.index)
    fallback = _text(raw["MoSPI_source_row"]) if "MoSPI_source_row" in raw else serial
    frame["source_observation_id"] = _text(raw["MoSPI_record_key"]).str.cat(serial.mask(serial.eq(""), fallback), sep="|person=")
    return frame


@dataclass(frozen=True)
class RunConfig:
    prepared_persons: Path
    output_root: Path
    rules_path: Path = DEFAULT_RULES
    run_id: str | None = None


def run(config: RunConfig) -> Path:
    started = time.perf_counter()
    prepared = Path(config.prepared_persons)
    meta = json.loads((prepared.parent / "run_metadata.json").read_text(encoding="utf-8"))
    mapping = concept_columns(str(meta["release"]), str(meta["observation"]))
    import pyarrow.parquet as pq
    available = set(pq.ParquetFile(prepared).schema_arrow.names)
    raw = pd.read_parquet(prepared, columns=[c for c in {*mapping.values(), "MoSPI_source_row", "MoSPI_record_key"} if c in available])
    rules = load_rules(config.rules_path)
    violations = evaluate(concept_frame(raw, str(meta["release"]), str(meta["observation"])), rules)
    run_id = config.run_id or str(uuid.uuid4())
    destination = Path(config.output_root) / f"{meta['release']}_{meta['observation']}_{run_id}"
    destination.mkdir(parents=True, exist_ok=False)
    violations.to_parquet(destination / "integrity_violations.parquet", index=False)
    counts = violations.groupby(["rule_id", "severity"]).size().rename("records").reset_index().to_dict(orient="records") if len(violations) else []
    report = {"records_checked": int(len(raw)), "rules": [{k: r[k] for k in ("id", "type", "severity", "message", "source")} for r in rules["rules"]],
              "rule_set_version": rules.get("version"), "violations": counts, "records_with_violations": int(violations["source_observation_id"].nunique()) if len(violations) else 0,
              "runtime_seconds": round(time.perf_counter() - started, 1)}
    (destination / "integrity_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (destination / "run_metadata.json").write_text(json.dumps({"run_id": run_id, "release": meta["release"], "observation": meta["observation"],
                                                               "design_period": meta["design_period"], "input_preprocessing_run_id": meta["run_id"],
                                                               "rule_set_version": rules.get("version"), "rules_path": str(config.rules_path)}, indent=2), encoding="utf-8")
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
