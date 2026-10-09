"""Contextual categorical evidence using already-issued peer assignments.

V1 intentionally implements no numerical model.  It measures the empirical
conditional occurrence of an observed three-digit occupation code inside the
existing day7-hours peer reference population.  The peer engine, including its
release/visit/month boundaries and backoff choice, remains the sole owner of
reference-population construction.
"""

from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from peer_groups.config import SOURCE_PROFILES, derive_context
from survey_rules.schema import read_parquet

from .config import (
    CONTEXTUAL_METHOD_VERSION,
    CONTEXTUAL_TARGET,
    METHOD_IDENTIFIER,
    METHOD_VERSION,
    PRIOR_STRENGTH,
    REFERENCE_ASSIGNMENT_TARGET,
    VALID_OCCUPATION_PATTERN,
)
from .reporting import utc_now, write_json, write_markdown_report


class ContextualFailure(RuntimeError):
    """Raised when input provenance or existing peer references are unsafe."""


@dataclass(frozen=True)
class RunConfig:
    prepared_person_path: Path
    peer_group_run_path: Path
    output_root: Path
    run_id: str | None = None


def _clean(values: pd.Series) -> pd.Series:
    return values.astype("string").fillna("").str.strip()


def _source_ids(frame: pd.DataFrame, serial_column: str) -> pd.Series:
    serial = _clean(frame[serial_column])
    return _clean(frame["MoSPI_record_key"]).str.cat(
        serial.mask(serial.eq(""), _clean(frame["MoSPI_source_row"])), sep="|person="
    )


def conditional_surprisal(frequency: float | int | None) -> float | None:
    """Return -ln(frequency) only for a genuine positive empirical frequency.

    Zero is never smoothed or substituted.  It remains unavailable rather than
    being converted to infinity or an invented finite number.
    """
    if frequency is None:
        return None
    value = float(frequency)
    if not math.isfinite(value) or value <= 0:
        return None
    return -math.log(value)


