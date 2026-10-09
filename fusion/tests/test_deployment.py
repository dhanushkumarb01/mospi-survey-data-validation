"""Review-only and hosted (Vercel) deployment modes, on synthetic data only (docs/VERCEL_REVIEW_ONLY_DEPLOYMENT.md).

Each test builds its own small Fusion run in a temporary directory; no stored run or real audit trail is opened.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import shutil
import sqlite3
import threading
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from fusion.api import create_app
from fusion.review import DecisionConflict, append_event, latest_statuses, verify_chain

ROOT = Path(__file__).resolve().parents[2]
DECISION = {"event_type": "DECISION_MADE", "decision": "VALID_BUT_UNUSUAL", "reason_code": "GENUINE_HIGH_OR_LOW_VALUE", "verification_source": "PHONE_CALL"}


@pytest.fixture()
def project(tmp_path):
    """A minimal lane-method Fusion run (two synthetic cases) in a throwaway project root."""
    run = tmp_path / "fusion" / "runs" / "2024_first_visit_synthetic"
    run.mkdir(parents=True)
    rows = [{"case_id": f"case_{i}", "source_observation_id": f"Q1|1|07|01|F{i}|1|1|01|person=1", "release": "2024", "observation_type": "first_visit",
             "state": "07", "sector": "1", "stratum": "01", "fsu": f"F{i}", "priority_score": 1.0 - i / 10, "priority_band": "CHECK_NOW",
             "tier": "A", "lanes": "VALUE", "lane": "VALUE", "queue_position": i + 1, "case_level": "PERSON", "household_key": f"h{i}"} for i in range(2)]
    pd.DataFrame(rows).to_parquet(run / "fused_cases.parquet", index=False)
    (run / "run_metadata.json").write_text(json.dumps({"run_id": "synthetic", "release": "2024", "observation": "first_visit",
                                                       "fusion_version": "iospi-fusion-v2.1-lanes", "source_runs": {}}), encoding="utf-8")
    (run / "fusion_report.json").write_text(json.dumps({"records_processed": 2, "priority_rows": 2}), encoding="utf-8")
    return tmp_path, run


def _client(root: Path, **options) -> TestClient:
    return TestClient(create_app(root / "fusion" / "runs", project_root=root, batch_datasets={}, **options))


# ------------------------------------------------------------------ review-only: no batch can start


def test_review_only_refuses_every_batch_start_on_the_server(project):
    root, _ = project
    client = _client(root, review_only=True)
    for method, path in (("post", "/api/batch"), ("put", "/api/batch"), ("post", "/api/batch/abc"), ("delete", "/api/batch/abc"), ("post", "/api/batch/inputs")):
        response = client.request(method.upper(), path, json={"release": "2024", "label": "x1"})
        assert response.status_code == 403 and "review-only" in response.json()["detail"], (method, path)
    inputs = client.get("/api/batch/inputs").json()
    assert inputs["can_start"] is False and inputs["inputs"] == [] and inputs["review_only"] is True
    assert client.get("/api/batch").json() == {"jobs": [], "review_only": True, "reason": inputs["reason"]}
    assert client.get("/api/batch/" + "0" * 32).status_code == 404
    assert client.get("/api/deployment").json()["review_only"] is True
    assert not (root / "pipeline" / "jobs").exists()        # nothing was queued or written


def test_review_only_refuses_batch_even_for_an_authenticated_admin(project):
    root, _ = project
    users = json.dumps({"users": [{"name": "Admin", "role": "admin", "token_sha256": hashlib.sha256(b"t-admin").hexdigest()}]})
    client = _client(root, review_only=True, users_json=users)
    response = client.post("/api/batch", json={"release": "2024", "label": "x1"}, headers={"Authorization": "Bearer t-admin"})
    assert response.status_code == 403 and response.json()["review_only"] is True


def test_review_pages_still_work_in_review_only_mode(project):
    root, _ = project
    client = _client(root, review_only=True)
    assert client.get("/api/overview").status_code == 200
    assert client.get("/api/cases").json()["total"] == 2
    assert client.post("/api/cases/case_0/events", json=DECISION).status_code == 200     # local disk: decisions still recorded
    assert client.get("/api/reviews").json()["total"] == 1


def test_batch_routes_stay_available_when_review_only_is_off(project):
    root, _ = project
    client = _client(root)
    assert client.get("/api/deployment").json() == {"review_only": False, "batch_reason": None, "audit_writable": True, "audit_reason": None, "data_notice": None}
    response = client.post("/api/batch", json={"release": "2024", "label": "x1"})
    assert response.status_code == 400 and "not a supported input" in response.json()["detail"]    # reaches the job manager


# ------------------------------------------------------------------ hosted: read-only audit, never temporary storage


def test_audit_read_only_refuses_writes_and_keeps_history_readable(project):
    root, run = project
    append_event(run / "review_audit.sqlite", case_id="case_0", event_type="DECISION_MADE", actor="earlier", **{k: v for k, v in DECISION.items() if k != "event_type"})
    before = (run / "review_audit.sqlite").read_bytes()
    client = _client(root, review_only=True, audit_read_only=True)
    for body in (DECISION, {"event_type": "CASE_VIEWED"}):
        response = client.post("/api/cases/case_1/events", json=body)
        assert response.status_code == 503 and "no durable audit store" in response.json()["detail"]
    assert client.get("/api/export/queue").status_code == 503              # exports are logged, so not offered
    assert client.get("/api/reviews").json()["rows"][0]["actor"] == "earlier"
    assert client.get("/api/audit/verify").json()["status"] == "INTACT"
    assert (run / "review_audit.sqlite").read_bytes() == before            # not one byte appended
    health = client.get("/healthz").json()
    assert health["audit_store"] == "read-only" and health["audit_store_writable"] is False and health["review_only"] is True


# ------------------------------------------------------------------ persistence and concurrency (local audit store)


def test_decision_persists_across_requests_and_application_restarts(project):
    root, run = project
    first = _client(root)
    assert first.post("/api/cases/case_0/events", json=DECISION).status_code == 200
    restarted = _client(root)        # a new application instance on the same store
    assert restarted.get("/api/cases/case_0").json()["review_status"] == "VALID_BUT_UNUSUAL"
    assert latest_statuses(run / "review_audit.sqlite") == {"case_0": "VALID_BUT_UNUSUAL"}


def test_stale_decision_is_refused_instead_of_silently_replacing_another(project):
    root, _ = project
    client = _client(root)
    first = client.post("/api/cases/case_0/events", json={**DECISION, "expected_last_decision_id": None})
    assert first.status_code == 200
    # A second reviewer opened the case before the first decision and still believes it is undecided.
    stale = client.post("/api/cases/case_0/events", json={**DECISION, "decision": "CONFIRMED_ERROR", "reason_code": "WRONG_CODE", "expected_last_decision_id": None})
    assert stale.status_code == 409 and "Another reviewer" in stale.json()["detail"]
    fresh = client.post("/api/cases/case_0/events", json={**DECISION, "decision": "CONFIRMED_ERROR", "reason_code": "WRONG_CODE",
                                                          "expected_last_decision_id": first.json()["event_id"]})
    assert fresh.status_code == 200
    assert client.get("/api/audit/verify").json()["status"] == "INTACT"


def test_concurrent_appends_keep_one_intact_chain(tmp_path):
    path = tmp_path / "audit.sqlite"
    errors: list[BaseException] = []

    def write(worker: int) -> None:
        try:
            for k in range(15):
                append_event(path, case_id=f"case_{worker}_{k}", event_type="DECISION_MADE", actor=f"reviewer {worker}",
                             **{k2: v for k2, v in DECISION.items() if k2 != "event_type"})
        except BaseException as error:   # noqa: BLE001 - reported below
            errors.append(error)

    threads = [threading.Thread(target=write, args=(w,)) for w in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    result = verify_chain(path)
    assert result["status"] == "INTACT" and result["events"] == 6 * 15 + 1      # + the chain-start event
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='AUDIT_CHAIN_STARTED'").fetchone()[0] == 1


def test_concurrent_decisions_on_one_case_admit_exactly_one(tmp_path):
    path = tmp_path / "audit.sqlite"
    outcomes: list[str] = []

    def decide() -> None:
        try:
            append_event(path, case_id="case_x", event_type="DECISION_MADE", actor="r", expected_last_decision_id=None,
                         **{k: v for k, v in DECISION.items() if k != "event_type"})
            outcomes.append("saved")
        except DecisionConflict:
            outcomes.append("conflict")

    threads = [threading.Thread(target=decide) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["conflict"] * 7 + ["saved"]
    assert verify_chain(path)["status"] == "INTACT"


# ------------------------------------------------------------------ access control


def test_hosted_mode_serves_no_data_until_users_are_configured(project):
    root, _ = project
    client = _client(root, review_only=True, audit_read_only=True, require_authentication=True)
    assert client.get("/api/session/required").status_code == 200
    for path in ("/api/runs", "/api/overview", "/api/cases", "/api/cases/case_0", "/api/reviews", "/api/export/queue", "/api/audit/verify", "/api/deployment"):
        assert client.get(path).status_code == 503, path


def test_environment_users_protect_every_api_route(project):
    root, _ = project
    token = "test-token-not-a-secret"
    users = json.dumps({"users": [{"name": "Reviewer One", "role": "technical", "token_sha256": hashlib.sha256(token.encode()).hexdigest()}]})
    client = _client(root, review_only=True, audit_read_only=True, require_authentication=True, users_json=users)
    paths = ["/api/runs", "/api/overview", "/api/cases", "/api/cases/case_0", "/api/worklist", "/api/reviews", "/api/groups", "/api/aggregates",
             "/api/feedback", "/api/audit/verify", "/api/export/queue", "/api/evaluation", "/api/integrity", "/api/summary", "/api/deployment", "/api/batch"]
    for path in paths:
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401, path
    assert client.post("/api/cases/case_0/events", json=DECISION).status_code == 401
    signed_in = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/session", headers=signed_in).json()["user"] == {"name": "Reviewer One", "role": "technical"}
    assert client.get("/api/cases", headers=signed_in).status_code == 200
    # The HTML shell and static assets carry no data and stay public; /healthz reports readiness only.
    assert client.get("/").status_code == 200 and client.get("/assets/app.js").status_code == 200


def test_every_api_route_is_covered_by_the_access_test():
    """A new /api route must be added to the access test above (or to this allowlist with a reason)."""
    api = (ROOT / "fusion" / "api.py").read_text(encoding="utf-8")
    routes = set(re.findall(r'@app\.(?:get|post)\("(/api/[^"{]*)', api))
    tested = {"/api/runs", "/api/overview", "/api/cases", "/api/cases/", "/api/worklist", "/api/reviews", "/api/groups", "/api/groups/", "/api/aggregates",
              "/api/feedback", "/api/audit/verify", "/api/export/queue", "/api/evaluation", "/api/integrity", "/api/summary", "/api/deployment", "/api/batch",
              "/api/batch/", "/api/batch/inputs", "/api/session", "/api/queue/position", "/api/labels", "/api/patterns", "/api/version", "/api/validate/record"}
    public = {"/api/session/required"}   # says only whether sign-in is needed
    assert routes - tested - public == set()


# ------------------------------------------------------------------ the Vercel entrypoint and packaging


def _vercel_app(monkeypatch, data: Path, **env):
    for name in ("MOSPI_USERS_JSON", "MOSPI_ALLOW_ANONYMOUS_DEMO"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MOSPI_DATA_DIR", str(data))
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    import fusion.vercel_app as module
    return TestClient(importlib.reload(module).app)


def test_vercel_entrypoint_is_review_only_read_only_and_requires_sign_in(project, monkeypatch):
    root, _ = project
    client = _vercel_app(monkeypatch, root)
    assert client.get("/api/runs").status_code == 503                         # no users configured
    assert _vercel_app(monkeypatch, root, MOSPI_USERS_JSON="not json").get("/api/runs").status_code == 503
    anonymous = _vercel_app(monkeypatch, root, MOSPI_ALLOW_ANONYMOUS_DEMO="1")
    assert anonymous.get("/api/runs").status_code == 503                      # refused: this data is not marked synthetic


def test_vercel_entrypoint_serves_the_committed_synthetic_demo(tmp_path, monkeypatch):
    demo = tmp_path / "demo-data"
    shutil.copytree(ROOT / "demo-data", demo)        # a copy, so the committed bundle is never written
    client = _vercel_app(monkeypatch, demo, MOSPI_ALLOW_ANONYMOUS_DEMO="1")
    deployment = client.get("/api/deployment").json()
    assert deployment["review_only"] and not deployment["audit_writable"] and "Synthetic demonstration data" in deployment["data_notice"]
    overview = client.get("/api/overview").json()
    assert overview["method"] == "lanes" and overview["records_processed"] > 0
    case_id = client.get("/api/cases").json()["rows"][0]["case_id"]
    assert client.get(f"/api/cases/{case_id}").json()["story"]["method"] == "lanes"
    assert client.post("/api/batch", json={"release": "2024", "label": "x"}).status_code == 403
    assert client.post(f"/api/cases/{case_id}/events", json=DECISION).status_code == 503
    assert client.get("/healthz").json()["status"] == "ok"
    assert not any(demo.rglob("*.sqlite"))


def test_vercel_packaging_matches_the_docker_dependencies_and_excludes_data():
    pins = sorted(line.strip() for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#"))
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert sorted(re.findall(r'^\s+"([^"]+==[^"]+)",', pyproject, flags=re.M)) == pins
    assert 'entrypoint = "fusion.vercel_app:app"' in pyproject
    assert "fusion/vercel_app.py" in json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))["functions"]
    ignore = (ROOT / ".vercelignore").read_text(encoding="utf-8").splitlines()
    assert "/*" in ignore and "!/demo-data/" in ignore and "/*/runs/" in ignore
    for never in ("*.sqlite", "users*.json", ".env", ".env.*", "*.csv"):
        assert never in ignore, never
    for folder in ("2023-June2024", "Jan-Dec2024", "Post2025", "EDA", "docs", "evaluation"):
        assert f"!/{folder}/" not in ignore, folder
    manifest = json.loads((ROOT / "demo-data" / "SERVING_DATA_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True and manifest["review_audit_included"] is False
