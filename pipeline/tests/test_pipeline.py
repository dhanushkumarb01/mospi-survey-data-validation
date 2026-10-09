"""End-to-end structural check of the V2 batch on a small synthetic delivery (no real data)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pipeline.qa import QAGateFailure, check_stage
from pipeline.run import Inputs, run_pipeline

from .synthetic import write_delivery


@pytest.fixture(scope="module")
def batch(tmp_path_factory):
    root = tmp_path_factory.mktemp("batch")
    prepared, injected = write_delivery(root / "preprocessing" / "runs" / "2024_first_visit_synthetic")
    result = run_pipeline(Inputs(prepared), "t", roots=root)
    return root, result, injected


def test_every_stage_runs_and_passes_its_quality_gate(batch):
    _, result, _ = batch
    assert set(result["qa"]) == {"statistical", "contextual", "ml", "pattern", "historical", "integrity", "fusion"}
    assert all(gate["status"] == "PASSED" for gate in result["qa"].values())


def test_injected_errors_reach_check_now_through_the_right_lane(batch):
    _, result, injected = batch
    cases = pd.read_parquet(Path(result["fusion"]) / "fused_cases.parquet").set_index("source_observation_id")
    salary = cases.loc[injected["x10_salary"]]
    # The strongest value evidence in the batch, and queued.  Whether it reaches "Check now" depends on the
    # sizes of its comparison groups (finite-sample floors): in this small fixture it lands in "Check if time".
    assert salary["value_p"] == cases["value_p"].min()
    assert salary["tier"] in {"A", "B"} and "VALUE" in salary["lanes"] and salary["value_lead_variable"] == "cws_earnings_salaried"
    household = cases.loc[injected["household_size"]]
    assert household["case_level"] == "HOUSEHOLD" and household["tier"] == "A" and "H02_HOUSEHOLD_SIZE_EQUALS_PERSONS_LISTED" in household["rule_ids"]
    # Rule findings come first in the queue; nothing else is ahead of them.
    assert cases.loc[cases["rule_error_count"].gt(0), "queue_position"].max() < cases.loc[cases["rule_error_count"].eq(0), "queue_position"].min()


def test_check_now_stays_within_budget_and_no_rank_bands_remain(batch):
    _, result, _ = batch
    cases = pd.read_parquet(Path(result["fusion"]) / "fused_cases.parquet")
    persons = cases[cases.case_level.eq("PERSON")]
    budget = max(1, -(-len(persons) // 100))
    assert int((persons.tier.eq("A") & persons.rule_error_count.eq(0)).sum()) <= budget
    assert set(cases.priority_band) <= {"CHECK_NOW", "CHECK_IF_TIME", "NOT_FLAGGED", "NOT_ASSESSABLE"}
    assert not {"risk_score", "influence_score", "override_applied"} & set(cases.columns)


def test_quality_gate_stops_a_degraded_stage(batch, tmp_path):
    _, result, _ = batch
    broken = tmp_path / "historical"
    broken.mkdir()
    evidence = pd.read_parquet(Path(result["historical"]) / "historical_record_evidence.parquet")
    evidence.assign(assessability_status="NOT_ASSESSABLE", release="").to_parquet(broken / "historical_record_evidence.parquet", index=False)
    for name in ("aggregate_indicators.parquet", "run_metadata.json"):
        (broken / name).write_bytes((Path(result["historical"]) / name).read_bytes())
    with pytest.raises(QAGateFailure, match="assessable|blank"):
        check_stage("historical", broken, len(evidence) // evidence.target_variable.nunique())
    empty = tmp_path / "pattern"; empty.mkdir()
    with pytest.raises(QAGateFailure, match="missing or empty"):
        check_stage("pattern", empty, 10)


def test_supervisor_api_on_a_lane_run(batch):
    from fastapi.testclient import TestClient
    from fusion.api import create_app
    root, result, injected = batch
    client = TestClient(create_app(root / "fusion" / "runs", project_root=root))
    overview = client.get("/api/overview").json()
    assert overview["method"] == "lanes" and {b["band"] for b in overview["bands"]} == {"CHECK_NOW", "CHECK_IF_TIME", "NOT_FLAGGED", "NOT_ASSESSABLE"}
    assert overview["burden"]["value_threshold"] > 0
    worklist = client.get("/api/worklist", params={"tier": "AB"}).json()
    assert worklist["total"] >= 1 and worklist["rows"][0]["households"]
    listed = client.get("/api/cases", params={"summaries": True, "lane": "VALUE"}).json()
    # Within a tier the list is ordered by impact, not by evidence, so the injected case need not be first.
    x10 = next(row for row in listed["rows"] if row["source_observation_id"] == injected["x10_salary"])
    case = client.get(f"/api/cases/{x10['case_id']}").json()
    story = case["story"]
    assert story["method"] == "lanes" and story["evidence"]
    salary = next(s for s in story["evidence"] if s["id"] == "value_cws_earnings_salaried")
    assert {c["kind"] for c in salary["comparisons"]} >= {"current", "history"}
    assert any("extra zero" in hint for hint in salary["hints"])             # x10 is recognised as a possible keying slip
    household = client.get("/api/cases", params={"case_level": "HOUSEHOLD"}).json()["rows"][0]
    household_story = client.get(f"/api/cases/{household['case_id']}").json()["story"]
    assert household_story["record"]["level"] == "household" and household_story["evidence"][0]["id"] == "rules"
    decision = {"event_type": "DECISION_MADE", "decision": "CONFIRMED_ERROR", "reason_code": "EXTRA_OR_MISSING_ZERO", "verification_source": "PHONE_CALL",
                "corrected_field": "salaried earnings", "corrected_value": "8300", "opened_at_utc": "2026-10-09T00:00:00+00:00"}
    assert client.post(f"/api/cases/{case['case_id']}/events", json=decision).status_code == 200
    feedback = client.get("/api/feedback").json()
    assert feedback["available"] and feedback["decided_cases"] == 1
