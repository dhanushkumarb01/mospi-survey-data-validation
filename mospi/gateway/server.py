"""The hosted read gateway: a fixed set of read-only routes over the ``hosted_*`` views, behind a Cloudflare Tunnel.

Routes (GET only; everything else is 405 or 404 after authentication, and nothing is listed without it):

    /v1/status                                   reader login works (role, TLS) - the hosted "database reachable" signal
    /v1/summary                                  HostedOperations.summary(): cleared runs, last check, verifications, failed jobs
    /v1/runs/{run}/statuses                      latest decision per case
    /v1/runs/{run}/events                        decision events without comments, snapshots or corrected values
    /v1/runs/{run}/verification                  last chain verification recorded on this machine
    /v1/runs/{run}/cases/{case}/history          one case's events (same columns as above)

Every request must be signed (mospi/gateway/signing.py).  The gateway listens on the loopback interface only and
connects to PostgreSQL as ``mospi_reader`` on the loopback interface; it refuses to start if that login is any other
role or is not read-only, so even a bug here cannot write or read a base table.  Unknown paths, other methods,
request bodies, bad signatures, replays and floods are refused before any database call.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import threading
import time
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from mospi.db.connection import DatabaseUnavailable

from .signing import IDENTIFIER, SigningError, Verifier

LOG = logging.getLogger("MoSPI.gateway")
LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1", ""}
SECURITY_HEADERS = [(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]


def _identifier(value: str, what: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise HTTPException(404, f"Unknown {what}.")
    return value


class _Window:
    """Requests per rolling minute (fixed one-minute buckets), shared by the process."""

    def __init__(self, limit: int) -> None:
        self.limit, self._bucket, self._count, self._lock = limit, 0, 0, threading.Lock()

    def allow(self, now: float) -> bool:
        with self._lock:
            bucket = int(now // 60)
            if bucket != self._bucket:
                self._bucket, self._count = bucket, 0
            self._count += 1
            return self._count <= self.limit


def _is_loopback(host: str | None) -> bool:
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


class Guard:
    """ASGI middleware: method, body, host, loopback peer, rate limits and signature - all before routing."""

    def __init__(self, app: Callable, *, verifier: Verifier, allowed_hosts: set[str] | None, loopback_only: bool,
                 rate_per_minute: int, failures_per_minute: int) -> None:
        self.app, self.verifier, self.allowed_hosts, self.loopback_only = app, verifier, allowed_hosts, loopback_only
        self.requests, self.failures = _Window(rate_per_minute), _Window(failures_per_minute)

    @staticmethod
    async def _reply(send, status: int, detail: str) -> None:
        body = ('{"detail": "%s"}' % detail).encode()
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            if scope["type"] == "lifespan":
                return await self.app(scope, receive, send)
            return None                                      # no websockets
        started, now = time.perf_counter(), time.time()
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        target = scope.get("raw_path", scope["path"].encode()).decode("latin-1")
        if scope.get("query_string"):
            target += "?" + scope["query_string"].decode("latin-1")
        status_box = {"status": 0}

        async def tracked_send(message):
            if message["type"] == "http.response.start":
                status_box["status"] = message["status"]
                message["headers"] = [h for h in message.get("headers", []) if h[0].lower() != b"server"] + SECURITY_HEADERS
            await send(message)

        try:
            if self.loopback_only and not _is_loopback((scope.get("client") or ("",))[0]):
                return await self._reply(tracked_send, 403, "forbidden")
            if self.allowed_hosts is not None and headers.get("host", "").split(":")[0].lower() not in self.allowed_hosts:
                return await self._reply(tracked_send, 421, "unknown host")
            if not self.requests.allow(now):
                return await self._reply(tracked_send, 429, "too many requests")
            if scope["method"] != "GET":
                return await self._reply(tracked_send, 405, "method not allowed")
            if headers.get("content-length", "0") not in ("", "0") or "transfer-encoding" in headers:
                return await self._reply(tracked_send, 400, "request body not allowed")
            if len(target) > 600:
                return await self._reply(tracked_send, 414, "request target too long")
            try:
                self.verifier.verify("GET", target, headers, now=now)
            except SigningError as error:
                limited = not self.failures.allow(now)
                LOG.warning("refused request: %s (cf-ray %s)", error, headers.get("cf-ray", "-"))
                return await self._reply(tracked_send, 429 if limited else 401, "too many requests" if limited else "authentication required")
            return await self.app(scope, receive, tracked_send)
        finally:
            LOG.info("%s %s -> %s in %.0f ms (cf-ray %s)", scope.get("method"), scope["path"], status_box["status"],
                     (time.perf_counter() - started) * 1000, headers.get("cf-ray", "-"))


def create_gateway(audit: Any, operations: Any, *, secrets_: list[str], allowed_hosts: set[str] | None = None, loopback_only: bool = True,
                   rate_per_minute: int = 600, failures_per_minute: int = 30) -> Any:
    """``audit`` is a hosted PostgresAuditStore and ``operations`` a HostedOperations, both on the reader role."""
    if not getattr(audit, "hosted", False) or getattr(audit, "writable", True) or not getattr(operations, "hosted", False):
        raise ValueError("The gateway serves the hosted (read-only) audit store and operations view only.")
    app = FastAPI(title="MoSPI hosted read gateway", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(DatabaseUnavailable)
    async def database_unavailable(request, error: DatabaseUnavailable) -> JSONResponse:
        LOG.error("database unavailable: %s", error)
        return JSONResponse({"detail": "The operational database is unavailable."}, status_code=503)

    def reply(value: Any) -> JSONResponse:
        return JSONResponse(jsonable_encoder(value))

    @app.get("/v1/status")
    def status() -> JSONResponse:
        info = operations.db.ping()
        return reply({"reachable": True, "role": info.get("role"), "ssl": info.get("ssl"), "via": "gateway"})

    @app.get("/v1/summary")
    def summary() -> JSONResponse:
        return reply(operations.summary())

    @app.get("/v1/runs/{run}/statuses")
    def statuses(run: str) -> JSONResponse:
        return reply(audit.latest_statuses(_identifier(run, "run")))

    @app.get("/v1/runs/{run}/events")
    def events(run: str) -> JSONResponse:
        return reply(audit.all_events(_identifier(run, "run")))

    @app.get("/v1/runs/{run}/verification")
    def verification(run: str) -> JSONResponse:
        return reply(audit.verify(_identifier(run, "run")))

    @app.get("/v1/runs/{run}/cases/{case}/history")
    def history(run: str, case: str) -> JSONResponse:
        return reply(audit.history(_identifier(run, "run"), _identifier(case, "case")))

    verifier = Verifier(secrets_)
    return Guard(app, verifier=verifier, allowed_hosts=allowed_hosts, loopback_only=loopback_only,
                 rate_per_minute=rate_per_minute, failures_per_minute=failures_per_minute)


# ------------------------------------------------------------------ configuration (environment only)


def reader_url() -> str:
    """``MOSPI_GATEWAY_DATABASE_URL``, or the app URL with the reader role and password; always a loopback host."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from mospi.db.config import load_env_file
    from mospi.db.migrate import READER_ROLE
    load_env_file()
    url = os.environ.get("MOSPI_GATEWAY_DATABASE_URL", "").strip()
    if not url:
        base, password = os.environ.get("MOSPI_DATABASE_URL", "").strip(), os.environ.get("MOSPI_DB_READER_PASSWORD", "")
        if not base or not password:
            raise RuntimeError("Set MOSPI_GATEWAY_DATABASE_URL, or MOSPI_DATABASE_URL and MOSPI_DB_READER_PASSWORD.")
        url = make_conninfo(base, user=READER_ROLE, password=password)
    host = str(conninfo_to_dict(url).get("host") or "")
    if any(part.strip() not in LOOPBACK_NAMES for part in host.split(",")):
        raise RuntimeError("The gateway connects to PostgreSQL on this computer only (host localhost or 127.0.0.1).")
    return url


