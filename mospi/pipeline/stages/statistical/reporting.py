"""Run report helpers for the Statistical Evidence Layer."""

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
    lines = [
        "# PLFS statistical evidence report", "",
        f"- Statistical run ID: `{metadata['run_id']}`",
        f"- Release / observation: `{metadata['release']}` / `{metadata['observation']}`",
        f"- Peer-group run: `{metadata['peer_group_run_id']}`",
        f"- Method version: `{metadata['statistical_method_version']}`", "",
        "## Target summary", "",
        "| Target | Records | Assessable | Assessability (%) | Zero-MAD groups |", "|---|---:|---:|---:|---:|",
    ]
    for row in report["target_summary"]:
        lines.append(f"| {row['target_variable']} | {row['records']:,} | {row['assessable']:,} | {row['assessability_percent']:.2f} | {row['zero_mad_groups']:,} |")
    lines.extend(["", "## Interpretation boundary", "", "This report describes statistical unusualness relative to assigned peer distributions. It does not identify errors, fraud, fabrication, or invalid responses.", "", "## Outputs", ""])
    for name in metadata["output_files"]:
        lines.append(f"- `{name}`")
    if report.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
