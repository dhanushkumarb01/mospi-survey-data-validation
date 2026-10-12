"""Report writing for peer-group runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, content: Any) -> None:
    path.write_text(json.dumps(content, indent=2, sort_keys=True, default=str), encoding="utf-8")


def write_markdown_report(output_dir: Path, report: dict[str, Any], metadata: dict[str, Any]) -> None:
    lines = [
        "# PLFS peer-group report",
        "",
        f"- Run ID: `{metadata['run_id']}`",
        f"- Reference input: `{metadata['input_preprocessing_run_id']}`",
        f"- Release / observation: `{metadata['release']}` / `{metadata['observation']}`",
        f"- Minimum group size: {metadata['minimum_group_size']}",
        f"- Specification version: `{metadata['specification_version']}`",
        "",
        "## Target summary",
        "",
        "| Target | Assignments | Assessable (%) | Groups | Not assessable (%) |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in report["target_summary"]:
        lines.append(
            f"| {row['target_variable']} | {row['assignments']:,} | {row['assessable_percent']:.2f} | "
            f"{row['groups']:,} | {row['not_assessable_percent']:.2f} |"
        )
    lines.extend(["", "## Group-size distribution", ""])
    distribution = report.get("group_size_distribution", {})
    if distribution:
        lines.append("| Groups | Minimum | Median | 95th percentile | Maximum |")
        lines.append("|---:|---:|---:|---:|---:|")
        lines.append(f"| {int(distribution['count']):,} | {distribution['min']:.0f} | {distribution['50%']:.0f} | {distribution['95%']:.0f} | {distribution['max']:.0f} |")
    lines.extend(["", "## Backoff usage", "", "| Target | Full level (%) | Backoff levels / not assessable (%) |", "|---|---:|---|"])
    for row in report["target_summary"]:
        percentages = row["backoff_percent"]
        full = percentages.get("0", 0.0)
        detail = ", ".join(f"L{level}: {value:.2f}%" if level != "<NA>" else f"Not assessable: {value:.2f}%" for level, value in percentages.items() if level != "0")
        lines.append(f"| {row['target_variable']} | {full:.2f} | {detail} |")
    lines.extend(["", "## Grouping dimensions used", ""])
    for row in report.get("grouping_dimension_sets", []):
        lines.append(f"- `{row['target_variable']}` / `{row['grouping_profile']}` / level {row['backoff_level']}: `{row['grouping_dimensions']}`")
    lines.extend([
        "",
        "## Boundaries",
        "",
        "- Groups are release-, observation-route-, design-period-, and visit-aware.",
        "- Post-2025 V1 groups additionally retain calendar month.",
        "- FSU and survey weight are prohibited as grouping dimensions.",
        "- This output is a reference-population assignment only; it contains no anomaly score or statistical decision.",
    ])
    (output_dir / "peer_group_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
