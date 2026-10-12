"""Backup, verified restore drill, and recovery of the operational schema.

    python -m mospi.db.backup create                       # pg_dump (custom format) + SHA-256 + content summary
    python -m mospi.db.backup verify <dump>                 # restore into a scratch database, compare, drop it
    python -m mospi.db.backup restore <dump> --target-db mospi_v22_recovered   # recovery into a NEW database

* Dumps go to ``MOSPI_BACKUP_DIR`` (default ``%LOCALAPPDATA%/MoSPI/backups``), outside the repository and OneDrive.
* ``verify`` is the restore drill: the dump's checksum, then every table's row count and every run's audit-chain
  status and head hash in the restored copy must equal the summary recorded at backup time.
* ``restore`` never writes into an existing database: recovery is "restore into a new database, verify, then point
  MOSPI_DATABASE_URL at it", so a bad dump can never damage the live store.
* The password goes to pg_dump/pg_restore through the PGPASSWORD environment of the child process only.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .connection import Database, redact
from .migrate import admin_database
from .migrate_audit import backup_root, sha256_file

TABLES = ("schema_migrations", "audit_events", "audit_verifications", "audit_migrations", "datasets", "dataset_files", "jobs", "job_events",
          "runs", "integrity_checks", "notifications", "serving_files", "serving_chunks")


def _binary(name: str) -> str:
    folder = os.environ.get("MOSPI_PG_BIN", "").strip()
    candidates = [Path(folder) / f"{name}.exe", Path(folder) / name] if folder else []
    candidates += [Path(p) for p in filter(None, [shutil.which(name)])]
    candidates += [Path(f"C:/Program Files/PostgreSQL/{v}/bin/{name}.exe") for v in (17, 16, 15)]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError(f"{name} not found; set MOSPI_PG_BIN to the PostgreSQL bin folder.")


def _params(url: str) -> dict[str, str]:
    from psycopg.conninfo import conninfo_to_dict
    return {k: str(v) for k, v in conninfo_to_dict(url).items()}


def _run(tool: str, args: list[str], url: str, database: str | None = None) -> None:
    params = _params(url)
    env = {**os.environ, "PGPASSWORD": params.get("password", ""), "PGSSLMODE": params.get("sslmode", "prefer")}
    if params.get("sslrootcert"):
        env["PGSSLROOTCERT"] = params["sslrootcert"]
    command = [_binary(tool), "-h", params.get("host", "localhost"), "-p", params.get("port", "5432"), "-U", params.get("user", "postgres"),
               "-d", database or params.get("dbname", "postgres"), *args]
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(f"{tool} failed: {redact(result.stderr.strip())[-800:]}")


def summary(db: Database) -> dict[str, Any]:
    from .audit import PostgresAuditStore
    counts = {table: db.fetchone(f"SELECT COUNT(*) AS n FROM {table}")["n"] for table in TABLES}
    store = PostgresAuditStore(db)
    chains = {}
    for key in store.run_keys():
        result = store.verify(key)
        chains[key] = {"status": result["status"], "events": result.get("events"), "last_hash": result.get("last_hash")}
    return {"schema": db.schema, "counts": counts, "chains": chains}


def create(db: Database, url: str, folder: Path | None = None, *, without_serving_data: bool = False) -> Path:
    """``without_serving_data`` leaves out the bytes of the hosted serving set (serving_chunks): they are rebuilt exactly
    from the stored runs with ``python -m mospi.db.serving load``, and the dump keeps their file list and checksums."""
    folder = Path(folder or backup_root())
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dump = folder / f"mospi-{db.schema}-{stamp}.dump"
    before = summary(db)
    exclude = [f"--exclude-table-data={db.schema}.serving_chunks"] if without_serving_data else []
    _run("pg_dump", ["--format=custom", f"--schema={db.schema}", "--no-privileges", *exclude, "--file", str(dump)], url)
    after = summary(db)
    if before["counts"] != after["counts"]:
        # Writes happened during the dump; pg_dump is a consistent snapshot, but the summary would not match it.
        dump.unlink()
        raise RuntimeError("The database changed while the backup ran; run it again (or stop the app and worker first).")
    (folder / f"{dump.name}.sha256").write_text(f"{sha256_file(dump)}  {dump.name}\n", encoding="utf-8")
    if without_serving_data:
        before["counts"]["serving_chunks"] = 0
        before["serving_data_excluded"] = True
    (folder / f"{dump.name}.summary.json").write_text(json.dumps({**before, "created_utc": stamp}, indent=2), encoding="utf-8")
    return dump


def _create_database(url: str, name: str) -> None:
    import psycopg
    from psycopg import sql
    with psycopg.connect(url, autocommit=True, connect_timeout=10) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def _drop_database(url: str, name: str) -> None:
    import psycopg
    from psycopg import sql
    with psycopg.connect(url, autocommit=True, connect_timeout=10) as connection:
        connection.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def _url_for(url: str, database: str) -> str:
    from psycopg.conninfo import make_conninfo
    return make_conninfo(url, dbname=database)


def restore(dump: Path, url: str, target: str) -> Database:
    expected = (dump.parent / f"{dump.name}.sha256").read_text(encoding="utf-8").split()[0]
    if sha256_file(dump) != expected:
        raise RuntimeError("The dump does not match its recorded SHA-256; it was not restored.")
    live = _params(url).get("dbname")
    if target == live:
        raise RuntimeError("Restore never writes into the live database; choose a new database name.")
    _create_database(url, target)
    _run("pg_restore", ["--no-owner", "--exit-on-error", str(dump)], url, database=target)
    schema = json.loads((dump.parent / f"{dump.name}.summary.json").read_text(encoding="utf-8"))["schema"]
    return Database(_url_for(url, target), schema=schema, application_name="mospi-restore")


def verify(dump: Path, url: str, *, keep: bool = False) -> dict[str, Any]:
    expected = json.loads((dump.parent / f"{dump.name}.summary.json").read_text(encoding="utf-8"))
    scratch = f"mospi_restore_check_{uuid.uuid4().hex[:8]}"
    restored = restore(dump, url, scratch)
    try:
        actual = summary(restored)
    finally:
        restored.close()
        if not keep:
            _drop_database(url, scratch)
    problems = [f"{t}: {expected['counts'].get(t)} expected, {actual['counts'].get(t)} restored" for t in TABLES
                if expected["counts"].get(t) != actual["counts"].get(t)]
    problems += [f"chain {k}: {v} vs {actual['chains'].get(k)}" for k, v in expected["chains"].items() if actual["chains"].get(k) != v]
    problems += [f"chain {k} is {v['status']}" for k, v in actual["chains"].items() if v["status"] not in ("INTACT",)]
    return {"dump": dump.name, "scratch_database": scratch, "kept": keep, "tables": actual["counts"], "chains": len(actual["chains"]),
            "status": "VERIFIED" if not problems else "MISMATCH", "problems": problems}


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up, verify and restore the MoSPI operational schema.")
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("create")
    make.add_argument("--folder", type=Path)
    make.add_argument("--without-serving-data", action="store_true", help="leave out serving_chunks bytes (rebuilt from the stored runs)")
    check = sub.add_parser("verify")
    check.add_argument("dump", type=Path)
    check.add_argument("--keep", action="store_true", help="keep the scratch database for inspection")
    back = sub.add_parser("restore")
    back.add_argument("dump", type=Path)
    back.add_argument("--target-db", required=True)
    args = parser.parse_args()
    db = admin_database()
    url = os.environ["MOSPI_DB_ADMIN_URL"]
    try:
        if args.command == "create":
            print(create(db, url, args.folder, without_serving_data=args.without_serving_data))
        elif args.command == "verify":
            result = verify(args.dump, url, keep=args.keep)
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "VERIFIED" else 1
        else:
            restored = restore(args.dump, url, args.target_db)
            print(json.dumps(summary(restored)["counts"], indent=2))
            print(f"Restored into database {args.target_db}. Verify, then point MOSPI_DATABASE_URL at it.")
    except (RuntimeError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
