"""Vectorised, deterministic construction of PLFS peer-group assignments."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

import pandas as pd

from .config import (
    DEFAULT_SPECIFICATIONS,
    PEER_GROUP_SPECIFICATION_VERSION,
    SOURCE_PROFILES,
    GroupingProfile,
    PeerGroupSpecification,
    SourceProfile,
)
from .reporting import utc_now, write_json, write_markdown_report


LOGGER = logging.getLogger(__name__)
SOFTWARE_VERSION = "0.1.0"
READY_STATUS = "ready_for_downstream_preparation_only"
PROHIBITED_DIMENSION_TOKENS = ("fsu", "weight")
REFERENCE_COLUMNS = (
    "peer_group_id", "target_variable", "grouping_profile", "grouping_dimensions", "grouping_values",
    "peer_group_size", "backoff_level", "reference_run_id", "specification_version",
    "release", "observation", "design_period", "visit", "month",
)


class PeerGroupFailure(RuntimeError):
    """Raised for an input or configuration that cannot be safely processed."""


@dataclass(frozen=True)
class RunConfig:
    """Immutable configuration for one prepared-person peer-group run."""

    prepared_person_path: Path
    output_root: Path
    run_id: str | None = None
    minimum_group_size: int = 30
    specifications: tuple[PeerGroupSpecification, ...] = DEFAULT_SPECIFICATIONS


def _clean_text(values: pd.Series) -> pd.Series:
    return values.astype("string").fillna("").str.strip()


def _major_occupation(values: pd.Series) -> pd.Series:
    """Coarsen supplied three-digit occupation codes to their major group."""
    clean = _clean_text(values)
    return clean.where(clean.str.fullmatch(r"\d{3}"), "").str.slice(0, 1).astype("string")


def _industry_division(values: pd.Series) -> pd.Series:
    """Coarsen supplied NIC industry codes to their first two digits."""
    clean = _clean_text(values)
    return clean.where(clean.str.fullmatch(r"\d{4,5}"), "").str.slice(0, 2).astype("string")


def _canonical_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=True)


def _peer_group_id(identity: dict[str, object]) -> str:
    digest = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()
    return f"pg_{digest[:24]}"


class PeerGroupEngine:
    """Create assignment/reference tables from one preprocessing person output."""

    def __init__(self, config: RunConfig) -> None:
        if config.minimum_group_size < 2:
            raise ValueError("minimum_group_size must be at least 2")
        self.config = replace(
            config,
            prepared_person_path=Path(config.prepared_person_path),
            output_root=Path(config.output_root),
        )
        self._validate_specifications(self.config.specifications)

    @staticmethod
    def _validate_specifications(specifications: Iterable[PeerGroupSpecification]) -> None:
        seen: set[str] = set()
        for specification in specifications:
            if specification.target_variable in seen:
                raise ValueError(f"Duplicate target specification: {specification.target_variable}")
            seen.add(specification.target_variable)
            for profile in specification.profiles:
                if not profile.levels:
                    raise ValueError(f"Specification {specification.target_variable} has no group levels")
                for level in profile.levels:
                    if not level:
                        raise ValueError(f"Specification {specification.target_variable} contains an empty group level")
                    if any(token in dimension.lower() for dimension in level for token in PROHIBITED_DIMENSION_TOKENS):
                        raise ValueError("FSU and survey weight cannot be peer-group dimensions")

    def _read_metadata(self) -> tuple[dict[str, object], str]:
        metadata_path = self.config.prepared_person_path.parent / "run_metadata.json"
        if not metadata_path.is_file():
            raise PeerGroupFailure(f"Prepared input must have adjacent run_metadata.json: {metadata_path}")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise PeerGroupFailure(f"Invalid preprocessing metadata: {metadata_path}") from error
        run_id = str(metadata.get("run_id", ""))
        if not run_id:
            raise PeerGroupFailure("Preprocessing metadata has no run_id")
        return metadata, run_id

    @staticmethod
    def _profile_for(metadata: dict[str, object]) -> SourceProfile:
        key = (str(metadata.get("release", "")), str(metadata.get("observation", "")))
        try:
            return SOURCE_PROFILES[key]
        except KeyError as error:
            raise PeerGroupFailure(f"No explicit source profile for release/observation {key}") from error

    @staticmethod
    def _profile_for_spec(specification: PeerGroupSpecification, observation: str) -> GroupingProfile | None:
        return next((profile for profile in specification.profiles if profile.observation == observation), None)

    def _load_frame(self, source: SourceProfile) -> pd.DataFrame:
        required = {
            "MoSPI_source_row", "MoSPI_record_key", "MoSPI_release", "MoSPI_observation",
            "MoSPI_design_period", "MoSPI_visit", "MoSPI_prepared_status", "MoSPI_state", "MoSPI_sector",
            source.person_serial_column, *source.context_columns.values(), *source.target_columns.values(),
        }
        if source.release == "2025":
            required.add("MoSPI_month")
        try:
            frame = pd.read_parquet(self.config.prepared_person_path, columns=sorted(required))
        except Exception as error:  # pandas exposes backend-specific exceptions.
            raise PeerGroupFailure(f"Could not read required prepared-person columns: {error}") from error
        absent = required - set(frame.columns)
        if absent:
            raise PeerGroupFailure(f"Prepared input lacks required columns: {sorted(absent)}")
        return frame

    @staticmethod
    def _verify_provenance(frame: pd.DataFrame, metadata: dict[str, object]) -> None:
        for field, expected in (("MoSPI_release", metadata["release"]), ("MoSPI_observation", metadata["observation"]), ("MoSPI_design_period", metadata["design_period"])):
            values = set(_clean_text(frame[field]).unique())
            if values != {str(expected)}:
                raise PeerGroupFailure(f"Prepared input has unexpected or mixed {field}: {sorted(values)}")

    @staticmethod
    def _context(frame: pd.DataFrame, source: SourceProfile) -> pd.DataFrame:
        context = pd.DataFrame(index=frame.index)
        context["state"] = _clean_text(frame["MoSPI_state"])
        context["sector"] = _clean_text(frame["MoSPI_sector"])
        context["cws_status"] = _clean_text(frame[source.context_columns["cws_status"]])
        if "education" in source.context_columns:
            context["education"] = _clean_text(frame[source.context_columns["education"]])
        if "occupation_major_group" in source.context_columns:
            context["occupation_major_group"] = _major_occupation(frame[source.context_columns["occupation_major_group"]])
        if "industry_division" in source.context_columns:
            context["industry_division"] = _industry_division(frame[source.context_columns["industry_division"]])
        return context

    @staticmethod
    def _boundaries(frame: pd.DataFrame, respect_month: bool) -> pd.DataFrame:
        boundaries = pd.DataFrame(index=frame.index)
        for field, output in (("MoSPI_release", "release"), ("MoSPI_observation", "observation"), ("MoSPI_design_period", "design_period"), ("MoSPI_visit", "visit")):
            boundaries[output] = _clean_text(frame[field])
        if respect_month and boundaries["design_period"].eq("post_2025").any():
            if "MoSPI_month" not in frame.columns:
                raise PeerGroupFailure("Post-2025 seasonal target requires MoSPI_month in prepared input")
            boundaries["month"] = _clean_text(frame["MoSPI_month"])
        return boundaries

    @staticmethod
    def _source_observation_ids(frame: pd.DataFrame, source: SourceProfile) -> pd.Series:
        key = _clean_text(frame["MoSPI_record_key"])
        serial = _clean_text(frame[source.person_serial_column])
        fallback = _clean_text(frame["MoSPI_source_row"])
        identifier = key.str.cat(serial.mask(serial.eq(""), fallback), sep="|person=")
        if identifier.duplicated().any():
            raise PeerGroupFailure("Prepared input cannot provide unique source observation identifiers")
        return identifier.astype("string")

    def _build_target(
        self,
        frame: pd.DataFrame,
        source: SourceProfile,
        specification: PeerGroupSpecification,
        metadata: dict[str, object],
        input_run_id: str,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        target = specification.target_variable
        common = pd.DataFrame(index=frame.index)
        common["source_observation_id"] = self._source_observation_ids(frame, source)
        common["MoSPI_record_key"] = _clean_text(frame["MoSPI_record_key"])
        common["MoSPI_source_row"] = frame["MoSPI_source_row"].astype("Int64")
        common["target_variable"] = target
        common["release"] = _clean_text(frame["MoSPI_release"])
        common["observation"] = _clean_text(frame["MoSPI_observation"])
        common["design_period"] = _clean_text(frame["MoSPI_design_period"])
        common["visit"] = _clean_text(frame["MoSPI_visit"])
        common["month"] = _clean_text(frame["MoSPI_month"]) if "MoSPI_month" in frame.columns else pd.Series("", index=frame.index, dtype="string")
        common["reference_run_id"] = input_run_id
        common["input_preprocessing_run_id"] = input_run_id
        common["specification_version"] = PEER_GROUP_SPECIFICATION_VERSION
        common["minimum_group_size"] = self.config.minimum_group_size
        common["peer_group_id"] = pd.Series(pd.NA, index=frame.index, dtype="string")
        common["peer_group_size"] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
        common["grouping_profile"] = pd.Series(pd.NA, index=frame.index, dtype="string")
        common["grouping_dimensions"] = pd.Series(pd.NA, index=frame.index, dtype="string")
        common["grouping_values"] = pd.Series(pd.NA, index=frame.index, dtype="string")
        common["backoff_level"] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
        common["assessability_status"] = "NOT_ASSESSABLE"
        common["not_assessable_reason"] = "TARGET_UNAVAILABLE_FOR_RELEASE_OBSERVATION"

        profile = self._profile_for_spec(specification, str(metadata["observation"]))
        target_column = source.target_columns.get(target)
        if profile is None or target_column is None:
            return common, pd.DataFrame()

        common["grouping_profile"] = profile.name
        raw_target = _clean_text(frame[target_column])
        numeric_target = pd.to_numeric(raw_target, errors="coerce")
        ready = _clean_text(frame["MoSPI_prepared_status"]).eq(READY_STATUS)
        target_valid = raw_target.ne("") & numeric_target.notna()
        common.loc[~ready, "not_assessable_reason"] = "PREPARED_RECORD_NOT_READY"
        common.loc[ready & ~target_valid, "not_assessable_reason"] = "TARGET_VALUE_MISSING_OR_INVALID"
        common.loc[ready & target_valid, "not_assessable_reason"] = "NO_CONFIGURED_GROUP_MEETS_MINIMUM"

        context = self._context(frame, source)
        boundaries = self._boundaries(frame, specification.respect_post_2025_month)
        base = pd.concat([boundaries, context], axis=1)
        eligible = ready & target_valid
        references: list[pd.DataFrame] = []
        assigned = pd.Series(False, index=frame.index)

        for level_number, dimensions in enumerate(profile.levels):
            unavailable = [dimension for dimension in dimensions if dimension not in base.columns]
            if unavailable:
                LOGGER.warning("Skipping unavailable configured level for %s: %s", target, unavailable)
                continue
            boundary_columns = list(boundaries.columns)
            key_columns = [*boundary_columns, *dimensions]
            complete_context = base[key_columns].ne("").all(axis=1)
            population_mask = eligible & complete_context
            if not population_mask.any():
                continue
            population = base.loc[population_mask, key_columns].copy()
            population["_size"] = population.groupby(key_columns, sort=True, dropna=False)[key_columns[0]].transform("size").astype("Int64")
            candidates = population.loc[population["_size"].ge(self.config.minimum_group_size)].copy()
            candidate_indexes = candidates.index[~assigned.loc[candidates.index]]
            if len(candidate_indexes) == 0:
                continue
            chosen = candidates.loc[candidate_indexes]
            unique_groups = chosen.drop(columns="_size").drop_duplicates().sort_values(key_columns, kind="mergesort")
            identities: list[dict[str, object]] = []
            for row in unique_groups.itertuples(index=False):
                values = dict(zip(key_columns, row, strict=True))
                identities.append({
                    "specification_version": PEER_GROUP_SPECIFICATION_VERSION,
                    "target_variable": target,
                    "grouping_profile": profile.name,
                    "grouping_dimensions": list(dimensions),
                    "boundary_values": {name: str(values[name]) for name in boundary_columns},
                    "dimension_values": {name: str(values[name]) for name in dimensions},
                })
            unique_groups["peer_group_id"] = [_peer_group_id(identity) for identity in identities]
            group_map = unique_groups[[*key_columns, "peer_group_id"]]
            chosen = chosen.merge(group_map, on=key_columns, how="left", validate="many_to_one", sort=False).set_axis(candidate_indexes)
            common.loc[candidate_indexes, "peer_group_id"] = chosen["peer_group_id"].astype("string")
            common.loc[candidate_indexes, "peer_group_size"] = chosen["_size"].astype("Int64")
            common.loc[candidate_indexes, "grouping_dimensions"] = _canonical_json(list(dimensions))
            value_rows = chosen.loc[:, list(dimensions)].to_dict(orient="records")
            common.loc[candidate_indexes, "grouping_values"] = [_canonical_json({key: str(value) for key, value in row.items()}) for row in value_rows]
            common.loc[candidate_indexes, "backoff_level"] = level_number
            common.loc[candidate_indexes, "assessability_status"] = "ASSESSABLE"
            common.loc[candidate_indexes, "not_assessable_reason"] = pd.NA
            assigned.loc[candidate_indexes] = True

            selected_references = unique_groups.copy()
            selected_references["target_variable"] = target
            selected_references["grouping_profile"] = profile.name
            selected_references["grouping_dimensions"] = _canonical_json(list(dimensions))
            selected_references["grouping_values"] = [
                _canonical_json({dimension: str(row[dimension]) for dimension in dimensions})
                for _, row in selected_references.iterrows()
            ]
            size_map = chosen.groupby("peer_group_id", sort=False)["_size"].first()
            selected_references["peer_group_size"] = selected_references["peer_group_id"].map(size_map).astype("Int64")
            selected_references["backoff_level"] = level_number
            selected_references["reference_run_id"] = input_run_id
            selected_references["specification_version"] = PEER_GROUP_SPECIFICATION_VERSION
            references.append(selected_references[[
                "peer_group_id", "target_variable", "grouping_profile", "grouping_dimensions", "grouping_values",
                "peer_group_size", "backoff_level", "reference_run_id", "specification_version", *boundary_columns,
            ]])

        reference_table = pd.concat(references, ignore_index=True) if references else pd.DataFrame()
        return common, reference_table

    @staticmethod
    def _report(assignments: pd.DataFrame, references: pd.DataFrame) -> dict[str, object]:
        def counts(values: pd.Series) -> dict[str, int]:
            return {str(key): int(value) for key, value in values.value_counts(dropna=False).sort_index().items()}

        target_rows: list[dict[str, object]] = []
        for target, group in assignments.groupby("target_variable", sort=True):
            count = len(group)
            assessable = int(group["assessability_status"].eq("ASSESSABLE").sum())
            backoff_counts = counts(group["backoff_level"])
            target_rows.append({
                "target_variable": target,
                "assignments": count,
                "assessable": assessable,
                "assessable_percent": 100 * assessable / count if count else 0.0,
                "groups": int(references.loc[references["target_variable"].eq(target), "peer_group_id"].nunique()) if not references.empty else 0,
                "not_assessable": count - assessable,
                "not_assessable_percent": 100 * (count - assessable) / count if count else 0.0,
                "backoff_distribution": backoff_counts,
                "backoff_percent": {level: 100 * value / count for level, value in backoff_counts.items()},
                "not_assessable_reasons": counts(group.loc[group["assessability_status"].eq("NOT_ASSESSABLE"), "not_assessable_reason"]),
            })
        size_distribution = references["peer_group_size"].describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]).to_dict() if not references.empty else {}
        return {
            "target_summary": target_rows,
            "number_of_groups": int(references["peer_group_id"].nunique()) if not references.empty else 0,
            "group_size_distribution": size_distribution,
            "grouping_dimension_sets": references[["target_variable", "grouping_profile", "backoff_level", "grouping_dimensions"]].drop_duplicates().sort_values(["target_variable", "grouping_profile", "backoff_level"]).to_dict(orient="records") if not references.empty else [],
            "release_visit_coverage": assignments[["release", "observation", "design_period", "visit", "month"]].drop_duplicates().sort_values(["release", "observation", "visit", "month"]).to_dict(orient="records"),
        }

    def run(self) -> Path:
        if not self.config.prepared_person_path.is_file():
            raise PeerGroupFailure(f"Prepared person input does not exist: {self.config.prepared_person_path}")
        metadata, input_run_id = self._read_metadata()
        source = self._profile_for(metadata)
        frame = self._load_frame(source)
        self._verify_provenance(frame, metadata)
        run_id = self.config.run_id or str(uuid.uuid4())
        output_dir = self.config.output_root / f"{metadata['release']}_{metadata['observation']}_{run_id}"
        output_dir.mkdir(parents=True, exist_ok=False)
        assignments, reference_tables = zip(*(self._build_target(frame, source, specification, metadata, input_run_id) for specification in self.config.specifications))
        assignment_table = pd.concat(assignments, ignore_index=True)
        reference_table = pd.concat(reference_tables, ignore_index=True) if any(not table.empty for table in reference_tables) else pd.DataFrame()
        assignment_table.sort_values(["target_variable", "source_observation_id"], kind="mergesort", inplace=True, ignore_index=True)
        if not reference_table.empty:
            reference_table.drop_duplicates(subset=["peer_group_id"], inplace=True)
            reference_table.sort_values(["target_variable", "peer_group_id"], kind="mergesort", inplace=True, ignore_index=True)
        for column in REFERENCE_COLUMNS:
            if column not in reference_table.columns:
                reference_table[column] = pd.Series(pd.NA, index=reference_table.index, dtype="string")
        reference_table = reference_table.loc[:, list(REFERENCE_COLUMNS)]
        assignment_table.to_parquet(output_dir / "peer_group_assignments.parquet", index=False)
        reference_table.to_parquet(output_dir / "peer_group_references.parquet", index=False)
        report = self._report(assignment_table, reference_table)
        run_metadata = {
            "run_id": run_id,
            "processing_timestamp_utc": utc_now(),
            "software_version": SOFTWARE_VERSION,
            "specification_version": PEER_GROUP_SPECIFICATION_VERSION,
            "input_preprocessing_run_id": input_run_id,
            "input_prepared_person_path": str(self.config.prepared_person_path),
            "release": metadata["release"],
            "observation": metadata["observation"],
            "design_period": metadata["design_period"],
            "minimum_group_size": self.config.minimum_group_size,
            "target_variables": [specification.target_variable for specification in self.config.specifications],
            "output_files": ["peer_group_assignments.parquet", "peer_group_references.parquet", "peer_group_report.json", "peer_group_report.md", "run_metadata.json"],
        }
        write_json(output_dir / "peer_group_report.json", report)
        write_json(output_dir / "run_metadata.json", run_metadata)
        write_markdown_report(output_dir, report, run_metadata)
        LOGGER.info("Created %s peer-group assignments and %s reference groups", len(assignment_table), len(reference_table))
        return output_dir
