from __future__ import annotations

import pandas as pd

from ml.conditional_models import build_conditional_features, run_conditional_models
from ml.config import Parameters
from .test_isolation_forest import _base


def test_target_is_not_a_predictor_and_predictions_are_out_of_fold_deterministic() -> None:
    base = _base(80)
    base["fsu"] = [str(100 + i // 4) for i in range(80)]
    features, _, _ = build_conditional_features(base)
    assert "earnings_salaried" not in features.columns
    parameters = Parameters(minimum_model_population=10, maximum_training_rows=30, conditional_max_iterations=8)
    first = run_conditional_models(base, parameters)
    second = run_conditional_models(base, parameters)
    assert set(first.assessability_status) == {"ASSESSABLE"}
    assert first.predicted_value.notna().all()
    pd.testing.assert_frame_equal(first, second)


def test_revisit_is_explicitly_not_supported() -> None:
    base = _base(20)
    base["observation_type"] = "revisit"
    base["day7_hours"] = pd.NA
    evidence = run_conditional_models(base, Parameters(minimum_model_population=10))
    assert set(evidence.assessability_status) == {"NOT_ASSESSABLE"}
    assert set(evidence.assessability_reason) == {"CONDITIONAL_TARGET_OR_CONTEXT_UNAVAILABLE_FOR_OBSERVATION"}


def test_population_is_applicable_positive_earners_only() -> None:
    """Audit C1: placeholder zeros for non-salaried statuses must never enter the target (Vol. I §3.6.17/§3.6.19)."""
    base = _base(120)
    base["fsu"] = [str(100 + i // 4) for i in range(120)]
    base.loc[60:99, "cws_status"] = "91"          # not asked item 9
    base.loc[60:99, "earnings_salaried"] = "0"
    base.loc[100:104, "earnings_salaried"] = "0"  # salaried, genuine 0 in the reference month
    out = run_conditional_models(base, Parameters(minimum_model_population=10, conditional_max_iterations=50))
    assert out.loc[60:99, "assessability_reason"].eq("TARGET_NOT_APPLICABLE_FOR_CWS_STATUS").all()
    assert out.loc[100:104, "assessability_reason"].eq("APPLICABLE_ZERO_EARNINGS_NOT_MODELLED").all()
    assessed = out[out.assessability_status.eq("ASSESSABLE")]
    assert len(assessed) == 120 - 40 - 5
    assert (assessed.observed_value > 0).all()


def test_estimate_is_not_biased_low_and_residual_is_a_log_ratio() -> None:
    """Audit C1: the old model's estimate was ~47% of the typical value. A correct model is centred on the data."""
    import numpy as np
    rows = 600
    base = _base(rows)
    rng = np.random.default_rng(7)
    base["state"] = ["07" if i % 2 else "09" for i in range(rows)]
    level = np.where(base["state"].eq("07"), 30000.0, 12000.0)
    base["earnings_salaried"] = (level * np.exp(rng.normal(0, .25, rows))).round().astype(int).astype(str)
    base["fsu"] = [str(100 + i // 6) for i in range(rows)]
    out = run_conditional_models(base, Parameters(minimum_model_population=50))
    assessed = out[out.assessability_status.eq("ASSESSABLE")]
    ratio = assessed.observed_to_estimate_ratio
    assert 0.9 < ratio.median() < 1.1                                  # centred, not ~0.47
    for state, rows_ in assessed.groupby(base.loc[assessed.index, "state"]):
        assert 0.85 < rows_.observed_to_estimate_ratio.median() < 1.15   # geography is modelled
    assert np.allclose(assessed.raw_model_score, np.abs(np.log(assessed.observed_value / assessed.predicted_value)))


def test_folds_keep_each_fsu_together() -> None:
    base = _base(200)
    base["fsu"] = [str(100 + i // 10) for i in range(200)]
    out = run_conditional_models(base, Parameters(minimum_model_population=10, conditional_max_iterations=20))
    assert out.groupby(base["fsu"]).training_fold.nunique().eq(1).all()
