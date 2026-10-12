"""Fixed, evidence-only payloads for supervisor case cards and audit snapshots."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd


DISCLAIMER = "This is a priority for supervisory review, not a determination that the reported value is incorrect."


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if pd.notna(result) else None


def _text(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value)
    return None if text in ("", "nan", "<NA>", "None") else text


def build_evidence_card(row: pd.Series | dict) -> dict[str, Any]:
    """Build a card only from the fusion row's stored fields (lane design, v2.1).

    Works for legacy V2.0 rows too (their fields are reported as stored).
    """
    get = row.get if hasattr(row, "get") else (lambda k, d=None: row[k] if k in row else d)
    tier = _text(get("tier"))
    if tier is None:  # legacy V2.0 row
        return {"case_id": get("case_id"), "method": "MoSPI-fusion-v2.0 (superseded)",
                "priority": {"priority_band": get("priority_band"), "priority_score": _finite(get("priority_score")),
                             "risk_score": _finite(get("risk_score")), "influence_score": _finite(get("influence_score"))},
                "provenance": json.loads(get("provenance_json") or "{}"), "disclaimer": DISCLAIMER}
    lanes = (_text(get("lanes")) or "").split(",") if _text(get("lanes")) else []
    return {
        "case_id": get("case_id"),
        "case_level": get("case_level"),
        "identity": {key: _text(get(key)) for key in ("source_observation_id", "release", "observation_type", "design_period", "visit", "month",
                                                       "state", "sector", "stratum", "fsu")},
        "queue": {"tier": tier, "priority_band": get("priority_band"), "queue_position": _finite(get("queue_position")), "lanes": lanes,
                  "reason": _text(get("tier_reason"))},
        "rules": {"hard_findings": int(_finite(get("rule_error_count")) or 0), "soft_findings": int(_finite(get("rule_warning_count")) or 0),
                  "rule_ids": _text(get("rule_ids"))},
        "value_check": {"status": get("value_status"), "tail_probability": _finite(get("value_p")), "lead_variable": _text(get("value_lead_variable")),
                        "lead_tail_probability": _finite(get("value_lead_p")), "variables_assessed": _finite(get("value_variables_assessed")),
                        "strongest_mechanism": _text(get("value_lead_mechanism")), "observed": _finite(get("value_lead_observed")),
                        "typical": _finite(get("value_lead_typical"))},
        "coding_check": {"status": get("coding_status"), "tail_probability": _finite(get("coding_p")), "code": _text(get("coding_code"))},
        "impact": {"standard_errors": _finite(get("impact_se")), "estimate_change": _finite(get("impact_estimate_change"))},
        "group_context": {"fsu_q_value": _finite(get("fsu_q_value")), "fsu_notable": bool(get("fsu_notable") or False),
                          "statement": _text(get("fsu_statement")),
                          "note": "Group context only; it does not mean any answer of this person is wrong and does not change the case's position."},
        "provenance": json.loads(get("provenance_json") or "{}"),
        "disclaimer": DISCLAIMER,
    }
