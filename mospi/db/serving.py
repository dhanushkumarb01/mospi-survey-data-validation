"""Hosted serving set: the stored-run files the review workspace reads, kept in PostgreSQL for the hosted instance.

The hosted instance (Vercel) has no persistent disk, and the review data must not travel in its deployment bundle.  An
operator therefore loads the files of one approved Fusion run, and of the stage runs it was built from, into
``serving_files``/``serving_chunks`` (migration 0004).  The hosted instance reads them through the reader-only
``hosted_serving_*`` views into its temporary directory, verifies every SHA-256, and serves them with the unchanged
DuckDB queries, so the queue order, scores, stories and evidence are exactly those of the local workspace.

What is loaded (current-method "lanes" runs only): only the files the review pages read, and only the columns they
read where a page reads a few columns of a wide file (``prepared_persons``: the person facts on the case page;
``statistical_evidence``: the four columns of the record-check tool).  Every row is kept.  Parquet is re-encoded with
zstd to save database space and transfer.  Each loaded file is verified against its source: the row count, and a
content digest over the kept columns of every row (DuckDB ``hash`` of each row, summed) computed on both files.  After
the upload, every chunk's SHA-256 and length are recomputed inside the database and compared, so nothing has to be
downloaded to verify it.

    python -m mospi.db.serving build  --run 2024_first_visit_v2_2 --out <scratch dir>   # build and verify locally only
    python -m mospi.db.serving load   --run 2024_first_visit_v2_2                        # build, upload, verify (idempotent)
    python -m mospi.db.serving verify --run 2024_first_visit_v2_2                        # recompute in the database
    python -m mospi.db.serving list
    python -m mospi.db.serving remove --run <run>                                        # teardown of one run's files
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from mospi.paths import data_root

from .connection import Database, DatabaseUnavailable

CHUNK_BYTES = 2 << 20          # 2 MiB per row: small enough for the pooler and the statement timeout, few enough rows
FETCH_CHUNKS = 4               # chunks per query when the hosted instance reads (8 MiB per round trip)
ZSTD_LEVEL = 12
ALL = None                     # keep every column
STAT_COLUMNS = ("target_variable", "statistical_assessability_status", "grouping_values", "observed_value")

# What the review pages read from each stage run of a current-method (lanes) Fusion run: mospi/app/api.py,
# mospi/pipeline/stages/fusion/story.py and explain.py.  {file: columns kept (ALL), or "persons" for person_context's own}.
SERVED: dict[str, dict[str, Any]] = {
    "fusion": {"fused_cases.parquet": ALL, "evidence_cards.parquet": ALL, "group_priorities.parquet": ALL, "value_evidence.parquet": ALL,
               "fusion_report.json": ALL, "run_metadata.json": ALL},
    "preprocessing": {"prepared_persons.parquet": "persons", "run_metadata.json": ALL},
    "statistical": {"statistical_evidence.parquet": STAT_COLUMNS, "run_metadata.json": ALL},
    "contextual": {"contextual_evidence.parquet": ALL, "run_metadata.json": ALL},
    "ml": {"run_metadata.json": ALL},
    "pattern": {"pattern_evidence.parquet": ALL, "run_metadata.json": ALL},
    "historical": {"aggregate_indicators.parquet": ALL, "historical_report.json": ALL, "run_metadata.json": ALL},
    "integrity": {"integrity_violations.parquet": ALL, "integrity_report.json": ALL, "run_metadata.json": ALL},
}


class ServingError(RuntimeError):
    pass


@dataclass
class ServingFile:
    path: str                  # <stage>/runs/<run dir>/<file>, the same layout the workspace reads
    stage: str
    local: str
    bytes: int
    sha256: str
    chunk_sha256: list[str]
    rows: int | None
    source_path: str
    source_bytes: int
    source_sha256: str
    source_rows: int | None
    content_digest: str | None
    transform: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def chunk_hashes(path: Path) -> list[str]:
    with open(path, "rb") as handle:
        return [hashlib.sha256(block).hexdigest() for block in iter(lambda: handle.read(CHUNK_BYTES), b"")]


def content_digest(path: Path, columns: list[str]) -> tuple[int, str]:
    """(rows, order-independent digest of the given columns of every row), identical for equal content in any encoding."""
    import duckdb
    select = ", ".join('"' + c.replace('"', '""') + '"' for c in columns)
    with duckdb.connect() as connection:
        rows, total = connection.execute(f"SELECT COUNT(*), COALESCE(SUM(hash(row({select}))::HUGEINT), 0) FROM read_parquet(?)", [str(path)]).fetchone()
    return int(rows), f"{len(columns)}:{total}"


def source_directories(fusion_dir: Path, project: Path) -> dict[str, Path]:
    from .registry import source_directories as stage_dirs
    directories = {"fusion": fusion_dir, **{k: v for k, v in stage_dirs(fusion_dir, project).items()}}
    missing = sorted(k for k, v in directories.items() if v is None)
    if missing:
        raise ServingError(f"Stage runs of {fusion_dir.name} were not found: {', '.join(missing)}.")
    return directories


def build(run: str, out: Path, *, project: Path | None = None) -> list[ServingFile]:
    """Write the serving set of one Fusion run under ``out`` (same layout as the data root) and verify it against its sources."""
    import pyarrow.parquet as pq
    from mospi.pipeline.stages.fusion.explain import person_source_columns
    project = Path(project or data_root()).resolve()
    fusion_dir = project / "fusion" / "runs" / run
    meta_path = fusion_dir / "run_metadata.json"
    if not meta_path.is_file() or not (fusion_dir / "fused_cases.parquet").is_file():
        raise ServingError(f"{run} is not a Fusion run under {project / 'fusion' / 'runs'}.")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if "lanes" not in str(meta.get("fusion_version", "")):
        raise ServingError(f"{run} uses a superseded method ({meta.get('fusion_version')}); only current-method runs are hosted.")
    release, observation = str(meta["release"]), str(meta["observation"])
    files: list[ServingFile] = []
    for stage, directory in source_directories(fusion_dir, project).items():
        for name, columns in SERVED[stage].items():
            source = directory / name
            if not source.is_file():
                if name.endswith(".parquet") or name == "run_metadata.json":
                    raise ServingError(f"{stage} run {directory.name} has no {name}; the review pages need it.")
                continue
            path = f"{stage}/runs/{directory.name}/{name}"
            target = out / path
            target.parent.mkdir(parents=True, exist_ok=True)
            rows = source_rows = digest = None
            if name.endswith(".parquet"):
                available = pq.ParquetFile(source).schema_arrow.names
                keep = available if columns is ALL else person_source_columns(source, release, observation) if columns == "persons" else list(columns)
                absent = [c for c in keep if c not in available]
                if absent or not keep:
                    raise ServingError(f"{path}: columns the pages read are missing ({', '.join(absent) or 'none found'}).")
                table = pq.read_table(source, columns=keep)
                pq.write_table(table, target, compression="zstd", compression_level=ZSTD_LEVEL)
                del table
                source_rows, source_digest = content_digest(source, keep)
                rows, digest = content_digest(target, keep)
                if (rows, digest) != (source_rows, source_digest):
                    raise ServingError(f"{path}: the re-encoded file differs from its source (rows {rows} vs {source_rows}).")
                transform = "parquet-zstd" + ("" if len(keep) == len(available) else f"; {len(keep)} of {len(available)} columns: " + ",".join(keep))
            else:
                shutil.copyfile(source, target)
                transform = "copy"
            files.append(ServingFile(path=path, stage=stage, local=str(target), bytes=target.stat().st_size, sha256=sha256_file(target),
                                     chunk_sha256=chunk_hashes(target), rows=rows, source_path=source.relative_to(project).as_posix(),
                                     source_bytes=source.stat().st_size, source_sha256=sha256_file(source), source_rows=source_rows,
                                     content_digest=digest, transform=transform))
            if transform == "copy" and files[-1].sha256 != files[-1].source_sha256:
                raise ServingError(f"{path}: copy differs from its source.")
    return files


# ---------------------------------------------------------------- database side (operator, admin connection)

def load(db: Database, run: str, files: list[ServingFile], *, actor: str = "serving-loader", log=print) -> dict[str, Any]:
    """Upload a built serving set idempotently: unchanged files are skipped, changed ones replaced, stale ones removed."""
    started = time.perf_counter()
    if not db.fetchone("SELECT 1 FROM runs WHERE run_id = %s AND status IN ('PUBLISHED', 'REGISTERED')", (run,)):
        raise ServingError(f"Run {run} is not registered as reviewable. Register it first (python -m mospi.db.registry register ...).")
    present = {r["path"]: r for r in db.fetch("SELECT path, sha256, chunks, bytes FROM serving_files WHERE run_id = %s", (run,))}
    outcome = {"run_id": run, "uploaded": [], "unchanged": [], "removed": []}
    for item in files:
        old = present.get(item.path)
        if old and old["sha256"] == item.sha256 and old["chunks"] == len(item.chunk_sha256) and old["bytes"] == item.bytes:
            stored = db.fetchone("SELECT COUNT(*) AS n FROM serving_chunks WHERE run_id = %s AND path = %s", (run, item.path))["n"]
            if stored == len(item.chunk_sha256):
                outcome["unchanged"].append(item.path)
                continue
        t0 = time.perf_counter()
        with db.transaction() as connection:          # one file per transaction: a failure leaves the previous copy intact
            connection.execute("DELETE FROM serving_files WHERE run_id = %s AND path = %s", (run, item.path))
            connection.execute("""INSERT INTO serving_files (run_id, path, stage, bytes, sha256, chunks, rows, source_path, source_bytes, source_sha256,
                                  source_rows, content_digest, transform, loaded_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                               (run, item.path, item.stage, item.bytes, item.sha256, len(item.chunk_sha256), item.rows, item.source_path,
                                item.source_bytes, item.source_sha256, item.source_rows, item.content_digest, item.transform, actor))
            with open(item.local, "rb") as handle, connection.cursor() as cursor:
                batch: list[tuple] = []
                for seq, expected in enumerate(item.chunk_sha256):
                    block = handle.read(CHUNK_BYTES)
                    if hashlib.sha256(block).hexdigest() != expected:
                        raise ServingError(f"{item.path} changed on disk while loading.")
                    batch.append((run, item.path, seq, expected, block))
                    if len(batch) == 4:
                        cursor.executemany("INSERT INTO serving_chunks (run_id, path, seq, sha256, data) VALUES (%s,%s,%s,%s,%s)", batch)
                        batch = []
                if batch:
                    cursor.executemany("INSERT INTO serving_chunks (run_id, path, seq, sha256, data) VALUES (%s,%s,%s,%s,%s)", batch)
        outcome["uploaded"].append(item.path)
        log(f"  uploaded {item.path} ({item.bytes / 1e6:.1f} MB) in {time.perf_counter() - t0:.0f} s")
    wanted = {f.path for f in files}
    for path in sorted(set(present) - wanted):
        db.execute("DELETE FROM serving_files WHERE run_id = %s AND path = %s", (run, path))
        outcome["removed"].append(path)
    outcome["verification"] = verify(db, run, files)
    outcome["seconds"] = round(time.perf_counter() - started)
    if outcome["uploaded"] or outcome["removed"]:
        from .audit import PostgresAuditStore
        PostgresAuditStore(db).append_operation("SERVING_SET_LOADED", subject=run, actor=actor, details={
            "files": len(files), "bytes": sum(f.bytes for f in files), "uploaded": len(outcome["uploaded"]), "removed": outcome["removed"],
            "verification": outcome["verification"]["status"], "manifest_sha256": serving_digest(files)})
    return outcome


