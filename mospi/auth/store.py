"""Where accounts live.

* :class:`PostgresUserStore` - the ``app_users`` table (0005_users.sql), used by the local app through ``mospi_app`` and by
  the command line through the administrative connection (the only way to create an administrator).
* :class:`HostedUserStore` - the hosted (Vercel) instance: looks accounts up through the reader's two functions and, when
  the insert-only reviewer connection is configured, records sign-in outcomes and password changes through its two.
  It cannot create or change accounts.
* :class:`SqliteUserStore` - a single file for instances without PostgreSQL (Docker without a database, tests).

Every store returns plain dicts.  ``password_hash`` appears only in :meth:`login_record`.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .roles import CREATABLE_ROLES, ROLES

USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,39}$")
MAX_FAILURES = 5
LOCK_MINUTES = 15
EVENT_TYPES = ("SIGNED_IN", "SIGN_IN_FAILED", "ACCOUNT_LOCKED", "SIGNED_OUT", "PASSWORD_CHANGED", "PASSWORD_RESET", "USER_CREATED", "USER_UPDATED")
PUBLIC_FIELDS = ("user_id", "username", "display_name", "role", "active", "must_change_password", "locked_until", "last_login_utc",
                 "created_by", "created_utc")


class AccountError(ValueError):
    """A refused account change, in plain words (``status`` is the HTTP status the API answers with)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalise_username(value: str) -> str:
    return str(value or "").strip().lower()


def check_new_account(username: str, display_name: str, role: str, *, allow_admin: bool) -> tuple[str, str]:
    username, display_name = normalise_username(username), " ".join(str(display_name or "").split())
    if not USERNAME.fullmatch(username):
        raise AccountError("A username has 3 to 40 characters: lower-case letters, digits, dots, hyphens or underscores, starting with a letter or digit.")
    if not 1 <= len(display_name) <= 80:
        raise AccountError("Give the person's name (at most 80 characters).")
    if role not in (ROLES if allow_admin else CREATABLE_ROLES):
        raise AccountError("Administrator accounts are created only on the server (python -m mospi.auth create-admin)." if role == "admin"
                           else "The role must be supervisor or analyst.")
    return username, display_name


def public(account: dict[str, Any] | None) -> dict[str, Any] | None:
    """The fields the workspace may show; timestamps as ISO 8601."""
    if account is None:
        return None
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in account.items() if k in PUBLIC_FIELDS}


def is_locked(account: dict[str, Any], at: datetime | None = None) -> bool:
    locked = account.get("locked_until")
    return bool(locked and locked > (at or now_utc()))


class UserStore:
    origin = "local"
    can_manage = True               # create, change, reset others
    can_change_password = True      # account holders set their own
    records_attempts = True         # failed-attempt counts and locks are kept here


# ---------------------------------------------------------------------------------------------------------- PostgreSQL


