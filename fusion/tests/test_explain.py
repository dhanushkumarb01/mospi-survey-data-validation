import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from fusion.api import create_app
from fusion.explain import SourceResolver, build_story, share_text, strength
from fusion.labels import format_value


RELEASE, OBSERVATION = "2024", "first_visit"
JARGON = ("isolation forest", "lof", "surprisal", "calibrated rank", "conditional expectation", "percentile position",
          "evidence fusion", "risk score", "influence score", "independent")


def _meta(path, run_id, **extra):
    path.mkdir(parents=True, exist_ok=True)
    (path / "run_metadata.json").write_text(json.dumps({"run_id": run_id, "release": RELEASE, "observation": OBSERVATION, **extra}), encoding="utf-8")


@pytest.fixture()
def project(tmp_path):
    a, b = "Q3|1|07|07|11111|1|1|01|person=01", "Q3|2|09|02|22222|1|1|04|person=02"
    provenance = {"preprocessing_run_id": "prep", "statistical_run_id": "stat", "contextual_run_id": "ctx", "ml_run_id": "ml",
                  "pattern_run_id": "pat", "fusion_version": "v", "calibration_version": "c", "influence_version": "i"}
    common = dict(release=RELEASE, observation_type=OBSERVATION, design_period="pre_2025", visit="V1", month="",
                  provenance_json=json.dumps(provenance), evidence_card_json="", statistical_details_json="[]",
                  contextual_details_json="[]", ml_details_json="[]", pattern_details_json="[]", override_applied=False,
                  statistical_statement="s", contextual_statement="c", statistical_reason=None, contextual_reason=None,
                  ml_reason=None, pattern_reason=None, available_evidence_count=3)
    fused = pd.DataFrame([
        dict(common, case_id="case_a", source_observation_id=a, state="07", sector="1", stratum="01", fsu="11111", design_weight="300",
             target_variable="cws_earnings_salaried", percentile_position=.999, peer_group_size=40, statistical_status="ASSESSABLE",
             contextual_status="NOT_ASSESSABLE", ml_status="ASSESSABLE", pattern_status="ASSESSABLE", statistical_rank=.999,
             contextual_rank=None, ml_rank=.97, pattern_rank=.9, risk_score=.99, influence_score=.9, raw_influence=5.0,
             priority_score=.891, priority_rank=1.0, priority_band="CRITICAL", max_peer_median_deviation=90000.0,
             ml_statement="Unusual multivariate response pattern.", pattern_statement="FSU 11111 shows a higher concentration of reported age values on terminal digit 5 than the comparable reference population."),
        dict(common, case_id="case_b", source_observation_id=b, state="09", sector="2", stratum="02", fsu="22222", design_weight="100",
             target_variable=None, percentile_position=None, peer_group_size=None, statistical_status="NOT_ASSESSABLE",
             contextual_status="NOT_ASSESSABLE", ml_status="ASSESSABLE", pattern_status="NOT_AVAILABLE", statistical_rank=None,
             contextual_rank=None, ml_rank=.4, pattern_rank=None, risk_score=.4, influence_score=None, raw_influence=None,
             priority_score=None, priority_rank=None, priority_band="NOT_ASSESSABLE", max_peer_median_deviation=None,
             ml_statement="Unusual multivariate response pattern.", pattern_statement="No compatible Pattern run was supplied for this fusion run."),
    ])
    run = tmp_path / "fusion" / "runs" / "2024_first_visit_t"
    _meta(run, "t", design_period="pre_2025", input_preprocessing_run_id="prep", parameters={},
          source_runs={"statistical": "stat", "contextual": "ctx", "ml": "ml", "pattern": "pat"})
    fused.to_parquet(run / "fused_cases.parquet", index=False)
    (run / "fusion_report.json").write_text(json.dumps({"records_processed": 2, "priority_rows": 1, "group_priority_rows": 1,
                                                        "source_availability": {}, "assessable_records": 2}), encoding="utf-8")
    pd.DataFrame([dict(release=RELEASE, observation_type=OBSERVATION, design_period="pre_2025", visit="V1", month="", state="07", sector="1",
                       stratum="01", fsu="11111", records=12, assessable_records=12, max_pattern_rank=.9, max_risk_score=.99,
                       max_priority_score=.891, mean_influence_score=.5, group_priority_score=.45, group_priority_rank=1.0,
                       group_priority_band="MEDIUM")]).to_parquet(run / "group_priorities.parquet", index=False)

    prep = tmp_path / "preprocessing" / "runs" / "2024_first_visit_prep"
    _meta(prep, "prep")
    pd.DataFrame([{"MoSPI_record_key": a.split("|person=")[0], "Person_Serial_No": "01", "Age": "45", "Sex": "2", "Relationship_To_Head": "1",
                   "Marital_Status": "2", "General_Education_Level": "12", "CWS_Status_Code": "31", "Principal_Occupation_Code": "241",
                   "Principal_Industry_Code": "64190", "District_Code": "07"}]).to_parquet(prep / "prepared_persons.parquet", index=False)

    stat = tmp_path / "statistical" / "runs" / "2024_first_visit_stat"
    _meta(stat, "stat")
    pd.DataFrame([
        {"source_observation_id": a, "target_variable": "cws_earnings_salaried", "assessability_status": "ASSESSABLE", "observed_value": 120000.0,
         "peer_median": 30000.0, "quantile_0_05": 10000.0, "quantile_0_25": 20000.0, "quantile_0_75": 40000.0, "quantile_0_95": 60000.0,
         "percentile_position": .999, "peer_group_size": 40, "distribution_position": "UPPER_TAIL", "absolute_distance_from_median": 90000.0,
         "grouping_values": '{"state":"07","sector":"1","cws_status":"31"}', "grouping_dimensions": '["state","sector","cws_status"]',
         "grouping_profile": "earnings_first_visit", "backoff_level": 2, "minimum_group_size": 30},
        {"source_observation_id": a, "target_variable": "day7_total_hours", "assessability_status": "ASSESSABLE", "observed_value": 8.0,
         "peer_median": 8.0, "quantile_0_05": 0.0, "quantile_0_25": 6.0, "quantile_0_75": 9.0, "quantile_0_95": 12.0,
         "percentile_position": .5, "peer_group_size": 50, "distribution_position": "CENTRAL_REFERENCE_RANGE", "absolute_distance_from_median": 0.0,
         "grouping_values": '{"state":"07","sector":"1","cws_status":"31"}', "grouping_dimensions": '["state","sector","cws_status"]',
         "grouping_profile": "hours_first_visit", "backoff_level": 1, "minimum_group_size": 30},
    ]).to_parquet(stat / "statistical_evidence.parquet", index=False)

    ctx = tmp_path / "contextual" / "runs" / "2024_first_visit_ctx"
    _meta(ctx, "ctx")
    pd.DataFrame([{"source_observation_id": a, "observed_value": "", "reference_count": 40.0, "category_count": None,
                   "context_values": "{}"}]).to_parquet(ctx / "contextual_evidence.parquet", index=False)

    ml = tmp_path / "ml" / "runs" / "2024_first_visit_ml"
    _meta(ml, "ml")
    pd.DataFrame([{"source_observation_id": a, "assessability_status": "ASSESSABLE", "evidence_rank": .97, "raw_model_score": .4,
                   "effective_feature_columns": "age_band_5_year,sex"}]).to_parquet(ml / "isolation_forest_evidence.parquet", index=False)
    pd.DataFrame([{"source_observation_id": a, "assessability_status": "NOT_ASSESSABLE", "evidence_rank": None}]).to_parquet(ml / "lof_evidence.parquet", index=False)
    pd.DataFrame([{"source_observation_id": a, "assessability_status": "ASSESSABLE", "target": "cws_earnings_salaried", "observed_value": 120000,
                   "predicted_value": 28000.0, "evidence_rank": .99}]).to_parquet(ml / "conditional_model_evidence.parquet", index=False)
    pd.DataFrame([{"source_observation_id": a, "assessability_status": "ASSESSABLE", "match_count": 0,
                   "signature_present_field_count": 9}]).to_parquet(ml / "similarity_evidence.parquet", index=False)

    pat = tmp_path / "pattern" / "runs" / "2024_first_visit_pat"
    _meta(pat, "pat")
    pd.DataFrame([{"pattern_component": "digit_heaping", "variable": "age", "release": RELEASE, "observation_type": OBSERVATION,
                   "design_period": "pre_2025", "visit": "V1", "month": "", "state": "07", "sector": "1", "stratum": "01", "fsu": "11111",
                   "n": 12, "reference_n": 400, "evidence_rank": .95, "assessability_status": "ASSESSABLE", "p_value": .0004, "q_value": .004,
                   "evidence_statement": "FSU 11111: 50% of reported age values end in 0 or 5, compared with 20% in comparable FSUs.",
                   "details_json": json.dumps({"fsu_share_ending_0_or_5": .5, "reference_share_ending_0_or_5": .2, "count_ending_0_or_5": 6})}]
                 ).to_parquet(pat / "pattern_evidence.parquet", index=False)
    return tmp_path


