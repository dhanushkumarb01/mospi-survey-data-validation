"""Small deterministic report writers shared by the ML components."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")


def write_markdown(path: Path, metadata: dict[str, Any], report: dict[str, Any]) -> None:
    lines = [
        "# PLFS ML evidence report", "",
        f"- Run ID: `{metadata['run_id']}`",
        f"- Release / observation: `{metadata['release']}` / `{metadata['observation']}`",
        f"- Preprocessing run: `{metadata['input_preprocessing_run_id']}`", "",
        "## Component coverage", "",
        "| Component | Records | Assessable | Not assessable |",
        "|---|---:|---:|---:|",
    ]
    for component, summary in report["components"].items():
        lines.append(f"| {component} | {summary['records']:,} | {summary['assessable']:,} | {summary['not_assessable']:,} |")
    lines += ["", "## Interpretation boundary", "", "Each output is separate anomaly evidence requiring investigation. No output is an error probability, a correction, or a finding that a record is wrong.", ""]
    if report.get("warnings"):
        lines += ["## Warnings", ""] + [f"- {item}" for item in report["warnings"]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
