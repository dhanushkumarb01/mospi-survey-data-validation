"""FSU-level fieldwork (paradata) and near-duplicate checks (plan W5.5, W5.6).

Every check compares one FSU with the *other* FSUs of the same release,
visit, month, State/UT, sector and stratum (leave-FSU-out), and returns a
p-value.  An alert describes how the FSU's interviews were conducted or
recorded; it is never evidence that a particular answer is wrong, and an FSU
is never treated as an enumerator (no investigator code exists in the
released data).

Checks
------
interview_duration_short
    Household interview durations (Block 2 item 4, minutes) in the FSU are
    shorter than in comparable FSUs: one-sided Mann-Whitney test.
survey_date_concentration
    The share of the FSU's households interviewed on its busiest single day,
    compared with the same share in comparable FSUs: empirical (finite-sample)
    p-value ``(#comparable FSUs with share >= x + 1) / (n + 1)``.
response_code_mix
    The mix of Block 1 response codes (co-operative and capable, busy,
    reluctant, ...) differs from comparable FSUs: G-test.
substitution_share
    The share of substituted households (survey code 2) is higher than in
    comparable FSUs: one-sided binomial test.
near_duplicate_persons
    Pairs of persons in *different* households of the FSU whose answers
    agree on at least ``similarity_threshold`` of the items both answered
    (at least ``minimum_common_fields`` items).  The count of such pairs is
    compared with the rate among cross-household pairs in comparable FSUs:
    one-sided binomial test.  Children and other people with few answered
    items are excluded by the common-field minimum; similar people in the
    same village are allowed for by the comparable-FSU rate.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

BOUNDARY = ["release", "observation_type", "design_period", "visit", "month", "state", "sector", "stratum"]


def g_test(observed: np.ndarray, expected: np.ndarray) -> tuple[float, float]:
    """G-test of observed against expected counts (same total), Williams-corrected."""
    observed, expected = np.asarray(observed, dtype=float), np.asarray(expected, dtype=float)
    keep = expected > 0
    observed, expected = observed[keep], expected[keep]
    k, n = len(observed), observed.sum()
    if k < 2 or n <= 0:
        return 1.0, 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        g = 2.0 * np.where(observed > 0, observed * np.log(observed / expected), 0.0).sum()
    williams = 1.0 + (k * k - 1.0) / (6.0 * n * (k - 1.0))
    return float(stats.chi2.sf(max(g, 0.0) / williams, k - 1)), float(g)


def _cells(frame: pd.DataFrame):
    return frame.groupby(BOUNDARY, sort=False, observed=True)


def duration_checks(households: pd.DataFrame, minimum_fsu: int, minimum_reference: int) -> list[dict]:
    """Interview duration and survey-date concentration per FSU."""
    rows: list[dict] = []
    for cell_key, cell in _cells(households):
        durations = pd.to_numeric(cell["survey_duration"], errors="coerce")
        valid = cell.assign(_d=durations).loc[durations.gt(0)]
        by_fsu_date = cell.loc[cell["survey_date"].ne("")].groupby("fsu")["survey_date"]
        busiest = (by_fsu_date.agg(lambda s: s.value_counts().iloc[0] / len(s)) if len(by_fsu_date.size()) else pd.Series(dtype=float))
        sizes = cell.loc[cell["survey_date"].ne("")].groupby("fsu").size()
        for fsu, own in valid.groupby("fsu"):
            reference = valid.loc[valid["fsu"].ne(fsu), "_d"].to_numpy(dtype=float)
            n, n_ref = len(own), len(reference)
            base = {"cell": cell_key, "fsu": fsu}
            if n < minimum_fsu or n_ref < minimum_reference or np.unique(np.concatenate([own["_d"], reference])).size < 2:
                rows.append({**base, "component": "interview_duration_short", "variable": "interview_duration_minutes", "n": n, "reference_n": n_ref,
                             "status": "NOT_ASSESSABLE", "reason": "PATTERN_GROUP_BELOW_MINIMUM" if n < minimum_fsu else "REFERENCE_GROUP_BELOW_MINIMUM"})
                continue
            p = float(stats.mannwhitneyu(own["_d"], reference, alternative="less", method="asymptotic").pvalue)
            own_median, ref_median = float(np.median(own["_d"])), float(np.median(reference))
            rows.append({**base, "component": "interview_duration_short", "variable": "interview_duration_minutes", "n": n, "reference_n": n_ref,
                         "status": "ASSESSABLE", "p_value": p, "raw_metric": own_median,
                         "statement": f"FSU {fsu}: the typical household interview took {own_median:g} minutes, compared with {ref_median:g} minutes in comparable FSUs.",
                         "details": {"test": "one-sided Mann-Whitney (FSU durations shorter)", "fsu_median_minutes": own_median, "reference_median_minutes": ref_median,
                                     "fsu_q25": float(np.quantile(own["_d"], .25)), "reference_q25": float(np.quantile(reference, .25)), "households": n}})
        for fsu, share in busiest.items():
            n = int(sizes.get(fsu, 0))
            others = busiest.drop(index=fsu)
            if n < minimum_fsu or len(others) < 5:
                rows.append({"cell": cell_key, "fsu": fsu, "component": "survey_date_concentration", "variable": "share_of_households_on_busiest_day",
                             "n": n, "reference_n": int(len(others)), "status": "NOT_ASSESSABLE",
                             "reason": "PATTERN_GROUP_BELOW_MINIMUM" if n < minimum_fsu else "TOO_FEW_COMPARABLE_FSUS"})
                continue
            p = float((int((others >= share).sum()) + 1) / (len(others) + 1))
            rows.append({"cell": cell_key, "fsu": fsu, "component": "survey_date_concentration", "variable": "share_of_households_on_busiest_day",
                         "n": n, "reference_n": int(len(others)), "status": "ASSESSABLE", "p_value": p, "raw_metric": float(share),
                         "statement": f"FSU {fsu}: {share:.0%} of its households were interviewed on a single day, compared with a typical {float(others.median()):.0%} in comparable FSUs.",
                         "details": {"test": "empirical p-value among comparable FSUs (finite-sample)", "fsu_share_busiest_day": float(share),
                                     "reference_median_share": float(others.median()), "comparable_fsus": int(len(others)), "households": n}})
    return rows


def response_checks(households: pd.DataFrame, minimum_fsu: int, minimum_reference: int) -> list[dict]:
    rows: list[dict] = []
    for cell_key, cell in _cells(households):
        codes = cell.loc[cell["response"].ne("")]
        categories = sorted(codes["response"].unique())
        cell_counts = codes["response"].value_counts()
        substitute = cell["survey_code"].eq("2")
        for fsu, own in cell.groupby("fsu"):
            n, n_ref = len(own), len(cell) - len(own)
            base = {"cell": cell_key, "fsu": fsu}
            if n < minimum_fsu or n_ref < minimum_reference:
                reason = "PATTERN_GROUP_BELOW_MINIMUM" if n < minimum_fsu else "REFERENCE_GROUP_BELOW_MINIMUM"
                rows.append({**base, "component": "response_code_mix", "variable": "response_code", "n": n, "reference_n": n_ref, "status": "NOT_ASSESSABLE", "reason": reason})
                rows.append({**base, "component": "substitution_share", "variable": "substituted_household", "n": n, "reference_n": n_ref, "status": "NOT_ASSESSABLE", "reason": reason})
                continue
            own_codes = own.loc[own["response"].ne(""), "response"].value_counts().reindex(categories, fill_value=0).to_numpy(dtype=float)
            ref_codes = cell_counts.reindex(categories, fill_value=0).to_numpy(dtype=float) - own_codes
            if len(categories) >= 2 and own_codes.sum() > 0 and ref_codes.sum() > 0:
                expected = own_codes.sum() * (ref_codes + 0.5) / (ref_codes.sum() + 0.5 * len(categories))
                p, g = g_test(own_codes, expected)
                largest = int(np.argmax(np.abs(own_codes / own_codes.sum() - ref_codes / ref_codes.sum())))
                rows.append({**base, "component": "response_code_mix", "variable": "response_code", "n": n, "reference_n": n_ref, "status": "ASSESSABLE",
                             "p_value": p, "raw_metric": g,
                             "statement": f"FSU {fsu}: the mix of household response codes differs from comparable FSUs; response code {categories[largest]} is "
                                          f"{own_codes[largest] / own_codes.sum():.0%} here and {ref_codes[largest] / ref_codes.sum():.0%} in comparable FSUs.",
                             "details": {"test": "G-test (Williams-corrected)", "categories": categories, "fsu_counts": own_codes.tolist(), "reference_counts": ref_codes.tolist()}})
            else:
                rows.append({**base, "component": "response_code_mix", "variable": "response_code", "n": n, "reference_n": n_ref, "status": "NOT_ASSESSABLE", "reason": "NO_VARIATION_IN_CELL"})
            k = int(substitute.loc[own.index].sum())
            rate = float((substitute.sum() - k) / n_ref)
            if 0 < rate < 1:
                p = float(stats.binom.sf(k - 1, n, rate))
                rows.append({**base, "component": "substitution_share", "variable": "substituted_household", "n": n, "reference_n": n_ref, "status": "ASSESSABLE",
                             "p_value": p, "raw_metric": k / n,
                             "statement": f"FSU {fsu}: {k} of {n} households are substitutes ({k / n:.0%}), compared with {rate:.0%} in comparable FSUs.",
                             "details": {"test": "one-sided binomial (substitution share higher)", "substituted": k, "households": n, "reference_rate": rate}})
            else:
                rows.append({**base, "component": "substitution_share", "variable": "substituted_household", "n": n, "reference_n": n_ref, "status": "NOT_ASSESSABLE", "reason": "NO_VARIATION_IN_CELL"})
    return rows


def _pair_counts(codes: np.ndarray, present: np.ndarray, households: np.ndarray, minimum_common: int, threshold: float) -> tuple[int, int, list[tuple[int, int]]]:
    """(eligible cross-household pairs, near-duplicate pairs, near-duplicate index pairs) within one FSU."""
    common = present[:, None, :] & present[None, :, :]
    equal = (codes[:, None, :] == codes[None, :, :]) & common
    n_common = common.sum(axis=2)
    share = np.divide(equal.sum(axis=2), n_common, out=np.zeros_like(n_common, dtype=float), where=n_common > 0)
    upper = np.triu(np.ones_like(n_common, dtype=bool), k=1) & (households[:, None] != households[None, :])
    eligible = upper & (n_common >= minimum_common)
    near = eligible & (share >= threshold)
    pairs = [(int(i), int(j)) for i, j in zip(*np.nonzero(near))]
    return int(eligible.sum()), int(near.sum()), pairs


def duplicate_checks(persons: pd.DataFrame, fields: list[str], minimum_common: int, threshold: float, minimum_reference_pairs: int) -> list[dict]:
    """Near-duplicate persons across households of one FSU, against the comparable-FSU pair rate."""
    rows: list[dict] = []
    available = [f for f in fields if f in persons]
    if len(available) < minimum_common:
        return rows
    values = persons[available].astype("string").fillna("").apply(lambda column: column.str.strip())
    present_all = values.ne("").to_numpy(dtype=bool)
    codes_all = np.zeros(values.shape, dtype=np.int64)
    for position, column in enumerate(available):
        codes_all[:, position] = pd.factorize(values[column])[0]
    per_fsu: list[tuple] = []
    for cell_key, cell in _cells(persons):
        for fsu, own in cell.groupby("fsu"):
            idx = persons.index.get_indexer(own.index)
            eligible, near, pairs = _pair_counts(codes_all[idx], present_all[idx], own["household"].to_numpy(), minimum_common, threshold)
            per_fsu.append((cell_key, fsu, eligible, near, [(str(own["household"].iloc[i]), str(own["household"].iloc[j])) for i, j in pairs], len(own)))
    table = pd.DataFrame(per_fsu, columns=["cell", "fsu", "eligible", "near", "pairs", "persons"])
    for cell_key, cell in table.groupby("cell", sort=False):
        total_eligible, total_near = int(cell["eligible"].sum()), int(cell["near"].sum())
        for item in cell.itertuples(index=False):
            ref_eligible, ref_near = total_eligible - item.eligible, total_near - item.near
            base = {"cell": cell_key, "fsu": item.fsu, "component": "near_duplicate_persons", "variable": "near_identical_cross_household_pairs",
                    "n": int(item.eligible), "reference_n": int(ref_eligible)}
            if item.eligible == 0 or ref_eligible < minimum_reference_pairs:
                rows.append({**base, "status": "NOT_ASSESSABLE", "reason": "NO_ELIGIBLE_PAIRS" if item.eligible == 0 else "REFERENCE_GROUP_BELOW_MINIMUM"})
                continue
            rate = (ref_near + 0.5) / (ref_eligible + 1.0)   # +0.5: a zero reference rate is not certainty
            p = float(stats.binom.sf(item.near - 1, item.eligible, rate)) if item.near > 0 else 1.0
            households = sorted({h for pair in item.pairs for h in pair})
            rows.append({**base, "status": "ASSESSABLE", "p_value": p, "raw_metric": float(item.near),
                         "statement": (f"FSU {item.fsu}: {item.near} pair(s) of people in different households gave near-identical answers "
                                       f"(at least {threshold:.0%} of {minimum_common}+ shared items), against about {rate * item.eligible:.1f} expected from comparable FSUs."
                                       if item.near else f"FSU {item.fsu}: no near-identical answer sets across households."),
                         "details": {"test": "one-sided binomial on near-identical cross-household pairs", "near_identical_pairs": int(item.near),
                                     "eligible_pairs": int(item.eligible), "reference_pair_rate": float(rate), "similarity_threshold": threshold,
                                     "minimum_common_items": minimum_common, "households_involved": households[:20],
                                     "household_pairs": [list(pair) for pair in item.pairs[:20]], "items_compared": available}})
    return rows


def cauchy_combination(p_values: np.ndarray) -> float:
    """Cauchy combination test (Liu & Xie 2020): valid under arbitrary dependence between the tests."""
    p = np.clip(np.asarray(p_values, dtype=float), 1e-300, 1.0)
    if len(p) == 0:
        return float("nan")
    small = p < 1e-15
    terms = np.where(small, 1.0 / (p * math.pi), np.tan((0.5 - p) * math.pi))
    statistic = float(terms.mean())
    if statistic > 1e15:
        return float(min(1.0, 1.0 / (statistic * math.pi)))
    return float(min(1.0, max(0.0, 0.5 - math.atan(statistic) / math.pi)))
