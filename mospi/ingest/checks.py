"""Periodic data-quality checks of registered datasets and published runs (operation A; no pipeline is run here).

Per published/registered run: every manifest artifact present and unchanged (size; SHA-256 when the file was modified
after publication or ``MOSPI_CHECK_FULL_HASH=1``), the Fusion quality-gate files present, unique case ids, metadata
consistent with the registry, and the audit hash chain intact (recorded in ``audit_verifications``).
Per dataset: stored upload files unchanged (a change there is tampering: FAILED); registered delivery paths
fingerprinted (a change is CHANGED: it needs a new validation, which is operation B and follows the rerun policy).
Storage: run directories on disk that the registry does not know, and registered runs whose directory is gone.

A check job whose findings include FAILED ends with status FAILED (error class INTEGRITY_FINDINGS): a failed
check is never reported as a pass.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from mospi.db.audit import PostgresAuditStore
from mospi.db.connection import Database
from mospi.db.registry import sha256_file, source_directories
from mospi.paths import REPO_ROOT
from mospi.pipeline.qa import CONTRACTS as QA_CONTRACTS

from .settings import Settings, sanitise

CHECKER = "integrity-check"


def _base_for(manifest: dict[str, Any], candidates: list[Path]) -> Path | None:
    fusion = [f["path"] for f in manifest.get("files", []) if f.get("stage") == "fusion"]
    for base in candidates:
        if fusion and (base / fusion[0]).is_file():
            return base
        if (base / "fusion" / "runs" / manifest.get("run_id", "") / "run_metadata.json").is_file():
            return base
    return None


def check_run(row: dict[str, Any], candidates: list[Path], settings: Settings) -> list[tuple[str, str, str]]:
    """(check_name, status, detail) for one registered run."""
    out: list[tuple[str, str, str]] = []
    manifest = row["manifest"] if isinstance(row["manifest"], dict) else json.loads(row["manifest"] or "{}")
    base = _base_for(manifest, candidates)
    if base is None:
        return [("run_directory_present", "FAILED", "The run's files are not found on this server.")]
    try:
        published = datetime.fromisoformat(str(manifest.get("generated_utc"))).timestamp()
    except (TypeError, ValueError):
        published = 0.0
    fusion_dir = base / "fusion" / "runs" / row["run_id"]
    stages = {"fusion": fusion_dir, **(source_directories(fusion_dir, base) if (fusion_dir / "run_metadata.json").is_file() else {})}
    missing, changed = [], []
    for entry in manifest.get("files", []):
        path = base / entry["path"]
        if not path.is_file() and stages.get(entry.get("stage")) is not None and entry["path"].startswith(f"{entry['stage']}/"):
            # Manifests registered before 12 Oct 2026 name files relative to their stage run (stage/file); resolve through the run's own metadata.
            path = stages[entry["stage"]] / entry["path"].split("/", 1)[1]
        if not path.is_file():
            missing.append(entry["path"])
            continue
        stat = path.stat()
        if stat.st_size != entry["bytes"]:
            changed.append(entry["path"])
        elif settings.full_hash_checks or stat.st_mtime > published + 2:
            if sha256_file(path) != entry["sha256"]:
                changed.append(entry["path"])
    out.append(("artifacts_present", "FAILED" if missing else "PASSED",
                f"{len(missing)} of {len(manifest.get('files', []))} published files are missing" + (f" (first: {Path(missing[0]).name})" if missing else "")))
    out.append(("artifacts_unchanged", "FAILED" if changed else "PASSED",
                f"{len(changed)} published files differ from the manifest" + (f" (first: {Path(changed[0]).name})" if changed else "")))
    gate_missing = [f for f in QA_CONTRACTS["fusion"].files if not (fusion_dir / f).is_file() or (fusion_dir / f).stat().st_size == 0]
    out.append(("fusion_outputs_complete", "FAILED" if gate_missing else "PASSED", ", ".join(gate_missing) or "all review outputs present"))
    if (fusion_dir / "fused_cases.parquet").is_file():
        with duckdb.connect() as connection:
            total, distinct = connection.execute("SELECT COUNT(*), COUNT(DISTINCT case_id) FROM read_parquet(?)", [str(fusion_dir / "fused_cases.parquet")]).fetchone()
        out.append(("unique_case_ids", "FAILED" if total != distinct else "PASSED", f"{total:,} cases, {total - distinct:,} duplicated case ids"))
    if (fusion_dir / "run_metadata.json").is_file():
        meta = json.loads((fusion_dir / "run_metadata.json").read_text(encoding="utf-8"))
        consistent = str(meta.get("release")) == str(row["release"]) and str(meta.get("observation")) == str(row["observation"])
        out.append(("metadata_consistent", "PASSED" if consistent else "FAILED",
                    "release and observation match the registry" if consistent else "run metadata disagrees with the registry"))
    return out


def run_checks(db: Database, job_id: str, *, root: Path, settings: Settings) -> dict[str, Any]:
    audit = PostgresAuditStore(db)
    findings: list[tuple[str, str, str, str, str]] = []           # (target_kind, target_id, check, status, detail)
    candidates = [Path(root), REPO_ROOT / "data" / "demo"]
    runs = db.fetch("SELECT run_id, release, observation, status, manifest FROM runs WHERE status IN ('PUBLISHED', 'REGISTERED') ORDER BY run_id")
    for row in runs:
        try:
            for name, status, detail in check_run(dict(row), candidates, settings):
                findings.append(("RUN", row["run_id"], name, status, detail))
        except Exception as error:   # noqa: BLE001 - a check that cannot run is a failure, never a pass
            findings.append(("RUN", row["run_id"], "check_could_not_run", "FAILED", sanitise(f"{type(error).__name__}: {error}")))
    for key in sorted({r["run_id"] for r in runs} | set(audit.run_keys())):
        result = audit.verify(key, record_as=CHECKER)
        status = {"INTACT": "PASSED", "NO_AUDIT_STORE": "PASSED", "BROKEN": "FAILED"}.get(result["status"], "WARNING")
        findings.append(("AUDIT", key, "audit_chain", status, f"{result['status']}, {result.get('events', 0)} events" +
                         (f", head {result['last_hash'][:12]}" if result.get("last_hash") else "") + (f"; {result['detail']}" if result.get("detail") else "")))
    registered = {r["run_id"] for r in db.fetch("SELECT run_id FROM runs")}
    on_disk = {d.name for d in (Path(root) / "fusion" / "runs").glob("*") if (d / "run_metadata.json").is_file() and (d / "fused_cases.parquet").is_file()}
    for name in sorted(on_disk - registered):
        findings.append(("STORAGE", name, "run_registered", "WARNING", "A Fusion run on disk is not in the registry (produced outside the registered workflow)."))
    changed_datasets: list[str] = []
    for f in db.fetch("""SELECT f.file_id, f.dataset_id, f.display_name, f.stored_path, f.size_bytes, f.sha256, f.mtime_ns, d.source, d.status
                         FROM dataset_files f JOIN datasets d USING (dataset_id) WHERE d.status NOT IN ('REJECTED', 'RECEIVING')"""):
        path = Path(f["stored_path"])
        changed_kind = "FAILED" if f["source"] == "UPLOAD" else "CHANGED"
        if not path.is_file():
            findings.append(("DATASET", f["dataset_id"], f"file_present:{f['display_name']}", "FAILED", "The stored file is missing."))
            continue
        stat = path.stat()
        same = stat.st_size == f["size_bytes"] and (stat.st_mtime_ns == f["mtime_ns"] and not settings.full_hash_checks or sha256_file(path) == f["sha256"])
        if same:
            findings.append(("DATASET", f["dataset_id"], f"file_unchanged:{f['display_name']}", "PASSED", "fingerprint matches"))
        else:
            findings.append(("DATASET", f["dataset_id"], f"file_unchanged:{f['display_name']}", changed_kind,
                             "The stored upload changed after it was received." if changed_kind == "FAILED" else
                             "The registered delivery file changed; a new validation is required for the new content."))
            if changed_kind == "CHANGED":
                changed_datasets.append(f["dataset_id"])
    with db.transaction() as connection:
        for kind, target, name, status, detail in findings:
            connection.execute("INSERT INTO integrity_checks (job_id, target_kind, target_id, check_name, status, detail) VALUES (%s,%s,%s,%s,%s,%s)",
                               (job_id, kind, target, name, status, sanitise(detail, 500)))
    counts = {s: sum(1 for f in findings if f[3] == s) for s in ("PASSED", "FAILED", "WARNING", "CHANGED")}
    return {"counts": counts, "targets": len({(f[0], f[1]) for f in findings}), "changed_datasets": sorted(set(changed_datasets)),
            "failed": [{"target": f[1], "check": f[2], "detail": f[4]} for f in findings if f[3] == "FAILED"][:20],
            "digest": hashlib.sha256(json.dumps(findings, default=str).encode()).hexdigest()[:16]}
