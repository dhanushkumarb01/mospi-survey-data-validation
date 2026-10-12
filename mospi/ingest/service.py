"""Operational records behind the Upload & validate page, the jobs ledger, integrity checks and alerts.

Every state change happens in one PostgreSQL transaction together with its job/stage event and, where it is an
operation people need to account for, an event in the hash-chained operations audit trail.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psycopg.errors import UniqueViolation

from mospi.db.audit import PostgresAuditStore
from mospi.db.connection import Database, DatabaseUnavailable
from mospi.db.registry import RunRegistry
from mospi.paths import data_root
from mospi.pipeline.stages.preprocessing.config import CONTRACTS

from .preflight import load_profiles, run_preflight
from .settings import LABEL_PATTERN, UPLOADABLE_CONTRACTS, Settings, sanitise, settings as load_settings
from .storage import dataset_dir, new_id

ACTIVE_JOB = ("QUEUED", "RUNNING")
RETRYABLE = ("FAILED", "INTERRUPTED")


class OperationError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _clean(row: dict[str, Any] | None, *, drop: tuple[str, ...] = ()) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: _iso(v) for k, v in row.items() if k not in drop}


def notify(connection, severity: str, kind: str, message: str, *, job_id: str | None = None, dataset_id: str | None = None, run_id: str | None = None) -> None:
    connection.execute("INSERT INTO notifications (severity, kind, job_id, dataset_id, run_id, message) VALUES (%s, %s, %s, %s, %s, %s)",
                       (severity, kind, job_id, dataset_id, run_id, sanitise(message, 1000)))


def job_event(connection, job_id: str, stage: str, status: str, message: str | None = None) -> None:
    connection.execute("INSERT INTO job_events (job_id, stage, status, message) VALUES (%s, %s, %s, %s)",
                       (job_id, stage, status, sanitise(message, 1000) if message else None))


def run_id_for(dataset: dict[str, Any], label: str) -> str:
    return f"{dataset['release']}_{dataset['observation']}_{label}"


def enqueue_validation(connection, audit: PostgresAuditStore, dataset: dict[str, Any], *, trigger: str, actor: str, verified: bool,
                       idempotency_key: str, attempt: int = 1, parent_job_id: str | None = None, role: str | None = None) -> dict[str, Any]:
    """Create the QUEUED validation job and its PENDING registry row (both or neither)."""
    existing = connection.execute("SELECT * FROM jobs WHERE idempotency_key = %s", (idempotency_key,)).fetchone()
    if existing:
        return dict(existing)
    label = dataset["label"]
    run_id = run_id_for(dataset, label)
    run = connection.execute("SELECT status FROM runs WHERE run_id = %s FOR UPDATE", (run_id,)).fetchone()
    if run and run["status"] in ("PUBLISHED", "REGISTERED"):
        raise OperationError(f"Run {run_id} is already published; stored runs are never overwritten. Use a new label.", 409)
    job_id = new_id()
    try:
        connection.execute("""INSERT INTO jobs (job_id, kind, status, trigger, dataset_id, run_id, label, idempotency_key, attempt, parent_job_id,
                              requested_by, requested_by_verified) VALUES (%s, 'VALIDATION', 'QUEUED', %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                           (job_id, trigger, dataset["dataset_id"], run_id, label, idempotency_key, attempt, parent_job_id, actor, verified))
    except UniqueViolation:
        raise OperationError("A validation of this dataset is already queued or running.", 409) from None
    if run:
        connection.execute("UPDATE runs SET status = 'PENDING', job_id = %s WHERE run_id = %s", (job_id, run_id))
    else:
        connection.execute("""INSERT INTO runs (run_id, release, observation, dataset_id, job_id, status, data_class)
                              VALUES (%s, %s, %s, %s, %s, 'PENDING', %s)""",
                           (run_id, dataset["release"], dataset["observation"], dataset["dataset_id"], job_id, dataset["data_class"]))
    connection.execute("UPDATE datasets SET status = 'QUEUED', updated_utc = now() WHERE dataset_id = %s", (dataset["dataset_id"],))
    job_event(connection, job_id, "queue", "INFO", f"Queued ({trigger.lower()}, attempt {attempt}).")
    audit.append_operation("VALIDATION_REQUESTED" if trigger != "RETRY" else "JOB_RETRIED", subject=job_id, actor=actor, actor_authenticated=verified,
                           actor_role=role, connection=connection,
                           details={"dataset_id": dataset["dataset_id"], "run_id": run_id, "trigger": trigger, "attempt": attempt, "parent_job_id": parent_job_id})
    return dict(connection.execute("SELECT * FROM jobs WHERE job_id = %s", (job_id,)).fetchone())