def smoothed_tail_probabilities(valid: pd.DataFrame, prior: pd.DataFrame, alpha: float = PRIOR_STRENGTH) -> pd.DataFrame:
    """Conformal frequency tail probability of each observed code (plan W2.5).

    ``valid``: one row per reference member (peer_group_id, observed_value, cws_status).
    ``prior``: release-wide code distribution per activity status (cws_status, observed_value, prior_probability).

    For a member with code k in a group of N comparable people (the member
    included), ``coding_tail_p`` is the share of the group whose code is at
    most as frequent as k:  sum_{j: c_j <= c_k} c_j / N.  It is the conformal
    p-value with "how common is my code here" as the score, so under
    exchangeability a correctly coded person has P(p <= a) <= a, and the
    smallest value is 1/N.  It depends on the code's *frequency*, not on how
    many people are compared (audit M1: raw surprisal grew with group size),
    and a code seen once in a group where many codes are seen once is not
    surprising.  (An earlier leave-one-out Dirichlet variant treated every
    singleton as unseen and flagged 1.6% of 2024 records below 0.001; it was
    replaced before release.)

    ``smoothed_probability`` (display only) is the Dirichlet-smoothed share
    (c_k + alpha * prior_k) / (N + alpha).
    """
    columns = ["peer_group_id", "observed_value", "smoothed_probability", "coding_tail_p"]
    if valid.empty:
        return pd.DataFrame(columns=columns)
    priors = {status: part.set_index("observed_value")["prior_probability"] for status, part in prior.groupby("cws_status", sort=False)}
    counts = valid.groupby(["peer_group_id", "observed_value"], sort=False).size()
    statuses = valid.groupby("peer_group_id", sort=False)["cws_status"].agg(lambda s: s.iloc[0] if s.nunique() == 1 else None)
    rows: list[pd.DataFrame] = []
    for group_id, group_counts in counts.groupby(level=0, sort=False):
        observed = group_counts.droplevel(0).astype(float)
        total = float(observed.sum())
        ordered = np.sort(observed.to_numpy())
        prefix = np.concatenate([[0.0], np.cumsum(ordered)])
        at_most = prefix[np.searchsorted(ordered, observed.to_numpy(), side="right")]
        prior_k = priors.get(statuses.get(group_id), pd.Series(dtype=float)).reindex(observed.index).fillna(0.0).to_numpy()
        rows.append(pd.DataFrame({"peer_group_id": group_id, "observed_value": observed.index.astype("string"),
                                  "smoothed_probability": (observed.to_numpy() + alpha * prior_k) / (total + alpha),
                                  "coding_tail_p": np.clip(at_most / total, 0.0, 1.0)}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=columns)


class ContextualEngine:
    """Materialise contextual categorical evidence from existing peer groups."""

    def __init__(self, config: RunConfig) -> None:
        self.config = replace(
            config,
            prepared_person_path=Path(config.prepared_person_path),
            peer_group_run_path=Path(config.peer_group_run_path),
            output_root=Path(config.output_root),
        )

    @staticmethod
    def _metadata(path: Path) -> dict[str, object]:
        if not path.is_file():
            raise ContextualFailure(f"Required metadata is absent: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ContextualFailure(f"Invalid JSON metadata: {path}") from error

    def _validate_inputs(self) -> tuple[dict[str, object], dict[str, object], object]:
        assignments = self.config.peer_group_run_path / "peer_group_assignments.parquet"
        references = self.config.peer_group_run_path / "peer_group_references.parquet"
        if not self.config.prepared_person_path.is_file():
            raise ContextualFailure(f"Prepared person input does not exist: {self.config.prepared_person_path}")
        if not assignments.is_file() or not references.is_file():
            raise ContextualFailure("Peer-group run must contain assignment and reference Parquet tables")
        prepared = self._metadata(self.config.prepared_person_path.parent / "run_metadata.json")
        peer = self._metadata(self.config.peer_group_run_path / "run_metadata.json")
        for field in ("release", "observation", "design_period"):
            if str(prepared.get(field)) != str(peer.get(field)):
                raise ContextualFailure(f"Prepared and peer-group metadata disagree on {field}")
        if str(prepared.get("run_id")) != str(peer.get("input_preprocessing_run_id")):
            raise ContextualFailure("Peer-group run was not built from this prepared-person run")
        try:
            source = SOURCE_PROFILES[(str(prepared["release"]), str(prepared["observation"]))]
        except KeyError as error:
            raise ContextualFailure("No explicit source profile for prepared provenance") from error
        return prepared, peer, source

    def _source_values(self, source: object) -> pd.DataFrame:
        occupation_column = source.context_columns.get("occupation_major_group")
        reference_column = source.target_columns.get(REFERENCE_ASSIGNMENT_TARGET)
        columns = {
            "MoSPI_record_key", "MoSPI_source_row", "MoSPI_prepared_status", "MoSPI_release", "MoSPI_observation",
            "MoSPI_design_period", "MoSPI_visit", "MoSPI_state", "MoSPI_sector", source.person_serial_column,
            source.context_columns["cws_status"],
        }
        if occupation_column:
            columns.add(occupation_column)
        if reference_column:
            columns.add(reference_column)
        if "industry_division" in source.context_columns:
            columns.add(source.context_columns["industry_division"])
        if source.release == "2025":
            columns.add("MoSPI_month")
        else:
            columns.add("MoSPI_quarter")
        frame = read_parquet(self.config.prepared_person_path, columns=sorted(columns))
        result = pd.DataFrame({"source_observation_id": _source_ids(frame, source.person_serial_column)})
        if result["source_observation_id"].duplicated().any():
            raise ContextualFailure("Prepared input cannot provide unique source observation identifiers")
        raw = _clean(frame[occupation_column]) if occupation_column else pd.Series("", index=frame.index, dtype="string")
        valid = raw.str.fullmatch(VALID_OCCUPATION_PATTERN)
        result["observed_value_raw"] = raw.mask(raw.eq(""), pd.NA)
        result["observed_value"] = raw.where(valid, pd.NA).astype("string")
        result["_target_blank"] = raw.eq("")
        result["_target_invalid"] = raw.ne("") & ~valid
        result["_target_available"] = occupation_column is not None
        result["_prepared_ready"] = _clean(frame["MoSPI_prepared_status"]).eq("ready_for_downstream_preparation_only")
        # State, sector and CWS status are mandatory at every existing hours
        # grouping level. Industry may be absent at level 0 and still allow the
        # already-configured level-1 backoff, so it is not treated as required.
        result["_required_context_missing"] = (
            _clean(frame["MoSPI_state"]).eq("")
            | _clean(frame["MoSPI_sector"]).eq("")
            | _clean(frame[source.context_columns["cws_status"]]).eq("")
        )
        result["release"] = _clean(frame["MoSPI_release"])
        result["observation"] = _clean(frame["MoSPI_observation"])
        result["design_period"] = _clean(frame["MoSPI_design_period"])
        result["visit"] = _clean(frame["MoSPI_visit"])
        result["month"] = _clean(frame["MoSPI_month"]) if "MoSPI_month" in frame else ""
        context = derive_context(frame, source, design_period=str(result["design_period"].iloc[0]) if len(result) else None)
        for column in ("state", "sector", "cws_status", "industry_division", "quarter"):
            if column in context:
                result[column] = context[column].to_numpy()
        result["_reference_target_valid"] = (
            pd.to_numeric(frame[reference_column], errors="coerce").notna()
            if reference_column else pd.Series(False, index=frame.index)
        )
        return result

    def _assignments(self) -> pd.DataFrame:
        columns = [
            "source_observation_id", "MoSPI_record_key", "MoSPI_source_row", "target_variable", "release", "observation",
            "design_period", "visit", "month", "reference_run_id", "input_preprocessing_run_id", "specification_version",
            "minimum_group_size", "peer_group_id", "peer_group_size", "grouping_profile", "grouping_dimensions",
            "grouping_values", "backoff_level", "assessability_status", "not_assessable_reason",
        ]
        result = read_parquet(
            self.config.peer_group_run_path / "peer_group_assignments.parquet",
            columns=columns,
            filters=[("target_variable", "=", REFERENCE_ASSIGNMENT_TARGET)],
        )
        if result.empty:
            raise ContextualFailure(f"Peer assignment table lacks {REFERENCE_ASSIGNMENT_TARGET}")
        if result["source_observation_id"].duplicated().any():
            raise ContextualFailure("Reference peer assignments are not one row per source observation")
        return result

    def _references(self, assignments: pd.DataFrame) -> pd.DataFrame:
        references = pd.read_parquet(self.config.peer_group_run_path / "peer_group_references.parquet")
        references = references.loc[references["target_variable"].eq(REFERENCE_ASSIGNMENT_TARGET)].copy()
        assessable_ids = set(assignments.loc[assignments["assessability_status"].eq("ASSESSABLE"), "peer_group_id"].dropna().astype(str))
        reference_ids = set(references["peer_group_id"].dropna().astype(str))
        if not assessable_ids.issubset(reference_ids):
            raise ContextualFailure("An assigned contextual reference group is absent from peer_group_references")
        if not references.empty and references["peer_group_id"].duplicated().any():
            raise ContextualFailure("Duplicate peer reference definitions for contextual reference target")
        return references

    @staticmethod
    def _context_values(row: pd.Series) -> str | object:
        if pd.isna(row["grouping_dimensions"]) or pd.isna(row["grouping_values"]):
            return pd.NA
        try:
            dimensions = json.loads(str(row["grouping_dimensions"]))
            values = json.loads(str(row["grouping_values"]))
        except json.JSONDecodeError as error:
            raise ContextualFailure("Invalid peer grouping JSON") from error
        if not isinstance(dimensions, list) or not isinstance(values, dict):
            raise ContextualFailure("Invalid peer grouping definition")
        boundary = {field: str(row[field]) for field in ("release", "observation", "design_period", "visit", "month")}
        return json.dumps({"boundaries": boundary, "dimensions": dimensions, "values": values}, separators=(",", ":"), sort_keys=True)

    def _issued_context_values(self, references: pd.DataFrame) -> dict[str, str]:
        """Create context JSON once per issued group, never once per person."""
        if references.empty:
            return {}
        return {
            str(row["peer_group_id"]): self._context_values(row)
            for _, row in references.iterrows()
        }

    def _validate_no_target_leakage(self, references: pd.DataFrame, source: object) -> None:
        raw_column = source.context_columns.get("occupation_major_group")
        if not raw_column:
            return
        for encoded in references["grouping_dimensions"].dropna().unique():
            try:
                dimensions = json.loads(str(encoded))
            except json.JSONDecodeError as error:
                raise ContextualFailure("Invalid peer grouping dimensions") from error
            if raw_column in dimensions or "occupation" in dimensions:
                raise ContextualFailure("Configured contextual reference contains the occupation target and would leak it")

    def _category_evidence(self, source_values: pd.DataFrame, references: pd.DataFrame) -> pd.DataFrame:
        """Materialise exactly the issued peer memberships, then count categories.

        An observation assigned at a detailed level can still belong to a
        coarser issued reference definition.  Therefore assignment-row counts
        alone are not reference populations; membership is reconstructed from
        each issued definition using the same prepared fields and eligibility
        rule as the peer engine, then reconciled to its stored group size.
        """
        selected: list[pd.DataFrame] = []
        for encoded, definitions in references.groupby("grouping_dimensions", sort=False, dropna=False):
            try:
                dimensions = json.loads(str(encoded))
            except json.JSONDecodeError as error:
                raise ContextualFailure("Invalid peer grouping dimensions") from error
            if not isinstance(dimensions, list):
                raise ContextualFailure("Peer grouping dimensions are not a list")
            key_columns = ["release", "observation", "design_period", "visit", "month", *dimensions]
            absent = set(key_columns) - set(source_values.columns)
            if absent:
                raise ContextualFailure(f"Prepared input lacks issued peer dimensions: {sorted(absent)}")
            definition_values = definitions[["peer_group_id", "peer_group_size", "grouping_values", *[column for column in ("release", "observation", "design_period", "visit", "month")]]].copy()
            try:
                values = definition_values["grouping_values"].map(lambda value: json.loads(str(value)))
            except json.JSONDecodeError as error:
                raise ContextualFailure("Invalid peer grouping values") from error
            for dimension in dimensions:
                definition_values[dimension] = values.map(lambda value: str(value.get(dimension, "")) if isinstance(value, dict) else "")
            definition_values = definition_values[key_columns + ["peer_group_id", "peer_group_size"]]
            for column in key_columns:
                definition_values[column] = _clean(definition_values[column])
            if definition_values.duplicated(key_columns).any():
                raise ContextualFailure("Duplicate issued contextual peer definitions")
            population = source_values.loc[
                source_values["_prepared_ready"] & source_values["_reference_target_valid"],
                ["source_observation_id", "observed_value", *key_columns],
            ].copy()
            population = population.loc[population[dimensions].ne("").all(axis=1)]
            members = population.merge(definition_values, on=key_columns, how="inner", validate="many_to_one", sort=False)
            actual_sizes = members.groupby("peer_group_id", sort=False).size()
            issued_sizes = definition_values.set_index("peer_group_id")["peer_group_size"].astype("int64")
            if not actual_sizes.reindex(issued_sizes.index).eq(issued_sizes).all():
                raise ContextualFailure("Contextual peer membership does not reconcile with issued peer_group_size")
            selected.append(members[["source_observation_id", "peer_group_id", "observed_value"]])
        members = pd.concat(selected, ignore_index=True) if selected else pd.DataFrame(columns=["source_observation_id", "peer_group_id", "observed_value"])
        valid = members.loc[members["observed_value"].notna()].copy()
        if valid.empty:
            return pd.DataFrame(columns=["peer_group_id", "reference_count"])
        valid["category_parent_value"] = valid["observed_value"].astype("string").str.slice(0, 1)
        reference_counts = valid.groupby("peer_group_id", sort=False).size().rename("reference_count")
        category_counts = valid.groupby(["peer_group_id", "observed_value"], sort=False).size().rename("category_count")
        parent_counts = valid.groupby(["peer_group_id", "category_parent_value"], sort=False).size().rename("category_parent_count")
        evidence = valid[["source_observation_id", "peer_group_id", "observed_value", "category_parent_value"]].copy()
        evidence = evidence.merge(reference_counts, left_on="peer_group_id", right_index=True, how="left", validate="many_to_one")
        evidence = evidence.merge(category_counts, left_on=["peer_group_id", "observed_value"], right_index=True, how="left", validate="many_to_one")
        evidence = evidence.merge(parent_counts, left_on=["peer_group_id", "category_parent_value"], right_index=True, how="left", validate="many_to_one")
        evidence["conditional_frequency"] = evidence["category_count"] / evidence["reference_count"]
        evidence["category_parent_conditional_frequency"] = evidence["category_parent_count"] / evidence["reference_count"]
        evidence["surprisal"] = evidence["conditional_frequency"].map(conditional_surprisal)
        statuses = source_values.set_index("source_observation_id")["cws_status"]
        valid["cws_status"] = valid["source_observation_id"].map(statuses).astype("string")
        eligible = source_values.loc[source_values["_prepared_ready"] & source_values["observed_value"].notna(), ["cws_status", "observed_value"]]
        prior = eligible.groupby(["cws_status", "observed_value"], sort=False).size().rename("n").reset_index()
        prior["prior_probability"] = prior["n"] / prior.groupby("cws_status")["n"].transform("sum")
        smoothed = smoothed_tail_probabilities(valid[["peer_group_id", "observed_value", "cws_status"]], prior)
        evidence = evidence.merge(smoothed, on=["peer_group_id", "observed_value"], how="left", validate="many_to_one")
        return evidence

    def _build(self, assignments: pd.DataFrame, source_values: pd.DataFrame, references: pd.DataFrame, source: object) -> pd.DataFrame:
        output_fields = [
            "source_observation_id", "observed_value_raw", "observed_value", "_target_blank", "_target_invalid",
            "_target_available", "_prepared_ready", "_required_context_missing",
        ]
        output = assignments.merge(source_values[output_fields], on="source_observation_id", how="left", validate="one_to_one")
        if output["_target_available"].isna().any():
            raise ContextualFailure("A peer assignment cannot be matched to the prepared source observation")
        output["target_variable"] = CONTEXTUAL_TARGET
        definitions = "existing peer group " + output["grouping_profile"].fillna("").astype("string") + " using " + output["grouping_dimensions"].fillna("").astype("string")
        output["context_definition"] = definitions.mask(output["grouping_dimensions"].isna(), pd.NA)
        output["context_values"] = output["peer_group_id"].astype("string").map(self._issued_context_values(references))
        output["contextual_assessability_status"] = "NOT_ASSESSABLE"
        output["contextual_assessability_reason"] = "TARGET_UNAVAILABLE_FOR_RELEASE_OBSERVATION"
        output.loc[output["_target_available"], "contextual_assessability_reason"] = "PREPARED_RECORD_NOT_READY"
        ready = output["_prepared_ready"]
        available = output["_target_available"]
        output.loc[available & ready & output["_target_blank"], "contextual_assessability_reason"] = "TARGET_MISSING_OR_NOT_APPLICABILITY_UNRESOLVED"
        output.loc[available & ready & output["_target_invalid"], "contextual_assessability_reason"] = "INVALID_CATEGORICAL_TARGET"
        peer_ready = output["assessability_status"].eq("ASSESSABLE") & output["peer_group_id"].notna()
        candidate = available & ready & output["observed_value"].notna()
        output.loc[candidate & ~peer_ready, "contextual_assessability_reason"] = "PEER_" + output.loc[candidate & ~peer_ready, "not_assessable_reason"].fillna("REFERENCE_NOT_AVAILABLE").astype("string")
        output.loc[candidate & ~peer_ready & output["_required_context_missing"], "contextual_assessability_reason"] = "MISSING_CONTEXT"

        evidence = self._category_evidence(source_values, references)
        fields = ["reference_count", "category_count", "category_parent_value", "category_parent_count", "conditional_frequency", "category_parent_conditional_frequency", "surprisal",
                  "smoothed_probability", "coding_tail_p"]
        if not evidence.empty:
            indexed = evidence.set_index(["source_observation_id", "peer_group_id"])
            output_keys = pd.MultiIndex.from_frame(output[["source_observation_id", "peer_group_id"]])
            for field in fields:
                output[field] = indexed[field].reindex(output_keys).to_numpy()
        else:
            for field in fields:
                output[field] = pd.NA
        output["context_reference_population_count"] = output["peer_group_size"]
        enough_reference = output["reference_count"].ge(output["minimum_group_size"])
        output.loc[candidate & peer_ready & output["reference_count"].isna(), "contextual_assessability_reason"] = "ZERO_REFERENCE_SUPPORT"
        output.loc[candidate & peer_ready & output["reference_count"].notna() & ~enough_reference, "contextual_assessability_reason"] = "INSUFFICIENT_REFERENCE_SIZE"
        assessable = candidate & peer_ready & enough_reference & output["category_count"].gt(0)
        output.loc[assessable, "contextual_assessability_status"] = "ASSESSABLE"
        output.loc[assessable, "contextual_assessability_reason"] = pd.NA
        output["category_level"] = "detailed_3_digit"
        output["frequency_statement"] = pd.Series(pd.NA, index=output.index, dtype="string")
        output.loc[assessable, "frequency_statement"] = (
            "This response occurs in " + output.loc[assessable, "category_count"].astype("Int64").astype(str)
            + " of " + output.loc[assessable, "reference_count"].astype("Int64").astype(str)
            + " comparable observations with a valid three-digit occupation code."
        )
        output["method_identifier"] = METHOD_IDENTIFIER
        output["method_version"] = METHOD_VERSION
        output["smoothing_method"] = "conformal_frequency_tail; dirichlet share for display"
        output["smoothing_parameters"] = json.dumps({"display_prior_strength": PRIOR_STRENGTH, "prior": "release-wide occupation distribution within the same activity status"})
        output.replace([np.inf, -np.inf], np.nan, inplace=True)
        required = ["reference_count", "category_count", "conditional_frequency", "surprisal", "coding_tail_p"]
        if assessable.any() and not np.isfinite(output.loc[assessable, required].to_numpy(dtype=float)).all():
            raise ContextualFailure("Non-finite required contextual evidence")
        return output.drop(columns=["_target_blank", "_target_invalid", "_target_available", "_prepared_ready", "_required_context_missing"])

    @staticmethod
    def _report(output: pd.DataFrame, runtime_seconds: float) -> dict[str, Any]:
        assessable = output["contextual_assessability_status"].eq("ASSESSABLE")
        counts = output.loc[~assessable, "contextual_assessability_reason"].value_counts(dropna=False).sort_index()
        refs = output.loc[assessable, "reference_count"]
        return {
            "records_processed": int(len(output)),
            "records_assessable": int(assessable.sum()),
            "records_not_assessable": int((~assessable).sum()),
            "assessability_rate_percent": float(100 * assessable.mean()) if len(output) else 0.0,
            "target_summary": {
                "target_variable": CONTEXTUAL_TARGET,
                "records": int(len(output)),
                "assessable": int(assessable.sum()),
                "not_assessable": int((~assessable).sum()),
                "reference_groups": int(output.loc[assessable, "peer_group_id"].nunique()),
                "not_assessable_reasons": {str(key): int(value) for key, value in counts.items()},
                "reference_count_summary": refs.describe(percentiles=[.05, .25, .5, .75, .95]).to_dict() if not refs.empty else {},
                "context_coverage": output.loc[assessable, ["grouping_profile", "grouping_dimensions", "backoff_level"]].value_counts().rename("records").reset_index().to_dict(orient="records"),
            },
            "runtime_seconds": round(runtime_seconds, 3),
            "warnings": [
                "The decision score is the conformal frequency tail probability (coding_tail_p); surprisal is retained for comparison only.",
                "Prepared data has no field-level occupation applicability mask; blank occupation fields are not assessed.",
            ],
            "errors": [],
        }

    def run(self) -> Path:
        started = time.perf_counter()
        prepared, peer, source = self._validate_inputs()
        run_id = self.config.run_id or str(uuid.uuid4())
        output_dir = self.config.output_root / f"{prepared['release']}_{prepared['observation']}_{run_id}"
        output_dir.mkdir(parents=True, exist_ok=False)
        self._validate_no_target_leakage(self._references(self._assignments()), source)
        assignments = self._assignments()
        references = self._references(assignments)
        source_values = self._source_values(source)
        evidence = self._build(assignments, source_values, references, source)
        evidence.sort_values("source_observation_id", kind="mergesort", inplace=True, ignore_index=True)
        evidence.to_parquet(output_dir / "contextual_evidence.parquet", index=False)
        report = self._report(evidence, time.perf_counter() - started)
        metadata = {
            "run_id": run_id,
            "processing_timestamp_utc": utc_now(),
            "software_version": "0.1.0",
            "contextual_method_version": CONTEXTUAL_METHOD_VERSION,
            "method_identifier": METHOD_IDENTIFIER,
            "input_preprocessing_run_id": prepared["run_id"],
            "input_prepared_person_path": str(self.config.prepared_person_path),
            "peer_group_run_id": peer["run_id"],
            "peer_group_run_path": str(self.config.peer_group_run_path),
            "peer_group_specification_version": peer["specification_version"],
            "reference_assignment_target": REFERENCE_ASSIGNMENT_TARGET,
            "release": prepared["release"],
            "observation": prepared["observation"],
            "design_period": prepared["design_period"],
            "target_variables": [CONTEXTUAL_TARGET],
            "decision_score": "coding_tail_p (conformal frequency tail probability within the comparison group)",
            "smoothing": {"method": "conformal_frequency_tail", "parameters": {"display_prior_strength": PRIOR_STRENGTH,
                                                                               "prior": "release-wide occupation distribution within the same activity status"}},
            "output_files": ["contextual_evidence.parquet", "contextual_report.json", "contextual_report.md", "run_metadata.json"],
        }
        write_json(output_dir / "contextual_report.json", report)
        write_json(output_dir / "run_metadata.json", metadata)
        write_markdown_report(output_dir / "contextual_report.md", report, metadata)
        return output_dir
