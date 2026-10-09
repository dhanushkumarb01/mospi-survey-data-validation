from __future__ import annotations

import pandas as pd
import pytest

from integrity.engine import IntegrityFailure, evaluate, load_rules

RULES = load_rules()


def _person(**values):
    base = {"source_observation_id": "k|person=01", "record_key": "k", "person_serial": "01", "age": "35", "cws_status": "31",
            "earnings_salaried": "15000", "earnings_self_employed": "0", "day7_hours": "8"}
    return {**base, **values}


def test_every_bundled_rule_cites_a_source_and_clean_records_pass():
    assert all(rule["source"] for rule in RULES["rules"])
    clean = pd.DataFrame([_person(), _person(source_observation_id="a|person=01", record_key="a", age="3", cws_status="99",
                                             earnings_salaried="0", day7_hours="0")])
    assert evaluate(clean, RULES).empty


@pytest.mark.parametrize("change, rule", [
    ({"cws_status": "91", "earnings_salaried": "5000", "day7_hours": "0"}, "R05_SALARIED_EARNINGS_ONLY_FOR_31_71_72"),
    ({"cws_status": "21", "earnings_salaried": "0", "earnings_self_employed": "300"}, "R07_HELPER_EARNINGS_ZERO"),
    ({"age": "3"}, "R03_STATUS_99_ONLY_UNDER_5"),
    ({"cws_status": "99", "earnings_salaried": "0", "day7_hours": "0"}, "R04_UNDER_5_ONLY_WITH_STATUS_99"),
    ({"day7_hours": "30"}, "R09_DAY7_HOURS_WITHIN_A_DAY"),
    ({"earnings_salaried": "-10"}, "R08_SALARIED_EARNINGS_NOT_NEGATIVE"),
    ({"cws_status": "45"}, "R01_CWS_STATUS_CODE"),
])
def test_each_documented_rule_detects_its_breach(change, rule):
    violations = evaluate(pd.DataFrame([_person(**change)]), RULES)
    assert rule in set(violations.rule_id)


def test_self_employed_negative_earnings_are_allowed():
    assert evaluate(pd.DataFrame([_person(cws_status="11", earnings_salaried="0", earnings_self_employed="-200")]), RULES).empty


def test_duplicates_and_missing_concepts():
    frame = pd.DataFrame([_person(), _person()])
    assert set(evaluate(frame, RULES).rule_id) == {"R11_UNIQUE_PERSON"}
    no_hours = pd.DataFrame([_person()]).drop(columns="day7_hours")       # e.g. revisit: hours not collected
    assert evaluate(no_hours, RULES).empty


def test_rules_must_cite_a_source(tmp_path):
    bad = tmp_path / "r.yaml"
    bad.write_text("rules:\n  - {id: X, type: range, field: age, min: 0, severity: error, message: m}\n", encoding="utf-8")
    with pytest.raises(IntegrityFailure):
        load_rules(bad)


def test_every_rule_has_metadata_and_passes_its_own_test_cases():
    from integrity.engine import run_rule_tests
    assert run_rule_tests(RULES) == []
    for rule in RULES["rules"]:
        assert rule["version"] and rule["owner"] and rule["approval_status"] in {"approved", "draft", "retired"}
    drafts = [r for r in RULES["rules"] if r["approval_status"] == "draft"]
    assert drafts and not any(r["active"] for r in drafts)          # soft proposals never reach supervisors unapproved


def test_rule_with_failing_test_case_is_refused(tmp_path):
    bad = tmp_path / "r.yaml"
    bad.write_text("rules:\n  - {id: X, version: 1, type: range, level: person, field: age, min: 0, max: 10, severity: error, message: m, source: s,"
                   " owner: o, approval_status: approved, tests: [{expect: violation, record: {age: '5'}}, {expect: pass, record: {age: '5'}}]}\n", encoding="utf-8")
    with pytest.raises(IntegrityFailure, match="test cases failed"):
        load_rules(bad)


def test_household_rules_run_on_a_prepared_delivery(tmp_path):
    import json
    from pathlib import Path
    from integrity.engine import RunConfig, run
    folder = tmp_path / "prep"; folder.mkdir()
    persons = [{"MoSPI_source_row": i + 2, "MoSPI_record_key": key, "Person_Serial_No": str(i), "Age": "40", "CWS_Status_Code": "31",
                "CWS_Earnings_Salaried": "1000", "CWS_Earnings_SelfEmployed": "0", "Day7_Total_Hours": "8", "Relationship_To_Head": rel,
                "Day7_Act1_Status_Code": "31", "Day7_Act1_Hours": "8", "Day7_Act2_Status_Code": "", "Day7_Act2_Hours": "", "Day7_Act1_Wage": "0",
                "MoSPI_household_link_status": "matched"}
               for i, (key, rel) in enumerate([("h1", "1"), ("h1", "2"), ("h2", "2"), ("h2", "5")])]
    households = [{"MoSPI_record_key": "h1", "MoSPI_state": "07", "MoSPI_quarter": "Q3", "Household_Size": "2", "Usual_Expenditure": "100",
                   "Imputed_Homegrown_Consumption": "0", "Imputed_Wages_Consumption": "0", "Annual_Clothing_Expenditure": "120",
                   "Annual_Durables_Expenditure": "0", "Monthly_Consumer_Expenditure": "110", "Survey_Date": "15022024", "District_Code": "01"},
                  {"MoSPI_record_key": "h2", "MoSPI_state": "07", "MoSPI_quarter": "Q3", "Household_Size": "3", "Usual_Expenditure": "100",
                   "Imputed_Homegrown_Consumption": "0", "Imputed_Wages_Consumption": "0", "Annual_Clothing_Expenditure": "120",
                   "Annual_Durables_Expenditure": "0", "Monthly_Consumer_Expenditure": "500", "Survey_Date": "15022024", "District_Code": "01"}]
    pd.DataFrame(persons).to_parquet(folder / "prepared_persons.parquet", index=False)
    pd.DataFrame(households).to_parquet(folder / "prepared_households.parquet", index=False)
    (folder / "run_metadata.json").write_text(json.dumps({"run_id": "p", "release": "2024", "observation": "first_visit", "design_period": "pre_2025"}), encoding="utf-8")
    out = run(RunConfig(folder / "prepared_persons.parquet", tmp_path / "runs", run_id="t"))
    found = pd.read_parquet(out / "integrity_violations.parquet")
    h2 = set(found.loc[found.source_observation_id.eq("h2|household"), "rule_id"])
    assert h2 == {"H01_ONE_HEAD_PER_HOUSEHOLD", "H02_HOUSEHOLD_SIZE_EQUALS_PERSONS_LISTED", "H03_MONTHLY_CONSUMER_EXPENDITURE_IDENTITY"}
    assert not found.source_observation_id.eq("h1|household").any()
    dry = json.loads((out / "rule_dry_run.json").read_text())
    assert {r["rule_id"]: r["applicable_to_release"] for r in dry["rules"]}["H04_MONTHLY_INCOME_TOTAL"] is False   # not collected pre-2025