class Operations:
    """Local (processing machine) operations: read and write."""

    hosted = False

    def __init__(self, db: Database, *, root: Path | None = None, config: Settings | None = None) -> None:
        self.db = db
        self.root = Path(root or data_root())
        self.settings = config or load_settings()
        self.audit = PostgresAuditStore(db)
        self.registry = RunRegistry(db)
        self._status: tuple[float, dict[str, Any]] = (0.0, {})

    # ------------------------------------------------------------ status

    def database_status(self) -> dict[str, Any]:
        now = time.monotonic()
        if now - self._status[0] > 5:
            try:
                info = self.db.ping()
                self._status = (now, {"reachable": True, "role": info.get("role"), "ssl": info.get("ssl")})
            except DatabaseUnavailable:
                self._status = (now, {"reachable": False})
        return self._status[1]

    def hidden_runs(self) -> set[str]:
        return self.registry.hidden_runs()

    # ------------------------------------------------------------ contracts and datasets

    def contracts(self) -> list[dict[str, Any]]:
        profiles = load_profiles(self.settings.mapping_profile_dir)
        out = []
        for name in UPLOADABLE_CONTRACTS:
            c = CONTRACTS[name]
            out.append({"name": name, "release": c.release, "observation": c.observation, "design_period": c.design_period,
                        "household_file": Path(c.household_path).name, "person_file": Path(c.person_path).name,
                        "household_required": sorted(set(c.household_fields.values())), "person_required": sorted(set(c.person_fields.values())),
                        "household_columns": c.expected_household_columns, "person_columns": c.expected_person_columns,
                        "mapping_profiles": [{"profile_id": p["profile_id"], "level": p["level"], "version": p["version"]}
                                             for p in profiles.values() if p.get("contract") == name and p.get("status") == "APPROVED"]})
        return out

    def limits(self) -> dict[str, Any]:
        s = self.settings
        return {"max_file_mb": s.max_file_bytes // (1024 * 1024), "max_files": s.max_files, "max_columns": s.max_columns,
                "uploads_enabled": s.uploads_enabled, "check_interval_minutes": s.check_interval_minutes}

    def _label_taken(self, release: str, observation: str, label: str) -> bool:
        stem = f"{release}_{observation}_{label}"
        on_disk = any((self.root / module / "runs" / stem).exists() for module in ("preprocessing", "fusion", "statistical"))
        in_db = self.db.fetchone("SELECT 1 FROM datasets WHERE release = %s AND observation = %s AND label = %s AND status NOT IN ('REJECTED', 'PREFLIGHT_BLOCKED')",
                                 (release, observation, label))
        return on_disk or bool(in_db) or bool(self.db.fetchone("SELECT 1 FROM runs WHERE run_id = %s", (stem,)))

    def _default_label(self, release: str, observation: str) -> str:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        for n in range(1, 100):
            label = f"u{day}_{n:02d}"
            if not self._label_taken(release, observation, label):
                return label
        raise OperationError("No free run label for today; give one explicitly.")

    def create_dataset(self, *, contract: str, synthetic: bool, idempotency_key: str | None, user: dict[str, Any]) -> dict[str, Any]:
        if contract not in UPLOADABLE_CONTRACTS:
            raise OperationError(f"Choose one of the supported layouts: {', '.join(UPLOADABLE_CONTRACTS)}.")
        c = CONTRACTS[contract]
        key = (idempotency_key or "").strip()[:100] or None
        if key:
            existing = self.db.fetchone("SELECT * FROM datasets WHERE idempotency_key = %s", (key,))
            if existing:
                return _clean(existing, drop=("input_root",))
        dataset_id = new_id()
        with self.db.transaction() as connection:
            connection.execute("""INSERT INTO datasets (dataset_id, contract_name, release, observation, source, data_class, status, idempotency_key,
                                  created_by, created_by_verified) VALUES (%s, %s, %s, %s, 'UPLOAD', %s, 'RECEIVING', %s, %s, TRUE)""",
                               (dataset_id, contract, c.release, c.observation, "SYNTHETIC" if synthetic else "INTERNAL_REAL", key, user["name"]))
            self.audit.append_operation("DATASET_CREATED", subject=dataset_id, actor=user["name"], actor_authenticated=True, actor_role=user["role"],
                                        connection=connection, details={"contract": contract, "data_class": "SYNTHETIC" if synthetic else "INTERNAL_REAL"})
        return self.dataset(dataset_id)

    def _dataset_row(self, dataset_id: str, connection=None, lock: bool = False) -> dict[str, Any]:
        sql = "SELECT * FROM datasets WHERE dataset_id = %s" + (" FOR UPDATE" if lock else "")
        row = (connection.execute(sql, (dataset_id,)).fetchone() if connection is not None else self.db.fetchone(sql, (dataset_id,)))
        if row is None:
            raise OperationError("Unknown dataset.", 404)
        return dict(row)

    def file_destination(self, dataset_id: str) -> tuple[str, Path]:
        dataset = self._dataset_row(dataset_id)
        if dataset["status"] != "RECEIVING":
            raise OperationError("Files can only be added before the pre-flight check has passed or been started.", 409)
        count = self.db.fetchone("SELECT COUNT(*) AS n FROM dataset_files WHERE dataset_id = %s", (dataset_id,))["n"]
        if count >= self.settings.max_files:
            raise OperationError(f"At most {self.settings.max_files} files can be uploaded per dataset.", 413)
        file_id = new_id()
        return file_id, dataset_dir(self.settings.upload_root, dataset_id) / "files" / f"{file_id}.csv"

    def add_file(self, dataset_id: str, file_id: str, destination: Path, info: dict[str, Any], *, display_name: str, relative_path: str | None,
                 user: dict[str, Any]) -> dict[str, Any]:
        with self.db.transaction() as connection:
            dataset = self._dataset_row(dataset_id, connection, lock=True)
            if dataset["status"] != "RECEIVING":
                raise OperationError("This dataset no longer accepts files.", 409)
            connection.execute("""INSERT INTO dataset_files (file_id, dataset_id, display_name, relative_path, size_bytes, sha256, content_fingerprint, encoding,
                                  stored_path, mtime_ns) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                               (file_id, dataset_id, display_name, relative_path, info["size_bytes"], info["sha256"], info["content_fingerprint"],
                                info["encoding"] + ("+nul" if info.get("nul_bytes") else ""), str(destination), info["mtime_ns"]))
            self.audit.append_operation("FILE_RECEIVED", subject=dataset_id, actor=user["name"], actor_authenticated=True, actor_role=user["role"],
                                        connection=connection, details={"file_id": file_id, "name": display_name, "bytes": info["size_bytes"], "sha256": info["sha256"]})
        return {"file_id": file_id, "name": display_name, "relative_path": relative_path, "bytes": info["size_bytes"], "sha256": info["sha256"],
                "encoding": info["encoding"]}

    def _files(self, dataset_id: str) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self.db.fetch("SELECT * FROM dataset_files WHERE dataset_id = %s ORDER BY created_utc", (dataset_id,))]
        for row in rows:
            row["nul_bytes"] = str(row.get("encoding") or "").endswith("+nul")
            row["encoding"] = str(row.get("encoding") or "").removesuffix("+nul")
        return rows

    def preflight(self, dataset_id: str, *, profile_id: str | None, user: dict[str, Any]) -> dict[str, Any]:
        dataset = self._dataset_row(dataset_id)
        if dataset["status"] not in ("RECEIVING", "PREFLIGHT_BLOCKED", "PREFLIGHT_PASSED"):
            raise OperationError("The pre-flight check cannot be repeated once validation has been requested.", 409)
        files = self._files(dataset_id)
        # Earlier registrations of the same on-server delivery are not "other deliveries": re-validating it is not a duplicate.
        same_path = dataset["input_root"] if dataset["source"] == "REGISTERED_PATH" else None
        others = [dict(r) for r in self.db.fetch(
            """SELECT f.dataset_id, f.sha256, f.content_fingerprint, f.created_utc FROM dataset_files f JOIN datasets d USING (dataset_id)
               WHERE f.dataset_id <> %s AND d.status NOT IN ('REJECTED', 'PREFLIGHT_BLOCKED', 'RECEIVING')
               AND (%s::text IS NULL OR d.input_root IS DISTINCT FROM %s)""", (dataset_id, same_path, same_path))]
        other_keys = [dataset_dir(self.settings.upload_root, r["dataset_id"]) / "keys_person.parquet" for r in self.db.fetch(
            """SELECT dataset_id FROM datasets WHERE contract_name = %s AND dataset_id <> %s AND status NOT IN ('REJECTED', 'PREFLIGHT_BLOCKED', 'RECEIVING')
               AND (%s::text IS NULL OR input_root IS DISTINCT FROM %s)""", (dataset["contract_name"], dataset_id, same_path, same_path))]
        report = run_preflight(dataset=dataset, files=files, other_files=others, other_key_files=other_keys, settings=self.settings,
                               workdir=dataset_dir(self.settings.upload_root, dataset_id), profile_id=profile_id)
        levels = report.pop("levels", {})
        fingerprint = "|".join(sorted(f"{levels.get(f['file_id'])}:{f['content_fingerprint']}" for f in files)) if files else None
        status = "PREFLIGHT_PASSED" if report["status"] == "PASSED" else "PREFLIGHT_BLOCKED"
        with self.db.transaction() as connection:
            current = self._dataset_row(dataset_id, connection, lock=True)
            if current["status"] not in ("RECEIVING", "PREFLIGHT_BLOCKED", "PREFLIGHT_PASSED"):
                raise OperationError("Validation was requested meanwhile; the pre-flight result was not changed.", 409)
            for file_id, level in levels.items():
                connection.execute("UPDATE dataset_files SET level = %s WHERE file_id = %s", (level, file_id))
            # A blocked dataset keeps accepting a corrected file set only by starting a new dataset (files are immutable records).
            connection.execute("""UPDATE datasets SET status = %s, preflight = %s, record_counts = %s, fingerprint = %s, mapping_profile = %s, updated_utc = now()
                                  WHERE dataset_id = %s""", (status, json.dumps(report, default=str), json.dumps(report.get("counts", {})), fingerprint,
                                                              profile_id, dataset_id))
            self.audit.append_operation("PREFLIGHT_COMPLETED", subject=dataset_id, actor=user["name"], actor_authenticated=True, actor_role=user["role"],
                                        connection=connection, details={"status": report["status"],
                                                                        "blocking": [f["code"] for f in report["findings"] if f["severity"] == "BLOCKING"]})
        return self.dataset(dataset_id)

    def confirm(self, dataset_id: str, *, label: str | None, confirmed: bool, idempotency_key: str | None, user: dict[str, Any]) -> dict[str, Any]:
        if not confirmed:
            raise OperationError("Confirm that the pre-flight report was reviewed before starting validation.")
        # The page sends one Idempotency-Key per confirmation, so a double click or a resent request returns the same job;
        # duplicate active jobs are impossible anyway (one active validation per dataset, enforced by a unique index).
        key = (idempotency_key or "").strip()[:100] or f"confirm:{dataset_id}:{new_id()}"
        existing = self.db.fetchone("SELECT job_id FROM jobs WHERE idempotency_key = %s", (key,))
        if existing:
            return self.job(existing["job_id"])
        dataset = self._dataset_row(dataset_id)
        if dataset["status"] != "PREFLIGHT_PASSED":
            raise OperationError("Validation can start only after a passed pre-flight check." if dataset["status"] != "QUEUED"
                                 else "Validation of this dataset was already requested.", 409)
        if dataset["label"]:                       # confirmed before and cancelled while queued: same label, nothing was produced
            label = dataset["label"]
        else:
            label = (label or "").strip().lower() or self._default_label(dataset["release"], dataset["observation"])
            if not LABEL_PATTERN.fullmatch(label):
                raise OperationError("Run label: 1-24 characters, lower-case letters, digits and underscores, starting with a letter or digit.")
            if self._label_taken(dataset["release"], dataset["observation"], label):
                raise OperationError(f"The label {label!r} is already used for this survey round; stored runs are never overwritten.", 409)
        with self.db.transaction() as connection:
            dataset = self._dataset_row(dataset_id, connection, lock=True)
            if dataset["status"] != "PREFLIGHT_PASSED":
                raise OperationError("Validation of this dataset was already requested.", 409)
            try:
                connection.execute("UPDATE datasets SET label = %s, confirmed_by = %s, confirmed_utc = now() WHERE dataset_id = %s", (label, user["name"], dataset_id))
            except UniqueViolation:
                raise OperationError(f"The label {label!r} is already used for this survey round.", 409) from None
            dataset["label"] = label
            job = enqueue_validation(connection, self.audit, dataset, trigger="MANUAL", actor=user["name"], verified=True, idempotency_key=key, role=user["role"])
        return self.job(job["job_id"])

    def reject(self, dataset_id: str, *, user: dict[str, Any]) -> dict[str, Any]:
        with self.db.transaction() as connection:
            dataset = self._dataset_row(dataset_id, connection, lock=True)
            if dataset["status"] not in ("RECEIVING", "PREFLIGHT_PASSED", "PREFLIGHT_BLOCKED"):
                raise OperationError("Only a dataset that has not been sent for validation can be rejected.", 409)
            connection.execute("UPDATE datasets SET status = 'REJECTED', updated_utc = now() WHERE dataset_id = %s", (dataset_id,))
            self.audit.append_operation("DATASET_REJECTED", subject=dataset_id, actor=user["name"], actor_authenticated=True, actor_role=user["role"],
                                        connection=connection, details={"previous_status": dataset["status"]})
        return self.dataset(dataset_id)

    def datasets(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.fetch("""SELECT d.dataset_id, d.contract_name, d.release, d.observation, d.source, d.data_class, d.status, d.label, d.created_by,
                                       d.created_utc, d.confirmed_by, d.confirmed_utc, d.record_counts,
                                       (SELECT COUNT(*) FROM dataset_files f WHERE f.dataset_id = d.dataset_id) AS files
                                FROM datasets d ORDER BY d.created_utc DESC LIMIT %s""", (limit,))
        return [_clean(r) for r in rows]

    def dataset(self, dataset_id: str) -> dict[str, Any]:
        row = _clean(self._dataset_row(dataset_id), drop=("input_root", "idempotency_key"))
        row["files"] = [_clean(f, drop=("stored_path", "mtime_ns", "dataset_id")) for f in self._files(dataset_id)]
        row["jobs"] = [_clean(j) for j in self.db.fetch("SELECT job_id, status, trigger, attempt, label, run_id, created_utc, finished_utc, error_class "
                                                        "FROM jobs WHERE dataset_id = %s ORDER BY created_utc DESC", (dataset_id,))]
        return row

    # ------------------------------------------------------------ jobs

    def jobs(self, *, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.fetch("""SELECT job_id, kind, status, trigger, dataset_id, run_id, label, attempt, requested_by, created_utc, started_utc, finished_utc,
                                       current_stage, error_class, error_message FROM jobs WHERE (%s::text IS NULL OR kind = %s)
                                ORDER BY created_utc DESC LIMIT %s""", (kind, kind, limit))
        return [_clean(r) for r in rows]

    def job(self, job_id: str) -> dict[str, Any]:
        row = self.db.fetchone("SELECT * FROM jobs WHERE job_id = %s", (job_id,)) if len(job_id or "") == 32 else None
        if row is None:
            raise OperationError("Unknown job.", 404)
        out = _clean(row, drop=("pid", "worker", "idempotency_key"))
        out["events"] = [_clean(e) for e in self.db.fetch("SELECT stage, status, message, created_utc FROM job_events WHERE job_id = %s ORDER BY event_id", (job_id,))]
        if row["kind"] == "INTEGRITY_CHECK":
            out["findings"] = [_clean(c) for c in self.db.fetch("SELECT target_kind, target_id, check_name, status, detail FROM integrity_checks "
                                                                "WHERE job_id = %s ORDER BY status <> 'FAILED', status <> 'CHANGED', check_id", (job_id,))]
        return out

    def retry(self, job_id: str, *, user: dict[str, Any]) -> dict[str, Any]:
        with self.db.transaction() as connection:
            job = connection.execute("SELECT * FROM jobs WHERE job_id = %s FOR UPDATE", (job_id,)).fetchone()
            if job is None:
                raise OperationError("Unknown job.", 404)
            if job["kind"] != "VALIDATION" or job["status"] not in RETRYABLE:
                reason = ("A run stopped by a quality check is not retried: the data or the method is the cause. Fix the data and upload it again."
                          if job["status"] == "FAILED_QA_GATE" else "Only a failed or interrupted validation can be retried.")
                raise OperationError(reason, 409)
            child = connection.execute("SELECT job_id FROM jobs WHERE parent_job_id = %s", (job_id,)).fetchone()
            if child:
                return self.job(child["job_id"])
            dataset = self._dataset_row(job["dataset_id"], connection, lock=True)
            new = enqueue_validation(connection, self.audit, dataset, trigger="RETRY", actor=user["name"], verified=True, role=user["role"],
                                     idempotency_key=f"retry:{job_id}", attempt=job["attempt"] + 1, parent_job_id=job_id)
        return self.job(new["job_id"])

    def cancel(self, job_id: str, *, user: dict[str, Any]) -> dict[str, Any]:
        with self.db.transaction() as connection:
            job = connection.execute("SELECT * FROM jobs WHERE job_id = %s FOR UPDATE", (job_id,)).fetchone()
            if job is None:
                raise OperationError("Unknown job.", 404)
            if job["status"] != "QUEUED":
                raise OperationError("Only a queued job can be cancelled. A running validation is never stopped half-way (its stages are "
                                     "immutable and resumable); wait for it to finish.", 409)
            connection.execute("UPDATE jobs SET status = 'CANCELLED', finished_utc = now() WHERE job_id = %s", (job_id,))
            job_event(connection, job_id, "queue", "INFO", "Cancelled before it started.")
            if job["kind"] == "VALIDATION":
                connection.execute("UPDATE runs SET status = 'FAILED' WHERE run_id = %s AND status = 'PENDING'", (job["run_id"],))
                connection.execute("UPDATE datasets SET status = 'PREFLIGHT_PASSED' WHERE dataset_id = %s AND status = 'QUEUED'", (job["dataset_id"],))
            self.audit.append_operation("JOB_CANCELLED", subject=job_id, actor=user["name"], actor_authenticated=True, actor_role=user["role"],
                                        connection=connection, details={"kind": job["kind"]})
        return self.job(job_id)

    def trigger_check(self, *, user: dict[str, Any] | None, trigger: str = "MANUAL", idempotency_key: str | None = None) -> dict[str, Any]:
        with self.db.transaction() as connection:
            active = connection.execute("SELECT job_id FROM jobs WHERE kind = 'INTEGRITY_CHECK' AND status IN ('QUEUED', 'RUNNING')").fetchone()
            if active:
                return {"job_id": active["job_id"], "already_active": True}
            key = idempotency_key or f"check:{new_id()}"
            earlier = connection.execute("SELECT job_id FROM jobs WHERE idempotency_key = %s", (key,)).fetchone()
            if earlier:
                return {"job_id": earlier["job_id"], "already_active": False, "duplicate": True}
            job_id = new_id()
            try:
                connection.execute("""INSERT INTO jobs (job_id, kind, status, trigger, idempotency_key, requested_by, requested_by_verified)
                                      VALUES (%s, 'INTEGRITY_CHECK', 'QUEUED', %s, %s, %s, %s)""",
                                   (job_id, trigger, key, user["name"] if user else "scheduler", user is not None))
            except UniqueViolation:
                raise OperationError("An integrity check is already queued or running.", 409) from None
            job_event(connection, job_id, "queue", "INFO", f"Integrity check queued ({trigger.lower()}).")
        return {"job_id": job_id, "already_active": False}

    # ------------------------------------------------------------ alerts and dashboard summary

    def notifications(self, *, include_acknowledged: bool = False, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.fetch("SELECT * FROM notifications WHERE (%s OR acknowledged_utc IS NULL) ORDER BY created_utc DESC LIMIT %s", (include_acknowledged, limit))
        return [_clean(r) for r in rows]

    def acknowledge(self, notification_id: int, *, user: dict[str, Any]) -> dict[str, Any]:
        count = self.db.execute("UPDATE notifications SET acknowledged_by = %s, acknowledged_utc = now() WHERE notification_id = %s AND acknowledged_utc IS NULL",
                                (user["name"], int(notification_id)))
        if not count:
            raise OperationError("Unknown or already acknowledged alert.", 404)
        return {"acknowledged": True}

    def summary(self) -> dict[str, Any]:
        runs = [_clean(r) for r in self.db.fetch("""SELECT run_id, release, observation, status, data_class, hosted_visible, records, published_utc,
                                                    registered_utc, left(manifest_sha256, 12) AS manifest FROM runs ORDER BY COALESCE(published_utc, registered_utc) DESC""")]
        check = self.db.fetchone("SELECT job_id, status, trigger, created_utc, finished_utc, error_class, result FROM jobs WHERE kind = 'INTEGRITY_CHECK' "
                                 "AND status NOT IN ('QUEUED', 'RUNNING', 'CANCELLED') ORDER BY created_utc DESC LIMIT 1")
        failed = [_clean(r) for r in self.db.fetch("""SELECT job_id, kind, status, run_id, label, created_utc, finished_utc, error_class, error_message
                                                      FROM jobs WHERE status IN ('FAILED', 'FAILED_QA_GATE', 'INTERRUPTED')
                                                      AND NOT EXISTS (SELECT 1 FROM jobs c WHERE c.parent_job_id = jobs.job_id)
                                                      AND NOT (kind = 'INTEGRITY_CHECK' AND EXISTS (SELECT 1 FROM jobs later WHERE later.kind = 'INTEGRITY_CHECK'
                                                               AND later.status = 'SUCCEEDED' AND later.created_utc > jobs.created_utc))
                                                      ORDER BY created_utc DESC LIMIT 10""")]
        active = [_clean(r) for r in self.db.fetch("SELECT job_id, kind, status, run_id, label, current_stage, created_utc, started_utc FROM jobs "
                                                   "WHERE status IN ('QUEUED', 'RUNNING') ORDER BY created_utc")]
        open_alerts = self.db.fetchone("SELECT COUNT(*) FILTER (WHERE severity = 'ERROR') AS errors, COUNT(*) AS total FROM notifications WHERE acknowledged_utc IS NULL")
        return {"backend": "postgres", "hosted": False, "database": self.database_status(), "runs": runs, "last_check": _clean(check), "failed_jobs": failed,
                "active_jobs": active, "open_alerts": dict(open_alerts or {}), "limits": self.limits()}


class HostedOperations:
    """Hosted (Vercel) view: the reader role sees only the hosted_* views; nothing is written."""

    hosted = True

    def __init__(self, db: Database) -> None:
        self.db = db
        self._status: tuple[float, dict[str, Any]] = (0.0, {})

    def database_status(self) -> dict[str, Any]:
        now = time.monotonic()
        if now - self._status[0] > 5:
            try:
                info = self.db.ping()
                self._status = (now, {"reachable": True, "role": info.get("role"), "ssl": info.get("ssl")})
            except DatabaseUnavailable:
                self._status = (now, {"reachable": False})
        return self._status[1]

    def hidden_runs(self) -> set[str]:
        return set()

    def summary(self) -> dict[str, Any]:
        runs = [_clean(r) for r in self.db.fetch("SELECT * FROM hosted_runs ORDER BY COALESCE(published_utc, registered_utc) DESC")]
        check = self.db.fetchone("SELECT job_id, status, trigger, created_utc, finished_utc, error_class FROM hosted_jobs WHERE kind = 'INTEGRITY_CHECK' "
                                 "AND status NOT IN ('QUEUED', 'RUNNING', 'CANCELLED') ORDER BY created_utc DESC LIMIT 1")
        findings = [_clean(r) for r in self.db.fetch("SELECT target_id, check_name, status, created_utc FROM hosted_integrity_checks "
                                                     "WHERE job_id = %s AND status <> 'PASSED'", (check["job_id"],))] if check else []
        verifications = [_clean(r) for r in self.db.fetch("SELECT * FROM hosted_audit_verifications ORDER BY run_id")]
        failed = [_clean(r) for r in self.db.fetch("SELECT * FROM hosted_jobs WHERE status IN ('FAILED', 'FAILED_QA_GATE', 'INTERRUPTED') ORDER BY created_utc DESC LIMIT 10")]
        return {"backend": "postgres", "hosted": True, "database": self.database_status(), "runs": runs, "last_check": _clean(check),
                "last_check_findings": findings, "audit_verifications": verifications, "failed_jobs": failed, "active_jobs": [], "open_alerts": None}
