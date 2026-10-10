"""Pairing a device by a code it uses once: the QR code under My account (5 minutes, once, bound to the account) and
OAuth 2 with PKCE for apps (S256 only, a fixed list of addresses per app, the code once and for two minutes). Both end
in a device token of the account, listed and revocable; a wrong code counts against the sender like a wrong password."""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app import clock
from app.db import SessionLocal
from app.models import Account, Device, Pairing
from app.services import pairing

from .conftest import make_account, new_client, require_second_factor


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def program() -> TestClient:
    """A device or an app: no cookie, and no tab header."""
    from app.main import app

    return TestClient(app, base_url="http://testserver")


def show_code(client: TestClient) -> dict[str, Any]:
    answer = client.post("/api/v1/devices/pairing")
    assert answer.status_code == 201, answer.text
    return answer.json()  # type: ignore[no-any-return]


def redeem(code: str, name: str = "iPhone von Jule") -> Any:
    with program() as device:
        return device.post("/api/v1/devices/pair", json={"code": code, "name": name})


def later(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    moment = clock.now() + timedelta(seconds=seconds)
    monkeypatch.setattr(clock, "now", lambda: moment)


# --- The QR code ------------------------------------------------------------------------------------------------------


def test_a_code_pairs_a_device_that_then_speaks_for_the_account(client: TestClient, operator: Account) -> None:
    shown = show_code(client)
    code = shown["code"]
    assert len(code) == 14 and code.count("-") == 2
    assert shown["link"].startswith("nexpaper://pair?") and "server=http" in shown["link"]
    assert parse_qs(urlsplit(shown["link"]).query)["code"] == [code]
    assert shown["qr_svg"].startswith("<svg") and shown["server"] == "http://testserver"
    assert client.get("/api/v1/devices/pairing").json()["state"] == "open"
    answer = redeem(code)
    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert body["account"] == "tester" and body["token"].startswith("npd_")
    assert body["device"]["name"] == "iPhone von Jule" and body["device"]["via"] == "qr"
    with program() as device:
        assert device.get("/api/v1/auth/me", headers=bearer(body["token"])).json()["name"] == "tester"
    # The browser that showed the code hears of it, and the device stands in the list.
    state = client.get("/api/v1/devices/pairing").json()
    assert state["state"] == "used" and state["device"]["id"] == body["device"]["id"]
    assert [row["via"] for row in client.get("/api/v1/devices").json()] == ["qr"]
    # Only its hash is kept.
    with SessionLocal() as db:
        stored = db.query(Pairing).one()
        assert stored.code_hash == hashlib.sha256(code.replace("-", "").encode()).hexdigest()
        assert code not in repr(stored.__dict__)


def test_a_code_is_typed_as_people_type_it(client: TestClient, operator: Account) -> None:
    code = show_code(client)["code"]
    assert redeem("  " + code.lower().replace("-", " ") + " ").status_code == 201


def test_a_code_is_used_once(client: TestClient, operator: Account) -> None:
    code = show_code(client)["code"]
    assert redeem(code).status_code == 201
    again = redeem(code, "Second phone")
    assert (again.status_code, again.json()["detail"]["code"]) == (400, "pairing_code_invalid")
    with SessionLocal() as db:
        assert db.query(Device).count() == 1


def test_two_devices_with_the_same_code_at_once_make_one(client: TestClient, operator: Account) -> None:
    code = show_code(client)["code"]
    start = threading.Barrier(4)
    answers: list[int] = []

    def go(index: int) -> None:
        start.wait()
        answers.append(redeem(code, f"Phone {index}").status_code)

    threads = [threading.Thread(target=go, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(answers) == [201, 400, 400, 400]
    with SessionLocal() as db:
        assert db.query(Device).count() == 1


def test_a_code_runs_out_after_five_minutes(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch
                                           ) -> None:
    code = show_code(client)["code"]
    later(monkeypatch, 5 * 60 + 1)
    assert client.get("/api/v1/devices/pairing").json()["state"] == "expired"
    assert redeem(code).status_code == 400
    with SessionLocal() as db:
        assert db.query(Device).count() == 0


def test_a_code_works_just_before_it_runs_out(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch
                                             ) -> None:
    code = show_code(client)["code"]
    later(monkeypatch, 5 * 60 - 1)
    assert redeem(code).status_code == 201


def test_a_new_code_ends_the_one_before_and_cancel_ends_it(client: TestClient, operator: Account) -> None:
    first = show_code(client)["code"]
    second = show_code(client)["code"]
    assert redeem(first).status_code == 400
    assert client.post("/api/v1/devices/pairing/cancel").status_code == 204
    assert client.get("/api/v1/devices/pairing").json()["state"] == "none"
    assert redeem(second).status_code == 400


def test_a_code_is_bound_to_its_account(client: TestClient, operator: Account) -> None:
    """The code of one account pairs a device of that account, whoever sends it; another account neither sees nor ends
    it."""
    noor = make_account("noor")
    with new_client(noor) as other:
        code = show_code(other)["code"]
        assert client.get("/api/v1/devices/pairing").json()["state"] == "none"
        assert client.post("/api/v1/devices/pairing/cancel").status_code == 204
        assert other.get("/api/v1/devices/pairing").json()["state"] == "open"
        made = redeem(code)
        assert made.json()["account"] == "noor"
        assert client.get("/api/v1/devices").json() == []
        assert [row["id"] for row in other.get("/api/v1/devices").json()] == [made.json()["device"]["id"]]


def test_guessing_codes_rests_the_sender_and_then_even_a_right_one_waits(client: TestClient, operator: Account) -> None:
    code = show_code(client)["code"]
    for _ in range(5):
        assert redeem("AAAA-BBBB-CCCC").status_code == 400
    resting = redeem(code)
    assert (resting.status_code, resting.json()["detail"]["code"]) == (429, "too_many_attempts")
    assert "Retry-After" in resting.headers


def test_codes_of_the_wrong_shape_count_as_wrong(client: TestClient, operator: Account) -> None:
    for wrong in ("x", "AAAA-BBBB-CCC1", "0000-0000-0000", "ÄÄÄÄ-BBBB-CCCC", "A" * 64):
        assert redeem(wrong).status_code == 400, wrong
    assert redeem("AAAA-BBBB-CCCC").status_code == 429


def test_only_a_signed_in_browser_with_a_full_session_makes_a_code(client: TestClient, operator: Account) -> None:
    token = client.post("/api/v1/devices", json={"name": "Old phone"}).json()["token"]
    with program() as device:
        for method, path in (("POST", "/api/v1/devices/pairing"), ("GET", "/api/v1/devices/pairing"),
                             ("POST", "/api/v1/devices/pairing/cancel")):
            answer = device.request(method, path, headers=bearer(token))
            assert (answer.status_code, answer.json()["detail"]["code"]) == (403, "browser_only"), path
        assert device.get("/api/v1/devices/pairing").status_code == 401
        assert device.post("/api/v1/devices/pairing", headers={"X-Nexpaper-Client": "tab-device00"}).status_code == 401
    # A session that still has to set up its second factor reaches no code either.
    require_second_factor(True)
    assert client.post("/api/v1/devices/pairing").status_code == 403


def test_a_code_of_an_account_that_may_not_sign_in_pairs_nothing(client: TestClient, operator: Account) -> None:
    noor = make_account("noor")
    with new_client(noor) as other:
        code = show_code(other)["code"]
    with SessionLocal() as db:
        row = db.get(Account, noor.id)
        assert row is not None
        row.blocked_at = clock.now()
        db.commit()
    assert redeem(code).status_code == 400
    with SessionLocal() as db:
        assert db.query(Device).count() == 0


def test_when_a_second_factor_is_required_and_missing_the_code_pairs_nothing(client: TestClient, operator: Account
                                                                            ) -> None:
    code = show_code(client)["code"]
    require_second_factor(True)
    assert redeem(code).status_code == 400


def test_the_device_names_itself_within_the_rules(client: TestClient, operator: Account) -> None:
    for wrong in ("", "x" * 81, "Phone\nTwo", "Ph\u202eone"):
        code = show_code(client)["code"]
        assert redeem(code, wrong).status_code == 422, repr(wrong)
        # A name that is not taken leaves the code as it was.
        assert redeem(code, "Fine").status_code == 201


def test_the_pairing_route_needs_no_tab_header_and_reads_no_cookie(client: TestClient, operator: Account) -> None:
    code = show_code(client)["code"]
    with program() as device:
        device.cookies.set("nexpaper_session", "made-up")
        assert device.post("/api/v1/devices/pair", json={"code": code, "name": "Tablet"}).status_code == 201


def test_a_paired_device_is_revoked_like_any_other(client: TestClient, operator: Account) -> None:
    body = redeem(show_code(client)["code"]).json()
    assert client.delete(f"/api/v1/devices/{body['device']['id']}").status_code == 204
    with program() as device:
        assert device.get("/api/v1/auth/me", headers=bearer(body["token"])).status_code == 401


# --- OAuth 2 with PKCE ------------------------------------------------------------------------------------------------

APP = "nexpaper-mobile"
BACK = "nexpaper://oauth/callback"


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def ask(client: TestClient, challenge: str, **change: Any) -> Any:
    body = {"client_id": APP, "redirect_uri": BACK, "response_type": "code", "code_challenge": challenge,
            "code_challenge_method": "S256", "state": "xyz", "device_name": "Pixel von Tom", **change}
    return client.post("/api/v1/oauth/authorize", json=body)


def code_from(answer: Any) -> str:
    assert answer.status_code == 200, answer.text
    target = answer.json()["redirect"]
    assert target.startswith((BACK + "?", "http://127.0.0.1"))
    query = parse_qs(urlsplit(target).query)
    assert query["state"] == ["xyz"]
    return query["code"][0]


def trade(code: str, verifier: str, **change: str) -> Any:
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": BACK, "client_id": APP,
            "code_verifier": verifier, **change}
    with program() as app:
        return app.post("/api/v1/oauth/token", data=form)


def test_an_app_gets_a_device_token_with_pkce(client: TestClient, operator: Account) -> None:
    verifier, challenge = pkce()
    seen = client.get("/api/v1/oauth/authorize", params={
        "client_id": APP, "redirect_uri": BACK, "response_type": "code", "code_challenge": challenge,
        "code_challenge_method": "S256", "state": "xyz", "device_name": "Pixel von Tom"})
    assert seen.status_code == 200 and seen.json()["device_name"] == "Pixel von Tom"
    answer = trade(code_from(ask(client, challenge)), verifier)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["token_type"] == "Bearer" and body["access_token"].startswith("npd_") and body["account"] == "tester"
    assert answer.headers["cache-control"] == "no-store"
    with program() as app:
        assert app.get("/api/v1/auth/me", headers=bearer(body["access_token"])).status_code == 200
    listed = client.get("/api/v1/devices").json()
    assert [(row["name"], row["via"]) for row in listed] == [("Pixel von Tom", "app:nexpaper-mobile")]


def test_the_token_request_may_be_json_too(client: TestClient, operator: Account) -> None:
    verifier, challenge = pkce()
    code = code_from(ask(client, challenge))
    with program() as app:
        answer = app.post("/api/v1/oauth/token", json={"grant_type": "authorization_code", "code": code,
                                                        "redirect_uri": BACK, "client_id": APP,
                                                        "code_verifier": verifier})
    assert answer.status_code == 200


def test_a_wrong_verifier_gets_nothing_and_uses_the_code_up(client: TestClient, operator: Account) -> None:
    verifier, challenge = pkce()
    code = code_from(ask(client, challenge))
    wrong, _ = pkce()
    refused = trade(code, wrong)
    assert (refused.status_code, refused.json()["error"]) == (400, "invalid_grant")
    assert trade(code, verifier).status_code == 400, "whoever caught the code gets one try"
    with SessionLocal() as db:
        assert db.query(Device).count() == 0


def test_a_code_is_traded_once(client: TestClient, operator: Account) -> None:
    verifier, challenge = pkce()
    code = code_from(ask(client, challenge))
    assert trade(code, verifier).status_code == 200
    assert trade(code, verifier).json()["error"] == "invalid_grant"
    with SessionLocal() as db:
        assert db.query(Device).count() == 1


def test_a_code_runs_out_after_two_minutes(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch
                                          ) -> None:
    verifier, challenge = pkce()
    code = code_from(ask(client, challenge))
    later(monkeypatch, 2 * 60 + 1)
    assert trade(code, verifier).json()["error"] == "invalid_grant"


def test_the_code_belongs_to_its_app_and_its_address(client: TestClient, operator: Account) -> None:
    verifier, challenge = pkce()
    assert trade(code_from(ask(client, challenge)), verifier, client_id="nexpaper-desktop").status_code == 400
    verifier, challenge = pkce()
    assert trade(code_from(ask(client, challenge)), verifier, redirect_uri=BACK + "x").status_code == 400


def test_a_foreign_address_or_an_unknown_app_is_never_answered(client: TestClient, operator: Account) -> None:
    _verifier, challenge = pkce()
    for change, code in (
        ({"redirect_uri": "https://evil.example.org/callback"}, "oauth_redirect_refused"),
        ({"redirect_uri": "nexpaper://oauth/callback/../x"}, "oauth_redirect_refused"),
        ({"redirect_uri": "http://127.0.0.1:8080/callback"}, "oauth_redirect_refused"),
        ({"client_id": "nexpaper-desktop", "redirect_uri": "http://evil.example.org:8080/callback"},
         "oauth_redirect_refused"),
        ({"client_id": "nexpaper-desktop", "redirect_uri": "http://127.0.0.1.evil.example.org:8080/callback"},
         "oauth_redirect_refused"),
        ({"client_id": "nexpaper-desktop", "redirect_uri": "http://user@127.0.0.1:8080/callback"},
         "oauth_redirect_refused"),
        ({"client_id": "nexpaper-desktop", "redirect_uri": "https://127.0.0.1:8080/callback"},
         "oauth_redirect_refused"),
        ({"client_id": "nexpaper-desktop", "redirect_uri": "http://127.0.0.1/callback"}, "oauth_redirect_refused"),
        ({"client_id": "made-up"}, "oauth_client_unknown"),
    ):
        answer = ask(client, challenge, **change)
        assert (answer.status_code, answer.json()["detail"]["code"]) == (400, code), change
        assert "redirect" not in answer.json()["detail"], "nothing goes back to an address that is not allowed"
    with SessionLocal() as db:
        assert db.query(Pairing).count() == 0


def test_a_desktop_app_is_answered_on_the_loopback_with_any_port(client: TestClient, operator: Account) -> None:
    verifier, challenge = pkce()
    for back in ("http://127.0.0.1:53123/callback", "http://[::1]:61000/callback"):
        answer = ask(client, challenge, client_id="nexpaper-desktop", redirect_uri=back)
        assert answer.json()["redirect"].startswith(back + "?code=")
        code = parse_qs(urlsplit(answer.json()["redirect"]).query)["code"][0]
        assert trade(code, verifier, client_id="nexpaper-desktop", redirect_uri=back).status_code == 200


def test_plain_pkce_and_no_pkce_are_refused_and_the_app_is_told(client: TestClient, operator: Account) -> None:
    verifier, challenge = pkce()
    for change in ({"code_challenge_method": "plain", "code_challenge": verifier[:43]},
                   {"code_challenge_method": "", "code_challenge": ""},
                   {"code_challenge": "short"}):
        answer = ask(client, challenge, **change)
        assert (answer.status_code, answer.json()["detail"]["code"]) == (400, "oauth_pkce_required"), change
        back = answer.json()["detail"]["redirect"]
        assert back.startswith(BACK + "?") and parse_qs(urlsplit(back).query)["error"] == ["invalid_request"]
    answer = ask(client, challenge, response_type="token")
    assert parse_qs(urlsplit(answer.json()["detail"]["redirect"]).query)["error"] == ["unsupported_response_type"]


def test_refusing_tells_the_app_and_makes_no_code(client: TestClient, operator: Account) -> None:
    _verifier, challenge = pkce()
    answer = ask(client, challenge, allow=False)
    query = parse_qs(urlsplit(answer.json()["redirect"]).query)
    assert query == {"error": ["access_denied"], "state": ["xyz"]}
    with SessionLocal() as db:
        assert db.query(Pairing).count() == 0


def test_only_a_signed_in_browser_allows_an_app(client: TestClient, operator: Account) -> None:
    _verifier, challenge = pkce()
    token = client.post("/api/v1/devices", json={"name": "Old phone"}).json()["token"]
    with program() as app:
        answer = app.post("/api/v1/oauth/authorize", headers=bearer(token), json={
            "client_id": APP, "redirect_uri": BACK, "code_challenge": challenge, "code_challenge_method": "S256"})
        assert (answer.status_code, answer.json()["detail"]["code"]) == (403, "browser_only")
        assert app.get("/api/v1/oauth/authorize").status_code == 401
    # Without the tab header a browser's cookie allows nothing either (the wall against other sites).
    with new_client() as stranger:
        stranger.cookies.update(client.cookies)
        answer = stranger.post("/api/v1/oauth/authorize", headers={"X-Nexpaper-Client": ""}, json={
            "client_id": APP, "redirect_uri": BACK, "code_challenge": challenge, "code_challenge_method": "S256"})
        assert (answer.status_code, answer.json()["detail"]["code"]) == (400, "client_required")
    require_second_factor(True)
    assert ask(client, challenge).status_code == 403


def test_wrong_codes_at_the_token_route_rest_the_sender(client: TestClient, operator: Account) -> None:
    verifier, challenge = pkce()
    code = code_from(ask(client, challenge))
    for _ in range(5):
        assert trade("made-up-" + secrets.token_hex(4), verifier).status_code == 400
    assert trade(code, verifier).status_code == 429


def test_the_token_route_answers_bad_requests_as_oauth_does(client: TestClient, operator: Account) -> None:
    with program() as app:
        assert app.post("/api/v1/oauth/token", data={"grant_type": "password"}).json()["error"] == "invalid_request"
        answer = app.post("/api/v1/oauth/token", data={"grant_type": "client_credentials", "code": "", "client_id": "",
                                                       "redirect_uri": "", "code_verifier": ""})
        assert answer.json()["error"] == "unsupported_grant_type"
        assert app.post("/api/v1/oauth/token", content=b"[1]",
                        headers={"Content-Type": "application/json"}).json()["error"] == "invalid_request"
        assert app.post("/api/v1/oauth/token", content=b"x" * 5000).json()["error"] == "invalid_request"


def test_codes_are_kept_as_hashes_and_never_logged(client: TestClient, operator: Account,
                                                    caplog: pytest.LogCaptureFixture) -> None:
    verifier, challenge = pkce()
    code = code_from(ask(client, challenge))
    token = trade(code, verifier).json()["access_token"]
    qr = show_code(client)["code"]
    with SessionLocal() as db:
        hashes = {row.code_hash for row in db.query(Pairing)}
    assert pairing.digest(code) in hashes
    for secret in (code, token, qr, qr.replace("-", ""), verifier):
        assert secret not in caplog.text


# --- Review: web pages, brakes, exact addresses, sweeping ---------------------------------------------------------------


def sign_in_works(client: TestClient) -> int:
    from app.main import app

    from .conftest import PASSWORD, TAB

    with TestClient(app, base_url="http://testserver", headers=TAB) as browser:
        return browser.post("/api/v1/auth/login", json={"name": "tester", "password": PASSWORD}).status_code


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example.org"}, {"Sec-Fetch-Site": "cross-site"},
                                     {"Sec-Fetch-Site": "same-site"}])