class PostgresUserStore(UserStore):
    """The ``app_users`` table through a writable connection (``mospi_app`` for the app; the admin connection for the CLI)."""

    _COLUMNS = ("user_id, username, display_name, role, active, must_change_password, session_version, failed_attempts, locked_until, "
                "last_login_utc, created_by, created_utc")

    def __init__(self, db: Any, *, origin: str = "local") -> None:
        self.db = db
        self.origin = origin

    def login_record(self, username: str) -> dict[str, Any] | None:
        return self.db.fetchone(f"SELECT {self._COLUMNS}, password_hash FROM app_users WHERE username = %s", (normalise_username(username),))

    def session_record(self, user_id: int) -> dict[str, Any] | None:
        return self.db.fetchone(f"SELECT {self._COLUMNS} FROM app_users WHERE user_id = %s", (int(user_id),))

    def list_users(self) -> list[dict[str, Any]]:
        return self.db.fetch(f"SELECT {self._COLUMNS} FROM app_users ORDER BY role = 'admin' DESC, active DESC, display_name, username")

    def events(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.db.fetch("SELECT event_type, username, actor, detail, origin, event_utc FROM auth_events ORDER BY event_id DESC LIMIT %s", (int(limit),))

    def log(self, event_type: str, username: str, actor: str, detail: str | None = None, connection: Any = None) -> None:
        sql = "INSERT INTO auth_events (event_type, username, actor, detail, origin) VALUES (%s, %s, %s, %s, %s)"
        values = (event_type, username[:40], actor[:120], detail, self.origin)
        if connection is not None:
            connection.execute(sql, values)
        else:
            self.db.execute(sql, values)

    def note_attempt(self, username: str, success: bool) -> None:
        username = normalise_username(username)
        with self.db.transaction() as connection:
            account = connection.execute("SELECT user_id, failed_attempts FROM app_users WHERE username = %s FOR UPDATE", (username,)).fetchone()
            if account is None:
                self.log("SIGN_IN_FAILED", username, "anonymous", "unknown username", connection)
            elif success:
                connection.execute("UPDATE app_users SET failed_attempts = 0, locked_until = NULL, last_login_utc = now() WHERE user_id = %s", (account["user_id"],))
                self.log("SIGNED_IN", username, username, None, connection)
            elif account["failed_attempts"] + 1 >= MAX_FAILURES:
                connection.execute("UPDATE app_users SET failed_attempts = 0, locked_until = now() + %s WHERE user_id = %s",
                                   (timedelta(minutes=LOCK_MINUTES), account["user_id"]))
                self.log("ACCOUNT_LOCKED", username, "anonymous", f"{MAX_FAILURES} failed sign-ins", connection)
            else:
                connection.execute("UPDATE app_users SET failed_attempts = failed_attempts + 1 WHERE user_id = %s", (account["user_id"],))
                self.log("SIGN_IN_FAILED", username, "anonymous", None, connection)

    def change_password(self, user_id: int, old_hash: str, new_hash: str) -> bool:
        with self.db.transaction() as connection:
            account = connection.execute("SELECT username, password_hash, active FROM app_users WHERE user_id = %s FOR UPDATE", (int(user_id),)).fetchone()
            if account is None or not account["active"] or account["password_hash"] != old_hash or new_hash == old_hash:
                return False
            connection.execute("UPDATE app_users SET password_hash = %s, must_change_password = false, session_version = session_version + 1 "
                               "WHERE user_id = %s", (new_hash, int(user_id)))
            self.log("PASSWORD_CHANGED", account["username"], account["username"], None, connection)
            return True

    def create(self, *, username: str, display_name: str, role: str, password_hash: str, created_by: str, allow_admin: bool = False) -> dict[str, Any]:
        import psycopg
        username, display_name = check_new_account(username, display_name, role, allow_admin=allow_admin)
        try:
            with self.db.transaction() as connection:
                account = connection.execute(f"INSERT INTO app_users (username, display_name, role, password_hash, created_by) VALUES (%s, %s, %s, %s, %s) "
                                             f"RETURNING {self._COLUMNS}", (username, display_name, role, password_hash, created_by[:120])).fetchone()
                self.log("USER_CREATED", username, created_by, role, connection)
        except psycopg.errors.UniqueViolation:
            raise AccountError("That username is already taken.", 409) from None
        return account

    def update(self, user_id: int, *, actor: str, role: str | None = None, active: bool | None = None, display_name: str | None = None,
               allow_admin: bool = False) -> dict[str, Any]:
        with self.db.transaction() as connection:
            account = connection.execute(f"SELECT {self._COLUMNS} FROM app_users WHERE user_id = %s FOR UPDATE", (int(user_id),)).fetchone()
            changes = _changes(account, role=role, active=active, display_name=display_name, allow_admin=allow_admin)
            if not changes:
                return account
            assignments = ", ".join(f"{k} = %s" for k in changes)
            account = connection.execute(f"UPDATE app_users SET {assignments}, session_version = session_version + 1 WHERE user_id = %s "
                                         f"RETURNING {self._COLUMNS}", (*changes.values(), int(user_id))).fetchone()
            self.log("USER_UPDATED", account["username"], actor, _describe(changes), connection)
            return account

    def reset_password(self, user_id: int, password_hash: str, *, actor: str, allow_admin: bool = False) -> dict[str, Any]:
        with self.db.transaction() as connection:
            account = connection.execute(f"SELECT {self._COLUMNS} FROM app_users WHERE user_id = %s FOR UPDATE", (int(user_id),)).fetchone()
            _check_target(account, allow_admin)
            account = connection.execute(f"UPDATE app_users SET password_hash = %s, must_change_password = true, failed_attempts = 0, locked_until = NULL, "
                                         f"session_version = session_version + 1 WHERE user_id = %s RETURNING {self._COLUMNS}",
                                         (password_hash, int(user_id))).fetchone()
            self.log("PASSWORD_RESET", account["username"], actor, None, connection)
            return account


class HostedUserStore(UserStore):
    """Hosted instance: account look-ups through the reader's functions; outcomes through the reviewer's, when configured."""
    origin = "hosted"
    can_manage = False

    def __init__(self, reader: Any, writer: Any = None) -> None:
        self.reader, self.writer = reader, writer
        self.can_change_password = self.records_attempts = writer is not None

    def login_record(self, username: str) -> dict[str, Any] | None:
        return self.reader.fetchone("SELECT * FROM auth_login_record(%s)", (normalise_username(username),))

    def session_record(self, user_id: int) -> dict[str, Any] | None:
        return self.reader.fetchone("SELECT * FROM auth_session_record(%s)", (int(user_id),))

    def note_attempt(self, username: str, success: bool) -> None:
        if self.writer is not None:
            self.writer.fetch("SELECT auth_note_attempt(%s, %s)", (normalise_username(username), bool(success)))

    def change_password(self, user_id: int, old_hash: str, new_hash: str) -> bool:
        if self.writer is None:
            return False
        row = self.writer.fetchone("SELECT auth_change_password(%s, %s, %s) AS changed", (int(user_id), old_hash, new_hash))
        return bool(row and row["changed"])

    def _managed_elsewhere(self, *_: Any, **__: Any):
        raise AccountError("Accounts are managed on the processing machine.", 403)

    list_users = create = update = reset_password = events = _managed_elsewhere


# ---------------------------------------------------------------------------------------------------------- SQLite


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'supervisor', 'analyst')), password_hash TEXT NOT NULL CHECK (password_hash LIKE 'scrypt$%'),
    active INTEGER NOT NULL DEFAULT 1, must_change_password INTEGER NOT NULL DEFAULT 1, session_version INTEGER NOT NULL DEFAULT 1,
    failed_attempts INTEGER NOT NULL DEFAULT 0, locked_until TEXT, last_login_utc TEXT, created_by TEXT NOT NULL, created_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS auth_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, username TEXT NOT NULL, actor TEXT NOT NULL, detail TEXT,
    origin TEXT NOT NULL, event_utc TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS auth_events_append_only_u BEFORE UPDATE ON auth_events BEGIN SELECT RAISE(ABORT, 'auth_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS auth_events_append_only_d BEFORE DELETE ON auth_events BEGIN SELECT RAISE(ABORT, 'auth_events is append-only'); END;
"""


class SqliteUserStore(UserStore):
    """One SQLite file (or ``:memory:`` for tests).  Administrator accounts only through ``allow_admin`` (the command line)."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.executescript(_SQLITE_SCHEMA)

    def _rows(self, sql: str, values: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [_from_sqlite(dict(r)) for r in self._connection.execute(sql, values).fetchall()]

    def _one(self, sql: str, values: tuple = ()) -> dict[str, Any] | None:
        rows = self._rows(sql, values)
        return rows[0] if rows else None

    def _write(self, statements: list[tuple[str, tuple]]) -> None:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                for sql, values in statements:
                    self._connection.execute(sql, values)
                self._connection.execute("COMMIT")
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise

    def _event(self, event_type: str, username: str, actor: str, detail: str | None = None) -> tuple[str, tuple]:
        return ("INSERT INTO auth_events (event_type, username, actor, detail, origin, event_utc) VALUES (?, ?, ?, ?, ?, ?)",
                (event_type, username[:40], actor[:120], detail, self.origin, now_utc().isoformat()))

    def login_record(self, username: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM app_users WHERE username = ?", (normalise_username(username),))

    def session_record(self, user_id: int) -> dict[str, Any] | None:
        account = self._one("SELECT * FROM app_users WHERE user_id = ?", (int(user_id),))
        if account:
            account.pop("password_hash")
        return account

    def list_users(self) -> list[dict[str, Any]]:
        rows = self._rows("SELECT * FROM app_users ORDER BY role = 'admin' DESC, active DESC, display_name, username")
        for row in rows:
            row.pop("password_hash")
        return rows

    def events(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._rows("SELECT event_type, username, actor, detail, origin, event_utc FROM auth_events ORDER BY event_id DESC LIMIT ?", (int(limit),))

    def log(self, event_type: str, username: str, actor: str, detail: str | None = None) -> None:
        self._write([self._event(event_type, username, actor, detail)])

    def note_attempt(self, username: str, success: bool) -> None:
        username = normalise_username(username)
        account = self._one("SELECT user_id, failed_attempts FROM app_users WHERE username = ?", (username,))
        if account is None:
            self._write([self._event("SIGN_IN_FAILED", username, "anonymous", "unknown username")])
        elif success:
            self._write([("UPDATE app_users SET failed_attempts = 0, locked_until = NULL, last_login_utc = ? WHERE user_id = ?", (now_utc().isoformat(), account["user_id"])),
                         self._event("SIGNED_IN", username, username)])
        elif account["failed_attempts"] + 1 >= MAX_FAILURES:
            until = (now_utc() + timedelta(minutes=LOCK_MINUTES)).isoformat()
            self._write([("UPDATE app_users SET failed_attempts = 0, locked_until = ? WHERE user_id = ?", (until, account["user_id"])),
                         self._event("ACCOUNT_LOCKED", username, "anonymous", f"{MAX_FAILURES} failed sign-ins")])
        else:
            self._write([("UPDATE app_users SET failed_attempts = failed_attempts + 1 WHERE user_id = ?", (account["user_id"],)),
                         self._event("SIGN_IN_FAILED", username, "anonymous")])

    def change_password(self, user_id: int, old_hash: str, new_hash: str) -> bool:
        account = self._one("SELECT username, password_hash, active FROM app_users WHERE user_id = ?", (int(user_id),))
        if account is None or not account["active"] or account["password_hash"] != old_hash or new_hash == old_hash:
            return False
        self._write([("UPDATE app_users SET password_hash = ?, must_change_password = 0, session_version = session_version + 1 WHERE user_id = ? AND password_hash = ?",
                      (new_hash, int(user_id), old_hash)), self._event("PASSWORD_CHANGED", account["username"], account["username"])])
        return True

    def create(self, *, username: str, display_name: str, role: str, password_hash: str, created_by: str, allow_admin: bool = False) -> dict[str, Any]:
        username, display_name = check_new_account(username, display_name, role, allow_admin=allow_admin)
        try:
            self._write([("INSERT INTO app_users (username, display_name, role, password_hash, created_by, created_utc) VALUES (?, ?, ?, ?, ?, ?)",
                          (username, display_name, role, password_hash, created_by[:120], now_utc().isoformat())),
                         self._event("USER_CREATED", username, created_by, role)])
        except sqlite3.IntegrityError:
            raise AccountError("That username is already taken.", 409) from None
        account = self.login_record(username)
        account.pop("password_hash")
        return account

    def update(self, user_id: int, *, actor: str, role: str | None = None, active: bool | None = None, display_name: str | None = None,
               allow_admin: bool = False) -> dict[str, Any]:
        account = self.session_record(user_id)
        changes = _changes(account, role=role, active=active, display_name=display_name, allow_admin=allow_admin)
        if changes:
            assignments = ", ".join(f"{k} = ?" for k in changes)
            self._write([(f"UPDATE app_users SET {assignments}, session_version = session_version + 1 WHERE user_id = ?",
                          (*(int(v) if isinstance(v, bool) else v for v in changes.values()), int(user_id))),
                         self._event("USER_UPDATED", account["username"], actor, _describe(changes))])
        return self.session_record(user_id)

    def reset_password(self, user_id: int, password_hash: str, *, actor: str, allow_admin: bool = False) -> dict[str, Any]:
        account = self.session_record(user_id)
        _check_target(account, allow_admin)
        self._write([("UPDATE app_users SET password_hash = ?, must_change_password = 1, failed_attempts = 0, locked_until = NULL, "
                      "session_version = session_version + 1 WHERE user_id = ?", (password_hash, int(user_id))),
                     self._event("PASSWORD_RESET", account["username"], actor)])
        return self.session_record(user_id)


def _from_sqlite(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("active", "must_change_password"):
        if key in row:
            row[key] = bool(row[key])
    for key in ("locked_until", "last_login_utc", "created_utc", "event_utc"):
        if row.get(key):
            row[key] = datetime.fromisoformat(row[key])
    return row


# ---------------------------------------------------------------------------------------------------------- shared rules


def _check_target(account: dict[str, Any] | None, allow_admin: bool) -> None:
    if account is None:
        raise AccountError("No such account.", 404)
    if account["role"] == "admin" and not allow_admin:
        raise AccountError("Administrator accounts are managed only on the server (python -m mospi.auth).", 403)


def _changes(account: dict[str, Any] | None, *, role: str | None, active: bool | None, display_name: str | None, allow_admin: bool) -> dict[str, Any]:
    _check_target(account, allow_admin)
    changes: dict[str, Any] = {}
    if role is not None and role != account["role"]:
        if role not in (ROLES if allow_admin else CREATABLE_ROLES):
            raise AccountError("An account can be made a supervisor or an analyst here; administrators are created only on the server.", 403)
        changes["role"] = role
    if active is not None and bool(active) != bool(account["active"]):
        changes["active"] = bool(active)
    if display_name is not None:
        name = " ".join(str(display_name).split())
        if not 1 <= len(name) <= 80:
            raise AccountError("Give the person's name (at most 80 characters).")
        if name != account["display_name"]:
            changes["display_name"] = name
    return changes


def _describe(changes: dict[str, Any]) -> str:
    return "; ".join(f"{k.replace('_', ' ')}: {('active' if v else 'deactivated') if k == 'active' else v}" for k, v in changes.items())
