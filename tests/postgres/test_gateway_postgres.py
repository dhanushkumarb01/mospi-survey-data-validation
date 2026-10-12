"""The hosted read gateway on the real reader role: same answers as the direct hosted reader, nothing more (synthetic data only)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from mospi.db.audit import PostgresAuditStore
from mospi.gateway.client import GatewayAuditStore, GatewayClient, GatewayOperations
from mospi.gateway.server import build_from_env, create_gateway
from mospi.gateway.signing import sign
from mospi.ingest.service import HostedOperations

pytestmark = pytest.mark.postgres
SECRET = "g" * 48
DECISION = {"event_type": "DECISION_MADE", "decision": "VALID_BUT_UNUSUAL", "reason_code": "GENUINE_HIGH_OR_LOW_VALUE", "verification_source": "PHONE_CALL"}


def _through_gateway(pg):
    gateway = TestClient(create_gateway(PostgresAuditStore(pg["reader"], hosted=True), HostedOperations(pg["reader"]), secrets_=[SECRET],
                                        loopback_only=False), base_url="http://127.0.0.1:8787")

    def transport(url, headers, timeout):
        response = gateway.get(url.replace("http://127.0.0.1:8787", ""), headers=headers)
        return response.status_code, response.content
    client = GatewayClient("http://127.0.0.1:8787", SECRET, transport=transport, cache_seconds=0)
    return gateway, GatewayAuditStore(client), GatewayOperations(client)


def test_gateway_matches_the_direct_hosted_reader_and_hides_what_it_hides(pg):
    store = PostgresAuditStore(pg["app"])
    store.append("synthetic_run", case_id="c1", actor="r", comment="private note", evidence_snapshot={"salary": 123456}, **DECISION)
    store.append("real_run", case_id="c1", actor="r", comment="real note", **DECISION)
    pg["admin"].execute("INSERT INTO runs (run_id, status, data_class, hosted_visible) VALUES ('synthetic_run', 'REGISTERED', 'SYNTHETIC', TRUE), "
                        "('real_run', 'REGISTERED', 'INTERNAL_REAL', FALSE)")
    store.verify("synthetic_run", record_as="tests")
    store.verify("real_run", record_as="tests")
    direct = PostgresAuditStore(pg["reader"], hosted=True)
    gateway, audit, operations = _through_gateway(pg)

    def same(a, b):
        return json.loads(json.dumps(a, default=str)) == json.loads(json.dumps(b, default=str))
    assert same(audit.history("synthetic_run", "c1"), direct.history("synthetic_run", "c1")) and audit.history("synthetic_run", "c1")
    assert same(audit.all_events("synthetic_run"), direct.all_events("synthetic_run"))
    assert audit.latest_statuses("synthetic_run") == direct.latest_statuses("synthetic_run") == {"c1": "VALID_BUT_UNUSUAL"}
    assert audit.verify("synthetic_run")["status"] == "INTACT"
    # The uncleared run, comments, snapshots and the operations trail are invisible through the gateway too.
    assert audit.history("real_run", "c1") == [] and audit.latest_statuses("real_run") == {} and audit.all_events("real_run") == []
    assert audit.verify("real_run")["status"] == "NOT_VERIFIED_YET"
    summary = operations.summary()
    assert [r["run_id"] for r in summary["runs"]] == ["synthetic_run"] and summary["database"]["role"] == "mospi_reader"
    text = json.dumps([audit.all_events("synthetic_run"), audit.history("synthetic_run", "c1"), summary])
    assert "private note" not in text and "123456" not in text and "real_run" not in text
    assert operations.database_status()["reachable"] is True
    for path in ("/v1/runs/__operations__/events", "/v1/runs/real_run/cases/c1/history"):
        response = gateway.get(path, headers=sign(SECRET, "GET", path))
        assert response.status_code in (200, 404) and "real note" not in response.text


def test_gateway_starts_only_as_the_read_only_reader_on_loopback(pg, monkeypatch):
    from psycopg.conninfo import make_conninfo
    monkeypatch.setenv("MOSPI_GATEWAY_SECRET", SECRET)
    monkeypatch.delenv("MOSPI_GATEWAY_DATABASE_URL", raising=False)
    assert build_from_env() is not None                                      # reader derived from the app URL + reader password
    monkeypatch.setenv("MOSPI_GATEWAY_DATABASE_URL", pg["urls"]["app"])
    with pytest.raises(RuntimeError, match="read-only role"):
        build_from_env()
    monkeypatch.setenv("MOSPI_GATEWAY_DATABASE_URL", make_conninfo(pg["urls"]["reader"], host="10.0.0.5"))
    with pytest.raises(RuntimeError, match="this computer only"):
        build_from_env()
    monkeypatch.setenv("MOSPI_GATEWAY_SECRET", "short")
    monkeypatch.delenv("MOSPI_GATEWAY_DATABASE_URL")
    with pytest.raises(ValueError):
        build_from_env()
