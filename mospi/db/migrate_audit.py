"""Copy every SQLite review/audit store into PostgreSQL without changing it (implementation_plan.md §11).

    python -m mospi.db.migrate_audit --dry-run     # everything except the final commit
    python -m mospi.db.migrate_audit               # migrate, verify, record

For each ``review_audit.sqlite`` under the data root (Fusion runs and evaluation runs):
1. back it up (copy + SHA-256 check) to ``MOSPI_BACKUP_DIR`` (default: ``%LOCALAPPDATA%/MoSPI/backups``), outside the repository;
2. verify its chain on the copy (opened read-only); a BROKEN store is refused and reported, never migrated;
3. in ONE transaction per store: copy every row verbatim (event ids, timestamps, payloads, hashes, order); rows already
   present must be identical (so a re-run or a resumed run inserts nothing twice and a conflicting row aborts);
   legacy stores (written before the chain existed) get the same ``AUDIT_CHAIN_STARTED`` seal review.py would add;
4. verify the PostgreSQL chain inside the same transaction (counts, last hash = source last hash) and record the
   result in ``audit_migrations`` and ``audit_verifications``; any difference rolls the whole store back.
The source files are hashed before and after: they must be byte-identical.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mospi.paths import data_root
from mospi.pipeline.stages.fusion.review import COLUMNS, verify_rows

from .audit import ALL_COLUMNS, PostgresAuditStore
from .connection import Database, DatabaseUnavailable

ACTOR = "audit-migration"


class _DryRun(Exception):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def backup_root() -> Path:
    value = os.environ.get("MOSPI_BACKUP_DIR", "").strip()
    if value:
        return Path(value)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "MoSPI" / "backups"


def discover(root: Path) -> list[tuple[str, Path]]:
    """(audit run key, store path).  Fusion runs keep their directory name; evaluation runs are prefixed by their path."""
    stores = [(p.parent.name, p) for p in sorted((root / "fusion" / "runs").glob("*/review_audit.sqlite"))]
    evaluation = root / "evaluation" / "runs"
    if evaluation.is_dir():
        stores += [("evaluation/" + p.parent.relative_to(evaluation).as_posix(), p) for p in sorted(evaluation.rglob("review_audit.sqlite"))]
    return stores


def read_rows(path: Path) -> tuple[str, list[dict[str, Any]]]:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        present = [row[1] for row in connection.execute("PRAGMA table_info(audit_events)")]
        rows = [dict(r) for r in connection.execute("SELECT * FROM audit_events ORDER BY event_id")] if present else []
    finally:
        connection.close()
    fmt = "chained" if "event_hash" in present else "legacy"
    # Same key order as review.COLUMNS; columns a legacy store lacks are NULL.
    return fmt, [{c: row.get(c) for c in COLUMNS} for row in rows]


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return all((a.get(c) == b.get(c)) or (a.get(c) is None and b.get(c) is None) for c in ALL_COLUMNS)


def migrate_store(db: Database, key: str, source: Path, copy: Path, *, dry_run: bool = False) -> dict[str, Any]:
    source_sha = sha256_file(source)
    if sha256_file(copy) != source_sha:
        raise RuntimeError(f"backup copy of {key} does not match its source")
    fmt, rows = read_rows(copy)
    source_result = verify_rows(rows) if rows else {"status": "NOT_CHAINED", "events": 0}
    report = {"run_id": key, "source_format": fmt, "source_events": len(rows), "source_chain_status": source_result["status"],
              "source_last_hash": source_result.get("last_hash")}
    if source_result["status"] == "BROKEN":
        return {**report, "outcome": "REFUSED", "detail": "the source chain is BROKEN; it was not migrated"}
    store = PostgresAuditStore(db)
    try:
        with db.transaction() as connection:
            store._lock(connection, key)
            recorded = connection.execute("SELECT source_sha256 FROM audit_migrations WHERE run_id = %s", (key,)).fetchone()
            if recorded and recorded["source_sha256"] != source_sha:
                return {**report, "outcome": "REFUSED", "detail": "this store was migrated before and has changed since; investigate before migrating"}
            existing = {r["event_id"]: dict(r) for r in connection.execute(
                f"SELECT {', '.join(ALL_COLUMNS)} FROM audit_events WHERE run_id = %s", (key,)).fetchall()}
            inserted = 0
            for row in rows:
                present = existing.get(row["event_id"])
                if present is not None:
                    if not _same(present, row):
                        raise RuntimeError(f"{key}: event {row['event_id']} already exists in PostgreSQL with different content")
                    continue
                connection.execute(f"INSERT INTO audit_events ({', '.join(ALL_COLUMNS)}, run_id, origin) VALUES "
                                   f"({', '.join(['%s'] * (len(ALL_COLUMNS) + 2))})", [*(row[c] for c in ALL_COLUMNS), key, "sqlite_migration"])
                inserted += 1
            chained_before = connection.execute("SELECT COUNT(*) AS n FROM audit_events WHERE run_id = %s AND event_hash IS NOT NULL", (key,)).fetchone()["n"]
            chain_start_added = chained_before == 0
            store._initialise(connection, key)            # seals legacy rows exactly as review.initialise does
            destination = [dict(r) for r in connection.execute(
                f"SELECT {', '.join(ALL_COLUMNS)} FROM audit_events WHERE run_id = %s ORDER BY event_id", (key,)).fetchall()]
            result = verify_rows(destination)
            source_ids = {r["event_id"] for r in rows}
            migrated = [r for r in destination if r["event_id"] in source_ids]
            problems = []
            if result["status"] != "INTACT":
                problems.append(f"PostgreSQL chain is {result['status']}")
            if len(migrated) != len(rows) or any(not _same(a, b) for a, b in zip(migrated, rows)):
                problems.append("migrated rows differ from the source")
            if fmt == "chained" and rows and source_result.get("last_hash") and not chain_start_added:
                tail = [r for r in destination if r["event_hash"]]
                if tail and tail[len([r for r in rows if r.get("event_hash")]) - 1]["event_hash"] != source_result["last_hash"]:
                    problems.append("last migrated hash differs from the source")
            if problems:
                raise RuntimeError(f"{key}: " + "; ".join(problems))
            connection.execute("""INSERT INTO audit_migrations (run_id, source_path, source_sha256, source_format, source_events, source_chain_status,
                                  source_last_hash, migrated_events, chain_start_added, destination_status, destination_events, destination_last_hash, migrated_by)
                                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (run_id) DO NOTHING""",
                               (key, source.relative_to(data_root()).as_posix() if source.is_relative_to(data_root()) else source.name, source_sha, fmt, len(rows),
                                source_result["status"], source_result.get("last_hash"), inserted, chain_start_added, result["status"], len(destination),
                                result.get("last_hash"), ACTOR))
            store.record_verification(key, result, ACTOR, connection=connection)
            if inserted or chain_start_added:
                store.append_operation("AUDIT_MIGRATED", subject=key, actor=ACTOR, actor_authenticated=True, actor_role="system", connection=connection,
                                       details={"source_events": len(rows), "inserted": inserted, "chain_start_added": chain_start_added,
                                                "status": result["status"], "last_hash": result.get("last_hash")})
            report.update(outcome="MIGRATED" if inserted or chain_start_added else "ALREADY_MIGRATED", inserted=inserted, chain_start_added=chain_start_added,
                          destination_events=len(destination), destination_status=result["status"], destination_last_hash=result.get("last_hash"))
            if dry_run:
                raise _DryRun
    except _DryRun:
        report["outcome"] = "DRY_RUN_OK"
    if sha256_file(source) != source_sha:
        raise RuntimeError(f"{key}: the source file changed during migration")
    return report


def migrate_all(db: Database, root: Path | None = None, *, dry_run: bool = False, backup_dir: Path | None = None) -> list[dict[str, Any]]:
    root = Path(root or data_root())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(backup_dir or backup_root()) / f"audit-sqlite-{stamp}-{uuid.uuid4().hex[:6]}"
    reports = []
    for key, path in discover(root):
        copy = folder / key.replace("/", "__") / "review_audit.sqlite"
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, copy)
        os.chmod(copy, 0o444)
        try:
            reports.append(migrate_store(db, key, path, copy, dry_run=dry_run))
        except (RuntimeError, DatabaseUnavailable) as error:
            reports.append({"run_id": key, "outcome": "FAILED", "detail": str(error)})
    (folder / "SHA256SUMS").write_text("".join(f"{sha256_file(p)}  {p.relative_to(folder).as_posix()}\n" for p in sorted(folder.rglob("*.sqlite"))),
                                      encoding="utf-8")
    return reports


def main() -> int:
    from .migrate import admin_database
    parser = argparse.ArgumentParser(description="Migrate the SQLite review/audit stores into PostgreSQL (non-destructive).")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--data-root", type=Path, default=None)
    args = parser.parse_args()
    reports = migrate_all(admin_database(), args.data_root, dry_run=args.dry_run)
    width = max(len(r["run_id"]) for r in reports) if reports else 10
    for r in reports:
        print(f"{r['run_id']:<{width}}  {r['outcome']:<17} src={r.get('source_events', '-')} {r.get('source_chain_status', ''):<11} "
              f"dst={r.get('destination_events', '-')} {r.get('destination_status', '')} {(r.get('destination_last_hash') or '')[:12]} {r.get('detail', '')}")
    failed = [r for r in reports if r["outcome"] in ("FAILED", "REFUSED")]
    print(f"{len(reports)} stores, {sum(r.get('source_events', 0) or 0 for r in reports)} source events, {len(failed)} failed or refused")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
