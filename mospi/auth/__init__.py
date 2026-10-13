"""Named user accounts: sign-in, roles (admin, supervisor, analyst) and account management.

Which store an instance uses (:func:`store_from_env`):
* hosted (Vercel, ``MOSPI_AUDIT_BACKEND=postgres``): :class:`HostedUserStore` over the reader connection, plus the
  reviewer connection (``MOSPI_REVIEW_DATABASE_URL``) when it is configured;
* local with ``MOSPI_DATABASE_URL``: :class:`PostgresUserStore` (role ``mospi_app``) - the same accounts as the hosted instance;
* local without a database: :class:`SqliteUserStore` at ``MOSPI_USERS_DB`` (default ``<data>/auth/users.sqlite``).

Administrator accounts are created only with ``python -m mospi.auth create-admin`` (docs/deployment/USER_ACCOUNTS.md).
"""
from __future__ import annotations

import os
from pathlib import Path

from .roles import CAPABILITIES, CREATABLE_ROLES, ROLE_LABELS, ROLES, can, capabilities
from .store import AccountError, HostedUserStore, PostgresUserStore, SqliteUserStore, UserStore

__all__ = ["AccountError", "CAPABILITIES", "CREATABLE_ROLES", "HostedUserStore", "PostgresUserStore", "ROLES", "ROLE_LABELS", "SqliteUserStore",
           "UserStore", "can", "capabilities", "sqlite_path", "store_from_env"]

REVIEW_URL_VARIABLE = "MOSPI_REVIEW_DATABASE_URL"


def sqlite_path() -> Path:
    from mospi.paths import data_root
    value = os.environ.get("MOSPI_USERS_DB", "").strip()
    return Path(value) if value else data_root() / "auth" / "users.sqlite"


def store_from_env(*, hosted: bool) -> UserStore | None:
    """The account store for this instance; None on a hosted instance without a database (it then serves nothing)."""
    from mospi.db.config import load_env_file
    from mospi.db.connection import database_from_env
    load_env_file()
    if hosted:
        reader = database_from_env(application_name="mospi-hosted", read_only=True)
        if reader is None:
            return None
        return HostedUserStore(reader, database_from_env(REVIEW_URL_VARIABLE, application_name="mospi-hosted-review"))
    db = database_from_env(application_name="mospi-app")
    return PostgresUserStore(db) if db is not None else SqliteUserStore(sqlite_path())
