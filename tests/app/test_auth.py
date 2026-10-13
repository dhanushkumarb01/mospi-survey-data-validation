"""Accounts, sign-in and the three roles (mospi/auth, mospi/app/auth_api.py), on synthetic data and in-memory accounts only."""
from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from mospi.app.api import create_app
from mospi.auth import AccountError, SqliteUserStore, can
from mospi.auth.__main__ import main as cli
from mospi.auth.passwords import hash_password, password_problem, temporary_password, verify_password
from mospi.auth.sessions import COOKIE, SessionSigner
from tests.auth_support import PASSWORD, SIGNER, auth, user_store

H = {"X-MoSPI-Request": "1"}
DECISION = {"event_type": "DECISION_MADE", "decision": "VALID_BUT_UNUSUAL", "reason_code": "GENUINE_HIGH_OR_LOW_VALUE", "verification_source": "PHONE_CALL"}


@pytest.fixture()
def root(tmp_path):
    run = tmp_path / "fusion" / "runs" / "2024_first_visit_synthetic"
    run.mkdir(parents=True)
    rows = [{"case_id": f"case_{i}", "source_observation_id": f"Q1|1|07|01|F{i}|1|1|01|person=1", "release": "2024", "observation_type": "first_visit",
             "state": "07", "sector": "1", "stratum": "01", "fsu": f"F{i}", "priority_score": 1.0 - i / 10, "priority_band": "CHECK_NOW",
             "tier": "A", "lanes": "VALUE", "lane": "VALUE", "queue_position": i + 1, "case_level": "PERSON", "household_key": f"h{i}"} for i in range(2)]
    pd.DataFrame(rows).to_parquet(run / "fused_cases.parquet", index=False)
    (run / "run_metadata.json").write_text(json.dumps({"run_id": "synthetic", "release": "2024", "observation": "first_visit",
                                                       "fusion_version": "iospi-fusion-v2.1-lanes", "source_runs": {}}), encoding="utf-8")
    (run / "fusion_report.json").write_text(json.dumps({"records_processed": 2, "priority_rows": 2}), encoding="utf-8")
    return tmp_path


def _client(root, store=None, **options) -> tuple[TestClient, SqliteUserStore]:
    store = store or user_store()
    return TestClient(create_app(root / "fusion" / "runs", project_root=root, batch_datasets={}, users=store, session_signer=SIGNER, **options)), store


def _login(client, username, password=PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password}, headers=H)


# ------------------------------------------------------------------ building blocks


def test_passwords_are_salted_scrypt_hashes_and_the_rules_are_plain():
    first, second = hash_password("a long passphrase"), hash_password("a long passphrase")
    assert first != second and first.startswith("scrypt$") and "passphrase" not in first
    assert verify_password("a long passphrase", first) and not verify_password("a long passphrasE", first)
    assert not verify_password("anything", "plain-text") and not verify_password("anything", "scrypt$99$8$1$x$y")
    assert password_problem("short") and password_problem("aaaaaaaaaaaaaaaa")
    assert password_problem("r.sharma-2026-pass", username="r.sharma") and password_problem("Priya is my name ok", display_name="Priya Rao")
    assert password_problem("three quiet river stones") is None
    temporary = temporary_password()
    assert len(temporary) == 19 and password_problem(temporary) is None and not set("0O1lI") & set(temporary)


def test_session_cookies_are_signed_expire_and_never_carry_the_role():
    signer = SessionSigner("x" * 40, lifetime=60)
    token = signer.issue(7, 3, now=1000)
    assert signer.read(token, now=1001) == (7, 3) and signer.read(token, now=1061) is None
    assert token.count(".") == 3 and "admin" not in token
    user_id, version, expires, signature = token.split(".")
    assert signer.read(f"{user_id}.4.{expires}.{signature}", now=1001) is None               # a changed version breaks the signature
    assert SessionSigner("y" * 40).read(token, now=1001) is None                              # another secret
    with pytest.raises(ValueError):
        SessionSigner("too short")


def test_roles_have_the_agreed_capabilities():
    admin, supervisor, analyst = ({"role": r} for r in ("admin", "supervisor", "analyst"))
    assert all(can(admin, c) for c in ("view", "decide", "export", "operations", "run", "manage_users"))
    assert can(supervisor, "decide") and can(supervisor, "export") and not can(supervisor, "operations") and not can(supervisor, "manage_users")
    assert can(analyst, "operations") and not can(analyst, "decide") and not can(analyst, "export") and not can(analyst, "run")
    assert not can(None, "view") and not can({"role": "technical"}, "view")                   # the old role name means nothing now


