"""Evidence lanes (plan §8.1): pure functions, no I/O.

Detectors look at *different variables*, so evidence is OR-like across
variables and mechanisms and AND-like only across references of the *same*
variable.  The former V2 design averaged within-run ranks of every source and
so diluted a value error that only one or two sources can see (audit C1).

Value lane, per variable v of a record
    p_cur   finite-sample tail probability against current comparable people
            (leave-one-out; statistical layer)
    p_hist  finite-sample tail probability against the same cell in earlier
            periods (out-of-sample; historical layer)
    p_model split-conformal tail probability of the gap between the value and
            the expected value for a person with these characteristics
            (model trained on earlier periods; ML layer)

    p_ref = mean(p_cur, p_hist)        both references must agree (AND-like);
                                       the one available if only one is
    p_v   = 1 - (1 - min(p_ref, p_model))^k   Sidak over the k mechanisms
                                       available (OR across mechanisms)

    record value p = 1 - (1 - min_v p_v)^m    Sidak over the m variables
                                       assessed, so a record with more answered
                                       items is not flagged more often by chance

Every input is a tail probability whose meaning does not depend on the run:
"fewer than 1 in 100 comparable records look like this".  The averaging of
p_cur and p_hist is conservative when the two references agree in
distribution (positively dependent); the observed flag rate on released data
is reported by every run so the calibration can be checked (§12.6).

Discrete tests (Tarone 1990), fusion v2.2
    A finite-sample tail probability against n comparable values can never be
    smaller than 2/(n + 1) (two-sided).  With a typical current-peer group of
    ~77 people that floor (~0.026) is above the value threshold (~0.022), so
    the reference mechanism of such a variable can never raise an alert, yet a
    plain Sidak count still charged for it and halved the power of the model.
    Given the threshold, a mechanism whose smallest attainable value exceeds
    it is not counted (k) and a variable with no such mechanism is not counted
    (m).  Counting is done against the threshold itself, not threshold/k, so
    the count is never smaller than Tarone's and the correction stays valid.
    The expected-value model is always counted (its floor 1/(n_cal + 1) is
    below 0.01 by construction).  Measured on the stored 2024 V2.1 run this
    moved observed/nominal value alerts from 0.51 to 0.82.

Coding lane
    coding p = conformal frequency tail probability of the occupation code
    within its comparison group (contextual layer).

Nothing here is an error probability.  A small p says the answer is rare for
comparable people; only the supervisor's review decides whether it is wrong.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sidak(p_min: pd.Series | np.ndarray, tests: pd.Series | np.ndarray) -> np.ndarray:
    """Sidak correction 1 - (1 - p)^k (k >= 1); NaN where p is NaN."""
    p = np.asarray(p_min, dtype=float)
    k = np.maximum(np.asarray(tests, dtype=float), 1.0)
    with np.errstate(invalid="ignore"):
        # -expm1(k*log1p(-p)) is 1-(1-p)^k without cancellation for tiny p.
        return np.where(np.isfinite(p), -np.expm1(k * np.log1p(-np.clip(p, 0.0, 1.0 - 1e-16))), np.nan)


def _two_sided_floor(n: pd.Series) -> pd.Series:
    """Smallest attainable two-sided finite-sample tail probability against n reference values."""
    return 2.0 / (pd.to_numeric(n, errors="coerce") + 1.0)


def variable_evidence(rows: pd.DataFrame, threshold: float | None = None) -> pd.DataFrame:
    """Per (record, variable) evidence.  ``rows`` carries p_current, p_history, p_model (NaN when unavailable).

    With ``threshold`` (the run's value threshold) and the reference sizes
    ``current_n`` / ``history_n``, mechanisms that cannot attain the threshold
    are left out of the Sidak count (Tarone).  Without it, every available
    mechanism is counted (fusion v2.1 behaviour).
    """
    out = rows.copy()
    references = out[["p_current", "p_history"]]
    out["p_reference"] = references.mean(axis=1, skipna=True)
    out["reference_sources"] = references.notna().sum(axis=1).astype(int)
    mechanisms = out[["p_reference", "p_model"]]
    out["mechanisms"] = mechanisms.notna().sum(axis=1).astype(int)
    floors = pd.concat([_two_sided_floor(out["current_n"]).where(out["p_current"].notna()) if "current_n" in out else pd.Series(np.nan, index=out.index),
                        _two_sided_floor(out["history_n"]).where(out["p_history"].notna()) if "history_n" in out else pd.Series(np.nan, index=out.index)], axis=1)
    out["reference_floor"] = floors.mean(axis=1, skipna=True).where(out["p_reference"].notna())
    reference_testable = out["p_reference"].notna()
    if threshold is not None:
        # An unknown floor counts as testable (conservative).
        reference_testable &= ~out["reference_floor"].gt(threshold)
    out["reference_testable"] = reference_testable
    testable = pd.concat([out["p_reference"].where(reference_testable), out["p_model"]], axis=1)
    out["mechanisms_testable"] = testable.notna().sum(axis=1).astype(int)
    p_testable = sidak(testable.min(axis=1, skipna=True), out["mechanisms_testable"])
    p_all = sidak(mechanisms.min(axis=1, skipna=True), out["mechanisms"])
    # A variable with no testable mechanism keeps its plain value: it is above the threshold by construction.
    out["p_variable"] = np.where(out["mechanisms_testable"].gt(0), p_testable, p_all)
    out.loc[out["mechanisms"].eq(0), "p_variable"] = np.nan
    lead = np.where(out["p_model"].notna() & (out["p_reference"].isna() | (out["p_model"] < out["p_reference"])), "MODEL", "REFERENCE")
    out["strongest_mechanism"] = pd.Series(lead, index=out.index).where(out["mechanisms"].gt(0))
    return out


def record_value_evidence(variables: pd.DataFrame) -> pd.DataFrame:
    """Combine per-variable evidence into one record-level value p (Sidak over the variables that can attain the threshold)."""
    usable = variables.loc[variables["p_variable"].notna()]
    if usable.empty:
        return pd.DataFrame(columns=["source_observation_id", "value_p", "value_variables_assessed", "value_variables_testable", "value_lead_variable", "value_lead_p"])
    lead = usable.sort_values(["p_variable", "target_variable"], kind="mergesort").drop_duplicates("source_observation_id")
    counts = usable.groupby("source_observation_id").size()
    testable = usable["mechanisms_testable"].gt(0) if "mechanisms_testable" in usable else pd.Series(True, index=usable.index)
    testable_counts = testable.groupby(usable["source_observation_id"]).sum()
    result = lead[["source_observation_id", "target_variable", "p_variable"]].rename(columns={"target_variable": "value_lead_variable", "p_variable": "value_lead_p"})
    result["value_variables_assessed"] = result["source_observation_id"].map(counts).astype(int)
    result["value_variables_testable"] = result["source_observation_id"].map(testable_counts).astype(int)
    # No testable variable: the record cannot reach the threshold; count every assessed variable.
    count = result["value_variables_testable"].where(result["value_variables_testable"].gt(0), result["value_variables_assessed"])
    result["value_p"] = sidak(result["value_lead_p"], count)
    return result.reset_index(drop=True)


def expected_false_alerts_per_1000(threshold: float, assessable_share: float) -> float:
    """Nominal false alerts per 1,000 records when every record is clean and the tail probabilities are calibrated."""
    return float(threshold) * 1000.0 * float(assessable_share)
