"""Deterministic reporting helpers for Pattern V1."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")


def write_markdown_report(path: Path, metadata: dict[str, Any], report: dict[str, Any]) -> None:
    lines = [
        "# PLFS Pattern run report", "",
        f"- Pattern run ID: `{metadata['run_id']}`",
        f"- Release / observation: `{metadata['release']}` / `{metadata['observation']}`",
        f"- Preprocessing run: `{metadata['input_preprocessing_run_id']}`",
        f"- Method version: `{metadata['pattern_method_version']}`", "",
        "## Component coverage", "",
        "| Component | Rows | Assessable | Not assessable |",
        "|---|---:|---:|---:|",
    ]
    for name, summary in report["components"].items():
        if "rows" in summary:
            lines.append(f"| {name} | {summary['rows']:,} | {summary['assessable']:,} | {summary['not_assessable']:,} |")
    fsu = report["components"].get("fsu_summary")
    if fsu:
        lines += ["", "## FSU-level alerts (Cauchy combination + Benjamini-Hochberg across FSUs)", "",
                  f"- FSUs: {fsu['fsus']:,}; assessable: {fsu['assessable']:,}; notable: {fsu['notable_q_lt_threshold']:,} "
                  f"(of which with a fieldwork signal: {fsu['notable_with_fieldwork_signal']:,})"]
    lines += ["", "## Interpretation boundary", "",
              "These are group-, FSU-, stratum-, or time-pattern evidence outputs for human review. They do not identify errors, fabrication, an enumerator, or a record requiring correction. No score is an error probability.",
              "", "## Warnings", ""]
    lines.extend(f"- {warning}" for warning in report.get("warnings", []))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