def test_the_store_never_creates_or_changes_an_administrator_without_the_server_flag():
    store = user_store()
    with pytest.raises(AccountError, match="only on the server"):
        store.create(username="boss", display_name="Boss", role="admin", password_hash=hash_password("x"), created_by="Test admin")
    with pytest.raises(AccountError):
        store.update(1, actor="Test admin", active=False)                                       # account 1 is the administrator
    with pytest.raises(AccountError):
        store.reset_password(1, hash_password("x"), actor="Test admin")
    with pytest.raises(AccountError, match="supervisor or an analyst"):
        store.update(2, actor="Test admin", role="admin")
    with pytest.raises(AccountError, match="already taken"):
        store.create(username="Supervisor", display_name="Again", role="supervisor", password_hash=hash_password("x"), created_by="t")
    with pytest.raises(AccountError, match="username"):
        store.create(username="a b", display_name="Space", role="analyst", password_hash=hash_password("x"), created_by="t")


# ------------------------------------------------------------------ sign-in


def test_sign_in_sets_an_http_only_cookie_and_the_session_names_the_person(root):
    client, _ = _client(root)
    response = _login(client, "  Supervisor ")                                                  # usernames are trimmed and case-insensitive
    assert response.status_code == 200 and response.json()["user"]["name"] == "Test supervisor"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=") and "HttpOnly" in cookie and "samesite=strict" in cookie.lower() and "Secure" not in cookie
    assert response.json()["capabilities"] == ["decide", "export", "view"]
    assert client.get("/api/overview").status_code == 200                                       # the cookie alone signs the browser in
    assert client.post("/api/auth/logout", headers=H).status_code == 200
    assert client.get("/api/overview").status_code == 401


def test_the_hosted_cookie_is_secure(root):
    client, _ = _client(root, hosted=True, review_only=True, audit_read_only=True, require_authentication=True)
    assert "Secure" in _login(client, "supervisor").headers["set-cookie"]


def test_a_wrong_password_and_an_unknown_name_get_the_same_answer_and_five_failures_lock(root):
    client, store = _client(root)
    unknown, wrong = _login(client, "nobody"), _login(client, "analyst", "not the password")
    assert unknown.status_code == wrong.status_code == 401 and unknown.json() == wrong.json()
    for _ in range(3):
        assert _login(client, "analyst", "still wrong").status_code == 401
    assert _login(client, "analyst", "fifth wrong").status_code == 401                         # the fifth failure locks the account
    locked = _login(client, "analyst")
    assert locked.status_code == 423 and "locked" in locked.json()["detail"]                    # even with the right password
    assert [e["event_type"] for e in store.events(3)] == ["ACCOUNT_LOCKED", "SIGN_IN_FAILED", "SIGN_IN_FAILED"]
    store.reset_password(3, hash_password(PASSWORD), actor="Test admin")                        # an administrator's reset unlocks it
    assert _login(client, "analyst").status_code == 200


def test_repeated_failures_from_one_place_are_throttled_in_memory(root):
    client, _ = _client(root)
    for k in range(30):
        _login(client, f"guess{k % 7}", "wrong")
    assert _login(client, "supervisor").status_code == 429


def test_state_changes_need_the_workspace_header(root):
    client, _ = _client(root)
    cookie = {"Cookie": auth("supervisor")["Cookie"]}
    assert client.post("/api/cases/case_0/events", json=DECISION, headers=cookie).status_code == 403   # a cross-site form cannot add the header
    assert client.post("/api/auth/login", json={"username": "supervisor", "password": PASSWORD}).status_code == 403
    assert client.post("/api/cases/case_0/events", json=DECISION, headers=auth("supervisor")).status_code == 200


def test_a_deactivated_account_or_a_changed_session_version_ends_the_session(root):
    client, store = _client(root)
    assert client.get("/api/overview", headers=auth("analyst")).status_code == 200
    store.update(3, actor="Test admin", active=False)
    fresh, _ = _client(root, store)                                                             # a new instance: no cached session
    assert fresh.get("/api/overview", headers=auth("analyst")).status_code == 401
    assert _login(fresh, "analyst").status_code == 401
    store.update(3, actor="Test admin", active=True)
    assert fresh.get("/api/overview", headers=auth("analyst")).status_code == 401              # reactivation does not revive old sessions
    assert _login(fresh, "analyst").status_code == 200


