"""Hosted read gateway (Cloudflare Tunnel origin) and its client, without PostgreSQL: access controls and failure handling.

The end-to-end path against a real reader role is in tests/postgres/test_gateway_postgres.py.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mospi.db.connection import DatabaseUnavailable
from mospi.gateway.client import GatewayAuditStore, GatewayClient, GatewayOperations
from mospi.gateway.server import create_gateway
from mospi.gateway.signing import SigningError, Verifier, sign

ROOT = Path(__file__).resolve().parents[2]
SECRET = "s" * 40
DEMO_RUN = "2024_first_visit_demo"


class FakeDb:
    def __init__(self) -> None:
        self.calls = 0
        self.down = False

    def ping(self) -> dict:
        self.calls += 1
        if self.down:
            raise DatabaseUnavailable("PostgreSQL is not reachable: connection refused")
        return {"role": "mospi_reader", "ssl": False}


class FakeAudit:
    backend, writable, hosted = "postgres", False, True

    def __init__(self, db: FakeDb) -> None:
        self.db = db

    def _touch(self):
        self.db.ping()

    def history(self, run, case_id):
        self._touch()
        return [{"event_id": 2, "case_id": case_id, "event_type": "DECISION_MADE", "decision": "VALID_BUT_UNUSUAL", "actor": "Reviewer"}] if case_id == "case_1" else []

    def latest_statuses(self, run):
        self._touch()
        return {"case_1": "VALID_BUT_UNUSUAL"}

    def all_events(self, run):
        self._touch()
        return [{"event_id": 2, "case_id": "case_1", "event_type": "DECISION_MADE", "decision": "VALID_BUT_UNUSUAL", "seconds_on_case": 12.5}]

    def verify(self, run):
        self._touch()
        return {"status": "INTACT", "events": 2, "verified_on": "processing machine"}


class FakeOperations:
    hosted = True

    def __init__(self, db: FakeDb) -> None:
        self.db = db

    def summary(self):
        self.db.ping()
        return {"backend": "postgres", "hosted": True, "database": {"reachable": True}, "runs": [{"run_id": DEMO_RUN, "data_class": "SYNTHETIC"}],
                "last_check": None, "last_check_findings": [], "audit_verifications": [], "failed_jobs": [], "active_jobs": [], "open_alerts": None}


@pytest.fixture()
def gateway():
    db = FakeDb()
    app = create_gateway(FakeAudit(db), FakeOperations(db), secrets_=[SECRET], loopback_only=False)
    return TestClient(app, base_url="http://127.0.0.1:8787"), db


def signed(path: str, secret: str = SECRET, method: str = "GET") -> dict[str, str]:
    return sign(secret, method, path)


def transport_for(client: TestClient):
    def transport(url, headers, timeout):
        response = client.get(url.replace("http://127.0.0.1:8787", ""), headers=headers)
        return response.status_code, response.content
    return transport


# ------------------------------------------------------------------ signing


def test_signature_window_and_replay():
    verifier = Verifier([SECRET])
    headers = sign(SECRET, "GET", "/v1/status", now=1_000_000)
    verifier.verify("GET", "/v1/status", headers, now=1_000_010)
    with pytest.raises(SigningError, match="replayed"):
        verifier.verify("GET", "/v1/status", headers, now=1_000_011)
    with pytest.raises(SigningError, match="window"):
        verifier.verify("GET", "/v1/status", sign(SECRET, "GET", "/v1/status", now=1_000_000), now=1_000_500)
    with pytest.raises(SigningError, match="bad signature"):
        verifier.verify("GET", "/v1/summary", sign(SECRET, "GET", "/v1/status", now=1_000_000), now=1_000_000)   # path is signed
    with pytest.raises(SigningError, match="bad signature"):
        verifier.verify("GET", "/v1/status", sign("t" * 40, "GET", "/v1/status", now=1_000_000), now=1_000_000)
    with pytest.raises(SigningError, match="malformed"):
        verifier.verify("GET", "/v1/status", {}, now=1_000_000)
    rotated = Verifier(["n" * 40, SECRET])                       # previous secret still accepted during rotation
    rotated.verify("GET", "/v1/status", sign(SECRET, "GET", "/v1/status", now=1_000_000), now=1_000_000)


def test_short_secret_is_refused(monkeypatch):
    from mospi.gateway.signing import configured_secret
    monkeypatch.setenv("MOSPI_GATEWAY_SECRET", "short")
    with pytest.raises(SigningError):
        configured_secret()


# ------------------------------------------------------------------ gateway access controls


def test_gateway_refuses_everything_unsigned_and_touches_no_database(gateway):
    client, db = gateway
    for path in ("/v1/status", "/v1/summary", f"/v1/runs/{DEMO_RUN}/events", "/docs", "/openapi.json", "/", "/v1/anything"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.headers["cache-control"] == "no-store" and "server" not in response.headers
    assert client.get("/v1/status", headers=signed("/v1/status", "w" * 40)).status_code == 401
    assert db.calls == 0


def test_gateway_serves_only_fixed_read_routes(gateway):
    client, db = gateway
    assert client.get("/v1/status", headers=signed("/v1/status")).json()["role"] == "mospi_reader"
    path = f"/v1/runs/{DEMO_RUN}/cases/case_1/history"
    assert client.get(path, headers=signed(path)).json()[0]["decision"] == "VALID_BUT_UNUSUAL"
    for bad in ("/v1/runs/__operations__/events", "/v1/runs/a%2F..%2Fb/events", "/docs", "/openapi.json", "/v1/runs/x/delete"):
        assert client.get(bad, headers=signed(bad)).status_code == 404, bad
    for method in ("post", "put", "delete", "patch"):
        assert getattr(client, method)("/v1/status", headers=signed("/v1/status", method=method.upper())).status_code == 405
    body = client.request("GET", "/v1/status", content=b"x", headers=signed("/v1/status"))
    assert body.status_code == 400
    # A captured request cannot be replayed.
    headers = signed("/v1/summary")
    assert client.get("/v1/summary", headers=headers).status_code == 200
    assert client.get("/v1/summary", headers=headers).status_code == 401


def test_gateway_requires_loopback_peer_and_known_host():
    db = FakeDb()
    loopback = TestClient(create_gateway(FakeAudit(db), FakeOperations(db), secrets_=[SECRET]))       # TestClient's peer is not loopback
    assert loopback.get("/v1/status", headers=signed("/v1/status")).status_code == 403
    hosts = TestClient(create_gateway(FakeAudit(db), FakeOperations(db), secrets_=[SECRET], loopback_only=False,
                                      allowed_hosts={"gw.example.org"}), base_url="http://evil.example.com")
    assert hosts.get("/v1/status", headers=signed("/v1/status")).status_code == 421
    assert db.calls == 0


def test_gateway_rate_limits_and_reports_database_outage_without_details():
    db = FakeDb()
    client = TestClient(create_gateway(FakeAudit(db), FakeOperations(db), secrets_=[SECRET], loopback_only=False, rate_per_minute=3,
                                       failures_per_minute=100))
    assert [client.get("/v1/status", headers=signed("/v1/status")).status_code for _ in range(4)] == [200, 200, 200, 429]
    db.down = True
    client = TestClient(create_gateway(FakeAudit(db), FakeOperations(db), secrets_=[SECRET], loopback_only=False))
    response = client.get("/v1/summary", headers=signed("/v1/summary"))
    assert response.status_code == 503 and "refused" not in response.text
    flood = TestClient(create_gateway(FakeAudit(db), FakeOperations(db), secrets_=[SECRET], loopback_only=False, failures_per_minute=2))
    assert [flood.get("/v1/status").status_code for _ in range(3)] == [401, 401, 429]


def test_gateway_refuses_a_writable_store():
    class Writable(FakeAudit):
        writable = True
    with pytest.raises(ValueError):
        create_gateway(Writable(FakeDb()), FakeOperations(FakeDb()), secrets_=[SECRET])


# ------------------------------------------------------------------ client


def test_client_reads_through_gateway_and_maps_every_failure_to_unavailable(gateway):
    client, _ = gateway
    gateway_client = GatewayClient("http://127.0.0.1:8787", SECRET, transport=transport_for(client))
    audit, operations = GatewayAuditStore(gateway_client), GatewayOperations(gateway_client)
    assert audit.latest_statuses(Path("x") / DEMO_RUN) == {"case_1": "VALID_BUT_UNUSUAL"}
    assert audit.history(DEMO_RUN, "case_1")[0]["actor"] == "Reviewer"
    assert audit.history(DEMO_RUN, "../etc") == [] and audit.latest_statuses("bad/run") == {}     # never sent
    assert audit.verify(DEMO_RUN)["status"] == "INTACT"
    assert operations.database_status() == {"reachable": True, "role": "mospi_reader", "ssl": False, "via": "gateway"}
    assert operations.summary()["database"]["via"] == "gateway"
    with pytest.raises(PermissionError):
        audit.append(DEMO_RUN, case_id="case_1")
    # Cached reads are fresh copies.
    audit.latest_statuses(DEMO_RUN)["case_1"] = "changed"
    assert audit.latest_statuses(DEMO_RUN)["case_1"] == "VALID_BUT_UNUSUAL"

    wrong = GatewayClient("http://127.0.0.1:8787", "w" * 40, transport=transport_for(client))
    with pytest.raises(DatabaseUnavailable, match="signature") as error:
        wrong.get("/v1/status")
    assert "w" * 40 not in str(error.value)
    for status, words in ((403, "Access"), (302, "login"), (530, "Tunnel"), (503, "PostgreSQL"), (502, "not running"), (500, "unexpected")):
        failing = GatewayClient("https://gw.example.org", SECRET, transport=lambda u, h, t, s=status: (s, b""))
        with pytest.raises(DatabaseUnavailable, match=words):
            failing.get("/v1/status")

    def offline(url, headers, timeout):
        raise TimeoutError("timed out")
    down = GatewayOperations(GatewayClient("https://gw.example.org", SECRET, transport=offline))
    assert down.database_status() == {"reachable": False, "via": "gateway"}
    not_json = GatewayClient("https://gw.example.org", SECRET, transport=lambda u, h, t: (200, b"<html>"))
    with pytest.raises(DatabaseUnavailable, match="JSON"):
        not_json.get("/v1/status")


def test_client_sends_access_token_and_requires_https():
    seen = {}

    def capture(url, headers, timeout):
        seen.update(url=url, headers=headers)
        return 200, b"{}"
    GatewayClient("https://gw.example.org/", SECRET, access_id="id.access", access_secret="cf-secret", transport=capture).get("/v1/status")
    assert seen["url"] == "https://gw.example.org/v1/status"
    assert seen["headers"]["CF-Access-Client-Id"] == "id.access" and seen["headers"]["CF-Access-Client-Secret"] == "cf-secret"
    assert SECRET not in json.dumps(seen["headers"])                 # the signing secret never travels
    for url in ("http://gw.example.org", "https://gw.example.org/v1", "https://user:pw@gw.example.org", "ftp://gw.example.org"):
        with pytest.raises(ValueError):
            GatewayClient(url, SECRET)


# ------------------------------------------------------------------ backend selection and the Vercel entrypoint


def test_gateway_backend_is_hosted_only(monkeypatch, tmp_path):
    from mospi.app import backends
    monkeypatch.setenv("MOSPI_AUDIT_BACKEND", "gateway")
    with pytest.raises(backends.BackendError):
        backends.build(tmp_path, tmp_path, hosted=False)
    monkeypatch.setenv("MOSPI_GATEWAY_URL", "https://gw.example.org")
    monkeypatch.setenv("MOSPI_GATEWAY_SECRET", SECRET)
    audit, operations = backends.build(tmp_path, tmp_path, hosted=True)
    assert isinstance(audit, GatewayAuditStore) and isinstance(operations, GatewayOperations) and not audit.writable


def _vercel(monkeypatch, demo: Path, **env):
    for name in ("MOSPI_USERS_JSON", "MOSPI_ALLOW_ANONYMOUS_DEMO", "MOSPI_GATEWAY_URL", "MOSPI_GATEWAY_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MOSPI_DATA_DIR", str(demo))
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    import mospi.app.vercel_app as module
    return importlib.reload(module)


def test_vercel_reads_review_history_through_the_gateway_and_degrades_when_it_is_down(tmp_path, monkeypatch, gateway):
    client, db = gateway
    demo = tmp_path / "demo"
    shutil.copytree(ROOT / "data" / "demo", demo)
    token = "supervisor-token-for-tests"
    users = json.dumps({"users": [{"name": "Sup", "role": "supervisor", "token_sha256": hashlib.sha256(token.encode()).hexdigest()}]})
    import mospi.gateway.client as client_module
    monkeypatch.setattr(client_module, "_urllib_transport", transport_for(client))
    module = _vercel(monkeypatch, demo, MOSPI_USERS_JSON=users, MOSPI_AUDIT_BACKEND="gateway", MOSPI_GATEWAY_URL="http://127.0.0.1:8787",
                     MOSPI_GATEWAY_SECRET=SECRET)
    hosted = TestClient(module.app)
    auth = {"Authorization": f"Bearer {token}"}
    operations = hosted.get("/api/operations", headers=auth).json()
    assert operations["available"] and operations["uploads"] is False and operations["database"]["via"] == "gateway"
    case_id = hosted.get("/api/cases", headers=auth).json()["rows"][0]["case_id"]
    assert hosted.get(f"/api/cases/{case_id}", headers=auth).json()["audit_history"] == []
    assert hosted.get("/api/audit/verify", headers=auth).json()["status"] == "INTACT"
    assert hosted.post("/api/datasets", json={"contract": "2024_first"}, headers=auth).status_code == 403
    assert hosted.get("/healthz").json()["audit_store"] == "read-only"

    db.down = True                                                   # the laptop's database stops: hosted keeps serving bundled data
    hosted = TestClient(_vercel(monkeypatch, demo, MOSPI_USERS_JSON=users, MOSPI_AUDIT_BACKEND="gateway",
                                MOSPI_GATEWAY_URL="http://127.0.0.1:8787", MOSPI_GATEWAY_SECRET=SECRET).app)
    assert hosted.get("/api/operations", headers=auth).status_code == 503
    assert hosted.get("/api/cases", headers=auth).status_code == 503          # review status unknown: say so, never guess
    assert hosted.get("/healthz").json()["audit_store"] == "read-only"
    assert hosted.get("/").status_code == 200

    # Misconfigured (no secret): the entrypoint logs it and serves bundled history only, never crashes.
    broken = TestClient(_vercel(monkeypatch, demo, MOSPI_USERS_JSON=users, MOSPI_AUDIT_BACKEND="gateway", MOSPI_GATEWAY_URL="https://gw.example.org").app)
    assert broken.get("/api/operations", headers=auth).json()["available"] is False


# ------------------------------------------------------------------ temporary Cloudflare Quick Tunnel (no Access layer)

QUICK = "https://random-words-here.trycloudflare.com"


def test_quick_tunnel_needs_explicit_opt_in_and_never_receives_the_access_token():
    from mospi.gateway.client import is_quick_tunnel
    assert is_quick_tunnel(QUICK) and is_quick_tunnel("https://TryCloudflare.com/") and not is_quick_tunnel("https://gw.example.org")
    assert not is_quick_tunnel("https://trycloudflare.com.evil.example") and not is_quick_tunnel("https://evil-trycloudflare.com")
    with pytest.raises(ValueError, match="Quick Tunnel"):
        GatewayClient(QUICK, SECRET)
    seen = {}

    def capture(url, headers, timeout):
        seen.update(url=url, headers=headers)
        return 200, b'{"role": "mospi_reader", "ssl": true}'
    client = GatewayClient(QUICK, SECRET, access_id="id.access", access_secret="cf-secret", transport=capture, allow_quick_tunnel=True)
    assert GatewayOperations(client).database_status()["tunnel"] == "quick (temporary)"
    assert seen["url"] == QUICK + "/v1/status"
    assert "CF-Access-Client-Id" not in seen["headers"] and "CF-Access-Client-Secret" not in seen["headers"]
    assert "x-mospi-signature" in seen["headers"] and SECRET not in json.dumps(seen["headers"])
    # A named hostname is unchanged: no marker, and the token is still sent.
    named = GatewayClient("https://gw.example.org", SECRET, access_id="id.access", access_secret="cf-secret", transport=capture)
    assert "tunnel" not in GatewayOperations(named).database_status() and seen["headers"]["CF-Access-Client-Id"] == "id.access"


def test_quick_tunnel_backend_selection_follows_the_environment(monkeypatch, tmp_path):
    from mospi.app import backends
    monkeypatch.setenv("MOSPI_AUDIT_BACKEND", "gateway")
    monkeypatch.setenv("MOSPI_GATEWAY_URL", QUICK)
    monkeypatch.setenv("MOSPI_GATEWAY_SECRET", SECRET)
    monkeypatch.delenv("MOSPI_GATEWAY_ALLOW_QUICK_TUNNEL", raising=False)
    with pytest.raises(ValueError, match="Quick Tunnel"):
        backends.build(tmp_path, tmp_path, hosted=True)
    monkeypatch.setenv("MOSPI_GATEWAY_ALLOW_QUICK_TUNNEL", "yes")                  # only the exact value 1 counts
    with pytest.raises(ValueError, match="Quick Tunnel"):
        backends.build(tmp_path, tmp_path, hosted=True)
    monkeypatch.setenv("MOSPI_GATEWAY_ALLOW_QUICK_TUNNEL", "1")
    audit, operations = backends.build(tmp_path, tmp_path, hosted=True)
    assert audit.client.quick_tunnel and not audit.writable


def test_quick_tunnel_probe_expects_the_gateway_to_refuse_and_reports_the_missing_access_layer(monkeypatch):
    """`python -m mospi.gateway check` against a Quick Tunnel: the signature is the only credential, so unsigned requests must be 401."""
    import mospi.gateway.__main__ as cli
    import mospi.gateway.client as client_module
    host = "random-words-here.trycloudflare.com"
    db = FakeDb()
    app = TestClient(create_gateway(FakeAudit(db), FakeOperations(db), secrets_=[SECRET], loopback_only=False, allowed_hosts={host}), base_url=QUICK)
    monkeypatch.setattr(client_module, "_urllib_transport", lambda url, headers, timeout: (lambda r: (r.status_code, r.content))(app.get(url.replace(QUICK, ""), headers=headers)))
    monkeypatch.setattr(cli, "_urllib_transport_post", lambda url, headers: (app.post(url.replace(QUICK, ""), headers=headers).status_code, b""))
    monkeypatch.setenv("MOSPI_GATEWAY_SECRET", SECRET)
    monkeypatch.setenv("MOSPI_CF_ACCESS_CLIENT_ID", "id.access")
    monkeypatch.setenv("MOSPI_CF_ACCESS_CLIENT_SECRET", "cf-secret")
    result = cli._probe(QUICK)
    assert result["verdict"].startswith("PASSED") and "Quick Tunnel" in result["verdict"], result
    assert result["cloudflare_access_token_configured"] is False and "no Cloudflare Access" in result["tunnel"]
    assert result["no_credentials_refused"].startswith("ok (HTTP 401") and result["unsigned_root_path_refused"].startswith("ok (HTTP 401")
    assert result["replayed_request_refused"].startswith("ok") and result["write_method_refused"].startswith("ok")
    assert result["database_role"] == "mospi_reader" and result["only_cleared_data_classes"] is True
    # A gateway that answers unsigned requests would be reported as a failure, never passed.
    monkeypatch.setattr(client_module, "_urllib_transport", lambda url, headers, timeout: (200, b"{}"))
    assert cli._probe(QUICK)["verdict"].startswith("FAILED")
    # The Host check: a request whose Host header is not the tunnel hostname is refused before authentication.
    other = TestClient(create_gateway(FakeAudit(db), FakeOperations(db), secrets_=[SECRET], loopback_only=False, allowed_hosts={host}), base_url="https://other.trycloudflare.com")
    assert other.get("/v1/status", headers=signed("/v1/status")).status_code == 421
