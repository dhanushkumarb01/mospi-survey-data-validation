"""Structured issue and report writing for PLFS preparation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class Issue:
    severity: str
    stage: str
    issue_code: str
    message: str
    dataset_level: str | None = None
    field: str | None = None
    source_row: int | None = None
    record_key: str | None = None
    observed_value: str | None = None
    count: int = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, content: Any) -> None:
    path.write_text(json.dumps(content, indent=2, sort_keys=True, default=str), encoding="utf-8")


def write_reports(output_dir: Path, report: dict[str, Any], issues: list[Issue], metadata: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    issue_rows = [asdict(issue) for issue in issues]
    pd.DataFrame(issue_rows, columns=list(Issue.__dataclass_fields__)).to_csv(output_dir / "issue_log.csv", index=False)
    write_json(output_dir / "preprocessing_report.json", report)
    write_json(output_dir / "run_metadata.json", metadata)
    lines = [
        "# PLFS preprocessing report",
        "",
        f"- Run ID: `{metadata['run_id']}`",
        f"- Release / observation: `{metadata['release']}` / `{metadata['observation']}`",
        f"- Overall status: **{report['overall_status']}**",
        f"- Issues: {report['issue_counts']}",
        "",
        "## Stage summary",
        "",
        "| Stage | Status | Notes |",
        "|---|---|---|",
    ]
    lines.extend(f"| {row['stage']} | {row['status']} | {row['summary']} |" for row in report["stages"])
    lines.extend(["", "## Boundaries", "", "- No records were dropped, imputed, corrected, scored, or treated as ML features.", "- Raw values remain in the prepared tables; standardised values are added in `MoSPI_*` columns."])
    (output_dir / "preprocessing_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
