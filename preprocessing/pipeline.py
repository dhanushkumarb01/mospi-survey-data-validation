"""Deterministic, traceable preparation of supplied PLFS CSV deliveries."""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .config import CONTRACTS, DatasetContract
from .reporting import Issue, utc_now, write_reports

LOGGER = logging.getLogger(__name__)
SOFTWARE_VERSION = "0.1.2"


class PreprocessingFailure(RuntimeError):
    """Raised after reports are written when a critical preparation gate fails."""


@dataclass(frozen=True)
class RunConfig:
    input_root: Path
    output_root: Path
    contract_name: str
    run_id: str | None = None
    issue_sample_limit: int = 1_000
    write_prepared_data: bool = True

    def contract(self) -> DatasetContract:
        try:
            return CONTRACTS[self.contract_name]
        except KeyError as error:
            raise ValueError(f"Unknown PLFS contract: {self.contract_name}") from error


def _normalise_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _normalise_month(value: object) -> str:
    value = _normalise_text(value)
    if not value:
        return ""
    try:
        as_float = float(value)
    except ValueError:
        return value
    return str(int(as_float)) if as_float.is_integer() else value


def _status(issues: Iterable[Issue]) -> str:
    severities = {issue.severity for issue in issues}
    return "failure" if "failure" in severities else "warning" if "warning" in severities else "valid"


