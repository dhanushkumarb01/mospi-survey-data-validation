from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from peer_groups.config import GroupingProfile, PeerGroupSpecification
from peer_groups.engine import PeerGroupEngine, PeerGroupFailure, RunConfig


def _first_visit_row(index: int, **updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "MoSPI_source_row": index + 2,
        "MoSPI_record_key": f"household-{index}",
        "MoSPI_release": "2024",
        "MoSPI_observation": "first_visit",
        "MoSPI_design_period": "pre_2025",
        "MoSPI_visit": "V1",
        "MoSPI_prepared_status": "ready_for_downstream_preparation_only",
        "MoSPI_state": "01",
        "MoSPI_sector": "1",
        "Person_Serial_No": "1",
        "CWS_Status_Code": "11",
        "General_Education_Level": "07",
        "Principal_Occupation_Code": "611",
        "Principal_Industry_Code": "01124",
        "CWS_Earnings_Salaried": "1000",
        "CWS_Earnings_SelfEmployed": "0",
        "Day7_Total_Hours": "8",
        "MoSPI_fsu": f"fsu-{index}",
        "MoSPI_weight": "9.5",
    }
    row.update(updates)
    return row


def _write_prepared(tmp_path: Path, rows: list[dict[str, object]], *, release: str = "2024", observation: str = "first_visit", design_period: str = "pre_2025") -> Path:
    directory = tmp_path / f"{release}_{observation}"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "prepared_persons.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    (directory / "run_metadata.json").write_text(json.dumps({"run_id": f"{release}-{observation}-source", "release": release, "observation": observation, "design_period": design_period}), encoding="utf-8")
    return path


def _run(tmp_path: Path, path: Path, *, minimum: int = 3, run_id: str = "peer") -> Path:
    return PeerGroupEngine(RunConfig(path, tmp_path / "peer_runs", run_id=run_id, minimum_group_size=minimum)).run()


def _assignments(destination: Path) -> pd.DataFrame:
    return pd.read_parquet(destination / "peer_group_assignments.parquet")


def test_valid_groups_are_target_specific_traceable_and_cross_fsu(tmp_path: Path) -> None:
    destination = _run(tmp_path, _write_prepared(tmp_path, [_first_visit_row(i) for i in range(3)]))
    assignments = _assignments(destination)
    references = pd.read_parquet(destination / "peer_group_references.parquet")
    assert set(assignments["assessability_status"]) == {"ASSESSABLE"}
    earnings = assignments[assignments["target_variable"] == "cws_earnings_salaried"]
    hours = assignments[assignments["target_variable"] == "day7_total_hours"]
    assert set(earnings["backoff_level"]) == {0}
    assert set(hours["backoff_level"]) == {0}
    assert '"occupation_major_group"' in earnings.iloc[0]["grouping_dimensions"]
    assert '"industry_division"' in hours.iloc[0]["grouping_dimensions"]
    assert "fsu" not in earnings.iloc[0]["grouping_dimensions"].lower()
    assert "weight" not in earnings.iloc[0]["grouping_dimensions"].lower()
    assert earnings["peer_group_id"].nunique() == 1
    assert earnings["peer_group_id"].iloc[0] in set(references["peer_group_id"])
    assert set(earnings["reference_run_id"]) == {"2024-first_visit-source"}


