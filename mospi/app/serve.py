"""Start the MoSPI survey data validation review workspace.

Every option can also be set by environment variable (used by the Docker image):
MOSPI_FUSION_ROOT, MOSPI_PROJECT_ROOT, MOSPI_HOST, MOSPI_PORT, MOSPI_REVIEW_ONLY and MOSPI_AUDIT_READ_ONLY
(docs/deployment/VERCEL_REVIEW_ONLY_DEPLOYMENT.md).
MOSPI_AUDIT_BACKEND=postgres with MOSPI_DATABASE_URL selects the PostgreSQL operational store and enables the
Upload & validate page (docs/deployment/POSTGRESQL.md); the default stays the per-run SQLite store.

Sign-in is always required.  Accounts live in PostgreSQL when MOSPI_DATABASE_URL is set, otherwise in the SQLite file
MOSPI_USERS_DB; the first administrator is created with ``python -m mospi.auth create-admin``
(docs/deployment/USER_ACCOUNTS.md).  MOSPI_SESSION_SECRET keeps sessions valid across restarts.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import uvicorn

from mospi.auth import store_from_env
from mospi.paths import data_root

from . import backends
from .api import create_app, env_flag


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the MoSPI survey data validation review workspace.")
    parser.add_argument("--fusion-root", type=Path, default=_env_path("MOSPI_FUSION_ROOT") or data_root() / "fusion" / "runs")
    parser.add_argument("--project-root", type=Path, default=_env_path("MOSPI_PROJECT_ROOT"),
                        help="Directory holding preprocessing/, statistical/, contextual/, ml/ and pattern/ runs (default: two levels above --fusion-root).")
    parser.add_argument("--review-only", action="store_true", default=env_flag("MOSPI_REVIEW_ONLY"),
                        help="Serve stored runs for review only: no batch validation can be started (enforced by the server).")
    parser.add_argument("--audit-read-only", action="store_true", default=env_flag("MOSPI_AUDIT_READ_ONLY"),
                        help="Show recorded decisions but append nothing to the audit trail (decisions and exports are refused).")
    parser.add_argument("--host", default=os.environ.get("MOSPI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MOSPI_PORT", "8000")))
    args = parser.parse_args()
    project_root = args.project_root or args.fusion_root.resolve().parent.parent
    try:
        audit_store, operations = backends.build(args.fusion_root, project_root, hosted=False)
    except Exception as error:   # noqa: BLE001 - never start half-configured; the message carries no credentials
        parser.error(f"PostgreSQL backend: {error}")
    users = store_from_env(hosted=False)
    if not os.environ.get("MOSPI_SESSION_SECRET", "").strip():
        logging.getLogger("uvicorn.error").warning("MOSPI_SESSION_SECRET is not set: sessions end whenever the server restarts.")
    app = create_app(args.fusion_root, args.project_root, users=users, review_only=args.review_only, audit_read_only=args.audit_read_only,
                     audit_store=audit_store, operations=operations)
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False)


if __name__ == "__main__":
    main()
