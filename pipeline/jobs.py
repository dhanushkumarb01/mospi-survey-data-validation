"""Batch validation jobs started from the review workspace (plan W8.7).

A job is one run of :func:`pipeline.run.run_pipeline` (every stage, quality
gates included) for a supported, already-prepared survey delivery.  It runs in
its own process so the web service stays responsive; its state is a small
JSON record and a log under ``pipeline/jobs/``, so a restarted service still
knows every job it started.

    python -m pipeline.jobs run pipeline/jobs/<job_id>.json     # what the service spawns

Rules
* Only supported inputs (``pipeline.run.PRESETS``: prepared persons of a
  documented release contract).  Raw file upload is not offered: a delivery
  must be prepared first (``preprocessing``), which checks its layout.
* Stage runs are immutable: a label that already has a fusion run for the
  release is refused, never overwritten.
* One job at a time (the 2025 batch needs several GB of memory).
* A job whose process has disappeared without finishing is reported as
  INTERRUPTED, not as running.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LABEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,23}$")
ACTIVE = {"STARTING", "RUNNING"}
STAGE_NAMES = ("peer", "statistical", "contextual", "ml", "pattern", "historical", "integrity", "fusion")
TAIL_LINES = 40


class JobError(ValueError):
    """A request the job manager refuses (shown to the user as is)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, record: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    os.replace(temporary, path)


def _alive(pid: int | None) -> bool:
    """Whether a process exists, without signalling it (os.kill would terminate it on Windows)."""
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259                                  # STILL_ACTIVE
    try:
        os.waitpid(int(pid), os.WNOHANG)      # reap our own finished child so it is not seen as alive
    except (ChildProcessError, OSError):
        pass
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def default_datasets(root: Path) -> dict[str, dict[str, Any]]:
    """Supported inputs: the release presets of pipeline.run, resolved under ``root``."""
    from .run import PRESETS
    datasets = {}
    for release, preset in PRESETS.items():
        datasets[release] = {"prepared": str(root / preset["prepared"]), "history": [str(root / h) for h in preset["history"]],
                             "revisit_prepared": str(root / preset["revisit_prepared"]) if preset.get("revisit_prepared") else None,
                             "revisit_peer": str(root / preset["revisit_peer"]) if preset.get("revisit_peer") else None}
    return datasets