def test_a_web_page_is_refused_and_feeds_no_brake(client: TestClient, operator: Account, headers: dict[str, str]
                                                  ) -> None:
    """A page a person visits sends forms to the open routes (a form needs no preflight): they are refused before
    anything is counted, and the sign-in of the household stays open."""
    with program() as page:
        for _ in range(6):
            answer = page.post("/api/v1/oauth/token", headers=headers, data={
                "grant_type": "authorization_code", "code": "x", "redirect_uri": BACK, "client_id": APP,
                "code_verifier": "v" * 43})
            assert answer.status_code == 403 and answer.json()["error"] == "invalid_request"
            refused = page.post("/api/v1/devices/pair", headers=headers, json={"code": "AAAA-BBBB-CCCC", "name": "x"})
            assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "origin_refused")
    assert sign_in_works(client) == 200
    # And a right code from a program still works: nothing rests.
    assert redeem(show_code(client)["code"]).status_code == 201


def test_wrong_codes_rest_pairing_and_never_the_sign_in(client: TestClient, operator: Account) -> None:
    for _ in range(5):
        assert redeem("AAAA-BBBB-CCCC").status_code == 400
    assert redeem("AAAA-BBBB-CCCC").status_code == 429
    verifier, _challenge = pkce()
    assert trade("made-up", verifier).status_code == 429, "one brake for both ways of pairing"
    assert sign_in_works(client) == 200


