"""Strict provenance-checked V2 evidence fusion over persisted MoSPI outputs.

V2 changes (each fixes an audited defect; see fusion/DESIGN.md):

* record risk uses record-level evidence only (statistical, contextual, ML,
  historical); FSU Pattern evidence is group context and never raises an
  individual record's risk or triggers its override (audit H3);
* statistical evidence is taken from the statistical layer's own
  assessability, which excludes questionnaire placeholders (audit C1/M4);
* influence is a per-variable share of a weighted domain total (audit H2);
* documented integrity-rule violations are reported as deterministic findings;
* FSU group alerts are ordered by Benjamini-Hochberg q-values.
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
import pyarrow.parquet as pq

from preprocessing.config import CONTRACTS
from survey_rules import APPLICABLE, WEIGHT_FIELDS, final_quarterly_weight, period_index

from .calibration import percentile_midrank
from .config import RECORD_SOURCES, FusionParameters
from .evidence_card import build_evidence_card
from .influence import calculate_influence, domain_shares
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
    """Preparation metadata owns its run ID; downstream metadata references it."""
    return (
        str(metadata.get("release", "")), str(metadata.get("observation", "")),
        str(metadata.get("design_period", "")), str(metadata.get("run_id", "")),
    )


class FusionEngine:
    """Fuse immutable evidence artifacts without recomputing source models."""

    def __init__(self, config: RunConfig) -> None:
        optional = lambda p: Path(p) if p else None  # noqa: E731
        self.config = RunConfig(
            prepared_persons=Path(config.prepared_persons), statistical_run=Path(config.statistical_run),
            contextual_run=Path(config.contextual_run), ml_run=Path(config.ml_run), output_root=Path(config.output_root),
            pattern_run=optional(config.pattern_run), run_id=config.run_id, parameters=config.parameters,
            historical_run=optional(config.historical_run), integrity_run=optional(config.integrity_run),
        )

    def _validate(self) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        prep_meta = _read_json(self.config.prepared_persons.parent / "run_metadata.json")
        expected = _preparation_identity(prep_meta)
        if not all(expected):
            raise FusionFailure("Preparation metadata lacks release, observation, design period, or run ID.")
        artifacts = {"statistical": self.config.statistical_run, "contextual": self.config.contextual_run, "ml": self.config.ml_run}
        for name in ("pattern", "historical", "integrity"):
            if getattr(self.config, f"{name}_run"):
                artifacts[name] = getattr(self.config, f"{name}_run")
        source_meta: dict[str, dict[str, Any]] = {}
        for source, directory in artifacts.items():
            metadata = _read_json(directory / "run_metadata.json")
            observed = _metadata_identity(metadata)
            if observed != expected:
                raise FusionFailure(f"{source} provenance {observed} does not match preparation provenance {expected}; incompatible runs cannot be merged.")
            source_meta[source] = metadata
        required = {"statistical": "statistical_evidence.parquet", "contextual": "contextual_evidence.parquet", "ml": "isolation_forest_evidence.parquet",
                    "pattern": "pattern_evidence.parquet", "historical": "historical_record_evidence.parquet", "integrity": "integrity_violations.parquet"}
        for source, directory in artifacts.items():
            if not (directory / required[source]).is_file():
                raise FusionFailure(f"{source} run lacks required {required[source]}.")
        return prep_meta, source_meta

    @staticmethod
    def _statistical(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
        columns = ["source_observation_id", "target_variable", "statistical_assessability_status", "statistical_assessability_reason",
                   "target_applicability", "percentile_position", "observed_value", "peer_median", "peer_group_id", "peer_group_size",
                   "distribution_position", "robust_deviation", "grouping_values"]
        data = pd.read_parquet(path, columns=columns)
        numeric = pd.to_numeric(data.percentile_position, errors="coerce")
        data["source_score"] = (numeric - .5).abs() * 2
        usable = data.statistical_assessability_status.eq("ASSESSABLE") & data.source_score.notna() & np.isfinite(data.source_score)
        assessments = data.loc[usable].groupby("source_observation_id", sort=False).source_score.max().rename("statistical_raw_score")
        ids = data[["source_observation_id"]].drop_duplicates().set_index("source_observation_id")
        statements = data.loc[usable].sort_values("source_score", ascending=False).drop_duplicates("source_observation_id")
        summary = ids.join(assessments).reset_index()
        summary["statistical_details_json"] = "[]"
        summary = summary.merge(statements[["source_observation_id", "target_variable", "peer_group_size", "percentile_position"]], on="source_observation_id", how="left")
        summary["statistical_status"] = np.where(summary.statistical_raw_score.notna(), "ASSESSABLE", "NOT_ASSESSABLE")
        summary["statistical_reason"] = np.where(summary.statistical_raw_score.notna(), None, "NO_ASSESSABLE_APPLICABLE_STATISTICAL_TARGET")
        summary["statistical_statement"] = np.where(summary.statistical_raw_score.notna(),
                                                    "Stored peer-conditioned numerical evidence relative to its reference population.",
                                                    "No applicable value could be compared with similar records.")
        # Per-target rows for the influence calculation (placeholders excluded via applicability).
        targets = data[["source_observation_id", "target_variable", "observed_value", "peer_median", "target_applicability"]].copy()
        targets["peer_median"] = targets["peer_median"].where(usable)
        targets["applicable"] = targets["target_applicability"].eq(APPLICABLE)
        return summary, targets

    @staticmethod
    def _contextual(path: Path) -> pd.DataFrame:
        columns = ["source_observation_id", "assessability_status", "not_assessable_reason", "surprisal", "frequency_statement"]
        data = pd.read_parquet(path, columns=columns)
        data["contextual_raw_score"] = pd.to_numeric(data.surprisal, errors="coerce").replace([np.inf, -np.inf], np.nan)
        data["contextual_status"] = np.where(data.assessability_status.eq("ASSESSABLE") & data.contextual_raw_score.notna(), "ASSESSABLE", "NOT_ASSESSABLE")
        data["contextual_reason"] = np.where(data.contextual_status.eq("ASSESSABLE"), None, data.not_assessable_reason.fillna("NO_ASSESSABLE_CONTEXTUAL_EVIDENCE"))
        data["contextual_statement"] = data.frequency_statement.fillna("No assessable contextual response frequency is available.")
        data["contextual_details_json"] = "[]"
        return data.drop(columns=["assessability_status", "not_assessable_reason", "surprisal", "frequency_statement"])

    @staticmethod
    def _ml(directory: Path) -> pd.DataFrame:
        pieces: list[pd.DataFrame] = []
        for filename in ("isolation_forest_evidence.parquet", "lof_evidence.parquet", "conditional_model_evidence.parquet", "similarity_evidence.parquet"):
            path = directory / filename
            if not path.is_file():
                continue
            data = pd.read_parquet(path, columns=[c for c in ("source_observation_id", "method", "assessability_status", "evidence_rank", "evidence_statement")
                                                  if c in pq.ParquetFile(path).schema_arrow.names])
            data["method_rank"] = pd.to_numeric(data.get("evidence_rank"), errors="coerce").replace([np.inf, -np.inf], np.nan)
            pieces.append(data)
        if not pieces:
            raise FusionFailure("ML run contains no readable evidence tables.")
        data = pd.concat(pieces, ignore_index=True)
        usable = data.assessability_status.eq("ASSESSABLE") & data.method_rank.notna()
        raw = data.loc[usable].groupby("source_observation_id", sort=False).method_rank.max().rename("ml_raw_score")
        ids = data[["source_observation_id"]].drop_duplicates().set_index("source_observation_id")
        statement = data.loc[usable].sort_values("method_rank", ascending=False).drop_duplicates("source_observation_id")
        summary = ids.join(raw).reset_index().merge(statement[["source_observation_id", "evidence_statement"]], on="source_observation_id", how="left")
        summary["ml_details_json"] = "[]"
        summary["ml_status"] = np.where(summary.ml_raw_score.notna(), "ASSESSABLE", "NOT_ASSESSABLE")
        summary["ml_reason"] = np.where(summary.ml_raw_score.notna(), None, "NO_NUMERIC_ASSESSABLE_ML_EVIDENCE")
        summary["ml_statement"] = summary.evidence_statement.fillna("No numeric assessable ML evidence is available.")
        return summary.drop(columns=["evidence_statement"])

    @staticmethod
    def _historical(directory: Path) -> pd.DataFrame:
        data = pd.read_parquet(directory / "historical_record_evidence.parquet",
                               columns=["source_observation_id", "target_variable", "assessability_status", "historical_score", "reference_periods"])
        usable = data.assessability_status.eq("ASSESSABLE") & data.historical_score.notna()
        raw = data.loc[usable].groupby("source_observation_id", sort=False).historical_score.max().rename("historical_raw_score")
        ids = data[["source_observation_id"]].drop_duplicates().set_index("source_observation_id")
        summary = ids.join(raw).reset_index()
        summary["historical_status"] = np.where(summary.historical_raw_score.notna(), "ASSESSABLE", "NOT_ASSESSABLE")
        summary["historical_reason"] = np.where(summary.historical_raw_score.notna(), None, "NO_COMPARABLE_EARLIER_PERIOD_EVIDENCE")
        summary["historical_statement"] = np.where(summary.historical_raw_score.notna(), "Compared with similar people interviewed in earlier periods.",
                                                   "No comparable earlier-period information is available.")
        summary["historical_details_json"] = "[]"
        return summary

    @staticmethod
    def _integrity(directory: Path) -> pd.DataFrame:
        data = pd.read_parquet(directory / "integrity_violations.parquet")
        if data.empty:
            return pd.DataFrame(columns=["source_observation_id", "rule_violation_count", "rule_error_count", "rule_ids"])
        grouped = data.groupby("source_observation_id")
        return pd.DataFrame({"rule_violation_count": grouped.size(), "rule_error_count": grouped.severity.apply(lambda s: int(s.eq("error").sum())),
                             "rule_ids": grouped.rule_id.apply(lambda s: ",".join(sorted(set(s))))}).reset_index()

    @staticmethod
    def _pattern(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
        columns = [*PATTERN_KEYS, "pattern_component", "variable", "evidence_rank", "assessability_status", "evidence_statement", "q_value"]
        available = pq.ParquetFile(path).schema_arrow.names
        data = pd.read_parquet(path, columns=[c for c in columns if c in available])
        if "q_value" not in data:
            data["q_value"] = np.nan
        usable = data.assessability_status.eq("ASSESSABLE") & pd.to_numeric(data.evidence_rank, errors="coerce").notna()
        u = data.loc[usable].copy()
        u["q_value"] = pd.to_numeric(u.q_value, errors="coerce")
        grouped = u.groupby(PATTERN_KEYS, sort=False, dropna=False)
        summary = pd.DataFrame({
            "pattern_raw_score": grouped.evidence_rank.max(), "pattern_min_q": grouped.q_value.min(),
            "pattern_notable_checks": grouped.q_value.apply(lambda q: int(q.lt(0.05).sum())), "pattern_checks": grouped.size(),
        }).reset_index()
        statement = u.sort_values(["q_value", "evidence_rank"], ascending=[True, False]).drop_duplicates(PATTERN_KEYS)[PATTERN_KEYS + ["evidence_statement"]]
        summary = summary.merge(statement, on=PATTERN_KEYS, how="left").rename(columns={"evidence_statement": "pattern_statement"})
        keys = data[PATTERN_KEYS].drop_duplicates()
        summary = keys.merge(summary, on=PATTERN_KEYS, how="left")
        summary["pattern_status"] = np.where(summary.pattern_raw_score.notna(), "ASSESSABLE", "NOT_ASSESSABLE")
        summary["pattern_reason"] = np.where(summary.pattern_raw_score.notna(), None, "NO_ASSESSABLE_GROUP_PATTERN_EVIDENCE")
        summary["pattern_statement"] = summary.pattern_statement.fillna("No assessable FSU-level pattern evidence is available.")
        summary["pattern_details_json"] = "[]"
        return summary, data

    def _prepared_identity(self, prep_meta: dict[str, Any]) -> pd.DataFrame:
        release, observation, _, _ = _metadata_identity(prep_meta)
        contract = next((c for c in CONTRACTS.values() if c.release == release and c.observation == observation), None)
        if contract is None:
            raise FusionFailure(f"No documented preparation contract for {release}/{observation}.")
        serial = contract.person_fields[contract.person_serial]
        weights = WEIGHT_FIELDS.get((release, observation), {})
        requested = ["MoSPI_record_key", "MoSPI_source_row", "MoSPI_release", "MoSPI_observation", "MoSPI_design_period", "MoSPI_visit", "MoSPI_month",
                     "MoSPI_quarter", "MoSPI_state", "MoSPI_sector", "MoSPI_stratum", "MoSPI_fsu", "MoSPI_weight", serial,
                     *[c for c in weights.values() if c]]
        schema = pq.ParquetFile(self.config.prepared_persons).schema_arrow.names
        frame = pd.read_parquet(self.config.prepared_persons, columns=[column for column in dict.fromkeys(requested) if column in schema])
        if serial not in frame or "MoSPI_record_key" not in frame:
            raise FusionFailure("Prepared persons file lacks the documented source identity fields.")
        for column in ("MoSPI_month", "MoSPI_quarter", "MoSPI_state", "MoSPI_sector", "MoSPI_stratum", "MoSPI_fsu"):
            if column not in frame:
                frame[column] = ""
        serial_text = frame[serial].astype("string").fillna("").str.strip()
        fallback = frame["MoSPI_source_row"].astype("string") if "MoSPI_source_row" in frame else serial_text
        frame["source_observation_id"] = frame.MoSPI_record_key.astype(str) + "|person=" + serial_text.mask(serial_text.eq(""), fallback).astype(str)
        if frame.source_observation_id.duplicated().any():
            raise FusionFailure("Prepared persons source observation IDs are not unique; fusion cannot safely attach evidence.")
        nss = frame[weights["nss"]] if weights.get("nss") in frame else None
        nsc = frame[weights["nsc"]] if weights.get("nsc") in frame else None
        frame["final_weight"] = final_quarterly_weight(release, frame[weights["mult"]], nss, nsc) if weights.get("mult") in frame else np.nan
        frame["period_index"] = [period_index(release, q, m) for q, m in zip(frame["MoSPI_quarter"].astype(str), frame["MoSPI_month"].astype(str))]
        frame = frame.rename(columns={"MoSPI_release": "release", "MoSPI_observation": "observation_type", "MoSPI_design_period": "design_period",
                                      "MoSPI_visit": "visit", "MoSPI_month": "month", "MoSPI_state": "state", "MoSPI_sector": "sector",
                                      "MoSPI_stratum": "stratum", "MoSPI_fsu": "fsu", "MoSPI_weight": "design_weight"})
        for column in ("month", "state", "sector", "stratum", "fsu", "visit"):
            frame[column] = frame[column].astype("string").fillna("").str.strip()
        return frame[["source_observation_id", "release", "observation_type", "design_period", "visit", "month", "state", "sector", "stratum", "fsu",
                      "design_weight", "final_weight", "period_index"]]

    def _band(self, score: Any) -> str:
        if pd.isna(score):
            return "NOT_ASSESSABLE"
        for band, threshold in self.config.parameters.priority_bands:
            if float(score) >= threshold:
                return band
        return "LOW"

    def fuse(self, cases: pd.DataFrame) -> pd.DataFrame:
        """Risk, influence-independent priority logic on an assembled case table (pure; used by evaluation)."""
        p = self.config.parameters
        for source in RECORD_SOURCES:
            raw, rank, status = f"{source}_raw_score", f"{source}_rank", f"{source}_status"
            if raw not in cases:
                cases[raw] = np.nan
            if status not in cases:
                cases[status] = "NOT_AVAILABLE"
            cases[rank] = percentile_midrank(cases[raw], zero_is_no_evidence=(source == "statistical"))
            cases.loc[cases[rank].isna() & cases[status].eq("ASSESSABLE"), status] = "NOT_ASSESSABLE"
            if f"{source}_reason" not in cases:
                cases[f"{source}_reason"] = None
        rank_columns = [f"{source}_rank" for source in RECORD_SOURCES]
        weights = p.source_weights
        numerator = sum(cases[f"{s}_rank"].fillna(0) * weights[s] for s in RECORD_SOURCES)
        denominator = sum(cases[f"{s}_rank"].notna() * weights[s] for s in RECORD_SOURCES)
        cases["available_evidence_count"] = cases[rank_columns].notna().sum(axis=1)
        cases["weighted_risk_score"] = np.where(denominator > 0, numerator / np.where(denominator > 0, denominator, 1), np.nan)
        cases["maximum_available_rank"] = cases[rank_columns].max(axis=1)
        cases["override_applied"] = cases.maximum_available_rank.ge(p.override_rank_threshold)
        cases["risk_score"] = np.where(cases.override_applied, np.maximum(cases.weighted_risk_score, cases.maximum_available_rank), cases.weighted_risk_score)
        rule_errors = pd.to_numeric(cases.get("rule_error_count", 0), errors="coerce").fillna(0)
        cases["rule_violation"] = rule_errors.gt(0)
        cases["risk_status"] = np.where(pd.notna(cases.risk_score), "ASSESSABLE", "NOT_ASSESSABLE")
        cases["priority_score"] = np.where(pd.notna(cases.risk_score) & cases.influence_score.notna(), cases.risk_score * cases.influence_score, np.nan)
        # A documented-rule breach is a definite inconsistency: it is reviewed first, whatever its size.
        cases.loc[cases.rule_violation, "priority_score"] = 1.0
        cases["priority_rank"] = percentile_midrank(cases.priority_score)
        cases["priority_band"] = cases.priority_score.map(self._band)
        return cases

    def run(self) -> Path:
        started = time.perf_counter()
        prep_meta, source_meta = self._validate()
        base = self._prepared_identity(prep_meta)
        stat, stat_targets = self._statistical(self.config.statistical_run / "statistical_evidence.parquet")
        sources = [stat, self._contextual(self.config.contextual_run / "contextual_evidence.parquet"), self._ml(self.config.ml_run)]
        if self.config.historical_run:
            sources.append(self._historical(self.config.historical_run))
        known = set(base.source_observation_id)
        for source in sources:
            unknown = set(source.source_observation_id) - known
            if unknown:
                raise FusionFailure(f"Evidence cannot be mapped to the supplied prepared persons run ({len(unknown)} unknown source IDs).")
        cases = base
        for source in sources:
            cases = cases.merge(source, on="source_observation_id", how="left")
        if not self.config.historical_run:
            cases["historical_status"] = "NOT_AVAILABLE"; cases["historical_reason"] = "HISTORICAL_RUN_NOT_SUPPLIED"
            cases["historical_statement"] = "No historical run was supplied."; cases["historical_details_json"] = "[]"
        if self.config.integrity_run:
            integrity = self._integrity(self.config.integrity_run)
            cases = cases.merge(integrity, on="source_observation_id", how="left")
            cases["rule_violation_count"] = cases["rule_violation_count"].fillna(0).astype(int)
            cases["rule_error_count"] = cases["rule_error_count"].fillna(0).astype(int)
            cases["rules_status"] = "CHECKED"
        else:
            cases["rule_violation_count"] = 0; cases["rule_error_count"] = 0; cases["rule_ids"] = None; cases["rules_status"] = "NOT_AVAILABLE"
        pattern_rows = None
        if self.config.pattern_run:
            pattern, pattern_rows = self._pattern(self.config.pattern_run / "pattern_evidence.parquet")
            cases = cases.merge(pattern, on=PATTERN_KEYS, how="left")
            cases["pattern_status"] = cases["pattern_status"].fillna("NOT_ASSESSABLE")
        else:
            cases["pattern_raw_score"] = np.nan; cases["pattern_min_q"] = np.nan; cases["pattern_notable_checks"] = 0; cases["pattern_checks"] = 0
            cases["pattern_status"] = "NOT_AVAILABLE"; cases["pattern_reason"] = "PATTERN_RUN_NOT_SUPPLIED"
            cases["pattern_statement"] = "No compatible Pattern run was supplied for this fusion run."; cases["pattern_details_json"] = "[]"
        # FSU context only: displayed, never part of record risk.
        cases["pattern_rank"] = percentile_midrank(cases["pattern_raw_score"])

        shares_input = stat_targets.merge(base[["source_observation_id", "final_weight", "release", "period_index", "state", "sector"]], on="source_observation_id", how="left")
        shares_input["domain"] = shares_input["release"].astype(str) + "|" + shares_input["period_index"].astype(str) + "|" + shares_input["state"].astype(str) + "|" + shares_input["sector"].astype(str)
        shares = domain_shares(shares_input)
        cases = calculate_influence(cases, shares)
        cases = self.fuse(cases)
        cases["case_id"] = cases.source_observation_id.map(lambda value: "case_" + hashlib.sha256(str(value).encode()).hexdigest()[:20])
        provenance = {
            "preprocessing_run_id": prep_meta["run_id"],
            **{f"{name}_run_id": source_meta.get(name, {}).get("run_id") for name in ("statistical", "contextual", "ml", "pattern", "historical", "integrity")},
            "fusion_version": self.config.parameters.fusion_version, "calibration_version": self.config.parameters.calibration_version,
            "influence_version": self.config.parameters.influence_version,
        }
        cases["provenance_json"] = json.dumps(provenance, sort_keys=True)
        for source in (*RECORD_SOURCES, "pattern"):
            if f"{source}_details_json" not in cases:
                cases[f"{source}_details_json"] = "[]"
        cases["evidence_card_json"] = ""
        card_rows = cases.loc[cases.priority_score.notna()].nlargest(self.config.parameters.evidence_card_capacity, "priority_score")
        evidence_cards = pd.DataFrame({"case_id": card_rows.case_id, "evidence_card_json": card_rows.apply(lambda row: json.dumps(build_evidence_card(row), default=str, sort_keys=True), axis=1)})
        groups = self._groups(cases, pattern_rows)
        run_id = self.config.run_id or str(uuid.uuid4())
        destination = self.config.output_root / f"{prep_meta['release']}_{prep_meta['observation']}_{run_id}"
        destination.mkdir(parents=True, exist_ok=False)
        cases.sort_values(["priority_score", "source_observation_id"], ascending=[False, True], na_position="last").to_parquet(destination / "fused_cases.parquet", index=False)
        evidence_cards.to_parquet(destination / "evidence_cards.parquet", index=False)
        groups.to_parquet(destination / "group_priorities.parquet", index=False)
        shares[["source_observation_id", "target_variable", "local_score", "domain", "domain_total"]].dropna(subset=["local_score"]).to_parquet(destination / "influence_components.parquet", index=False)
        initialise(destination / "review_audit.sqlite")
        assessable = int(cases.risk_status.eq("ASSESSABLE").sum())
        summary = {
            "records_processed": int(len(cases)), "assessable_records": assessable, "not_assessable_records": int(len(cases) - assessable),
            "priority_rows": int(cases.priority_score.notna().sum()), "group_priority_rows": int(groups.group_priority_score.notna().sum()) if len(groups) else 0,
            "notable_groups": int(groups.group_priority_band.isin(["HIGH", "MEDIUM"]).sum()) if len(groups) else 0,
            "rule_violation_records": int(cases.rule_violation.sum()),
            "source_availability": {source: int(cases[f"{source}_status"].eq("ASSESSABLE").sum()) for source in (*RECORD_SOURCES, "pattern")},
            "influence_availability": int(cases.influence_status.eq("ASSESSABLE").sum()),
            "risk_distribution": _distribution(cases.risk_score), "influence_distribution": _distribution(cases.influence_score),
            "priority_distribution": _distribution(cases.priority_score),
            "band_counts": {str(k): int(v) for k, v in cases.priority_band.value_counts().items()},
            "runtime_seconds": round(time.perf_counter() - started, 3),
        }
        metadata = {"run_id": run_id, "release": prep_meta["release"], "observation": prep_meta["observation"], "design_period": prep_meta["design_period"],
                    "input_preprocessing_run_id": prep_meta["run_id"], "source_runs": {name: value.get("run_id") for name, value in source_meta.items()},
                    "fusion_version": self.config.parameters.fusion_version,
                    "parameters": {"source_weights": self.config.parameters.source_weights, "override_rank_threshold": self.config.parameters.override_rank_threshold,
                                   "priority_bands": self.config.parameters.priority_bands, "group_bands": self.config.parameters.group_bands,
                                   "evidence_card_capacity": self.config.parameters.evidence_card_capacity, "influence_version": self.config.parameters.influence_version,
                                   "calibration_version": self.config.parameters.calibration_version},
                    "output_files": ["fused_cases.parquet", "evidence_cards.parquet", "group_priorities.parquet", "influence_components.parquet",
                                     "fusion_report.json", "fusion_report.md", "review_audit.sqlite", "run_metadata.json"]}
        (destination / "fusion_report.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        (destination / "run_metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
        (destination / "fusion_report.md").write_text(_markdown_report(metadata, summary), encoding="utf-8")
        return destination

    def _groups(self, cases: pd.DataFrame, pattern_rows: pd.DataFrame | None) -> pd.DataFrame:
        group = cases.groupby(PATTERN_KEYS, dropna=False, sort=False).agg(
            records=("case_id", "size"), assessable_records=("risk_status", lambda x: int(x.eq("ASSESSABLE").sum())),
            max_pattern_rank=("pattern_raw_score", "max"), pattern_min_q=("pattern_min_q", "min"),
            notable_checks=("pattern_notable_checks", "max"), pattern_checks=("pattern_checks", "max"),
            max_risk_score=("risk_score", "max"), max_priority_score=("priority_score", "max"), mean_influence_score=("influence_score", "mean"),
        ).reset_index()
        q = pd.to_numeric(group.pattern_min_q, errors="coerce")
        group["group_priority_score"] = -np.log10(q.clip(lower=1e-300))
        group["group_priority_rank"] = percentile_midrank(group.group_priority_score)

        def band(value: Any) -> str:
            if pd.isna(value):
                return "NOT_ASSESSABLE"
            for name, threshold in self.config.parameters.group_bands:
                if float(value) < threshold:
                    return name
            return "LOW"

        group["group_priority_band"] = q.map(band)
        return group.sort_values(["group_priority_score", "fsu"], ascending=[False, True], na_position="last").reset_index(drop=True)


def _distribution(series: pd.Series) -> dict[str, Any]:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return {"count": 0}
    return {"count": int(len(numeric)), "min": float(numeric.min()), "p50": float(numeric.quantile(.5)), "p95": float(numeric.quantile(.95)), "max": float(numeric.max())}


def _markdown_report(metadata: dict[str, Any], summary: dict[str, Any]) -> str:
    availability = "\n".join(f"| {name.title()} | {count:,} |" for name, count in summary["source_availability"].items())
    return f"""# MoSPI Fusion V2 report

- Fusion run: `{metadata['run_id']}`
- Release / observation: `{metadata['release']}` / `{metadata['observation']}`
- Preparation run: `{metadata['input_preprocessing_run_id']}`

## Coverage

| Measure | Count |
|---|---:|
| Records processed | {summary['records_processed']:,} |
| Assessable risk | {summary['assessable_records']:,} |
| Assessable influence | {summary['influence_availability']:,} |
| Assessable priority | {summary['priority_rows']:,} |
| Records breaking a documented rule | {summary['rule_violation_records']:,} |

## Available evidence by source

| Source | Assessable records |
|---|---:|
{availability}

## Interpretation boundary

Risk is a calibrated combined record-level evidence-strength score, not a probability that a record is wrong. FSU (pattern) evidence is group context and is not part of record risk. Influence is a PROVISIONAL selective-editing local score: the largest per-variable share of a weighted State x sector x period total that would change if the value were replaced by its peer median; it is not the impact on an official PLFS estimate. Priority is `risk x influence` and supports review ordering only. Weights, override and bands are provisional engineering settings. No source response is changed.
"""
