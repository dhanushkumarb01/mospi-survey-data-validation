"""PostgreSQL foundation: migrations, least privilege, guards, the audit store, the SQLite migration and backups."""
from __future__ import annotations

import itertools
import json
import shutil
import sqlite3
import threading
from pathlib import Path

import psycopg
import pytest

from mospi.db.audit import PostgresAuditStore, SqliteAuditStore
from mospi.db.connection import DatabaseUnavailable, redact
from mospi.db.migrate import MigrationError, apply, status
from mospi.db.migrate_audit import migrate_all, sha256_file
from mospi.pipeline.stages.fusion import review
from mospi.pipeline.stages.fusion.review import DecisionConflict, verify_chain

pytestmark = pytest.mark.postgres
DECISION = {"event_type": "DECISION_MADE", "decision": "VALID_BUT_UNUSUAL", "reason_code": "GENUINE_HIGH_OR_LOW_VALUE", "verification_source": "PHONE_CALL"}


# ------------------------------------------------------------------ migrations and privileges


def test_migrations_are_recorded_and_a_second_run_applies_nothing(pg):
    assert apply(pg["admin"]) == []
    state = status(pg["admin"])
    assert state["pending"] == [] and state["changed"] == [] and len(state["applied"]) == 5
    pg["admin"].execute("UPDATE schema_migrations SET checksum = 'edited' WHERE version = '0001_audit'")
    with pytest.raises(MigrationError, match="changed after it was applied"):
        apply(pg["admin"])


