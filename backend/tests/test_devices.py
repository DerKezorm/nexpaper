"""Paired devices: a token in ``Authorization: Bearer`` speaks for an account next to the session cookie of a browser, with
the rights of the account and no more. It is made from a signed-in browser only, shown once, kept as a hash, and dead
when it is revoked or its account is blocked, locked or gone. A wrong one counts against the sender."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account, Device, utcnow
from app.services import devices

from .conftest import make_account, new_client, require_second_factor, sign_in


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def pair(client: TestClient, name: str = "iPhone") -> tuple[str, str]:
    answer = client.post("/api/v1/devices", json={"name": name})
    assert answer.status_code == 201, answer.text
    return str(answer.json()["token"]), str(answer.json()["device"]["id"])


def program() -> TestClient:
    """A program: no cookie, and no tab header (a device does not name a browser tab)."""
    from app.main import app

    return TestClient(app, base_url="http://testserver")


def test_a_paired_device_speaks_for_its_account_with_its_token_alone(client: TestClient, operator: Account) -> None:
    token, _uid = pair(client)
    assert token.startswith("npd_") and len(token) > 40
    with program() as device:
        me = device.get("/api/v1/auth/me", headers=bearer(token))
        assert me.status_code == 200 and me.json()["name"] == "tester" and me.json()["role"] == "operator"
        # A change needs no tab: the token is the proof. And it acts with the rights of the account.
        assert device.put("/api/v1/me/preferences", headers=bearer(token), json={"mode": "dark"}).status_code == 200
        # The operator's side is the browser's: a token is refused there, even the operator's own.
        refused = device.get("/api/v1/settings", headers=bearer(token))
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "browser_only")
    assert client.get("/api/v1/auth/me").json()["profile"]["mode"] == "dark"


def test_a_member_device_has_the_rights_of_a_member_only(client: TestClient, operator: Account) -> None:
    with new_client(make_account("noor")) as noor:
        token, _uid = pair(noor)
    with program() as device:
        assert device.get("/api/v1/auth/me", headers=bearer(token)).json()["name"] == "noor"
        denied = device.get("/api/v1/settings", headers=bearer(token))
        assert (denied.status_code, denied.json()["detail"]["code"]) == (403, "browser_only")
        assert device.get("/api/v1/accounts", headers=bearer(token)).status_code == 403


def test_the_token_is_shown_once_and_only_its_hash_is_kept(client: TestClient, operator: Account) -> None:
    token, uid = pair(client)
    listed = client.get("/api/v1/devices").json()
    assert [(row["id"], row["name"], row["prefix"]) for row in listed] == [(uid, "iPhone", token[:8])]
    assert token not in str(listed)
    with SessionLocal() as db:
        row = db.query(Device).one()
        assert row.token_hash == devices.digest(token) and token not in str(row.__dict__)


def test_a_device_is_revoked_one_by_one_and_stops_at_once(client: TestClient, operator: Account) -> None:
    first, first_id = pair(client, "Phone")
    second, _second_id = pair(client, "Tablet")
    with program() as device:
        assert device.get("/api/v1/auth/me", headers=bearer(first)).status_code == 200
        assert client.delete(f"/api/v1/devices/{first_id}").status_code == 204
        assert device.get("/api/v1/auth/me", headers=bearer(first)).status_code == 401
        assert device.get("/api/v1/auth/me", headers=bearer(second)).status_code == 200
    assert [row["name"] for row in client.get("/api/v1/devices").json()] == ["Tablet"]
    assert client.delete(f"/api/v1/devices/{first_id}").status_code == 404, "already gone"


def test_a_device_of_another_account_is_neither_listed_nor_revoked(client: TestClient, operator: Account) -> None:
    with new_client(make_account("noor")) as noor:
        token, uid = pair(noor)
    assert client.get("/api/v1/devices").json() == []
    assert client.delete(f"/api/v1/devices/{uid}").status_code == 404
    with program() as device:
        assert device.get("/api/v1/auth/me", headers=bearer(token)).status_code == 200


def test_a_device_cannot_pair_another_or_list_devices_or_change_the_way_in(client: TestClient, operator: Account) -> None:
    token, uid = pair(client)
    with program() as device:
        for method, path, body in (("get", "/api/v1/devices", None), ("post", "/api/v1/devices", {"name": "x"}),
                                   ("delete", f"/api/v1/devices/{uid}", None),
                                   ("get", "/api/v1/api-keys", None),
                                   ("post", "/api/v1/auth/logout-all", None),
                                   ("put", "/api/v1/auth/password", {"current": "x" * 12, "new": "y" * 12}),
                                   ("post", "/api/v1/auth/totp/begin", None),
                                   ("get", "/api/v1/auth/passkeys", None)):
            answer = getattr(device, method)(path, headers=bearer(token), **({"json": body} if body else {}))
            assert (answer.status_code, answer.json()["detail"]["code"]) == (403, "browser_only"), path
    assert len(client.get("/api/v1/devices").json()) == 1


def test_a_wrong_token_is_refused_and_counts_against_the_sender(client: TestClient, operator: Account) -> None:
    token, _uid = pair(client)
    with program() as device:
        for wrong in ("npd_" + "x" * 43, "npd_" + "y" * 43, "not-a-token", ""):
            answer = device.get("/api/v1/auth/me", headers=bearer(wrong))
            assert (answer.status_code, answer.json()["detail"]["code"]) == (401, "token_invalid"), wrong
        # Five wrong ones in all (one more here), then the sender rests even with a right token.
        assert device.get("/api/v1/auth/me", headers=bearer("npd_" + "z" * 43)).status_code == 401
        rest = device.get("/api/v1/auth/me", headers=bearer(token))
        assert rest.status_code == 429 and int(rest.headers["retry-after"]) > 0


def test_a_wrong_token_never_falls_back_to_the_cookie(client: TestClient, operator: Account) -> None:
    """The browser is signed in, but the request names a token: it is judged by the token alone."""
    assert client.get("/api/v1/auth/me").status_code == 200
    refused = client.get("/api/v1/auth/me", headers=bearer("npd_" + "q" * 43))
    assert (refused.status_code, refused.json()["detail"]["code"]) == (401, "token_invalid")


def test_a_cookie_without_the_tab_header_still_cannot_change_anything(client: TestClient, operator: Account) -> None:
    """The exemption of the tab header belongs to the ``Authorization`` header only, never to the cookie."""
    from app.main import app

    with TestClient(app, base_url="http://testserver") as bare:
        sign_in(bare, operator)
        refused = bare.put("/api/v1/me/preferences", json={"mode": "dark"})
        assert (refused.status_code, refused.json()["detail"]["code"]) == (400, "client_required")


def test_a_blocked_locked_or_deleted_account_has_dead_devices(client: TestClient, operator: Account) -> None:
    noor = make_account("noor")
    with new_client(noor) as browser:
        token, _uid = pair(browser)
    with program() as device:
        assert device.get("/api/v1/auth/me", headers=bearer(token)).status_code == 200
        with SessionLocal() as db:
            row = db.get(Account, noor.id)
            assert row is not None
            row.locked_until = utcnow() + timedelta(minutes=15)
            db.commit()
        assert device.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401
        with SessionLocal() as db:
            row = db.get(Account, noor.id)
            assert row is not None
            row.locked_until = None
            row.blocked_at = utcnow()
            db.commit()
        assert device.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401
        with SessionLocal() as db:
            row = db.get(Account, noor.id)
            assert row is not None
            row.blocked_at = None
            db.commit()
        assert device.get("/api/v1/auth/me", headers=bearer(token)).status_code == 200
        assert client.request("DELETE", f"/api/v1/accounts/{noor.id}", json={"confirm_name": "noor", "current_password": "correct horse battery"}
                              ).status_code == 204
        assert device.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401
    with SessionLocal() as db:
        assert db.query(Device).count() == 0, "the rows go with the account"


def test_signing_everywhere_out_and_the_operators_sign_out_end_the_devices_too(
    client: TestClient, operator: Account
) -> None:
    token, _uid = pair(client)
    with program() as device:
        assert device.get("/api/v1/auth/me", headers=bearer(token)).status_code == 200
        assert client.post("/api/v1/auth/logout-all").status_code == 204
        assert device.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401
    noor = make_account("noor")
    with new_client(noor) as browser:
        other, _uid = pair(browser)
    with program() as device:
        assert device.get("/api/v1/auth/me", headers=bearer(other)).status_code == 200
        assert client.post(f"/api/v1/accounts/{noor.id}/sign-out").status_code == 204
        assert device.get("/api/v1/auth/me", headers=bearer(other)).status_code == 401


def test_when_the_second_factor_is_required_a_device_waits_for_a_browser_to_set_it_up(
    client: TestClient, operator: Account
) -> None:
    token, _uid = pair(client)
    with program() as device:
        assert device.get("/api/v1/auth/me", headers=bearer(token)).status_code == 200
        require_second_factor(True)
        waiting = device.get("/api/v1/auth/me", headers=bearer(token))
        assert (waiting.status_code, waiting.json()["detail"]["code"]) == (403, "second_factor_setup_required")


def test_names_are_cleaned_and_limited(client: TestClient, operator: Account) -> None:
    assert client.post("/api/v1/devices", json={"name": "  Mein   iPhone "}).json()["device"]["name"] == "Mein iPhone"
    for wrong in ("", "   ", "x" * 81, "Phone\nTwo", "Ph\u202eone"):
        answer = client.post("/api/v1/devices", json={"name": wrong})
        assert answer.status_code == 422, repr(wrong)


def test_an_account_holds_a_limited_number_of_devices(client: TestClient, operator: Account,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(devices, "MAX_DEVICES", 2)
    pair(client, "one")
    _token, second = pair(client, "two")
    full = client.post("/api/v1/devices", json={"name": "three"})
    assert (full.status_code, full.json()["detail"]["code"]) == (409, "too_many_devices")
    # A revoked device frees its place.
    assert client.delete(f"/api/v1/devices/{second}").status_code == 204
    assert client.post("/api/v1/devices", json={"name": "three"}).status_code == 201


def test_the_token_never_reaches_the_log(client: TestClient, operator: Account) -> None:
    import logging

    from app.services import logs

    logs.set_mode("trace", 30)
    try:
        token, _uid = pair(client)
        with program() as device:
            assert device.get("/api/v1/auth/me", headers=bearer(token)).status_code == 200
            assert device.get("/api/v1/auth/me", headers=bearer(token[:-3] + "xyz")).status_code == 401
    finally:
        logs.set_mode(logs.DEFAULT_MODE)
    for handler in logging.getLogger().handlers:
        handler.flush()
    folder = logs.log_file().parent
    text = "".join(path.read_text(encoding="utf-8", errors="replace") for path in folder.glob(logs.log_file().name + "*"))
    assert "Device paired" in text
    assert token not in text and token[4:20] not in text and devices.digest(token) not in text


def test_only_our_own_tokens_stand_in_for_the_tab_header(client: TestClient, operator: Account) -> None:
    """A change without the tab header is let through for ``Bearer npd_`` and ``Bearer npk_`` and for nothing else: a
    cookie with some other ``Authorization`` header is still a browser, and a browser names its tab."""
    from app.main import app
    from app.middleware import TOKEN_STARTS
    from app.services import apikeys

    assert TOKEN_STARTS == (devices.TOKEN_PREFIX.encode(), apikeys.KEY_PREFIX.encode())
    with TestClient(app, base_url="http://testserver") as bare:
        sign_in(bare, operator)
        for odd in ("Basic dXNlcjpwYXNz", "Bearer abc", "Bearer", "Token npd_" + "x" * 43, "npd_" + "x" * 43):
            refused = bare.put("/api/v1/me/preferences", json={"mode": "dark"}, headers={"Authorization": odd})
            assert (refused.status_code, refused.json()["detail"]["code"]) == (400, "client_required"), odd
        # Nor does a token of ours next to the cookie: a made-up one must not take the wall from what the cookie answers.
        for path in ("/api/v1/auth/logout", "/api/v1/auth/logout-all", "/api/v1/me/preferences"):
            beside = bare.post(path, headers=bearer("npd_" + "x" * 43))
            assert (beside.status_code, beside.json()["detail"]["code"]) == (400, "client_required"), path
        assert bare.get("/api/v1/auth/me").status_code == 200, "the session is still there"
    # A program has no cookie of ours: a token of ours needs no tab (a wrong one is judged by the route, as 401).
    with program() as plain:
        wrong = plain.put("/api/v1/me/preferences", json={"mode": "dark"}, headers=bearer("npd_" + "x" * 43))
        assert (wrong.status_code, wrong.json()["detail"]["code"]) == (401, "token_invalid")


def test_a_token_of_the_other_kind_is_refused_without_feeding_the_brake(client: TestClient, operator: Account) -> None:
    """An API key on a device route, and a device token on an API route, are a mistake of a program, not a guess at a
    secret: they say what is wrong and do not lock the sender's address out."""
    assert client.put("/api/v1/settings", json={"api_keys_allowed": True}).status_code == 200
    key = client.post("/api/v1/api-keys", json={"name": "nexdeck"}).json()["secret"]
    token, _uid = pair(client)
    with program() as program_box:
        for _ in range(12):
            on_device_route = program_box.get("/api/v1/auth/me", headers=bearer(key))
            assert (on_device_route.status_code, on_device_route.json()["detail"]["code"]) == (401, "token_wrong_kind")
            on_key_route = program_box.get("/api/v1/me", headers=bearer(token))
            assert (on_key_route.status_code, on_key_route.json()["detail"]["code"]) == (401, "token_wrong_kind")
        # The address is not locked: both right tokens still work on their own routes.
        assert program_box.get("/api/v1/auth/me", headers=bearer(token)).status_code == 200
        assert program_box.get("/api/v1/me", headers=bearer(key)).status_code == 200


