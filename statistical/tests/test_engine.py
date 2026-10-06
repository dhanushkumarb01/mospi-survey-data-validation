from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from peer_groups.engine import PeerGroupEngine, RunConfig as PeerRunConfig
from statistical.config import StatisticalParameters
from statistical.engine import RunConfig, StatisticalEngine


def _write(path: Path, rows: list[dict[str, object]], metadata: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    (path.parent / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return path


def _first_2024(index: int, value: object = "0", status: str = "31") -> dict[str, object]:
    return {
        "MoSPI_source_row": index + 2, "MoSPI_record_key": f"h-{index}", "MoSPI_release": "2024", "MoSPI_observation": "first_visit",
        "MoSPI_design_period": "pre_2025", "MoSPI_visit": "V1", "MoSPI_prepared_status": "ready_for_downstream_preparation_only",
        "MoSPI_state": "01", "MoSPI_sector": "1", "Person_Serial_No": "1", "CWS_Status_Code": status, "General_Education_Level": "07",
        "Principal_Occupation_Code": "611", "Principal_Industry_Code": "01124", "CWS_Earnings_Salaried": value,
        "CWS_Earnings_SelfEmployed": value, "Day7_Total_Hours": value,
    }


def _peer(path: Path, output_root: Path, run_id: str) -> Path:
    return PeerGroupEngine(PeerRunConfig(path, output_root, run_id=run_id, minimum_group_size=3)).run()


def _statistical(path: Path, peer: Path, output_root: Path, run_id: str, **kwargs: object) -> Path:
    parameters = kwargs.pop("parameters", StatisticalParameters(minimum_revisit_change_group_size=3))
    return StatisticalEngine(RunConfig(path, peer, output_root, run_id=run_id, parameters=parameters, **kwargs)).run()


def test_midrank_quantiles_and_mad_are_deterministic(tmp_path: Path) -> None:
    prepared = _write(tmp_path / "p" / "prepared_persons.parquet", [_first_2024(i, value) for i, value in enumerate(("0", "1", "2", "100"))], {"run_id": "prepared", "release": "2024", "observation": "first_visit", "design_period": "pre_2025"})
    peer = _peer(prepared, tmp_path / "peer", "peer")
    first = _statistical(prepared, peer, tmp_path / "stat", "one")
    second = _statistical(prepared, peer, tmp_path / "stat", "two")
    a = pd.read_parquet(first / "statistical_evidence.parquet")
    b = pd.read_parquet(second / "statistical_evidence.parquet")
    salary = a[a.target_variable.eq("cws_earnings_salaried")].sort_values("observed_value")
    assert salary.percentile_position.tolist() == [0.125, 0.375, 0.625, 0.875]
    assert salary.iloc[-1].distribution_position == "UPPER_TAIL"
    assert salary.iloc[-1].peer_median == 1.5
    assert np.isclose(salary.iloc[-1].mad, 1.0)
    cols = ["source_observation_id", "percentile_position", "peer_median", "mad", "robust_deviation", "distribution_position"]
    pd.testing.assert_frame_equal(a[cols], b[cols])


def test_zero_mad_missing_values_and_peer_non_assessability_are_explicit(tmp_path: Path) -> None:
    rows = [_first_2024(i, value) for i, value in enumerate(("0", "0", "0", "99"))]
    rows.append(_first_2024(4, ""))
    prepared = _write(tmp_path / "p" / "prepared_persons.parquet", rows, {"run_id": "prepared", "release": "2024", "observation": "first_visit", "design_period": "pre_2025"})
    peer = _peer(prepared, tmp_path / "peer", "peer")
    result = _statistical(prepared, peer, tmp_path / "stat", "run")
    evidence = pd.read_parquet(result / "statistical_evidence.parquet")
    salary = evidence[evidence.target_variable.eq("cws_earnings_salaried")]
    extreme = salary[salary.observed_value.eq(99)].iloc[0]
    assert extreme.mad == 0
    assert pd.isna(extreme.robust_deviation)
    assert extreme.robust_deviation_status == "ZERO_MAD_DEVIATION_NOT_NUMERIC"
    zero = salary[salary.observed_value.eq(0)].iloc[0]
    assert zero.robust_deviation == 0
    missing = salary[salary.observed_value_raw.fillna("").eq("")].iloc[0]
    assert missing.statistical_assessability_status == "NOT_ASSESSABLE"
    assert "TARGET_VALUE_MISSING" in missing.statistical_assessability_reason


def _first_2023(index: int, value: int) -> dict[str, object]:
    return {
        "MoSPI_source_row": index + 2, "MoSPI_record_key": f"Q1|V1|2|01|01|100{index}|1|1|01", "MoSPI_release": "2023_24", "MoSPI_observation": "first_visit", "MoSPI_design_period": "pre_2025", "MoSPI_visit": "V1", "MoSPI_prepared_status": "ready_for_downstream_preparation_only", "MoSPI_state": "01", "MoSPI_sector": "2",
        "b4q1_perv1": "01", "b6q5_perv1": "31", "b4q8_perv1": "07", "b5pt1q6_perv1": "611", "b5pt1q5_perv1": "01124", "b6q9_perv1": str(value), "b6q10_perv1": str(-value), "b6q7_3pt1_perv1": "8",
        "distcode_perv1": "01", "b1q1_perv1": f"100{index}", "b1q13_perv1": "1", "b1q14_perv1": "1", "b1q15_perv1": "01",
    }


def _revisit_2023(index: int, value: int) -> dict[str, object]:
    return {
        "MoSPI_source_row": index + 2, "MoSPI_record_key": f"Q2|V2|2|01|01|100{index}|1|1|01", "MoSPI_release": "2023_24", "MoSPI_observation": "revisit", "MoSPI_design_period": "pre_2025", "MoSPI_visit": "V2", "MoSPI_prepared_status": "ready_for_downstream_preparation_only", "MoSPI_state": "01", "MoSPI_sector": "2",
        "b4q1_pervv": "01", "b6q5_perrv": "31", "b6q9_perrv": str(value), "b6q10_perrv": str(-value),
        "dist_code_perrv": "01", "b1q1_perrv": f"100{index}", "b1q13_perrv": "1", "b1q14_perrv": "1", "b1q15_perrv": "01",
    }


def test_revisit_uses_only_linked_pairs_and_never_fabricates_hours(tmp_path: Path) -> None:
    first = _write(tmp_path / "first" / "prepared_persons.parquet", [_first_2023(i, value) for i, value in enumerate((100, 200, 300))], {"run_id": "first", "release": "2023_24", "observation": "first_visit", "design_period": "pre_2025"})
    revisit = _write(tmp_path / "revisit" / "prepared_persons.parquet", [_revisit_2023(i, value) for i, value in enumerate((110, 202, 400))] + [_revisit_2023(9, 999)], {"run_id": "revisit", "release": "2023_24", "observation": "revisit", "design_period": "pre_2025"})
    first_peer = _peer(first, tmp_path / "peer", "first-peer")
    revisit_peer = _peer(revisit, tmp_path / "peer", "revisit-peer")
    run = _statistical(first, first_peer, tmp_path / "stat", "with-revisit", revisit_prepared_person_path=revisit, revisit_peer_group_run_path=revisit_peer)
    changes = pd.read_parquet(run / "revisit_statistical_evidence.parquet")
    salary = changes[changes.target_variable.eq("cws_earnings_salaried")]
    assert salary.revisit_comparison_status.eq("ASSESSABLE").sum() == 3
    assert salary.revisit_assessability_reason.eq("NO_VALID_LINKED_FIRST_VISIT").sum() == 1
    hours = changes[changes.target_variable.eq("day7_total_hours")]
    assert set(hours.revisit_assessability_reason) == {"REVISIT_TARGET_UNAVAILABLE_FOR_RELEASE_OBSERVATION"}


def test_revisit_change_group_below_minimum_is_not_assessable(tmp_path: Path) -> None:
    """The final V1 revisit correction must never leave a pending status."""
    first = _write(tmp_path / "first" / "prepared_persons.parquet", [_first_2023(i, value) for i, value in enumerate((100, 200, 300))], {"run_id": "first", "release": "2023_24", "observation": "first_visit", "design_period": "pre_2025"})
    revisit = _write(tmp_path / "revisit" / "prepared_persons.parquet", [_revisit_2023(i, value) for i, value in enumerate((110, 202, 400))], {"run_id": "revisit", "release": "2023_24", "observation": "revisit", "design_period": "pre_2025"})
    first_peer = _peer(first, tmp_path / "peer", "first-peer")
    revisit_peer = _peer(revisit, tmp_path / "peer", "revisit-peer")
    run = _statistical(
        first, first_peer, tmp_path / "stat", "below-minimum",
        revisit_prepared_person_path=revisit, revisit_peer_group_run_path=revisit_peer,
        parameters=StatisticalParameters(minimum_revisit_change_group_size=4),
    )
    changes = pd.read_parquet(run / "revisit_statistical_evidence.parquet")
    earnings = changes[changes.target_variable.eq("cws_earnings_salaried")]
    assert earnings.revisit_comparison_status.eq("NOT_ASSESSABLE").all()
    assert earnings.revisit_assessability_reason.eq("REVISIT_CHANGE_REFERENCE_GROUP_BELOW_MINIMUM").all()
    # Status 31 at both visits: self-employment earnings are a placeholder, never a "change".
    self_employed = changes[changes.target_variable.eq("cws_earnings_self_employed") & changes.first_source_observation_id.notna()]
    assert self_employed.revisit_assessability_reason.eq("TARGET_NOT_APPLICABLE_AT_ONE_OR_BOTH_VISITS").all()
    assert "PENDING_CHANGE_REFERENCE" not in set(changes.revisit_comparison_status)


def test_non_applicable_placeholder_zeros_are_never_assessed(tmp_path: Path) -> None:
    """Audit C1/H5/M4: a 0 stored because the item does not apply is not evidence (Vol. I §3.6.17-3.6.18)."""
    rows = [_first_2024(i, value, "31") for i, value in enumerate(("10", "20", "30", "40"))]
    rows += [_first_2024(10 + i, "0", "91") for i in range(4)]            # students: earnings item not asked
    rows += [_first_2024(20 + i, "0", "21") for i in range(4)]            # helpers: self-employment earnings 0 by definition
    prepared = _write(tmp_path / "p" / "prepared_persons.parquet", rows, {"run_id": "prepared", "release": "2024", "observation": "first_visit", "design_period": "pre_2025"})
    result = _statistical(prepared, _peer(prepared, tmp_path / "peer", "peer"), tmp_path / "stat", "run")
    evidence = pd.read_parquet(result / "statistical_evidence.parquet")
    salaried = evidence[evidence.target_variable.eq("cws_earnings_salaried")]
    students = salaried[salaried.source_observation_id.str.match(r"h-1d")]
    assert students.statistical_assessability_status.eq("NOT_ASSESSABLE").all()
    assert students.statistical_assessability_reason.eq("TARGET_NOT_APPLICABLE_FOR_CWS_STATUS").all()
    assert salaried[salaried.target_applicability.eq("APPLICABLE")].statistical_assessability_status.eq("ASSESSABLE").all()
    helpers = evidence[evidence.target_variable.eq("cws_earnings_self_employed") & evidence.source_observation_id.str.match(r"h-2d")]
    assert helpers.statistical_assessability_reason.eq("TARGET_ZERO_BY_DEFINITION_FOR_CWS_STATUS").all()
    hours = evidence[evidence.target_variable.eq("day7_total_hours")]
    assert hours[hours.source_observation_id.str.match(r"h-1d")].statistical_assessability_status.eq("NOT_ASSESSABLE").all()
    assert hours[hours.source_observation_id.str.match(r"h-2d")].statistical_assessability_status.eq("ASSESSABLE").all()
