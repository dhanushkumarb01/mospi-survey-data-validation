from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from evaluation.metrics import capi_pass_mask, paired_bootstrap_difference, ranking_metrics, rule_list_metrics


def _frame(n=200, positives=20):
    ids = pd.Series([f"r{i}" for i in range(n)])
    positive = pd.Series([i < positives for i in range(n)])
    types = pd.Series(["scale_x10" if i < positives else None for i in range(n)])
    return ids, positive, types


def test_perfect_ranking_scores_perfectly():
    ids, positive, types = _frame()
    m = ranking_metrics(positive.astype(float), positive, ids, types, budget=20)
    assert m["average_precision"] == 1.0 and m["at_budget"]["precision"] == 1.0
    assert m["at_0.05"]["recall"] == 0.5 and m["at_0.05"]["k"] == 10           # hand-computed: 10 slots, 20 positives
    assert m["recall_by_type_at_0.05"]["scale_x10"] == 0.5


def test_ties_are_not_broken_by_the_label():
    """A constant score must not find errors: ties fall back to a label-blind hash."""
    ids, positive, types = _frame()
    m = ranking_metrics(pd.Series(0.0, index=ids.index), positive, ids, types)
    assert m["at_0.05"]["recall"] < .5


def test_rule_breaches_are_removed_from_the_headline_population_and_scored_separately():
    """Audit N4: rule records took 600 of 1,071 top-1% slots and capped non-rule recall."""
    rule = pd.Series([True, False, False, False])
    types = pd.Series(["age_status_rule", "scale_x10", None, "status_earnings_rule"])
    assert capi_pass_mask(rule, types).tolist() == [False, True, True, False]
    assert rule_list_metrics(rule, types)["recall"] == 0.5


def test_paired_bootstrap_difference_is_centred_on_the_observed_difference():
    ids, positive, types = _frame()
    better = positive.astype(float) + np.linspace(0, .1, 200)
    worse = pd.Series(np.linspace(1, 0, 200))[::-1].reset_index(drop=True)
    result = paired_bootstrap_difference(better, worse, positive, ids, share=0.05, resamples=200)
    assert result["difference"] == pytest.approx(0.5) and result["ci95_low"] > 0


def test_lane_rankings_are_read_from_stored_artefacts(tmp_path):
    """Structural: every compared design gets a score for every record from a real (synthetic) batch."""
    from evaluation.run import rankings
    from pipeline.run import Inputs, run_pipeline
    from pipeline.tests.synthetic import write_delivery
    prepared, _ = write_delivery(tmp_path / "preprocessing" / "runs" / "2024_first_visit_synthetic")
    result = run_pipeline(Inputs(prepared), "t", roots=tmp_path)
    stages = {k: Path(v) for k, v in result.items() if k not in ("timing_seconds", "qa")}
    scores, rule_breach = rankings(stages["fusion"], stages, prepared)
    assert {"A0_superseded_v2_0", "D_value_lane", "E6_operational_queue", "E2_earlier_periods"} <= set(scores.columns)
    assert scores["E6_operational_queue"].notna().all() and scores["A0_superseded_v2_0"].notna().any()
    assert len(scores) == len(rule_breach)
