"""Bounded PostgreSQL connections with timeouts, used by the app, the worker and the CLI tools.

* At most ``max_connections`` connections per process (a semaphore; callers wait up to the connect timeout).
* Idle connections are reused (checked before reuse) and closed after ``max_idle_seconds``.
* Every statement runs under ``statement_timeout``; the schema is fixed through ``search_path``.  Both are also set
  per transaction (``set_config(..., is_local => true)``), because a transaction pooler (Supabase port 6543) shares
  server connections between clients and cannot be trusted to keep session state; ``read_only`` connections mark
  every transaction read-only the same way.
* ``prepare_threshold=None``: no server-side prepared statements, so transaction poolers also work.
* Session-level state (session advisory locks, LISTEN, temporary tables) is never used; the advisory locks that exist
  are transaction-scoped (``pg_advisory_xact_lock``) and therefore safe behind a transaction pooler.
* All variable data goes through parameters (``%s``); SQL text never contains user input.
* Connection strings are never logged: use :func:`redact` for messages.
* A refused login is never retried by the same process: repeated failed logins get the client's address banned by the
  Supabase pooler, so after one the connection reports itself unavailable until the application restarts.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import int_setting, load_env_file, schema as configured_schema

LOGGER = logging.getLogger("MoSPI.db")
_LOGIN_REFUSED = re.compile(r"authentication failed|tenant or user not found|no pg_hba\.conf entry", re.I)
LOGIN_REFUSED = "The database refused this login, so it is not tried again until the application restarts. Check the configured credentials."


class DatabaseUnavailable(RuntimeError):
    """PostgreSQL could not be reached or refused the connection (message never contains credentials)."""


def redact(text: str) -> str:
    """Remove passwords from a connection string or an error message."""
    text = re.sub(r"(postgres(?:ql)?://[^:/@\s]+):[^@\s]+@", r"\1:***@", str(text))
    return re.sub(r"(password\s*=\s*)('[^']*'|\S+)", r"\1***", text, flags=re.I)


class Database:
    def __init__(self, url: str, *, schema: str | None = None, max_connections: int | None = None, connect_timeout: int | None = None,
                 statement_timeout_ms: int | None = None, max_idle_seconds: float = 60.0, application_name: str = "mospi",
                 read_only: bool = False) -> None:
        if not url:
            raise DatabaseUnavailable("No database connection is configured (MOSPI_DATABASE_URL).")
        ca_file = os.environ.get("MOSPI_DB_CA_FILE", "").strip()
        if ca_file and "sslrootcert" not in url:
            # The server's CA certificate (public; deploy/supabase/prod-ca-2021.crt), resolved against the project on any host.
            from psycopg.conninfo import make_conninfo
            from mospi.paths import REPO_ROOT
            path = Path(ca_file) if Path(ca_file).is_absolute() else REPO_ROOT / ca_file
            url = make_conninfo(url, sslrootcert=str(path))
        self._url = url
        self.schema = schema or configured_schema()
        self.max_connections = max_connections or int_setting("MOSPI_DB_MAX_CONNECTIONS", 5)
        self.connect_timeout = connect_timeout or int_setting("MOSPI_DB_CONNECT_TIMEOUT", 5)
        self.statement_timeout_ms = statement_timeout_ms or int_setting("MOSPI_DB_STATEMENT_TIMEOUT_MS", 15000)
        self.max_idle_seconds = max_idle_seconds
        self.application_name = application_name
        self.read_only = read_only
        self.login_refused = False
        self._slots = threading.BoundedSemaphore(self.max_connections)
        self._idle: list[tuple[float, Any]] = []
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"Database({redact(self._url)}, schema={self.schema})"

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        if self.login_refused:
            raise DatabaseUnavailable(LOGIN_REFUSED)
        try:
            return psycopg.connect(self._url, connect_timeout=self.connect_timeout, prepare_threshold=None, row_factory=dict_row,
                                   application_name=self.application_name,
                                   options=f"-c search_path={self.schema} -c statement_timeout={int(self.statement_timeout_ms)}")
        except psycopg.Error as error:
            if _LOGIN_REFUSED.search(str(error)):
                self.login_refused = True
                LOGGER.error("Login refused for %s (application %s); not retried until restart.", redact(self._url), self.application_name)
            raise DatabaseUnavailable(f"PostgreSQL is not reachable: {redact(error)}".strip()) from None

    def _checkout(self):
        now = time.monotonic()
        with self._lock:
            while self._idle:
                since, connection = self._idle.pop()
                if connection.closed or now - since > self.max_idle_seconds:
                    connection.close()
                    continue
                return connection
        return self._connect()

    def _begin(self, connection) -> None:
        """Transaction-local settings, so nothing depends on the session a pooler hands out."""
        try:
            connection.execute("SELECT set_config('search_path', %s, true), set_config('statement_timeout', %s, true)"
                               + (", set_config('transaction_read_only', 'on', true)" if self.read_only else ""),
                               (self.schema, str(int(self.statement_timeout_ms))))
        except Exception as error:   # noqa: BLE001 - a dead pooled connection surfaces here first
            import psycopg
            if isinstance(error, psycopg.OperationalError):
                raise DatabaseUnavailable(f"The database connection failed: {redact(error)}") from None
            raise

    def _checkin(self, connection, healthy: bool) -> None:
        import psycopg
        if not healthy or connection.closed or connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            connection.close()
            return
        with self._lock:
            self._idle.append((time.monotonic(), connection))

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """A connection inside one transaction: committed on success, rolled back on any error."""
        import psycopg
        if not self._slots.acquire(timeout=max(1, self.connect_timeout)):
            raise DatabaseUnavailable("All database connections are busy; try again.")
        connection = None
        healthy = True
        try:
            connection = self._checkout()
            try:
                self._begin(connection)
                yield connection
                connection.commit()
            except BaseException as error:
                healthy = not isinstance(error, psycopg.OperationalError)
                try:
                    connection.rollback()
                except psycopg.Error:
                    healthy = False
                if isinstance(error, psycopg.OperationalError):
                    raise DatabaseUnavailable(f"The database connection failed: {redact(error)}") from None
                raise
        finally:
            if connection is not None:
                self._checkin(connection, healthy)
            self._slots.release()

    def fetch(self, sql: str, params: tuple | list | dict | None = None) -> list[dict[str, Any]]:
        with self.transaction() as connection:
            return list(connection.execute(sql, params).fetchall())

    def fetchone(self, sql: str, params: tuple | list | dict | None = None) -> dict[str, Any] | None:
        rows = self.fetch(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple | list | dict | None = None) -> int:
        with self.transaction() as connection:
            return connection.execute(sql, params).rowcount

    def ping(self) -> dict[str, Any]:
        """Role, server version and whether this client's link is TLS (behind a pooler, pg_stat_ssl only describes the pooler's hop)."""
        with self.transaction() as connection:
            row = connection.execute("SELECT current_user AS role, current_setting('server_version') AS server_version").fetchone()
            return {**dict(row or {}), "ssl": bool(connection.pgconn.ssl_in_use)}

    def close(self) -> None:
        with self._lock:
            for _, connection in self._idle:
                connection.close()
            self._idle.clear()


_SHARED: dict[tuple[str, str], Database] = {}


def database_from_env(variable: str = "MOSPI_DATABASE_URL", *, application_name: str = "mospi", read_only: bool = False) -> Database | None:
    """The shared Database for a URL variable, or None when it is not configured."""
    load_env_file()
    url = os.environ.get(variable, "").strip()
    if not url:
        return None
    key = (variable, url + "|" + configured_schema())
    if key not in _SHARED:
        _SHARED[key] = Database(url, application_name=application_name, read_only=read_only)
    return _SHARED[key]
