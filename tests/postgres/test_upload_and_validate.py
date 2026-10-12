"""Upload & validate, the worker, periodic checks and the hosted reader, end to end on SYNTHETIC data only.

Upload -> pre-flight -> explicit confirmation -> PostgreSQL job -> worker child process running the unchanged
preparation and V2.2 pipeline -> publication -> dashboard sees the run (same app instance, no restart) ->
decision recorded in PostgreSQL -> audit chains verified -> hosted reader sees only what it may.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from mospi.app.api import create_app
from mospi.db.audit import OPERATIONS_RUN, PostgresAuditStore
from mospi.pipeline.stages.preprocessing.config import CONTRACTS
from tests.postgres.conftest import USERS, auth
from tests.synthetic_raw import write_raw_delivery

pytestmark = pytest.mark.postgres
DECISION = {"event_type": "DECISION_MADE", "decision": "CONFIRMED_ERROR", "reason_code": "EXTRA_OR_MISSING_ZERO", "verification_source": "PHONE_CALL",
            "comment": "private reviewer note"}


@pytest.fixture()
def env(pg, tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "fusion" / "runs").mkdir(parents=True)
    monkeypatch.setenv("MOSPI_DATA_DIR", str(root))
    monkeypatch.setenv("MOSPI_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("MOSPI_JOB_STALE_SECONDS", "120")
    return {"pg": pg, "root": root, "tmp": tmp_path}


def _ops(env):
    from mospi.ingest.service import Operations
    return Operations(env["pg"]["app"], root=env["root"])


def _client(env, **options) -> TestClient:
    ops = options.pop("operations", None) or _ops(env)
    return TestClient(create_app(env["root"] / "fusion" / "runs", project_root=env["root"], users_json=USERS, batch_datasets={},
                                 audit_store=PostgresAuditStore(env["pg"]["app"]), operations=ops, **options))


def _upload(client: TestClient, files: dict[str, bytes], *, contract: str = "2024_first", synthetic: bool = True) -> dict:
    dataset = client.post("/api/datasets", json={"contract": contract, "synthetic": synthetic}, headers=auth("admin"))
    assert dataset.status_code == 200, dataset.text
    dataset_id = dataset.json()["dataset_id"]
    for name, content in files.items():
        response = client.put(f"/api/datasets/{dataset_id}/files", params={"name": name, "path": f"delivery/{name}"}, content=content, headers=auth("admin"))
        assert response.status_code == 200, response.text
    return client.post(f"/api/datasets/{dataset_id}/preflight", json={}, headers=auth("admin")).json()


def _delivery(env, name: str = "delivery", **sizes) -> dict[str, bytes]:
    paths = write_raw_delivery(env["tmp"] / name, **sizes)
    return {path.name: path.read_bytes() for path in paths.values()}


def _codes(dataset: dict) -> set[str]:
    return {f["code"] for f in dataset["preflight"]["findings"] if f["severity"] == "BLOCKING"}


def _run_worker(env) -> None:
    from mospi.ingest.worker import loop
    loop(_ops(env), once=True)


# ------------------------------------------------------------------ the whole path


def test_upload_to_published_run_to_dashboard_to_audit(env):
    from mospi.ingest.service import HostedOperations
    client = _client(env)
    files = _delivery(env)
    dataset = _upload(client, files)
    assert dataset["status"] == "PREFLIGHT_PASSED", dataset["preflight"]["findings"]
    assert {f["level"] for f in dataset["files"]} == {"household", "person"} and dataset["preflight"]["counts"]["person"]["rows"] == 1152
    # Counts and column names only: no record key or survey value leaves the server in the report.
    sample_key = pd.read_csv(env["tmp"] / "delivery" / "cperv1.csv", dtype=str, nrows=1).iloc[0]
    report_text = json.dumps(dataset)
    assert sample_key["FSU"] not in report_text and "observed_value" not in report_text
    dataset_id = dataset["dataset_id"]

    # Explicit confirmation, idempotent.
    assert client.post(f"/api/datasets/{dataset_id}/confirm", json={"label": "e2e_run"}, headers=auth("admin")).status_code == 400
    key = {"Idempotency-Key": uuid.uuid4().hex, **auth("admin")}
    job = client.post(f"/api/datasets/{dataset_id}/confirm", json={"label": "e2e_run", "confirm": True}, headers=key).json()
    again = client.post(f"/api/datasets/{dataset_id}/confirm", json={"label": "e2e_run", "confirm": True}, headers=key).json()
    assert job["status"] == "QUEUED" and again["job_id"] == job["job_id"]
    assert client.post(f"/api/datasets/{dataset_id}/confirm", json={"confirm": True}, headers=auth("admin")).status_code == 409
    run_id = "2024_first_visit_e2e_run"
    assert run_id not in {r["directory"] for r in client.get("/api/runs", headers=auth("supervisor")).json()}

    _run_worker(env)

    job = client.get(f"/api/jobs/{job['job_id']}", headers=auth("technical")).json()
    assert job["status"] == "SUCCEEDED", (job["error_class"], job["error_message"], job["events"][-3:])
    stages = {e["stage"] for e in job["events"] if e["status"] in ("COMPLETED", "REUSED")}
    assert {"staging", "preparation", "peer", "statistical", "contextual", "ml", "pattern", "historical", "integrity", "fusion", "publication"} <= stages
    assert set(job["result"]["qa"].values()) == {"PASSED"}
    registry = env["pg"]["admin"].fetchone("SELECT * FROM runs WHERE run_id = %s", (run_id,))
    assert registry["status"] == "PUBLISHED" and registry["manifest_sha256"] and registry["records"] == 1152

    # The dashboard sees the new run at once (same application instance; no restart or redeploy).
    runs = {r["directory"] for r in client.get("/api/runs", headers=auth("supervisor")).json()}
    assert run_id in runs
    overview = client.get("/api/overview", params={"run": run_id}, headers=auth("supervisor")).json()
    assert overview["method"] == "lanes" and overview["records_processed"] > 0
    case_id = client.get("/api/cases", params={"run": run_id, "tier": "A"}, headers=auth("supervisor")).json()["rows"][0]["case_id"]
    assert client.post(f"/api/cases/{case_id}/events", params={"run": run_id}, json=DECISION, headers=auth("supervisor")).status_code == 200
    assert client.get(f"/api/cases/{case_id}", params={"run": run_id}, headers=auth("supervisor")).json()["review_status"] == "CONFIRMED_ERROR"
    assert client.get("/api/audit/verify", params={"run": run_id}, headers=auth("technical")).json()["status"] == "INTACT"
    store = PostgresAuditStore(env["pg"]["app"])
    operations_trail = [e["event_type"] for e in store.all_events(OPERATIONS_RUN)]
    for event in ("DATASET_CREATED", "FILE_RECEIVED", "PREFLIGHT_COMPLETED", "VALIDATION_REQUESTED", "VALIDATION_STARTED", "VALIDATION_SUCCEEDED", "RUN_PUBLISHED"):
        assert event in operations_trail, event
    assert store.verify(OPERATIONS_RUN)["status"] == "INTACT"
    status = client.get("/api/operations", headers=auth("supervisor")).json()
    assert any(r["run_id"] == run_id and r["status"] == "PUBLISHED" for r in status["runs"]) and not status["active_jobs"]
    assert any(n["kind"] == "RUN_PUBLISHED" for n in client.get("/api/notifications", headers=auth("technical")).json()["notifications"])

    # Hosted reader: nothing until the run is cleared for hosting; then decisions without the comment, read-only.
    hosted = TestClient(create_app(env["root"] / "fusion" / "runs", project_root=env["root"], users_json=USERS, review_only=True, audit_read_only=True,
                                   require_authentication=True, audit_store=PostgresAuditStore(env["pg"]["reader"], hosted=True),
                                   operations=HostedOperations(env["pg"]["reader"])))
    assert hosted.get(f"/api/cases/{case_id}", params={"run": run_id}, headers=auth("supervisor")).json()["audit_history"] == []
    env["pg"]["admin"].execute("UPDATE runs SET hosted_visible = TRUE WHERE run_id = %s", (run_id,))
    history = hosted.get(f"/api/cases/{case_id}", params={"run": run_id}, headers=auth("supervisor")).json()["audit_history"]
    assert [h["decision"] for h in history if h["event_type"] == "DECISION_MADE"] == ["CONFIRMED_ERROR"] and "private reviewer note" not in json.dumps(history)
    assert hosted.post(f"/api/cases/{case_id}/events", params={"run": run_id}, json=DECISION, headers=auth("admin")).status_code == 503
    assert hosted.post("/api/datasets", json={"contract": "2024_first"}, headers=auth("admin")).status_code == 403
    assert any(r["run_id"] == run_id for r in hosted.get("/api/operations", headers=auth("supervisor")).json()["runs"])

    # Periodic integrity check (operation A): passes, then catches a changed published artifact; never starts a rerun.
    assert client.post("/api/checks", headers=auth("admin")).status_code == 200
    _run_worker(env)
    check = client.get("/api/jobs", params={"kind": "INTEGRITY_CHECK"}, headers=auth("technical")).json()["jobs"][0]
    assert check["status"] == "SUCCEEDED", client.get(f"/api/jobs/{check['job_id']}", headers=auth("technical")).json()["findings"][:5]
    with open(env["root"] / "fusion" / "runs" / run_id / "fusion_report.md", "ab") as handle:
        handle.write(b"\nedited by hand\n")
    client.post("/api/checks", headers=auth("admin"))
    _run_worker(env)
    check = client.get(f"/api/jobs/{client.get('/api/jobs', params={'kind': 'INTEGRITY_CHECK'}, headers=auth('technical')).json()['jobs'][0]['job_id']}",
                       headers=auth("technical")).json()
    assert check["status"] == "FAILED" and check["error_class"] == "INTEGRITY_FINDINGS"
    assert any(f["target_id"] == run_id and f["check_name"] == "artifacts_unchanged" and f["status"] == "FAILED" for f in check["findings"])
    assert client.get("/api/operations", headers=auth("supervisor")).json()["last_check"]["status"] == "FAILED"
    assert len(client.get("/api/jobs", params={"kind": "VALIDATION"}, headers=auth("technical")).json()["jobs"]) == 1     # no unnecessary rerun


# ------------------------------------------------------------------ pre-flight refusals


def test_preflight_blocks_invalid_deliveries_with_actionable_reasons(env, monkeypatch):
    client = _client(env)
    files = _delivery(env)
    household, person = files["chhv1.csv"], files["cperv1.csv"]
    assert _codes(_upload(client, {"notes.txt": household})) >= {"NOT_A_CSV"}
    assert "UTF8_BOM" in _codes(_upload(client, {"chhv1.csv": b"\xef\xbb\xbf" + household, "cperv1.csv": person}))
    assert "NOT_UTF8" in _codes(_upload(client, {"chhv1.csv": household.replace(b"P4", "P\xe9".encode("cp1252"), 1), "cperv1.csv": person}))
    assert "MISSING_FILE" in _codes(_upload(client, {"chhv1.csv": household}))
    frame = pd.read_csv(env["tmp"] / "delivery" / "cperv1.csv", dtype=str, keep_default_na=False)
    missing = _upload(client, {"chhv1.csv": household, "cperv1.csv": frame.drop(columns=["Age"]).to_csv(index=False).encode()})
    assert "MISSING_REQUIRED_COLUMNS" in _codes(missing) and any("Age" in f["message"] for f in missing["preflight"]["findings"])
    layout_2025 = ",".join(sorted(set(CONTRACTS["2025_first"].person_fields.values()))).encode() + b"\n"
    wrong = _upload(client, {"chhv1.csv": household, "cperv1.csv": layout_2025 + b",".join([b"1"] * len(set(CONTRACTS["2025_first"].person_fields.values()))) + b"\n"})
    assert any("2025_first" in f["message"] for f in wrong["preflight"]["findings"])
    ragged = person + b"1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62\n"
    assert "MALFORMED_CSV" in _codes(_upload(client, {"chhv1.csv": household, "cperv1.csv": ragged}))
    blocked = _upload(client, {"chhv1.csv": household})
    assert client.post(f"/api/datasets/{blocked['dataset_id']}/confirm", json={"confirm": True}, headers=auth("admin")).status_code == 409
    assert client.post(f"/api/datasets/{blocked['dataset_id']}/reject", headers=auth("admin")).json()["status"] == "REJECTED"
    # Names are display text only: a traversal attempt in the folder path is refused, and nothing is written outside the upload root.
    dataset_id = client.post("/api/datasets", json={"contract": "2024_first"}, headers=auth("admin")).json()["dataset_id"]
    assert client.put(f"/api/datasets/{dataset_id}/files", params={"name": "a.csv", "path": "../../evil/a.csv"}, content=b"x", headers=auth("admin")).status_code == 400
    assert client.put(f"/api/datasets/{dataset_id}/files", params={"name": ".."}, content=b"x", headers=auth("admin")).status_code == 400
    stored = client.put(f"/api/datasets/{dataset_id}/files", params={"name": "../../../windows/x.csv"}, content=b"a\n1\n", headers=auth("admin")).json()
    assert stored["name"] == "x.csv" and not (env["tmp"] / "windows").exists()
    # Size and count limits.
    monkeypatch.setenv("MOSPI_UPLOAD_MAX_FILE_MB", "1")
    monkeypatch.setenv("MOSPI_UPLOAD_MAX_FILES", "2")
    small = _client(env)
    dataset_id = small.post("/api/datasets", json={"contract": "2024_first"}, headers=auth("admin")).json()["dataset_id"]
    assert small.put(f"/api/datasets/{dataset_id}/files", params={"name": "big.csv"}, content=b"a," * 600_000, headers=auth("admin")).status_code == 413
    assert not list((env["tmp"] / "uploads" / dataset_id).rglob("*.part"))
    for name in ("a.csv", "b.csv"):
        assert small.put(f"/api/datasets/{dataset_id}/files", params={"name": name}, content=b"a\n1\n", headers=auth("admin")).status_code == 200
    assert small.put(f"/api/datasets/{dataset_id}/files", params={"name": "c.csv"}, content=b"a\n1\n", headers=auth("admin")).status_code == 413


def test_duplicate_files_resaved_copies_and_overlapping_records_are_blocked(env):
    client = _client(env)
    files = _delivery(env)
    first = _upload(client, files)
    assert first["status"] == "PREFLIGHT_PASSED"
    client.post(f"/api/datasets/{first['dataset_id']}/confirm", json={"confirm": True}, headers=auth("admin"))
    assert "DUPLICATE_FILE" in _codes(_upload(client, files))
    lines = {name: content.decode().splitlines() for name, content in files.items()}
    resaved = {name: ("\r\n".join([rows[0], *reversed(rows[1:])]) + "\r\n").encode() for name, rows in lines.items()}
    assert "DUPLICATE_CONTENT" in _codes(_upload(client, resaved))
    changed = {name: content.replace(b"P4", b"P5") for name, content in files.items()}      # a non-key column: same records, different bytes
    overlapping = _upload(client, changed)
    assert "OVERLAPPING_RECORDS" in _codes(overlapping) and overlapping["preflight"]["counts"]["person"]["overlapping_records"] == 1152


# ------------------------------------------------------------------ authorisation


def test_uploads_and_operations_require_the_right_role_and_a_local_instance(env):
    from mospi.ingest.service import HostedOperations
    client = _client(env)
    assert client.post("/api/datasets", json={"contract": "2024_first"}).status_code == 401
    assert client.post("/api/datasets", json={"contract": "2024_first"}, headers=auth("supervisor")).status_code == 403
    assert client.post("/api/datasets", json={"contract": "2024_first"}, headers=auth("technical")).status_code == 403
    assert client.get("/api/datasets", headers=auth("technical")).status_code == 200
    assert client.get("/api/datasets", headers=auth("supervisor")).status_code == 403
    assert client.post("/api/checks", headers=auth("technical")).status_code == 403
    assert client.get("/api/operations", headers=auth("supervisor")).status_code == 200
    no_users = TestClient(create_app(env["root"] / "fusion" / "runs", project_root=env["root"], batch_datasets={}, operations=_ops(env),
                                     audit_store=PostgresAuditStore(env["pg"]["app"])))
    assert no_users.post("/api/datasets", json={"contract": "2024_first"}).status_code == 403          # loopback without sign-in: still refused
    review_only = _client(env, review_only=True)
    assert review_only.post("/api/datasets", json={"contract": "2024_first"}, headers=auth("admin")).status_code == 403
    hosted = _client(env, operations=HostedOperations(env["pg"]["reader"]))
    assert hosted.post("/api/checks", headers=auth("admin")).status_code == 403
    sqlite_only = TestClient(create_app(env["root"] / "fusion" / "runs", project_root=env["root"], users_json=USERS, batch_datasets={}))
    assert sqlite_only.get("/api/datasets", headers=auth("admin")).status_code == 404
    assert sqlite_only.get("/api/operations", headers=auth("admin")).json()["available"] is False


# ------------------------------------------------------------------ reliability: cancel, interruption, automatic retry, QA-gate rule


def test_cancel_interruption_and_automatic_retry_resume_without_overwriting(env):
    from mospi.ingest.worker import claim_validation, recover
    client = _client(env)
    dataset = _upload(client, _delivery(env))
    job = client.post(f"/api/datasets/{dataset['dataset_id']}/confirm", json={"label": "resume", "confirm": True}, headers=auth("admin")).json()
    cancelled = client.post(f"/api/jobs/{job['job_id']}/cancel", headers=auth("admin")).json()
    assert cancelled["status"] == "CANCELLED"
    assert client.post(f"/api/jobs/{job['job_id']}/cancel", headers=auth("admin")).status_code == 409
    job = client.post(f"/api/datasets/{dataset['dataset_id']}/confirm", json={"confirm": True}, headers=auth("admin")).json()
    assert job["status"] == "QUEUED" and job["label"] == "resume"

    # A worker claims the job and dies before reporting (simulated: no process, heartbeat in the past) after leaving a partial stage directory.
    ops = _ops(env)
    claimed = claim_validation(ops)
    assert claimed["job_id"] == job["job_id"]
    env["pg"]["admin"].execute("UPDATE jobs SET heartbeat_utc = now() - interval '1 hour' WHERE job_id = %s", (job["job_id"],))
    partial = env["root"] / "statistical" / "runs" / "2024_first_visit_resume"
    partial.mkdir(parents=True)
    (partial / "half-written.parquet").write_bytes(b"partial")
    assert recover(ops) == [job["job_id"]]
    interrupted = client.get(f"/api/jobs/{job['job_id']}", headers=auth("technical")).json()
    assert interrupted["status"] == "INTERRUPTED"
    retry = env["pg"]["admin"].fetchone("SELECT * FROM jobs WHERE parent_job_id = %s", (job["job_id"],))
    assert retry["status"] == "QUEUED" and retry["attempt"] == 2 and retry["trigger"] == "RETRY"
    assert "2024_first_visit_resume" not in {r["directory"] for r in client.get("/api/runs", headers=auth("supervisor")).json()}

    _run_worker(env)
    done = client.get(f"/api/jobs/{retry['job_id']}", headers=auth("technical")).json()
    assert done["status"] == "SUCCEEDED", done["error_message"]
    assert any("set aside" in (e["message"] or "") for e in done["events"])
    assert list(partial.parent.glob("2024_first_visit_resume.incomplete-*/half-written.parquet"))       # kept, never deleted
    assert client.post(f"/api/jobs/{job['job_id']}/retry", headers=auth("admin")).json()["job_id"] == retry["job_id"]   # idempotent

    env["pg"]["admin"].execute("""INSERT INTO jobs (job_id, kind, status, trigger, dataset_id, run_id, label, requested_by)
                                  VALUES (%s, 'VALIDATION', 'FAILED_QA_GATE', 'MANUAL', %s, 'x', 'x', 't')""", ("f" * 32, dataset["dataset_id"]))
    refused = client.post(f"/api/jobs/{'f' * 32}/retry", headers=auth("admin"))
    assert refused.status_code == 409 and "quality check" in refused.json()["detail"]


# ------------------------------------------------------------------ scheduler and change detection


def test_scheduler_queues_one_check_per_slot_and_reruns_only_changed_deliveries(env, monkeypatch):
    from mospi.ingest.register import register_delivery
    from mospi.ingest.worker import run_check_job, schedule
    monkeypatch.setenv("MOSPI_CHECK_INTERVAL_MINUTES", "60")
    ops = _ops(env)
    first = schedule(ops, now=7200.0)
    assert first and schedule(ops, now=7300.0) is None and schedule(ops, now=11000.0) is None       # same slot; then the first is still active
    assert run_check_job(ops) == first
    assert env["pg"]["admin"].fetchone("SELECT COUNT(*) AS n FROM jobs WHERE kind = 'INTEGRITY_CHECK'")["n"] == 1

    # A delivery registered in place (as under data/raw), validated earlier.
    raw = env["tmp"] / "raw"
    contract = CONTRACTS["2024_first"]
    for level, path in write_raw_delivery(env["tmp"] / "made").items():
        target = contract.file_path(raw, level)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    registered = register_delivery(ops, contract="2024_first", input_root=raw, synthetic=True)
    assert registered["status"] == "PREFLIGHT_PASSED"
    env["pg"]["admin"].execute("UPDATE datasets SET status = 'VALIDATED' WHERE dataset_id = %s", (registered["dataset_id"],))
    ops.trigger_check(user=None)
    run_check_job(ops)
    assert env["pg"]["admin"].fetchone("SELECT COUNT(*) AS n FROM jobs WHERE kind = 'VALIDATION'")["n"] == 0      # unchanged: no rerun

    person = contract.file_path(raw, "person")
    person.write_bytes(person.read_bytes().replace(b"P4", b"P6", 1))
    monkeypatch.setenv("MOSPI_RERUN_ON_CHANGE", "1")
    ops = _ops(env)
    ops.trigger_check(user=None)
    check_id = run_check_job(ops)
    findings = ops.job(check_id)["findings"]
    assert any(f["status"] == "CHANGED" and f["target_id"] == registered["dataset_id"] for f in findings)
    jobs = env["pg"]["admin"].fetch("SELECT trigger, status FROM jobs WHERE kind = 'VALIDATION'")
    assert [(j["trigger"], j["status"]) for j in jobs] == [("CHANGE_DETECTED", "QUEUED")]
    ops.trigger_check(user=None)
    run_check_job(ops)
    assert env["pg"]["admin"].fetchone("SELECT COUNT(*) AS n FROM jobs WHERE kind = 'VALIDATION'")["n"] == 1      # one rerun per change, not per check

    # A stored upload that changes after it was received is tampering: FAILED, never CHANGED.
    client = _client(env)
    uploaded = _upload(client, _delivery(env, "other", seed=5))
    stored = Path(env["pg"]["admin"].fetchone("SELECT stored_path FROM dataset_files WHERE dataset_id = %s LIMIT 1", (uploaded["dataset_id"],))["stored_path"])
    stored.write_bytes(stored.read_bytes() + b"\n")
    ops.trigger_check(user=None)
    check = ops.job(run_check_job(ops))
    assert check["status"] == "FAILED" and any(f["target_id"] == uploaded["dataset_id"] and f["status"] == "FAILED" for f in check["findings"])
