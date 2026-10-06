from pathlib import Path

import pandas as pd
import pytest

from pattern.config import PatternParameters
from pattern.engine import PatternEngine, PatternFailure, RunConfig


def _engine() -> PatternEngine:
    engine = PatternEngine(RunConfig(Path("input.parquet"), Path("runs"), parameters=PatternParameters(
        minimum_fsu_population=3, minimum_reference_population=6, minimum_valid_target_population=3,
        minimum_temporal_population=3, minimum_temporal_history=2, minimum_revisit_linked_population=3,
    )))
    engine.preprocessing_run_id = "prepared-test"
    engine.pattern_run_id = "pattern-test"
    return engine


def _base(*, shifted: bool = False, post: bool = False) -> pd.DataFrame:
    rows = []
    for fsu, offset in (("A", 20 if shifted else 0), ("B", 0), ("C", 1)):
        for period in range(1, 5):
            for person in range(4):
                value = offset + period * 3 + person
                rows.append({
                    "source_observation_id": f"{fsu}-{period}-{person}", "release": "2025" if post else "2024",
                    "observation_type": "first_visit", "design_period": "post_2025" if post else "pre_2025",
                    "visit": "V1", "month": str(period) if post else "", "quarter": "" if post else f"Q{period}",
                    "state": "1", "sector": "1", "stratum": "10", "fsu": fsu, "ready": True,
                    "age": value, "day7_total_hours": value, "cws_earnings_salaried": value * 10,
                    "cws_earnings_self_employed": value * 5, "cws_status": "31" if person < 3 else "11",
                    "principal_occupation_major_group": "1" if person < 3 else "2",
                    "principal_industry_division": "01" if person < 3 else "02",
                })
    return pd.DataFrame(rows)


def test_distribution_shift_and_small_fsu_are_explicit():
    engine = _engine()
    result = engine._distribution(_base(shifted=True))
    shifted = result[(result.fsu == "A") & (result.variable == "age")].iloc[0]
    stable = result[(result.fsu == "B") & (result.variable == "age")].iloc[0]
    assert shifted.assessability_status == "ASSESSABLE"
    assert shifted.evidence_score > stable.evidence_score
    tiny = _base().iloc[:2]
    result = engine._distribution(tiny)
    # Below-minimum FSUs are explicit; an item applying to nobody in the FSU is ZERO_VALID_OBSERVATIONS.
    assert set(result.assessability_reason) <= {"PATTERN_GROUP_BELOW_MINIMUM", "ZERO_VALID_OBSERVATIONS"}
    assert set(result.assessability_status) == {"NOT_ASSESSABLE"}


def test_concentration_and_zero_variance_are_not_errors():
    engine = _engine()
    frame = _base()
    frame.loc[frame.fsu.eq("A"), "age"] = 30
    result = engine._concentration(frame)
    low = result[(result.fsu == "A") & (result.variable == "age")].iloc[0]
    normal = result[(result.fsu == "B") & (result.variable == "age")].iloc[0]
    assert low.assessability_status == "ASSESSABLE"
    assert low.evidence_score > normal.evidence_score
    assert "error" not in low.evidence_statement.lower()


def test_digit_heaping_does_not_use_categorical_codes():
    engine = _engine()
    frame = _base()
    frame.loc[frame.fsu.eq("A"), "age"] = [20, 30, 40, 50] * 4
    result = engine._heaping(frame)
    assert set(result.variable) == set(engine.config.parameters.heaping_targets)
    age_a = result[(result.fsu == "A") & (result.variable == "age")].iloc[0]
    age_b = result[(result.fsu == "B") & (result.variable == "age")].iloc[0]
    assert age_a.evidence_score > age_b.evidence_score


def test_month_and_design_period_are_never_pooled():
    engine = _engine()
    post = engine._distribution(_base(post=True))
    assert set(post.month) == {"1", "2", "3", "4"}
    assert set(post.design_period) == {"post_2025"}
    # Each month has exactly two other FSUs × four observations as reference;
    # it is not silently expanded to the 32 records across all four months.
    assert set(post.loc[post.variable.eq("age"), "reference_n"]) == {8}


def test_temporal_requires_history_and_never_crosses_break():
    engine = _engine()
    frame = _base()
    result = engine._temporal(frame)
    assert set(result.design_period) == {"pre_2025"}
    early = result[result.period.eq("Q1") & ~result.variable.eq("median_cws_earnings_self_employed")]
    assert set(early.assessability_reason) == {"INSUFFICIENT_REFERENCE_HISTORY"}
    assert "STRUCTURAL_BREAK" not in set(result.assessability_reason.dropna())


