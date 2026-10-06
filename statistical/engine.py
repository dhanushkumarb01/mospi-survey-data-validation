"""Peer-group consuming, robust statistical evidence engine for PLFS V1."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from peer_groups.config import SOURCE_PROFILES
from survey_rules import APPLICABLE, applicability_series

from .config import APPROVED_TARGETS, STATISTICAL_METHOD_VERSION, StatisticalParameters
from .reporting import utc_now, write_json, write_markdown_report
from .revisit import build_revisit_evidence
from .statistics import add_distribution_evidence, finite_numeric


class StatisticalFailure(RuntimeError):
    """Raised when provenance or peer-reference integrity is insufficient."""


@dataclass(frozen=True)
class RunConfig:
    prepared_person_path: Path
    peer_group_run_path: Path
    output_root: Path
    run_id: str | None = None
    parameters: StatisticalParameters = StatisticalParameters()
    revisit_prepared_person_path: Path | None = None
    revisit_peer_group_run_path: Path | None = None


def _clean(values: pd.Series) -> pd.Series:
    return values.astype("string").fillna("").str.strip()


def _source_ids(frame: pd.DataFrame, serial_column: str) -> pd.Series:
    serial = _clean(frame[serial_column])
    return _clean(frame["MoSPI_record_key"]).str.cat(serial.mask(serial.eq(""), _clean(frame["MoSPI_source_row"])), sep="|person=")


class StatisticalEngine:
    """Calculate only robust statistical evidence within existing peer groups."""

    def __init__(self, config: RunConfig) -> None:
        self.config = replace(
            config, prepared_person_path=Path(config.prepared_person_path), peer_group_run_path=Path(config.peer_group_run_path),
            output_root=Path(config.output_root),
            revisit_prepared_person_path=Path(config.revisit_prepared_person_path) if config.revisit_prepared_person_path else None,
            revisit_peer_group_run_path=Path(config.revisit_peer_group_run_path) if config.revisit_peer_group_run_path else None,
        )
        if bool(self.config.revisit_prepared_person_path) != bool(self.config.revisit_peer_group_run_path):
            raise ValueError("Both revisit input paths are required for linked revisit evidence")

    @staticmethod
    def _metadata(path: Path) -> dict[str, object]:
        if not path.is_file():
            raise StatisticalFailure(f"Required metadata is absent: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise StatisticalFailure(f"Invalid JSON metadata: {path}") from error

    def _validate_inputs(self) -> tuple[dict[str, object], dict[str, object], object]:
        if not self.config.prepared_person_path.is_file():
            raise StatisticalFailure(f"Prepared person input does not exist: {self.config.prepared_person_path}")
        assignments = self.config.peer_group_run_path / "peer_group_assignments.parquet"
        references = self.config.peer_group_run_path / "peer_group_references.parquet"
        if not assignments.is_file() or not references.is_file():
            raise StatisticalFailure("Peer-group run must contain assignment and reference Parquet tables")
        prepared = self._metadata(self.config.prepared_person_path.parent / "run_metadata.json")
        peer = self._metadata(self.config.peer_group_run_path / "run_metadata.json")
        for field in ("release", "observation", "design_period"):
            if str(prepared.get(field)) != str(peer.get(field)):
                raise StatisticalFailure(f"Prepared and peer-group metadata disagree on {field}")
        if str(prepared.get("run_id")) != str(peer.get("input_preprocessing_run_id")):
            raise StatisticalFailure("Peer-group run was not built from this prepared-person run")
        key = (str(prepared["release"]), str(prepared["observation"]))
        try:
            source = SOURCE_PROFILES[key]
        except KeyError as error:
            raise StatisticalFailure(f"No source profile for prepared provenance {key}") from error
        return prepared, peer, source

    def _source_values(self, source) -> pd.DataFrame:
        columns = {
            "MoSPI_record_key", "MoSPI_source_row", "MoSPI_release", "MoSPI_observation", "MoSPI_design_period", "MoSPI_visit",
            "MoSPI_prepared_status", "MoSPI_state", "MoSPI_sector", source.person_serial_column,
            *source.target_columns.values(), *source.context_columns.values(),
        }
        if source.release == "2025":
            columns.add("MoSPI_month")
        frame = pd.read_parquet(self.config.prepared_person_path, columns=sorted(columns))
        result = pd.DataFrame({"source_observation_id": _source_ids(frame, source.person_serial_column)})
        if result["source_observation_id"].duplicated().any():
            raise StatisticalFailure("Prepared input cannot provide unique source observation identifiers")
        for target in APPROVED_TARGETS:
            raw = frame[source.target_columns[target]] if target in source.target_columns else pd.Series(pd.NA, index=frame.index, dtype="string")
            result[f"{target}__raw"] = raw.astype("string")
            result[f"{target}__value"] = finite_numeric(raw)
        # These are not a second grouping mechanism.  They are the exact
        # source values needed to materialise membership of each already-issued
        # peer_group_reference definition (including members assigned at a
        # more detailed backoff level).
        result["release"] = _clean(frame["MoSPI_release"])
        result["observation"] = _clean(frame["MoSPI_observation"])
        result["design_period"] = _clean(frame["MoSPI_design_period"])
        result["visit"] = _clean(frame["MoSPI_visit"])
        result["month"] = _clean(frame["MoSPI_month"]) if "MoSPI_month" in frame else ""
        result["state"] = _clean(frame["MoSPI_state"])
        result["sector"] = _clean(frame["MoSPI_sector"])
        result["cws_status"] = _clean(frame[source.context_columns["cws_status"]])
        if "education" in source.context_columns:
            result["education"] = _clean(frame[source.context_columns["education"]])
        if "occupation_major_group" in source.context_columns:
            occupation = _clean(frame[source.context_columns["occupation_major_group"]])
            result["occupation_major_group"] = occupation.where(occupation.str.fullmatch(r"\d{3}"), "").str.slice(0, 1)
        if "industry_division" in source.context_columns:
            industry = _clean(frame[source.context_columns["industry_division"]])
            result["industry_division"] = industry.where(industry.str.fullmatch(r"\d{4,5}"), "").str.slice(0, 2)
        result["_prepared_ready"] = _clean(frame["MoSPI_prepared_status"]).eq("ready_for_downstream_preparation_only")
        return result

    def _assignments(self, target: str) -> pd.DataFrame:
        columns = [
            "source_observation_id", "MoSPI_record_key", "MoSPI_source_row", "target_variable", "release", "observation", "design_period", "visit", "month",
            "reference_run_id", "input_preprocessing_run_id", "specification_version", "minimum_group_size", "peer_group_id", "peer_group_size",
            "grouping_profile", "grouping_dimensions", "grouping_values", "backoff_level", "assessability_status", "not_assessable_reason",
        ]
        return pd.read_parquet(self.config.peer_group_run_path / "peer_group_assignments.parquet", columns=columns, filters=[("target_variable", "=", target)])

    def _references_for(self, assignments: pd.DataFrame, target: str) -> pd.DataFrame:
        references = pd.read_parquet(self.config.peer_group_run_path / "peer_group_references.parquet", columns=["peer_group_id", "target_variable"])
        # Read the full reference definition only after retaining the target.
        references = pd.read_parquet(self.config.peer_group_run_path / "peer_group_references.parquet")
        references = references.loc[references["target_variable"].eq(target)].copy()
        reference_ids = set(references["peer_group_id"].dropna().astype(str))
        assigned_ids = set(assignments.loc[assignments["assessability_status"].eq("ASSESSABLE"), "peer_group_id"].dropna().astype(str))
        if not assigned_ids.issubset(reference_ids):
            raise StatisticalFailure(f"Peer assignments for {target} reference group IDs absent from peer_group_references")
        return references

    def _reference_evidence(self, source_values: pd.DataFrame, references: pd.DataFrame, requested: pd.DataFrame, target: str) -> pd.DataFrame:
        """Calculate only evidence rows actually assigned to this target.

        Membership is materialised one peer-definition level at a time.  This
        keeps real-release memory bounded while still checking every reference
        group's recorded membership count before retaining requested rows.
        """
        selected_parts: list[pd.DataFrame] = []
        for dimensions_json, definitions in references.groupby("grouping_dimensions", sort=False, dropna=False):
            try:
                dimensions = json.loads(str(dimensions_json))
            except json.JSONDecodeError as error:
                raise StatisticalFailure(f"Invalid peer grouping dimensions for {target}") from error
            if not isinstance(dimensions, list):
                raise StatisticalFailure(f"Peer grouping dimensions are not a list for {target}")
            key_columns = ["release", "observation", "design_period", "visit", "month", *dimensions]
            absent = set(key_columns) - set(source_values.columns)
            if absent:
                raise StatisticalFailure(f"Prepared input lacks peer reference dimensions: {sorted(absent)}")
            definition_values = definitions[["release", "observation", "design_period", "visit", "month", "peer_group_id", "peer_group_size", "grouping_values"]].copy()
            try:
                dimension_values = definition_values["grouping_values"].map(lambda value: json.loads(str(value)))
            except json.JSONDecodeError as error:
                raise StatisticalFailure(f"Invalid peer grouping values for {target}") from error
            for dimension in dimensions:
                definition_values[dimension] = dimension_values.map(lambda value: str(value.get(dimension, "")) if isinstance(value, dict) else "")
            definition_values = definition_values[key_columns + ["peer_group_id", "peer_group_size"]]
            for column in key_columns:
                definition_values[column] = _clean(definition_values[column])
            if definition_values.duplicated(key_columns).any():
                raise StatisticalFailure(f"Duplicate peer reference definitions for {target}")
            population = source_values.loc[source_values["_prepared_ready"] & np.isfinite(source_values[f"{target}__value"]), ["source_observation_id", f"{target}__value", *key_columns]].copy()
            # A blank month is the documented pre-2025 boundary representation;
            # only configured comparison dimensions, not every boundary field,
            # must be populated to belong to a reference population.
            population = population.loc[population[dimensions].ne("").all(axis=1)]
            merged = population.merge(definition_values, on=key_columns, how="inner", validate="many_to_one", sort=False)
            actual = merged.groupby("peer_group_id", sort=False).size()
            expected = definition_values.set_index("peer_group_id")["peer_group_size"].astype("int64")
            if not actual.reindex(expected.index).eq(expected).all():
                raise StatisticalFailure(f"Peer reference population mismatch for {target}; refusing to reconstruct a different group")
            evidence = add_distribution_evidence(
                merged.rename(columns={f"{target}__value": "observed_value"}), value_column="observed_value", group_column="peer_group_id",
                lower_quantile=self.config.parameters.lower_tail_quantile, upper_quantile=self.config.parameters.upper_tail_quantile,
            ).rename(columns={"reference_group_size": "computed_peer_group_size"})
            peer_ids = set(definition_values["peer_group_id"].astype(str))
            wanted = requested.loc[requested["peer_group_id"].astype(str).isin(peer_ids)]
            selected_parts.append(wanted.merge(evidence, on=["source_observation_id", "peer_group_id"], how="left", validate="one_to_one", sort=False))
        result = pd.concat(selected_parts, ignore_index=True) if selected_parts else pd.DataFrame()
        if len(result) != len(requested):
            raise StatisticalFailure(f"Could not materialise evidence for every assigned peer observation of {target}")
        return result

    def _build_target(self, assignments: pd.DataFrame, source_values: pd.DataFrame, references: pd.DataFrame, target: str) -> tuple[pd.DataFrame, dict[str, object]]:
        output = assignments.merge(source_values[["source_observation_id", f"{target}__raw", f"{target}__value", "cws_status"]], on="source_observation_id", how="left", validate="one_to_one")
        output.rename(columns={f"{target}__raw": "observed_value_raw", f"{target}__value": "observed_value"}, inplace=True)
        # PLFS questionnaire applicability (survey_rules.plfs): a 0 stored for a
        # person whose activity status does not route to this item is a
        # placeholder, not a reported value, and carries no evidence.
        output["target_applicability"] = applicability_series(target, output["cws_status"]).to_numpy()
        output.drop(columns="cws_status", inplace=True)
        output["statistical_assessability_status"] = "NOT_ASSESSABLE"
        output["statistical_assessability_reason"] = "PEER_" + output["not_assessable_reason"].fillna("NOT_ASSESSABLE").astype("string")
        peer_ready = output["assessability_status"].eq("ASSESSABLE") & output["peer_group_id"].notna()
        finite = np.isfinite(output["observed_value"])
        applicable = output["target_applicability"].eq(APPLICABLE)
        eligible = peer_ready & finite & applicable
        output.loc[peer_ready & ~finite, "statistical_assessability_reason"] = "TARGET_VALUE_MISSING_INVALID_OR_NONFINITE"
        output.loc[peer_ready & finite & ~applicable, "statistical_assessability_reason"] = "TARGET_" + output.loc[peer_ready & finite & ~applicable, "target_applicability"].astype("string") + "_FOR_CWS_STATUS"
        output.loc[eligible, "statistical_assessability_status"] = "ASSESSABLE"
        output.loc[eligible, "statistical_assessability_reason"] = pd.NA
        output["statistical_method_version"] = STATISTICAL_METHOD_VERSION
        output["percentile_convention"] = "EMPIRICAL_MIDRANK_INCLUDING_OBSERVATION"
        output["quantile_convention"] = "LINEAR_INTERPOLATION"
        requested = output.loc[eligible, ["source_observation_id", "peer_group_id"]].copy()
        evidence = self._reference_evidence(source_values, references, requested, target) if not requested.empty else pd.DataFrame()
        # Keep one schema for every target, even when nothing is assessable,
        # so the per-target Parquet batches always align.
        lower, upper = self.config.parameters.lower_tail_quantile, self.config.parameters.upper_tail_quantile
        schema_fields = ["computed_peer_group_size", *[f"quantile_{str(q).replace('.', '_')}" for q in (lower, .25, .5, .75, upper)],
                         "peer_median", "mad", "percentile_position", "signed_distance_from_median", "absolute_distance_from_median",
                         "robust_deviation", "robust_deviation_status", "distribution_position", "lower_tail_percentile_distance", "upper_tail_percentile_distance"]
        for field in schema_fields:
            output[field] = pd.Series(pd.NA, index=output.index, dtype="string") if field in {"robust_deviation_status", "distribution_position"} else np.nan
        if not evidence.empty:
            fields = [
                "computed_peer_group_size", "quantile_0_05", "quantile_0_25", "quantile_0_5", "quantile_0_75", "quantile_0_95",
                "peer_median", "mad", "percentile_position", "signed_distance_from_median", "absolute_distance_from_median",
                "robust_deviation", "robust_deviation_status", "distribution_position", "lower_tail_percentile_distance", "upper_tail_percentile_distance",
            ]
            # Quantile field names are parameter-derived, so keep the common schema explicit for V1 defaults and generic otherwise.
            fields = [field for field in evidence.columns if field in fields or field.startswith("quantile_")]
            evidence_by_observation = evidence.set_index(["source_observation_id", "peer_group_id"])
            output_keys = pd.MultiIndex.from_frame(output[["source_observation_id", "peer_group_id"]])
            for field in fields:
                output[field] = evidence_by_observation[field].reindex(output_keys).to_numpy()
        output.replace([np.inf, -np.inf], np.nan, inplace=True)
        for field in schema_fields:
            output[field] = output[field].astype("string") if field in {"robust_deviation_status", "distribution_position"} else pd.to_numeric(output[field], errors="coerce").astype("float64")
        assessed = output["statistical_assessability_status"].eq("ASSESSABLE")
        required = ["observed_value", "peer_median", "mad", "percentile_position"]
        if assessed.any() and not np.isfinite(output.loc[assessed, required].to_numpy(dtype=float)).all():
            raise StatisticalFailure(f"Non-finite required statistical evidence for {target}")
        summary = {
            "target_variable": target, "records": int(len(output)), "assessable": int(assessed.sum()),
            "not_assessable": int((~assessed).sum()), "assessability_percent": float(100 * assessed.mean()) if len(output) else 0.0,
            "peer_groups": int(output.loc[assessed, "peer_group_id"].nunique()),
            "zero_mad_groups": int(output.loc[assessed & output["mad"].eq(0), "peer_group_id"].nunique()),
            "distribution_positions": {str(k): int(v) for k, v in output.loc[assessed, "distribution_position"].value_counts().items()},
            "percentile_summary": output.loc[assessed, "percentile_position"].describe(percentiles=[.05, .25, .5, .75, .95]).to_dict(),
            "robust_deviation_summary": output.loc[assessed & output["robust_deviation"].notna(), "robust_deviation"].describe(percentiles=[.05, .25, .5, .75, .95]).to_dict(),
        }
        return output, summary

    def run(self) -> Path:
        started = time.perf_counter()
        prepared, peer, source = self._validate_inputs()
        run_id = self.config.run_id or str(uuid.uuid4())
        output_dir = self.config.output_root / f"{prepared['release']}_{prepared['observation']}_{run_id}"
        output_dir.mkdir(parents=True, exist_ok=False)
        source_values = self._source_values(source)
        writer = None
        summaries: list[dict[str, object]] = []
        try:
            for target in APPROVED_TARGETS:
                assignments = self._assignments(target)
                if assignments.empty:
                    raise StatisticalFailure(f"Peer assignment table is missing approved target {target}")
                references = self._references_for(assignments, target)
                evidence, summary = self._build_target(assignments, source_values, references, target)
                table = pa.Table.from_pandas(evidence, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(output_dir / "statistical_evidence.parquet", table.schema, compression="snappy")
                writer.write_table(table.select(writer.schema.names).cast(writer.schema))
                summaries.append(summary)
        finally:
            if writer is not None:
                writer.close()
        revisit_summary: dict[str, object] = {"available": False, "reason": "NO_LINKED_REVISIT_INPUT_FOR_THIS_RUN"}
        outputs = ["statistical_evidence.parquet", "statistical_report.json", "statistical_report.md", "run_metadata.json"]
        if self.config.revisit_prepared_person_path:
            if str(prepared["release"]) != "2023_24" or str(prepared["observation"]) != "first_visit":
                raise StatisticalFailure("Linked revisit evidence is only supported from the 2023_24 first-visit run")
            revisit_table = build_revisit_evidence(
                first_prepared_path=self.config.prepared_person_path, revisit_prepared_path=self.config.revisit_prepared_person_path,
                revisit_assignment_path=self.config.revisit_peer_group_run_path / "peer_group_assignments.parquet", parameters=self.config.parameters,
            )
            revisit_table.to_parquet(output_dir / "revisit_statistical_evidence.parquet", index=False)
            outputs.insert(1, "revisit_statistical_evidence.parquet")
            revisit_summary = {
                "available": True, "records": int(len(revisit_table)),
                "assessable": int(revisit_table["revisit_comparison_status"].eq("ASSESSABLE").sum()),
                "status_counts": {str(k): int(v) for k, v in revisit_table["revisit_comparison_status"].value_counts().items()},
                "reason_counts": {str(k): int(v) for k, v in revisit_table["revisit_assessability_reason"].value_counts(dropna=False).items()},
            }
        report = {
            "records_processed": int(sum(row["records"] for row in summaries)), "records_assessable": int(sum(row["assessable"] for row in summaries)),
            "assessability_rate_percent": float(100 * sum(row["assessable"] for row in summaries) / sum(row["records"] for row in summaries)),
            "target_summary": summaries, "revisit_coverage": revisit_summary,
            "runtime_seconds": round(time.perf_counter() - started, 3), "warnings": [], "errors": [],
        }
        metadata = {
            "run_id": run_id, "processing_timestamp_utc": utc_now(), "software_version": "0.1.0", "statistical_method_version": STATISTICAL_METHOD_VERSION,
            "peer_group_run_id": peer["run_id"], "peer_group_specification_version": peer["specification_version"], "input_preprocessing_run_id": prepared["run_id"],
            "input_prepared_person_path": str(self.config.prepared_person_path), "peer_group_run_path": str(self.config.peer_group_run_path),
            "release": prepared["release"], "observation": prepared["observation"], "design_period": prepared["design_period"],
            "target_variables": list(APPROVED_TARGETS), "parameters": self.config.parameters.__dict__, "output_files": outputs,
        }
        write_json(output_dir / "statistical_report.json", report)
        write_json(output_dir / "run_metadata.json", metadata)
        write_markdown_report(output_dir / "statistical_report.md", report, metadata)
        return output_dir
