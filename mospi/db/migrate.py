"""Apply the numbered SQL migrations and the role grants (run by an operator with the admin connection).

    python -m mospi.db.migrate              # apply pending migrations, then (re)apply grants
    python -m mospi.db.migrate --roles      # also create/update the login roles (mospi_app, mospi_reader, optional mospi_reviewer)
    python -m mospi.db.migrate --status     # list applied and pending migrations; change nothing

Rules
* Each migration runs in its own transaction and is recorded in ``schema_migrations`` with its SHA-256.
  A second run applies nothing; an applied file whose content changed is refused (never re-applied).
* A transaction-scoped advisory lock serialises concurrent runners.
* Nothing here drops or rewrites data.  The web application never runs migrations at start-up.

Roles (least privilege; passwords from ``MOSPI_DB_APP_PASSWORD`` / ``MOSPI_DB_READER_PASSWORD`` / ``MOSPI_DB_REVIEWER_PASSWORD``):
* ``mospi_app``    local app and worker: INSERT/SELECT on the audit trail (no UPDATE/DELETE), read/write ledgers.
* ``mospi_reader`` hosted instance: SELECT on the ``hosted_*`` views only, read-only sessions, connection limit.
* ``mospi_reviewer`` hosted decisions (optional; created when ``MOSPI_DB_REVIEWER_PASSWORD`` is set): INSERT on
  ``audit_events``, SELECT on its id and hash columns only (never comments, snapshots or corrected values) and on
  ``hosted_runs``.  Row level security limits inserts to chained decision/case-view/chain-start events of hosted runs,
  outside the operations trail, by a signed-in actor.  No UPDATE, no DELETE, no other table: a hosted decision can be
  added but never changed or removed.
* Accounts (0005_users.sql): ``mospi_app`` reads and writes ``app_users`` (a trigger refuses any administrator change
  from it) and appends to ``auth_events``; the reader may only EXECUTE the two sign-in look-up functions, the reviewer
  the two that record a sign-in outcome and a password change.  Administrators come only from this admin connection.

Supabase hardening (applied with the grants, idempotent): row level security is enabled on every table of the schema,
with a policy for ``mospi_app`` and two narrow ones for ``mospi_reviewer`` (the views run as their owner, so the reader
sees rows only through them); every
privilege on the schema and its objects is revoked from PUBLIC and from Supabase's ``anon``/``authenticated``/
``service_role`` roles, including default privileges for future objects.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

from .config import load_env_file
from .connection import Database, DatabaseUnavailable

MIGRATIONS = Path(__file__).with_name("migrations")
APP_ROLE, READER_ROLE, REVIEWER_ROLE = "mospi_app", "mospi_reader", "mospi_reviewer"
REVIEWER_EVENTS = ("DECISION_MADE", "CASE_VIEWED", "AUDIT_CHAIN_STARTED")
# All the hosted writer reads: enough to find the chain head, the next event id and the latest decision on a case.
REVIEWER_COLUMNS = ("run_id", "event_id", "case_id", "event_type", "event_hash")
APP_WRITE = ("datasets", "dataset_files", "runs", "jobs", "notifications", "app_users")
APP_APPEND = ("audit_events", "audit_verifications", "job_events", "integrity_checks", "auth_events")
# Hosted sign-in (0005_users.sql): the reader looks accounts up, the optional reviewer records outcomes and password changes.
READER_FUNCTIONS = ("auth_login_record(text)", "auth_session_record(bigint)")
REVIEWER_FUNCTIONS = ("auth_note_attempt(text, boolean)", "auth_change_password(bigint, text, text)")
APP_READ = ("audit_migrations", "schema_migrations")
HOSTED_VIEWS = ("hosted_runs", "hosted_audit_events", "hosted_audit_verifications", "hosted_jobs", "hosted_integrity_checks",
                "hosted_serving_files", "hosted_serving_chunks", "hosted_schema_version")
# Supabase's API roles (and any other platform role) must never read the schema; revoked whenever they exist.
PLATFORM_ROLES = ("anon", "authenticated", "service_role", "authenticator")


class MigrationError(RuntimeError):
    pass


def migration_files() -> list[tuple[str, str, str]]:
    files = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        files.append((path.stem, text, hashlib.sha256(text.encode("utf-8")).hexdigest()))
    return files


def _identifier(name: str):
    from psycopg import sql
    return sql.Identifier(name)


def apply(db: Database, *, actor: str = "migration-runner") -> list[str]:
    """Apply pending migrations; return the versions applied now."""
    from psycopg import sql
    applied_now: list[str] = []
    with db.transaction() as connection:
        connection.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(_identifier(db.schema)))
        connection.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version text PRIMARY KEY, checksum text NOT NULL, applied_by text NOT NULL, applied_utc timestamptz NOT NULL DEFAULT now())""")
    for version, text, checksum in migration_files():
        with db.transaction() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('mospi-migrations:' || current_schema(), 0))")
            row = connection.execute("SELECT checksum FROM schema_migrations WHERE version = %s", (version,)).fetchone()
            if row:
                if row["checksum"] != checksum:
                    raise MigrationError(f"Migration {version} was changed after it was applied (checksum differs). "
                                         "Applied migrations are never edited; add a new numbered migration instead.")
                continue
            connection.execute(text)
            connection.execute("INSERT INTO schema_migrations (version, checksum, applied_by) VALUES (%s, %s, %s)", (version, checksum, actor))
            applied_now.append(version)
    return applied_now