def test_normalisation_schema_and_determinism():
    engine = _engine()
    result = engine._normalise(engine._distribution(_base()))
    assert result.evidence_id.is_unique
    assert list(result.columns)[0:3] == ["evidence_id", "pattern_component", "group_level"]
    assert result.equals(engine._normalise(engine._distribution(_base())))


def test_revisit_is_explicitly_unavailable_without_valid_inputs():
    engine = _engine()
    output = engine._revisit(_base(), {"release": "2025", "observation": "first_visit", "design_period": "post_2025"})
    assert output.iloc[0].assessability_reason == "REVISIT_DATA_UNAVAILABLE"


def test_pairing_of_revisit_inputs_is_required():
    with pytest.raises(ValueError):
        PatternEngine(RunConfig(Path("a"), Path("b"), revisit_prepared_person_path=Path("revisit")))


def test_non_applicable_placeholders_do_not_form_fsu_earnings_distributions():
    """Audit H5: earnings comparisons use only persons for whom the item applies."""
    engine = _engine()
    frame = _base()
    result = engine._distribution(frame)
    salaried = result[result.variable.eq("cws_earnings_salaried") & result.assessability_status.eq("ASSESSABLE")]
    assert set(salaried.n) == {12}         # 16 people per FSU, 12 with status 31; status-11 placeholders excluded


def test_heaping_statements_never_claim_a_direction_the_numbers_do_not_support():
    """Audit H4: 'higher' only when the FSU share of 0/5 endings exceeds the reference share."""
    import json
    engine = _engine()
    frame = _base()
    frame.loc[frame.fsu.eq("A"), "age"] = [21, 22, 23, 24] * 4                 # no 0/5 endings at all
    result = engine._heaping(frame)
    a = result[(result.fsu == "A") & result.assessability_status.eq("ASSESSABLE")].iloc[0]
    details = json.loads(a.details_json)
    assert details["fsu_share_ending_0_or_5"] < details["reference_share_ending_0_or_5"]
    assert "not higher" in a.evidence_statement and a.p_value > 0.5


def test_scores_are_valid_probabilities_and_q_values():
    """Audit M1: no position above 1 and no negative score."""
    engine = _engine()
    frame = _base(shifted=True)
    for result in (engine._distribution(frame), engine._concentration(frame), engine._heaping(frame)):
        assessed = result[result.assessability_status.eq("ASSESSABLE")]
        assert assessed.p_value.between(0, 1).all() and assessed.q_value.between(0, 1).all()
        assert (assessed.evidence_score >= 0).all() and assessed.evidence_rank.between(0, 1).all()
        assert (assessed.q_value >= assessed.p_value - 1e-12).all()


def test_tests_account_for_fsu_size():
    """Audit H6: the same proportional difference is stronger evidence in a larger FSU, not a smaller one."""
    from pattern.engine import g_test_p_value
    import numpy as np
    reference = np.array([500.0, 500.0])
    small, _ = g_test_p_value(np.array([7.0, 3.0]), reference)
    large, _ = g_test_p_value(np.array([70.0, 30.0]), reference)
    assert large < small


def test_overdispersion_correction_calibrates_clustered_null():
    """Evaluation finding: clustered answers made 16-54% of clean FSUs 'notable'. Inflated null statistics are rescaled."""
    import numpy as np
    from scipy import stats
    from pattern.engine import benjamini_hochberg, overdispersion_adjust
    rng = np.random.default_rng(1)
    z = rng.normal(0, 2.0, 2000)                               # null with dispersion factor 4
    p = pd.Series(stats.chi2.sf(z ** 2, 1))
    assert (benjamini_hochberg(p) < .05).mean() > .1           # uncorrected: many false alerts
    adjusted, phi = overdispersion_adjust(p, one_sided=False)
    assert 3 < phi < 5
    assert (benjamini_hochberg(adjusted) < .05).mean() < .01   # corrected: calibrated
    signal = pd.concat([p, pd.Series([1e-40] * 5)], ignore_index=True)
    adjusted, _ = overdispersion_adjust(signal, one_sided=False)
    assert (benjamini_hochberg(adjusted).iloc[-5:] < .05).all()  # genuine strong signals survive
