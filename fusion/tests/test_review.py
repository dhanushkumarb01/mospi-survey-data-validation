import sqlite3

import pytest

from fusion.review import all_events, append_event, history, initialise, latest_statuses, verify_chain


def _decide(path, case="case_a", **extra):
    values = {"decision": "CONFIRMED_ERROR", "reason_code": "EXTRA_OR_MISSING_ZERO", "verification_source": "PHONE_CALL",
              "corrected_field": "salaried earnings", "corrected_value": "12000"}
    values.update(extra)
    return append_event(path, case_id=case, event_type="DECISION_MADE", actor="supervisor", **values)


def test_decision_taxonomy_reason_codes_and_append_only_audit(tmp_path):
    path = tmp_path / "audit.sqlite"
    initialise(path)
    append_event(path, case_id="case_a", event_type="CASE_VIEWED", actor="supervisor")
    _decide(path, opened_at_utc="2026-10-09T00:00:00+00:00")
    assert latest_statuses(path) == {"case_a": "CONFIRMED_ERROR"}
    decided = history(path, "case_a")[-1]
    assert decided["reason_code"] == "EXTRA_OR_MISSING_ZERO" and decided["seconds_on_case"] >= 0 and decided["actor_authenticated"] == 0
    with pytest.raises(ValueError, match="reason code"):
        _decide(path, reason_code="NOT_A_CODE")
    with pytest.raises(ValueError, match="verified"):
        _decide(path, verification_source=None)
    with pytest.raises(ValueError):
        append_event(path, case_id="x", event_type="DECISION_MADE", actor="a", decision="MAYBE")
    with sqlite3.connect(path) as connection, pytest.raises(sqlite3.DatabaseError, match="append-only"):
        connection.execute("UPDATE audit_events SET decision='VALID_BUT_UNUSUAL'")


def test_hash_chain_detects_tampering(tmp_path):
    path = tmp_path / "audit.sqlite"
    _decide(path)
    _decide(path, case="case_b")
    assert verify_chain(path)["status"] == "INTACT"
    with sqlite3.connect(path) as connection:   # an attacker with file access drops the triggers and edits a row
        connection.execute("DROP TRIGGER audit_no_update")
        connection.execute("UPDATE audit_events SET corrected_value='99999' WHERE case_id='case_b'")
    assert verify_chain(path)["status"] == "BROKEN"


def test_legacy_rows_are_sealed_not_rewritten_and_legacy_codes_read(tmp_path):
    path = tmp_path / "audit.sqlite"
    with sqlite3.connect(path) as connection:   # a V2.0 store
        connection.execute("CREATE TABLE audit_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, event_type TEXT NOT NULL, actor TEXT NOT NULL, "
                           "event_timestamp_utc TEXT NOT NULL, decision TEXT, comment TEXT, evidence_snapshot_json TEXT)")
        connection.execute("INSERT INTO audit_events(case_id,event_type,actor,event_timestamp_utc,decision) VALUES ('old','DECISION_MADE','x','2026-10-01T00:00:00','CONFIRMED_VALID')")
    initialise(path)
    assert latest_statuses(path)["old"] == "VALID_BUT_UNUSUAL"
    assert all_events(path)[0]["legacy_decision"] == "CONFIRMED_VALID"
    assert verify_chain(path)["status"] == "INTACT"
