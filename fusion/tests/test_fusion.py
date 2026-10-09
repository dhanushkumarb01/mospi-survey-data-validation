import json

import numpy as np
import pandas as pd
import pytest

from fusion.config import FusionParameters
from fusion.engine import FusionEngine, FusionFailure, RunConfig
from fusion.evidence_card import build_evidence_card
from fusion.impact import domain_standard_errors, record_impact
from fusion.lanes import record_value_evidence, sidak, variable_evidence
from fusion.legacy import legacy_fuse
from fusion.queue import build_queue


def _variables(rows):
    return variable_evidence(pd.DataFrame(rows, columns=["source_observation_id", "target_variable", "p_current", "p_history", "p_model"]))


def test_references_of_one_variable_must_agree_and_mechanisms_are_or_combined():
    v = _variables([("a", "x", 0.01, 0.01, np.nan), ("b", "x", 0.01, 0.9, np.nan), ("c", "x", 0.5, 0.5, 0.001), ("d", "x", np.nan, np.nan, np.nan)])
    p = v.set_index("source_observation_id")["p_variable"]
    assert p["a"] == pytest.approx(0.01)                    # both references agree
    assert p["b"] > 0.4                                     # one reference alone does not carry the AND
    assert p["c"] == pytest.approx(1 - (1 - 0.001) ** 2)    # the model is a second mechanism (Sidak over 2)
    assert np.isnan(p["d"])


def test_value_evidence_is_not_diluted_by_variables_that_cannot_see_the_error():
    """Audit C1: averaging ranks pulled a value error down by sources blind to it.  Here other variables only cost a Sidak factor."""
    v = _variables([("a", "salary", 0.001, 0.001, np.nan), ("a", "hours", 0.9, 0.9, np.nan), ("a", "wage", 0.8, 0.8, np.nan)])
    record = record_value_evidence(v).iloc[0]
    assert record["value_lead_variable"] == "salary"
    assert record["value_p"] == pytest.approx(1 - (1 - 0.001) ** 3)


def test_mechanism_that_cannot_attain_the_threshold_is_not_counted_tarone():
    """A 50-person peer group cannot give a two-sided tail probability below 2/51 ~ 0.039, so at a 0.02
    threshold it is not counted: the model alone carries the variable, without a Sidak charge for the reference."""
    rows = pd.DataFrame([("a", "salary", 0.5, np.nan, 0.004, 50, np.nan),        # small reference: untestable at 0.02
                         ("b", "salary", 0.5, np.nan, 0.004, 5000, np.nan)],     # large reference: testable
                        columns=["source_observation_id", "target_variable", "p_current", "p_history", "p_model", "current_n", "history_n"])
    p = variable_evidence(rows, threshold=0.02).set_index("source_observation_id")
    assert p.loc["a", "mechanisms_testable"] == 1 and p.loc["a", "p_variable"] == pytest.approx(0.004)
    assert p.loc["b", "mechanisms_testable"] == 2 and p.loc["b", "p_variable"] == pytest.approx(1 - (1 - 0.004) ** 2)
    # Without the threshold the v2.1 behaviour (every available mechanism counted) is reproduced.
    assert variable_evidence(rows).set_index("source_observation_id").loc["a", "p_variable"] == pytest.approx(1 - (1 - 0.004) ** 2)


def test_variable_that_cannot_attain_the_threshold_is_not_counted_and_cannot_alert():
    rows = pd.DataFrame([("a", "salary", 0.5, 0.5, 0.004, 5000, 5000), ("a", "hours", 0.9, np.nan, np.nan, 30, np.nan),
                         ("z", "hours", 2 / 31, np.nan, np.nan, 30, np.nan)],
                        columns=["source_observation_id", "target_variable", "p_current", "p_history", "p_model", "current_n", "history_n"])
    record = record_value_evidence(variable_evidence(rows, threshold=0.02)).set_index("source_observation_id")
    assert record.loc["a", "value_variables_assessed"] == 2 and record.loc["a", "value_variables_testable"] == 1
    assert record.loc["a", "value_p"] == pytest.approx(1 - (1 - 0.004) ** 2)  # Sidak over 2 mechanisms of 1 variable
    # Nothing testable: the record keeps a value but it is above the threshold by construction.
    assert record.loc["z", "value_variables_testable"] == 0 and record.loc["z", "value_p"] > 0.02


def test_sidak_handles_tiny_probabilities_without_cancellation():
    assert sidak(np.array([1e-12]), np.array([3]))[0] == pytest.approx(3e-12, rel=1e-6)


def _cases(n=1000, **columns):
    frame = pd.DataFrame({"case_id": [f"c{i:04d}" for i in range(n)], "case_level": "PERSON", "state": "07", "sector": "1",
                          "fsu": [f"F{i // 20}" for i in range(n)], "value_p": 0.5, "coding_p": 0.5, "impact_se": 0.1,
                          "rule_error_count": 0, "rule_warning_count": 0})
    for name, values in columns.items():
        frame[name] = values
    return frame


