"""Deterministic robust distribution calculations used by the V1 engine."""

from __future__ import annotations

import numpy as np
import pandas as pd


NORMAL_MAD_SCALE = 0.6744897501960817


def finite_numeric(values: pd.Series) -> pd.Series:
    """Parse numbers without treating blanks/non-finite text as observations."""
    parsed = pd.to_numeric(values.astype("string").str.strip(), errors="coerce")
    return parsed.where(np.isfinite(parsed), np.nan).astype("float64")


def add_distribution_evidence(
    frame: pd.DataFrame,
    *,
    value_column: str,
    group_column: str,
    lower_quantile: float,
    upper_quantile: float,
    prefix: str = "",
) -> pd.DataFrame:
    """Return group-conditioned quantiles, mid-ranks, and MAD evidence.

    Percentile is the empirical mid-distribution position:
    ``(count(value < x) + 0.5 * count(value == x)) / n``.  This makes every
    tie share one deterministic position and does not depend on row order.
    Quantiles use pandas/NumPy's documented linear interpolation convention.
    """
    if frame.empty:
        return frame.copy()
    result = frame.copy()
    values = result[value_column].astype("float64")
    grouped = result.groupby(group_column, sort=False, dropna=False)[value_column]
    result[f"{prefix}reference_group_size"] = grouped.transform("size").astype("Int64")
    result[f"{prefix}peer_median"] = grouped.transform("median")
    quantiles = grouped.quantile([lower_quantile, 0.25, 0.5, 0.75, upper_quantile]).unstack()
    quantiles.columns = [
        f"{prefix}quantile_{str(q).replace('.', '_')}" for q in quantiles.columns
    ]
    result = result.merge(quantiles, left_on=group_column, right_index=True, how="left", validate="many_to_one", sort=False)
    deviations = (values - result[f"{prefix}peer_median"]).abs()
    result["_absolute_deviation"] = deviations
    result[f"{prefix}mad"] = result.groupby(group_column, sort=False, dropna=False)["_absolute_deviation"].transform("median")
    ranks = result.groupby(group_column, sort=False, dropna=False)[value_column]
    average_rank = ranks.rank(method="average")
    size = result[f"{prefix}reference_group_size"].astype("float64")
    result[f"{prefix}percentile_position"] = (average_rank - 0.5) / size
    # Leave-one-out placement (plan S1): the record is compared with the
    # *other* members of its group, never with itself.
    below = ranks.rank(method="min") - 1.0
    equal = ranks.rank(method="max") - below          # includes the record itself
    above = size - below - equal
    others = size - 1.0
    result[f"{prefix}loo_reference_size"] = others.astype("Int64")
    result[f"{prefix}loo_percentile_position"] = np.where(others > 0, (below + 0.5 * (equal - 1.0)) / others.where(others > 0, 1.0), np.nan)
    # Finite-sample (conformal) tail probabilities against the other members:
    # P(a comparable record is at least this high) = (#others >= x + 1) / (n_others + 1).
    # Under exchangeability with its peers a clean record has P(p <= a) <= a,
    # so the value is a calibrated tail probability, not a within-run rank.
    # The smallest attainable value is 1/n, so a small group can never
    # produce overwhelming evidence (plan S2).
    result[f"{prefix}upper_tail_p"] = (above + equal) / size
    result[f"{prefix}lower_tail_p"] = (below + equal) / size
    result[f"{prefix}two_sided_tail_p"] = np.minimum(1.0, 2.0 * np.minimum(result[f"{prefix}upper_tail_p"], result[f"{prefix}lower_tail_p"]))
    result[f"{prefix}tail_direction"] = np.where(result[f"{prefix}upper_tail_p"] < result[f"{prefix}lower_tail_p"], "HIGH",
                                                 np.where(result[f"{prefix}upper_tail_p"] > result[f"{prefix}lower_tail_p"], "LOW", "CENTRE"))
    result[f"{prefix}signed_distance_from_median"] = values - result[f"{prefix}peer_median"]
    result[f"{prefix}absolute_distance_from_median"] = deviations
    zero_mad = result[f"{prefix}mad"].eq(0)
    same_as_median = result[f"{prefix}signed_distance_from_median"].eq(0)
    result[f"{prefix}robust_deviation"] = np.where(
        ~zero_mad,
        NORMAL_MAD_SCALE * result[f"{prefix}signed_distance_from_median"] / result[f"{prefix}mad"],
        np.where(same_as_median, 0.0, np.nan),
    )
    result[f"{prefix}robust_deviation_status"] = np.where(
        ~zero_mad, "COMPUTED",
        np.where(same_as_median, "ZERO_MAD_AT_MEDIAN", "ZERO_MAD_DEVIATION_NOT_NUMERIC"),
    )
    low = f"{prefix}quantile_{str(lower_quantile).replace('.', '_')}"
    high = f"{prefix}quantile_{str(upper_quantile).replace('.', '_')}"
    result[f"{prefix}distribution_position"] = np.select(
        [values.lt(result[low]), values.gt(result[high])],
        ["LOWER_TAIL", "UPPER_TAIL"],
        default="CENTRAL_REFERENCE_RANGE",
    )
    result[f"{prefix}lower_tail_percentile_distance"] = (lower_quantile - result[f"{prefix}percentile_position"]).clip(lower=0)
    result[f"{prefix}upper_tail_percentile_distance"] = (result[f"{prefix}percentile_position"] - upper_quantile).clip(lower=0)
    return result.drop(columns="_absolute_deviation")