def _case(project, case_id):
    return json.loads(pd.read_parquet(project / "fusion" / "runs" / "2024_first_visit_t" / "fused_cases.parquet").query("case_id == @case_id").to_json(orient="records"))[0]


def test_story_uses_only_stored_values_and_never_claims_error(project):
    story = build_story(_case(project, "case_a"), SourceResolver(project), priority_position=1, priority_total=1, weight_share=.75)
    text = json.dumps(story, ensure_ascii=False)
    assert "₹1,20,000" in text and "₹30,000" in text and "₹20,000 to ₹40,000" in text  # stored observed, median and quartiles
    assert "about ₹28,000" in text  # stored model expectation, not recomputed
    assert "Delhi" in text and "Female" in text and "Graduate" in text  # documented code labels
    assert "not found the record to be incorrect" in story["caveat"]
    assert "above the range covering 9 in 10 comparable records" in story["headline"]   # audit M10: no "far above" for any top-5% value
    assert "far above" not in story["headline"]
    assert any("did not have at least 30 records" in (e.get("comparison_note") or "") for e in story["evidence"])
    lowered = text.lower()
    for word in JARGON:
        assert word not in lowered.replace("independently", ""), word


def test_unavailable_evidence_is_explicit_not_negative(project):
    story = build_story(_case(project, "case_a"), SourceResolver(project))
    contextual = next(u for u in story["unavailable"] if u["source"] == "contextual")
    assert "No occupation code is recorded" in contextual["text"]
    other = build_story(_case(project, "case_b"), SourceResolver(project))
    sources = {u["source"]: u["text"] for u in other["unavailable"]}
    assert "Not enough comparable information" in sources["statistical"]
    assert "No compatible FSU pattern run" in sources["pattern"]
    assert "could not be calculated" in other["importance"]["summary"]


