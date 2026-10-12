"""Vercel entrypoint for the hosted, review-only workspace (docs/deployment/VERCEL_REVIEW_ONLY_DEPLOYMENT.md).

Local and Docker serving keep using ``python -m mospi.app.serve``; nothing here changes them.

On Vercel the app is always:
* review-only - batch validation cannot be started (Vercel Functions cannot run
  the 23-47 minute batch, and the project directory is read-only);
* audit read-only - decisions are not recorded, because Vercel offers no durable
  shared disk and the Python Blob SDK has no conditional (compare-and-swap) write,
  so concurrent decisions could be lost or fork the hash chain.  Recorded history
  bundled with the data is shown read-only;
* sign-in required - every /api request needs a bearer token from
  ``MOSPI_USERS_JSON``.  The only exception is ``MOSPI_ALLOW_ANONYMOUS_DEMO=1`` on a
  data directory whose manifest says it is synthetic.

Environment: ``MOSPI_DATA_DIR`` (default ``data/demo``, relative to the project),
``MOSPI_USERS_JSON``, ``MOSPI_ALLOW_ANONYMOUS_DEMO``, ``MOSPI_CODE_VERSION``.

With ``MOSPI_AUDIT_BACKEND=postgres`` and ``MOSPI_DATABASE_URL`` (role ``mospi_reader``, ``sslmode=require`` or
stricter) the review records, run registry, job status and integrity-check results are read live from the
processing machine's PostgreSQL through the ``hosted_*`` views only.  Uploads are never available here, and the
reader role makes the hosted instance read-only at the database as well (docs/deployment/POSTGRESQL.md).

With ``MOSPI_AUDIT_BACKEND=gateway`` (the current set-up) the same reader views are read through the signed hosted read
gateway on the processing machine, over a Cloudflare Tunnel (``MOSPI_GATEWAY_URL``, ``MOSPI_GATEWAY_SECRET``,
``MOSPI_CF_ACCESS_CLIENT_ID``/``_SECRET``); Vercel then holds no database credential (docs/deployment/CLOUDFLARE_TUNNEL.md).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from . import backends
from .api import _load_users, create_app, env_flag

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


def build() -> object:
    root = _data_root()
    users_json = os.environ.get("MOSPI_USERS_JSON", "").strip() or None
    if users_json:
        try:
            _load_users(None, users_json)
        except (ValueError, TypeError, KeyError, AttributeError):
            # Never echo the value: it holds token hashes.  Serving continues with every /api call refused.
            log.error("MOSPI_USERS_JSON is not a valid users document; every /api request will be refused until it is fixed.")
            users_json = None
    anonymous_demo = env_flag("MOSPI_ALLOW_ANONYMOUS_DEMO") and _synthetic(root)
    if env_flag("MOSPI_ALLOW_ANONYMOUS_DEMO") and not anonymous_demo:
        log.error("MOSPI_ALLOW_ANONYMOUS_DEMO is ignored: the data directory is not marked synthetic.")
    try:
        audit_store, operations = backends.build(root / "fusion" / "runs", root, hosted=True)
    except Exception as error:   # noqa: BLE001 - serve the bundled data read-only rather than fail every request
        log.error("PostgreSQL reader is not configured correctly (%s); serving bundled review history only.", type(error).__name__)
        audit_store, operations = None, None
    return create_app(root / "fusion" / "runs", root, users_json=users_json, review_only=True, audit_read_only=True,
                      require_authentication=not anonymous_demo, audit_store=audit_store, operations=operations)


app = build()
