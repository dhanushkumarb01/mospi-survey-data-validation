from __future__ import annotations

import pandas as pd

from ml.config import Parameters
from ml.isolation_forest import build_if_features, run_isolation_forest


def _base(rows: int = 24) -> pd.DataFrame:
    return pd.DataFrame({
        "source_observation_id": [f"r-{i}" for i in range(rows)], "record_id": [f"h-{i}" for i in range(rows)],
        "release": "2024", "observation_type": "first_visit", "design_period": "pre_2025", "visit": "V1", "month": "",
        "preprocessing_run_id": "prepared", "prepared_ready": True, "age": [str(20 + i % 30) for i in range(rows)], "sex": ["1" if i % 2 == 0 else "2" for i in range(rows)],
        "education": "07", "cws_status": "31", "occupation_major_group": "5", "industry_division": "47", "occupation": "522", "industry": "4711",
        "day7_hours": [str(6 + i % 5) for i in range(rows)], "earnings_salaried": [str(100 + i) for i in range(rows)], "earnings_self_employed": "0", "state": "01", "sector": "1", "fsu": "100",
    })


def test_feature_space_excludes_weight_and_identifiers_and_handles_missing() -> None:
    values = _base()
    values.loc[0, "earnings_salaried"] = "not-number"
    features, numeric, categorical = build_if_features(values)
    assert "MoSPI_weight" not in features.columns
    assert "source_observation_id" not in features.columns
    assert pd.isna(features.loc[0, "earnings_salaried"])
    assert set(numeric).isdisjoint(categorical)


def test_isolation_is_deterministic_and_not_assessable_when_required_data_missing() -> None:
    values = _base()
    values.loc[0, "age"] = ""
    parameters = Parameters(minimum_model_population=10, maximum_training_rows=20, isolation_trees=20, isolation_max_samples=10)
    first = run_isolation_forest(values, parameters)
    second = run_isolation_forest(values, parameters)
    assert first.loc[0, "assessability_status"] == "NOT_ASSESSABLE"
    pd.testing.assert_frame_equal(first, second)
    assert set(first.loc[first.assessability_status.eq("ASSESSABLE"), "evidence_statement"]) == {"Unusual multivariate response pattern."}