def test_group_evidence_is_labelled_as_group_level_with_neutral_wording(project):
    story = build_story(_case(project, "case_a"), SourceResolver(project))
    group = next(e for e in story["evidence"] if e["level"] == "group")
    assert "not evidence that this person's answers are wrong" in group["meaning"]
    item = group["items"][0]
    assert "ending in 0 or 5" in item["title"] and "50%" in item["text"] and "20%" in item["text"]
    assert item["notable"] and item["strength"]["label"] == "Notable difference"     # wording from the stored q-value
    assert all(c["level"] == "group" for c in story["checks"] if "FSU as a whole" in c["text"])


def test_display_helpers_never_overstate():
    assert share_text(.99999) == "99.9%"
    assert strength(.995)["label"] == "Very unusual" and strength(.5)["label"] == "Not notably unusual"
    assert format_value(1234567, "rupees") == "₹12,34,567" and format_value(-500, "rupees") == "₹−500"


def test_supervisor_api_flow(project):
    client = TestClient(create_app(project / "fusion" / "runs"))
    overview = client.get("/api/overview").json()
    assert overview["priority_rows"] == 1 and overview["review"]["decided"] == 0
    listed = client.get("/api/cases", params={"summaries": True}).json()
    assert listed["rows"][0]["position"] == 1 and "above the usual range" in listed["rows"][0]["unusual"]
    comparison = listed["rows"][0]["comparison"]          # stored quantiles, unchanged, for the list's range drawing
    assert comparison["position"] == "UPPER_TAIL" and comparison["low"] <= comparison["typical"] <= comparison["high"] < comparison["observed"]
    assert client.get("/api/queue/position", params={"position": 2}).json()["case_id"] == "case_b"
    detail = client.get("/api/cases/case_a").json()
    assert detail["story"]["importance"]["position"] == 1 and detail["review_status"] == "UNREVIEWED"
    saved = client.post("/api/cases/case_a/events", json={"event_type": "DECISION_MADE", "decision": "CONFIRMED_VALID", "actor": "A. Reviewer", "comment": "Checked schedule"})
    assert saved.status_code == 200
    assert client.get("/api/cases", params={"review_status": "UNREVIEWED"}).json()["total"] == 1
    assert client.get("/api/queue/position", params={"position": 1, "review_status": "UNREVIEWED"}).json()["case_id"] == "case_b"
    reviews = client.get("/api/reviews").json()["rows"]
    assert reviews[0]["decision_label"] == "Confirmed valid" and reviews[0]["actor"] == "A. Reviewer"
    assert client.get("/api/overview").json()["review"]["decisions"]["CONFIRMED_VALID"] == 1
    groups = client.get("/api/groups").json()
    assert groups["rows"][0]["fsu"] == "11111" and groups["rows"][0]["patterns"]
    assert client.get("/api/groups/11111").json()["patterns"][0]["component"] == "digit_heaping"
    assert client.post("/api/cases/case_a/events", json={"event_type": "DECISION_MADE", "decision": "WRONG"}).status_code == 422


