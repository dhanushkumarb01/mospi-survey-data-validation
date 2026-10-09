"""Strict provenance-checked evidence fusion over persisted MoSPI outputs (v2.1, lanes).

The V2.0 construction (weighted mean of within-run ranks, max-of-ML, 0.995
override, x domain-share influence, fixed rank bands) was measured to lose
about half of the evidence of its own best components and to over-review the
smallest UTs (docs/10_10_IMPROVEMENT_PLAN.md §5.7).  It is replaced here, in
place, by separate evidence lanes (plan §8):

* Rule findings: approved hard rules at person and household level; always
  "Check now", never mixed into any score.
* Value checks: per-variable finite-sample tail probabilities from current
  peers (leave-one-out), earlier periods (out-of-sample) and the
  expected-value models trained on earlier periods (fusion.lanes); since
  v2.2 mechanisms that cannot attain the threshold are not counted (Tarone).
* Coding checks: smoothed conditional tail probability of the occupation code,
  with its own small share of the budget.
* Impact (change in the domain estimate in design SEs) orders cases within a
  tier only (fusion.impact).
* FSU patterns are group alerts with an FSU-level q-value; they never change a
  record's position.
* Isolation Forest and LOF are not read at all (research outputs only).

Stored V2.0 fusion runs remain readable by the API; fusion/legacy.py keeps the
old construction solely as evaluation baseline A0.
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

from pattern.engine import FSU_COMBINATION_METHOD, fsu_summary
from preprocessing.config import CONTRACTS
from survey_rules import WEIGHT_FIELDS, final_quarterly_weight, period_index
from survey_rules.schema import SchemaError, available_columns, read_parquet

from .config import VALUE_VARIABLES, FusionParameters
from .evidence_card import build_evidence_card
from .impact import domain_standard_errors, record_impact
from .lanes import expected_false_alerts_per_1000, record_value_evidence, variable_evidence
from .queue import build_queue, thresholds, value_threshold
from .review import initialise


class FusionFailure(RuntimeError):
    """Raised when source artifacts are incompatible or incomplete."""


@dataclass(frozen=True)
class RunConfig:
    prepared_persons: Path
    statistical_run: Path
    contextual_run: Path
    ml_run: Path
    output_root: Path
    pattern_run: Path | None = None
    run_id: str | None = None
    parameters: FusionParameters = FusionParameters()
    historical_run: Path | None = None
    integrity_run: Path | None = None


PATTERN_KEYS = ["release", "observation_type", "design_period", "visit", "month", "state", "sector", "stratum", "fsu"]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FusionFailure(f"Cannot read required metadata: {path}") from error


def _metadata_identity(metadata: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(metadata.get("release", "")),
        str(metadata.get("observation", metadata.get("observation_type", ""))),
        str(metadata.get("design_period", "")),
        str(metadata.get("input_preprocessing_run_id", metadata.get("preprocessing_run_id", ""))),
    )


def _preparation_identity(metadata: dict[str, Any]) -> tuple[str, str, str, str]:
    return (str(metadata.get("release", "")), str(metadata.get("observation", "")),
            str(metadata.get("design_period", "")), str(metadata.get("run_id", "")))


def _clean(values: pd.Series) -> pd.Series:
    return values.astype("string").fillna("").str.strip()


def _case_id(value: object) -> str:
    return "case_" + hashlib.sha256(str(value).encode()).hexdigest()[:20]


def _read(path: Path, columns: list[str], stage: str, optional: list[str] | None = None) -> pd.DataFrame:
    try:
        return read_parquet(path, columns=columns, optional=optional or [])
    except SchemaError as error:
        raise FusionFailure(f"The {stage} run at {path.parent} does not provide the evidence this fusion method needs "
                            f"(it probably predates the current method version; re-run that stage): {error}") from error


class FusionEngine:
    """Fuse immutable evidence artifacts into lanes and a workload-bounded queue."""

    def __init__(self, config: RunConfig) -> None:
        optional = lambda p: Path(p) if p else None  # noqa: E731
        self.config = RunConfig(
            prepared_persons=Path(config.prepared_persons), statistical_run=Path(config.statistical_run),
            contextual_run=Path(config.contextual_run), ml_run=Path(config.ml_run), output_root=Path(config.output_root),
            pattern_run=optional(config.pattern_run), run_id=config.run_id, parameters=config.parameters,
            historical_run=optional(config.historical_run), integrity_run=optional(config.integrity_run),
        )

    # ------------------------------------------------------------------ inputs

    def _validate(self) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        prep_meta = _read_json(self.config.prepared_persons.parent / "run_metadata.json")
        expected = _preparation_identity(prep_meta)
        if not all(expected):
            raise FusionFailure("Preparation metadata lacks release, observation, design period, or run ID.")
        if self.config.historical_run is None or self.config.integrity_run is None:
            raise FusionFailure("The lane design needs the historical and integrity runs; both are required.")
        artifacts = {"statistical": self.config.statistical_run, "contextual": self.config.contextual_run, "ml": self.config.ml_run,
                     "historical": self.config.historical_run, "integrity": self.config.integrity_run}
        if self.config.pattern_run:
            artifacts["pattern"] = self.config.pattern_run
        required = {"statistical": "statistical_evidence.parquet", "contextual": "contextual_evidence.parquet", "ml": "conditional_model_evidence.parquet",
                    "pattern": "pattern_evidence.parquet", "historical": "historical_record_evidence.parquet", "integrity": "integrity_violations.parquet"}
        source_meta: dict[str, dict[str, Any]] = {}
        for source, directory in artifacts.items():
            metadata = _read_json(directory / "run_metadata.json")
            observed = _metadata_identity(metadata)
            if observed != expected:
                raise FusionFailure(f"{source} provenance {observed} does not match preparation provenance {expected}; incompatible runs cannot be merged.")
            if not (directory / required[source]).is_file():
                raise FusionFailure(f"{source} run lacks required {required[source]}.")
            source_meta[source] = metadata
        return prep_meta, source_meta

    def _identity(self, prep_meta: dict[str, Any]) -> pd.DataFrame:
        release, observation, design, _ = _preparation_identity(prep_meta)
        contract = next((c for c in CONTRACTS.values() if c.release == release and c.observation == observation), None)
        if contract is None:
            raise FusionFailure(f"No documented preparation contract for {release}/{observation}.")
        serial = contract.person_fields[contract.person_serial]
        weights = WEIGHT_FIELDS.get((release, observation), {})
        required = ["MoSPI_record_key", "MoSPI_source_row", "MoSPI_release", "MoSPI_observation", "MoSPI_design_period", "MoSPI_visit",
                    "MoSPI_quarter", "MoSPI_state", "MoSPI_sector", "MoSPI_stratum", "MoSPI_fsu", serial, contract.person_fields["district"],
                    *[c for c in weights.values() if c]]
        if design == "post_2025":
            required.append("MoSPI_month")
        frame = _read(self.config.prepared_persons, list(dict.fromkeys(required)), "preparation")
        serial_text = _clean(frame[serial])
        frame["source_observation_id"] = _clean(frame["MoSPI_record_key"]) + "|person=" + serial_text.mask(serial_text.eq(""), _clean(frame["MoSPI_source_row"]))
        if frame.source_observation_id.duplicated().any():
            raise FusionFailure("Prepared persons source observation IDs are not unique; fusion cannot safely attach evidence.")
        nss = frame[weights["nss"]] if weights.get("nss") in frame else None
        nsc = frame[weights["nsc"]] if weights.get("nsc") in frame else None
        output = pd.DataFrame({
            "source_observation_id": frame["source_observation_id"], "household_key": _clean(frame["MoSPI_record_key"]),
            "release": _clean(frame["MoSPI_release"]), "observation_type": _clean(frame["MoSPI_observation"]),
            "design_period": _clean(frame["MoSPI_design_period"]), "visit": _clean(frame["MoSPI_visit"]),
            "month": _clean(frame["MoSPI_month"]) if "MoSPI_month" in frame else "", "quarter": _clean(frame["MoSPI_quarter"]),
            "state": _clean(frame["MoSPI_state"]), "sector": _clean(frame["MoSPI_sector"]), "stratum": _clean(frame["MoSPI_stratum"]),
            "fsu": _clean(frame["MoSPI_fsu"]), "district": _clean(frame[contract.person_fields["district"]]),
            "final_weight": final_quarterly_weight(release, frame[weights["mult"]], nss, nsc),
        })
        output["period_index"] = [period_index(release, q, m) for q, m in zip(output["quarter"], output["month"])]
        for column in ("release", "state", "sector"):
            if output[column].eq("").all():
                raise FusionFailure(f"Prepared persons have no {column} values; refusing to build a queue.")
        return output

    def _value_rows(self, use_model: bool) -> pd.DataFrame:
        stat = _read(self.config.statistical_run / "statistical_evidence.parquet",
                     ["source_observation_id", "target_variable", "statistical_assessability_status", "target_applicability", "observed_value",
                      "peer_median", "quantile_0_05", "quantile_0_25", "quantile_0_75", "quantile_0_95", "peer_group_size", "loo_reference_size",
                      "two_sided_tail_p", "tail_direction", "grouping_values", "grouping_dimensions"], "statistical")
        stat = stat.loc[stat["target_variable"].isin(VALUE_VARIABLES)]
        assessed = stat["statistical_assessability_status"].eq("ASSESSABLE")
        rows = stat.rename(columns={"observed_value": "observed_value", "two_sided_tail_p": "p_current", "tail_direction": "current_direction",
                                    "quantile_0_05": "current_q05", "quantile_0_25": "current_q25", "quantile_0_75": "current_q75",
                                    "quantile_0_95": "current_q95", "loo_reference_size": "current_n"})
        for column in ("p_current", "peer_median", "current_q05", "current_q25", "current_q75", "current_q95", "current_n"):
            rows[column] = pd.to_numeric(rows[column], errors="coerce").where(assessed)
        rows["applicable"] = rows["target_applicability"].eq("APPLICABLE")
        hist = _read(self.config.historical_run / "historical_record_evidence.parquet",
                     ["source_observation_id", "target_variable", "assessability_status", "two_sided_tail_p", "tail_direction", "reference_median",
                      "quantile_0_05", "quantile_0_95", "reference_size", "reference_periods", "period_label", "same_season_two_sided_tail_p",
                      "same_season_median", "same_season_period"], "historical")
        hist = hist.loc[hist["assessability_status"].eq("ASSESSABLE")].rename(columns={
            "two_sided_tail_p": "p_history", "tail_direction": "history_direction", "reference_median": "history_median", "quantile_0_05": "history_q05",
            "quantile_0_95": "history_q95", "reference_size": "history_n", "same_season_two_sided_tail_p": "p_same_season"}).drop(columns="assessability_status")
        rows = rows.merge(hist, on=["source_observation_id", "target_variable"], how="left", validate="one_to_one")
        if use_model:
            model = _read(self.config.ml_run / "conditional_model_evidence.parquet",
                          ["source_observation_id", "target", "assessability_status", "model_tail_p", "predicted_value", "usual_range_low",
                           "usual_range_high", "training_scheme", "training_periods"], "ML (conditional models)")
            model = model.loc[model["assessability_status"].eq("ASSESSABLE")].rename(columns={
                "target": "target_variable", "model_tail_p": "p_model", "predicted_value": "model_estimate", "usual_range_low": "model_low",
                "usual_range_high": "model_high", "training_scheme": "model_training_scheme", "training_periods": "model_training_periods"}).drop(columns="assessability_status")
            rows = rows.merge(model, on=["source_observation_id", "target_variable"], how="left", validate="one_to_one")
        else:
            rows["p_model"] = np.nan
        # Evidence only for applicable values (placeholders never count).
        for column in ("p_current", "p_history", "p_model"):
            rows[column] = pd.to_numeric(rows[column], errors="coerce").where(rows["applicable"])
        return rows.drop(columns=["statistical_assessability_status", "target_applicability"])

    def _coding(self) -> pd.DataFrame:
        data = _read(self.config.contextual_run / "contextual_evidence.parquet",
                     ["source_observation_id", "contextual_assessability_status", "coding_tail_p", "observed_value", "category_count", "reference_count"],
                     "contextual")
        usable = data["contextual_assessability_status"].eq("ASSESSABLE")
        return pd.DataFrame({"source_observation_id": data["source_observation_id"],
                             "coding_p": pd.to_numeric(data["coding_tail_p"], errors="coerce").where(usable),
                             "coding_code": data["observed_value"].where(usable),
                             "coding_count": pd.to_numeric(data["category_count"], errors="coerce").where(usable),
                             "coding_reference": pd.to_numeric(data["reference_count"], errors="coerce").where(usable)})

    def _rules(self) -> pd.DataFrame:
        data = read_parquet(self.config.integrity_run / "integrity_violations.parquet")
        if "level" not in data:
            data["level"] = "person"
        return data

    # ------------------------------------------------------------------ run

    def run(self) -> Path:
        started = time.perf_counter()
        p = self.config.parameters
        prep_meta, source_meta = self._validate()
        base = self._identity(prep_meta)
        known = set(base.source_observation_id)

        rows = self._value_rows(p.use_conditional_model)
        # The value threshold depends only on counts (records, value-assessable records), so it is known
        # before the evidence is combined; the discrete-test correction needs it (fusion.lanes).
        has_mechanism = rows[["p_current", "p_history", "p_model"]].notna().any(axis=1)
        limit = value_threshold(p, len(base), int(rows.loc[has_mechanism, "source_observation_id"].nunique()))
        variables = variable_evidence(rows, limit if p.discrete_test_correction else None)
        unknown = set(variables.source_observation_id) - known
        if unknown:
            raise FusionFailure(f"Value evidence cannot be mapped to the supplied prepared persons run ({len(unknown)} unknown source IDs).")
        value = record_value_evidence(variables)

        # Impact of each applicable value on its domain mean, in design SEs.
        geo = base[["source_observation_id", "final_weight", "release", "period_index", "state", "sector", "stratum", "fsu"]]
        impact_input = variables.loc[variables["applicable"] & variables["observed_value"].notna()].merge(geo, on="source_observation_id", how="left")
        impact_input["value"] = pd.to_numeric(impact_input["observed_value"], errors="coerce")
        impact_input["expected_value"] = impact_input["peer_median"].fillna(impact_input["history_median"])
        if "model_estimate" in impact_input:
            impact_input["expected_value"] = impact_input["expected_value"].fillna(impact_input["model_estimate"])
        impact_input["domain"] = impact_input["release"] + "|" + impact_input["period_index"].astype(str) + "|" + impact_input["state"] + "|" + impact_input["sector"]
        impact_input["stratum_key"] = impact_input["state"] + "|" + impact_input["sector"] + "|" + impact_input["stratum"]
        impact_input["psu_key"] = impact_input["stratum_key"] + "|" + impact_input["fsu"]
        domains = domain_standard_errors(impact_input)
        impacts = record_impact(impact_input, domains) if len(domains) else impact_input.assign(impact_se=np.nan, estimate_change=np.nan, domain_mean=np.nan, effective_se=np.nan)
        variables = variables.merge(impacts[["source_observation_id", "target_variable", "expected_value", "estimate_change", "domain_mean", "effective_se", "impact_se"]],
                                    on=["source_observation_id", "target_variable"], how="left")

        cases = base.merge(value, on="source_observation_id", how="left").merge(self._coding(), on="source_observation_id", how="left")
        lead_impact = variables[["source_observation_id", "target_variable", "impact_se", "estimate_change", "effective_se"]].rename(
            columns={"target_variable": "value_lead_variable", "estimate_change": "impact_estimate_change", "effective_se": "impact_domain_se"})
        cases = cases.merge(lead_impact, on=["source_observation_id", "value_lead_variable"], how="left")
        lead_rows = variables.set_index(["source_observation_id", "target_variable"])
        keys = pd.MultiIndex.from_arrays([cases["source_observation_id"], cases["value_lead_variable"]])
        for column, name in (("strongest_mechanism", "value_lead_mechanism"), ("current_direction", "value_lead_direction"),
                             ("observed_value", "value_lead_observed"), ("peer_median", "value_lead_typical")):
            cases[name] = lead_rows[column].reindex(keys).to_numpy() if column in lead_rows else np.nan
        cases["value_status"] = np.where(cases["value_p"].notna(), "ASSESSABLE", "NOT_ASSESSABLE")
        cases["coding_status"] = np.where(cases["coding_p"].notna(), "ASSESSABLE", "NOT_ASSESSABLE")
        cases["case_level"] = "PERSON"

        # Rule findings: person level onto persons; household level as household cases.
        rules = self._rules()
        person_rules = rules.loc[rules["level"].eq("person")]
        if len(person_rules):
            grouped = person_rules.groupby("source_observation_id")
            counts = pd.DataFrame({"rule_error_count": grouped["severity"].apply(lambda s: int(s.eq("error").sum())),
                                   "rule_warning_count": grouped["severity"].apply(lambda s: int(s.eq("warning").sum())),
                                   "rule_ids": grouped["rule_id"].apply(lambda s: ",".join(sorted(set(s))))}).reset_index()
            cases = cases.merge(counts, on="source_observation_id", how="left")
        household_rules = rules.loc[rules["level"].eq("household")]
        if len(household_rules):
            household_rules = household_rules.assign(household_key=household_rules["source_observation_id"].str.removesuffix("|household"))
            identity = base.drop_duplicates("household_key").set_index("household_key")
            grouped = household_rules.groupby("household_key")
            household_cases = identity.loc[identity.index.intersection(grouped.size().index), ["release", "observation_type", "design_period", "visit", "month",
                                                                                                  "quarter", "state", "sector", "stratum", "fsu", "district", "period_index"]].reset_index()
            household_cases["source_observation_id"] = household_cases["household_key"] + "|household"
            household_cases["case_level"] = "HOUSEHOLD"
            household_cases["rule_error_count"] = household_cases["household_key"].map(grouped["severity"].apply(lambda s: int(s.eq("error").sum())))
            household_cases["rule_warning_count"] = household_cases["household_key"].map(grouped["severity"].apply(lambda s: int(s.eq("warning").sum())))
            household_cases["rule_ids"] = household_cases["household_key"].map(grouped["rule_id"].apply(lambda s: ",".join(sorted(set(s)))))
            household_cases["value_status"] = "NOT_APPLICABLE"
            household_cases["coding_status"] = "NOT_APPLICABLE"
            cases = pd.concat([cases, household_cases], ignore_index=True)
        for column in ("rule_error_count", "rule_warning_count"):
            values = cases[column] if column in cases else pd.Series(0, index=cases.index)
            cases[column] = pd.to_numeric(values, errors="coerce").fillna(0).astype(int)
        if "rule_ids" not in cases:
            cases["rule_ids"] = None
        cases["rule_violation"] = cases["rule_error_count"].gt(0)
        cases["rules_status"] = "CHECKED"

        # FSU group context (never part of a record's position).
        groups_source = None
        if self.config.pattern_run:
            summary_path = self.config.pattern_run / "fsu_summary.parquet"
            stored = read_parquet(summary_path) if summary_path.is_file() else None
            if stored is not None and "method" in stored and stored["method"].astype(str).eq(FSU_COMBINATION_METHOD).all():
                groups_source = stored
            else:  # pattern run made with an earlier FSU combination: combine its stored checks with the current one
                groups_source = fsu_summary(read_parquet(self.config.pattern_run / "pattern_evidence.parquet"), p.group_alert_q)
            context = groups_source[[*PATTERN_KEYS, "fsu_q_value", "notable", "strongest_statement", "fieldwork_signal"]].rename(
                columns={"notable": "fsu_notable", "strongest_statement": "fsu_statement", "fieldwork_signal": "fsu_fieldwork_signal"})
            for column in PATTERN_KEYS:
                context[column] = _clean(context[column])
            cases = cases.merge(context.drop_duplicates(PATTERN_KEYS), on=PATTERN_KEYS, how="left")
            cases["pattern_status"] = np.where(cases["fsu_q_value"].notna(), "ASSESSABLE", "NOT_ASSESSABLE")
        else:
            cases["fsu_q_value"] = np.nan; cases["fsu_notable"] = False; cases["fsu_statement"] = None; cases["fsu_fieldwork_signal"] = False
            cases["pattern_status"] = "NOT_AVAILABLE"
        cases["fsu_notable"] = cases["fsu_notable"].fillna(False).astype(bool)

        cases["case_id"] = cases["source_observation_id"].map(_case_id)
        cases = build_queue(cases, p)
        queue_summary = dict(cases.attrs.get("queue_summary", {}))
        if p.discrete_test_correction and not np.isclose(queue_summary.get("value_threshold", np.nan), limit, rtol=0, atol=1e-15):
            raise FusionFailure(f"Value threshold used for the discrete-test correction ({limit}) differs from the queue's ({queue_summary.get('value_threshold')}).")
        queue_summary["discrete_test_correction"] = bool(p.discrete_test_correction)
        provenance = {"preprocessing_run_id": prep_meta["run_id"],
                      **{f"{name}_run_id": source_meta.get(name, {}).get("run_id") for name in ("statistical", "contextual", "ml", "pattern", "historical", "integrity")},
                      "fusion_version": p.fusion_version, "calibration_version": p.calibration_version, "impact_version": p.impact_version}
        cases["provenance_json"] = json.dumps(provenance, sort_keys=True)
        groups = self._groups(cases, groups_source)

        run_id = self.config.run_id or str(uuid.uuid4())
        destination = self.config.output_root / f"{prep_meta['release']}_{prep_meta['observation']}_{run_id}"
        destination.mkdir(parents=True, exist_ok=False)
        cases.sort_values("queue_position", kind="mergesort").to_parquet(destination / "fused_cases.parquet", index=False)
        variables["case_id"] = variables["source_observation_id"].map(_case_id)
        variables.to_parquet(destination / "value_evidence.parquet", index=False)
        if len(domains):
            domains.to_parquet(destination / "impact_domains.parquet", index=False)
        groups.to_parquet(destination / "group_priorities.parquet", index=False)
        in_queue = cases.loc[cases["tier"].isin(["A", "B"])].nsmallest(p.evidence_card_capacity, "queue_position")
        evidence_cards = pd.DataFrame({"case_id": in_queue["case_id"], "evidence_card_json": [json.dumps(build_evidence_card(row), default=str, sort_keys=True)
                                                                                             for _, row in in_queue.iterrows()]})
        evidence_cards.to_parquet(destination / "evidence_cards.parquet", index=False)
        initialise(destination / "review_audit.sqlite")

        summary = self._report(cases, groups, queue_summary, time.perf_counter() - started)
        summary["burden"]["calibration_by_mechanism"] = calibration_by_mechanism(variables, queue_summary["value_threshold"])
        metadata = {"run_id": run_id, "release": prep_meta["release"], "observation": prep_meta["observation"], "design_period": prep_meta["design_period"],
                    "input_preprocessing_run_id": prep_meta["run_id"], "source_runs": {name: value.get("run_id") for name, value in source_meta.items()},
                    "fusion_version": p.fusion_version, "parameters": dict(p.__dict__), "queue": queue_summary,
                    "output_files": ["fused_cases.parquet", "value_evidence.parquet", "impact_domains.parquet", "evidence_cards.parquet",
                                     "group_priorities.parquet", "fusion_report.json", "fusion_report.md", "review_audit.sqlite", "run_metadata.json"]}
        (destination / "fusion_report.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=float), encoding="utf-8")
        (destination / "run_metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True, default=float), encoding="utf-8")
        (destination / "fusion_report.md").write_text(_markdown_report(metadata, summary), encoding="utf-8")
        return destination

    def _report(self, cases: pd.DataFrame, groups: pd.DataFrame, queue_summary: dict[str, Any], runtime: float) -> dict[str, Any]:
        p = self.config.parameters
        persons = cases.loc[cases["case_level"].eq("PERSON")]
        limits = {"value": queue_summary.get("value_threshold", thresholds(p)["value"]), "coding": queue_summary.get("coding_threshold", thresholds(p)["coding"])}
        value_share = float(persons["value_p"].notna().mean()) if len(persons) else 0.0
        coding_share = float(persons["coding_p"].notna().mean()) if len(persons) else 0.0
        observed_value_rate = float(persons["value_p"].le(limits["value"]).mean() * 1000) if len(persons) else 0.0
        nominal_value_rate = expected_false_alerts_per_1000(limits["value"], value_share)
        tier_a = persons["tier"].eq("A")
        by_state = persons.groupby("state").agg(records=("case_id", "size"), tier_a=("tier", lambda t: int(t.eq("A").sum())))
        by_state = by_state.loc[by_state["records"].ge(1000)]
        rates = by_state["tier_a"] / by_state["records"] * 1000
        return {
            "records_processed": int(len(persons)), "household_cases": int(cases["case_level"].eq("HOUSEHOLD").sum()),
            "tier_counts": {str(k): int(v) for k, v in cases["tier"].value_counts().items()},
            "lane_counts_check_now": {str(k): int(v) for k, v in cases.loc[cases["tier"].eq("A"), "lane"].value_counts().items()},
            "coverage": {"value_check_assessable_share": value_share, "coding_check_assessable_share": coding_share,
                         "any_non_rule_check_share": float((persons["value_p"].notna() | persons["coding_p"].notna()).mean()) if len(persons) else 0.0,
                         "value_variables_assessed_distribution": {str(k): int(v) for k, v in persons["value_variables_assessed"].value_counts().sort_index().items()}},
            "queue": queue_summary,
            # Real-data burden check (plan §12.6): released files are post-scrutiny, so the observed rate of
            # value checks at or below the threshold should be near the nominal rate if the tail probabilities
            # are calibrated.  A large excess points at calibration, not at the data being full of errors.
            "burden": {"value_threshold": limits["value"], "nominal_value_alerts_per_1000_if_all_clean": nominal_value_rate,
                       "observed_value_alerts_per_1000": observed_value_rate,
                       "observed_over_nominal": observed_value_rate / nominal_value_rate if nominal_value_rate else None,
                       "check_now_per_1000_by_state": {str(k): float(v) for k, v in rates.items()},
                       "check_now_state_rate_max_over_median": float(rates.max() / rates.median()) if len(rates) and rates.median() > 0 else None,
                       "note": "States/UTs with at least 1,000 records; not validated against confirmed errors."},
            "rule_findings": {"persons_with_hard_rule": int(persons["rule_error_count"].gt(0).sum()), "households_with_hard_rule": int((cases["case_level"].eq("HOUSEHOLD") & cases["rule_error_count"].gt(0)).sum())},
            "group_alerts": {str(k): int(v) for k, v in groups["group_priority_band"].value_counts().items()} if len(groups) else {},
            "impact_available": int(persons["impact_se"].notna().sum()),
            "check_now_cases": int(tier_a.sum()),
            "runtime_seconds": round(runtime, 3),
        }

    def _groups(self, cases: pd.DataFrame, summary: pd.DataFrame | None) -> pd.DataFrame:
        persons = cases.loc[cases["case_level"].eq("PERSON")]
        counts = persons.groupby(PATTERN_KEYS, dropna=False, sort=False).agg(
            records=("case_id", "size"), check_now_cases=("tier", lambda t: int(t.eq("A").sum())),
            check_if_time_cases=("tier", lambda t: int(t.eq("B").sum()))).reset_index()
        if summary is None or summary.empty:
            counts["group_priority_band"] = "NOT_ASSESSABLE"; counts["group_priority_score"] = np.nan; counts["pattern_min_q"] = np.nan
            return counts
        table = summary.copy()
        for column in PATTERN_KEYS:
            table[column] = _clean(table[column])
        group = counts.merge(table, on=PATTERN_KEYS, how="left")
        q = pd.to_numeric(group["fsu_q_value"], errors="coerce")
        p = self.config.parameters
        group["pattern_min_q"] = q   # kept name for the API: now the FSU-level (combined) q-value
        group["group_priority_score"] = -np.log10(q.clip(lower=1e-300))
        group["group_priority_band"] = np.select([q.isna(), q.lt(p.group_strong_q), q.lt(p.group_alert_q)], ["NOT_ASSESSABLE", "HIGH", "MEDIUM"], "LOW")
        group["notable_checks"] = group.get("notable_checks", 0)
        group["pattern_checks"] = group.get("checks", 0)
        return group.sort_values(["group_priority_score", "fsu"], ascending=[False, True], na_position="last").reset_index(drop=True)


def calibration_by_mechanism(variables: pd.DataFrame, threshold: float) -> dict[str, Any]:
    """Observed share at or below the threshold divided by the threshold, per evidence mechanism (1.0 = calibrated).

    On released (post-scrutiny) data a value well below 1 means the mechanism is conservative (for example a
    small reference whose smallest attainable tail probability is above the threshold); well above 1 means it
    flags more often than its nominal rate.  Diagnostic only; not a validation.
    """
    result: dict[str, Any] = {"threshold": float(threshold)}
    for column in ("p_current", "p_history", "p_model", "p_reference", "p_variable"):
        values = pd.to_numeric(variables.get(column), errors="coerce").dropna() if column in variables else pd.Series(dtype=float)
        result[column] = {"rows": int(len(values)), "observed_over_nominal": float((values <= threshold).mean() / threshold) if len(values) else None}
    if "reference_testable" in variables:
        has_reference = variables["p_reference"].notna()
        result["reference_can_attain_threshold_share"] = float(variables.loc[has_reference, "reference_testable"].mean()) if has_reference.any() else None
    return result


def _markdown_report(metadata: dict[str, Any], summary: dict[str, Any]) -> str:
    tiers = "\n".join(f"| {k} | {v:,} |" for k, v in summary["tier_counts"].items())
    burden = summary["burden"]
    return f"""# MoSPI fusion report ({metadata['fusion_version']})

