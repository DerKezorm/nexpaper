"""API keys on the shared key module: the old routes and the new ones see the same keys, every key made before keeps
working, the shortcut's card and nexpaper-ios keep their routes, and the operator unblocks a key."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account
from app.services import apikeys

from .conftest import make_account, new_client

NEW = "/api/v1/connections"


@pytest.fixture(autouse=True)
def fresh_brake() -> Iterator[None]:
    apikeys.forget()
    yield
    apikeys.forget()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def old_key(account: Account, name: str, scope: str, days: int | None) -> str:
    """Made as nexpaper made keys before the module (no switch asked)."""
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None
        return apikeys.make(db, row, name, scope, days)[1]


def test_keys_made_before_work_and_both_lists_show_them(client: TestClient, operator: Account) -> None:
    # Since mcp 1.1.0 the switch "MCP-Zugang" stands beside it, off in a new installation.
    assert client.put(f"{NEW}/interfaces", json={"api": True}).json() == {"api": True, "mcp": False}
    made = {
        "read": old_key(operator, "nexdeck", "read", 365),
        "upload": old_key(operator, "Scanner", "upload", None),
        "shortcut": old_key(operator, "iPhone-Kurzbefehl", "upload", None),
    }
    for token in made.values():
        apikeys.forget()
        assert client.get("/api/v1/me", headers=bearer(token)).status_code == 200
    old = client.get("/api/v1/api-keys").json()
    new = client.get(f"{NEW}/keys").json()
    assert old["allowed"] is True and new["api"] is True
    assert [row["id"] for row in old["keys"]] == sorted(row["id"] for row in new["keys"])
    by_id = {row["id"]: row for row in new["keys"]}
    for row in old["keys"]:
        assert by_id[row["id"]]["prefix"] == row["prefix"] and by_id[row["id"]]["right"] == row["scope"]
        assert by_id[row["id"]]["kind"] == "api" and by_id[row["id"]]["legacy"] is None
    assert next(row for row in old["keys"] if row["name"] == "iPhone-Kurzbefehl")["expires_at"] is None


def test_the_old_routes_answer_in_their_old_shapes(client: TestClient, operator: Account) -> None:
    assert client.post("/api/v1/api-keys", json={"name": "x"}).json()["detail"]["code"] == "api_off"
    assert client.put("/api/v1/settings", json={"api_keys_allowed": True}).status_code == 200
    # The shortcut's card: upload, no end.
    shortcut = client.post("/api/v1/api-keys", json={"name": "iPhone-Kurzbefehl", "days": None, "scope": "upload"})
    assert shortcut.status_code == 201
    body = shortcut.json()
    assert set(body) == {"key", "secret"} and body["secret"].startswith("npk_")
    assert body["key"]["scope"] == "upload" and body["key"]["expires_at"] is None
    assert set(body["key"]) == {"id", "name", "scope", "prefix", "created_at", "last_used_at", "expires_at", "blocked"}
    # Left out, the days were never (the old form), not the module's year for reading.
    assert client.post("/api/v1/api-keys", json={"name": "card"}).json()["key"]["expires_at"] is None
    assert client.post("/api/v1/api-keys", json={"name": "   "}).json()["key"]["name"] == "API"
    seven = client.post("/api/v1/api-keys", json={"name": "x", "days": 7})
    assert seven.status_code == 422 and seven.json()["detail"]["code"] == "invalid_input"
    write = client.post("/api/v1/api-keys", json={"name": "x", "scope": "write"})
    assert write.status_code == 422 and write.json()["detail"]["code"] == "invalid_input"
    for number in range(17):
        assert client.post("/api/v1/api-keys", json={"name": f"k{number}"}).status_code == 201
    full = client.post("/api/v1/api-keys", json={"name": "one too many"})
    assert full.status_code == 409 and full.json()["detail"]["code"] == "too_many_keys"
    gone = client.delete("/api/v1/api-keys/999999")
    assert gone.status_code == 404 and gone.json()["detail"]["code"] == "not_found"


def test_the_operator_unblocks_a_key_through_the_old_route_too(client: TestClient, operator: Account) -> None:
    client.put("/api/v1/settings", json={"api_keys_allowed": True})
    member = make_account("mika")
    token = old_key(member, "script", "read", None)
    every = client.get("/api/v1/admin/api-keys").json()
    key = next(row for row in every if row["account"] == "mika")
    assert client.post(f"/api/v1/admin/api-keys/{key['id']}/block").json()["blocked"] is True
    assert client.get("/api/v1/me", headers=bearer(token)).json()["detail"]["code"] == "key_invalid"
    unblocked = client.post(f"/api/v1/admin/api-keys/{key['id']}/unblock")
    assert unblocked.status_code == 200
    assert unblocked.json()["blocked"] is False and unblocked.json()["account"] == "mika"
    apikeys.forget()
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 200
    assert client.post("/api/v1/admin/api-keys/999999/unblock").status_code == 404
    with new_client(member) as browser:
        assert browser.post(f"/api/v1/admin/api-keys/{key['id']}/unblock").status_code == 403


def test_the_new_routes_want_a_signed_in_browser(client: TestClient, operator: Account) -> None:
    client.put("/api/v1/settings", json={"api_keys_allowed": True})
    token = old_key(operator, "script", "read", None)
    with TestClient(client.app, base_url="http://testserver", headers={"X-Nexpaper-Client": "program-tab"}) as bare:
        assert bare.get(f"{NEW}/keys").status_code == 401
        for method, path in (("GET", "/keys"), ("POST", "/keys"), ("GET", "/admin/keys"), ("GET", "/interfaces")):
            answer = bare.request(method, f"{NEW}{path}", headers=bearer(token), json={"kind": "api", "name": "x"})
            assert answer.status_code == 403 and answer.json()["detail"]["code"] == "browser_only", path
    member = make_account("mika")
    with new_client(member) as browser:
        assert browser.get(f"{NEW}/keys").status_code == 200
        assert browser.get(f"{NEW}/admin/keys").status_code == 403
        assert browser.put(f"{NEW}/interfaces", json={"api": False}).status_code == 403


def test_the_switch_of_the_card_is_the_old_setting(client: TestClient, operator: Account) -> None:
    assert client.get(f"{NEW}/interfaces").json() == {"api": False, "mcp": False}
    # Since mcp 1.1.0 the switch "MCP-Zugang" stands beside it, off in a new installation.
    assert client.put(f"{NEW}/interfaces", json={"api": True}).json() == {"api": True, "mcp": False}
    assert client.get("/api/v1/settings").json()["api_keys_allowed"] is True
    # Since mcp 1.1.0 the switch "MCP-Zugang" is nexpaper's too (setting ``mcp_enabled``); a switch nexpaper does not
    # have is still refused.
    assert client.put(f"{NEW}/interfaces", json={"mcp": True}).json() == {"api": True, "mcp": True}
    assert client.put(f"{NEW}/interfaces", json={"mcp": False}).json()["mcp"] is False
    assert client.put(f"{NEW}/interfaces", json={"pairing": True}).status_code == 422
    client.put("/api/v1/settings", json={"api_keys_allowed": False})
    assert client.get(f"{NEW}/interfaces").json() == {"api": False, "mcp": False}


def test_a_new_key_starts_with_a_year_for_reading_and_never_for_uploading(client: TestClient,
                                                                          operator: Account) -> None:
    client.put(f"{NEW}/interfaces", json={"api": True})
    listed = client.get(f"{NEW}/keys").json()
    kind = listed["kinds"][0]
    assert kind["rights"] == ["read", "upload"] and kind["default_days"] == 365
    # Since mcp 1.1.0 nexpaper has MCP (off from the start): ``mcp`` is the switch, no more ``None``.
    assert kind["default_days_by_right"] == {"upload": None} and listed["mcp"] is False
    read = client.post(f"{NEW}/keys", json={"kind": "api", "name": "card"}).json()
    upload = client.post(f"{NEW}/keys", json={"kind": "api", "name": "scanner", "right": "upload"}).json()
    assert read["key"]["expires_at"] is not None and upload["key"]["expires_at"] is None
    apikeys.forget()
    assert client.get("/api/v1/me", headers=bearer(read["secret"])).json()["scope"] == "read"
    assert client.get("/api/v1/dashboard", headers=bearer(upload["secret"])).json()["detail"]["code"] == "key_scope"


def test_an_account_that_owes_its_second_factor_reaches_its_keys_and_nothing_more(client: TestClient,
                                                                                 operator: Account) -> None:
    """Bauplan E33, the module's rule: the operator asks every account for a second factor and mika has none yet.
    Mika's browser still lists and makes keys (they rest, the card says so); everything else waits for the factor, and
    a resting key is refused where a program shows it."""
    from .conftest import require_second_factor

    client.put("/api/v1/settings", json={"api_keys_allowed": True})
    member = make_account("mika")
    with new_client(member) as browser:
        require_second_factor(True)
        listed = browser.get(f"{NEW}/keys")
        assert listed.status_code == 200 and listed.json()["keys_wait"] is True
        made = browser.post(f"{NEW}/keys", json={"kind": "api", "name": "script"})
        assert made.status_code == 201, made.text
        key = made.json()["key"]["id"]
        assert browser.patch(f"{NEW}/keys/{key}", json={"name": "scanner"}).status_code == 200
        for path in ("/api/v1/api-keys", "/api/v1/documents", f"{NEW}/interfaces", f"{NEW}/admin/keys"):
            answer = browser.get(path)
            assert answer.status_code == 403 and answer.json()["detail"]["code"] == "second_factor_setup_required", path
        apikeys.forget()
        assert client.get("/api/v1/me", headers=bearer(made.json()["secret"])).status_code == 401
        assert browser.delete(f"{NEW}/keys/{key}").status_code == 204
