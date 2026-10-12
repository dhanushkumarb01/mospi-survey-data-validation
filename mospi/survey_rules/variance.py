"""Design-based standard errors for weighted domain estimates (survey-generic).

PLFS is a stratified multi-stage sample: FSUs (first-stage units) are drawn
within strata, and people within an FSU resemble each other.  A standard
error that treats people as a simple random sample understates the true
sampling error by roughly the square root of the design effect (audit M4).

Method (standard textbook practice, e.g. Wolter 2007; Lumley 2010):

* every estimate is a ratio ``R = sum(w*y) / sum(w*x)`` (a mean has x = 1, a
  rate such as LFPR has x = 1 for the base population);
* each record gets the linearised value ``z = w * (y - R*x) / sum(w*x)``;
* z is totalled per FSU (the PSU), and the variance is the with-replacement
  between-PSU variance within strata,
  ``V = sum_h n_h/(n_h-1) * sum_i (z_hi - zbar_h)^2``;
* a stratum with a single PSU in the domain is centred on the domain's mean
  PSU total (the "adjust" convention for lonely PSUs).

A median's standard error uses Woodruff's method: the linearised SE of the
estimated distribution function at the median is mapped back through the
weighted quantile function.

These are approximations (with-replacement first stage, no finite
population correction); they are documented as such wherever they are shown.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _psu_variance(z: np.ndarray, strata: np.ndarray, psu: np.ndarray) -> tuple[float, int]:
    frame = pd.DataFrame({"z": z, "h": strata, "i": psu})
    totals = frame.groupby(["h", "i"], sort=False)["z"].sum().reset_index()
    n_psu = len(totals)
    if n_psu < 2:
        return float("nan"), n_psu
    counts = totals.groupby("h")["z"].transform("size").to_numpy()
    means = totals.groupby("h")["z"].transform("mean").to_numpy()
    values = totals["z"].to_numpy()
    lonely = counts == 1
    grand = values.mean()
    contribution = np.where(lonely, (values - grand) ** 2, (counts / np.maximum(counts - 1, 1)) * (values - means) ** 2)
    return float(contribution.sum()), n_psu


def ratio_estimate(y: np.ndarray, x: np.ndarray, w: np.ndarray, strata: np.ndarray, psu: np.ndarray) -> dict[str, float]:
    """Weighted ratio sum(w y)/sum(w x) with its linearised design-based SE."""
    y, x, w = (np.asarray(a, dtype=float) for a in (y, x, w))
    denominator = float(np.sum(w * x))
    if not np.isfinite(denominator) or denominator <= 0:
        return {"estimate": float("nan"), "design_se": float("nan"), "psus": 0}
    estimate = float(np.sum(w * y)) / denominator
    z = w * (y - estimate * x) / denominator
    variance, n_psu = _psu_variance(z, np.asarray(strata), np.asarray(psu))
    return {"estimate": estimate, "design_se": float(np.sqrt(variance)) if np.isfinite(variance) else float("nan"), "psus": n_psu}


def weighted_quantile(values: np.ndarray, weights: np.ndarray, probability: float) -> float:
    values, weights = np.asarray(values, dtype=float), np.asarray(weights, dtype=float)
    if len(values) == 0 or weights.sum() <= 0:
        return float("nan")
    order = np.argsort(values, kind="mergesort")
    v, cumulative = values[order], np.cumsum(weights[order])
    return float(v[min(len(v) - 1, np.searchsorted(cumulative, probability * cumulative[-1]))])


def median_estimate(values: np.ndarray, w: np.ndarray, strata: np.ndarray, psu: np.ndarray) -> dict[str, float]:
    """Weighted median with a Woodruff design-based SE."""
    values, w = np.asarray(values, dtype=float), np.asarray(w, dtype=float)
    median = weighted_quantile(values, w, 0.5)
    if not np.isfinite(median):
        return {"estimate": float("nan"), "design_se": float("nan"), "psus": 0}
    below = (values <= median).astype(float)
    proportion = ratio_estimate(below, np.ones_like(below), w, strata, psu)
    se_p = proportion["design_se"]
    if not np.isfinite(se_p) or se_p <= 0:
        return {"estimate": median, "design_se": float("nan"), "psus": proportion["psus"]}
    low = weighted_quantile(values, w, max(0.0, 0.5 - 1.96 * se_p))
    high = weighted_quantile(values, w, min(1.0, 0.5 + 1.96 * se_p))
    return {"estimate": median, "design_se": (high - low) / (2 * 1.96), "psus": proportion["psus"]}
