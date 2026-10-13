"""Routes of the Upload & validate page, the jobs ledger, integrity checks and alerts.

Authorisation (on top of the sign-in middleware of api.py):
* sign-in is mandatory for every route here, even on a loopback instance;
* uploads, pre-flight, starting validation, retry, cancel and manual checks: the ``run`` capability (administrators);
* reading datasets, jobs, checks and alerts: the ``operations`` capability (administrators and analysts); the dashboard
  status (``/api/operations``): any role.
* never on a hosted or review-only instance: those have no operations store that can be written.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from mospi.auth import can

READERS = "operations"
WRITERS = "run"
UNAVAILABLE = ("Upload & validate runs on the processing machine with the PostgreSQL operational store "
               "(MOSPI_DATABASE_URL); it is not available on this instance.")


def register(app: FastAPI, *, operations: Any, signed_in: bool, review_only: bool) -> None:
    from mospi.ingest.service import OperationError
    from mospi.ingest.storage import FileReceiver, UploadRejected, safe_display_name, safe_relative_path

    writable = operations is not None and not getattr(operations, "hosted", True) and not review_only

    def user_for(request: Request, capability: str) -> dict[str, Any]:
        user = getattr(request.state, "user", None)
        if not signed_in:
            raise HTTPException(403, "Sign-in is required for this action, so that every upload and validation is attributed to a verified person.")
        if user is None:
            raise HTTPException(401, "Authentication required.")
        if not can(user, capability):
            raise HTTPException(403, "Your role cannot do this." if capability == WRITERS else "Your role cannot see operational records.")
        return user

    def local(request: Request, capability: str) -> dict[str, Any]:
        user = user_for(request, capability)
        if not writable:
            raise HTTPException(404 if operations is None else 403, UNAVAILABLE)
        return user

    def call(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except OperationError as error:
            raise HTTPException(error.status, str(error)) from error
        except UploadRejected as error:
            raise HTTPException(error.status, str(error)) from error

    @app.get("/api/operations")
    def operations_status() -> dict[str, Any]:
        """Run registry, last integrity check, failed and active jobs: what the dashboard needs to say whether data is current."""
        if operations is None:
            return {"backend": "sqlite", "available": False, "reason": UNAVAILABLE}
        return {"available": True, "uploads": writable, **operations.summary()}

    @app.get("/api/ingest/contracts")
    def ingest_contracts(request: Request) -> dict[str, Any]:
        local(request, READERS)
        return {"contracts": operations.contracts(), "limits": operations.limits()}

    @app.get("/api/datasets")
    def list_datasets(request: Request, limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
        local(request, READERS)
        return {"datasets": operations.datasets(limit)}

    @app.post("/api/datasets")
    def create_dataset(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        user = local(request, WRITERS)
        return call(operations.create_dataset, contract=str(payload.get("contract") or ""), synthetic=bool(payload.get("synthetic")),
                    idempotency_key=request.headers.get("idempotency-key"), user=user)

    @app.get("/api/datasets/{dataset_id}")
    def get_dataset(dataset_id: str, request: Request) -> dict[str, Any]:
        local(request, READERS)
        return call(operations.dataset, dataset_id)

    @app.put("/api/datasets/{dataset_id}/files")
    async def upload_file(dataset_id: str, request: Request, name: str = Query(..., max_length=300), path: str | None = Query(None, max_length=600)) -> dict[str, Any]:
        """Stream one file (raw request body, any size up to the limit; never buffered in memory)."""
        user = local(request, WRITERS)
        display, relative = call(safe_display_name, name), call(safe_relative_path, path)
        declared = request.headers.get("content-length")
        limit = operations.settings.max_file_bytes
        if declared and declared.isdigit() and int(declared) > limit:
            raise HTTPException(413, f"The file is larger than the configured limit of {limit // (1024 * 1024):,} MB.")
        file_id, destination = await run_in_threadpool(call, operations.file_destination, dataset_id)
        receiver = FileReceiver(destination, limit)
        try:
            async for chunk in request.stream():
                receiver.write(chunk)
            info = await run_in_threadpool(receiver.finish)
        except UploadRejected as error:
            receiver.abort()
            raise HTTPException(error.status, str(error)) from error
        except BaseException:
            receiver.abort()
            raise
        return await run_in_threadpool(call, operations.add_file, dataset_id, file_id, destination, info, display_name=display, relative_path=relative, user=user)

    @app.post("/api/datasets/{dataset_id}/preflight")
    def preflight(dataset_id: str, request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        user = local(request, WRITERS)
        return call(operations.preflight, dataset_id, profile_id=(payload or {}).get("mapping_profile") or None, user=user)

    @app.post("/api/datasets/{dataset_id}/confirm")
    def confirm(dataset_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
        user = local(request, WRITERS)
        return call(operations.confirm, dataset_id, label=payload.get("label"), confirmed=payload.get("confirm") is True,
                    idempotency_key=request.headers.get("idempotency-key"), user=user)

    @app.post("/api/datasets/{dataset_id}/reject")
    def reject(dataset_id: str, request: Request) -> dict[str, Any]:
        user = local(request, WRITERS)
        return call(operations.reject, dataset_id, user=user)

    @app.get("/api/jobs")
    def list_jobs(request: Request, kind: str | None = Query(None, pattern="^(VALIDATION|INTEGRITY_CHECK)$"), limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
        local(request, READERS)
        return {"jobs": operations.jobs(kind=kind, limit=limit)}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, request: Request) -> dict[str, Any]:
        local(request, READERS)
        return call(operations.job, job_id)

    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: str, request: Request) -> dict[str, Any]:
        user = local(request, WRITERS)
        return call(operations.retry, job_id, user=user)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str, request: Request) -> dict[str, Any]:
        user = local(request, WRITERS)
        return call(operations.cancel, job_id, user=user)

    @app.post("/api/checks")
    def run_check(request: Request) -> dict[str, Any]:
        user = local(request, WRITERS)
        return call(operations.trigger_check, user=user)

    @app.get("/api/notifications")
    def notifications(request: Request, all: bool = False) -> dict[str, Any]:
        local(request, READERS)
        return {"notifications": operations.notifications(include_acknowledged=all)}

    @app.post("/api/notifications/{notification_id}/ack")
    def acknowledge(notification_id: int, request: Request) -> dict[str, Any]:
        user = local(request, READERS)
        return call(operations.acknowledge, notification_id, user=user)
