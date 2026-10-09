from __future__ import annotations

import numpy as np
import pandas as pd

from ml.conditional_models import TARGETS, run_conditional_models
from ml.config import Parameters
from .test_isolation_forest import _base


def _periods(rows: int, periods: tuple[int, ...] = (1, 2)) -> pd.DataFrame:
    base = _base(rows)
    base["fsu"] = [str(100 + i // 5) for i in range(rows)]
    base["period_index"] = [periods[i * len(periods) // rows] for i in range(rows)]
    base["day7_activity1_status"] = "31"
    base["day7_activity1_industry"] = "47"
    base["casual_wage"] = "0"
    return base


def _salaried(table: pd.DataFrame) -> pd.DataFrame:
    return table[table.target.eq("cws_earnings_salaried")].reset_index(drop=True)


def test_target_is_never_a_predictor() -> None:
    for spec in TARGETS:
        assert spec.value_column not in spec.numeric_features + spec.categorical_features
        assert not {"state_weight", "MoSPI_weight", "fsu", "source_observation_id"} & set(spec.numeric_features + spec.categorical_features)


def test_later_period_is_scored_by_a_model_trained_only_on_earlier_periods() -> None:
    base = _periods(200)
    parameters = Parameters(minimum_model_population=20, conditional_max_iterations=20)
    table, registry = run_conditional_models(base, parameters)
    salary = _salaried(table)
    later = salary[base["period_index"].eq(2).to_numpy()]
    assert later.assessability_status.eq("ASSESSABLE").all()
    assert later.training_scheme.eq("TRAINED_ON_EARLIER_PERIODS").all() and later.training_periods.eq("1").all()
    first = salary[base["period_index"].eq(1).to_numpy()]
    assert first.training_scheme.eq("IN_ROUND_CROSS_FIT_NO_EARLIER_PERIOD").all()          # fallback is labelled
    trained = [r for r in registry if r["target"] == "cws_earnings_salaried" and r["scored_period"] == 2]
    assert trained and trained[0]["training_periods"] == [1]
    assert later.model_tail_p.between(0, 1).all() and (later.usual_range_low <= later.usual_range_high).all()
    again, _ = run_conditional_models(base, parameters)
    pd.testing.assert_frame_equal(table, again)                                               # deterministic


def test_revisit_is_explicitly_not_supported() -> None:
    base = _periods(40)
    base["observation_type"] = "revisit"
    table, _ = run_conditional_models(base, Parameters(minimum_model_population=10))
    salary = _salaried(table)
    assert set(salary.assessability_status) == {"NOT_ASSESSABLE"}
    assert set(salary.assessability_reason) == {"CONDITIONAL_CONTEXT_UNAVAILABLE_FOR_OBSERVATION"}


def test_population_is_applicable_positive_values_only() -> None:
    """Audit C1: placeholder zeros for non-salaried statuses must never enter the target (Vol. I §3.6.17/§3.6.19)."""
    base = _periods(160)
    base.loc[60:99, "cws_status"] = "91"          # not asked item 9
    base.loc[60:99, "earnings_salaried"] = "0"
    base.loc[100:104, "earnings_salaried"] = "0"  # salaried, genuine 0 in the reference month
    table, _ = run_conditional_models(base, Parameters(minimum_model_population=10, conditional_max_iterations=30))
    salary = _salaried(table)
    assert salary.loc[60:99, "assessability_reason"].eq("TARGET_NOT_APPLICABLE_FOR_STATUS").all()
    assert salary.loc[100:104, "assessability_reason"].eq("APPLICABLE_ZERO_OR_NEGATIVE_NOT_MODELLED").all()
    assert (salary[salary.assessability_status.eq("ASSESSABLE")].observed_value > 0).all()


def test_estimate_is_centred_and_an_extreme_value_has_a_small_tail_probability() -> None:
    rows = 800
    base = _periods(rows)
    rng = np.random.default_rng(7)
    base["state"] = ["07" if i % 2 else "09" for i in range(rows)]
    level = np.where(base["state"].eq("07"), 30000.0, 12000.0)
    base["earnings_salaried"] = (level * np.exp(rng.normal(0, .25, rows))).round().astype(int).astype(str)
    base.loc[rows - 1, "earnings_salaried"] = str(int(level[rows - 1] * 10))           # an extra zero
    table, _ = run_conditional_models(base, Parameters(minimum_model_population=50))
    salary = _salaried(table)
    later = salary[base["period_index"].eq(2).to_numpy() & salary.assessability_status.eq("ASSESSABLE").to_numpy()]
    assert 0.9 < later.observed_to_estimate_ratio.iloc[:-1].median() < 1.1                 # centred on the data
    # The x10 value is beyond every calibration residual: its p is the finite-sample floor 1/(n_cal + 1).
    assert later.model_tail_p.iloc[-1] == later.model_tail_p.min() and later.model_tail_p.iloc[-1] < 0.02
    assert later.model_tail_p.iloc[:-1].median() > 0.3                                      # ordinary values are not


def test_tail_probabilities_are_calibrated_within_state_when_residual_spread_differs() -> None:
    """Mondrian calibration (ML v2.1): one national calibration set over-flags a State with wider residuals
    and under-flags one with narrower residuals; calibrating within State restores the nominal rate in both."""
    rows = 6000
    base = _periods(rows)
    rng = np.random.default_rng(11)
    base["state"] = ["07" if i % 2 else "09" for i in range(rows)]
    sigma = np.where(base["state"].eq("07"), 0.8, 0.1)
    base["earnings_salaried"] = (15000.0 * np.exp(rng.normal(0, sigma))).round().astype(int).astype(str)

    def flagged_share(parameters: Parameters) -> dict[str, float]:
        salary = _salaried(run_conditional_models(base, parameters)[0])
        later = salary[base["period_index"].eq(2).to_numpy() & salary.assessability_status.eq("ASSESSABLE").to_numpy()]
        state = base.loc[base["period_index"].eq(2), "state"].to_numpy()[: len(later)]
        return {s: float((later.model_tail_p.to_numpy()[state == s] <= 0.05).mean()) for s in ("07", "09")}

    national = flagged_share(Parameters(minimum_model_population=50, conformal_group_minimum=0))
    by_state = flagged_share(Parameters(minimum_model_population=50))
    assert national["07"] > 0.08 and national["09"] < 0.01          # pooled calibration: wide State over-flagged
    assert 0.02 < by_state["07"] < 0.08 and 0.02 < by_state["09"] < 0.08