def build_from_env() -> Any:
    from mospi.db.audit import PostgresAuditStore
    from mospi.db.connection import Database
    from mospi.db.config import int_setting
    from mospi.db.migrate import READER_ROLE
    from mospi.ingest.service import HostedOperations
    from .signing import configured_secret
    secrets_ = [configured_secret()]
    if os.environ.get("MOSPI_GATEWAY_SECRET_PREVIOUS", "").strip():
        secrets_.append(configured_secret("MOSPI_GATEWAY_SECRET_PREVIOUS"))
    db = Database(reader_url(), application_name="mospi-gateway", max_connections=int_setting("MOSPI_GATEWAY_DB_CONNECTIONS", 4))
    row = db.fetchone("SELECT current_user AS role, current_setting('transaction_read_only') AS read_only")
    if not row or row["role"] != READER_ROLE or row["read_only"] != "on":
        raise RuntimeError(f"The gateway must log in as the read-only role {READER_ROLE}; refusing to start as {row and row['role']!r}.")
    hostname = os.environ.get("MOSPI_GATEWAY_HOSTNAME", "").strip().lower()
    allowed = {hostname, "127.0.0.1", "localhost"} if hostname else None
    return create_gateway(PostgresAuditStore(db, hosted=True), HostedOperations(db), secrets_=secrets_, allowed_hosts=allowed,
                          rate_per_minute=int_setting("MOSPI_GATEWAY_RATE_PER_MINUTE", 600))
