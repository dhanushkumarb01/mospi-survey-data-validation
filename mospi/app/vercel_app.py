"""Vercel entrypoint for the hosted, review-only workspace (docs/deployment/VERCEL_REVIEW_ONLY_DEPLOYMENT.md).

Local and Docker serving keep using ``python -m mospi.app.serve``; nothing here changes them.

On Vercel the app is always:
* review-only - batch validation and uploads cannot be started (Vercel Functions cannot run the batch, and the
  project directory is read-only);
* audit append-only - with ``MOSPI_REVIEW_DATABASE_URL`` (the insert-only ``mospi_reviewer`` role) signed-in supervisors
  and administrators record decisions straight into the Supabase audit trail; without it decisions are refused.  History
  and the chain verification recorded on the processing machine are read through the reader views;
* sign-in required - accounts are read from the database through the reader's two sign-in functions (mospi/auth); every
  /api request but sign-in needs a session cookie signed with ``MOSPI_SESSION_SECRET``.  With the reviewer connection,
  failed sign-ins lock an account and account holders can set their own password here.

Data (``MOSPI_AUDIT_BACKEND=postgres``, the hosted set-up): ``MOSPI_DATABASE_URL`` is the **reader** role on the Supabase
transaction pooler (``sslmode=verify-full`` with ``MOSPI_DB_CA_FILE=deploy/supabase/prod-ca-2021.crt``).  The review
records, run registry, chain verification and the review data themselves (the hosted serving set, mospi/db/serving.py)
are read through the ``hosted_*`` views only.  The serving set is fetched into the function's temporary directory on the
first authenticated data request of each instance, verified by SHA-256, and reused while the instance lives; the
unchanged DuckDB queries then serve it.  No review data is bundled with the deployment.

No silent fallback: if the database is not configured or cannot be reached, every data request answers HTTP 503 with a
plain-language message, and nothing is served from anywhere else.

Without ``MOSPI_AUDIT_BACKEND=postgres`` the synthetic demonstration bundle (``MOSPI_DATA_DIR``, default ``data/demo``)
is served as before; it is not uploaded in the Supabase set-up (.vercelignore).

Environment: ``MOSPI_AUDIT_BACKEND``, ``MOSPI_DATABASE_URL``, ``MOSPI_REVIEW_DATABASE_URL`` (optional), ``MOSPI_DB_CA_FILE``, ``MOSPI_SESSION_SECRET``,
``MOSPI_DB_MAX_CONNECTIONS`` (default 3 here), ``MOSPI_CODE_VERSION``, ``MOSPI_ALLOW_ANONYMOUS_DEMO`` (synthetic bundle only).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from mospi.auth import store_from_env

from . import backends
from .api import create_app, env_flag

PROJECT = Path(__file__).resolve().parents[2]
log = logging.getLogger("MoSPI.vercel")


def _data_root() -> Path:
    value = Path(os.environ.get("MOSPI_DATA_DIR", "").strip() or "data/demo")
    return value if value.is_absolute() else PROJECT / value


def _synthetic(root: Path) -> bool:
    try:
        return json.loads((root / "SERVING_DATA_MANIFEST.json").read_text(encoding="utf-8")).get("synthetic") is True
    except (OSError, ValueError):
        return False


def _not_configured(reason: str):
    from mospi.db.connection import DatabaseUnavailable

    def refuse() -> None:
        raise DatabaseUnavailable(reason)
    return refuse


def build_postgres() -> object:
    """Hosted instance reading everything from the database through the reader views."""
    os.environ.setdefault("MOSPI_DB_MAX_CONNECTIONS", "3")          # serverless: a few connections per instance
    from mospi.db.connection import DatabaseUnavailable, database_from_env
    from mospi.db.serving import HostedServingData
    root = Path(os.environ.get("MOSPI_SERVING_DIR", "").strip() or Path(tempfile.gettempdir()) / "mospi-serving")
    (root / "fusion" / "runs").mkdir(parents=True, exist_ok=True)
    try:
        audit_store, operations = backends.build(root / "fusion" / "runs", root, hosted=True)
        db = database_from_env(application_name="mospi-hosted", read_only=True)
        users = store_from_env(hosted=True)
    except Exception as error:   # noqa: BLE001 - misconfiguration: refuse data requests plainly, never fall back
        log.error("Hosted database is not configured correctly (%s).", type(error).__name__)
        return create_app(root / "fusion" / "runs", root, review_only=True, audit_read_only=True, require_authentication=True,
                          before_data=_not_configured("The hosted database connection is not configured."), hosted=True,
                          health_check=lambda: ({"status": "unavailable", "database": {"configured": False}}, 503))
    serving = HostedServingData(db, root)

    def health() -> tuple[dict[str, Any], int]:
        try:
            info = db.ping()
            version = db.fetchone("SELECT version, migrations FROM hosted_schema_version") or {}
            database = {"reachable": True, "tls": bool(info.get("ssl")), "schema_version": version.get("version"), "migrations": version.get("migrations")}
        except DatabaseUnavailable:
            return {"status": "unavailable", "database": {"reachable": False}, "review_data": serving.status()}, 503
        return {"status": "ok", "database": database, "review_data": serving.status(), "audit_store": "append-only" if audit_store.writable else "read-only",
                "audit_backend": "postgres"}, 200

    return create_app(root / "fusion" / "runs", root, users=users, review_only=True, audit_read_only=not audit_store.writable, require_authentication=True,
                      audit_store=audit_store, operations=operations, before_data=serving.ensure, health_check=health, hosted=True, allow_export=False)


def build() -> object:
    try:
        backend = backends.audit_backend()
    except backends.BackendError as error:
        log.error("%s", error)
        backend = "postgres"                    # an invalid value must not silently serve something else: refuse plainly
        os.environ["MOSPI_AUDIT_BACKEND"] = "invalid"
    if backend == "postgres":
        return build_postgres()
    root = _data_root()
    anonymous_demo = env_flag("MOSPI_ALLOW_ANONYMOUS_DEMO") and _synthetic(root)
    if env_flag("MOSPI_ALLOW_ANONYMOUS_DEMO") and not anonymous_demo:
        log.error("MOSPI_ALLOW_ANONYMOUS_DEMO is ignored: the data directory is not marked synthetic.")
    # The synthetic bundle has no database, so no accounts: it is served only as the anonymous demonstration, never with sign-in.
    return create_app(root / "fusion" / "runs", root, review_only=True, audit_read_only=True, require_authentication=not anonymous_demo)


app = build()
