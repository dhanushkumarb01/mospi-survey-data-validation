"""Accounts for tests: an in-memory store with one account per role (passwords already chosen) and ready session headers.

``auth(role)`` returns the headers a signed-in browser sends: the session cookie (signed with :data:`SIGNER`, which the app
under test must use) and the workspace request header required on state-changing requests.
"""
from __future__ import annotations

from mospi.auth import SqliteUserStore
from mospi.auth.passwords import hash_password
from mospi.auth.sessions import COOKIE, SessionSigner

SECRET = "test-session-secret-not-used-anywhere-else"
SIGNER = SessionSigner(SECRET)
PASSWORD = "plain test passphrase 42"
ROLES = ("admin", "supervisor", "analyst")


def user_store() -> SqliteUserStore:
    """Accounts ``admin`` (id 1), ``supervisor`` (2) and ``analyst`` (3), named "Test <role>", password :data:`PASSWORD`."""
    store = SqliteUserStore(":memory:")
    hashed = hash_password(PASSWORD)
    for role in ROLES:
        store.create(username=role, display_name=f"Test {role}", role=role, password_hash=hashed, created_by="tests", allow_admin=True)
    store._write([("UPDATE app_users SET must_change_password = 0", ())])
    return store


def seed_postgres(admin_db) -> None:
    """The same three accounts in a fresh PostgreSQL schema (through the administrative connection, the table owner)."""
    from mospi.auth import PostgresUserStore
    store, hashed = PostgresUserStore(admin_db, origin="cli"), hash_password(PASSWORD)
    for role in ROLES:
        store.create(username=role, display_name=f"Test {role}", role=role, password_hash=hashed, created_by="tests", allow_admin=True)
    admin_db.execute("UPDATE app_users SET must_change_password = false")


def auth(role: str) -> dict[str, str]:
    return {"Cookie": f"{COOKIE}={SIGNER.issue(ROLES.index(role) + 1, 1)}", "X-MoSPI-Request": "1"}


def signed_in(**options) -> dict:
    """create_app keyword arguments for an instance with these accounts."""
    return {"users": user_store(), "session_signer": SIGNER, **options}
