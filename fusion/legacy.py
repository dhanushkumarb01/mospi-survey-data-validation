"""The superseded V2.0 priority construction, kept ONLY as evaluation baseline A0.

It is not on the decision path and no supervisor queue is built from it.  The
measured reasons it was replaced (docs/10_10_IMPROVEMENT_PLAN.md §5.7):
averaging within-run ranks diluted evidence that only one source can see;
the maximum of three ML ranks let Isolation Forest dominate; the 0.995
override lifted noise to CRITICAL; and multiplying by a domain-share
influence favoured the smallest States/UTs.

Stored V2.0 fusion runs (``fusion_version`` MoSPI-fusion-v2.0) were produced
by exactly this code and remain readable for the record.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .calibration import percentile_midrank

LEGACY_SOURCES = ("statistical", "contextual", "ml", "historical")


@dataclass(frozen=True)
class LegacyParameters:
    source_weights: dict[str, float] = field(default_factory=lambda: {"statistical": 0.30, "contextual": 0.20, "ml": 0.25, "historical": 0.25})
    override_rank_threshold: float = 0.995
    priority_bands: tuple[tuple[str, float], ...] = (("CRITICAL", 0.80), ("HIGH", 0.50), ("MEDIUM", 0.20), ("LOW", 0.00))


def legacy_fuse(cases: pd.DataFrame, parameters: LegacyParameters = LegacyParameters()) -> pd.DataFrame:
    """V2.0 risk (weighted mean of within-run ranks with override); priority = risk x influence_score."""
    cases = cases.copy()
    for source in LEGACY_SOURCES:
        raw, rank, status = f"{source}_raw_score", f"{source}_rank", f"{source}_status"
        if raw not in cases:
            cases[raw] = np.nan
        if status not in cases:
            cases[status] = "NOT_AVAILABLE"
        cases[rank] = percentile_midrank(cases[raw], zero_is_no_evidence=(source == "statistical"))
    weights = parameters.source_weights
    numerator = sum(cases[f"{s}_rank"].fillna(0) * weights.get(s, 0.0) for s in LEGACY_SOURCES)
    denominator = sum(cases[f"{s}_rank"].notna() * weights.get(s, 0.0) for s in LEGACY_SOURCES)
    cases["weighted_risk_score"] = np.where(denominator > 0, numerator / np.where(denominator > 0, denominator, 1), np.nan)
    cases["maximum_available_rank"] = cases[[f"{s}_rank" for s in LEGACY_SOURCES if weights.get(s, 0) > 0]].max(axis=1)
    cases["override_applied"] = cases.maximum_available_rank.ge(parameters.override_rank_threshold)
    cases["risk_score"] = np.where(cases.override_applied, np.maximum(cases.weighted_risk_score, cases.maximum_available_rank), cases.weighted_risk_score)
    influence = cases["influence_score"] if "influence_score" in cases else pd.Series(1.0, index=cases.index)
    cases["priority_score"] = np.where(pd.notna(cases.risk_score) & influence.notna(), cases.risk_score * influence, np.nan)
    rule_errors = pd.to_numeric(cases.get("rule_error_count", 0), errors="coerce").fillna(0)
    cases.loc[rule_errors.gt(0), "priority_score"] = 1.0
    return cases


def legacy_domain_share_influence(values: pd.DataFrame) -> pd.Series:
    """V2.0 influence: w|y - m| / sum_domain w|y| (kept for the A0 baseline and the State-burden comparison)."""
    w = pd.to_numeric(values["final_weight"], errors="coerce")
    y = pd.to_numeric(values["observed_value"], errors="coerce")
    m = pd.to_numeric(values["peer_median"], errors="coerce")
    mass = np.where(values["applicable"].astype(bool) & w.notna() & y.notna(), w * y.abs(), 0.0)
    totals = pd.Series(mass, index=values.index).groupby([values["target_variable"], values["domain"]]).transform("sum")
    return pd.Series(np.where(m.notna() & totals.gt(0), w * (y - m).abs() / totals, np.nan), index=values.index)
