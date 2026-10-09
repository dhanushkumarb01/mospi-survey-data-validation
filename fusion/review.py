"""Append-only, tamper-evident local review and audit store; no survey response is modified.

* Append-only is enforced by the database: triggers abort any UPDATE or
  DELETE on ``audit_events``.
* Tamper evidence: every event stores ``previous_hash`` and
  ``event_hash = sha256(previous_hash + canonical event content)``.
  :func:`verify_chain` recomputes the chain; an edited, inserted or deleted
  row breaks it.  Rows written before the chain existed are not modified:
  the first chained event (``AUDIT_CHAIN_STARTED``) stores a digest that
  seals them.
* Reads use a read-only connection.
* ``actor_authenticated`` records whether the actor came from a verified
  sign-in; a typed name without sign-in is stored and shown as unverified.

The chain makes tampering *detectable* inside one file; it is not a
substitute for the PostgreSQL INSERT-only store and signed daily digests
planned for deployment (plan W7.7/W9.6), which belong to the later stage.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Decision taxonomy (plan §11).  Legacy V2.0 codes stay readable.
DECISIONS = {"CONFIRMED_ERROR", "VALID_BUT_UNUSUAL", "NEEDS_FIELD_VERIFICATION", "CANNOT_VERIFY", "ESCALATE"}
LEGACY_DECISIONS = {"CONFIRMED_ISSUE": "CONFIRMED_ERROR", "CONFIRMED_VALID": "VALID_BUT_UNUSUAL", "INCONCLUSIVE_NEEDS_FOLLOW_UP": "NEEDS_FIELD_VERIFICATION"}
REASON_CODES = {
    "CONFIRMED_ERROR": {"EXTRA_OR_MISSING_ZERO", "MONTHLY_ANNUAL_CONFUSION", "DIGIT_TRANSPOSITION", "WRONG_CODE", "WRONG_UNIT_OR_PERIOD",
                        "WRONG_PERSON_OR_HOUSEHOLD", "OTHER"},
    "VALID_BUT_UNUSUAL": {"GENUINE_HIGH_OR_LOW_VALUE", "SEASONAL_OR_ONE_OFF", "SPECIAL_CIRCUMSTANCE", "RARE_BUT_CORRECT_CODE", "OTHER"},
    "NEEDS_FIELD_VERIFICATION": {"CALL_BACK", "REVISIT", "CHECK_SCHEDULE_IMAGE", "OTHER"},
    "CANNOT_VERIFY": {"RESPONDENT_UNREACHABLE", "NO_SCHEDULE_IMAGE", "OTHER"},
    "ESCALATE": {"POSSIBLE_FIELDWORK_ISSUE", "NEEDS_SUBJECT_EXPERT", "OTHER"},
}
VERIFICATION_SOURCES = {"PHONE_CALL", "FIELD_REVISIT", "SCHEDULE_IMAGE", "SUPERVISOR_KNOWLEDGE", "NOT_VERIFIED"}
EVENT_TYPES = {"CASE_VIEWED", "DECISION_MADE", "EXPORT", "AUDIT_CHAIN_STARTED"}
MAX_TEXT = 2000

COLUMNS = {
    "event_id": "INTEGER PRIMARY KEY AUTOINCREMENT", "case_id": "TEXT NOT NULL", "event_type": "TEXT NOT NULL", "actor": "TEXT NOT NULL",
    "event_timestamp_utc": "TEXT NOT NULL", "decision": "TEXT", "comment": "TEXT", "evidence_snapshot_json": "TEXT",
    "reason_code": "TEXT", "verification_source": "TEXT", "corrected_field": "TEXT", "corrected_value": "TEXT", "lane": "TEXT",
    "opened_at_utc": "TEXT", "seconds_on_case": "REAL", "actor_authenticated": "INTEGER", "actor_role": "TEXT",
    "previous_hash": "TEXT", "event_hash": "TEXT",
}
HASHED_FIELDS = [c for c in COLUMNS if c not in ("event_id", "previous_hash", "event_hash")]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(previous: str, event: dict[str, Any]) -> str:
    content = json.dumps({k: event.get(k) for k in HASHED_FIELDS}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256((previous + "|" + content).encode("utf-8")).hexdigest()


def initialise(path: Path) -> None:
    """Create or migrate the store (adds columns and triggers; never rewrites existing rows)."""
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")   # one writer at a time, so only one chain start is ever written
        _initialise(connection)
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def _initialise(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE IF NOT EXISTS audit_events (" + ", ".join(
        f"{name} {kind}" for name, kind in list(COLUMNS.items())[:8]) + ")")
    present = {row[1] for row in connection.execute("PRAGMA table_info(audit_events)")}
    for name, kind in COLUMNS.items():
        if name not in present:
            connection.execute(f"ALTER TABLE audit_events ADD COLUMN {name} {kind}")
    connection.execute("CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit trail is append-only'); END")
    connection.execute("CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit trail is append-only'); END")
    chained = connection.execute("SELECT COUNT(*) FROM audit_events WHERE event_hash IS NOT NULL").fetchone()[0]
    if chained == 0:
        legacy = connection.execute("SELECT event_id, case_id, event_type, actor, event_timestamp_utc, decision, comment, evidence_snapshot_json "
                                    "FROM audit_events ORDER BY event_id").fetchall()
        seal = hashlib.sha256(json.dumps(legacy, default=str).encode("utf-8")).hexdigest()
        _insert(connection, {"case_id": "*", "event_type": "AUDIT_CHAIN_STARTED", "actor": "system", "event_timestamp_utc": _now(),
                             "comment": json.dumps({"rows_sealed": len(legacy), "sha256_of_rows_sealed": seal}), "actor_authenticated": 1, "actor_role": "system"})


def _insert(connection: sqlite3.Connection, event: dict[str, Any]) -> dict[str, Any]:
    row = connection.execute("SELECT event_hash FROM audit_events WHERE event_hash IS NOT NULL ORDER BY event_id DESC LIMIT 1").fetchone()
    event = {k: event.get(k) for k in HASHED_FIELDS}
    event["previous_hash"] = row[0] if row else "GENESIS"
    event["event_hash"] = _digest(event["previous_hash"], event)
    names = list(event)
    cursor = connection.execute(f"INSERT INTO audit_events({','.join(names)}) VALUES ({','.join(':' + n for n in names)})", event)
    event["event_id"] = cursor.lastrowid
    return event


def _text(value: Any, name: str) -> str | None:
    if value is None or value == "":
        return None
    text = str(value)
    if len(text) > MAX_TEXT:
        raise ValueError(f"{name} is longer than {MAX_TEXT} characters.")
    return text


class DecisionConflict(ValueError):
    """Another reviewer recorded a decision on the case after the client last saw it."""


_ANY = object()


def append_event(path: Path, *, case_id: str, event_type: str, actor: str, decision: str | None = None, comment: str | None = None,
                 evidence_snapshot: dict[str, Any] | None = None, reason_code: str | None = None, verification_source: str | None = None,
                 corrected_field: str | None = None, corrected_value: str | None = None, lane: str | None = None,
                 opened_at_utc: str | None = None, actor_authenticated: bool = False, actor_role: str | None = None,
                 expected_last_decision_id: Any = _ANY) -> dict[str, Any]:
    """Append one event.  ``expected_last_decision_id`` (event id, or None for "no decision yet") makes a
    decision fail with :class:`DecisionConflict` when someone else decided the case in the meantime."""
    if event_type not in EVENT_TYPES - {"AUDIT_CHAIN_STARTED"}:
        raise ValueError("Unknown event type.")
    if event_type == "DECISION_MADE":
        if decision not in DECISIONS:
            raise ValueError(f"A decision must be one of {sorted(DECISIONS)}.")
        if reason_code not in REASON_CODES[decision]:
            raise ValueError(f"A {decision} decision needs a reason code from {sorted(REASON_CODES[decision])}.")
        if verification_source not in VERIFICATION_SOURCES:
            raise ValueError(f"Say how it was verified: one of {sorted(VERIFICATION_SOURCES)}.")
        if decision == "CONFIRMED_ERROR" and corrected_value and not corrected_field:
            raise ValueError("A corrected value needs the item it corrects.")
    seconds = None
    if opened_at_utc:
        try:
            opened = datetime.fromisoformat(str(opened_at_utc).replace("Z", "+00:00"))
            seconds = max(0.0, (datetime.now(timezone.utc) - opened).total_seconds())
        except ValueError as error:
            raise ValueError("opened_at_utc must be an ISO timestamp.") from error
    initialise(path)
    event = {"case_id": _text(case_id, "case_id"), "event_type": event_type, "actor": (_text(actor, "actor") or "local-supervisor").strip(),
             "event_timestamp_utc": _now(), "decision": decision, "comment": _text(comment, "comment"),
             "evidence_snapshot_json": json.dumps(evidence_snapshot, sort_keys=True, default=str) if evidence_snapshot else None,
             "reason_code": reason_code, "verification_source": verification_source, "corrected_field": _text(corrected_field, "corrected_field"),
             "corrected_value": _text(corrected_value, "corrected_value"), "lane": lane, "opened_at_utc": opened_at_utc, "seconds_on_case": seconds,
             "actor_authenticated": int(bool(actor_authenticated)), "actor_role": actor_role}
    # BEGIN IMMEDIATE takes the write lock before the last hash is read, so concurrent appends
    # (threads or processes) are serialised and cannot fork the chain.
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        try:
            if event_type == "DECISION_MADE" and expected_last_decision_id is not _ANY:
                latest = connection.execute("SELECT MAX(event_id) FROM audit_events WHERE case_id=? AND event_type='DECISION_MADE'", (case_id,)).fetchone()[0]
                expected = None if expected_last_decision_id in (None, "") else int(expected_last_decision_id)
                if latest != expected:
                    raise DecisionConflict("Another reviewer recorded a decision on this case after you opened it. Reload the case to see it before deciding.")
            stored = _insert(connection, event)
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
    finally:
        connection.close()
    return stored


def _read(path: Path):
    if not Path(path).is_file():
        return None
    connection = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _normalised(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("decision") in LEGACY_DECISIONS:
        row["legacy_decision"] = row["decision"]
        row["decision"] = LEGACY_DECISIONS[row["decision"]]
    return row


def history(path: Path, case_id: str) -> list[dict[str, Any]]:
    connection = _read(path)
    if connection is None:
        return []
    with connection:
        return [_normalised(dict(row)) for row in connection.execute("SELECT * FROM audit_events WHERE case_id=? ORDER BY event_id", (case_id,))]


def latest_statuses(path: Path) -> dict[str, str]:
    connection = _read(path)
    if connection is None:
        return {}
    with connection:
        rows = connection.execute(
            """SELECT case_id, decision FROM audit_events WHERE event_type='DECISION_MADE'
               AND event_id IN (SELECT MAX(event_id) FROM audit_events WHERE event_type='DECISION_MADE' GROUP BY case_id)""").fetchall()
    return {case_id: LEGACY_DECISIONS.get(decision, decision) for case_id, decision in rows}


def all_events(path: Path) -> list[dict[str, Any]]:
    """Every audit event without snapshots, oldest first (read-only)."""
    connection = _read(path)
    if connection is None:
        return []
    with connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_events)")}
        wanted = [c for c in ("event_id", "case_id", "event_type", "actor", "event_timestamp_utc", "decision", "comment", "reason_code",
                              "verification_source", "corrected_field", "corrected_value", "lane", "seconds_on_case", "actor_authenticated", "actor_role") if c in columns]
        return [_normalised(dict(row)) for row in connection.execute(f"SELECT {', '.join(wanted)} FROM audit_events ORDER BY event_id")]


def verify_chain(path: Path) -> dict[str, Any]:
    """Recompute the hash chain; report the first break, if any."""
    connection = _read(path)
    if connection is None:
        return {"status": "NO_AUDIT_STORE", "events": 0}
    with connection:
        rows = [dict(r) for r in connection.execute("SELECT * FROM audit_events ORDER BY event_id")]
    chained = [r for r in rows if r.get("event_hash")]
    if not chained:
        return {"status": "NOT_CHAINED", "events": len(rows)}
    previous = "GENESIS"
    for row in chained:
        if row["previous_hash"] != previous or _digest(previous, row) != row["event_hash"]:
            return {"status": "BROKEN", "events": len(rows), "first_bad_event_id": row["event_id"]}
        previous = row["event_hash"]
    genesis = chained[0]
    legacy = [tuple(r.values()) for r in rows if r["event_id"] < genesis["event_id"]]
    sealed = json.loads(genesis.get("comment") or "{}")
    if genesis["event_type"] == "AUDIT_CHAIN_STARTED" and sealed.get("rows_sealed") is not None:
        # Re-derive the seal from the rows as they were before the migration added columns.
        base = [r[:8] for r in legacy]
        if len(base) != sealed["rows_sealed"] or hashlib.sha256(json.dumps(base, default=str).encode("utf-8")).hexdigest() != sealed["sha256_of_rows_sealed"]:
            return {"status": "BROKEN", "events": len(rows), "detail": "rows written before the chain started have changed"}
    unchained_after = [r["event_id"] for r in rows if not r.get("event_hash") and r["event_id"] > genesis["event_id"]]
    if unchained_after:
        return {"status": "BROKEN", "events": len(rows), "detail": "unchained rows after the chain started", "first_bad_event_id": unchained_after[0]}
    return {"status": "INTACT", "events": len(rows), "chained_events": len(chained), "last_hash": previous}
