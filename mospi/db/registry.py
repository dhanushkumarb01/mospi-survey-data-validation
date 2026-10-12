"""Run registry: which Fusion runs exist, whether they are reviewable, and what exactly was published.

* A manifest lists every file of the Fusion run and of the stage runs it was built from (path relative to the
  data root, size, SHA-256).  Its own SHA-256 is stored; a published manifest never changes (database trigger).
* Status ``PENDING`` (being produced), ``PUBLISHED`` (passed every gate; manifest verified), ``REGISTERED``
  (existed before the registry), ``FAILED``, ``WITHDRAWN``.  Only PUBLISHED/REGISTERED runs are listed for review;
  a run directory the registry marks PENDING/FAILED/WITHDRAWN is hidden, so incomplete output is never shown as a run.
* ``hosted_visible`` is allowed only for SYNTHETIC data or APPROVED_REAL with a recorded approval (gate G-AUTH).

    python -m mospi.db.registry register --fusion-root data/fusion/runs --data-class INTERNAL_REAL
    python -m mospi.db.registry register --fusion-root data/demo/fusion/runs --data-class SYNTHETIC --hosted
    python -m mospi.db.registry list
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mospi.paths import data_root

from .connection import Database

EXCLUDED = ("review_audit.sqlite", ".tmp", ".incomplete")
SOURCE_MODULES = ("preprocessing", "statistical", "contextual", "ml", "pattern", "historical", "integrity")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def source_directories(fusion_dir: Path, project_root: Path) -> dict[str, Path | None]:
    """The stage runs a Fusion run was built from (as recorded in its metadata)."""
    from mospi.pipeline.stages.fusion.explain import SourceResolver
    meta = json.loads((fusion_dir / "run_metadata.json").read_text(encoding="utf-8"))
    resolver = SourceResolver(project_root)                    # fresh resolver: never a cached "missing"
    release, observation = str(meta.get("release")), str(meta.get("observation"))
    runs = dict(meta.get("source_runs") or {})
    if meta.get("input_preprocessing_run_id"):
        runs.setdefault("preprocessing", meta["input_preprocessing_run_id"])
    return {module: resolver.run_dir(module, release, observation, runs.get(module)) for module in SOURCE_MODULES if runs.get(module)}


def build_manifest(fusion_dir: Path, project_root: Path) -> dict[str, Any]:
    fusion_dir, project_root = Path(fusion_dir).resolve(), Path(project_root).resolve()
    meta = json.loads((fusion_dir / "run_metadata.json").read_text(encoding="utf-8"))
    report_path = fusion_dir / "fusion_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    directories = {"fusion": fusion_dir, **source_directories(fusion_dir, project_root)}
    files, missing = [], sorted(m for m, d in directories.items() if d is None)
    for module, directory in directories.items():
        if directory is None:
            continue
        for path in sorted(p for p in directory.rglob("*") if p.is_file() and not any(x in p.name for x in EXCLUDED)):
            relative = path.relative_to(project_root).as_posix() if path.is_relative_to(project_root) else f"{module}/{path.relative_to(directory).as_posix()}"
            files.append({"stage": module, "path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return {"run_id": fusion_dir.name, "release": meta.get("release"), "observation": meta.get("observation"), "fusion_version": meta.get("fusion_version"),
            "records": report.get("records_processed"), "source_runs_missing": missing, "files": files,
            "generated_utc": datetime.now(timezone.utc).isoformat()}


def manifest_digest(manifest: dict[str, Any]) -> str:
    """Digest of what was published (the file list), independent of when the manifest was written."""
    return hashlib.sha256(json.dumps(manifest["files"], sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def register_existing(db: Database, fusion_root: Path, project_root: Path, *, data_class: str, hosted: bool = False,
                      approval: str | None = None) -> list[dict[str, Any]]:
    """Record runs that predate the registry (status REGISTERED).  Already-registered runs are left unchanged."""
    if hosted and data_class not in ("SYNTHETIC", "APPROVED_REAL"):
        raise ValueError("Only SYNTHETIC or APPROVED_REAL runs may be visible to the hosted instance (gate G-AUTH).")
    if data_class == "APPROVED_REAL" and not approval:
        raise ValueError("APPROVED_REAL needs the reference of the written approval (--approval).")
    out = []
    for directory in sorted(Path(fusion_root).glob("*")):
        if not ((directory / "run_metadata.json").is_file() and (directory / "fused_cases.parquet").is_file()):
            continue
        if db.fetchone("SELECT 1 FROM runs WHERE run_id = %s", (directory.name,)):
            out.append({"run_id": directory.name, "outcome": "already registered"})
            continue
        started = time.perf_counter()
        manifest = build_manifest(directory, project_root)
        if approval:
            manifest["hosted_approval"] = approval
        with db.transaction() as connection:
            connection.execute("""INSERT INTO runs (run_id, release, observation, fusion_version, status, data_class, hosted_visible, records, manifest,
                                  manifest_sha256, code_version) VALUES (%s,%s,%s,%s,'REGISTERED',%s,%s,%s,%s,%s,%s) ON CONFLICT (run_id) DO NOTHING""",
                               (directory.name, manifest["release"], manifest["observation"], manifest["fusion_version"], data_class, hosted,
                                manifest["records"], json.dumps(manifest), manifest_digest(manifest), None))
        out.append({"run_id": directory.name, "outcome": "registered", "files": len(manifest["files"]), "missing_sources": manifest["source_runs_missing"],
                    "seconds": round(time.perf_counter() - started, 1)})
    return out


class RunRegistry:
    """Small read helpers used by the web app (cached for a few seconds per process)."""

    def __init__(self, db: Database, *, ttl: float = 3.0) -> None:
        self.db, self.ttl = db, ttl
        self._hidden: tuple[float, set[str]] = (0.0, set())

    def hidden_runs(self) -> set[str]:
        now = time.monotonic()
        if now - self._hidden[0] > self.ttl:
            rows = self.db.fetch("SELECT run_id FROM runs WHERE status IN ('PENDING', 'FAILED', 'WITHDRAWN')")
            self._hidden = (now, {r["run_id"] for r in rows})
        return self._hidden[1]


def main() -> int:
    from .migrate import admin_database
    parser = argparse.ArgumentParser(description="MoSPI run registry.")
    sub = parser.add_subparsers(dest="command", required=True)
    register = sub.add_parser("register", help="register existing Fusion runs (status REGISTERED)")
    register.add_argument("--fusion-root", type=Path, required=True)
    register.add_argument("--project-root", type=Path, default=None, help="data root holding the stage runs (default: two levels above --fusion-root)")
    register.add_argument("--data-class", choices=("SYNTHETIC", "INTERNAL_REAL", "APPROVED_REAL"), required=True)
    register.add_argument("--hosted", action="store_true", help="visible to the hosted reader role (SYNTHETIC or APPROVED_REAL only)")
    register.add_argument("--approval", help="reference of the written hosting approval (required for APPROVED_REAL)")
    sub.add_parser("list")
    args = parser.parse_args()
    db = admin_database()
    if args.command == "list":
        for row in db.fetch("SELECT run_id, status, data_class, hosted_visible, records, left(manifest_sha256, 12) AS manifest FROM runs ORDER BY run_id"):
            print(row)
        return 0
    project = args.project_root or args.fusion_root.resolve().parent.parent
    try:
        for row in register_existing(db, args.fusion_root, project, data_class=args.data_class, hosted=args.hosted, approval=args.approval):
            print(row)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