def status(db: Database) -> dict[str, list[str]]:
    rows = db.fetch("SELECT version, checksum FROM schema_migrations ORDER BY version") if _has_table(db, "schema_migrations") else []
    applied = {r["version"]: r["checksum"] for r in rows}
    files = migration_files()
    return {"applied": sorted(applied), "pending": [v for v, _, _ in files if v not in applied],
            "changed": [v for v, _, c in files if v in applied and applied[v] != c]}


def _has_table(db: Database, name: str) -> bool:
    row = db.fetchone("SELECT to_regclass(%s) IS NOT NULL AS present", (f"{db.schema}.{name}",))
    return bool(row and row["present"])


def ensure_roles(db: Database) -> None:
    """Create or update the login roles (passwords from the environment; never printed).  mospi_reviewer only when its password is set."""
    from psycopg import sql
    passwords = {APP_ROLE: os.environ.get("MOSPI_DB_APP_PASSWORD", ""), READER_ROLE: os.environ.get("MOSPI_DB_READER_PASSWORD", "")}
    for role, password in passwords.items():
        if len(password) < 24:
            raise MigrationError(f"Set a strong password (24+ characters) for {role} in MOSPI_DB_{'APP' if role == APP_ROLE else 'READER'}_PASSWORD.")
    reviewer_password = os.environ.get("MOSPI_DB_REVIEWER_PASSWORD", "")
    if reviewer_password:
        if len(reviewer_password) < 24:
            raise MigrationError("Set a strong password (24+ characters) for mospi_reviewer in MOSPI_DB_REVIEWER_PASSWORD.")
        passwords[REVIEWER_ROLE] = reviewer_password
    with db.transaction() as connection:
        for role, password in passwords.items():
            exists = connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            verb = "ALTER" if exists else "CREATE"
            connection.execute(sql.SQL(verb + " ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION PASSWORD {}").format(
                _identifier(role), sql.Literal(password)))
        connection.execute(sql.SQL("ALTER ROLE {} CONNECTION LIMIT 20").format(_identifier(READER_ROLE)))
        connection.execute(sql.SQL("ALTER ROLE {} CONNECTION LIMIT 30").format(_identifier(APP_ROLE)))
        if REVIEWER_ROLE in passwords:
            connection.execute(sql.SQL("ALTER ROLE {} CONNECTION LIMIT 10").format(_identifier(REVIEWER_ROLE)))
            connection.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '15s'").format(_identifier(REVIEWER_ROLE)))
            connection.execute(sql.SQL("ALTER ROLE {} SET idle_in_transaction_session_timeout = '30s'").format(_identifier(REVIEWER_ROLE)))
        connection.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(_identifier(READER_ROLE)))
        connection.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '15s'").format(_identifier(READER_ROLE)))
        connection.execute(sql.SQL("ALTER ROLE {} SET idle_in_transaction_session_timeout = '30s'").format(_identifier(READER_ROLE)))
        connection.execute(sql.SQL("ALTER ROLE {} SET idle_in_transaction_session_timeout = '60s'").format(_identifier(APP_ROLE)))