def test_small_cells_back_off_deterministically_and_no_group_is_explicit(tmp_path: Path) -> None:
    rows = [_first_visit_row(i, General_Education_Level=f"0{i + 4}", Principal_Occupation_Code=occupation) for i, occupation in enumerate(("111", "211", "611"))]
    first = _run(tmp_path, _write_prepared(tmp_path, rows), run_id="one")
    second = _run(tmp_path, _write_prepared(tmp_path, rows), run_id="two")
    a = _assignments(first)
    b = _assignments(second)
    a_salary = a[a.target_variable == "cws_earnings_salaried"]
    b_salary = b[b.target_variable == "cws_earnings_salaried"]
    assert set(a_salary.backoff_level) == {2}
    pd.testing.assert_series_equal(a_salary.peer_group_id.reset_index(drop=True), b_salary.peer_group_id.reset_index(drop=True))
    no_group = _run(tmp_path, _write_prepared(tmp_path / "other", rows), minimum=4, run_id="none")
    no_group_assignments = _assignments(no_group)
    assert set(no_group_assignments.assessability_status) == {"NOT_ASSESSABLE"}
    assert set(no_group_assignments[no_group_assignments.target_variable == "cws_earnings_salaried"].not_assessable_reason) == {"NO_CONFIGURED_GROUP_MEETS_MINIMUM"}
    no_group_references = pd.read_parquet(no_group / "peer_group_references.parquet")
    assert no_group_references.empty
    assert {"peer_group_id", "target_variable", "release", "visit", "month", "reference_run_id"}.issubset(no_group_references.columns)


def test_revisit_is_a_separate_context_limited_route_and_hours_are_unavailable(tmp_path: Path) -> None:
    rows = []
    for index in range(3):
        rows.append({
            "MoSPI_source_row": index + 2, "MoSPI_record_key": f"rv-{index}", "MoSPI_release": "2023_24",
            "MoSPI_observation": "revisit", "MoSPI_design_period": "pre_2025", "MoSPI_visit": "V2",
            "MoSPI_prepared_status": "ready_for_downstream_preparation_only", "MoSPI_state": "01", "MoSPI_sector": "2",
            "b4q1_pervv": "1", "b6q5_perrv": "11", "b6q9_perrv": "100", "b6q10_perrv": "0",
        })
    destination = _run(tmp_path, _write_prepared(tmp_path, rows, release="2023_24", observation="revisit"))
    assignments = _assignments(destination)
    earnings = assignments[assignments.target_variable == "cws_earnings_salaried"]
    hours = assignments[assignments.target_variable == "day7_total_hours"]
    assert set(earnings.grouping_profile) == {"earnings_revisit_context_limited"}
    assert set(earnings.assessability_status) == {"ASSESSABLE"}
    assert set(hours.not_assessable_reason) == {"TARGET_UNAVAILABLE_FOR_RELEASE_OBSERVATION"}


def test_post_2025_month_is_a_mandatory_boundary(tmp_path: Path) -> None:
    rows: list[dict[str, object]] = []
    for month in ("1", "2"):
        for index in range(3):
            rows.append({
                "MoSPI_source_row": len(rows) + 2, "MoSPI_record_key": f"m{month}-{index}", "MoSPI_release": "2025",
                "MoSPI_observation": "first_visit", "MoSPI_design_period": "post_2025", "MoSPI_visit": "V1", "MoSPI_month": month,
                "MoSPI_prepared_status": "ready_for_downstream_preparation_only", "MoSPI_state": "01", "MoSPI_sector": "1",
                "srl": "1", "acws": "11", "gedu_lvl": "07", "ocu_pas": "611", "ind_pas": "01124",
                "ern_reg": "100", "ern_self": "0", "hr7": "8",
            })
    destination = _run(tmp_path, _write_prepared(tmp_path, rows, release="2025", design_period="post_2025"))
    assignment = _assignments(destination)
    salary = assignment[assignment.target_variable == "cws_earnings_salaried"]
    assert salary.groupby("month").peer_group_id.nunique().eq(1).all()
    assert salary.groupby("month").peer_group_id.first().nunique() == 2


def test_mixed_release_is_rejected_and_prohibited_dimensions_are_rejected(tmp_path: Path) -> None:
    mixed = [_first_visit_row(0), _first_visit_row(1, MoSPI_release="2023_24"), _first_visit_row(2)]
    with pytest.raises(PeerGroupFailure, match="mixed MoSPI_release"):
        _run(tmp_path, _write_prepared(tmp_path, mixed))
    invalid = PeerGroupSpecification("test", "test", (GroupingProfile("bad", "first_visit", (("state", "weight"),)),))
    with pytest.raises(ValueError, match="FSU and survey weight"):
        PeerGroupEngine(RunConfig(Path("unused"), tmp_path / "x", specifications=(invalid,)))
