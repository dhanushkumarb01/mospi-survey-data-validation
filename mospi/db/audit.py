"""Review/audit stores behind one interface, selected by configuration.

* :class:`SqliteAuditStore` - the existing per-run ``review_audit.sqlite`` (mospi/pipeline/stages/fusion/review.py, unchanged).
* :class:`PostgresAuditStore` - the same events, the same SHA-256 chain per run, in PostgreSQL.  Validation, digest,
  legacy seal and verification are imported from review.py, never re-implemented, so the two cannot drift.
* ``hosted=True`` - read-only access through the ``hosted_audit_*`` views (no comments, snapshots or corrected values);
  chain verification is the latest result recorded on the processing machine.

Appends are serialised per run with a transaction-scoped advisory lock (the PostgreSQL equivalent of
``BEGIN IMMEDIATE``), so concurrent writers cannot fork a chain, and a stale decision raises
:class:`DecisionConflict` exactly as before.  There is no silent fallback: if PostgreSQL is unreachable the
call fails with :class:`DatabaseUnavailable` and nothing is written anywhere else.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mospi.pipeline.stages.fusion import review
from mospi.pipeline.stages.fusion.review import COLUMNS, HASHED_FIELDS, DecisionConflict, _digest, _now, build_event, legacy_seal, verify_rows

from .connection import Database

ALL_COLUMNS = list(COLUMNS)
LEGACY_COLUMNS = ALL_COLUMNS[:8]
EVENT_COLUMNS = [c for c in ("event_id", "case_id", "event_type", "actor", "event_timestamp_utc", "decision", "comment", "reason_code",
                             "verification_source", "corrected_field", "corrected_value", "lane", "seconds_on_case", "actor_authenticated", "actor_role")]
HOSTED_COLUMNS = ["event_id", "case_id", "event_type", "actor", "event_timestamp_utc", "decision", "reason_code", "verification_source",
                  "corrected_field", "lane", "opened_at_utc", "seconds_on_case", "actor_authenticated", "actor_role", "event_hash"]
# Operational events (uploads, validation jobs, publication, checks) share the same chained trail under their own key.
OPERATIONS_RUN = "__operations__"
OPERATION_EVENTS = {"DATASET_CREATED", "FILE_RECEIVED", "PREFLIGHT_COMPLETED", "DATASET_REJECTED", "VALIDATION_REQUESTED", "VALIDATION_STARTED",
                    "VALIDATION_SUCCEEDED", "VALIDATION_FAILED", "RUN_PUBLISHED", "JOB_RETRIED", "JOB_CANCELLED", "INTEGRITY_CHECK_COMPLETED",
                    "DATASET_REGISTERED", "AUDIT_MIGRATED", "HOSTING_APPROVED", "SERVING_SET_LOADED"}
_ANY = review._ANY


def run_key(run: str | Path) -> str:
    return run.name if isinstance(run, Path) else str(run)


class SqliteAuditStore:
    backend, writable, hosted = "sqlite", True, False

    @staticmethod
    def _path(run: str | Path) -> Path:
        return Path(run) / "review_audit.sqlite"

    def append(self, run: Path, **fields: Any) -> dict[str, Any]:
        return review.append_event(self._path(run), **fields)

    def history(self, run: Path, case_id: str) -> list[dict[str, Any]]:
        return review.history(self._path(run), case_id)

    def latest_statuses(self, run: Path) -> dict[str, str]:
        return review.latest_statuses(self._path(run))

    def all_events(self, run: Path) -> list[dict[str, Any]]:
        return review.all_events(self._path(run))

    def verify(self, run: Path) -> dict[str, Any]:
        return review.verify_chain(self._path(run))


class PostgresAuditStore:
    backend = "postgres"

    def __init__(self, db: Database, *, hosted: bool = False) -> None:
        self.db = db
        self.hosted = hosted
        self.writable = not hosted

    # ------------------------------------------------------------ writing

    @staticmethod
    def _lock(connection, key: str) -> None:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('mospi-audit:' || %s, 0))", (key,))

    @staticmethod
    def _last_hash(connection, key: str) -> str | None:
        row = connection.execute("SELECT event_hash FROM audit_events WHERE run_id = %s AND event_hash IS NOT NULL ORDER BY event_id DESC LIMIT 1",
                                 (key,)).fetchone()
        return row["event_hash"] if row else None

    @staticmethod
    def _insert(connection, key: str, event: dict[str, Any], previous: str) -> dict[str, Any]:
        event = {k: event.get(k) for k in HASHED_FIELDS}
        event["previous_hash"] = previous
        event["event_hash"] = _digest(previous, event)
        next_id = connection.execute("SELECT COALESCE(MAX(event_id), 0) + 1 AS n FROM audit_events WHERE run_id = %s", (key,)).fetchone()["n"]
        names = ["run_id", "event_id", *event]
        connection.execute(f"INSERT INTO audit_events ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))})",
                           [key, next_id, *event.values()])
        return {"event_id": next_id, **event}

    def _initialise(self, connection, key: str) -> str:
        """Inside a locked transaction: start the chain (sealing any legacy rows) if the run has none; return the head hash."""
        head = self._last_hash(connection, key)
        if head is not None:
            return head
        legacy = [[row[c] for c in LEGACY_COLUMNS] for row in connection.execute(
            f"SELECT {', '.join(LEGACY_COLUMNS)} FROM audit_events WHERE run_id = %s ORDER BY event_id", (key,)).fetchall()]
        started = self._insert(connection, key, {"case_id": "*", "event_type": "AUDIT_CHAIN_STARTED", "actor": "system", "event_timestamp_utc": _now(),
                                                 "comment": json.dumps(legacy_seal(legacy)), "actor_authenticated": 1, "actor_role": "system"}, "GENESIS")
        return started["event_hash"]

    def register_run(self, run: str | Path) -> None:
        """Start the run's chain if it has none (idempotent; the PostgreSQL counterpart of review.initialise)."""
        self._require_writable()
        key = run_key(run)
        with self.db.transaction() as connection:
            self._lock(connection, key)
            self._initialise(connection, key)

    def append(self, run: str | Path, *, expected_last_decision_id: Any = _ANY, **fields: Any) -> dict[str, Any]:
        self._require_writable()
        event = build_event(**fields)
        key = run_key(run)
        with self.db.transaction() as connection:
            self._lock(connection, key)
            head = self._initialise(connection, key)
            if event["event_type"] == "DECISION_MADE" and expected_last_decision_id is not _ANY:
                latest = connection.execute("SELECT MAX(event_id) AS m FROM audit_events WHERE run_id = %s AND case_id = %s AND event_type = 'DECISION_MADE'",
                                            (key, event["case_id"])).fetchone()["m"]
                expected = None if expected_last_decision_id in (None, "") else int(expected_last_decision_id)
                if latest != expected:
                    raise DecisionConflict("Another reviewer recorded a decision on this case after you opened it. Reload the case to see it before deciding.")
            return self._insert(connection, key, event, head)

    def append_operation(self, event_type: str, *, subject: str, actor: str, details: dict[str, Any] | None = None,
                         actor_authenticated: bool = False, actor_role: str | None = None, connection=None) -> dict[str, Any]:
        """Record an operation (upload, validation, publication, check) in the chained operations trail."""
        self._require_writable()
        if event_type not in OPERATION_EVENTS:
            raise ValueError(f"Unknown operation event {event_type!r}.")
        event = {"case_id": str(subject)[:200], "event_type": event_type, "actor": (str(actor or "system")[:120]).strip() or "system",
                 "event_timestamp_utc": _now(), "comment": json.dumps(details or {}, sort_keys=True, default=str)[:review.MAX_TEXT],
                 "actor_authenticated": int(bool(actor_authenticated)), "actor_role": actor_role}

        def write(conn):
            self._lock(conn, OPERATIONS_RUN)
            return self._insert(conn, OPERATIONS_RUN, event, self._initialise(conn, OPERATIONS_RUN))

        if connection is not None:
            return write(connection)
        with self.db.transaction() as conn:
            return write(conn)

    def _require_writable(self) -> None:
        if not self.writable:
            raise PermissionError("This instance reads the audit trail only.")

    # ------------------------------------------------------------ reading

    @staticmethod
    def _normalise(row: dict[str, Any]) -> dict[str, Any]:
        return review._normalised(dict(row))

    def history(self, run: str | Path, case_id: str) -> list[dict[str, Any]]:
        table, columns = ("hosted_audit_events", HOSTED_COLUMNS) if self.hosted else ("audit_events", ALL_COLUMNS)
        rows = self.db.fetch(f"SELECT {', '.join(columns)} FROM {table} WHERE run_id = %s AND case_id = %s ORDER BY event_id", (run_key(run), case_id))
        return [self._normalise(r) for r in rows]

    def latest_statuses(self, run: str | Path) -> dict[str, str]:
        table = "hosted_audit_events" if self.hosted else "audit_events"
        rows = self.db.fetch(f"SELECT DISTINCT ON (case_id) case_id, decision FROM {table} WHERE run_id = %s AND event_type = 'DECISION_MADE' "
                             "ORDER BY case_id, event_id DESC", (run_key(run),))
        return {r["case_id"]: review.LEGACY_DECISIONS.get(r["decision"], r["decision"]) for r in rows}

    def all_events(self, run: str | Path) -> list[dict[str, Any]]:
        table = "hosted_audit_events" if self.hosted else "audit_events"
        columns = [c for c in EVENT_COLUMNS if not self.hosted or c in HOSTED_COLUMNS]
        rows = self.db.fetch(f"SELECT {', '.join(columns)} FROM {table} WHERE run_id = %s ORDER BY event_id", (run_key(run),))
        return [self._normalise({**{"comment": None, "corrected_value": None}, **r}) for r in rows]

    def rows(self, run: str | Path) -> list[dict[str, Any]]:
        """Every column of every event of a run, in COLUMNS order (as SQLite ``SELECT *`` returns them)."""
        return [dict(r) for r in self.db.fetch(f"SELECT {', '.join(ALL_COLUMNS)} FROM audit_events WHERE run_id = %s ORDER BY event_id", (run_key(run),))]

    def verify(self, run: str | Path, *, record_as: str | None = None) -> dict[str, Any]:
        key = run_key(run)
        if self.hosted:
            row = self.db.fetchone("SELECT status, events, chained_events, last_hash, checked_utc FROM hosted_audit_verifications WHERE run_id = %s", (key,))
            if row is None:
                return {"status": "NOT_VERIFIED_YET", "events": None,
                        "detail": "No chain verification has been recorded for this run on the processing machine yet."}
            return {**{k: row[k] for k in ("status", "events", "chained_events", "last_hash")}, "verified_on": "processing machine",
                    "checked_utc": row["checked_utc"].isoformat()}
        rows = self.rows(key)
        result = verify_rows(rows) if rows else {"status": "NO_AUDIT_STORE", "events": 0}
        if record_as:
            self.record_verification(key, result, record_as)
        return result

    def record_verification(self, run: str | Path, result: dict[str, Any], checked_by: str, connection=None) -> None:
        detail = result.get("detail") or (f"first bad event {result['first_bad_event_id']}" if result.get("first_bad_event_id") else None)
        params = (run_key(run), result["status"], int(result.get("events") or 0), result.get("chained_events"), result.get("last_hash"), detail, checked_by)
        sql = ("INSERT INTO audit_verifications (run_id, status, events, chained_events, last_hash, detail, checked_by) "
               "VALUES (%s, %s, %s, %s, %s, %s, %s)")
        if connection is not None:
            connection.execute(sql, params)
        else:
            self.db.execute(sql, params)

    def run_keys(self) -> list[str]:
        return [r["run_id"] for r in self.db.fetch("SELECT DISTINCT run_id FROM audit_events ORDER BY run_id")]