def test_application_role_cannot_rewrite_the_audit_trail_and_reader_sees_views_only(pg):
    store = PostgresAuditStore(pg["app"])
    store.append("run_a", case_id="c1", actor="r", **{k: v for k, v in DECISION.items()})
    for sql in ("UPDATE audit_events SET actor = 'x'", "DELETE FROM audit_events", "TRUNCATE audit_events"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            pg["app"].execute(sql)
    for sql in ("SELECT * FROM audit_events", "SELECT * FROM datasets", "SELECT * FROM jobs", "SELECT * FROM notifications"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            pg["reader"].fetch(sql)
    assert pg["reader"].fetch("SELECT * FROM hosted_runs") == []
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        pg["reader"].execute("CREATE TEMP TABLE x (a int)")
    # Even the owner cannot change an event: the trigger refuses it.
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        pg["admin"].execute("UPDATE audit_events SET actor = 'x'")


def test_finished_jobs_and_published_runs_cannot_be_rewritten(pg):
    db = pg["app"]
    db.execute("INSERT INTO jobs (job_id, kind, status, trigger, requested_by) VALUES (%s, 'INTEGRITY_CHECK', 'FAILED', 'MANUAL', 't')", ("a" * 32,))
    with pytest.raises(psycopg.errors.RaiseException, match="finished"):
        db.execute("UPDATE jobs SET status = 'SUCCEEDED' WHERE job_id = %s", ("a" * 32,))
    db.execute("INSERT INTO runs (run_id, status, data_class, manifest_sha256) VALUES ('r1', 'PUBLISHED', 'INTERNAL_REAL', 'abc')")
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute("UPDATE runs SET status = 'PENDING' WHERE run_id = 'r1'")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("INSERT INTO runs (run_id, status, data_class, hosted_visible) VALUES ('r2', 'REGISTERED', 'INTERNAL_REAL', TRUE)")


def test_connection_errors_never_reveal_the_password(pg):
    from psycopg.conninfo import make_conninfo
    from mospi.db.connection import Database
    # Unreachable rather than a wrong password: Supabase bans an IP address after repeated failed logins.
    bad = Database(make_conninfo(pg["urls"]["app"], password="wrong-password-123", host="127.0.0.1", port="1"), schema=pg["schema"])
    with pytest.raises(DatabaseUnavailable) as caught:
        bad.ping()
    assert "wrong-password-123" not in str(caught.value) and "wrong-password-123" not in repr(bad)
    assert redact("postgresql://u:secret@h/db") == "postgresql://u:***@h/db" and "secret" not in redact("password=secret host=h")


# ------------------------------------------------------------------ the audit store


def _clock(monkeypatch):
    """A deterministic clock for both stores (the hash covers the timestamp)."""
    import mospi.db.audit as audit_module
    ticks = itertools.count()
    now = lambda: f"2026-10-11T10:00:{next(ticks) % 60:02d}.000001+00:00"   # noqa: E731
    monkeypatch.setattr(review, "_now", now)
    monkeypatch.setattr(audit_module, "_now", now)


def _events():
    yield {"case_id": "c1", "event_type": "CASE_VIEWED", "actor": "Ana", "opened_at_utc": None}
    yield {"case_id": "c1", "actor": "Ana", "comment": "unicode ✓ “quotes” é", "evidence_snapshot": {"value": 1e-300, "list": [1, None, "x"]}, **DECISION}
    yield {"case_id": "c2", "actor": "Bo", "decision": "CONFIRMED_ERROR", "reason_code": "WRONG_CODE", "verification_source": "FIELD_REVISIT",
           "event_type": "DECISION_MADE", "corrected_field": "age", "corrected_value": "", "comment": "x" * 2000, "actor_authenticated": True, "actor_role": "admin"}
    yield {"case_id": "*", "event_type": "EXPORT", "actor": "Bo", "comment": json.dumps({"filters": {}})}


def test_postgres_and_sqlite_produce_byte_identical_hash_chains(pg, tmp_path, monkeypatch):
    pg_store, sqlite_store = PostgresAuditStore(pg["app"]), SqliteAuditStore()
    run = tmp_path / "run_x"
    run.mkdir()
    _clock(monkeypatch)
    for event in _events():
        pg_store.append(run, **event)
    _clock(monkeypatch)                    # same timestamps again for the original SQLite code
    for event in _events():
        sqlite_store.append(run, **event)
    with sqlite3.connect(run / "review_audit.sqlite") as connection:
        sqlite_hashes = [r[0] for r in connection.execute("SELECT event_hash FROM audit_events ORDER BY event_id")]
    assert len(sqlite_hashes) == 5 and [r["event_hash"] for r in pg_store.rows("run_x")] == sqlite_hashes
    assert pg_store.verify("run_x") == verify_chain(run / "review_audit.sqlite")
    assert pg_store.latest_statuses("run_x") == sqlite_store.latest_statuses(run)
    assert [e["comment"] for e in pg_store.all_events("run_x")] == [e["comment"] for e in sqlite_store.all_events(run)]


def test_concurrent_appends_keep_one_intact_chain_and_one_decision_wins(pg):
    store, errors = PostgresAuditStore(pg["app"]), []

    def write(worker: int) -> None:
        try:
            for k in range(8):
                store.append("run_c", case_id=f"case_{worker}_{k}", actor=f"r{worker}", **DECISION)
        except BaseException as error:   # noqa: BLE001
            errors.append(error)
    threads = [threading.Thread(target=write, args=(w,)) for w in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    result = store.verify("run_c")
    assert result["status"] == "INTACT" and result["events"] == 4 * 8 + 1
    outcomes = []

    def decide() -> None:
        try:
            store.append("run_c", case_id="contested", actor="r", expected_last_decision_id=None, **DECISION)
            outcomes.append("saved")
        except DecisionConflict:
            outcomes.append("conflict")
    threads = [threading.Thread(target=decide) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(outcomes) == ["conflict"] * 3 + ["saved"]
    assert store.verify("run_c")["status"] == "INTACT"


def test_tampering_by_the_owner_is_detected(pg):
    store = PostgresAuditStore(pg["app"])
    for case in ("a", "b", "c"):
        store.append("run_t", case_id=case, actor="r", **DECISION)
    with pg["admin"].transaction() as connection:
        connection.execute("ALTER TABLE audit_events DISABLE TRIGGER audit_no_update")
        connection.execute("UPDATE audit_events SET decision = 'CONFIRMED_ERROR' WHERE run_id = 'run_t' AND case_id = 'b'")
        connection.execute("ALTER TABLE audit_events ENABLE TRIGGER audit_no_update")
    result = store.verify("run_t")
    assert result["status"] == "BROKEN" and result["first_bad_event_id"] == 3


def test_hosted_reader_sees_only_cleared_runs_and_no_comments_or_snapshots(pg):
    store = PostgresAuditStore(pg["app"])
    store.append("synthetic_run", case_id="c1", actor="r", comment="private note", evidence_snapshot={"salary": 123456}, **DECISION)
    store.append("real_run", case_id="c1", actor="r", **DECISION)
    pg["admin"].execute("INSERT INTO runs (run_id, status, data_class, hosted_visible) VALUES ('synthetic_run', 'REGISTERED', 'SYNTHETIC', TRUE), "
                        "('real_run', 'REGISTERED', 'INTERNAL_REAL', FALSE)")
    store.verify("synthetic_run", record_as="tests")
    hosted = PostgresAuditStore(pg["reader"], hosted=True)
    history = hosted.history("synthetic_run", "c1")
    assert len(history) == 1 and "comment" not in history[0] and "evidence_snapshot_json" not in history[0] and history[0]["decision"] == "VALID_BUT_UNUSUAL"
    assert "123456" not in json.dumps(history)
    assert hosted.history("real_run", "c1") == [] and hosted.latest_statuses("real_run") == {}
    assert hosted.verify("synthetic_run")["status"] == "INTACT" and hosted.verify("synthetic_run")["verified_on"] == "processing machine"
    with pytest.raises(PermissionError):
        hosted.append("synthetic_run", case_id="c2", actor="r", **DECISION)


# ------------------------------------------------------------------ SQLite -> PostgreSQL migration


def _legacy_store(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE audit_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, event_type TEXT NOT NULL, "
                           "actor TEXT NOT NULL, event_timestamp_utc TEXT NOT NULL, decision TEXT, comment TEXT, evidence_snapshot_json TEXT)")
        connection.execute("INSERT INTO audit_events (case_id, event_type, actor, event_timestamp_utc, decision) VALUES "
                           "('c1', 'DECISION_MADE', 'old', '2026-01-01T00:00:00+00:00', 'CONFIRMED_VALID'), ('c2', 'CASE_VIEWED', 'old', '2026-01-02T00:00:00+00:00', NULL)")


def _data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    _legacy_store(root / "fusion" / "runs" / "legacy_run" / "review_audit.sqlite")
    chained = root / "fusion" / "runs" / "chained_run" / "review_audit.sqlite"
    chained.parent.mkdir(parents=True)
    for case in ("a", "b"):
        review.append_event(chained, case_id=case, actor="r", **DECISION)
    mixed = root / "fusion" / "runs" / "mixed_run" / "review_audit.sqlite"
    _legacy_store(mixed)
    review.append_event(mixed, case_id="c3", actor="r", **DECISION)       # seals the legacy rows, then chains
    review.append_event(root / "evaluation" / "runs" / "p1" / "fusion" / "runs" / "eval_run" / "review_audit.sqlite", case_id="e", actor="r", **DECISION) \
        if (root / "evaluation" / "runs" / "p1" / "fusion" / "runs" / "eval_run").mkdir(parents=True) is None else None
    return root


def test_migration_copies_every_store_verbatim_is_idempotent_and_leaves_sources_unchanged(pg, tmp_path):
    root = _data_root(tmp_path)
    sources = {p: sha256_file(p) for p in root.rglob("review_audit.sqlite")}
    reports = {r["run_id"]: r for r in migrate_all(pg["admin"], root, backup_dir=tmp_path / "backups")}
    assert {r["outcome"] for r in reports.values()} == {"MIGRATED"} and len(reports) == 4
    assert reports["chained_run"]["destination_last_hash"] == verify_chain(root / "fusion/runs/chained_run/review_audit.sqlite")["last_hash"]
    assert reports["mixed_run"]["destination_last_hash"] == verify_chain(root / "fusion/runs/mixed_run/review_audit.sqlite")["last_hash"]
    assert reports["legacy_run"]["chain_start_added"] and reports["legacy_run"]["destination_events"] == 3
    assert "evaluation/p1/fusion/runs/eval_run" in reports
    store = PostgresAuditStore(pg["app"])
    assert store.latest_statuses("legacy_run") == {"c1": "VALID_BUT_UNUSUAL"}          # legacy alias still mapped at read time
    for key in reports:
        assert store.verify(key)["status"] == "INTACT"
    again = migrate_all(pg["admin"], root, backup_dir=tmp_path / "backups")
    assert {r["outcome"] for r in again} == {"ALREADY_MIGRATED"}
    assert pg["admin"].fetchone("SELECT COUNT(*) AS n FROM audit_events WHERE origin = 'sqlite_migration'")["n"] == 2 + 3 + 4 + 2   # legacy, chained, mixed, evaluation (with their chain starts)
    assert all(sha256_file(p) == digest for p, digest in sources.items())
    assert len(list((tmp_path / "backups").rglob("review_audit.sqlite"))) == 8 and list((tmp_path / "backups").rglob("SHA256SUMS"))


def test_broken_or_conflicting_stores_are_refused_and_nothing_partial_is_committed(pg, tmp_path):
    root = _data_root(tmp_path)
    broken = root / "fusion/runs/chained_run/review_audit.sqlite"
    with sqlite3.connect(broken) as connection:
        connection.execute("DROP TRIGGER audit_no_update")
        connection.execute("UPDATE audit_events SET actor = 'forged' WHERE event_id = 2")
    # A conflicting row already in PostgreSQL for another run: that store must roll back completely.
    pg["admin"].execute("INSERT INTO audit_events (run_id, event_id, case_id, event_type, actor, event_timestamp_utc) "
                        "VALUES ('legacy_run', 1, 'c1', 'DECISION_MADE', 'someone else', '2026-01-01T00:00:00+00:00')")
    reports = {r["run_id"]: r for r in migrate_all(pg["admin"], root, backup_dir=tmp_path / "b")}
    assert reports["chained_run"]["outcome"] == "REFUSED" and "BROKEN" in reports["chained_run"]["detail"]
    assert reports["legacy_run"]["outcome"] == "FAILED" and "different content" in reports["legacy_run"]["detail"]
    assert reports["mixed_run"]["outcome"] == "MIGRATED"
    counts = {r["run_id"]: r["n"] for r in pg["admin"].fetch("SELECT run_id, COUNT(*) AS n FROM audit_events GROUP BY 1")}
    assert counts.get("chained_run") is None and counts["legacy_run"] == 1        # only the pre-existing row; nothing half-written
    assert pg["admin"].fetchone("SELECT COUNT(*) AS n FROM audit_migrations WHERE run_id IN ('chained_run', 'legacy_run')")["n"] == 0


def test_postgres_mode_refuses_to_start_while_review_history_is_unmigrated(pg, tmp_path):
    from mospi.app.backends import BackendError, startup_check
    root = _data_root(tmp_path)
    with pytest.raises(BackendError, match="never migrated"):
        startup_check(pg["app"], root / "fusion" / "runs")
    migrate_all(pg["admin"], root, backup_dir=tmp_path / "b")
    startup_check(pg["app"], root / "fusion" / "runs")
    review.append_event(root / "fusion/runs/chained_run/review_audit.sqlite", case_id="late", actor="r", **DECISION)   # written in SQLite mode later
    with pytest.raises(BackendError, match="changed after migration"):
        startup_check(pg["app"], root / "fusion" / "runs")


# ------------------------------------------------------------------ backup and restore drill


def test_backup_restores_into_a_new_database_with_identical_counts_and_chains(pg, tmp_path):
    from mospi.db.backup import create, restore, verify
    store = PostgresAuditStore(pg["app"])
    for case in ("a", "b"):
        store.append("run_b", case_id=case, actor="r", **DECISION)
    dump = create(pg["admin"], pg["urls"]["admin"], tmp_path)
    result = verify(dump, pg["urls"]["admin"])
    assert result["status"] == "VERIFIED", result["problems"]
    assert result["tables"]["audit_events"] == 3 and result["chains"] == 1
    with pytest.raises(RuntimeError, match="live database"):
        restore(dump, pg["urls"]["admin"], pg["admin"].fetchone("SELECT current_database() AS d")["d"])
    dump.write_bytes(dump.read_bytes() + b"x")
    with pytest.raises(RuntimeError, match="SHA-256"):
        verify(dump, pg["urls"]["admin"])
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_registering_runs_from_a_relative_path_records_data_root_relative_manifests(pg, tmp_path, monkeypatch):
    """Regression: a relative --fusion-root once produced stage-relative paths; the checker must pass either form."""
    from mospi.db.registry import register_existing
    from mospi.ingest.checks import check_run
    from mospi.ingest.settings import settings
    from tests.synthetic import write_delivery
    from mospi.pipeline.run import Inputs, run_pipeline
    root = tmp_path / "data"
    prepared, _ = write_delivery(root / "preprocessing" / "runs" / "2024_first_visit_synthetic-prep")     # <release>_<observation>_<run_id>
    run_pipeline(Inputs(prepared), "reg", roots=root)
    monkeypatch.chdir(tmp_path)
    rows = register_existing(pg["admin"], Path("data/fusion/runs"), Path("data").resolve(), data_class="SYNTHETIC")
    assert rows[0]["outcome"] == "registered" and not rows[0]["missing_sources"]
    manifest = pg["admin"].fetchone("SELECT manifest FROM runs")["manifest"]
    assert all(f["path"].startswith(f"{f['stage']}/runs/") for f in manifest["files"])
    row = dict(pg["admin"].fetchone("SELECT run_id, release, observation, manifest FROM runs"))
    assert {status for _, status, _ in check_run(row, [root], settings())} == {"PASSED"}
    legacy = {**row, "manifest": {**manifest, "files": [{**f, "path": f"{f['stage']}/{f['path'].split('/', 3)[3]}"} for f in manifest["files"]]}}
    assert {status for _, status, _ in check_run(legacy, [root], settings())} == {"PASSED"}


# ------------------------------------------------------------------ accounts (0005_users.sql)


def test_the_database_keeps_administrator_accounts_out_of_reach_of_the_runtime_roles(pg):
    from mospi.auth import AccountError, PostgresUserStore
    from mospi.auth.passwords import hash_password
    owner, app = PostgresUserStore(pg["admin"], origin="cli"), PostgresUserStore(pg["app"])
    hashed = hash_password("a long test passphrase")
    admin = owner.create(username="chief", display_name="Chief", role="admin", password_hash=hashed, created_by="tests", allow_admin=True)
    supervisor = app.create(username="sup.one", display_name="Sup One", role="supervisor", password_hash=hashed, created_by="Chief")
    for statement, values in (
            ("INSERT INTO app_users (username, display_name, role, password_hash, created_by) VALUES ('x.admin', 'X', 'admin', %s, 't')", (hashed,)),
            ("UPDATE app_users SET role = 'admin' WHERE user_id = %s", (supervisor["user_id"],)),
            ("UPDATE app_users SET active = false WHERE user_id = %s", (admin["user_id"],)),
            ("UPDATE app_users SET username = 'renamed' WHERE user_id = %s", (supervisor["user_id"],)),
            ("UPDATE app_users SET password_hash = 'plain text' WHERE user_id = %s", (supervisor["user_id"],)),
            ("DELETE FROM app_users WHERE user_id = %s", (supervisor["user_id"],)),
            ("UPDATE auth_events SET actor = 'someone else'", None)):
        with pytest.raises(psycopg.Error):
            pg["app"].execute(statement, values)
    # An administrator may still change their own password through the app role.
    assert app.change_password(admin["user_id"], hashed, hash_password("another long passphrase"))
    with pytest.raises(AccountError):
        app.update(admin["user_id"], actor="someone", active=False)
    # The reader sees no account table at all: only the two look-up functions, which never list accounts.
    with pytest.raises(psycopg.Error):
        pg["reader"].fetch("SELECT * FROM app_users")
    record = pg["reader"].fetchone("SELECT * FROM auth_login_record(%s)", ("  SUP.ONE ",))
    assert record["user_id"] == supervisor["user_id"] and record["password_hash"].startswith("scrypt$")
    assert "password_hash" not in pg["reader"].fetchone("SELECT * FROM auth_session_record(%s)", (supervisor["user_id"],))
    for function in ("SELECT auth_note_attempt('sup.one', true)", "SELECT auth_change_password(1, 'a', 'b')"):
        with pytest.raises(psycopg.Error):
            pg["reader"].fetch(function)                         # the reviewer's functions, not the reader's
