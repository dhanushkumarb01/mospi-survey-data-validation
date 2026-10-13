"""Server-side account administration: the only way to create or change an administrator account.

    python -m mospi.auth create-admin --username admin --name "Full Name"
    python -m mospi.auth reset-password --username admin       # any account, e.g. a locked-out administrator
    python -m mospi.auth deactivate --username someone          # or: activate
    python -m mospi.auth list

With ``MOSPI_DATABASE_URL`` configured the accounts are in PostgreSQL and these commands use the administrative connection
(``MOSPI_DB_ADMIN_URL``: the table owner, the one role the database lets create an administrator).  Without a database they
use the SQLite account file (``MOSPI_USERS_DB``, or ``--sqlite PATH``).

A new or reset password is generated here and printed once; nothing else stores or shows it.  Give it to the person through a
separate channel.  They must choose their own at their first sign-in.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .passwords import hash_password, temporary_password
from .roles import ROLE_LABELS
from .store import AccountError, PostgresUserStore, SqliteUserStore, UserStore, normalise_username


def _store(sqlite: Path | None) -> UserStore:
    from mospi.db.config import load_env_file
    load_env_file()
    if sqlite is not None:
        store = SqliteUserStore(sqlite)
    elif os.environ.get("MOSPI_DATABASE_URL", "").strip():
        from mospi.db.migrate import admin_database
        return PostgresUserStore(admin_database(), origin="cli")
    else:
        from . import sqlite_path
        store = SqliteUserStore(sqlite_path())
    store.origin = "cli"
    return store


def _actor() -> str:
    return f"server: {os.environ.get('USERNAME') or os.environ.get('USER') or 'operator'}"


def _account(store: UserStore, username: str) -> dict:
    account = store.login_record(username)
    if account is None:
        raise AccountError(f"No account named {normalise_username(username)!r}.")
    return account


def _print_credentials(username: str, password: str) -> None:
    print(f"  username:           {username}")
    print(f"  temporary password: {password}")
    print("Shown once. Give it to the person through a separate channel; they choose their own password at the first sign-in.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mospi.auth", description="Administrator accounts and account recovery (server only).")
    parser.add_argument("--sqlite", type=Path, help="use this SQLite account file instead of the configured store")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin", help="create an administrator account")
    create.add_argument("--username", required=True)
    create.add_argument("--name", required=True, help="the person's name, as shown in the audit trail")
    reset = commands.add_parser("reset-password", help="set a new temporary password for any account and unlock it")
    reset.add_argument("--username", required=True)
    for name in ("activate", "deactivate"):
        commands.add_parser(name, help=f"{name} any account").add_argument("--username", required=True)
    commands.add_parser("list", help="list the accounts")
    args = parser.parse_args(argv)
    try:
        store = _store(args.sqlite)
        if args.command == "create-admin":
            password = temporary_password()
            account = store.create(username=args.username, display_name=args.name, role="admin", password_hash=hash_password(password),
                                   created_by=_actor(), allow_admin=True)
            print(f"Administrator account created for {account['display_name']}.")
            _print_credentials(account["username"], password)
        elif args.command == "reset-password":
            account = _account(store, args.username)
            password = temporary_password()
            store.reset_password(account["user_id"], hash_password(password), actor=_actor(), allow_admin=True)
            print(f"New temporary password set for {account['display_name']}; the account is unlocked and its sessions have ended.")
            _print_credentials(account["username"], password)
        elif args.command in ("activate", "deactivate"):
            account = _account(store, args.username)
            store.update(account["user_id"], actor=_actor(), active=args.command == "activate", allow_admin=True)
            print(f"{account['username']}: {'active' if args.command == 'activate' else 'deactivated'}.")
        else:
            for account in store.list_users():
                state = "active" if account["active"] else "deactivated"
                print(f"{account['username']:<24} {ROLE_LABELS[account['role']]:<14} {state:<12} {account['display_name']}")
        return 0
    except AccountError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except Exception as error:   # noqa: BLE001 - e.g. the database is unreachable or migration 0005 is not applied
        from mospi.db.connection import redact
        print(f"error: {redact(str(error))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
