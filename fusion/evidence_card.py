"""Fixed, evidence-only rendering payloads for supervisor case cards."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd


DISCLAIMER = "This is a priority for supervisory review, not a determination that the reported value is incorrect."
RECORD_SOURCES = (("Statistical", "statistical"), ("Contextual", "contextual"), ("ML", "ml"), ("Historical", "historical"))


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if pd.notna(result) else None


def _source_line(name: str, status: Any, rank: Any, detail: Any = None, level: str = "record") -> dict[str, Any]:
    line: dict[str, Any] = {"source": name, "status": str(status) if status is not None and not (isinstance(status, float) and pd.isna(status)) else "NOT_AVAILABLE", "level": level}
    if _finite(rank) is not None:
        line["calibrated_rank"] = round(float(rank), 6)
    if isinstance(detail, str) and detail:
        line["statement"] = detail
    return line


def build_evidence_card(row: pd.Series) -> dict[str, Any]:
    """Build a card only from the fusion row's stored evidence fields.

    The text is deterministic and deliberately modest: it reports reference
    relationships and does not convert a rank into a probability or verdict.
    FSU evidence is listed separately as group context; it is not part of the
    record's risk.
    """
    get = row.get if hasattr(row, "get") else (lambda k, d=None: row[k] if k in row else d)
    source_lines = [_source_line(label, get(f"{key}_status"), get(f"{key}_rank"), get(f"{key}_statement")) for label, key in RECORD_SOURCES]
    group_line = _source_line("Pattern (FSU group context)", get("pattern_status"), get("pattern_rank"), get("pattern_statement"), level="group")
    available = [line["source"] for line in source_lines if line["status"] == "ASSESSABLE"]
    if int(_finite(get("rule_error_count")) or 0) > 0:
        reason = "The record breaks a documented questionnaire rule; it is listed first for review."
    elif not available:
        reason = "No record-level evidence source could be combined for this observation."
    elif len(available) == 1:
        reason = f"Priority is based on the available {available[0].lower()} evidence; other record-level sources are not assessable or unavailable."
    else:
        reason = "Several record-level evidence sources were combined; they share inputs and are not independent proofs."
    return {
        "case_id": get("case_id"),
        "identity": {key: get(key) for key in ("source_observation_id", "release", "observation_type", "design_period", "visit", "month", "state", "sector", "stratum", "fsu")},
        "priority": {"priority_score": _finite(get("priority_score")), "priority_rank": _finite(get("priority_rank")), "priority_band": get("priority_band"),
                     "risk_score": _finite(get("risk_score")), "influence_score": _finite(get("influence_score")), "override_applied": bool(get("override_applied") or False),
                     "rule_violation": bool(get("rule_violation") or False)},
        "reason_for_prioritisation": reason,
        "evidence": source_lines,
        "group_context": group_line,
        "provenance": json.loads(get("provenance_json") or "{}"),
        "disclaimer": DISCLAIMER,
    }