# ------------------------------------------------------------------ passwords chosen by their holder


def test_a_new_account_must_choose_its_own_password_before_anything_else(root):
    admin, store = _client(root)
    created = admin.post("/api/users", json={"username": "r.sharma", "display_name": "R. Sharma", "role": "supervisor"}, headers=auth("admin"))
    assert created.status_code == 200
    temporary = created.json()["temporary_password"]
    assert created.json()["user"]["must_change_password"] is True and "password_hash" not in created.text
    person = TestClient(admin.app)
    signed = _login(person, "r.sharma", temporary)
    assert signed.status_code == 200 and signed.json()["user"]["must_change_password"] is True
    blocked = person.get("/api/overview")
    assert blocked.status_code == 403 and blocked.json()["password_change_required"] is True
    assert person.get("/api/session").status_code == 200                                       # the workspace can still ask who is signed in
    weak = person.post("/api/auth/password", json={"current_password": temporary, "new_password": "short"}, headers=H)
    assert weak.status_code == 400 and "12 characters" in weak.json()["detail"]
    wrong = person.post("/api/auth/password", json={"current_password": "not it", "new_password": "a calm blue harbour"}, headers=H)
    assert wrong.status_code == 400
    changed = person.post("/api/auth/password", json={"current_password": temporary, "new_password": "a calm blue harbour"}, headers=H)
    assert changed.status_code == 200 and changed.json()["user"]["must_change_password"] is False
    assert person.get("/api/overview").status_code == 200                                       # the response re-issued the cookie
    assert _login(TestClient(admin.app), "r.sharma", temporary).status_code == 401              # the temporary password no longer works
    assert "PASSWORD_CHANGED" in [e["event_type"] for e in store.events(3)]


# ------------------------------------------------------------------ the role matrix on the server


def test_each_role_can_do_exactly_its_part(root):
    client, _ = _client(root)
    assert client.post("/api/cases/case_0/events", json={**DECISION, "expected_last_decision_id": None}, headers=auth("supervisor")).status_code == 200
    assert client.post("/api/cases/case_1/events", json=DECISION, headers=auth("analyst")).status_code == 403
    assert client.post("/api/cases/case_1/events", json=DECISION, headers=auth("admin")).status_code == 200
    assert client.get("/api/export/queue", headers=auth("analyst")).status_code == 403
    assert client.get("/api/export/queue", headers=auth("supervisor")).status_code == 200
    for role in ("analyst", "supervisor", "admin"):
        assert client.get("/api/cases", headers=auth(role)).status_code == 200, role
    assert client.post("/api/batch", json={"release": "2024", "label": "x"}, headers=auth("analyst")).status_code == 403
    assert client.post("/api/batch", json={"release": "2024", "label": "x"}, headers=auth("supervisor")).status_code == 403
    for role in ("supervisor", "analyst"):
        assert client.get("/api/users", headers=auth(role)).status_code == 403, role
        assert client.post("/api/users", json={"username": "x.y", "display_name": "X", "role": "analyst"}, headers=auth(role)).status_code == 403, role
    session = client.get("/api/session", headers=auth("supervisor")).json()
    assert session["role_label"] == "Supervisor" and session["accounts_managed_here"] is True


