"""Batch validation started from the workspace (W8.7): a real pipeline run in its own process, on a synthetic delivery."""
from __future__ import annotations

import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient

from fusion.api import create_app

from .synthetic import write_delivery


def _wait(client: TestClient, job_id: str, seconds: float = 300) -> dict:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        job = client.get(f"/api/batch/{job_id}").json()
        if job["status"] not in {"STARTING", "RUNNING"}:
            return job
        time.sleep(1)
    raise AssertionError(f"job {job_id} did not finish: {job}")


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    root = tmp_path_factory.mktemp("workspace")
    prepared, _ = write_delivery(root / "preprocessing" / "runs" / "2024_first_visit_synthetic")
    broken = root / "preprocessing" / "runs" / "broken" / "prepared_persons.parquet"
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"this is not a parquet file")
    datasets = {"2024": {"prepared": str(prepared), "history": []}, "broken": {"prepared": str(broken), "history": []},
                "absent": {"prepared": str(root / "missing" / "prepared_persons.parquet"), "history": []}}
    return root, datasets, TestClient(create_app(root / "fusion" / "runs", project_root=root, batch_datasets=datasets))


def test_inputs_list_supported_deliveries_and_say_upload_is_not_offered(workspace):
    _, _, client = workspace
    data = client.get("/api/batch/inputs").json()
    by_release = {row["release"]: row for row in data["inputs"]}
    assert by_release["2024"]["available"] and by_release["2024"]["records"] > 0 and not by_release["absent"]["available"]
    assert data["can_start"] and data["upload"]["available"] is False


def test_invalid_requests_are_refused_with_a_reason(workspace):
    _, _, client = workspace
    assert client.post("/api/batch", json={"release": "1999", "label": "x"}).status_code == 400
    assert client.post("/api/batch", json={"release": "2024", "label": "Bad Label!"}).status_code == 400
    assert client.post("/api/batch", json={"release": "absent", "label": "x"}).status_code == 409
    response = client.post("/api/batch", json={"release": "2024", "label": "x", "rerun": ["fusion"]})
    assert response.status_code == 400 and "earlier run" in response.json()["detail"]


def test_batch_runs_the_real_pipeline_and_its_result_opens_in_the_workspace(workspace):
    _, _, client = workspace
    started = client.post("/api/batch", json={"release": "2024", "label": "ui_batch", "actor": "Test Admin"})
    assert started.status_code == 200, started.text
    job = started.json()
    assert job["status"] in {"STARTING", "RUNNING"} and job["actor_verified"] is False
    # One batch at a time.
    assert client.post("/api/batch", json={"release": "2024", "label": "second"}).status_code == 409
    job = _wait(client, job["job_id"])
    assert job["status"] == "COMPLETED", job.get("error")
    assert set(job["qa"].values()) == {"PASSED"} and job["summary"]["records"] > 0 and job["log_tail"]
    runs = {run["directory"] for run in client.get("/api/runs").json()}
    assert job["fusion_run"] in runs
    overview = client.get("/api/overview", params={"run": job["fusion_run"]}).json()
    assert overview["method"] == "lanes"
    cases = client.get("/api/cases", params={"run": job["fusion_run"], "tier": "B"}).json()
    assert cases["rows"]
    # Stored runs are immutable: the same label is refused.
    assert client.post("/api/batch", json={"release": "2024", "label": "ui_batch"}).status_code == 409
    # Re-computing only fusion on top of the stored stages is allowed under a new label.
    again = client.post("/api/batch", json={"release": "2024", "label": "ui_batch2", "reuse_label": "ui_batch", "rerun": ["fusion"]}).json()
    again = _wait(client, again["job_id"])
    assert again["status"] == "COMPLETED" and again["timing_seconds"]["statistical"] == "reused" and again["timing_seconds"]["fusion"] != "reused"
    assert [j["job_id"] for j in client.get("/api/batch").json()["jobs"]][:2] == [again["job_id"], job["job_id"]]


def test_a_failing_batch_reports_its_error(workspace):
    _, _, client = workspace
    job = _wait(client, client.post("/api/batch", json={"release": "broken", "label": "fails"}).json()["job_id"], 120)
    assert job["status"] == "FAILED" and job["error"]


def test_a_vanished_process_is_reported_as_interrupted(workspace):
    root, _, client = workspace
    job_id = "0" * 32
    folder = root / "pipeline" / "jobs"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{job_id}.json").write_text(json.dumps({"job_id": job_id, "release": "2024", "label": "lost", "status": "RUNNING", "pid": 2 ** 22 + 7,
                                                       "created_utc": "2026-01-01T00:00:00+00:00", "log": str(folder / "none.log")}), encoding="utf-8")
    assert client.get(f"/api/batch/{job_id}").json()["status"] == "INTERRUPTED"
    assert client.get("/api/batch/not-a-job").status_code == 404


def test_only_an_administrator_can_start_a_batch(workspace, tmp_path):
    root, datasets, _ = workspace
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": [{"name": "S", "role": "supervisor", "token_sha256": hashlib.sha256(b"sup").hexdigest()},
                                           {"name": "A", "role": "admin", "token_sha256": hashlib.sha256(b"adm").hexdigest()}]}), encoding="utf-8")
    client = TestClient(create_app(root / "fusion" / "runs", project_root=root, users_file=users, batch_datasets=datasets))
    assert client.post("/api/batch", json={"release": "2024", "label": "y"}).status_code == 401
    refused = client.post("/api/batch", json={"release": "2024", "label": "y"}, headers={"Authorization": "Bearer sup"})
    assert refused.status_code == 403
    assert client.get("/api/batch/inputs", headers={"Authorization": "Bearer sup"}).json()["can_start"] is False
    # The administrator passes the role check (and is then refused for the invalid label, before anything runs).
    assert client.post("/api/batch", json={"release": "2024", "label": "Bad!"}, headers={"Authorization": "Bearer adm"}).status_code == 400
