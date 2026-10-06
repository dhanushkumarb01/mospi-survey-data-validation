from fusion.review import append_event, history, latest_statuses


def test_decision_and_append_only_audit(tmp_path):
    path = tmp_path / "audit.sqlite"
    append_event(path, case_id="case_a", event_type="CASE_VIEWED", actor="reviewer")
    append_event(path, case_id="case_a", event_type="DECISION_MADE", actor="reviewer", decision="CONFIRMED_VALID", comment="Checked source schedule.")
    assert len(history(path, "case_a")) == 2
    assert latest_statuses(path)["case_a"] == "CONFIRMED_VALID"