def test_model_estimate_is_never_called_typical(project):
    """Audit C1: the model estimate is a model estimate, with a ratio, not 'the typical value'."""
    story = build_story(_case(project, "case_a"), SourceResolver(project))
    section = next(e for e in story["evidence"] if e["id"] == "ml_conditional")
    assert "model estimate" in section["title"].lower() and "typical" not in section["title"].lower()
    assert "about ₹28,000" in section["comparison"] and "not the typical value" in section["matters"]
    assert any("times the model estimate" in f["value"] for f in section["facts"])          # 1,20,000 / 28,000 ≈ 4.3


def test_fsu_sentence_needs_a_notable_check(project):
    """Audit M9: the FSU sentence appeared on ~89% of cases. It now needs a q < 0.05 check."""
    pattern = project / "pattern" / "runs" / "2024_first_visit_pat" / "pattern_evidence.parquet"
    frame = pd.read_parquet(pattern)
    frame["q_value"] = 0.4
    frame.to_parquet(pattern, index=False)
    story = build_story(_case(project, "case_a"), SourceResolver(project))
    assert not any(r["level"] == "group" for r in story["reasons"])
    assert "FSU" not in story["headline"]


def test_export_streams_every_row_not_first_10000(project):
    """Audit M13: export silently stopped at 10,000 rows."""
    client = TestClient(create_app(project / "fusion" / "runs"))
    text = client.get("/api/export/queue").text.strip().splitlines()
    assert text[0].startswith("position,") and len(text) == 1 + 2


def test_authentication_roles_and_audit_identity(project, tmp_path):
    import hashlib
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": [
        {"name": "S. Supervisor", "role": "supervisor", "token_sha256": hashlib.sha256(b"sup-token").hexdigest()},
        {"name": "T. Analyst", "role": "technical", "token_sha256": hashlib.sha256(b"tech-token").hexdigest()}]}), encoding="utf-8")
    client = TestClient(create_app(project / "fusion" / "runs", users_file=users))
    assert client.get("/api/overview").status_code == 401
    assert client.get("/api/session/required").json() == {"authentication": True}
    sup = {"Authorization": "Bearer sup-token"}
    saved = client.post("/api/cases/case_a/events", headers=sup, json={"event_type": "DECISION_MADE", "decision": "CONFIRMED_VALID", "actor": "someone else"})
    assert saved.status_code == 200 and saved.json()["actor"] == "S. Supervisor"      # typed names cannot impersonate
    tech = client.post("/api/cases/case_a/events", headers={"Authorization": "Bearer tech-token"}, json={"event_type": "DECISION_MADE", "decision": "CONFIRMED_VALID"})
    assert tech.status_code == 403
    assert client.get("/api/overview", headers=sup).headers["x-frame-options"] == "DENY"


