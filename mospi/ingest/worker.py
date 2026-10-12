"""The validation worker and scheduler (a separate process; nothing long runs inside a web request).

    python -m mospi.ingest.worker run            # loop: recover, schedule checks, run checks, run validations
    python -m mospi.ingest.worker run --once     # process what is queued now, then exit (tests, cron)
    python -m mospi.ingest.worker check-now      # queue an integrity check (it runs in the worker loop)

A validation job runs in its own child process (``execute <job_id>``) that writes a heartbeat every 15 s:
1. staging      - re-verify the stored files' SHA-256 and lay them out as the contract expects (copies; originals untouched)
2. preparation  - the unchanged PLFSPreprocessor (contract-driven; nothing dropped or corrected)
3. pipeline     - the unchanged mospi.pipeline.run.run_pipeline with its quality gates, one stage event per stage
4. publication  - manifest with SHA-256 per file, registry PENDING -> PUBLISHED, audit chain started, alerts
A QA-gate failure is FAILED_QA_GATE and never retried automatically.  A job whose heartbeat stops (worker or host
restart) becomes INTERRUPTED and is retried once automatically; stage runs that completed are reused by the
pipeline's own resume rule, and partial stage directories are renamed aside (never deleted).
Only one validation runs at a time (the 2025 batch needs several GB of memory).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mospi.db.connection import Database, DatabaseUnavailable, database_from_env
from mospi.db.registry import build_manifest, manifest_digest, sha256_file
from mospi.paths import REPO_ROOT, data_root
from mospi.pipeline.stages.preprocessing.config import CONTRACTS

from .checks import run_checks
from .service import Operations, enqueue_validation, job_event, notify
from .settings import Settings, sanitise, settings as load_settings
from .storage import dataset_dir

LOGGER = logging.getLogger("MoSPI.worker")
STAGE_MODULES = ("preprocessing", "peer_groups", "statistical", "contextual", "ml", "pattern", "historical", "integrity", "fusion")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------- recovery and scheduling


def _interrupt(connection, ops: Operations, job: dict[str, Any], reason: str) -> None:
    """Mark one RUNNING job INTERRUPTED; an interrupted validation is retried once automatically."""
    connection.execute("""UPDATE jobs SET status = 'INTERRUPTED', finished_utc = now(), error_class = 'INTERRUPTED', error_message = %s
                          WHERE job_id = %s AND status = 'RUNNING'""", (reason, job["job_id"]))
    job_event(connection, job["job_id"], job["current_stage"] or "worker", "FAILED", f"Interrupted: {reason}")
    if job["kind"] != "VALIDATION":
        notify(connection, "WARNING", "CHECK_INTERRUPTED", "An integrity check was interrupted; it will run again at the next schedule.", job_id=job["job_id"])
        return
    connection.execute("UPDATE datasets SET status = 'FAILED' WHERE dataset_id = %s", (job["dataset_id"],))
    if job["attempt"] < job["max_attempts"]:
        dataset = dict(connection.execute("SELECT * FROM datasets WHERE dataset_id = %s", (job["dataset_id"],)).fetchone())
        retry = enqueue_validation(connection, ops.audit, dataset, trigger="RETRY", actor="worker (automatic retry)", verified=False, role="system",
                                   idempotency_key=f"auto-retry:{job['job_id']}", attempt=job["attempt"] + 1, parent_job_id=job["job_id"])
        notify(connection, "WARNING", "VALIDATION_INTERRUPTED", f"Validation {job['label']} was interrupted and has been queued again "
               f"(attempt {retry['attempt']}); completed stages will be reused.", job_id=job["job_id"], dataset_id=job["dataset_id"], run_id=job["run_id"])
    else:
        connection.execute("UPDATE runs SET status = 'FAILED' WHERE run_id = %s AND status = 'PENDING'", (job["run_id"],))
        notify(connection, "ERROR", "VALIDATION_INTERRUPTED", f"Validation {job['label']} was interrupted again and was not retried automatically. "
               "An administrator can retry it.", job_id=job["job_id"], dataset_id=job["dataset_id"], run_id=job["run_id"])


def recover(ops: Operations) -> list[str]:
    """Mark RUNNING jobs whose heartbeat stopped (worker or host restart) as INTERRUPTED."""
    with ops.db.transaction() as connection:
        stale = connection.execute("""SELECT * FROM jobs WHERE status = 'RUNNING' AND COALESCE(heartbeat_utc, started_utc, created_utc)
                                      < now() - make_interval(secs => %s) FOR UPDATE SKIP LOCKED""", (ops.settings.stale_seconds,)).fetchall()
        for job in stale:
            _interrupt(connection, ops, dict(job), "the worker stopped reporting (restart or crash) before the job finished.")
    return [job["job_id"] for job in stale]


def schedule(ops: Operations, now: float | None = None) -> str | None:
    """Queue the periodic integrity check for the current interval slot (idempotent; never overlaps a running check)."""
    minutes = ops.settings.check_interval_minutes
    if minutes <= 0:
        return None
    slot = int((now or time.time()) // (minutes * 60))
    try:
        result = ops.trigger_check(user=None, trigger="SCHEDULED", idempotency_key=f"scheduled-check:{minutes}:{slot}")
    except Exception as error:   # noqa: BLE001 - a scheduling problem must not stop the worker
        LOGGER.warning("could not schedule the integrity check: %s", sanitise(error))
        return None
    return None if result.get("already_active") or result.get("duplicate") else result["job_id"]


def schedule_full_reruns(ops: Operations, now: float | None = None) -> list[str]:
    """Optional (MOSPI_FULL_RERUN_DAYS): re-validate registered deliveries whose last validation is older than N days."""
    days = ops.settings.full_rerun_days
    if days <= 0:
        return []
    slot = int((now or time.time()) // (days * 86400))
    rows = ops.db.fetch("""SELECT DISTINCT ON (d.input_root) d.dataset_id, d.contract_name, d.input_root, d.data_class FROM datasets d
                           WHERE d.source = 'REGISTERED_PATH' AND d.status = 'VALIDATED'
                           AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.dataset_id = d.dataset_id AND j.finished_utc > now() - make_interval(days => %s))
                           ORDER BY d.input_root, d.created_utc DESC""", (days,))
    return [job for row in rows if (job := revalidate(ops, row, trigger="SCHEDULED", key=f"scheduled-rerun:{row['dataset_id']}:{slot}"))]


def revalidate(ops: Operations, dataset: dict[str, Any], *, trigger: str, key: str) -> str | None:
    """Register the delivery again (new fingerprints), run its pre-flight and queue a full validation if it passes."""
    from .register import register_delivery
    if ops.db.fetchone("SELECT 1 FROM jobs WHERE idempotency_key = %s", (key,)):
        return None
    fresh = register_delivery(ops, contract=dataset["contract_name"], input_root=Path(dataset["input_root"]),
                              synthetic=dataset["data_class"] == "SYNTHETIC", user={"name": "scheduler", "role": "system"})
    if fresh["status"] != "PREFLIGHT_PASSED":
        with ops.db.transaction() as connection:
            notify(connection, "ERROR", "REVALIDATION_BLOCKED", "A changed or scheduled delivery did not pass its pre-flight check; it was not validated.",
                   dataset_id=fresh["dataset_id"])
        return None
    label = ops._default_label(fresh["release"], fresh["observation"]).replace("u", "c" if trigger == "CHANGE_DETECTED" else "s", 1)
    with ops.db.transaction() as connection:
        row = dict(connection.execute("SELECT * FROM datasets WHERE dataset_id = %s FOR UPDATE", (fresh["dataset_id"],)).fetchone())
        connection.execute("UPDATE datasets SET label = %s, confirmed_by = 'scheduler', confirmed_utc = now() WHERE dataset_id = %s", (label, row["dataset_id"]))
        row["label"] = label
        job = enqueue_validation(connection, ops.audit, row, trigger=trigger, actor="scheduler", verified=False, role="system", idempotency_key=key)
    return job["job_id"]


# ---------------------------------------------------------------- integrity checks (in the worker loop; quick)


def run_check_job(ops: Operations) -> str | None:
    with ops.db.transaction() as connection:
        job = connection.execute("""UPDATE jobs SET status = 'RUNNING', started_utc = now(), heartbeat_utc = now(), worker = %s, current_stage = 'checks'
                                    WHERE job_id = (SELECT job_id FROM jobs WHERE kind = 'INTEGRITY_CHECK' AND status = 'QUEUED'
                                                    ORDER BY created_utc FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *""", (WORKER_ID,)).fetchone()
    if job is None:
        return None
    job_id = job["job_id"]
    try:
        result = run_checks(ops.db, job_id, root=ops.root, settings=ops.settings)
        failed = result["counts"]["FAILED"]
        with ops.db.transaction() as connection:
            connection.execute("""UPDATE jobs SET status = %s, finished_utc = now(), result = %s, error_class = %s, error_message = %s, current_stage = NULL
                                  WHERE job_id = %s""", ("FAILED" if failed else "SUCCEEDED", json.dumps(result), "INTEGRITY_FINDINGS" if failed else None,
                                                        f"{failed} integrity checks failed." if failed else None, job_id))
            job_event(connection, job_id, "checks", "FAILED" if failed else "COMPLETED", json.dumps(result["counts"]))
            if failed:
                notify(connection, "ERROR", "INTEGRITY_CHECK_FAILED", f"{failed} integrity checks failed: " +
                       "; ".join(f"{f['target']} {f['check']}" for f in result["failed"][:5]), job_id=job_id)
            if result["counts"]["CHANGED"]:
                notify(connection, "WARNING", "DELIVERY_CHANGED", f"{len(result['changed_datasets'])} registered deliveries changed and need a new validation"
                       + (" (queued automatically)." if ops.settings.rerun_on_change else " (automatic re-validation is off: MOSPI_RERUN_ON_CHANGE)."), job_id=job_id)
            ops.audit.append_operation("INTEGRITY_CHECK_COMPLETED", subject=job_id, actor="worker", actor_authenticated=True, actor_role="system",
                                       connection=connection, details={"counts": result["counts"], "digest": result["digest"], "trigger": job["trigger"]})
        if ops.settings.rerun_on_change:
            for dataset_id in result["changed_datasets"]:
                row = ops.db.fetchone("SELECT * FROM datasets WHERE dataset_id = %s", (dataset_id,))
                newest = ops.db.fetchone("SELECT dataset_id FROM datasets WHERE input_root = %s AND contract_name = %s ORDER BY created_utc DESC LIMIT 1",
                                         (row["input_root"], row["contract_name"]))
                if newest and newest["dataset_id"] == dataset_id:     # only the latest registration of a delivery is re-validated
                    revalidate(ops, dict(row), trigger="CHANGE_DETECTED", key=f"change:{dataset_id}:{result['digest']}")
    except Exception as error:   # noqa: BLE001 - a check that crashed is a failed check, never a pass
        with ops.db.transaction() as connection:
            connection.execute("UPDATE jobs SET status = 'FAILED', finished_utc = now(), error_class = %s, error_message = %s WHERE job_id = %s",
                               (type(error).__name__, sanitise(error), job_id))
            notify(connection, "ERROR", "INTEGRITY_CHECK_ERROR", f"The integrity check could not complete: {type(error).__name__}.", job_id=job_id)
    return job_id


# ---------------------------------------------------------------- validation jobs (child process)


def claim_validation(ops: Operations) -> dict[str, Any] | None:
    with ops.db.transaction() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('mospi-claim-validation:' || current_schema(), 0))")
        if connection.execute("SELECT 1 FROM jobs WHERE kind = 'VALIDATION' AND status = 'RUNNING'").fetchone():
            return None
        job = connection.execute("""UPDATE jobs SET status = 'RUNNING', started_utc = now(), heartbeat_utc = now(), worker = %s, current_stage = 'starting'
                                    WHERE job_id = (SELECT job_id FROM jobs WHERE kind = 'VALIDATION' AND status = 'QUEUED'
                                                    ORDER BY created_utc FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *""", (WORKER_ID,)).fetchone()
        if job:
            connection.execute("UPDATE datasets SET status = 'VALIDATING' WHERE dataset_id = %s", (job["dataset_id"],))
            job_event(connection, job["job_id"], "worker", "INFO", "Claimed by the worker.")
    return dict(job) if job else None


def spawn(ops: Operations, job: dict[str, Any]) -> subprocess.Popen:
    log_dir = dataset_dir(ops.settings.upload_root, job["dataset_id"]) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = open(log_dir / f"{job['job_id']}.log", "ab")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return subprocess.Popen([sys.executable, "-m", "mospi.ingest.worker", "execute", job["job_id"]], cwd=str(REPO_ROOT), stdout=log,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != "nt")


class _StageRecorder(logging.Handler):
    """Turns the pipeline's own 'run <stage>' / 'reuse <stage>' log lines into real stage events (no invented progress)."""

    def __init__(self, db: Database, job_id: str) -> None:
        super().__init__(logging.INFO)
        self.db, self.job_id, self.current = db, job_id, None

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        verb, _, rest = message.partition(" ")
        if verb not in ("run", "reuse") or not rest:
            return
        stage = rest.split(" ")[0]
        try:
            with self.db.transaction() as connection:
                if self.current:
                    job_event(connection, self.job_id, self.current, "COMPLETED")
                    self.current = None
                if verb == "run":
                    job_event(connection, self.job_id, stage, "STARTED")
                    self.current = stage
                else:
                    job_event(connection, self.job_id, stage, "REUSED", "Completed earlier; reused unchanged.")
                connection.execute("UPDATE jobs SET current_stage = %s, heartbeat_utc = now() WHERE job_id = %s", (stage, self.job_id))
        except DatabaseUnavailable:
            pass

    def finish(self) -> None:
        if self.current:
            with self.db.transaction() as connection:
                job_event(connection, self.job_id, self.current, "COMPLETED")
            self.current = None


def _set_stage(db: Database, job_id: str, stage: str, status: str, message: str | None = None) -> None:
    with db.transaction() as connection:
        job_event(connection, job_id, stage, status, message)
        connection.execute("UPDATE jobs SET current_stage = %s, heartbeat_utc = now() WHERE job_id = %s", (stage, job_id))


def _set_aside(path: Path, db: Database, job_id: str) -> None:
    """Rename a partial directory (never delete) so the unchanged pipeline can resume."""
    target = path.with_name(f"{path.name}.incomplete-{_stamp()}")
    path.rename(target)
    _set_stage(db, job_id, "resume", "WARNING", f"A partial {path.parent.parent.name} directory from an earlier attempt was set aside as {target.name}.")


def stage_inputs(ops: Operations, job_id: str, dataset: dict[str, Any], files: list[dict[str, Any]]) -> Path:
    """Verify the stored files and lay them out under an input root the contract expects."""
    contract = CONTRACTS[dataset["contract_name"]]
    for f in files:
        if sha256_file(Path(f["stored_path"])) != f["sha256"]:
            raise RuntimeError(f"The stored {f['level']} file no longer matches the SHA-256 recorded when it was received.")
    if dataset["source"] == "REGISTERED_PATH":
        return Path(dataset["input_root"])
    from .preflight import load_profiles
    profile = load_profiles(ops.settings.mapping_profile_dir).get(dataset["mapping_profile"] or "") if dataset["mapping_profile"] else None
    root = dataset_dir(ops.settings.upload_root, dataset["dataset_id"]) / "input"
    for f in files:
        target = root / (contract.household_path if f["level"] == "household" else contract.person_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        rename = profile["rename"] if profile and profile.get("level") == f["level"] else None
        if rename:
            # Approved mapping: only the header row is rewritten; every data byte is copied unchanged.
            with open(f["stored_path"], "rb") as source, open(target, "wb") as out:
                header = source.readline()
                ending = b"\r\n" if header.endswith(b"\r\n") else b"\n"
                names = header.rstrip(b"\r\n").decode("utf-8").split(",")
                out.write(",".join(rename.get(n, n) for n in names).encode("utf-8") + ending)
                shutil.copyfileobj(source, out, 1 << 20)
        else:
            shutil.copyfile(f["stored_path"], target)
    return root


def _history(release: str, root: Path) -> tuple[list[Path], list[str]]:
    from mospi.pipeline.run import PRESETS
    wanted = [root / h for h in PRESETS.get(release, {}).get("history", [])]
    return [p for p in wanted if p.is_file()], [p.parent.name for p in wanted if not p.is_file()]


def execute(job_id: str) -> int:
    """Child-process entry: run one claimed validation job to a terminal state."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    db = database_from_env(application_name="mospi-worker-job")
    ops = Operations(db)
    job = db.fetchone("SELECT * FROM jobs WHERE job_id = %s", (job_id,))
    if job is None or job["status"] != "RUNNING":
        LOGGER.error("job %s is not running", job_id)
        return 2
    dataset = dict(db.fetchone("SELECT * FROM datasets WHERE dataset_id = %s", (job["dataset_id"],)))
    files = [dict(r) for r in db.fetch("SELECT * FROM dataset_files WHERE dataset_id = %s AND level IS NOT NULL", (dataset["dataset_id"],))]
    root, label, run_id = ops.root, job["label"], job["run_id"]
    db.execute("UPDATE jobs SET pid = %s, heartbeat_utc = now() WHERE job_id = %s", (os.getpid(), job_id))
    with db.transaction() as connection:
        ops.audit.append_operation("VALIDATION_STARTED", subject=job_id, actor="worker", actor_authenticated=True, actor_role="system", connection=connection,
                                   details={"dataset_id": dataset["dataset_id"], "run_id": run_id, "attempt": job["attempt"]})
    stop = threading.Event()

    def beat() -> None:
        while not stop.wait(15):
            try:
                db.execute("UPDATE jobs SET heartbeat_utc = now() WHERE job_id = %s AND status = 'RUNNING'", (job_id,))
            except DatabaseUnavailable:
                pass
    threading.Thread(target=beat, daemon=True).start()
    recorder = _StageRecorder(db, job_id)
    pipeline_logger = logging.getLogger("MoSPI.pipeline")
    started = time.perf_counter()
    stage = "staging"
    try:
        from mospi.pipeline.qa import QAGateFailure
        from mospi.pipeline.run import Inputs, code_version, run_pipeline
        from mospi.pipeline.stages.preprocessing.pipeline import PLFSPreprocessor, PreprocessingFailure, RunConfig
        _set_stage(db, job_id, "staging", "STARTED")
        input_root = stage_inputs(ops, job_id, dataset, files)
        _set_stage(db, job_id, "staging", "COMPLETED", "Stored files verified (SHA-256) and laid out as the contract expects.")
        stage = "preparation"
        contract = CONTRACTS[dataset["contract_name"]]
        prep_dir = root / "preprocessing" / "runs" / f"{contract.release}_{contract.observation}_{label}"
        if job["attempt"] > 1:
            for module in STAGE_MODULES:
                partial = root / module / "runs" / f"{contract.release}_{contract.observation}_{label}"
                complete = (partial / "run_metadata.json").is_file() and (module != "preprocessing" or (partial / "prepared_persons.parquet").is_file())
                if partial.exists() and not complete:
                    _set_aside(partial, db, job_id)
        if (prep_dir / "prepared_persons.parquet").is_file() and (prep_dir / "run_metadata.json").is_file():
            _set_stage(db, job_id, "preparation", "REUSED", "Prepared earlier in this job's previous attempt; reused unchanged.")
        else:
            _set_stage(db, job_id, "preparation", "STARTED")
            try:
                PLFSPreprocessor(RunConfig(input_root, root / "preprocessing" / "runs", dataset["contract_name"], run_id=label)).run()
            except PreprocessingFailure as error:
                raise _JobFailure("PREPARATION_FAILED", "Preparation stopped on a critical finding (see the preparation report of this run).") from error
            report = json.loads((prep_dir / "preprocessing_report.json").read_text(encoding="utf-8"))
            _set_stage(db, job_id, "preparation", "COMPLETED", f"Preparation status {report.get('overall_status')}; issues {report.get('issue_counts')}.")
        prepared = prep_dir / "prepared_persons.parquet"
        history, unavailable = _history(contract.release, root)
        if unavailable:
            _set_stage(db, job_id, "pipeline", "WARNING", "Earlier-period reference data of the release preset is not on this server and was not used: "
                       + ", ".join(unavailable))
        stage = "pipeline"
        pipeline_logger.addHandler(recorder)
        result = run_pipeline(Inputs(prepared, history=history), label, roots=root)
        recorder.finish()
        stage = "publication"
        fusion = Path(result["fusion"])
        if fusion.name != run_id:
            raise _JobFailure("PUBLICATION_FAILED", "The pipeline produced a run under an unexpected name; nothing was published.")
        _set_stage(db, job_id, "publication", "STARTED")
        manifest = build_manifest(fusion, root)
        if manifest["source_runs_missing"]:
            raise _JobFailure("PUBLICATION_FAILED", "Stage runs named in the Fusion metadata are missing: " + ", ".join(manifest["source_runs_missing"]))
        ops.audit.register_run(run_id)
        report = json.loads((fusion / "fusion_report.json").read_text(encoding="utf-8"))
        summary = {"records": report.get("records_processed"), "check_now": report.get("check_now_cases"), "tiers": report.get("tier_counts"),
                   "fsu_alerts": report.get("group_alerts"), "qa": {k: v.get("status") for k, v in result["qa"].items()},
                   "timing_seconds": result["timing_seconds"], "history_used": [p.parent.name for p in history], "total_seconds": round(time.perf_counter() - started, 1)}
        version = code_version()
        with db.transaction() as connection:
            connection.execute("""UPDATE runs SET status = 'PUBLISHED', manifest = %s, manifest_sha256 = %s, records = %s, fusion_version = %s, code_version = %s,
                                  published_utc = now() WHERE run_id = %s AND status = 'PENDING'""",
                               (json.dumps(manifest), manifest_digest(manifest), manifest["records"], manifest["fusion_version"], version, run_id))
            connection.execute("""UPDATE jobs SET status = 'SUCCEEDED', finished_utc = now(), current_stage = NULL, result = %s WHERE job_id = %s""",
                               (json.dumps(summary, default=str), job_id))
            connection.execute("UPDATE datasets SET status = 'VALIDATED', record_counts = record_counts || %s WHERE dataset_id = %s",
                               (json.dumps({"validated_records": manifest["records"]}), dataset["dataset_id"]))
            job_event(connection, job_id, "publication", "COMPLETED", f"Run {run_id} published ({len(manifest['files'])} files, manifest {manifest_digest(manifest)[:12]}).")
            notify(connection, "INFO", "RUN_PUBLISHED", f"Validation {label} finished; run {run_id} is published and listed in the survey-round selector.",
                   job_id=job_id, dataset_id=dataset["dataset_id"], run_id=run_id)
            for event, details in (("VALIDATION_SUCCEEDED", {"run_id": run_id, "qa": summary["qa"]}),
                                   ("RUN_PUBLISHED", {"run_id": run_id, "manifest_sha256": manifest_digest(manifest), "files": len(manifest["files"])})):
                ops.audit.append_operation(event, subject=job_id if event == "VALIDATION_SUCCEEDED" else run_id, actor="worker", actor_authenticated=True,
                                           actor_role="system", connection=connection, details=details)
        _write_report(root, contract.release, label, job, "COMPLETED", summary, version)
        return 0
    except BaseException as error:   # noqa: BLE001 - every failure reaches the ledger
        from mospi.pipeline.qa import QAGateFailure
        recorder.current = None
        if isinstance(error, QAGateFailure):
            status, error_class, message = "FAILED_QA_GATE", "QA_GATE", str(error)
        elif isinstance(error, _JobFailure):
            status, error_class, message = "FAILED", error.error_class, str(error)
        else:
            status, error_class, message = "FAILED", type(error).__name__, f"{type(error).__name__}: {error}"
        LOGGER.error("job %s failed in %s: %s\n%s", job_id, stage, sanitise(message), traceback.format_exc()[-3000:])
        with db.transaction() as connection:
            connection.execute("""UPDATE jobs SET status = %s, finished_utc = now(), error_class = %s, error_message = %s WHERE job_id = %s AND status = 'RUNNING'""",
                               (status, error_class, sanitise(message, 1000), job_id))
            connection.execute("UPDATE runs SET status = 'FAILED' WHERE run_id = %s AND status = 'PENDING'", (run_id,))
            connection.execute("UPDATE datasets SET status = 'FAILED' WHERE dataset_id = %s", (dataset["dataset_id"],))
            job_event(connection, job_id, stage, "FAILED", message)
            notify(connection, "ERROR", "VALIDATION_FAILED" if status == "FAILED" else "QA_GATE_FAILED",
                   f"Validation {label} {'was stopped by a quality check' if status == 'FAILED_QA_GATE' else 'failed'} during {stage}. Nothing was published.",
                   job_id=job_id, dataset_id=dataset["dataset_id"], run_id=run_id)
            ops.audit.append_operation("VALIDATION_FAILED", subject=job_id, actor="worker", actor_authenticated=True, actor_role="system", connection=connection,
                                       details={"stage": stage, "status": status, "error_class": error_class})
        _write_report(root, CONTRACTS[dataset["contract_name"]].release, label, job, status, {"error_class": error_class, "stage": stage}, None)
        return 2 if status == "FAILED_QA_GATE" else 1
    finally:
        stop.set()
        pipeline_logger.removeHandler(recorder)


class _JobFailure(RuntimeError):
    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class


def _write_report(root: Path, release: str, label: str, job: dict[str, Any], status: str, details: dict[str, Any], version: str | None) -> None:
    folder = root / "pipeline" / "runs"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{release}_{label}.json").write_text(json.dumps({"release": release, "label": label, "status": status, "code_version": version,
                                                               "started_from": "upload", "job_id": job["job_id"], "attempt": job["attempt"],
                                                               "actor": job["requested_by"], **details}, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------- loop


def loop(ops: Operations, *, once: bool = False) -> None:
    child: tuple[subprocess.Popen, dict[str, Any]] | None = None
    while True:
        try:
            recover(ops)
            schedule(ops)
            schedule_full_reruns(ops)
            while run_check_job(ops):
                pass
            if child is not None and child[0].poll() is not None:
                process, job = child
                child = None
                with ops.db.transaction() as connection:          # the child ended without recording a result: crash or kill
                    row = connection.execute("SELECT * FROM jobs WHERE job_id = %s AND status = 'RUNNING' FOR UPDATE", (job["job_id"],)).fetchone()
                    if row:
                        _interrupt(connection, ops, dict(row), f"the job process ended unexpectedly (exit code {process.returncode}).")
            if child is None:
                job = claim_validation(ops)
                if job:
                    child = (spawn(ops, job), job)
                    LOGGER.info("validation %s started (dataset %s)", job["job_id"], job["dataset_id"])
        except DatabaseUnavailable as error:
            LOGGER.warning("database unavailable: %s", error)
        if once and child is None and not ops.db.fetchone("SELECT 1 FROM jobs WHERE status = 'QUEUED'"):
            return
        time.sleep(1 if once else ops.settings.poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="MoSPI validation worker and integrity-check scheduler.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--once", action="store_true")
    execute_parser = sub.add_parser("execute")
    execute_parser.add_argument("job_id")
    sub.add_parser("check-now")
    args = parser.parse_args()
    db = database_from_env(application_name="mospi-worker")
    if db is None:
        print("error: MOSPI_DATABASE_URL is not set", file=sys.stderr)
        return 2
    if args.command == "execute":
        return execute(args.job_id)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ops = Operations(db)
    if args.command == "check-now":
        print(ops.trigger_check(user={"name": "operator (command line)", "role": "admin"}))
        return 0
    loop(ops, once=args.once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
