"""The three roles and what each may do.  The server checks these capabilities; the UI receives them from /api/session
and only hides what a role cannot use."""
from __future__ import annotations

from typing import Any

ROLES = ("admin", "supervisor", "analyst")
ROLE_LABELS = {"admin": "Administrator", "supervisor": "Supervisor", "analyst": "Analyst"}
# Accounts an administrator can create in the workspace.  Administrator accounts come only from the command line.
CREATABLE_ROLES = ("supervisor", "analyst")

CAPABILITIES: dict[str, frozenset[str]] = {
    # view: review pages and analytics; decide: record review decisions; export: the logged CSV export;
    # operations: datasets, jobs, checks and alerts (read); run: uploads, validation, retries, checks, batches;
    # manage_users: create supervisor and analyst accounts, reset their passwords, change or deactivate them.
    "admin": frozenset({"view", "decide", "export", "operations", "run", "manage_users"}),
    "supervisor": frozenset({"view", "decide", "export"}),
    "analyst": frozenset({"view", "operations"}),
}


def can(user: dict[str, Any] | None, capability: str) -> bool:
    return user is not None and capability in CAPABILITIES.get(user.get("role", ""), frozenset())


def capabilities(user: dict[str, Any] | None) -> list[str]:
    return sorted(CAPABILITIES.get(user.get("role", ""), frozenset())) if user else []
