"""Potential impact of a value on a published-type estimate (plan W2.7).

The former influence score was a value's share of a State x sector *total*.
Small domains have small totals, so small UTs dominated the queue
(Lakshadweep 20.4% CRITICAL against Uttar Pradesh 1.15%), and multiplying it
into risk turned an error list into a list of large-weight records.

Here impact answers "how far would this one value move the estimate PLFS
publishes for its domain, measured in standard errors of that estimate?":

    domain d   = release x period x State/UT x sector
    estimate   = weighted mean of the variable among persons to whom the item
                 applies (the published-type statistic: average earnings,
                 average hours, average wage)
    delta_i    = w_i * (y_i - m_i) / sum_{j in d} w_j
                 (the change if y_i were replaced by its expected value m_i)
    SE_d       = design-based SE of the domain mean (Taylor linearisation,
                 FSU as PSU within strata; survey_rules.variance), floored at
                 the national coefficient of variation times the domain mean
                 so that a tiny domain's unstable SE cannot shrink to ~0
    impact_i   = |delta_i| / SE_d

A small domain has a large SE, so the same relative error does not
automatically score higher there.  Impact is used ONLY to order cases within
the same evidence tier and as a filter; it is never multiplied into evidence.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from survey_rules.variance import ratio_estimate


def domain_standard_errors(values: pd.DataFrame) -> pd.DataFrame:
    """``values``: one row per applicable (record, variable) with value, final_weight, domain, stratum_key, psu_key, period_index, sector.

    Returns one row per (target_variable, domain) with the weighted mean, its
    design SE, the national CV used as floor, and the effective SE.
    """
    rows = []
    usable = values.loc[values["value"].notna() & values["final_weight"].gt(0)]
    for (variable, domain), group in usable.groupby(["target_variable", "domain"], sort=False):
        estimate = ratio_estimate(group["value"].to_numpy(dtype=float), np.ones(len(group)), group["final_weight"].to_numpy(dtype=float),
                                  group["stratum_key"].to_numpy(), group["psu_key"].to_numpy())
        rows.append({"target_variable": variable, "domain": domain, "domain_mean": estimate["estimate"], "domain_se": estimate["design_se"],
                     "domain_weight": float(group["final_weight"].sum()), "domain_records": int(len(group)), "psus": estimate["psus"],
                     "period_index": group["period_index"].iloc[0], "sector": group["sector"].iloc[0]})
    domains = pd.DataFrame(rows)
    if domains.empty:
        return domains
    national = []
    for (variable, period, sector), group in usable.groupby(["target_variable", "period_index", "sector"], sort=False):
        estimate = ratio_estimate(group["value"].to_numpy(dtype=float), np.ones(len(group)), group["final_weight"].to_numpy(dtype=float),
                                  group["stratum_key"].to_numpy(), group["psu_key"].to_numpy())
        cv = abs(estimate["design_se"] / estimate["estimate"]) if estimate["estimate"] else np.nan
        national.append({"target_variable": variable, "period_index": period, "sector": sector, "national_cv": cv})
    domains = domains.merge(pd.DataFrame(national), on=["target_variable", "period_index", "sector"], how="left")
    floor = (domains["national_cv"] * domains["domain_mean"].abs()).fillna(0.0)
    domains["effective_se"] = np.fmax(domains["domain_se"].fillna(0.0), floor)
    domains.loc[domains["effective_se"].le(0), "effective_se"] = np.nan
    domains["se_floored"] = domains["domain_se"].isna() | (domains["domain_se"] < floor)
    return domains


def record_impact(values: pd.DataFrame, domains: pd.DataFrame) -> pd.DataFrame:
    """Per (record, variable) impact in standard errors; NaN without an expected value, weight or SE."""
    merged = values.merge(domains[["target_variable", "domain", "domain_mean", "domain_weight", "effective_se", "se_floored"]],
                          on=["target_variable", "domain"], how="left")
    delta = merged["final_weight"] * (merged["value"] - merged["expected_value"]) / merged["domain_weight"]
    merged["estimate_change"] = delta
    merged["impact_se"] = (delta.abs() / merged["effective_se"]).where(merged["expected_value"].notna() & merged["effective_se"].notna())
    return merged
