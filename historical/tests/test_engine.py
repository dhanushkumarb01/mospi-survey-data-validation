from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from historical.config import HistoricalParameters
from historical.engine import (HistoricalEngine, HistoricalFailure, RunConfig, aggregate_indicators, deduplicate_periods,
                               load_release, record_evidence)

PARAMS = HistoricalParameters(minimum_reference_size=5, minimum_domain_persons=5, minimum_domain_earners=3)


def _rows(release: str, quarter: str, n: int, salary: float, *, status: str = "31", start: int = 0, state: str = "07") -> list[dict]:
    month = {"2025": quarter}.get(release, "")
    return [{
        "MoSPI_source_row": i + 2, "MoSPI_record_key": f"{release}|{quarter}|{state}|{i}", "MoSPI_release": release, "MoSPI_observation": "first_visit",
        "MoSPI_design_period": "post_2025" if release == "2025" else "pre_2025", "MoSPI_visit": "V1", "MoSPI_quarter": "Q1" if release == "2025" else quarter,
        "MoSPI_month": month, "MoSPI_state": state, "MoSPI_sector": "2", "MoSPI_prepared_status": "ready_for_downstream_preparation_only",
        "MoSPI_stratum": "01", "MoSPI_fsu": f"F{i % 4}",
        "Day7_Act1_Status_Code": status, "Day7_Act1_Industry_Code": "64", "Day7_Act1_Wage": "0",
        "das17": status, "ind17": "64", "ern17": "0",
        "Person_Serial_No": "01", "CWS_Status_Code": status, "Age": "35", "District_Code": "01", "Principal_Occupation_Code": "241",
        "Principal_Industry_Code": "64190", "CWS_Earnings_Salaried": str(salary + i), "CWS_Earnings_SelfEmployed": "0", "Day7_Total_Hours": "8",
        "Subsample_Multiplier": "200", "Ns_Count_Sector_Stratum_Substratum_Subsample": "4", "Ns_Count_Sector_Stratum_Substratum": "8",
        "State_Sector_Stratum_Substra": "4",
        # 2025 contract fields
        "srl": "01", "acws": status, "age": "35", "dc": "01", "ocu_pas": "241", "ind_pas": "64190", "ern_reg": str(salary + i), "ern_self": "0",
        "hr7": "8", "mult": "200", "nsc": "8",
    } for i in range(start, start + n)]


def _write(tmp: Path, name: str, release: str, rows: list[dict]) -> Path:
    folder = tmp / name; folder.mkdir()
    path = folder / "prepared_persons.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    (folder / "run_metadata.json").write_text(json.dumps({"run_id": name, "release": release, "observation": "first_visit",
                                                          "design_period": "post_2025" if release == "2025" else "pre_2025"}), encoding="utf-8")
    return path


def test_record_is_compared_only_with_strictly_earlier_periods(tmp_path: Path) -> None:
    rows = _rows("2024", "Q3", 10, 10000) + _rows("2024", "Q4", 10, 10000, start=10) + _rows("2024", "Q5", 1, 99999, start=20)
    frame, _ = load_release(_write(tmp_path, "t", "2024", rows))
    evidence = record_evidence(frame, deduplicate_periods([frame]), PARAMS)
    salary = evidence[evidence.target_variable.eq("cws_earnings_salaried")].set_index("source_observation_id")
    first = salary[salary.period_index.eq(3)]
    assert first.assessability_reason.eq("NO_EARLIER_PERIOD_SUPPLIED").all()       # no history before the first period supplied
    q5 = salary[salary.period_index.eq(5)].iloc[0]
    assert q5.reference_size == 20 and q5.historical_percentile == 1.0 and q5.distribution_position == "UPPER_TAIL"
    q4 = salary[salary.period_index.eq(4)]
    assert q4.reference_size.eq(10).all()                                          # Q4 sees only Q3, never itself or later


