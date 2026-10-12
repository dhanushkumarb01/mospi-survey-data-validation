"""Hosted read gateway commands.

    python -m mospi.gateway secret                 # print a new random signing secret (put it in .env and in Vercel)
    python -m mospi.gateway serve [--port 8787] [--log-file F]   # run the gateway on 127.0.0.1 (cloudflared forwards the public hostname here)
    python -m mospi.gateway check [--url URL]      # probe the gateway (default MOSPI_GATEWAY_URL) and its access controls

Reads the local, git-ignored .env for values not already in the environment.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import sys


def _probe(url: str) -> dict[str, object]:
    """Positive and negative checks against a running gateway, as Vercel would reach it."""
    from .client import GatewayClient, _check_url, _urllib_transport, is_quick_tunnel
    from .signing import configured_secret, sign
    origin, secret = _check_url(url), configured_secret()
    access_id, access_secret = os.environ.get("MOSPI_CF_ACCESS_CLIENT_ID", "").strip(), os.environ.get("MOSPI_CF_ACCESS_CLIENT_SECRET", "").strip()
    access = {"CF-Access-Client-Id": access_id, "CF-Access-Client-Secret": access_secret} if access_id and access_secret else {}
    agent = {"User-Agent": "mospi-gateway-check/1", "Accept": "application/json"}
    quick = is_quick_tunnel(origin)
    if quick:
        access = {}                                  # Access cannot protect a trycloudflare.com hostname; never send the token there
    results: dict[str, object] = {"gateway": origin, "cloudflare_access_token_configured": bool(access)}
    if quick:
        results["tunnel"] = ("QUICK TUNNEL: temporary, random URL, no Cloudflare Access. The request signature is the only credential "
                             "at the gateway; use for a demonstration only.")

    def status(path: str, headers: dict[str, str], expect: set[int], name: str) -> None:
        try:
            code, _ = _urllib_transport(origin + path, {**agent, **headers}, 10)
        except OSError as error:
            results[name] = f"FAILED: not reachable ({type(error).__name__})"
            return
        results[name] = f"{'ok' if code in expect else 'FAILED'} (HTTP {code}; expected {'/'.join(map(str, sorted(expect)))})"

    remote = not origin.startswith("http://")
    # Without any credential: Cloudflare Access must stop it at the edge (403, or a redirect to its login page).
    # A Quick Tunnel has no Access, so here the gateway itself must refuse it (401) - on any path, before routing.
    status("/v1/status", {}, {302, 403} if remote and not quick else {401}, "no_credentials_refused")
    if quick:
        status("/", {}, {401}, "unsigned_root_path_refused")
    if access:
        status("/v1/status", access, {401}, "access_token_without_signature_refused")
    status("/v1/status", {**access, **sign("x" * 40, "GET", "/v1/status")}, {401}, "wrong_secret_refused")
    signed = sign(secret, "GET", "/v1/status")
    status("/v1/status", {**access, **signed}, {200}, "signed_request_accepted")
    status("/v1/status", {**access, **signed}, {401}, "replayed_request_refused")
    status("/v1/not-a-route", {**access, **sign(secret, "GET", "/v1/not-a-route")}, {404}, "unknown_route_refused")
    try:
        code, _ = _urllib_transport_post(origin + "/v1/status", {**agent, **access, **sign(secret, "POST", "/v1/status")})
        results["write_method_refused"] = f"{'ok' if code in (403, 405) else 'FAILED'} (HTTP {code})"
    except OSError as error:
        results["write_method_refused"] = f"FAILED: not reachable ({type(error).__name__})"

    client = GatewayClient(origin, secret, access_id=access_id or None, access_secret=access_secret or None, cache_seconds=0, allow_quick_tunnel=quick)
    try:
        info = client.get("/v1/status", cache=False)
        results["database_role"] = info.get("role")
        summary = client.get("/v1/summary", cache=False)
        runs = summary.get("runs") or []
        results["runs_visible_to_hosted"] = [f"{r['run_id']} ({r['data_class']})" for r in runs]
        results["only_cleared_data_classes"] = all(r["data_class"] in ("SYNTHETIC", "APPROVED_REAL") for r in runs)
        results["audit_verifications"] = {v["run_id"]: v["status"] for v in summary.get("audit_verifications") or []}
    except Exception as error:                       # noqa: BLE001 - report, never echo secrets
        results["read_through_gateway"] = f"FAILED: {error}"
    failures = [k for k, v in results.items() if isinstance(v, str) and v.startswith("FAILED")]
    if results.get("database_role") not in (None, "mospi_reader") or results.get("only_cleared_data_classes") is False:
        failures.append("database_role/data_class")
    results["verdict"] = ("PASSED (temporary Quick Tunnel: no Cloudflare Access layer)" if quick else "PASSED") if not failures else f"FAILED: {', '.join(failures)}"
    return results


def _urllib_transport_post(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    import urllib.error
    import urllib.request
    from .client import _OPENER
    try:
        with _OPENER.open(urllib.request.Request(url, data=b"", headers=headers, method="POST"), timeout=10) as response:
            return response.status, b""
    except urllib.error.HTTPError as error:
        return error.code, b""


def main() -> int:
    parser = argparse.ArgumentParser(description="Hosted read gateway (Cloudflare Tunnel origin).")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("secret", help="print a new random signing secret")
    serve = sub.add_parser("serve", help="run the gateway on 127.0.0.1")
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--log-file", default=None, help="also append the gateway's request log to this file")
    check = sub.add_parser("check", help="probe a running gateway and its access controls")
    check.add_argument("--url", default=None, help="gateway origin (default MOSPI_GATEWAY_URL)")
    args = parser.parse_args()
    from mospi.db.config import int_setting, load_env_file
    load_env_file()
    if args.command == "secret":
        print(secrets.token_urlsafe(48))
        return 0
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if getattr(args, "log_file", None):
        from pathlib import Path
        Path(args.log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)
    try:
        if args.command == "check":
            url = args.url or os.environ.get("MOSPI_GATEWAY_URL", "").strip()
            if not url:
                print("error: give --url or set MOSPI_GATEWAY_URL", file=sys.stderr)
                return 2
            result = _probe(url)
            print(json.dumps(result, indent=2))
            return 0 if str(result["verdict"]).startswith("PASSED") else 1
        import uvicorn
        from .server import build_from_env
        app = build_from_env()
        uvicorn.run(app, host="127.0.0.1", port=args.port or int_setting("MOSPI_GATEWAY_PORT", 8787), access_log=False,
                    server_header=False, proxy_headers=False, log_level="info")
        return 0
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