def test_an_administrator_manages_supervisor_and_analyst_accounts_only(root):
    client, store = _client(root)
    admin = auth("admin")
    for role in ("admin", "technical", ""):
        refused = client.post("/api/users", json={"username": f"new.{role or 'none'}", "display_name": "New", "role": role}, headers=admin)
        assert refused.status_code == 400, role
    assert "only on the server" in client.post("/api/users", json={"username": "n.admin", "display_name": "N", "role": "admin"}, headers=admin).json()["detail"]
    analyst = client.post("/api/users", json={"username": "a.n", "display_name": "A. N.", "role": "analyst"}, headers=admin).json()["user"]
    assert client.post("/api/users", json={"username": "a.n", "display_name": "Twice", "role": "analyst"}, headers=admin).status_code == 409
    promoted = client.patch(f"/api/users/{analyst['user_id']}", json={"role": "supervisor"}, headers=admin)
    assert promoted.status_code == 200 and promoted.json()["user"]["role"] == "supervisor"
    assert client.patch(f"/api/users/{analyst['user_id']}", json={"role": "admin"}, headers=admin).status_code == 403
    assert client.patch("/api/users/1", json={"active": False}, headers=admin).status_code == 403          # their own account
    assert client.post("/api/users/1/password", headers=admin).status_code == 403
    reset = client.post(f"/api/users/{analyst['user_id']}/password", headers=admin)
    assert reset.status_code == 200 and len(reset.json()["temporary_password"]) == 19
    assert client.patch("/api/users/999", json={"active": False}, headers=admin).status_code == 404
    listing = client.get("/api/users", headers=admin).json()
    assert listing["roles"] == ["supervisor", "analyst"] and all("password_hash" not in u for u in listing["users"])
    assert {e["event_type"] for e in listing["activity"]} >= {"USER_CREATED", "USER_UPDATED", "PASSWORD_RESET"}
    assert listing["activity"][0]["actor"] == "Test admin"


def test_a_role_change_applies_to_an_open_session(root):
    client, store = _client(root)
    assert client.post("/api/cases/case_0/events", json=DECISION, headers=auth("analyst")).status_code == 403
    store.update(3, actor="Test admin", role="supervisor")
    fresh, _ = _client(root, store)
    assert fresh.get("/api/cases", headers=auth("analyst")).status_code == 401                 # the change ended the session ...
    assert _login(fresh, "analyst").json()["user"]["role"] == "supervisor"                     # ... and the next sign-in has the new role


def test_hosted_accounts_are_managed_on_the_processing_machine(root):
    from mospi.auth import HostedUserStore

    class Reader:
        def __init__(self, store): self.store = store
        def fetchone(self, sql, params):
            return self.store.login_record(params[0]) if "auth_login_record" in sql else self.store.session_record(params[0])

    hosted = HostedUserStore(Reader(user_store()))
    client = TestClient(create_app(root / "fusion" / "runs", project_root=root, users=hosted, session_signer=SIGNER, hosted=True, review_only=True,
                                   audit_read_only=True, require_authentication=True))
    assert client.get("/api/users", headers=auth("admin")).status_code == 403
    session = client.get("/api/session", headers=auth("supervisor")).json()
    assert session["accounts_managed_here"] is False and session["can_change_password"] is False    # no reviewer connection
    assert client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "a calm blue harbour"},
                       headers=auth("supervisor")).status_code == 403


def test_without_a_session_secret_a_hosted_instance_refuses_plainly(root, monkeypatch):
    monkeypatch.delenv("MOSPI_SESSION_SECRET", raising=False)
    client = TestClient(create_app(root / "fusion" / "runs", project_root=root, users=user_store(), hosted=True, review_only=True, audit_read_only=True,
                                   require_authentication=True))
    response = _login(client, "supervisor")
    assert response.status_code == 503 and "MOSPI_SESSION_SECRET" in response.json()["detail"]


# ------------------------------------------------------------------ the server command line


def test_the_command_line_creates_and_recovers_administrators(tmp_path, capsys):
    path = tmp_path / "users.sqlite"
    assert cli(["--sqlite", str(path), "create-admin", "--username", "chief", "--name", "Chief Admin"]) == 0
    printed = capsys.readouterr().out
    password = next(line.split(":", 1)[1].strip() for line in printed.splitlines() if "temporary password" in line)
    store = SqliteUserStore(path)
    account = store.login_record("chief")
    assert account["role"] == "admin" and account["must_change_password"] and verify_password(password, account["password_hash"])
    assert cli(["--sqlite", str(path), "create-admin", "--username", "chief", "--name", "Again"]) == 2       # no duplicate
    assert cli(["--sqlite", str(path), "reset-password", "--username", "chief"]) == 0
    assert not verify_password(password, SqliteUserStore(path).login_record("chief")["password_hash"])
    assert cli(["--sqlite", str(path), "deactivate", "--username", "chief"]) == 0
    assert SqliteUserStore(path).login_record("chief")["active"] is False
    assert cli(["--sqlite", str(path), "list"]) == 0 and "Administrator" in capsys.readouterr().out
    assert [e["origin"] for e in SqliteUserStore(path).events(5)] == ["cli"] * 3