class JobManager:
    def __init__(self, root: Path, datasets: dict[str, dict[str, Any]] | None = None, python: str | None = None) -> None:
        self.root = Path(root)
        self.folder = self.root / "pipeline" / "jobs"
        self.datasets = datasets if datasets is not None else default_datasets(self.root)
        self.python = python or sys.executable

    # ------------------------------------------------------------ inputs

    def _fusion_runs(self, release: str) -> dict[str, str]:
        """Completed fusion runs of a release: directory name -> run label."""
        runs, found = self.root / "fusion" / "runs", {}
        for directory in sorted(runs.glob("*")) if runs.is_dir() else []:
            meta_path = directory / "run_metadata.json"
            if meta_path.is_file() and (directory / "fused_cases.parquet").is_file():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if str(meta.get("release")) == release:
                    found[directory.name] = str(meta.get("run_id"))
        return found

    def inputs(self) -> list[dict[str, Any]]:
        """Supported deliveries with what the user needs to choose: availability, size, existing run labels."""
        rows = []
        for release, spec in self.datasets.items():
            prepared = Path(spec["prepared"])
            row: dict[str, Any] = {"release": release, "available": prepared.is_file(), "prepared_file": prepared.name,
                                   "preparation_run": prepared.parent.name, "history_releases": len(spec.get("history") or []),
                                   "includes_revisit": bool(spec.get("revisit_prepared"))}
            if prepared.is_file():
                meta_path = prepared.parent / "run_metadata.json"
                if meta_path.is_file():
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    row.update({"observation": meta.get("observation"), "design_period": meta.get("design_period")})
                try:
                    import pyarrow.parquet as pq
                    row["records"] = int(pq.ParquetFile(prepared).metadata.num_rows)
                except Exception:   # noqa: BLE001 - informational only
                    row["records"] = None
            else:
                row["reason"] = "The prepared file for this release is not present on this server."
            existing = self._fusion_runs(release)
            row["existing_runs"] = sorted(existing)
            row["existing_labels"] = sorted(set(existing.values()))
            rows.append(row)
        return rows

    # ------------------------------------------------------------ jobs

    def _path(self, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", job_id or ""):
            raise JobError("Unknown job.", 404)
        return self.folder / f"{job_id}.json"

    def _refresh(self, record: dict[str, Any]) -> dict[str, Any]:
        if record.get("status") in ACTIVE and not _alive(record.get("pid")):
            # The runner writes its final state itself; re-read once in case it just did.
            fresh = json.loads(self._path(record["job_id"]).read_text(encoding="utf-8"))
            if fresh.get("status") in ACTIVE:
                fresh.update(status="INTERRUPTED", finished_utc=_now(),
                             error="The batch process ended without reporting a result (the server may have restarted). Start the batch again with a new label.")
                _write(self._path(record["job_id"]), fresh)
            record = fresh
        log = Path(record.get("log", ""))
        if log.is_file():
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            record["log_tail"] = [line[:400] for line in lines[-TAIL_LINES:]]
            record["current_stage"] = next((m.group(1) for line in reversed(lines) if (m := re.search(r"MoSPI\.pipeline (?:run|reuse) (\w+)", line))), None)
        return record

    def list(self) -> list[dict[str, Any]]:
        if not self.folder.is_dir():
            return []
        records = []
        for path in self.folder.glob("*.json"):
            try:
                records.append(self._refresh(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(records, key=lambda r: r.get("created_utc", ""), reverse=True)

    def get(self, job_id: str) -> dict[str, Any]:
        path = self._path(job_id)
        if not path.is_file():
            raise JobError("Unknown job.", 404)
        return self._refresh(json.loads(path.read_text(encoding="utf-8")))

    def start(self, release: str, label: str, *, actor: str | None = None, actor_verified: bool = False,
              reuse_label: str | None = None, rerun: list[str] | None = None) -> dict[str, Any]:
        spec = self.datasets.get(release)
        if spec is None:
            raise JobError(f"Release {release!r} is not a supported input. Supported: {', '.join(sorted(self.datasets))}.")
        if not Path(spec["prepared"]).is_file():
            raise JobError(f"The prepared file for release {release} is not present on this server; it must be prepared first.", 409)
        label = (label or "").strip().lower()
        if not LABEL_PATTERN.fullmatch(label):
            raise JobError("Run label: 1-24 characters, lower-case letters, digits and underscores, starting with a letter or digit (for example v2_2 or oct_batch).")
        if label in self._fusion_runs(release).values():
            raise JobError(f"Release {release} already has a run labelled {label!r}. Stored runs are never overwritten; choose a new label.", 409)
        rerun = [s for s in (rerun or []) if s]
        if reuse_label:
            reuse_label = reuse_label.strip().lower()
            if reuse_label not in self._fusion_runs(release).values():
                raise JobError(f"There is no completed run labelled {reuse_label!r} for release {release} to reuse.")
            unknown = sorted(set(rerun) - set(STAGE_NAMES))
            if unknown or not rerun:
                raise JobError(f"When reusing an earlier run, name the stages to recompute ({', '.join(STAGE_NAMES)}).")
        elif rerun:
            raise JobError("Stages to recompute can only be chosen together with an earlier run to reuse.")
        self.folder.mkdir(parents=True, exist_ok=True)
        running = [job for job in self.list() if job.get("status") in ACTIVE]
        if running:
            raise JobError(f"A batch is already running (release {running[0]['release']}, label {running[0]['label']}). Wait for it to finish.", 409)
        job_id = uuid.uuid4().hex
        path = self._path(job_id)
        record = {"job_id": job_id, "release": release, "label": label, "reuse_label": reuse_label, "rerun": rerun, "status": "STARTING",
                  "created_utc": _now(), "actor": actor or "", "actor_verified": bool(actor_verified), "roots": str(self.root),
                  "inputs": spec, "log": str(self.folder / f"{job_id}.log")}
        _write(path, record)
        with open(record["log"], "ab") as log:
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            process = subprocess.Popen([self.python, "-m", "pipeline.jobs", "run", str(path)], cwd=str(Path(__file__).resolve().parents[1]),
                                       stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags,
                                       start_new_session=os.name != "nt")
        record = json.loads(path.read_text(encoding="utf-8"))
        record.setdefault("pid", process.pid)
        if record.get("status") == "STARTING":
            record["pid"] = process.pid
            _write(path, record)
        return record


def run_job(path: Path) -> int:
    """Executed in the job's own process: run the batch and record the outcome."""
    from .qa import QAGateFailure
    from .run import Inputs, code_version, run_pipeline
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update(status="RUNNING", pid=os.getpid(), started_utc=_now(), code_version=code_version())
    _write(path, record)
    spec, root = record["inputs"], Path(record["roots"])
    started = time.perf_counter()
    try:
        inputs = Inputs(Path(spec["prepared"]), None, None, [Path(p) for p in spec.get("history") or []],
                        Path(spec["revisit_prepared"]) if spec.get("revisit_prepared") else None,
                        Path(spec["revisit_peer"]) if spec.get("revisit_peer") else None)
        result = run_pipeline(inputs, record["label"], roots=root, reuse_suffix=record.get("reuse_label"), rerun=tuple(record.get("rerun") or ()))
        fusion = Path(result["fusion"])
        report = json.loads((fusion / "fusion_report.json").read_text(encoding="utf-8"))
        record.update(status="COMPLETED", fusion_run=fusion.name, stage_runs={k: str(v) for k, v in result.items() if k not in ("timing_seconds", "qa")},
                      timing_seconds=result["timing_seconds"], qa={k: v.get("status") for k, v in result["qa"].items()},
                      summary={"records": report.get("records_processed"), "check_now": report.get("check_now_cases"), "tiers": report.get("tier_counts"),
                               "fsu_alerts": report.get("group_alerts")})
        code = 0
    except QAGateFailure as error:
        record.update(status="FAILED_QA_GATE", error=str(error))
        code = 2
    except Exception as error:   # noqa: BLE001 - every failure must reach the user, not only expected ones
        record.update(status="FAILED", error=f"{type(error).__name__}: {error}"[:2000], traceback=traceback.format_exc()[-4000:])
        code = 1
    record.update(finished_utc=_now(), total_seconds=round(time.perf_counter() - started, 1))
    _write(path, record)
    reports = root / "pipeline" / "runs"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"{record['release']}_{record['label']}.json").write_text(json.dumps({**{k: record.get(k) for k in (
        "release", "label", "status", "code_version", "reuse_label", "rerun", "timing_seconds", "qa", "error", "total_seconds", "fusion_run")},
        "started_from": "workspace", "job_id": record["job_id"], "actor": record.get("actor"), "actor_verified": record.get("actor_verified")},
        indent=2, default=str), encoding="utf-8")
    return code


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "run":
        return run_job(Path(sys.argv[2]))
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