def apply_grants(db: Database) -> None:
    """Least-privilege grants on the configured schema (idempotent).  Skipped for roles that do not exist yet."""
    from psycopg import sql
    with db.transaction() as connection:
        roles = {r["rolname"] for r in connection.execute("SELECT rolname FROM pg_roles WHERE rolname IN (%s, %s, %s)", (APP_ROLE, READER_ROLE, REVIEWER_ROLE))}
        schema = _identifier(db.schema)
        connection.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM PUBLIC").format(schema))
        connection.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(schema))
        database = connection.execute("SELECT current_database() AS name").fetchone()["name"]
        # On Supabase the database is shared with the platform's own services (Auth, Storage, Realtime), which connect through
        # PUBLIC's CONNECT; there the schema-level revocations, row level security and view-only grants protect "mospi" instead.
        supabase = connection.execute("SELECT 1 FROM pg_roles WHERE rolname = 'supabase_admin'").fetchone() is not None
        if not supabase:
            connection.execute(sql.SQL("REVOKE CONNECT, TEMPORARY ON DATABASE {} FROM PUBLIC").format(_identifier(database)))
        for role in roles:
            connection.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(_identifier(database), _identifier(role)))
            connection.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, _identifier(role)))
        if APP_ROLE in roles:
            app = _identifier(APP_ROLE)
            connection.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM {}").format(schema, app))
            for table in APP_WRITE:
                connection.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE ON {}.{} TO {}").format(schema, _identifier(table), app))
            for table in APP_APPEND:
                connection.execute(sql.SQL("GRANT SELECT, INSERT ON {}.{} TO {}").format(schema, _identifier(table), app))
            for table in APP_READ + HOSTED_VIEWS:
                connection.execute(sql.SQL("GRANT SELECT ON {}.{} TO {}").format(schema, _identifier(table), app))
            connection.execute(sql.SQL("GRANT USAGE ON ALL SEQUENCES IN SCHEMA {} TO {}").format(schema, app))
        if READER_ROLE in roles:
            reader = _identifier(READER_ROLE)
            connection.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM {}").format(schema, reader))
            for view in HOSTED_VIEWS:
                connection.execute(sql.SQL("GRANT SELECT ON {}.{} TO {}").format(schema, _identifier(view), reader))
            _grant_functions(connection, schema, READER_FUNCTIONS, reader)
        if REVIEWER_ROLE in roles:
            reviewer = _identifier(REVIEWER_ROLE)
            connection.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM {}").format(schema, reviewer))   # column grants too
            connection.execute(sql.SQL("GRANT INSERT ON {}.audit_events TO {}").format(schema, reviewer))
            connection.execute(sql.SQL("GRANT SELECT ({}) ON {}.audit_events TO {}").format(
                sql.SQL(", ").join(_identifier(c) for c in REVIEWER_COLUMNS), schema, reviewer))
            connection.execute(sql.SQL("GRANT SELECT ON {}.hosted_runs TO {}").format(schema, reviewer))   # the policies' run check
            _grant_functions(connection, schema, REVIEWER_FUNCTIONS, reviewer)
        _harden(connection, db.schema, roles)


def _grant_functions(connection, schema, signatures: tuple[str, ...], role) -> None:
    """EXECUTE on named functions only (signatures are constants above, never input)."""
    from psycopg import sql
    for signature in signatures:
        name, _, arguments = signature.partition("(")
        connection.execute(sql.SQL("GRANT EXECUTE ON FUNCTION {}.{}(" + arguments + " TO {}").format(schema, _identifier(name), role))


