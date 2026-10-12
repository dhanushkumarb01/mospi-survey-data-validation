"""Hosted-side client of the read gateway: drop-in replacements for the hosted PostgresAuditStore and HostedOperations.

Used on Vercel when ``MOSPI_AUDIT_BACKEND=gateway``:

``MOSPI_GATEWAY_URL``                 https://<hostname of the Cloudflare Tunnel route> (https is required except for loopback)
``MOSPI_GATEWAY_SECRET``              the request-signing secret shared with the gateway (32+ characters)
``MOSPI_CF_ACCESS_CLIENT_ID`` / ``MOSPI_CF_ACCESS_CLIENT_SECRET``   the Cloudflare Access service token (sent as headers)
``MOSPI_GATEWAY_TIMEOUT`` (8 s), ``MOSPI_GATEWAY_CACHE_SECONDS`` (5)
``MOSPI_GATEWAY_ALLOW_QUICK_TUNNEL=1``  required to use a temporary ``*.trycloudflare.com`` URL (no Cloudflare Access; the signature alone protects it)

Any failure (network, Cloudflare Access, signature, gateway or database) raises :class:`DatabaseUnavailable`, so the
hosted app behaves exactly as when the database itself is unreachable: requests that need review history return 503,
the status strip says "unreachable" and the bundled synthetic data is still served.  Secrets never appear in errors.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from mospi.db.connection import DatabaseUnavailable

from .signing import IDENTIFIER, configured_secret, sign

Transport = Callable[[str, dict[str, str], float], tuple[int, bytes]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):          # a redirect means Cloudflare Access wants a login: refuse it
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _urllib_transport(url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return response.status, response.read(32 * 1024 * 1024)
    except urllib.error.HTTPError as error:
        return error.code, b""


def _check_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url.strip())
    loopback = parts.hostname in ("127.0.0.1", "localhost", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and loopback):
        raise ValueError("MOSPI_GATEWAY_URL must be an https:// address (http is allowed for loopback testing only).")
    if not parts.hostname or parts.path not in ("", "/") or parts.query or parts.username:
        raise ValueError("MOSPI_GATEWAY_URL must be the gateway origin only, e.g. https://mospi-gateway.example.org")
    return f"{parts.scheme}://{parts.netloc}"


def is_quick_tunnel(url: str) -> bool:
    """A Cloudflare Quick Tunnel hostname (random ``*.trycloudflare.com``): temporary, and never behind Cloudflare Access."""
    host = (urllib.parse.urlsplit(url.strip()).hostname or "").lower()
    return host == "trycloudflare.com" or host.endswith(".trycloudflare.com")


class GatewayClient:
    def __init__(self, url: str, secret: str, *, access_id: str | None = None, access_secret: str | None = None, timeout: float = 8.0,
                 cache_seconds: float = 5.0, transport: Transport | None = None, allow_quick_tunnel: bool = False) -> None:
        self.origin = _check_url(url)
        self._secret = secret
        self._access = {"CF-Access-Client-Id": access_id, "CF-Access-Client-Secret": access_secret} if access_id and access_secret else {}
        # A Quick Tunnel has no Cloudflare Access layer, so the request signature is the only credential at the gateway's edge.
        # That is acceptable for a temporary demonstration only, so it must be switched on deliberately (MOSPI_GATEWAY_ALLOW_QUICK_TUNNEL=1).
        self.quick_tunnel = is_quick_tunnel(self.origin)
        if self.quick_tunnel and not allow_quick_tunnel:
            raise ValueError("MOSPI_GATEWAY_URL is a temporary Cloudflare Quick Tunnel (trycloudflare.com), which has no Cloudflare Access layer. "
                             "Use a named tunnel with an Access service token, or set MOSPI_GATEWAY_ALLOW_QUICK_TUNNEL=1 for a temporary demonstration.")
        if self.quick_tunnel:
            self._access = {}                                  # Access cannot protect this hostname: never send the service token to it
        self.timeout, self.cache_seconds = timeout, cache_seconds
        self._transport = transport or _urllib_transport
        self._cache: dict[str, tuple[float, bytes]] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"GatewayClient({self.origin})"

    def get(self, path: str, *, cache: bool = True) -> Any:
        now = time.monotonic()
        if cache:
            with self._lock:
                hit = self._cache.get(path)
            if hit and hit[0] > now:
                return json.loads(hit[1])            # a fresh copy each time: callers may modify what they get
        headers = {"Accept": "application/json", "User-Agent": "mospi-hosted/1", **self._access, **sign(self._secret, "GET", path)}
        try:
            status, body = self._transport(self.origin + path, headers, self.timeout)
        except (OSError, ValueError) as error:          # URLError, timeouts, TLS and DNS failures are OSErrors
            raise DatabaseUnavailable(f"The hosted read gateway is not reachable ({type(error).__name__}).") from None
        if status != 200:
            reason = {401: "the gateway refused the request signature", 403: "Cloudflare Access refused the service token",
                      429: "the gateway is rate-limiting requests", 502: "the tunnel is up but the gateway is not running", 503: "the gateway cannot reach PostgreSQL",
                      530: "the Cloudflare Tunnel is down"}.get(status, "redirected to a login page" if 300 <= status < 400 else "unexpected response")
            raise DatabaseUnavailable(f"The hosted read gateway did not answer ({status}: {reason}).")
        try:
            value = json.loads(body)
        except ValueError:
            raise DatabaseUnavailable("The hosted read gateway returned a response that is not JSON.") from None
        if cache and self.cache_seconds > 0:
            with self._lock:
                self._cache[path] = (now + self.cache_seconds, body)
        return value


def _key(run: str | Path) -> str:
    return run.name if isinstance(run, Path) else str(run)


def _valid(*values: str) -> bool:
    return all(IDENTIFIER.fullmatch(v) for v in values)


class GatewayAuditStore:
    """Read-only audit store over the gateway (same results as PostgresAuditStore(reader, hosted=True))."""

    backend, writable, hosted = "postgres", False, True

    def __init__(self, client: GatewayClient) -> None:
        self.client = client

    def append(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise PermissionError("This instance reads the audit trail only.")

    def history(self, run: str | Path, case_id: str) -> list[dict[str, Any]]:
        key = _key(run)
        return self.client.get(f"/v1/runs/{key}/cases/{case_id}/history", cache=False) if _valid(key, str(case_id)) else []

    def latest_statuses(self, run: str | Path) -> dict[str, str]:
        key = _key(run)
        return self.client.get(f"/v1/runs/{key}/statuses") if _valid(key) else {}

    def all_events(self, run: str | Path) -> list[dict[str, Any]]:
        key = _key(run)
        return self.client.get(f"/v1/runs/{key}/events") if _valid(key) else []

    def verify(self, run: str | Path) -> dict[str, Any]:
        key = _key(run)
        if not _valid(key):
            return {"status": "NOT_VERIFIED_YET", "events": None, "detail": "No chain verification has been recorded for this run."}
        return self.client.get(f"/v1/runs/{key}/verification")


class GatewayOperations:
    """Hosted operations view over the gateway (same results as HostedOperations(reader))."""

    hosted = True

    def __init__(self, client: GatewayClient) -> None:
        self.client = client
        self._status: tuple[float, dict[str, Any]] = (0.0, {})

    def database_status(self) -> dict[str, Any]:
        now = time.monotonic()
        if now - self._status[0] > 5:
            try:
                info = self.client.get("/v1/status", cache=False)
                self._status = (now, {"reachable": True, "role": info.get("role"), "ssl": info.get("ssl"), "via": "gateway",
                                      **({"tunnel": "quick (temporary)"} if self.client.quick_tunnel else {})})
            except DatabaseUnavailable:
                self._status = (now, {"reachable": False, "via": "gateway"})
        return self._status[1]

    def hidden_runs(self) -> set[str]:
        return set()

    def summary(self) -> dict[str, Any]:
        summary = dict(self.client.get("/v1/summary"))
        summary["database"] = {**(summary.get("database") or {}), "via": "gateway"}
        return summary


def from_env() -> tuple[GatewayAuditStore, GatewayOperations]:
    url = os.environ.get("MOSPI_GATEWAY_URL", "").strip()
    if not url:
        raise ValueError("MOSPI_AUDIT_BACKEND=gateway needs MOSPI_GATEWAY_URL.")
    from mospi.db.config import int_setting
    client = GatewayClient(url, configured_secret(), access_id=os.environ.get("MOSPI_CF_ACCESS_CLIENT_ID", "").strip() or None,
                           access_secret=os.environ.get("MOSPI_CF_ACCESS_CLIENT_SECRET", "").strip() or None,
                           timeout=float(int_setting("MOSPI_GATEWAY_TIMEOUT", 8)), cache_seconds=float(int_setting("MOSPI_GATEWAY_CACHE_SECONDS", 5)),
                           allow_quick_tunnel=os.environ.get("MOSPI_GATEWAY_ALLOW_QUICK_TUNNEL", "").strip() == "1")
    return GatewayAuditStore(client), GatewayOperations(client)