def test_wrong_tokens_of_the_right_kind_still_count(client: TestClient, operator: Account) -> None:
    assert client.put("/api/v1/settings", json={"api_keys_allowed": True}).status_code == 200
    token, _uid = pair(client)
    with program() as program_box:
        for number in range(5):
            assert program_box.get("/api/v1/me", headers=bearer("npk_" + "w" * 40 + f"{number:03d}")).status_code == 401
        assert program_box.get("/api/v1/me", headers=bearer("npk_" + "w" * 43)).status_code == 429
        # The same address rests for the device routes too, even with the right token (one brake per sender).
        assert program_box.get("/api/v1/auth/me", headers=bearer(token)).status_code == 429


def test_a_device_token_cannot_switch_off_the_notice_of_new_sign_ins(client: TestClient, operator: Account) -> None:
    """Harmless choices (the look) stay open to a token; what guards the account is the browser's."""
    token, _uid = pair(client)
    assert client.get("/api/v1/auth/me").json()["profile"]["notify_login"] is True
    with program() as device:
        refused = device.put("/api/v1/me/preferences", headers=bearer(token), json={"notify_login": False})
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "browser_only")
        mixed = device.put("/api/v1/me/preferences", headers=bearer(token), json={"mode": "dark", "notify_login": False})
        assert mixed.status_code == 403, "nothing of a request that asks for it is applied"
        assert device.put("/api/v1/me/preferences", headers=bearer(token), json={"mode": "dark"}).status_code == 200
    profile = client.get("/api/v1/auth/me").json()["profile"]
    assert profile["notify_login"] is True and profile["mode"] == "dark"
    # The browser may.
    assert client.put("/api/v1/me/preferences", json={"notify_login": False}).json()["notify_login"] is False
