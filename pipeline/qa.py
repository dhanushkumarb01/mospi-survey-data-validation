"""Run quality gates (plan W0.3).

After each stage the batch checks that its output is complete and not
degraded.  A failed gate stops the pipeline before fusion, so no queue is
published from a broken stage.  This is the class of defect that once let an
all-"not assessable" historical stage and an empty stage pass silently
(audit H10, N2).

Gates per stage
* required files present and non-empty;
* one evidence row per prepared record (per target where the stage is long);
* identity columns never entirely blank;
* the share of assessable rows above a floor (default 1%) — a stage that
  assesses nothing is a failure, not a quiet batch;
* optionally, the assessable share within +/- ``tolerance`` (relative) of a
  baseline run of the same release (e.g. the last approved run).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import duckdb

from survey_rules.schema import column_map


class QAGateFailure(RuntimeError):
    """A stage output failed a quality gate; nothing downstream is published."""


@dataclass(frozen=True)
class StageContract:
    files: tuple[str, ...]
    evidence_file: str | None = None
    rows_per_record: str | None = None     # column whose distinct values multiply the record count (e.g. target_variable)
    status_column: str | None = None
    identity_columns: tuple[str, ...] = ()


CONTRACTS: dict[str, StageContract] = {
    "statistical": StageContract(("statistical_evidence.parquet", "run_metadata.json"), "statistical_evidence.parquet", "target_variable",
                                 "statistical_assessability_status", ("source_observation_id", "target_variable")),
    "contextual": StageContract(("contextual_evidence.parquet", "run_metadata.json"), "contextual_evidence.parquet", None,
                                "contextual_assessability_status", ("source_observation_id",)),
    "ml": StageContract(("conditional_model_evidence.parquet", "run_metadata.json"), "conditional_model_evidence.parquet", "target",
                        "assessability_status", ("source_observation_id", "target")),
    "pattern": StageContract(("pattern_evidence.parquet", "run_metadata.json"), "pattern_evidence.parquet", None, "assessability_status",
                             ("state", "sector", "fsu")),
    "historical": StageContract(("historical_record_evidence.parquet", "aggregate_indicators.parquet", "run_metadata.json"),
                                "historical_record_evidence.parquet", "target_variable", "assessability_status",
                                ("source_observation_id", "release", "design_period")),
    "integrity": StageContract(("integrity_violations.parquet", "rule_dry_run.json", "run_metadata.json")),
    "fusion": StageContract(("fused_cases.parquet", "group_priorities.parquet", "fusion_report.json", "run_metadata.json"), "fused_cases.parquet", None,
                            None, ("case_id", "state", "sector", "fsu", "tier")),
}


def _scalar(sql: str, path: Path) -> object:
    with duckdb.connect() as connection:
        return connection.execute(sql, [str(path)]).fetchone()[0]


def check_stage(name: str, directory: Path, prepared_records: int, *, minimum_assessable_share: float = 0.01,
                baseline: Path | None = None, tolerance: float = 0.10) -> dict[str, object]:
    contract = CONTRACTS[name]
    directory = Path(directory)
    findings: list[str] = []
    for file in contract.files:
        path = directory / file
        if not path.is_file() or path.stat().st_size == 0:
            findings.append(f"missing or empty {file}")
    result: dict[str, object] = {"stage": name, "directory": str(directory)}
    if contract.evidence_file and not findings:
        path = directory / contract.evidence_file
        physical = column_map(path)
        rows = int(_scalar("SELECT COUNT(*) FROM read_parquet(?)", path))
        result["rows"] = rows
        if rows == 0:
            findings.append(f"{contract.evidence_file} has no rows")
        if contract.rows_per_record:
            multiplier = int(_scalar(f'SELECT COUNT(DISTINCT "{physical[contract.rows_per_record]}") FROM read_parquet(?)', path))
            expected = prepared_records * multiplier
            if rows != expected:
                findings.append(f"{contract.evidence_file} has {rows:,} rows; expected {expected:,} ({prepared_records:,} records x {multiplier})")
        elif name in ("contextual",) and rows != prepared_records:
            findings.append(f"{contract.evidence_file} has {rows:,} rows; expected one per prepared record ({prepared_records:,})")
        elif name == "fusion" and rows < prepared_records:
            findings.append(f"{contract.evidence_file} has {rows:,} cases; expected at least the {prepared_records:,} prepared records")
        for column in contract.identity_columns:
            if column not in physical:
                findings.append(f"{contract.evidence_file} lacks {column}")
                continue
            blank = int(_scalar(f"SELECT COUNT(*) FROM read_parquet(?) WHERE COALESCE(TRIM(CAST(\"{physical[column]}\" AS VARCHAR)), '') <> ''", path))
            if rows and blank == 0:
                findings.append(f"{contract.evidence_file}: column {column} is entirely blank")
        if contract.status_column and contract.status_column in physical and rows:
            share = float(_scalar(f"SELECT AVG(CASE WHEN \"{physical[contract.status_column]}\" = 'ASSESSABLE' THEN 1.0 ELSE 0.0 END) FROM read_parquet(?)", path))
            result["assessable_share"] = share
            if share < minimum_assessable_share:
                findings.append(f"only {share:.2%} of {contract.evidence_file} rows are assessable (floor {minimum_assessable_share:.0%})")
            if baseline is not None and (Path(baseline) / contract.evidence_file).is_file():
                base_path = Path(baseline) / contract.evidence_file
                base_physical = column_map(base_path)
                if contract.status_column in base_physical:
                    base_share = float(_scalar(f"SELECT AVG(CASE WHEN \"{base_physical[contract.status_column]}\" = 'ASSESSABLE' THEN 1.0 ELSE 0.0 END) FROM read_parquet(?)", base_path))
                    result["baseline_assessable_share"] = base_share
                    if base_share and abs(share - base_share) / base_share > tolerance:
                        findings.append(f"assessable share {share:.2%} differs from the baseline {base_share:.2%} by more than {tolerance:.0%}")
    result["status"] = "PASSED" if not findings else "FAILED"
    result["findings"] = findings
    if findings:
        raise QAGateFailure(f"Quality gate failed for {name} ({directory}): " + "; ".join(findings))
    return result


def prepared_record_count(prepared_persons: Path) -> int:
    # Counted from the file itself: evaluation subsets inherit their parent's metadata.
    return int(_scalar("SELECT COUNT(*) FROM read_parquet(?)", Path(prepared_persons)))
