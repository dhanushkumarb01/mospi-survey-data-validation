"""PostgreSQL fixtures: every test runs in its own throwaway schema (never the operational ``mospi`` schema)."""
from __future__ import annotations

import hashlib
import json
import os
import uuid

import pytest

from mospi.db.config import load_env_file
from mospi.db.connection import Database

TOKENS = {"admin": "admin-token-for-tests", "technical": "technical-token-for-tests", "supervisor": "supervisor-token-for-tests"}
USERS = json.dumps({"users": [{"name": f"Test {role}", "role": role, "token_sha256": hashlib.sha256(token.encode()).hexdigest()} for role, token in TOKENS.items()]})


def auth(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKENS[role]}"}


def _urls() -> dict[str, str]:
    load_env_file(force=True)
    from psycopg.conninfo import make_conninfo
    admin, app = os.environ.get("MOSPI_DB_ADMIN_URL", ""), os.environ.get("MOSPI_DATABASE_URL", "")
    if not admin or not app or not os.environ.get("MOSPI_DB_READER_PASSWORD"):
        pytest.skip("MOSPI_DB_ADMIN_URL, MOSPI_DATABASE_URL and MOSPI_DB_READER_PASSWORD are needed for PostgreSQL tests")
    return {"admin": admin, "app": app, "reader": make_conninfo(app, user="mospi_reader", password=os.environ["MOSPI_DB_READER_PASSWORD"])}


@pytest.fixture()
def pg(monkeypatch):
    """Throwaway schema with every migration and grant applied; yields admin/app/reader Database objects."""
    from mospi.db.migrate import apply, apply_grants
    urls = _urls()
    schema = f"t_{uuid.uuid4().hex[:12]}"
    admin = Database(urls["admin"], schema=schema, application_name="mospi-tests")
    apply(admin, actor="tests")
    apply_grants(admin)
    monkeypatch.setenv("MOSPI_DB_SCHEMA", schema)
    monkeypatch.setenv("MOSPI_DATABASE_URL", urls["app"])
    monkeypatch.setenv("MOSPI_DB_ADMIN_URL", urls["admin"])
    monkeypatch.setenv("MOSPI_KEY_HMAC_SECRET", "test-secret-" + schema)
    monkeypatch.setenv("MOSPI_CHECK_INTERVAL_MINUTES", "0")
    databases = {"admin": admin, "app": Database(urls["app"], schema=schema), "reader": Database(urls["reader"], schema=schema), "schema": schema, "urls": urls}
    try:
        yield databases
    finally:
        for name in ("app", "reader"):
            databases[name].close()
        with admin.transaction() as connection:
            connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
        admin.close()
