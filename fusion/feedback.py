"""Decision-based recalibration report (plan W8.4).

Recorded supervisor decisions are summarised per lane and tier: how many
flagged cases were decided, and what share were confirmed errors, valid but
unusual, or unresolved.  Proportions carry Wilson 95% intervals.

The report may *propose* a threshold change when the evidence is clear, but
it never changes anything: thresholds and budgets change only through a new,
HSD-approved configuration.  Decided cases are the ones supervisors chose to
open, so the rates describe flagged cases only; the miss rate needs a random
audit sample of unflagged records (plan §12.7, gate G1).
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

MINIMUM_DECISIONS_FOR_PROPOSAL = 30


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def recalibration_report(cases: pd.DataFrame, statuses: dict[str, str]) -> dict[str, Any]:
    """``cases``: case_id, tier, lane; ``statuses``: case_id -> latest decision."""
    decided = cases.loc[cases["case_id"].isin(statuses)].copy()
    decided["decision"] = decided["case_id"].map(statuses)
    groups = []
    for (lane, tier), part in decided.groupby([decided["lane"].fillna("NONE"), decided["tier"].fillna("NONE")], sort=True):
        n = len(part)
        confirmed = int(part["decision"].eq("CONFIRMED_ERROR").sum())
        valid = int(part["decision"].eq("VALID_BUT_UNUSUAL").sum())
        resolved = confirmed + valid
        low, high = wilson(confirmed, resolved)
        proposal = None
        if lane in ("VALUE", "CODING") and tier == "A" and resolved >= MINIMUM_DECISIONS_FOR_PROPOSAL:
            if high is not None and high < 0.10:
                proposal = "Few confirmed errors among resolved 'Check now' cases: consider a stricter threshold or a smaller share for this lane (HSD approval required)."
            elif low is not None and low > 0.50:
                proposal = "Most resolved 'Check now' cases are confirmed errors: consider a larger budget share for this lane (HSD approval required)."
        groups.append({"lane": lane, "tier": tier, "decided": n, "confirmed_error": confirmed, "valid_but_unusual": valid,
                       "unresolved": n - resolved, "confirmed_share_of_resolved": confirmed / resolved if resolved else None,
                       "confirmed_share_ci95": [low, high], "proposal": proposal})
    flagged = cases["tier"].isin(["A", "B"])
    return {"decided_cases": int(len(decided)), "flagged_cases": int(flagged.sum()),
            "decided_share_of_flagged": float(decided["tier"].isin(["A", "B"]).sum() / flagged.sum()) if flagged.any() else None,
            "by_lane_and_tier": groups, "minimum_decisions_for_a_proposal": MINIMUM_DECISIONS_FOR_PROPOSAL,
            "note": ("Rates describe decided flagged cases only (true precision among reviewed flags). The miss rate needs a random audit sample of "
                     "unflagged records (pilot protocol, plan §12.7). Proposals are never applied automatically.")}
