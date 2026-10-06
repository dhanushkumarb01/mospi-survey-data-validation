import pandas as pd

from evaluation.run import _metrics


def _frame(n=200, positives=20):
    ids = pd.Series([f"r{i}" for i in range(n)])
    positive = pd.Series([i < positives for i in range(n)])
    types = pd.Series(["scale_x10" if i < positives else None for i in range(n)])
    return ids, positive, types


def test_perfect_ranking_scores_perfectly():
    ids, positive, types = _frame()
    m = _metrics(positive.astype(float), positive, ids, types, {})
    assert m["average_precision"] == 1.0 and m["roc_auc"] == 1.0
    assert m["at_k_eq_injected"]["precision"] == 1.0 and m["recall_by_error_type_at_5pct"]["scale_x10"] == .5


def test_ties_are_not_broken_by_the_label():
    """A constant score must not find errors: ties fall back to a label-blind hash."""
    ids, positive, types = _frame()
    m = _metrics(pd.Series(0.0, index=ids.index), positive, ids, types, {})
    assert m["roc_auc"] == 0.5 and m["at_k_eq_injected"]["recall"] < .5
