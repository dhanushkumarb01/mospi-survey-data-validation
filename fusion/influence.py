"""Potential effect of a value on a weighted domain total (selective-editing local score).

V1 multiplied the design weight by the largest |observed - peer median|
across targets measured in rupees *and* hours, which has no meaning when the
units differ (audit H2).  V2 uses the standard selective-editing local score
(Latouche & Berthelot 1992; Hedlin 2003), computed separately per variable:

    score_t = w_i * |y_it - m_it| / sum_{j in d} w_j * |y_jt|

* ``w`` is the documented final weight for a quarterly (pre-2025) or monthly
  (2025) estimate (survey_rules.final_quarterly_weight);
* ``m`` is the stored peer-group median, used as the anticipated value;
* ``d`` is the estimation domain release x quarter/month x State/UT x sector,
  and the denominator is the weighted total of that variable among persons
  for whom the item applies.

Each score is a share of a weighted domain total, so scores for rupees and
hours are comparable as shares.  ``raw_influence`` is the largest share.

PROVISIONAL engineering proxy: the anticipated value (peer median), the domain
and the choice of "total" as the estimate of interest are not HSD-approved,
and the score has not been validated against official LFPR/WPR/UR or earnings
estimates.  It must be described as "potential effect on a weighted total",
never as the impact on an official estimate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .calibration import percentile_midrank


def domain_shares(values: pd.DataFrame) -> pd.DataFrame:
    """``values``: one row per (record, target) with observed, peer_median, final_weight, domain, applicable.

    Returns the per-target local score.  Rows without a weight, a stored
    anticipated value or an applicable item get NaN (not 0).
    """
    frame = values.copy()
    w = pd.to_numeric(frame["final_weight"], errors="coerce")
    y = pd.to_numeric(frame["observed_value"], errors="coerce")
    m = pd.to_numeric(frame["peer_median"], errors="coerce")
    usable_total = frame["applicable"].astype(bool) & w.notna() & y.notna()
    frame["_mass"] = np.where(usable_total, w * y.abs(), 0.0)
    totals = frame.groupby(["target_variable", "domain"], sort=False)["_mass"].transform("sum")
    numerator = w * (y - m).abs()
    valid = usable_total & m.notna() & totals.gt(0)
    frame["local_score"] = np.where(valid, numerator / totals, np.nan)
    frame["domain_total"] = np.where(valid, totals, np.nan)
    return frame.drop(columns="_mass")


def calculate_influence(records: pd.DataFrame, shares: pd.DataFrame | None = None) -> pd.DataFrame:
    """Attach raw_influence (largest per-target share), its target, status and calibrated rank."""
    output = records.copy()
    if shares is None or shares.empty:
        output["raw_influence"] = np.nan
        output["influence_target"] = pd.NA
    else:
        valid = shares.loc[shares["local_score"].notna()]
        best = valid.sort_values(["local_score", "target_variable"], ascending=[False, True]).drop_duplicates("source_observation_id")
        best = best.set_index("source_observation_id")
        output["raw_influence"] = output["source_observation_id"].map(best["local_score"])
        output["influence_target"] = output["source_observation_id"].map(best["target_variable"])
    assessable = pd.to_numeric(output["raw_influence"], errors="coerce").notna()
    output["influence_status"] = np.where(assessable, "ASSESSABLE", "NOT_ASSESSABLE")
    weight = pd.to_numeric(output.get("final_weight"), errors="coerce") if "final_weight" in output else pd.Series(np.nan, index=output.index)
    output["influence_reason"] = np.where(assessable, None, np.where(weight.isna(), "MISSING_OR_INVALID_DESIGN_WEIGHT",
                                                                     "NO_APPLICABLE_VALUE_WITH_STORED_ANTICIPATED_VALUE"))
    output["influence_score"] = percentile_midrank(output["raw_influence"], zero_is_no_evidence=True)
    return output
