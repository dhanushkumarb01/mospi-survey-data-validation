from __future__ import annotations

import pandas as pd

from ml.config import Parameters
from ml.lof import run_peer_lof
from .test_isolation_forest import _base


def _assignments(base: pd.DataFrame, peer: str = "pg-a") -> pd.DataFrame:
    return pd.DataFrame({"source_observation_id": base.source_observation_id, "peer_group_id": peer, "peer_group_size": len(base), "assessability_status": "ASSESSABLE", "not_assessable_reason": pd.NA, "reference_run_id": "prepared", "specification_version": "plfs-peer-groups-v1.0"})


def test_lof_uses_existing_peer_assignment_and_marks_small_population_not_assessable() -> None:
    base = _base(20)
    evidence = run_peer_lof(base, _assignments(base), Parameters(lof_minimum_population=30))
    assert set(evidence.assessability_status) == {"NOT_ASSESSABLE"}
    assert set(evidence.assessability_reason) == {"INSUFFICIENT_VALID_PEER_FEATURE_POPULATION"}


def test_lof_is_peer_scoped() -> None:
    base = _base(40)
    assignments = _assignments(base)
    assignments.loc[20:, "peer_group_id"] = "pg-b"
    assignments.loc[:19, "peer_group_size"] = 20
    assignments.loc[20:, "peer_group_size"] = 20
    evidence = run_peer_lof(base, assignments, Parameters(lof_minimum_population=10, lof_neighbors=5, lof_minimum_distinct_points=6))
    assert set(evidence.assessability_status) == {"ASSESSABLE"}
    assert set(evidence.peer_group_id) == {"pg-a", "pg-b"}
    assert set(evidence.evidence_statement) == {"Local unusualness within the comparable peer population."}


def test_duplicate_heavy_groups_give_finite_density_ratios() -> None:
    """Audit H7: identical answers made k-distance 0 and scores above 1e6."""
    import numpy as np
    base = _base(300)
    base["age"] = [str(30 + i % 20) for i in range(300)]          # few distinct values, many exact repeats
    base["day7_hours"] = ["8"] * 290 + ["8"] * 9 + ["19"]
    base["earnings_salaried"] = ["15000"] * 150 + ["20000"] * 149 + ["21000"]
    evidence = run_peer_lof(base, _assignments(base), Parameters(lof_minimum_population=30, lof_neighbors=20))
    scores = evidence.loc[evidence.assessability_status.eq("ASSESSABLE"), "raw_model_score"]
    assert len(scores) == 300 and np.isfinite(scores).all()
    assert scores.max() < 100                                       # a density ratio, not a numerical explosion
    assert scores.idxmax() == 299                                   # the one genuinely different answer stands out


def test_too_few_distinct_values_is_not_assessable() -> None:
    base = _base(60)
    for column in ("age", "day7_hours", "earnings_salaried"):
        base[column] = base[column].iloc[0]
    evidence = run_peer_lof(base, _assignments(base), Parameters(lof_minimum_population=30))
    assert set(evidence.assessability_reason) == {"INSUFFICIENT_DISTINCT_PEER_VALUES"}
