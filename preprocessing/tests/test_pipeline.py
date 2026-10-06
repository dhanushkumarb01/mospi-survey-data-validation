from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from preprocessing.config import CONTRACTS, DatasetContract
from preprocessing.pipeline import PLFSPreprocessor, PreprocessingFailure, RunConfig


@pytest.fixture()
def synthetic_contract(monkeypatch: pytest.MonkeyPatch) -> DatasetContract:
    contract = DatasetContract(
        release="test", observation="first_visit", design_period="post_2025", cadence="monthly",
        household_path="household.csv", person_path="person.csv",
        household_fields={"quarter": "q", "month": "month", "visit": "visit", "sector": "sec", "state": "state", "district": "district", "stratum": "stratum", "fsu": "fsu", "sss": "sss", "household": "hh", "household_size": "hh_size", "response": "response", "survey_code": "survey", "substitution_reason": "sub", "weight": "weight"},
        person_fields={"quarter": "q", "month": "month", "visit": "visit", "sector": "sec", "state": "state", "district": "district", "stratum": "stratum", "fsu": "fsu", "sss": "sss", "household": "hh", "person": "person", "age": "age", "principal_industry": "industry", "training_field": "training", "day7_activity2": "activity2", "earnings_salaried": "earn_salary", "earnings_self_employed": "earn_self", "weight": "weight"},
        household_key=("quarter", "month", "sector", "state", "district", "fsu", "sss", "household"), person_serial="person",
        expected_household_columns=15, expected_person_columns=18,
        documented_code_values={"quarter": frozenset({"Q1"}), "month": frozenset({"1"}), "visit": frozenset({"V1"}), "sector": frozenset({"1", "2"}), "response": frozenset({"1", "2"}), "survey_code": frozenset({"1", "2"}), "substitution_reason": frozenset({"1", "2", "3", "9"})},
    )
    monkeypatch.setitem(CONTRACTS, "test_contract", contract)
    return contract


def _household(**updates: str) -> dict[str, str]:
    row = {"q": "Q1", "month": "1.0", "visit": "V1", "sec": "1", "state": "01", "district": "01", "stratum": "01", "fsu": "10001", "sss": "1", "hh": "01", "hh_size": "1", "response": "1", "survey": "1", "sub": "", "weight": "2.50"}
    row.update(updates)
    return row


def _person(**updates: str) -> dict[str, str]:
    row = {"q": "Q1", "month": "01", "visit": "V1", "sec": "1", "state": "01", "district": "01", "stratum": "01", "fsu": "10001", "sss": "1", "hh": "01", "person": "01", "age": "20", "industry": "", "training": "", "activity2": "", "earn_salary": "0", "earn_self": "0", "weight": "2.50"}
    row.update(updates)
    return row


def _run(tmp_path: Path, **kwargs: object) -> Path:
    return PLFSPreprocessor(RunConfig(tmp_path, tmp_path / "runs", "test_contract", run_id=str(kwargs.pop("run_id", "run")), **kwargs)).run()


def _report(path: Path) -> dict[str, object]:
    return json.loads((path / "preprocessing_report.json").read_text())


def test_valid_input_links_after_month_standardisation(tmp_path: Path, synthetic_contract: DatasetContract) -> None:
    pd.DataFrame([_household()]).to_csv(tmp_path / "household.csv", index=False)
    pd.DataFrame([_person()]).to_csv(tmp_path / "person.csv", index=False)
    destination = _run(tmp_path)
    persons = pd.read_parquet(destination / "prepared_persons.parquet")
    assert persons.loc[0, "MoSPI_household_link_status"] == "matched"
    assert persons.loc[0, "MoSPI_month"] == "1"
    assert persons.loc[0, "earn_salary"] == "0"
    assert _report(destination)["linkage"]["matched_persons"] == 1


def test_missing_required_column_stops_before_prepared_data(tmp_path: Path, synthetic_contract: DatasetContract) -> None:
    household = _household()
    household.pop("fsu")
    pd.DataFrame([household]).to_csv(tmp_path / "household.csv", index=False)
    pd.DataFrame([_person()]).to_csv(tmp_path / "person.csv", index=False)
    with pytest.raises(PreprocessingFailure):
        _run(tmp_path)
    report = _report(tmp_path / "runs" / "test_first_visit_run")
    assert report["overall_status"] == "failure"
    assert not (tmp_path / "runs" / "test_first_visit_run" / "prepared_households.parquet").exists()


def test_invalid_code_and_duplicate_key_are_reported_and_retained(tmp_path: Path, synthetic_contract: DatasetContract) -> None:
    pd.DataFrame([_household(response="8")]).to_csv(tmp_path / "household.csv", index=False)
    pd.DataFrame([_person(age="twenty"), _person(age="21")]).to_csv(tmp_path / "person.csv", index=False)
    destination = _run(tmp_path)
    issues = pd.read_csv(destination / "issue_log.csv")
    persons = pd.read_parquet(destination / "prepared_persons.parquet")
    assert "UNSUPPORTED_DOCUMENTED_CODE" in set(issues["issue_code"])
    assert "INVALID_NUMERIC_REPRESENTATION" in set(issues["issue_code"])
    assert "DUPLICATE_EXPECTED_KEY" in set(issues["issue_code"])
    assert len(persons) == 2
    assert set(persons["MoSPI_key_status"]) == {"not_assessable_key_integrity"}


def test_linkage_failure_is_visible_and_not_dropped(tmp_path: Path, synthetic_contract: DatasetContract) -> None:
    pd.DataFrame([_household(hh="01")]).to_csv(tmp_path / "household.csv", index=False)
    pd.DataFrame([_person(hh="02")]).to_csv(tmp_path / "person.csv", index=False)
    destination = _run(tmp_path)
    person = pd.read_parquet(destination / "prepared_persons.parquet")
    assert person.loc[0, "MoSPI_household_link_status"] == "unmatched_household"
    assert person.loc[0, "MoSPI_prepared_status"] == "unmatched_household"


def test_missing_and_zero_remain_distinct_and_run_metadata_is_reproducible(tmp_path: Path, synthetic_contract: DatasetContract) -> None:
    pd.DataFrame([_household()]).to_csv(tmp_path / "household.csv", index=False)
    pd.DataFrame([_person()]).to_csv(tmp_path / "person.csv", index=False)
    first = _run(tmp_path, run_id="one")
    second = _run(tmp_path, run_id="two")
    missing = pd.read_csv(first / "missingness_summary.csv")
    earnings = missing[missing["concept"] == "earnings_salaried"].iloc[0]
    assert earnings["blank_records"] == 0 and earnings["valid_zero_records"] == 1
    one = pd.read_parquet(first / "prepared_persons.parquet")
    two = pd.read_parquet(second / "prepared_persons.parquet")
    pd.testing.assert_frame_equal(one, two)
    assert json.loads((first / "run_metadata.json").read_text())["configuration_contract"] == "test_contract"


def test_release_and_visit_contracts_remain_separate() -> None:
    assert CONTRACTS["2023_24_revisit"].observation == "revisit"
    assert CONTRACTS["2023_24_revisit"].household_key[1] == "visit"
    assert CONTRACTS["2025_first"].design_period == "post_2025"
    assert "month" in CONTRACTS["2025_first"].household_key
