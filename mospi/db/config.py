"""Connection settings from environment variables (never from source code).

``MOSPI_DATABASE_URL``   runtime connection (local app/worker: role ``mospi_app``; hosted: role ``mospi_reader``)
``MOSPI_DB_ADMIN_URL``   migrations, role setup, backups and the audit migration only
``MOSPI_DB_SCHEMA``      schema holding every table (default ``mospi``; tests use a throwaway schema)
``MOSPI_DB_MAX_CONNECTIONS`` (5), ``MOSPI_DB_CONNECT_TIMEOUT`` seconds (5), ``MOSPI_DB_STATEMENT_TIMEOUT_MS`` (15000)

A local, git-ignored ``.env`` at the repository root is read for values not already in the environment.
It is never read on Vercel (``VERCEL`` is set there) and is excluded from Docker and Vercel uploads.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from mospi.paths import REPO_ROOT

SCHEMA_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def load_env_file(path: Path | None = None, *, force: bool = False) -> None:
    """Fill missing environment variables from a simple KEY=VALUE file; existing variables always win."""
    if os.environ.get("VERCEL") or (os.environ.get("MOSPI_NO_ENV_FILE") and not force):
        return
    path = path or REPO_ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def schema() -> str:
    value = os.environ.get("MOSPI_DB_SCHEMA", "mospi").strip() or "mospi"
    if not SCHEMA_PATTERN.fullmatch(value):
        raise ValueError("MOSPI_DB_SCHEMA must be a lower-case SQL identifier.")
    return value


def int_setting(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