def test_quiet_batch_gives_a_short_list_and_rules_come_first():
    cases = _cases()
    cases.loc[5, "rule_error_count"] = 1
    queue = build_queue(cases, FusionParameters())
    assert queue.tier.eq("A").sum() == 1 and queue.loc[5, "queue_position"] == 1   # no forced 1.4% "CRITICAL"


def test_budget_and_fsu_cap_bound_check_now_and_overflow_goes_to_check_if_time():
    cases = _cases()
    cases.loc[0:39, "value_p"] = np.linspace(1e-6, 1e-3, 40)      # 40 strong value checks in FSUs F0 and F1
    queue = build_queue(cases, FusionParameters(per_fsu_cap=5))
    check_now = queue.loc[queue.tier.eq("A")]
    assert len(check_now) == 9                                      # value share of a 10-case budget (1 slot reserved for coding)
    assert check_now.groupby("fsu").size().max() <= 5
    assert queue.loc[0:39, "tier"].isin(["A", "B"]).all()


def test_impact_orders_within_a_tier_but_never_changes_the_tier():
    cases = _cases()
    cases.loc[0:3, "value_p"] = [1e-5, 2e-5, 3e-5, 0.2]
    cases.loc[0:3, "impact_se"] = [0.1, 5.0, 1.0, 50.0]
    queue = build_queue(cases, FusionParameters())
    assert queue.loc[3, "tier"] == "NONE"                         # huge impact, weak evidence: not queued
    order = queue.loc[0:2].sort_values("queue_position").index.tolist()
    assert order == [1, 2, 0]                                      # within Check now: by impact


def test_impact_is_relative_to_the_domain_standard_error_not_its_total():
    """Audit N5: shares of small domains' totals were large; impact in SEs is comparable across domain sizes."""
    rng = np.random.default_rng(0)
    rows = []
    for domain, n in (("small", 60), ("large", 6000)):
        for i in range(n):
            rows.append({"source_observation_id": f"{domain}{i}", "target_variable": "salary", "domain": domain, "value": float(rng.normal(10000, 2000)),
                         "final_weight": 1.0, "stratum_key": domain, "psu_key": f"{domain}{i // 6}", "period_index": 1, "sector": "1", "expected_value": 10000.0})
    values = pd.DataFrame(rows)
    values.loc[0, "value"] = values.loc[60, "value"] = 100000.0      # the same x10 error in each domain
    impact = record_impact(values, domain_standard_errors(values)).set_index("source_observation_id")["impact_se"]
    ratio = impact["small0"] / impact["large0"]
    assert ratio < 15        # a share-of-total score would be ~100x larger in the 100x smaller domain


def test_fusion_requires_the_lane_inputs_and_matching_provenance(tmp_path):
    prepared = tmp_path / "prepared_persons.parquet"; prepared.touch()
    (tmp_path / "run_metadata.json").write_text(json.dumps({"run_id": "prep_a", "release": "2024", "observation": "first_visit", "design_period": "pre_2025"}))
    runs = []
    for name in ("stat", "context", "ml", "hist", "integ"):
        directory = tmp_path / name; directory.mkdir(); runs.append(directory)
        (directory / "run_metadata.json").write_text(json.dumps({"run_id": name, "release": "2024", "observation": "first_visit", "design_period": "pre_2025", "input_preprocessing_run_id": "wrong_prep"}))
    with pytest.raises(FusionFailure, match="historical and integrity"):
        FusionEngine(RunConfig(prepared, runs[0], runs[1], runs[2], tmp_path / "out"))._validate()
    with pytest.raises(FusionFailure, match="incompatible runs"):
        FusionEngine(RunConfig(prepared, runs[0], runs[1], runs[2], tmp_path / "out", historical_run=runs[3], integrity_run=runs[4]))._validate()


def test_evidence_card_reports_lanes_and_keeps_group_context_separate():
    row = pd.Series({"case_id": "case_1", "case_level": "PERSON", "source_observation_id": "s", "tier": "A", "priority_band": "CHECK_NOW", "queue_position": 3,
                     "lanes": "VALUE", "tier_reason": "r", "value_status": "ASSESSABLE", "value_p": 0.001, "value_lead_variable": "cws_earnings_salaried",
                     "fsu_q_value": 0.01, "fsu_notable": True, "fsu_statement": "FSU differs", "provenance_json": "{}"})
    card = build_evidence_card(row)
    assert card["queue"]["lanes"] == ["VALUE"] and card["value_check"]["tail_probability"] == 0.001
    assert "does not mean any answer" in card["group_context"]["note"] and "not a determination" in card["disclaimer"]


def test_legacy_construction_is_kept_only_as_baseline():
    cases = pd.DataFrame({"statistical_raw_score": [.1, .9], "contextual_raw_score": [.5, .5], "ml_raw_score": [.2, .3], "historical_raw_score": [.1, .8],
                          "influence_score": [1.0, 1.0], "rule_error_count": [0, 0]})
    assert legacy_fuse(cases).priority_score.iloc[1] > legacy_fuse(cases).priority_score.iloc[0]


def test_parameters_are_validated():
    with pytest.raises(ValueError):
        FusionParameters(review_budget_share=0)