def test_overlapping_releases_are_deduplicated_so_no_record_is_its_own_reference(tmp_path: Path) -> None:
    base = _rows("2023_24", "Q1", 10, 10000)
    overlap = _rows("2023_24", "Q3", 10, 20000, start=50)
    old = _write(tmp_path, "old", "2023_24", [{**r, "b4q1_perv1": "01", "b6q5_perv1": "31", "b4q6_perv1": "35", "distcode_perv1": "01",
                                               "b5pt1q6_perv1": "241", "b5pt1q5_perv1": "64190", "b6q9_perv1": r["CWS_Earnings_Salaried"],
                                               "b6q10_perv1": "0", "b6q7_3pt1_perv1": "8", "mult_perv1": "200", "NSS_perv1": "4", "NSC_perv1": "8",
                                               "no_qtr_perv1": "4", "b6q4_3pt1_perv1": "31", "b6q5_3pt1_perv1": "64",
                                               "b6q9_3pt1_perv1": "0"} for r in base + overlap])
    new = _write(tmp_path, "new", "2024", _rows("2024", "Q3", 10, 20000, start=50))   # same Jan-Mar 2024 records
    destination = HistoricalEngine(RunConfig(new, (old,), tmp_path / "out", "run", PARAMS)).run()
    evidence = pd.read_parquet(destination / "historical_record_evidence.parquet")
    q3 = evidence[evidence.target_variable.eq("cws_earnings_salaried")]
    assert q3.reference_size.eq(10).all()               # Jul-Sep 2023 only; the duplicated Jan-Mar 2024 copy is excluded
    assert q3.reference_median.eq(np.median([10000 + i for i in range(10)])).all()


def test_january_2025_is_never_compared_with_2024_and_design_periods_cannot_mix(tmp_path: Path) -> None:
    jan = _write(tmp_path, "jan", "2025", _rows("2025", "1", 10, 10000) + _rows("2025", "2", 3, 10000, start=10))
    frame, _ = load_release(jan)
    evidence = record_evidence(frame, deduplicate_periods([frame]), PARAMS)
    assert evidence[evidence.period_index.eq(1)].assessability_reason.isin(
        ["DESIGN_BREAK_NO_COMPARABLE_EARLIER_PERIOD", "TARGET_NOT_APPLICABLE_FOR_STATUS"]).all()
    pre = _write(tmp_path, "pre", "2024", _rows("2024", "Q3", 10, 10000))
    with pytest.raises(HistoricalFailure):
        HistoricalEngine(RunConfig(jan, (pre,), tmp_path / "out", "x", PARAMS)).run()


def test_placeholder_values_never_enter_history(tmp_path: Path) -> None:
    rows = _rows("2024", "Q3", 10, 10000) + _rows("2024", "Q4", 10, 0, status="91", start=10)
    frame, _ = load_release(_write(tmp_path, "t", "2024", rows))
    evidence = record_evidence(frame, deduplicate_periods([frame]), PARAMS)
    students = evidence[evidence.target_variable.eq("cws_earnings_salaried") & evidence.period_index.eq(4)]
    assert students.assessability_reason.eq("TARGET_NOT_APPLICABLE_FOR_STATUS").all()


def test_aggregate_definitions_and_break(tmp_path: Path) -> None:
    rows = (_rows("2024", "Q3", 8, 10000) + _rows("2024", "Q3", 2, 0, status="81", start=8)
            + _rows("2024", "Q3", 10, 0, status="91", start=10))
    frame, _ = load_release(_write(tmp_path, "t", "2024", rows))
    table = aggregate_indicators(deduplicate_periods([frame]), PARAMS)
    national = table[table.level.eq("national")].set_index("indicator")["value"]
    assert national["lfpr_cws_15plus"] == pytest.approx(10 / 20)     # 8 workers + 2 seeking work, of 20 aged 15+
    assert national["wpr_cws_15plus"] == pytest.approx(8 / 20)
    assert national["ur_cws_15plus"] == pytest.approx(2 / 10)
    assert table.change_reason.eq("NO_EARLIER_PERIOD_SUPPLIED").all()


