"""Evaluation metrics (plan §12.2, §12.5; W1.3, W1.4).

Headline metrics are computed on the **CAPI-pass population**: all records
minus every record breaking a documented hard rule and minus the injection
types that are rule breaches by construction.  CAPI already catches those;
mixing them into the same top-K once capped non-rule recall at 26.6% (audit
N4).  Rule findings are scored separately (their recall should be 100%).

Injected labels are the only known positives; unlabelled records may still
hold genuine errors, so precision is a lower bound.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

K_SHARES = (0.005, 0.01, 0.02, 0.05)
RULE_INJECTION_TYPES = frozenset({"status_earnings_rule", "age_status_rule"})


def ranked(score: pd.Series, ids: pd.Series) -> pd.Series:
    """1-based rank: score descending; ties broken by a stable hash of the id (never by the label)."""
    tie = pd.util.hash_pandas_object(ids.astype(str), index=False).astype("uint64")
    order = pd.DataFrame({"s": score.fillna(-np.inf).to_numpy(), "t": tie.to_numpy()}, index=score.index).sort_values(["s", "t"], ascending=[False, True], kind="mergesort")
    return pd.Series(np.arange(1, len(order) + 1), index=order.index).reindex(score.index)


def capi_pass_mask(rule_breach: pd.Series, error_type: pd.Series) -> pd.Series:
    return ~rule_breach.fillna(False).astype(bool) & ~error_type.isin(RULE_INJECTION_TYPES)


def at_k(rank: pd.Series, positive: pd.Series, k: int) -> dict[str, float]:
    top = rank.le(k)
    tp, p = int((top & positive).sum()), int(positive.sum())
    precision, recall = (tp / k if k else 0.0), (tp / p if p else 0.0)
    f05 = 1.25 * precision * recall / (0.25 * precision + recall) if precision + recall else 0.0
    return {"k": int(k), "true_positives": tp, "precision": precision, "recall": recall, "f0_5": f05}


def ranking_metrics(score: pd.Series, positive: pd.Series, ids: pd.Series, error_type: pd.Series, *, budget: int | None = None,
                    subgroups: dict[str, pd.Series] | None = None) -> dict:
    """Metrics for one ranking on one population (already restricted by the caller)."""
    n, p = len(score), int(positive.sum())
    out: dict = {"records": n, "injected": p}
    if p == 0 or p == n:
        return out
    rank = ranked(score, ids)
    finite = score.replace([np.inf, -np.inf], np.nan).fillna(score.replace([np.inf, -np.inf], np.nan).min() - 1 if score.notna().any() else 0)
    out["average_precision"] = float(average_precision_score(positive, finite))
    out["chance_average_precision"] = p / n
    for share in K_SHARES:
        out[f"at_{share:g}"] = at_k(rank, positive, max(1, round(share * n)))
    if budget:
        out["at_budget"] = at_k(rank, positive, budget)
    top1, top5 = rank.le(max(1, round(0.01 * n))), rank.le(max(1, round(0.05 * n)))
    out["recall_by_type_at_0.01"] = {t: float(top1[error_type.eq(t)].mean()) for t in sorted(error_type.dropna().unique())}
    out["recall_by_type_at_0.05"] = {t: float(top5[error_type.eq(t)].mean()) for t in sorted(error_type.dropna().unique())}
    for name, groups in (subgroups or {}).items():
        out[f"recall_at_0.05_by_{name}"] = {str(g): {"recall": float(top5[positive & groups.eq(g)].mean()) if (positive & groups.eq(g)).any() else None,
                                                     "injected": int((positive & groups.eq(g)).sum())} for g in sorted(groups.dropna().unique())}
    return out


def paired_bootstrap_difference(score_a: pd.Series, score_b: pd.Series, positive: pd.Series, ids: pd.Series, *, share: float = 0.01,
                                resamples: int = 500, seed: int = 0) -> dict[str, float]:
    """Recall@K of A minus B with a percentile CI, resampling the injected records (paired: same resample for both)."""
    k = max(1, round(share * len(score_a)))
    hit_a = ranked(score_a, ids).le(k)[positive].to_numpy()
    hit_b = ranked(score_b, ids).le(k)[positive].to_numpy()
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(hit_a), size=(resamples, len(hit_a)))
    differences = hit_a[draws].mean(axis=1) - hit_b[draws].mean(axis=1)
    return {"difference": float(hit_a.mean() - hit_b.mean()), "ci95_low": float(np.quantile(differences, 0.025)),
            "ci95_high": float(np.quantile(differences, 0.975)), "k": int(k), "resamples": resamples}


def rule_list_metrics(rule_breach: pd.Series, error_type: pd.Series) -> dict:
    """Recall of the rule-type injections by the rule list (should be 1.0: rules are deterministic)."""
    injected = error_type.isin(RULE_INJECTION_TYPES)
    return {"rule_type_injections": int(injected.sum()), "found_by_rules": int((injected & rule_breach).sum()),
            "recall": float((injected & rule_breach).sum() / injected.sum()) if injected.any() else None,
            "records_breaking_rules": int(rule_breach.sum())}
