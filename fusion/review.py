"""Append-only local review and audit store; no survey response is modified."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DECISIONS = {"CONFIRMED_ISSUE", "CONFIRMED_VALID", "INCONCLUSIVE_NEEDS_FOLLOW_UP"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialise(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                event_timestamp_utc TEXT NOT NULL,
                decision TEXT,
                comment TEXT,
                evidence_snapshot_json TEXT
            )"""
        )
        connection.commit()


def append_event(path: Path, *, case_id: str, event_type: str, actor: str, decision: str | None = None,
                 comment: str | None = None, evidence_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    if event_type == "DECISION_MADE" and decision not in DECISIONS:
        raise ValueError("A decision must be CONFIRMED_ISSUE, CONFIRMED_VALID, or INCONCLUSIVE_NEEDS_FOLLOW_UP.")
    initialise(path)
    event = {
        "case_id": case_id, "event_type": event_type, "actor": actor.strip() or "local-supervisor",
        "event_timestamp_utc": _now(), "decision": decision, "comment": comment,
        "evidence_snapshot_json": json.dumps(evidence_snapshot, sort_keys=True) if evidence_snapshot else None,
    }
    with sqlite3.connect(path) as connection:
        cursor = connection.execute(
            "INSERT INTO audit_events(case_id,event_type,actor,event_timestamp_utc,decision,comment,evidence_snapshot_json) VALUES (:case_id,:event_type,:actor,:event_timestamp_utc,:decision,:comment,:evidence_snapshot_json)", event
        )
        event["event_id"] = cursor.lastrowid
        connection.commit()
    return event


def history(path: Path, case_id: str) -> list[dict[str, Any]]:
    initialise(path)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM audit_events WHERE case_id=? ORDER BY event_id", (case_id,))]


def latest_statuses(path: Path) -> dict[str, str]:
    initialise(path)
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            """SELECT case_id, decision FROM audit_events WHERE event_type='DECISION_MADE'
               AND event_id IN (SELECT MAX(event_id) FROM audit_events WHERE event_type='DECISION_MADE' GROUP BY case_id)"""
        ).fetchall()
    return {case_id: decision for case_id, decision in rows}


def all_events(path: Path) -> list[dict[str, Any]]:
    """Every audit event without snapshots, oldest first (read-only)."""
    initialise(path)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(
            "SELECT event_id, case_id, event_type, actor, event_timestamp_utc, decision, comment FROM audit_events ORDER BY event_id")]
