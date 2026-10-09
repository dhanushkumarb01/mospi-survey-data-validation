from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pattern.engine import fsu_summary
from pattern.fieldwork import cauchy_combination, duplicate_checks, duration_checks

from .test_engine import _engine

CELL = {"release": "2024", "observation_type": "first_visit", "design_period": "pre_2025", "visit": "V1", "month": "", "state": "01", "sector": "1", "stratum": "10"}


def test_cauchy_combination_is_a_valid_p_value_under_the_null() -> None:
    assert cauchy_combination(np.array([0.3])) == pytest.approx(0.3)
    rng = np.random.default_rng(1)
    combined = np.array([cauchy_combination(rng.uniform(size=8)) for _ in range(4000)])
    assert abs((combined < 0.05).mean() - 0.05) < 0.015          # nominal size under independence
    assert cauchy_combination(np.array([1e-12, 0.5, 0.9])) < 1e-10  # one strong check is not diluted


def test_fsu_alerts_use_one_combined_q_value_per_fsu() -> None:
    rows = []
    for fsu in range(40):
        for check in range(10):
            p = 1e-9 if (fsu == 0 and check == 0) else 0.5
            rows.append({**CELL, "fsu": f"F{fsu}", "group_id": f"g{fsu}", "group_level": "FSU", "pattern_component": f"c{check}", "variable": "v",
                         "assessability_status": "ASSESSABLE", "p_value": p, "q_value": p, "evidence_statement": "s"})
    summary = fsu_summary(pd.DataFrame(rows)).set_index("group_id")
    assert summary.loc["g0", "notable"] and summary.loc["g0", "strongest_component"] == "c0"
    assert not summary.drop(index="g0")["notable"].any()
    assert summary["checks"].eq(10).all()


def test_a_check_with_p_equal_to_one_does_not_veto_the_fsus_other_evidence() -> None:
    """The Cauchy combination returned 1 whenever one check had p = 1 (tan(-pi/2)); 86% of 2024 FSUs had one."""
    rows = []
    for fsu in range(40):
        for check, p in enumerate((1e-9 if fsu == 0 else 0.5, 1.0, 0.5)):
            rows.append({**CELL, "fsu": f"F{fsu}", "group_id": f"g{fsu}", "group_level": "FSU", "pattern_component": f"c{check}", "variable": "v",
                         "assessability_status": "ASSESSABLE", "p_value": p, "q_value": p, "evidence_statement": "s"})
    summary = fsu_summary(pd.DataFrame(rows)).set_index("group_id")
    assert summary.loc["g0", "fsu_combined_p"] == pytest.approx(3e-9) and summary.loc["g0", "notable"]
    assert not summary.drop(index="g0")["notable"].any()


def test_uncalibrated_fieldwork_checks_are_context_not_alerts() -> None:
    rows = []
    for fsu in range(40):
        for component, p in (("interview_duration_short", 1e-9 if fsu == 0 else 0.5), ("digit_heaping", 0.5)):
            rows.append({**CELL, "fsu": f"F{fsu}", "group_id": f"g{fsu}", "group_level": "FSU", "pattern_component": component, "variable": "v",
                         "assessability_status": "ASSESSABLE", "p_value": p, "q_value": p, "evidence_statement": "s"})
    summary = fsu_summary(pd.DataFrame(rows)).set_index("group_id")
    assert not summary.loc["g0", "notable"] and summary.loc["g0", "context_only_notable_checks"] == 1 and summary["checks"].eq(1).all()


def test_age_sex_standardisation_does_not_flag_an_older_fsu_for_its_demography() -> None:
    engine = _engine()
    rows = []
    rng = np.random.default_rng(3)
    for fsu in range(8):
        older = fsu == 0                                   # FSU 0 has mostly elderly members
        for person in range(30):
            age = int(rng.integers(65, 80)) if older else int(rng.integers(20, 80))
            status = "94" if age >= 60 else "31"           # status depends on age only, identically everywhere
            rows.append({**CELL, "source_observation_id": f"{fsu}-{person}", "fsu": f"F{fsu}", "quarter": "Q3", "ready": True,
                         "age": age, "sex": "1", "cws_status": status, "day7_total_hours": np.nan, "cws_earnings_salaried": np.nan,
                         "cws_earnings_self_employed": np.nan, "principal_occupation_major_group": "", "principal_industry_division": ""})
    result = engine._distribution(pd.DataFrame(rows))
    status = result[(result.variable == "cws_status") & (result.fsu == "F0")].iloc[0]
    assert status.assessability_status == "ASSESSABLE"
    assert '"composition_adjusted":true' in status.details_json
    assert status.p_value_unadjusted > 0.05                # explained by age, not flagged


def test_copied_household_is_found_and_similar_villagers_are_allowed_for() -> None:
    fields = [f"dup_{i}" for i in range(16)]
    rows = []
    rng = np.random.default_rng(5)
    for fsu in range(6):
        for household in range(8):
            for person in range(3):
                answers = {f: str(rng.integers(0, 4)) for f in fields}
                rows.append({**CELL, "fsu": f"F{fsu}", "household": f"H{fsu}-{household}", **answers})
    frame = pd.DataFrame(rows)
    copied = frame.index[(frame.fsu == "F0") & (frame.household == "H0-1")]
    source = frame.index[(frame.fsu == "F0") & (frame.household == "H0-0")]
    frame.loc[copied, fields] = frame.loc[source, fields].to_numpy()     # household 1 copies household 0
    result = pd.DataFrame(duplicate_checks(frame, fields, minimum_common=15, threshold=0.95, minimum_reference_pairs=50)).set_index("fsu")
    assert result.loc["F0", "p_value"] < 0.001
    assert result.drop(index="F0")["p_value"].min() > 0.05


def test_short_interviews_are_a_one_sided_fieldwork_signal() -> None:
    rows = []
    for fsu in range(6):
        for household in range(8):
            rows.append({**CELL, "fsu": f"F{fsu}", "survey_duration": str(10 if fsu == 0 else 50 + household),
                         "survey_date": f"{10 + household % 4:02d}012024", "response": "1", "survey_code": "1"})
    result = pd.DataFrame(duration_checks(pd.DataFrame(rows), minimum_fsu=4, minimum_reference=20))
    duration = result[result.component.eq("interview_duration_short")].set_index("fsu")
    assert duration.loc["F0", "p_value"] < 0.001 and duration.drop(index="F0")["p_value"].min() > 0.05