- Fusion run: `{metadata['run_id']}`; release / observation: `{metadata['release']}` / `{metadata['observation']}`
- Preparation run: `{metadata['input_preprocessing_run_id']}`
- Review budget: {metadata['queue'].get('review_budget_share')} of records = {metadata['queue'].get('budget_cases'):,} cases (default until HSD supplies capacity)

## Queue

| Tier | Cases |
|---|---:|
{tiers}

## Real-data burden check (not a validation)

- Value-check threshold: {burden['value_threshold']}
- Nominal alerts per 1,000 records if every record were clean and the tail probabilities calibrated: {burden['nominal_value_alerts_per_1000_if_all_clean']:.2f}
- Observed on this (released, post-scrutiny) batch: {burden['observed_value_alerts_per_1000']:.2f}
- Max / median State "Check now" rate: {burden['check_now_state_rate_max_over_median']}
- Discrete-test (Tarone) correction: {metadata['queue'].get('discrete_test_correction')}

## Interpretation boundary

Evidence is a tail probability ("this is rare for comparable people"), never a probability that an answer is wrong. Rule findings
are definite inconsistencies in the recorded answers. Impact orders cases within a tier and never changes which tier a case is in.
FSU alerts describe a group and never move a record. Isolation Forest and LOF are research outputs and are not read. Thresholds,
budget and lane shares are provisional engineering settings; the evaluation stage (docs/10_10_IMPROVEMENT_PLAN.md §12) has not been run.
"""