def serving_digest(files: list[ServingFile]) -> str:
    return hashlib.sha256(json.dumps(sorted((f.path, f.sha256) for f in files), separators=(",", ":")).encode()).hexdigest()


def verify(db: Database, run: str, files: list[ServingFile] | None = None) -> dict[str, Any]:
    """Recompute every chunk's SHA-256 and length inside the database; compare with the file rows (and the built set, if given)."""
    problems = []
    stored = {r["path"]: r for r in db.fetch("SELECT path, bytes, sha256, chunks, rows, source_rows FROM serving_files WHERE run_id = %s", (run,))}
    chunks: dict[str, list[dict[str, Any]]] = {}
    for row in db.fetch("SELECT path, seq, sha256, encode(sha256(data), 'hex') AS actual, length(data) AS n FROM serving_chunks WHERE run_id = %s "
                        "ORDER BY path, seq", (run,)):
        chunks.setdefault(row["path"], []).append(row)
    for path, info in stored.items():
        parts = chunks.get(path, [])
        if [c["seq"] for c in parts] != list(range(info["chunks"])):
            problems.append(f"{path}: chunks missing or out of order")
        if any(c["sha256"] != c["actual"] for c in parts):
            problems.append(f"{path}: a chunk does not match its SHA-256")
        if sum(c["n"] for c in parts) != info["bytes"]:
            problems.append(f"{path}: stored length differs")
        if info["rows"] != info["source_rows"]:
            problems.append(f"{path}: row count differs from the source")
    if files is not None:
        for item in files:
            info = stored.get(item.path)
            if info is None or info["sha256"] != item.sha256:
                problems.append(f"{item.path}: not stored as built")
            elif [c["actual"] for c in chunks.get(item.path, [])] != item.chunk_sha256:
                problems.append(f"{item.path}: stored chunks differ from the built file")
        if set(stored) != {f.path for f in files}:
            problems.append("the stored file list differs from the built set")
    return {"status": "VERIFIED" if stored and not problems else "FAILED", "files": len(stored), "bytes": sum(i["bytes"] for i in stored.values()),
            "rows": {p: i["rows"] for p, i in stored.items() if i["rows"] is not None}, "problems": problems}


