"""What the operator allows each account: the AI, on for everybody from the start. The routes that use it are tested where
they live (``test_ai``); here the switch itself."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import OPERATOR, SIGN_IN_OIDC, Account
from app.security import SESSION_COOKIE, start_session

from .conftest import make_account, new_client, person


def listed(client: TestClient) -> dict[str, dict[str, Any]]:
    return {row["name"]: row for row in client.get("/api/v1/accounts").json()}


def test_every_account_is_allowed_the_ai_from_the_start(client: TestClient, operator: Account) -> None:
    with person("ben"):
        rows = listed(client)
    assert all(row["ai_allowed"] is True for row in rows.values())
    assert client.get("/api/v1/auth/me").json()["ai_allowed"] is True


def test_the_operator_takes_it_away_and_gives_it_back_and_only_the_fields_sent_change(client: TestClient,
                                                                                      operator: Account) -> None:
    with person("ben") as ben:
        ben_id = listed(client)["ben"]["id"]
        answered = client.put(f"/api/v1/accounts/{ben_id}/permissions", json={"ai_allowed": False})
        assert answered.status_code == 200 and answered.json() == {"ai_allowed": False}
        assert client.put(f"/api/v1/accounts/{ben_id}/permissions", json={}).json() == {"ai_allowed": False}
        assert ben.get("/api/v1/auth/me").json()["ai_allowed"] is False
        assert listed(client)["tester"]["ai_allowed"] is True
        assert client.put(f"/api/v1/accounts/{ben_id}/permissions", json={"ai_allowed": True}
                          ).json() == {"ai_allowed": True}


@pytest.mark.parametrize("body", [{"ai_allowed": "no"}, {"ai_allowed": 2}, {"admin": True}, {"ai_allowed": [True]},
                                  {"push_allowed": False}])
def test_nothing_but_the_one_switch_is_taken(client: TestClient, operator: Account, body: dict[str, Any]) -> None:
    with person("ben"):
        ben_id = listed(client)["ben"]["id"]
        assert client.put(f"/api/v1/accounts/{ben_id}/permissions", json=body).status_code == 422
        assert listed(client)["ben"]["ai_allowed"] is True


def test_a_member_cannot_change_it_not_even_for_themselves(client: TestClient, operator: Account) -> None:
    with person("ben") as ben:
        ben_id = listed(client)["ben"]["id"]
        for target in (ben_id, operator.id):
            denied = ben.put(f"/api/v1/accounts/{target}/permissions", json={"ai_allowed": False})
            assert (denied.status_code, denied.json()["detail"]["code"]) == (403, "operator_only")
        assert new_client().put(f"/api/v1/accounts/{ben_id}/permissions", json={}).status_code == 401
    assert listed(client)["tester"]["ai_allowed"] is True


def test_a_missing_account_is_not_found(client: TestClient, operator: Account) -> None:
    assert client.put("/api/v1/accounts/9999/permissions", json={"ai_allowed": False}).status_code == 404


def test_the_change_is_said_in_the_log_without_anything_else(client: TestClient, operator: Account,
                                                            caplog: pytest.LogCaptureFixture) -> None:
    with person("ben"):
        ben_id = listed(client)["ben"]["id"]
        with caplog.at_level("WARNING", logger="nexpaper.auth"):
            client.put(f"/api/v1/accounts/{ben_id}/permissions", json={"ai_allowed": False})
    assert any("Permissions changed name=ben ai_allowed=no" in record.getMessage() for record in caplog.records)


def provider_operator() -> TestClient:
    """A second operator who signs in through a provider (no password), in a browser with a fresh sign-in."""
    with SessionLocal() as db:
        row = Account(name="olga", role=OPERATOR, sign_in=SIGN_IN_OIDC, oidc_subject="sub-9", email="olga@example.com")
        db.add(row)
        db.commit()
        token = start_session(db, row, "127.0.0.1", "tests")
    browser = TestClient(app, base_url="http://testserver", headers={"X-Nexpaper-Client": "tab-provider0"})
    browser.cookies.set(SESSION_COOKIE, token)
    return browser


def test_an_operator_from_a_provider_confirms_an_act_with_a_fresh_sign_in(client: TestClient, operator: Account) -> None:
    """No password to ask for, so the sign-in must be recent; the act that a stolen session must not be enough for
    (a link to set a new password, a backup, deleting an account) is then as guarded as with a password."""
    anna = make_account("anna")
    olga = provider_operator()
    fresh = olga.post(f"/api/v1/accounts/{anna.id}/reset-link", json={"current_password": ""})
    assert fresh.status_code == 200, fresh.text


def test_an_operator_from_a_provider_with_an_old_sign_in_is_asked_to_sign_in_again(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import timedelta

    from app import clock

    anna = make_account("anna")
    olga = provider_operator()
    later = clock.now() + timedelta(minutes=11)
    monkeypatch.setattr(clock, "now", lambda: later)
    for method, path, body in (
        ("post", f"/api/v1/accounts/{anna.id}/reset-link", {"current_password": ""}),
        ("delete", f"/api/v1/accounts/{anna.id}", {"current_password": ""}),
    ):
        stale = olga.request(method.upper(), path, json=body)
        assert (stale.status_code, stale.json()["detail"]["code"]) == (403, "sign_in_again"), path