def test_the_routes_without_a_tab_are_exactly_these() -> None:
    from app.middleware import PROGRAM_PATHS

    assert frozenset({"/api/v1/devices/pair", "/api/v1/oauth/token"}) == PROGRAM_PATHS
    with program() as anyone:
        assert anyone.post("/api/v1/auth/login", json={"name": "x", "password": "y"}).json()["detail"]["code"] == (
            "client_required")


@pytest.mark.parametrize("back", [
    "http://127.0.0.1:1023/callback", "http://127.0.0.1:0/callback", "http://127.0.0.1:65536/callback",
    "http://127.0.0.1:8080/x", "http://127.0.0.1:8080/", "http://127.0.0.1:8080/callback/",
    "HTTP://127.0.0.1:8080/callback", "Http://127.0.0.1:8080/callback", "http://LOCALHOST:8080/callback",
    "http://127.0.0.1:8080/callback?x=1", "http://127.0.0.1:8080/callback#x",
])
def test_the_loopback_is_one_spelling(client: TestClient, operator: Account, back: str) -> None:
    _verifier, challenge = pkce()
    answer = ask(client, challenge, client_id="nexpaper-desktop", redirect_uri=back)
    assert (answer.status_code, answer.json()["detail"]["code"]) == (400, "oauth_redirect_refused")


def test_the_lowest_and_highest_ports_are_taken(client: TestClient, operator: Account) -> None:
    _verifier, challenge = pkce()
    for back in ("http://127.0.0.1:1024/callback", "http://127.0.0.1:65535/callback"):
        assert ask(client, challenge, client_id="nexpaper-desktop", redirect_uri=back).status_code == 200


def test_a_verifier_of_the_wrong_form_leaves_the_code_as_it_was(client: TestClient, operator: Account) -> None:
    verifier, challenge = pkce()
    code = code_from(ask(client, challenge))
    assert trade(code, "short").json()["error"] == "invalid_grant"
    assert trade(code, verifier).status_code == 200


def test_used_and_run_out_codes_are_swept_after_an_hour(client: TestClient, operator: Account,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    used = show_code(client)["code"]
    assert redeem(used).status_code == 201
    _verifier, challenge = pkce()
    code_from(ask(client, challenge))
    open_code = show_code(client)["code"]
    with SessionLocal() as db:
        assert pairing.sweep(db) == 0
        assert db.query(Pairing).count() == 3
    later(monkeypatch, 3600 + 6 * 60)
    with SessionLocal() as db:
        assert pairing.sweep(db) == 3
        assert db.query(Pairing).count() == 0
    assert open_code