def remove(db: Database, run: str) -> int:
    return db.execute("DELETE FROM serving_files WHERE run_id = %s", (run,))


# ---------------------------------------------------------------- hosted side (reader role, read-only views)

class HostedServingData:
    """Materialise the hosted serving set into a local directory once per process (Vercel: /tmp), verified by SHA-256.

    ``ensure()`` is called before each authenticated data request; the first call downloads, later calls return at once.
    A failed or incomplete download leaves nothing half-written in place (files are renamed into place only when verified),
    so a page never reads a partial file, and the next request tries again.
    """

    def __init__(self, db: Database, root: Path) -> None:
        self.db, self.root = db, Path(root)
        self._lock = threading.Lock()
        self._ready = False
        self.files = 0
        self.bytes = 0
        self.seconds: float | None = None

    @property
    def ready(self) -> bool:
        return self._ready

    def ensure(self) -> None:
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            started = time.perf_counter()
            listing = self.db.fetch("SELECT run_id, path, bytes, sha256, chunks FROM hosted_serving_files ORDER BY run_id, path")
            for item in listing:
                self._fetch(item)
            self.files, self.bytes = len(listing), sum(int(i["bytes"]) for i in listing)
            self.seconds = round(time.perf_counter() - started, 1)
            self._ready = True

    def _fetch(self, item: dict[str, Any]) -> None:
        target = self.root / item["path"]
        if target.is_file() and target.stat().st_size == item["bytes"] and sha256_file(target) == item["sha256"]:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".partial")
        digest = hashlib.sha256()
        with open(partial, "wb") as handle:
            for first in range(0, int(item["chunks"]), FETCH_CHUNKS):
                with self.db.transaction() as connection, connection.cursor(binary=True) as cursor:
                    cursor.execute("SELECT seq, sha256, data FROM hosted_serving_chunks WHERE run_id = %s AND path = %s AND seq >= %s AND seq < %s ORDER BY seq",
                                   (item["run_id"], item["path"], first, first + FETCH_CHUNKS))
                    rows = cursor.fetchall()
                if [r["seq"] for r in rows] != list(range(first, min(first + FETCH_CHUNKS, int(item["chunks"])))):
                    raise ServingError(f"{item['path']}: chunks are missing in the database.")
                for row in rows:
                    data = bytes(row["data"])
                    if hashlib.sha256(data).hexdigest() != row["sha256"]:
                        raise ServingError(f"{item['path']}: a chunk failed its SHA-256 check.")
                    digest.update(data)
                    handle.write(data)
        if digest.hexdigest() != item["sha256"] or partial.stat().st_size != int(item["bytes"]):
            partial.unlink(missing_ok=True)
            raise ServingError(f"{item['path']}: the downloaded file failed its SHA-256 check.")
        os.replace(partial, target)

    def status(self) -> dict[str, Any]:
        return {"loaded": self._ready, "files": self.files, "megabytes": round(self.bytes / 1e6, 1), "load_seconds": self.seconds}