def test_small_domain_noise_is_not_screened_as_unusual_change():
    """Small areas swing by chance; a change must also exceed its sampling noise (v1.1)."""
    rows = []
    def people(state, period, n, unemployed):
        for i in range(n):
            status = "81" if i < unemployed else "31"
            rows.append({"ready": True, "final_weight": 1.0, "period_index": period, "cws_status": status, "age": 30.0, "design_period": "pre_2025",
                         "state": state, "district": "01", "sector": "2", "stratum": "01", "fsu": f"F{i % 8}",
                         "cws_earnings_salaried": 10000.0, "cws_earnings_salaried__applicable": status == "31",
                         "day7_total_hours": 8.0, "day7_total_hours__applicable": status == "31"})
    for s in ("01", "02", "03", "04", "05"):
        people(s, 1, 400, 20); people(s, 2, 400, 20 + 2 * int(s))          # stable areas, slightly different changes
    people("06", 1, 400, 20); people("06", 2, 400, 200)                     # large area, large change
    people("07", 1, 6, 0); people("07", 2, 6, 3)                            # tiny area, large change by chance
    table = aggregate_indicators(pd.DataFrame(rows), HistoricalParameters(minimum_domain_persons=5))
    ur = table[table.level.eq("state") & table.indicator.eq("ur_cws_15plus") & table.period_index.eq(2)].set_index("state")
    assert bool(ur.loc["06", "notable_change"]) is True
    assert bool(ur.loc["07", "notable_change"]) is False and abs(ur.loc["07", "robust_z"]) >= 3.5


def test_tail_probabilities_are_finite_sample_and_out_of_sample():
    from historical.engine import tail_probabilities
    reference = np.arange(1.0, 20.0)                  # 19 earlier values
    upper, lower, two = tail_probabilities(np.array([100.0, 10.0]), reference)
    assert upper[0] == pytest.approx(1 / 20)          # nothing in the reference is as high: (0 + 1)/(19 + 1)
    assert two[0] == pytest.approx(2 / 20)
    assert two[1] == pytest.approx(1.0)               # the median value carries no tail evidence


def test_same_quarter_previous_year_is_shown_pre_2025(tmp_path: Path) -> None:
    rows = (_rows("2024", "Q3", 10, 10000) + _rows("2024", "Q4", 10, 10000, start=10)
            + _rows("2024", "Q5", 10, 10000, start=20) + _rows("2024", "Q6", 10, 10000, start=30))
    old = [{**r, "MoSPI_release": "2023_24"} for r in _rows("2023_24", "Q1", 10, 9000, start=40)]
    frame, _ = load_release(_write(tmp_path, "t", "2024", rows))
    prior, _ = load_release(_write(tmp_path, "p", "2023_24", [{**r, "b4q1_perv1": "01", "b6q5_perv1": "31", "b4q6_perv1": "35", "distcode_perv1": "01",
                                                                 "b5pt1q6_perv1": "241", "b5pt1q5_perv1": "64190", "b6q9_perv1": r["CWS_Earnings_Salaried"],
                                                                 "b6q10_perv1": "0", "b6q7_3pt1_perv1": "8", "mult_perv1": "200", "NSS_perv1": "4",
                                                                 "NSC_perv1": "8", "no_qtr_perv1": "4", "b6q4_3pt1_perv1": "31", "b6q5_3pt1_perv1": "64",
                                                                 "b6q9_3pt1_perv1": "0"} for r in old]))
    evidence = record_evidence(frame, deduplicate_periods([prior, frame]), PARAMS)
    salary = evidence[evidence.target_variable.eq("cws_earnings_salaried")]
    q5 = salary[salary.period_index.eq(5)]
    assert q5.same_season_status.eq("ASSESSABLE").all() and q5.same_season_period.eq("Jul–Sep 2023").all()
    assert q5.same_season_median.eq(np.median([9000 + i for i in range(40, 50)])).all()


def test_missing_required_column_fails_loudly(tmp_path: Path) -> None:
    rows = [{k: v for k, v in r.items() if k != "MoSPI_state"} for r in _rows("2024", "Q3", 5, 10000)]
    with pytest.raises(HistoricalFailure, match="MoSPI_state"):
        load_release(_write(tmp_path, "t", "2024", rows))


def test_legacy_iospi_columns_are_read_through_the_schema_boundary(tmp_path: Path) -> None:
    rows = [{(k.replace("MoSPI_", "iospi_") if k.startswith("MoSPI_") else k): v for k, v in r.items()} for r in _rows("2024", "Q3", 5, 10000)]
    frame, _ = load_release(_write(tmp_path, "t", "2024", rows))
    assert frame["state"].eq("07").all() and frame["ready"].all() and frame["period_index"].eq(3).all()
