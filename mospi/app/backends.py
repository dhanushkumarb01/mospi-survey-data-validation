"""Choose the audit store and the operations service from configuration (``MOSPI_AUDIT_BACKEND``).

* ``sqlite`` (default): per-run ``review_audit.sqlite``, exactly as V2.2; no upload page.
* ``postgres``: PostgreSQL (``MOSPI_DATABASE_URL``).  The local instance refuses to start while migrations are
  pending, or while a SQLite store holds review history that was never migrated (or changed after migration),
  so the two stores can never silently diverge.  The hosted instance (Vercel) uses the read-only reader role and
  the ``hosted_*`` views only, on the Supabase transaction pooler (docs/deployment/POSTGRESQL.md).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from mospi.db.config import load_env_file


class BackendError(RuntimeError):
    pass


def audit_backend() -> str:
    load_env_file()
    value = os.environ.get("MOSPI_AUDIT_BACKEND", "sqlite").strip().lower() or "sqlite"
    if value not in {"sqlite", "postgres"}:
        raise BackendError("MOSPI_AUDIT_BACKEND must be 'sqlite' or 'postgres'.")
    return value


def _review_events(path: Path) -> int:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM audit_events WHERE event_type <> 'AUDIT_CHAIN_STARTED'").fetchone()[0])
    except sqlite3.Error:
        return 0
    finally:
        connection.close()


def startup_check(db: Any, fusion_root: Path) -> None:
    from mospi.db.migrate import migration_files
    from mospi.db.migrate_audit import sha256_file
    applied = {r["version"]: r["checksum"] for r in db.fetch("SELECT version, checksum FROM schema_migrations")}
    pending = [version for version, _, checksum in migration_files() if applied.get(version) != checksum]
    if pending:
        raise BackendError(f"PostgreSQL migrations are not applied ({', '.join(pending)}). Run: python -m mospi.db.migrate")
    migrated = {r["run_id"]: r["source_sha256"] for r in db.fetch("SELECT run_id, source_sha256 FROM audit_migrations")}
    problems = []
    for store in sorted(Path(fusion_root).glob("*/review_audit.sqlite")):
        if _review_events(store) == 0:
            continue                                   # only the chain-start marker: no review history to carry over
        run = store.parent.name
        if run not in migrated:
            problems.append(f"{run} (never migrated)")
        elif sha256_file(store) != migrated[run]:
            problems.append(f"{run} (changed after migration)")
    if problems:
        raise BackendError("These SQLite review stores hold history that PostgreSQL does not have: " + "; ".join(problems) +
                           ". Run python -m mospi.db.migrate_audit (it refuses a changed store; investigate those first).")


def build(fusion_root: Path, project_root: Path, *, hosted: bool) -> tuple[Any, Any]:
    """(audit_store, operations) for create_app; (None, None) means the V2.2 SQLite behaviour."""
    backend = audit_backend()
    if backend == "sqlite":
        return None, None
    from mospi.db.audit import PostgresAuditStore
    from mospi.db.connection import database_from_env
    db = database_from_env(application_name="mospi-hosted" if hosted else "mospi-app", read_only=hosted)
    if db is None:
        raise BackendError("MOSPI_AUDIT_BACKEND=postgres needs MOSPI_DATABASE_URL.")
    if hosted:
        from mospi.ingest.service import HostedOperations
        return PostgresAuditStore(db, hosted=True), HostedOperations(db)
    from mospi.ingest.service import Operations
    startup_check(db, fusion_root)
    return PostgresAuditStore(db), Operations(db, root=project_root)
