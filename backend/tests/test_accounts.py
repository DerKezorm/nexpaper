"""Accounts: the first one, signing in, the brake and the lock, the own password and language, the operator's list."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import OPERATOR, Account, AuthSession, utcnow
from app.security import MAX_FAILURES, SESSION_COOKIE, decrypt_secret, encrypt_secret, hash_token
from app.services import settings_service

from .conftest import PASSWORD, SETUP_CODE, TAB, make_account, sign_in

GOOD = "a long enough password"


def test_the_first_account_is_the_operator_and_only_the_first(client: TestClient) -> None:
    assert client.get("/api/v1/setup").json()["needs_setup"] is True
    short = client.post("/api/v1/setup", json={"code": SETUP_CODE, "name": "boss", "password": "short"})
    assert short.status_code == 422 and short.json()["detail"]["code"] == "password_too_short"
    made = client.post("/api/v1/setup", json={"code": SETUP_CODE, "name": "Boss", "password": GOOD, "language": "de"})
    assert made.status_code == 200
    assert made.json()["name"] == "boss" and made.json()["role"] == OPERATOR and made.json()["language"] == "de"
    # Signed in right away.
    assert client.get("/api/v1/auth/me").json()["name"] == "boss"
    assert client.get("/api/v1/setup").json()["needs_setup"] is False
    again = client.post("/api/v1/setup", json={"code": SETUP_CODE, "name": "other", "password": GOOD})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_set_up"


def kinds_of(client: TestClient) -> list[str]:
    return [kind["name"] for kind in client.get("/api/v1/kinds").json()]


def test_a_server_set_up_in_english_has_its_kinds_in_english(client: TestClient) -> None:
    made = client.post("/api/v1/setup", json={"code": SETUP_CODE, "name": "boss", "password": GOOD, "language": "en"})
    assert made.status_code == 200
    names = kinds_of(client)
    assert "Invoice" in names and "Contract" in names and "Rechnung" not in names


def test_a_server_set_up_in_german_keeps_the_german_kinds(client: TestClient) -> None:
    client.post("/api/v1/setup", json={"code": SETUP_CODE, "name": "boss", "password": GOOD, "language": "de"})
    names = kinds_of(client)
    assert "Rechnung" in names and "Invoice" not in names


def test_setup_refuses_a_language_nexpaper_does_not_have(client: TestClient) -> None:
    refused = client.post("/api/v1/setup", json={"code": SETUP_CODE, "name": "boss", "password": GOOD, "language": "xx"})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "unknown_language"


def test_sign_in_and_out(client: TestClient) -> None:
    make_account("anna")
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/setup").json()["signed_in"] is False
    wrong = client.post("/api/v1/auth/login", json={"name": "anna", "password": "wrong password here"})
    unknown = client.post("/api/v1/auth/login", json={"name": "nobody", "password": "wrong password here"})
    # The same answer for a wrong password and an unknown name.
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]
    signed = client.post("/api/v1/auth/login", json={"name": "ANNA ", "password": PASSWORD})
    assert signed.status_code == 200 and signed.json()["name"] == "anna"
    cookie = signed.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Secure" not in cookie
    token = client.cookies.get(SESSION_COOKIE)
    with SessionLocal() as db:
        # The database knows the hash only.
        assert db.scalar(select(AuthSession).where(AuthSession.token_hash == token)) is None
        assert db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token))) is not None
    assert client.get("/api/v1/auth/me").json()["name"] == "anna"
    assert client.get("/api/v1/setup").json()["signed_in"] is True
    assert client.post("/api/v1/auth/logout").status_code == 204
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_the_cookie_is_secure_behind_https(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    make_account("anna")
    monkeypatch.setattr(get_settings(), "trusted_proxies", "10.0.0.2")
    with TestClient(app, base_url="http://testserver", headers=TAB, client=("10.0.0.2", 50000)) as proxied:
        signed = proxied.post(
            "/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}, headers={"X-Forwarded-Proto": "https"}
        )
    assert "Secure" in signed.headers["set-cookie"]


def test_an_expired_session_is_gone(client: TestClient) -> None:
    anna = make_account("anna")
    sign_in(client, anna)
    with SessionLocal() as db:
        for row in db.scalars(select(AuthSession)):
            row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401
    with SessionLocal() as db:
        assert db.scalar(select(AuthSession)) is None


def test_the_brake_holds_a_guesser_back(client: TestClient) -> None:
    make_account("anna")
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"name": "anna", "password": "wrong password"}).status_code == 401
    held = client.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD})
    # Even the right password waits: otherwise the brake would tell when a guess was right.
    assert held.status_code == 429 and int(held.headers["Retry-After"]) > 0


def test_the_account_locks_after_ten_failures_from_anywhere(client: TestClient) -> None:
    from app.security import brake

    make_account("anna")
    for number in range(MAX_FAILURES):
        # Every guess from another address: the brake per sender does not help, the lock per account does.
        brake.forget()
        response = client.post(
            "/api/v1/auth/login", json={"name": "anna", "password": "wrong password"},
            headers={"X-Forwarded-For": f"10.0.0.{number}"},
        )
        assert response.status_code == 401
    brake.forget()
    # Locked, and saying so no more than a wrong password does (review before 1.0.0): the name stays unconfirmed.
    locked = client.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD})
    assert locked.status_code == 401 and locked.json()["detail"]["code"] == "wrong_credentials"
    with SessionLocal() as db:
        row = db.scalar(select(Account).where(Account.name == "anna"))
        assert row is not None
        row.locked_until = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 200


def test_forwarded_for_counts_only_from_a_trusted_proxy(client: TestClient, monkeypatch) -> None:
    from app.config import get_settings
    from app.deps import client_ip

    class Fake:
        def __init__(self, peer: str, forwarded: str) -> None:
            self.client = type("C", (), {"host": peer})()
            self.headers = {"x-forwarded-for": forwarded}

    assert client_ip(Fake("10.1.1.1", "1.2.3.4")) == "10.1.1.1"  # type: ignore[arg-type]
    monkeypatch.setattr(get_settings(), "trusted_proxies", "10.1.1.0/24")
    # The rightmost hop that is not a proxy: whatever the sender wrote left of it does not count.
    assert client_ip(Fake("10.1.1.1", "6.6.6.6, 1.2.3.4")) == "1.2.3.4"  # type: ignore[arg-type]
    assert client_ip(Fake("10.1.1.1", "1.2.3.4, 10.1.1.2")) == "1.2.3.4"  # type: ignore[arg-type]
    assert client_ip(Fake("9.9.9.9", "1.2.3.4")) == "9.9.9.9"  # type: ignore[arg-type]


def test_password_sign_in_off_keeps_the_operator_in(client: TestClient) -> None:
    make_account("anna")
    make_account("boss", OPERATOR)
    with SessionLocal() as db:
        settings_service.save(db, {"password_login": False})
    refused = client.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "password_login_off"
    assert client.post("/api/v1/auth/login", json={"name": "boss", "password": PASSWORD}).status_code == 200
    # No passkeys offered: no public address is set, and the test server is not called "localhost".
    assert client.get("/api/v1/auth/methods").json() == {"password": False, "providers": [], "passkeys": False, "forgot": False,
                                                       "session_days": 30}


def test_changing_the_password_ends_the_other_sessions(client: TestClient) -> None:
    anna = make_account("anna")
    other = TestClient(client.app, headers={"X-Nexpaper-Client": "tab-other0000"})
    sign_in(other, anna)
    sign_in(client, anna)
    wrong = client.put("/api/v1/auth/password", json={"current": "not the password", "new": GOOD})
    assert wrong.status_code == 401
    too_short = client.put("/api/v1/auth/password", json={"current": PASSWORD, "new": "short"})
    assert too_short.status_code == 422
    assert client.put("/api/v1/auth/password", json={"current": PASSWORD, "new": GOOD}).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 200
    assert other.get("/api/v1/auth/me").status_code == 401
    client.cookies.clear()
    assert client.post("/api/v1/auth/login", json={"name": "anna", "password": GOOD}).status_code == 200


def test_a_wrong_current_password_counts_like_a_wrong_sign_in(client: TestClient) -> None:
    anna = make_account("anna")
    sign_in(client, anna)
    for _ in range(5):
        client.put("/api/v1/auth/password", json={"current": "guess guess guess", "new": GOOD})
    held = client.put("/api/v1/auth/password", json={"current": PASSWORD, "new": GOOD})
    assert held.status_code == 429


def test_the_own_language(client: TestClient) -> None:
    sign_in(client, make_account("anna"))
    assert client.put("/api/v1/me/language", json={"language": "de"}).json()["language"] == "de"
    assert client.get("/api/v1/auth/me").json()["language"] == "de"
    assert client.put("/api/v1/me/language", json={"language": "xx"}).status_code == 422
    assert client.put("/api/v1/me/language", json={"language": ""}).json()["language"] == ""


def test_the_operator_manages_accounts(client: TestClient, operator: Account) -> None:
    anna = make_account("anna")
    listed = client.get("/api/v1/accounts").json()
    assert [row["name"] for row in listed] == ["tester", "anna"]
    assert "password_hash" not in listed[0]
    assert client.put(f"/api/v1/accounts/{operator.id}/role", json={"role": "member", "current_password": PASSWORD}).status_code == 409
    assert client.request("DELETE", f"/api/v1/accounts/{operator.id}", json={"current_password": PASSWORD}).status_code == 409
    anna_client = TestClient(client.app, headers={"X-Nexpaper-Client": "tab-anna00000"})
    sign_in(anna_client, anna)
    assert anna_client.get("/api/v1/accounts").status_code == 403
    # The operator cannot set a password for anybody (a link is sent instead: ``test_password_links.py``).
    assert client.put(f"/api/v1/accounts/{anna.id}/password", json={"password": GOOD, "current_password": PASSWORD}).status_code in (404, 405)
    assert anna_client.get("/api/v1/auth/me").status_code == 200
    assert client.post(f"/api/v1/accounts/{anna.id}/sign-out").status_code == 204
    assert anna_client.get("/api/v1/auth/me").status_code == 401
    assert client.put(f"/api/v1/accounts/{anna.id}/role", json={"role": "operator", "current_password": PASSWORD}).json()["role"] == OPERATOR
    assert client.request("DELETE", f"/api/v1/accounts/{anna.id}", json={"confirm_name": "anna", "current_password": PASSWORD}).status_code == 204
    assert [row["name"] for row in client.get("/api/v1/accounts").json()] == ["tester"]


def test_changes_without_the_tab_header_are_refused_even_with_a_session(client: TestClient) -> None:
    anna = make_account("anna")
    bare = TestClient(client.app)
    sign_in(bare, anna)
    # A form from another site carries the cookie but cannot add a header.
    refused = bare.put("/api/v1/me/language", json={"language": "de"})
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "client_required"


def test_server_secrets_are_encrypted_and_bound_to_the_key(monkeypatch) -> None:
    from app.config import get_settings

    sealed = encrypt_secret("smtp password")
    assert "smtp password" not in sealed and decrypt_secret(sealed) == "smtp password"
    monkeypatch.setattr(get_settings(), "secret_key", "another key entirely")
    assert decrypt_secret(sealed) == ""


def test_a_name_is_taken_once_whatever_its_case(client: TestClient, operator: Account) -> None:
    link = client.post("/api/v1/invites", json={}).json()["link"]
    token = link.rsplit("/", 1)[1]
    stranger = TestClient(client.app, headers={"X-Nexpaper-Client": "tab-stranger0"})
    taken = stranger.post(f"/api/v1/invite/{token}", json={"name": "Tester", "password": GOOD})
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "name_taken"
    bad = stranger.post(f"/api/v1/invite/{token}", json={"name": "a b", "password": GOOD})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_account_name"
    # The invitation is still there after both refusals.
    assert stranger.post(f"/api/v1/invite/{token}", json={"name": "dora", "password": GOOD}).status_code == 200
