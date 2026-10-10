"""API keys and the routes for programs: a key reads as its account, never more, and only what its scope says."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account, ApiKey, utcnow
from app.services import apikeys

from .conftest import make_account, new_client, sign_in


@pytest.fixture(autouse=True)
def fresh_brake() -> Iterator[None]:
    apikeys.forget()
    yield
    apikeys.forget()


def switch_on(client: TestClient) -> None:
    assert client.put("/api/v1/settings", json={"api_keys_allowed": True}).status_code == 200


def make_key(client: TestClient, **body: object) -> str:
    answer = client.post("/api/v1/api-keys", json={"name": "nexdeck", **body})
    assert answer.status_code == 201, answer.text
    return str(answer.json()["secret"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_closed_until_the_operator_opens_it_and_never_for_a_web_page(client: TestClient, operator: Account) -> None:
    assert client.post("/api/v1/api-keys", json={"name": "x"}).json()["detail"]["code"] == "api_off"
    switch_on(client)
    token = make_key(client)
    assert token.startswith("npk_")
    assert client.get("/api/v1/me", headers=bearer(token)).json()["name"] == "tester"
    assert client.get("/api/v1/me", headers={**bearer(token), "Origin": "https://example.com"}).status_code == 403
    assert client.put("/api/v1/settings", json={"api_keys_allowed": False}).status_code == 200
    assert client.get("/api/v1/me", headers=bearer(token)).json()["detail"]["code"] == "api_off"


def test_a_session_is_no_key_and_a_key_makes_no_keys(client: TestClient, operator: Account) -> None:
    switch_on(client)
    token = make_key(client)
    # The browser's session counts for nothing on the routes for keys.
    assert client.get("/api/v1/me").status_code == 401
    with TestClient(client.app, base_url="http://testserver", headers={"X-Nexpaper-Client": "program-tab"}) as bare:
        # Not a device token either: a key is refused by the account routes, it makes no keys and pairs no device.
        assert bare.get("/api/v1/api-keys", headers=bearer(token)).status_code == 403
        assert bare.post("/api/v1/api-keys", headers=bearer(token), json={"name": "more"}).status_code == 403
        assert bare.post("/api/v1/devices", headers=bearer(token), json={"name": "more"}).status_code == 403


def test_keys_only_read(client: TestClient, operator: Account) -> None:
    switch_on(client)
    assert client.post("/api/v1/api-keys", json={"name": "n8n", "scope": "write"}).status_code == 422
    assert client.get("/api/v1/me", headers=bearer(make_key(client))).json()["scope"] == "read"


def test_a_key_speaks_for_its_own_account_only(client: TestClient, operator: Account) -> None:
    switch_on(client)
    rita = make_account("rita")
    with new_client(rita) as own:
        token = make_key(own)
        assert own.get("/api/v1/me", headers=bearer(token)).json()["name"] == "rita"
        listed = own.get("/api/v1/api-keys").json()["keys"]
        assert [item["name"] for item in listed] == ["nexdeck"]
    # The operator sees that rita has a key, never its secret, and cannot delete it as its own.
    every = client.get("/api/v1/admin/api-keys").json()
    assert [(item["account"], item["prefix"]) for item in every] == [("rita", token[:8])]
    assert all(token not in str(item) for item in every)
    assert client.delete(f"/api/v1/api-keys/{every[0]['id']}").status_code == 404
    assert client.get("/api/v1/api-keys").json()["keys"] == []


def test_run_out_blocked_or_deleted_keys_answer_like_none(client: TestClient, operator: Account) -> None:
    switch_on(client)
    late = make_key(client, days=30)
    blocked = make_key(client)
    gone = make_key(client)
    with SessionLocal() as db:
        row = db.query(ApiKey).filter(ApiKey.token_hash == apikeys.digest(late)).one()
        row.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    ids = {item["prefix"]: item["id"] for item in client.get("/api/v1/api-keys").json()["keys"]}
    assert client.post(f"/api/v1/admin/api-keys/{ids[blocked[:8]]}/block").status_code == 200
    assert client.delete(f"/api/v1/api-keys/{ids[gone[:8]]}").status_code == 204
    for token in (late, blocked, gone, "npk_" + "x" * 43, "not-a-token"):
        assert client.get("/api/v1/me", headers=bearer(token)).json()["detail"]["code"] == "key_invalid"
    assert client.post("/api/v1/api-keys", json={"name": "x", "days": 7}).status_code == 422


def test_a_key_slows_down_at_its_rate(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    switch_on(client)
    token = make_key(client)
    monkeypatch.setattr(apikeys, "PER_MINUTE", 2)
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 200
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 200
    slow = client.get("/api/v1/me", headers=bearer(token))
    assert slow.status_code == 429 and slow.headers["retry-after"] == "60"


def test_a_blocked_account_reads_nothing_with_its_key(client: TestClient, operator: Account) -> None:
    switch_on(client)
    anna = make_account("anna")
    with new_client() as browser:
        sign_in(browser, anna)
        token = make_key(browser)
    with new_client() as program:
        assert program.get("/api/v1/me", headers=bearer(token)).status_code == 200
        with SessionLocal() as db:
            db.get(Account, anna.id).blocked_at = utcnow()  # type: ignore[union-attr]
            db.commit()
        assert program.get("/api/v1/me", headers=bearer(token)).status_code == 401


def test_wrong_keys_count_against_the_sender_like_wrong_passwords(client: TestClient, operator: Account) -> None:
    """Guessing keys is guessing passwords: five wrong ones and the sender rests, even with a right key after."""
    switch_on(client)
    token = make_key(client)
    with new_client() as program:
        for _ in range(5):
            assert program.get("/api/v1/me", headers=bearer("npk_" + "y" * 43)).status_code == 401
        rest = program.get("/api/v1/me", headers=bearer(token))
        assert rest.status_code == 429
        assert int(rest.headers["retry-after"]) > 0
