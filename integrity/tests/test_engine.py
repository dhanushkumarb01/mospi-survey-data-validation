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