def _harden(connection, schema_name: str, roles: set[str]) -> None:
    """Row level security on every table and no access at all for PUBLIC or the platform's API roles."""
    from psycopg import sql
    schema = _identifier(schema_name)
    platform = [r["rolname"] for r in connection.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (list(PLATFORM_ROLES),))]
    for role in ["PUBLIC", *platform]:
        grantee = sql.SQL("PUBLIC") if role == "PUBLIC" else _identifier(role)
        connection.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM {}").format(schema, grantee))
        for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
            connection.execute(sql.SQL("REVOKE ALL ON ALL " + kind + " IN SCHEMA {} FROM {}").format(schema, grantee))
            connection.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} REVOKE ALL ON " + kind + " FROM {}").format(schema, grantee))
    tables = [r["relname"] for r in connection.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = %s AND c.relkind IN ('r', 'p')",
        (schema_name,))]
    for table in tables:
        connection.execute(sql.SQL("ALTER TABLE {}.{} ENABLE ROW LEVEL SECURITY").format(schema, _identifier(table)))
        if APP_ROLE in roles:
            present = connection.execute("SELECT 1 FROM pg_policies WHERE schemaname = %s AND tablename = %s AND policyname = 'mospi_app_access'",
                                         (schema_name, table)).fetchone()
            if not present:
                # Row filtering is not the control here (grants are); the policy only lets the granted statements see rows.
                connection.execute(sql.SQL("CREATE POLICY mospi_app_access ON {}.{} TO {} USING (true) WITH CHECK (true)").format(
                    schema, _identifier(table), _identifier(APP_ROLE)))
    if REVIEWER_ROLE in roles:
        # Hosted decisions: the grants allow INSERT and a few columns of SELECT on audit_events; these policies narrow the
        # rows to runs cleared for hosting (never the operations trail), and inserts to chained review events by a signed-in
        # actor.  Dropped and re-created each time, so a changed rule always takes effect.
        audit, reviewer = _identifier("audit_events"), _identifier(REVIEWER_ROLE)
        hosted_run = sql.SQL("run_id <> '__operations__' AND run_id IN (SELECT run_id FROM {}.hosted_runs)").format(schema)
        for name in ("mospi_reviewer_read", "mospi_reviewer_insert"):
            connection.execute(sql.SQL("DROP POLICY IF EXISTS {} ON {}.{}").format(_identifier(name), schema, audit))
        connection.execute(sql.SQL("CREATE POLICY mospi_reviewer_read ON {}.{} FOR SELECT TO {} USING ({})").format(schema, audit, reviewer, hosted_run))
        connection.execute(sql.SQL("CREATE POLICY mospi_reviewer_insert ON {}.{} FOR INSERT TO {} WITH CHECK ({} AND event_type IN ({}) "
                                   "AND event_hash IS NOT NULL AND origin = 'postgres' AND actor_authenticated = 1)").format(
            schema, audit, reviewer, hosted_run, sql.SQL(", ").join(sql.Literal(e) for e in REVIEWER_EVENTS)))


def admin_database() -> Database:
    load_env_file()
    url = os.environ.get("MOSPI_DB_ADMIN_URL", "").strip()
    if not url:
        raise MigrationError("MOSPI_DB_ADMIN_URL is not set (administrative connection for migrations).")
    return Database(url, application_name="mospi-migrate", statement_timeout_ms=300_000)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply MoSPI PostgreSQL migrations and grants.")
    parser.add_argument("--roles", action="store_true", help="create or update the login roles (mospi_reviewer only when MOSPI_DB_REVIEWER_PASSWORD is set)")
    parser.add_argument("--status", action="store_true", help="show applied and pending migrations only")
    args = parser.parse_args()
    try:
        db = admin_database()
        if args.status:
            print(status(db))
            return 0
        applied = apply(db)
        if args.roles:
            ensure_roles(db)
        apply_grants(db)
        print(f"schema {db.schema}: applied {applied or 'nothing (up to date)'}; grants applied")
        return 0
    except (MigrationError, DatabaseUnavailable) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