class PLFSPreprocessor:
    """Prepare one documented PLFS household/person delivery without inference."""

    def __init__(self, config: RunConfig) -> None:
        self.config = replace(config, input_root=Path(config.input_root), output_root=Path(config.output_root))
        self.contract = self.config.contract()
        self.issues: list[Issue] = []
        self.stages: list[dict[str, str]] = []

    def _add_issue(self, **kwargs: Any) -> None:
        self.issues.append(Issue(**kwargs))

    def _stage(self, name: str, start: int, summary: str) -> None:
        stage_issues = self.issues[start:]
        self.stages.append({"stage": name, "status": _status(stage_issues), "summary": summary})

    def _read(self, path: Path) -> pd.DataFrame:
        # Strings preserve formatting, including the 2025 `1.0` versus `01`
        # month values, and prevent identifiers from losing leading zeroes.
        return pd.read_csv(path, dtype="string", keep_default_na=False, na_filter=False, low_memory=False)

    def _schema_validate(self, frame: pd.DataFrame, level: str, path: Path) -> None:
        start = len(self.issues)
        fields = self.contract.fields(level)
        required = set(fields.values())
        observed = set(frame.columns)
        missing = sorted(required - observed)
        if missing:
            self._add_issue(severity="failure", stage="schema", issue_code="MISSING_REQUIRED_COLUMN", message="Required documented PLFS columns are absent.", dataset_level=level, field=", ".join(missing), count=len(missing))
        expected_count = self.contract.expected_household_columns if level == "household" else self.contract.expected_person_columns
        if len(frame.columns) != expected_count:
            self._add_issue(severity="warning", stage="schema", issue_code="COLUMN_COUNT_MISMATCH", message=f"Observed {len(frame.columns)} columns; documented delivered count is {expected_count}.", dataset_level=level, count=abs(len(frame.columns) - expected_count))
        whitelist = self.contract.expected_household_headers if level == "household" else self.contract.expected_person_headers
        if whitelist is None:
            self._add_issue(severity="warning", stage="schema", issue_code="FULL_HEADER_WHITELIST_UNCONFIRMED", message="No HSD/NSO-reviewed complete header whitelist is configured; required fields and documented column count were checked.", dataset_level=level)
        else:
            for name in sorted(observed - whitelist):
                self._add_issue(severity="warning", stage="schema", issue_code="UNEXPECTED_COLUMN", message="Column is not in the configured release header whitelist.", dataset_level=level, field=name)
            for name in sorted(whitelist - observed):
                self._add_issue(severity="failure", stage="schema", issue_code="MISSING_EXPECTED_COLUMN", message="Configured release header is absent.", dataset_level=level, field=name)
        for column in required & observed:
            if not pd.api.types.is_string_dtype(frame[column]):
                self._add_issue(severity="failure", stage="schema", issue_code="UNEXPECTED_INGEST_DTYPE", message="PLFS raw fields must be ingested as strings to preserve identifiers and blank/zero distinction.", dataset_level=level, field=column)
        self._stage(f"schema:{level}", start, f"{len(frame):,} rows, {len(frame.columns)} columns; {len(missing)} missing required columns.")

    def _canonical_key(self, frame: pd.DataFrame, level: str) -> pd.Series:
        fields = self.contract.fields(level)
        parts: list[pd.Series] = []
        for concept in self.contract.household_key:
            raw = frame[fields[concept]]
            part = raw.map(_normalise_month if concept == "month" else _normalise_text)
            parts.append(part.astype("string"))
        key = parts[0]
        for part in parts[1:]:
            key = key.str.cat(part, sep="|")
        return key

    def _record_issue_samples(self, mask: pd.Series, frame: pd.DataFrame, level: str, field: str, code: str, message: str, *, key: pd.Series | None = None, severity: str = "warning") -> None:
        indexes = frame.index[mask]
        total = len(indexes)
        for index in indexes[: self.config.issue_sample_limit]:
            observed = str(key.loc[index]) if field == "MoSPI_record_key" and key is not None else ("<complete raw row>" if field == "__row__" else str(frame.loc[index, field]))
            self._add_issue(severity=severity, stage="value", issue_code=code, message=message, dataset_level=level, field=field, source_row=int(index) + 2, record_key=None if key is None else str(key.loc[index]), observed_value=observed, count=total)
        if total > self.config.issue_sample_limit:
            self._add_issue(severity=severity, stage="value", issue_code=f"{code}_ADDITIONAL", message="Additional affected records are represented by this aggregate issue.", dataset_level=level, field=field, count=total - self.config.issue_sample_limit)

    def _value_and_key_validate(self, frame: pd.DataFrame, level: str) -> tuple[pd.Series, pd.Series]:
        start = len(self.issues)
        fields = self.contract.fields(level)
        key = self._canonical_key(frame, level)
        invalid_key = pd.Series(False, index=frame.index)
        for concept in self.contract.household_key:
            raw_name = fields[concept]
            blank = frame[raw_name].map(_normalise_text).eq("")
            invalid_key |= blank
            self._record_issue_samples(blank, frame, level, raw_name, "INCOMPLETE_KEY", "A documented household-key component is blank.", key=key, severity="failure")
        if level == "person":
            serial_name = fields[self.contract.person_serial]
            blank = frame[serial_name].map(_normalise_text).eq("")
            invalid_key |= blank
            self._record_issue_samples(blank, frame, level, serial_name, "MISSING_PERSON_SERIAL", "The documented person serial is blank.", key=key, severity="failure")
        for concept, allowed in self.contract.documented_code_values.items():
            if concept not in fields:
                continue
            raw_name = fields[concept]
            values = frame[raw_name].map(_normalise_month if concept == "month" else _normalise_text)
            invalid = values.ne("") & ~values.isin(allowed)
            self._record_issue_samples(invalid, frame, level, raw_name, "UNSUPPORTED_DOCUMENTED_CODE", "Value is outside the documented code set configured for this delivery.", key=key)
        # These fields are explicitly described as numeric quantities in the
        # release README/layout material.  This is a syntax check only: no
        # undocumented range, conversion, or correction is imposed.
        numeric_concepts = {"household_size", "weight"} if level == "household" else {"age", "weight", "earnings_salaried", "earnings_self_employed"}
        for concept in numeric_concepts & set(fields):
            raw_name = fields[concept]
            values = frame[raw_name].map(_normalise_text)
            invalid_numeric = values.ne("") & pd.to_numeric(values, errors="coerce").isna()
            self._record_issue_samples(invalid_numeric, frame, level, raw_name, "INVALID_NUMERIC_REPRESENTATION", "Documented numeric field contains non-numeric raw text; value was retained unchanged.", key=key)
        duplicate_key = key.duplicated(keep=False) & ~invalid_key
        if level == "person":
            serial = frame[fields[self.contract.person_serial]].map(_normalise_text).astype("string")
            full_key = key.str.cat(serial, sep="|")
            duplicate_key = full_key.duplicated(keep=False) & ~invalid_key
        self._record_issue_samples(duplicate_key, frame, level, "MoSPI_record_key", "DUPLICATE_EXPECTED_KEY", "Documented expected key occurs more than once.", key=key, severity="failure")
        full_duplicate = frame.duplicated(keep=False)
        self._record_issue_samples(full_duplicate, frame, level, "__row__", "FULL_DUPLICATE_ROW", "An identical complete raw row occurs more than once.", key=key, severity="warning")
        self._stage(f"value_and_key:{level}", start, f"Checked documented codes, incomplete keys, duplicate expected keys, and complete duplicate rows.")
        # Duplicate expected keys are retained, but cannot be represented as a
        # single unambiguous prepared observation for downstream processing.
        return key, invalid_key | duplicate_key

    def _missingness_summary(self, frame: pd.DataFrame, level: str) -> list[dict[str, Any]]:
        fields = self.contract.fields(level)
        rows: list[dict[str, Any]] = []
        gated = {"principal_industry", "training_completed", "day7_activity2"}
        for concept, column in fields.items():
            values = frame[column].map(_normalise_text)
            blank = values.eq("")
            zeros = values.eq("0") | values.eq("0.0")
            classification = (
                "structural_identifier_missing" if concept in set(self.contract.household_key) | {self.contract.person_serial}
                else "blank_applicability_unresolved" if concept in gated
                else "raw_blank_unclassified"
            )
            rows.append({"level": level, "concept": concept, "raw_field": column, "blank_records": int(blank.sum()), "valid_zero_records": int((zeros & ~blank).sum()), "blank_interpretation": classification})
        return rows

    def _add_prepared_columns(self, frame: pd.DataFrame, level: str, key: pd.Series, invalid_key: pd.Series) -> pd.DataFrame:
        result = frame.copy()
        fields = self.contract.fields(level)
        result.insert(0, "MoSPI_source_row", pd.Series(range(2, len(frame) + 2), dtype="Int64"))
        result.insert(1, "MoSPI_record_key", key)
        result.insert(2, "MoSPI_release", self.contract.release)
        result.insert(3, "MoSPI_observation", self.contract.observation)
        result.insert(4, "MoSPI_design_period", self.contract.design_period)
        result.insert(5, "MoSPI_cadence", self.contract.cadence)
        result.insert(6, "MoSPI_key_status", pd.Series("valid", index=frame.index, dtype="string").mask(invalid_key, "not_assessable_key_integrity"))
        for concept in ("month", "quarter", "visit", "panel", "state", "sector", "stratum", "fsu", "sss", "weight"):
            if concept in fields:
                normalizer = _normalise_month if concept == "month" else _normalise_text
                result[f"MoSPI_{concept}"] = frame[fields[concept]].map(normalizer).astype("string")
        return result

    def _link(self, household: pd.DataFrame, persons: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
        start = len(self.issues)
        counts = household["MoSPI_record_key"].value_counts(dropna=False)
        person_counts = persons["MoSPI_record_key"].map(counts).fillna(0).astype("Int64")
        status = pd.Series("matched", index=persons.index, dtype="string")
        status = status.mask(person_counts.eq(0), "unmatched_household")
        status = status.mask(person_counts.gt(1), "ambiguous_multiple_households")
        status = status.mask(persons["MoSPI_key_status"].ne("valid"), "not_assessable_key_integrity")
        persons["MoSPI_household_link_status"] = status
        persons["MoSPI_household_match_count"] = person_counts
        for value, severity, code in (("unmatched_household", "failure", "UNMATCHED_PERSON_HOUSEHOLD"), ("ambiguous_multiple_households", "failure", "AMBIGUOUS_PERSON_HOUSEHOLD_LINK")):
            mask = status.eq(value)
            for index in persons.index[mask][: self.config.issue_sample_limit]:
                self._add_issue(severity=severity, stage="linkage", issue_code=code, message="Person-to-household linkage is not uniquely resolvable; record is retained and marked not assessable for linkage-dependent downstream work.", dataset_level="person", source_row=int(persons.loc[index, "MoSPI_source_row"]), record_key=str(persons.loc[index, "MoSPI_record_key"]))
        summary = {"matched_persons": int(status.eq("matched").sum()), "unmatched_persons": int(status.eq("unmatched_household").sum()), "ambiguous_persons": int(status.eq("ambiguous_multiple_households").sum()), "not_assessable_persons": int(status.eq("not_assessable_key_integrity").sum())}
        self._stage("household_person_linkage", start, f"{summary['matched_persons']:,} matched; {summary['unmatched_persons']:,} unmatched; {summary['ambiguous_persons']:,} ambiguous.")
        return persons, summary

    def run(self) -> Path:
        run_id = self.config.run_id or str(uuid.uuid4())
        output_dir = self.config.output_root / f"{self.contract.release}_{self.contract.observation}_{run_id}"
        output_dir.mkdir(parents=True, exist_ok=False)
        paths = {level: self.contract.file_path(self.config.input_root, level) for level in ("household", "person")}
        metadata: dict[str, Any] = {"run_id": run_id, "processing_timestamp_utc": utc_now(), "software_version": SOFTWARE_VERSION, "survey": "PLFS", "release": self.contract.release, "observation": self.contract.observation, "design_period": self.contract.design_period, "cadence": self.contract.cadence, "configuration_contract": self.config.contract_name, "input_files": {level: str(path) for level, path in paths.items()}, "reference_files": list(self.contract.reference_files)}
        start = len(self.issues)
        missing_files = [str(path) for path in paths.values() if not path.is_file()]
        if missing_files:
            self._add_issue(severity="failure", stage="ingestion", issue_code="INPUT_FILE_NOT_FOUND", message="Configured raw PLFS input file does not exist.", observed_value="; ".join(missing_files), count=len(missing_files))
            frames: dict[str, pd.DataFrame] = {}
        else:
            frames = {level: self._read(path) for level, path in paths.items()}
        self._stage("ingestion", start, "Raw files read without modification." if not missing_files else "Input files missing; preparation cannot continue.")
        metadata["input_shape"] = {level: {"rows": len(frame), "columns": len(frame.columns)} for level, frame in frames.items()}
        if missing_files:
            return self._finish_failure(output_dir, metadata, [], {})
        for level, frame in frames.items():
            self._schema_validate(frame, level, paths[level])
        if any(issue.severity == "failure" and issue.stage == "schema" for issue in self.issues):
            return self._finish_failure(output_dir, metadata, [], {})
        keys: dict[str, pd.Series] = {}
        invalid: dict[str, pd.Series] = {}
        for level, frame in frames.items():
            keys[level], invalid[level] = self._value_and_key_validate(frame, level)
        missingness = [row for level, frame in frames.items() for row in self._missingness_summary(frame, level)]
        missing_path = output_dir / "missingness_summary.csv"
        pd.DataFrame(missingness).to_csv(missing_path, index=False)
        self.stages.append({"stage": "missingness_applicability", "status": "valid", "summary": "Raw blanks and valid zero values were counted separately; no values were imputed or converted."})
        prepared_hh = self._add_prepared_columns(frames["household"], "household", keys["household"], invalid["household"])
        prepared_person = self._add_prepared_columns(frames["person"], "person", keys["person"], invalid["person"])
        prepared_person, linkage = self._link(prepared_hh, prepared_person)
        prepared_person["MoSPI_prepared_status"] = prepared_person["MoSPI_household_link_status"].replace({"matched": "ready_for_downstream_preparation_only"}).astype("string")
        prepared_hh["MoSPI_prepared_status"] = prepared_hh["MoSPI_key_status"].replace({"valid": "ready_for_downstream_preparation_only"}).astype("string")
        if self.config.write_prepared_data:
            prepared_hh.to_parquet(output_dir / "prepared_households.parquet", index=False)
            prepared_person.to_parquet(output_dir / "prepared_persons.parquet", index=False)
        standardization = [{"transformation": "trim_identifier_and_context_text", "purpose": "deterministic key construction; raw columns retained", "affected_fields": ", ".join(self.contract.household_key)}, {"transformation": "month_to_integer_text" if "month" in self.contract.household_key else "not_applicable", "purpose": "2025 household/person linkage only; raw month retained", "affected_fields": "month" if "month" in self.contract.household_key else ""}]
        pd.DataFrame(standardization).to_csv(output_dir / "standardization_summary.csv", index=False)
        metadata["output_files"] = ["prepared_households.parquet", "prepared_persons.parquet", "missingness_summary.csv", "standardization_summary.csv"] if self.config.write_prepared_data else ["missingness_summary.csv", "standardization_summary.csv"]
        metadata["prepared_rows"] = {"household": len(prepared_hh), "person": len(prepared_person)}
        return self._finish(output_dir, metadata, missingness, linkage)

    def _finish_failure(self, output_dir: Path, metadata: dict[str, Any], missingness: list[dict[str, Any]], linkage: dict[str, int]) -> Path:
        metadata["completed_with_critical_failure"] = True
        return self._finish(output_dir, metadata, missingness, linkage, raise_failure=True)

    def _finish(self, output_dir: Path, metadata: dict[str, Any], missingness: list[dict[str, Any]], linkage: dict[str, int], *, raise_failure: bool = False) -> Path:
        counts = Counter(issue.severity for issue in self.issues)
        report = {"overall_status": _status(self.issues), "stages": self.stages, "issue_counts": dict(counts), "linkage": linkage, "missingness_summary_file": "missingness_summary.csv" if missingness else None, "scope": "deterministic PLFS preparation only; no anomaly scoring, ML, automatic correction, or record dropping."}
        write_reports(output_dir, report, self.issues, metadata)
        if raise_failure:
            raise PreprocessingFailure(f"Critical preparation failure. See {output_dir}")
        return output_dir
