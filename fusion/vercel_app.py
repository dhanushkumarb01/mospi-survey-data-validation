"""Vercel entrypoint for the hosted, review-only workspace (docs/VERCEL_REVIEW_ONLY_DEPLOYMENT.md).

Local and Docker serving keep using ``python -m fusion.serve``; nothing here changes them.

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

Environment: ``MOSPI_DATA_DIR`` (default ``demo-data``, relative to the project),
``MOSPI_USERS_JSON``, ``MOSPI_ALLOW_ANONYMOUS_DEMO``, ``MOSPI_CODE_VERSION``.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .api import _load_users, create_app, env_flag

PROJECT = Path(__file__).resolve().parents[1]
log = logging.getLogger("MoSPI.vercel")


def _data_root() -> Path:
    value = Path(os.environ.get("MOSPI_DATA_DIR", "").strip() or "demo-data")
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
    return create_app(root / "fusion" / "runs", root, users_json=users_json, review_only=True, audit_read_only=True,
                      require_authentication=not anonymous_demo)


app = build()
