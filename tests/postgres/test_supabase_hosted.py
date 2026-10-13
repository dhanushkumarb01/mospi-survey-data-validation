"""Supabase hosting: transaction-pooler behaviour, row level security, platform roles denied, the hosted serving set
(load -> verify in the database -> reader-only download -> unchanged pages), tamper detection and the hosting approval.

Runs against the database named by MOSPI_DB_ADMIN_URL, in a throwaway schema (tests/postgres/conftest.py), on the
SYNTHETIC demonstration bundle only (data/demo).
"""
from __future__ import annotations

import hashlib
import importlib
import json
import shutil

import psycopg
import pytest
from fastapi.testclient import TestClient

from mospi.db.connection import Database
from mospi.db.registry import register_existing
from mospi.db.serving import HostedServingData, ServingError, build, load, verify
from mospi.paths import REPO_ROOT

from .conftest import SECRET, auth, seed_postgres

pytestmark = pytest.mark.postgres
DEMO = REPO_ROOT / "data" / "demo"
DEMO_RUN = "2024_first_visit_demo"
PLATFORM_ROLES = ("anon", "authenticated", "service_role")


def _tables(pg) -> list[str]:
    return [r["relname"] for r in pg["admin"].fetch("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                                                    "WHERE n.nspname = %s AND c.relkind = 'r' ORDER BY 1", (pg["schema"],))]


def _objects(pg) -> list[str]:
    return [r["relname"] for r in pg["admin"].fetch("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                                                    "WHERE n.nspname = %s AND c.relkind IN ('r', 'v') ORDER BY 1", (pg["schema"],))]


@pytest.fixture()
def demo(pg, tmp_path):
    """The synthetic demo run registered as SYNTHETIC + hosted, its serving set built and loaded."""
    project = tmp_path / "demo"
    shutil.copytree(DEMO, project)
    register_existing(pg["admin"], project / "fusion" / "runs", project, data_class="SYNTHETIC", hosted=True)
    files = build(DEMO_RUN, tmp_path / "built", project=project)
    result = load(pg["admin"], DEMO_RUN, files, actor="tests", log=lambda *_: None)
    return {"project": project, "files": files, "result": result}


# ------------------------------------------------------------------ pooler behaviour


def test_every_transaction_carries_its_own_schema_timeout_and_read_only_mode(pg):
    """Behind a transaction pooler the session is shared, so the settings must hold per transaction, every time."""
    reader = pg["reader"]
    for _ in range(12):                      # more than psycopg's prepare threshold: no server-side prepared statement may appear
        row = reader.fetchone("SELECT current_setting('search_path') AS path, current_setting('transaction_read_only') AS ro, "
                              "current_setting('statement_timeout') AS timeout")
        assert row["path"] == pg["schema"] and row["ro"] == "on" and row["timeout"] != "0"
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        reader.execute("CREATE TEMP TABLE should_fail (a int)")
    assert reader.ping()["ssl"] is True and reader.ping()["role"] == "mospi_reader"


# ------------------------------------------------------------------ Supabase hardening


def test_row_level_security_is_on_for_every_table(pg):
    rows = pg["admin"].fetch("SELECT c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                             "WHERE n.nspname = %s AND c.relkind = 'r'", (pg["schema"],))
    assert rows and all(r["relrowsecurity"] for r in rows), [r["relname"] for r in rows if not r["relrowsecurity"]]
    policies = {r["policyname"] for r in pg["admin"].fetch("SELECT policyname FROM pg_policies WHERE schemaname = %s", (pg["schema"],))}
    assert policies in ({"mospi_app_access"}, {"mospi_app_access", "mospi_reviewer_read", "mospi_reviewer_insert"})   # reviewer policies exist with the role


def test_platform_roles_and_public_can_read_nothing(pg, demo):
    present = [r["rolname"] for r in pg["admin"].fetch("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (list(PLATFORM_ROLES),))]
    if not present:
        pytest.skip("not a Supabase database (no anon/authenticated roles)")
    for role in present:
        assert not pg["admin"].fetchone("SELECT has_schema_privilege(%s, %s, 'USAGE') AS u", (role, pg["schema"]))["u"]
        for name in _objects(pg):
            assert not pg["admin"].fetchone("SELECT has_table_privilege(%s, %s, 'SELECT') AS s", (role, f'{pg["schema"]}.{name}'))["s"], (role, name)
        # And in practice: as that role, every object is refused.
        for name in ("hosted_serving_chunks", "serving_chunks", "audit_events", "runs"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), pg["admin"].transaction() as connection:
                connection.execute(f"SET LOCAL ROLE {role}")
                connection.execute(f'SELECT 1 FROM "{pg["schema"]}"."{name}" LIMIT 1')
    assert pg["admin"].fetch("SELECT 1 FROM information_schema.role_table_grants WHERE table_schema = %s AND grantee = 'PUBLIC'", (pg["schema"],)) == []


def test_reader_sees_only_the_hosted_views_and_never_a_base_table(pg, demo):
    reader = pg["reader"]
    for table in _tables(pg):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.fetch(f'SELECT 1 FROM "{table}" LIMIT 1')
    assert {r["run_id"] for r in reader.fetch("SELECT run_id FROM hosted_serving_files")} == {DEMO_RUN}
    assert reader.fetchone("SELECT version FROM hosted_schema_version")["version"] == "0005_users"


# ------------------------------------------------------------------ the hosted serving set


def test_serving_set_is_verified_in_the_database_and_a_second_load_uploads_nothing(pg, demo):
    first = demo["result"]
    assert first["verification"]["status"] == "VERIFIED" and len(first["uploaded"]) == len(demo["files"])
    assert all(f.rows == f.source_rows for f in demo["files"] if f.rows is not None)
    again = load(pg["admin"], DEMO_RUN, demo["files"], actor="tests", log=lambda *_: None)
    assert again["uploaded"] == [] and again["removed"] == [] and len(again["unchanged"]) == len(demo["files"])
    assert verify(pg["admin"], DEMO_RUN, demo["files"])["status"] == "VERIFIED"
    events = pg["admin"].fetch("SELECT event_type FROM audit_events WHERE run_id = '__operations__' AND event_type = 'SERVING_SET_LOADED'")
    assert len(events) == 1                  # the unchanged second load records nothing


def test_serving_files_need_a_registered_run_and_hidden_runs_stay_invisible(pg, demo):
    with pytest.raises(psycopg.errors.RaiseException, match="not registered"):
        pg["admin"].execute("""INSERT INTO serving_files (run_id, path, stage, bytes, sha256, chunks, source_path, source_bytes, source_sha256, transform, loaded_by)
                               VALUES ('nope', 'fusion/runs/nope/x.json', 'fusion', 0, %s, 0, 'x', 0, %s, 'copy', 't')""", ("0" * 64, "0" * 64))
    pg["admin"].execute("UPDATE runs SET hosted_visible = FALSE WHERE run_id = %s", (DEMO_RUN,))
    assert pg["reader"].fetch("SELECT run_id FROM hosted_serving_files") == [] and pg["reader"].fetch("SELECT seq FROM hosted_serving_chunks") == []


def test_tampered_bytes_are_caught_in_the_database_and_never_served(pg, demo, tmp_path):
    path = next(f.path for f in demo["files"] if f.path.endswith("fused_cases.parquet"))
    pg["admin"].execute("UPDATE serving_chunks SET data = data || '\\x00'::bytea WHERE run_id = %s AND path = %s AND seq = 0", (DEMO_RUN, path))
    report = verify(pg["admin"], DEMO_RUN)
    assert report["status"] == "FAILED" and any(path in p for p in report["problems"])
    hosted = HostedServingData(pg["reader"], tmp_path / "serving")
    with pytest.raises(ServingError):
        hosted.ensure()
    assert not (tmp_path / "serving" / path).exists() and not list((tmp_path / "serving").rglob("*.partial"))


def _hosted_client(pg, monkeypatch, tmp_path, url: str | None = None, review_url: str | None = None) -> TestClient:
    monkeypatch.setenv("MOSPI_AUDIT_BACKEND", "postgres")
    monkeypatch.setenv("MOSPI_DATABASE_URL", url or pg["urls"]["reader"])
    monkeypatch.setenv("MOSPI_SERVING_DIR", str(tmp_path / "hosted-tmp"))
    monkeypatch.setenv("MOSPI_SESSION_SECRET", SECRET)
    if not pg["admin"].fetchone("SELECT count(*) AS n FROM app_users")["n"]:
        seed_postgres(pg["admin"])
    if review_url:
        monkeypatch.setenv("MOSPI_REVIEW_DATABASE_URL", review_url)
    else:
        monkeypatch.delenv("MOSPI_REVIEW_DATABASE_URL", raising=False)
    import mospi.db.connection as connection
    monkeypatch.setattr(connection, "_SHARED", {})
    import mospi.app.vercel_app as module
    return TestClient(importlib.reload(module).app)


def test_hosted_app_serves_the_same_pages_from_the_database_as_the_local_files(pg, demo, monkeypatch, tmp_path):
    from mospi.app.api import create_app
    client = _hosted_client(pg, monkeypatch, tmp_path)
    health = client.get("/healthz").json()
    assert health["status"] == "ok" and health["database"]["schema_version"] == "0005_users" and health["review_data"]["loaded"] is False
    assert client.get("/api/runs").status_code == 401                               # nothing is fetched before sign-in
    assert not list((tmp_path / "hosted-tmp").rglob("*.parquet"))
    hosted = {path: client.get(path, headers=auth("supervisor")).json()
              for path in ("/api/overview", "/api/cases?limit=20", "/api/groups?limit=10", "/api/worklist")}
    local = TestClient(create_app(demo["project"] / "fusion" / "runs", demo["project"], review_only=True, audit_read_only=True))
    for path, body in hosted.items():
        expected = local.get(path).json()
        for key in ("review", "metadata"):
            body.pop(key, None), expected.pop(key, None)
        assert body == expected, path
    case = hosted["/api/cases?limit=20"]["rows"][0]["case_id"]
    detail = client.get(f"/api/cases/{case}", headers=auth("supervisor")).json()
    assert detail["story"] == local.get(f"/api/cases/{case}").json()["story"]
    assert client.get("/api/audit/verify", headers=auth("supervisor")).status_code == 200
    assert client.post(f"/api/cases/{case}/events", headers=auth("admin"), json={"event_type": "CASE_VIEWED"}).status_code == 503
    assert client.post("/api/batch", headers=auth("admin"), json={"release": "2024", "label": "x"}).status_code == 403
    assert client.get("/healthz").json()["review_data"]["loaded"] is True
    for item in demo["files"]:                                                       # byte-identical to what was loaded
        assert hashlib.sha256((tmp_path / "hosted-tmp" / item.path).read_bytes()).hexdigest() == item.sha256


def test_hosted_app_refuses_plainly_when_the_database_is_unreachable(pg, monkeypatch, tmp_path):
    from psycopg.conninfo import make_conninfo
    # An unreachable address, not a wrong password: Supabase bans an IP address after repeated failed logins.
    client = _hosted_client(pg, monkeypatch, tmp_path, make_conninfo(pg["urls"]["reader"], host="127.0.0.1", port="1", password="wrong-password-for-tests"))
    response = client.get("/api/overview", headers=auth("supervisor"))
    assert response.status_code == 503 and response.json()["database_unavailable"] is True
    text = response.text.lower()
    assert "wrong-password" not in text and "127.0.0.1" not in text and "cannot be reached" in text
    assert client.get("/healthz").status_code == 503 and client.get("/healthz").json()["database"] == {"reachable": False}


# ------------------------------------------------------------------ hosted decisions (insert-only mospi_reviewer role)


DECISION = {"event_type": "DECISION_MADE", "decision": "CONFIRMED_ERROR", "reason_code": "EXTRA_OR_MISSING_ZERO", "verification_source": "PHONE_CALL",
            "comment": "hosted reviewer note", "expected_last_decision_id": None}


@pytest.fixture()
def reviewer_url(pg):
    """URL of the mospi_reviewer login.  The role is created by ``python -m mospi.db.migrate --roles`` with
    MOSPI_DB_REVIEWER_PASSWORD set; without the role and its password these tests are skipped (never guessed)."""
    import os
    from psycopg.conninfo import make_conninfo
    if not pg["admin"].fetchone("SELECT 1 FROM pg_roles WHERE rolname = 'mospi_reviewer'") or not (
            os.environ.get("MOSPI_REVIEW_DATABASE_URL") or os.environ.get("MOSPI_DB_REVIEWER_PASSWORD")):
        pytest.skip("the mospi_reviewer role and its URL or password are needed")
    return os.environ.get("MOSPI_REVIEW_DATABASE_URL") or make_conninfo(pg["urls"]["app"], user="mospi_reviewer", password=os.environ["MOSPI_DB_REVIEWER_PASSWORD"])


def _raw_insert(db, run_id: str, event_type: str, *, event_id: int = 900, authenticated: int = 1, chained: bool = True) -> None:
    db.execute("INSERT INTO audit_events (run_id, event_id, case_id, event_type, actor, event_timestamp_utc, actor_authenticated, previous_hash, event_hash) "
               "VALUES (%s, %s, 'c1', %s, 'role test', now()::text, %s, %s, %s)",
               (run_id, event_id, event_type, authenticated, "p" if chained else None, f"h{event_id}" if chained else None))


def test_reviewer_role_can_append_review_events_and_nothing_else(pg, demo, reviewer_url):
    reviewer = Database(reviewer_url, schema=pg["schema"])
    try:
        _raw_insert(reviewer, DEMO_RUN, "CASE_VIEWED")                                  # the one thing it may do
        refused = ["UPDATE audit_events SET actor = 'x'", "DELETE FROM audit_events", "TRUNCATE audit_events",
                   "SELECT comment FROM audit_events", "SELECT evidence_snapshot_json FROM audit_events", "SELECT corrected_value FROM audit_events",
                   "SELECT 1 FROM runs", "SELECT 1 FROM jobs", "SELECT 1 FROM hosted_serving_files", "INSERT INTO runs (run_id) VALUES ('x')",
                   "INSERT INTO audit_verifications (run_id, status, checked_by) VALUES ('x', 'INTACT', 'x')"]
        for statement in refused:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                reviewer.execute(statement)
        # Row level security: no operations trail, no other event types, no unchained or unsigned rows, no run outside hosting.
        pg["admin"].execute("INSERT INTO runs (run_id, release, observation, status, data_class) VALUES ('hidden_run', '2024', 'first_visit', 'REGISTERED', 'SYNTHETIC')")
        for run_id, event_type, options in (("__operations__", "DECISION_MADE", {}), (DEMO_RUN, "RUN_PUBLISHED", {}), (DEMO_RUN, "EXPORT", {}),
                                            (DEMO_RUN, "DECISION_MADE", {"authenticated": 0}), (DEMO_RUN, "DECISION_MADE", {"chained": False}),
                                            ("hidden_run", "DECISION_MADE", {})):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                _raw_insert(reviewer, run_id, event_type, event_id=901, **options)
        assert reviewer.fetchone("SELECT COUNT(*) AS n FROM audit_events WHERE run_id = '__operations__'")["n"] == 0
        assert pg["admin"].fetchone("SELECT COUNT(*) AS n FROM audit_events WHERE run_id = '__operations__'")["n"] > 0   # it exists, unseen
        assert [r["event_type"] for r in pg["admin"].fetch("SELECT event_type FROM audit_events WHERE run_id = %s", (DEMO_RUN,))] == ["CASE_VIEWED"]
    finally:
        reviewer.close()


def test_reviewer_grants_and_policies_are_idempotent(pg, reviewer_url):
    from mospi.db.migrate import REVIEWER_COLUMNS, apply_grants

    def privileges():
        columns = pg["admin"].fetch("SELECT column_name FROM information_schema.column_privileges WHERE grantee = 'mospi_reviewer' "
                                    "AND table_schema = %s AND table_name = 'audit_events' AND privilege_type = 'SELECT' ORDER BY 1", (pg["schema"],))
        tables = pg["admin"].fetch("SELECT table_name, privilege_type FROM information_schema.role_table_grants WHERE grantee = 'mospi_reviewer' "
                                   "AND table_schema = %s ORDER BY 1, 2", (pg["schema"],))
        policies = pg["admin"].fetch("SELECT policyname, cmd FROM pg_policies WHERE schemaname = %s AND 'mospi_reviewer' = ANY(roles) ORDER BY 1", (pg["schema"],))
        return [r["column_name"] for r in columns], [(r["table_name"], r["privilege_type"]) for r in tables], [(r["policyname"], r["cmd"]) for r in policies]

    before = privileges()
    apply_grants(pg["admin"])
    apply_grants(pg["admin"])
    assert privileges() == before
    columns, tables, policies = before
    assert columns == sorted(REVIEWER_COLUMNS)
    assert tables == [("audit_events", "INSERT"), ("hosted_runs", "SELECT")]
    assert policies == [("mospi_reviewer_insert", "INSERT"), ("mospi_reviewer_read", "SELECT")]


def test_hosted_app_records_a_decision_in_the_chain_and_shows_it_back(pg, demo, reviewer_url, monkeypatch, tmp_path):
    from mospi.db.audit import PostgresAuditStore
    client = _hosted_client(pg, monkeypatch, tmp_path, review_url=reviewer_url)
    assert client.get("/healthz").json()["audit_store"] == "append-only"
    deployment = client.get("/api/deployment", headers=auth("supervisor")).json()
    assert deployment["audit_writable"] is True and deployment["exports"] is False and deployment["notes_shown"] is False
    case = client.get("/api/cases?limit=1", headers=auth("supervisor")).json()["rows"][0]["case_id"]
    assert client.post(f"/api/cases/{case}/events", headers=auth("analyst"), json=DECISION).status_code == 403    # role still checked
    assert client.post(f"/api/cases/{case}/events", headers=auth("supervisor"), json={"event_type": "CASE_VIEWED"}).status_code == 200
    saved = client.post(f"/api/cases/{case}/events", headers=auth("supervisor"), json={**DECISION, "actor": "typed name"})
    assert saved.status_code == 200 and saved.json()["actor"] == "Test supervisor"                                   # the signed-in name
    again = client.post(f"/api/cases/{case}/events", headers=auth("admin"), json=DECISION)
    assert again.status_code == 409                                                                                  # stale decision refused
    history = client.get(f"/api/cases/{case}", headers=auth("supervisor")).json()["audit_history"]
    assert [h["event_type"] for h in history] == ["CASE_VIEWED", "DECISION_MADE"] and history[1]["decision"] == "CONFIRMED_ERROR"
    assert "hosted reviewer note" not in json.dumps(history)                                                         # notes stay off the hosted views
    assert pg["admin"].fetchone("SELECT comment FROM audit_events WHERE run_id = %s AND event_type = 'DECISION_MADE'", (DEMO_RUN,))["comment"] == "hosted reviewer note"
    events = pg["admin"].fetch("SELECT event_type, actor_role, origin FROM audit_events WHERE run_id = %s ORDER BY event_id", (DEMO_RUN,))
    assert [e["event_type"] for e in events] == ["AUDIT_CHAIN_STARTED", "CASE_VIEWED", "DECISION_MADE"]
    assert PostgresAuditStore(pg["app"]).verify(DEMO_RUN)["status"] == "INTACT"                                      # chain unbroken
    for role in ("admin", "supervisor"):
        assert client.get("/api/export/queue", headers=auth(role)).status_code == 503
    assert pg["admin"].fetchone("SELECT COUNT(*) AS n FROM audit_events WHERE event_type = 'EXPORT'")["n"] == 0


def test_hosted_app_without_the_reviewer_url_stays_read_only(pg, demo, monkeypatch, tmp_path):
    client = _hosted_client(pg, monkeypatch, tmp_path)
    assert client.get("/healthz").json()["audit_store"] == "read-only"
    assert client.get("/api/deployment", headers=auth("supervisor")).json()["audit_writable"] is False
    case = client.get("/api/cases?limit=1", headers=auth("supervisor")).json()["rows"][0]["case_id"]
    response = client.post(f"/api/cases/{case}/events", headers=auth("supervisor"), json=DECISION)
    assert response.status_code == 503 and response.json()["detail"].startswith("Decisions are recorded on the processing machine")
    assert pg["admin"].fetchone("SELECT COUNT(*) AS n FROM audit_events WHERE run_id = %s", (DEMO_RUN,))["n"] == 0


def test_two_concurrent_hosted_decisions_leave_one_saved_and_one_conflict(pg, demo, reviewer_url):
    import threading
    from mospi.db.audit import PostgresAuditStore
    from mospi.pipeline.stages.fusion.review import DecisionConflict
    reviewer = Database(reviewer_url, schema=pg["schema"])
    stores = [PostgresAuditStore(pg["reader"], hosted=True, writer=reviewer) for _ in range(2)]
    stores[0].append(DEMO_RUN, case_id="c1", event_type="CASE_VIEWED", actor="warm-up", actor_authenticated=True, actor_role="supervisor")
    barrier, outcomes = threading.Barrier(2), []

    def decide(store, name):
        barrier.wait()
        try:
            store.append(DEMO_RUN, case_id="c1", event_type="DECISION_MADE", actor=name, decision="CONFIRMED_ERROR", reason_code="EXTRA_OR_MISSING_ZERO",
                         verification_source="PHONE_CALL", actor_authenticated=True, actor_role="supervisor", expected_last_decision_id=None)
            outcomes.append("saved")
        except DecisionConflict:
            outcomes.append("conflict")

    try:
        threads = [threading.Thread(target=decide, args=(store, f"reviewer {i}")) for i, store in enumerate(stores)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert sorted(outcomes) == ["conflict", "saved"]
        assert pg["admin"].fetchone("SELECT COUNT(*) AS n FROM audit_events WHERE run_id = %s AND event_type = 'DECISION_MADE'", (DEMO_RUN,))["n"] == 1
        assert PostgresAuditStore(pg["app"]).verify(DEMO_RUN)["status"] == "INTACT"
    finally:
        reviewer.close()


def test_hosted_writer_leaves_sealing_earlier_history_to_the_processing_machine(pg, demo, reviewer_url):
    from mospi.db.audit import PostgresAuditStore
    pg["admin"].execute("INSERT INTO audit_events (run_id, event_id, case_id, event_type, actor, event_timestamp_utc, comment) "
                        "VALUES (%s, 1, 'c1', 'DECISION_MADE', 'legacy', now()::text, 'legacy note')", (DEMO_RUN,))
    reviewer = Database(reviewer_url, schema=pg["schema"])
    try:
        with pytest.raises(PermissionError, match="processing machine"):
            PostgresAuditStore(pg["reader"], hosted=True, writer=reviewer).append(DEMO_RUN, case_id="c1", event_type="CASE_VIEWED", actor="x",
                                                                                   actor_authenticated=True, actor_role="supervisor")
        assert pg["admin"].fetchone("SELECT COUNT(*) AS n FROM audit_events WHERE run_id = %s", (DEMO_RUN,))["n"] == 1
    finally:
        reviewer.close()


# ------------------------------------------------------------------ hosting approval


def test_approved_real_needs_a_named_approver_and_is_recorded_in_the_chained_trail(pg, tmp_path):
    from mospi.db.audit import PostgresAuditStore
    project = tmp_path / "demo"
    shutil.copytree(DEMO, project)
    with pytest.raises(ValueError, match="approver"):
        register_existing(pg["admin"], project / "fusion" / "runs", project, data_class="APPROVED_REAL", hosted=True, approval="ref-1")
    with pytest.raises(ValueError, match="SYNTHETIC or APPROVED_REAL"):
        register_existing(pg["admin"], project / "fusion" / "runs", project, data_class="INTERNAL_REAL", hosted=True)
    register_existing(pg["admin"], project / "fusion" / "runs", project, data_class="APPROVED_REAL", hosted=True, approval="ref-1",
                      approver="Test Approver", approver_role="Test role", runs=[DEMO_RUN])
    event = pg["admin"].fetchone("SELECT actor, case_id, comment FROM audit_events WHERE run_id = '__operations__' AND event_type = 'HOSTING_APPROVED'")
    details = json.loads(event["comment"])
    assert event["actor"] == "Test Approver" and event["case_id"] == DEMO_RUN
    assert details["reference"] == "ref-1" and details["approver_role"] == "Test role" and details["run_label"] == DEMO_RUN and details["approved_utc"]
    manifest = pg["admin"].fetchone("SELECT manifest FROM runs WHERE run_id = %s", (DEMO_RUN,))["manifest"]
    assert manifest["hosted_approval"]["approver"] == "Test Approver"
    assert PostgresAuditStore(pg["admin"]).verify("__operations__")["status"] == "INTACT"