# ---------------------------------------------------------------- CLI

def main() -> int:
    from .migrate import admin_database
    parser = argparse.ArgumentParser(description="Hosted serving set (files the hosted review workspace reads from the database).")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "load", "verify", "remove"):
        command = sub.add_parser(name)
        command.add_argument("--run", required=True, help="Fusion run directory name, e.g. 2024_first_visit_v2_2")
        if name in ("build", "load"):
            command.add_argument("--project-root", type=Path, default=None, help="data root (default: data/ or MOSPI_DATA_DIR)")
            command.add_argument("--out", type=Path, default=None, help="where to build (default: a temporary directory outside the repository)")
    sub.add_parser("list")
    args = parser.parse_args()
    try:
        if args.command == "build":
            out = args.out or Path(tempfile.mkdtemp(prefix="mospi-serving-"))
            files = build(args.run, out, project=args.project_root)
            print(json.dumps({"out": str(out), "files": len(files), "megabytes": round(sum(f.bytes for f in files) / 1e6, 1),
                              "source_megabytes": round(sum(f.source_bytes for f in files) / 1e6, 1),
                              "items": [{k: v for k, v in asdict(f).items() if k not in ("local", "chunk_sha256")} for f in files]}, indent=2))
            return 0
        db = admin_database()
        if args.command == "load":
            with tempfile.TemporaryDirectory(prefix="mospi-serving-") as scratch:
                out = args.out or Path(scratch)
                files = build(args.run, out, project=args.project_root)
                print(f"built {len(files)} files, {sum(f.bytes for f in files) / 1e6:.1f} MB (sources {sum(f.source_bytes for f in files) / 1e6:.1f} MB)")
                result = load(db, args.run, files)
            print(json.dumps({k: v for k, v in result.items() if k != "verification"} | {"verification": {k: v for k, v in result["verification"].items() if k != "rows"}}, indent=2))
            return 0 if result["verification"]["status"] == "VERIFIED" else 1
        if args.command == "verify":
            result = verify(db, args.run)
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "VERIFIED" else 1
        if args.command == "remove":
            print(f"removed {remove(db, args.run)} files of {args.run}")
            return 0
        for row in db.fetch("SELECT run_id, COUNT(*) AS files, SUM(bytes) AS bytes, MAX(loaded_utc) AS loaded FROM serving_files GROUP BY 1 ORDER BY 1"):
            print({**row, "bytes": int(row["bytes"])})
        return 0
    except (ServingError, DatabaseUnavailable) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