def test_online_record_validation_reports_documented_rule_breaches(project):
    client = TestClient(create_app(project / "fusion" / "runs"))
    result = client.post("/api/validate/record", json={"record": {"cws_status": "91", "age": "20", "earnings_salaried": "5000",
                                                                  "earnings_self_employed": "0", "day7_hours": "0"}}).json()
    assert "R05_SALARIED_EARNINGS_ONLY_FOR_31_71_72" in {v["rule_id"] for v in result["rule_violations"]}
    assert "not stored" in result["note"]


def test_overview_reasons_and_drill_down_filters_come_from_stored_ranks(project):
    client = TestClient(create_app(project / "fusion" / "runs"))
    reasons = client.get("/api/overview").json()["highest_reasons"]
    # case_a is the only highest-priority record: statistical .999 and ML .97 are at/above the display threshold.
    assert reasons["statistical"] == 1 and reasons["ml"] == 1 and reasons["contextual"] == 0 and reasons["combined_only"] == 0
    assert client.get("/api/cases", params={"strong_source": "statistical"}).json()["total"] == 1
    assert client.get("/api/cases", params={"strong_source": "contextual"}).json()["total"] == 0
    assert client.get("/api/cases", params={"strong_source": "not-a-source"}).json()["total"] == 2      # unknown values are ignored
    assert client.get("/api/groups", params={"band": "ALERTS"}).json()["total"] == 1


def test_case_story_gives_short_checks_and_plain_importance(project):
    story = TestClient(create_app(project / "fusion" / "runs")).get("/api/cases/case_a").json()["story"]
    first = story["checks"][0]
    assert first["text"] == "Confirm that ₹1,20,000 was entered correctly." and "schedule" in first["detail"]
    assert story["importance"]["levels"] == {"unusualness": "Very high", "influence": "Moderate"}
    assert "unusually different" in story["importance"]["plain"]


def test_health_reports_readiness_without_authentication_or_paths(project, tmp_path):
    import hashlib
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": [{"name": "S", "role": "supervisor", "token_sha256": hashlib.sha256(b"t").hexdigest()}]}), encoding="utf-8")
    client = TestClient(create_app(project / "fusion" / "runs", users_file=users))
    response = client.get("/healthz")
    assert response.status_code in (200, 503)            # fixture source runs are partial; the endpoint must still answer
    body = response.json()
    assert body["runs"] == 1 and "audit_store_writable" in body and str(tmp_path) not in response.text
    assert client.get("/api/overview").status_code == 401   # health is the only unauthenticated data-free route


def test_health_is_unavailable_without_runs(tmp_path):
    response = TestClient(create_app(tmp_path / "fusion" / "runs")).get("/healthz")
    assert response.status_code == 503 and response.json()["status"] == "unavailable"


def test_export_file_is_mospi_named(project):
    response = TestClient(create_app(project / "fusion" / "runs")).get("/api/export/queue")
    assert "mospi-review-queue.csv" in response.headers["content-disposition"]


def test_server_refuses_network_bind_without_auth_unless_container_opt_in(monkeypatch):
    import sys
    from fusion import serve
    monkeypatch.setattr(serve.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.delenv("MOSPI_CONTAINER", raising=False)
    monkeypatch.setattr(sys, "argv", ["serve", "--host", "0.0.0.0"])
    with pytest.raises(SystemExit):
        serve.main()
    monkeypatch.setenv("MOSPI_CONTAINER", "1")
    serve.main()                                          # explicit container opt-in is allowed
