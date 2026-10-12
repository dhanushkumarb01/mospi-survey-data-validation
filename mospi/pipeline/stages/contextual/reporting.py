"""Deterministic report helpers for contextual evidence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, content: Any) -> None:
    path.write_text(json.dumps(content, indent=2, sort_keys=True, default=str), encoding="utf-8")


def write_markdown_report(path: Path, report: dict[str, Any], metadata: dict[str, Any]) -> None:
    summary = report["target_summary"]
    lines = [
        "# PLFS contextual evidence report", "",
        f"- Contextual run ID: `{metadata['run_id']}`",
        f"- Release / observation: `{metadata['release']}` / `{metadata['observation']}`",
        f"- Peer-group run: `{metadata['peer_group_run_id']}`",
        f"- Method version: `{metadata['contextual_method_version']}`", "",
        "## Target summary", "",
        "| Target | Records | Assessable | Not assessable | Reference groups |", "|---|---:|---:|---:|---:|",
        f"| {summary['target_variable']} | {summary['records']:,} | {summary['assessable']:,} | {summary['not_assessable']:,} | {summary['reference_groups']:,} |", "",
        "## Interpretation boundary", "",
        "Conditional frequency describes how often an observed occupation code occurs among comparable observations with a valid three-digit occupation code. It is contextual response evidence, not an error-likelihood estimate, and it makes no error, fraud, fabrication, or correction decision.", "",
        "## Outputs", "",
    ]
    lines.extend(f"- `{name}`" for name in metadata["output_files"])
    if report.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
