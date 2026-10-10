"""A sign-in through the provider comes back to the page it was asked from (an app's request to be paired, say), with
the fake provider of ``test_oidc.py``: after the callback, after nexpaper's own second factor, and after setting one up.
Only a path of nexpaper itself is taken; anything else ends on the start page."""

from __future__ import annotations

import time
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account
from app.services import oidc

from .conftest import PASSWORD, require_second_factor
from .test_oidc import FakeProvider, come_back, configure, fresh_browser, provider  # noqa: F401 - the fixture

ASKED = "/oauth/authorize?response_type=code&client_id=nexpaper-mobile&redirect_uri=nexpaper%3A%2F%2Foauth%2Fcallback" \
        "&code_challenge=" + "c" * 43 + "&code_challenge_method=S256&state=xyz"


def start_with(browser: TestClient, provider: FakeProvider, next_value: str | None) -> dict[str, str]:  # noqa: F811
    query = "" if next_value is None else "?next=" + quote(next_value, safe="")
    response = browser.get("/api/v1/oidc/start" + query, follow_redirects=False)
    assert response.status_code == 302, response.text
    values = {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}
    provider.challenge = values["code_challenge"]
    provider.claims = {"nonce": values["nonce"]}
    return values


def test_the_sign_in_comes_back_to_the_page_it_was_asked_from(client: TestClient, operator: Account,
                                                              provider: FakeProvider) -> None:  # noqa: F811
    configure(client)
    browser = fresh_browser(client)
    values = start_with(browser, provider, ASKED)
    answer = come_back(browser, values["state"])
    assert answer.status_code == 303 and answer.headers["location"] == ASKED
    assert browser.get("/api/v1/auth/me").status_code == 200


@pytest.mark.parametrize("hostile", [
    "//evil.example.org/x", "https://evil.example.org/", "/\\evil.example.org", "/x\\..\\y", "javascript:alert(1)",
    "/\t/evil.example.org", "/\n/evil.example.org", "/ok\r\nSet-Cookie: x=1", "/a b", "evil", "", "/" + "a" * 1200,
    "/\u0085x",
])
def test_anything_but_a_path_of_nexpaper_ends_on_the_start_page(client: TestClient, operator: Account,
                                                                 provider: FakeProvider, hostile: str  # noqa: F811
                                                                 ) -> None:
    configure(client)
    browser = fresh_browser(client)
    values = start_with(browser, provider, hostile)
    # Dropped at the start already: the signed cookie carries no way back at all.
    assert "next" not in oidc.read_attempt(browser.cookies.get(oidc.COOKIE_NAME))
    assert come_back(browser, values["state"]).headers["location"] == "/"


def test_the_way_back_is_checked_again_when_it_comes_back(client: TestClient, operator: Account,
                                                          provider: FakeProvider) -> None:  # noqa: F811
    """A cookie signed with the server's key cannot be forged, but its value is checked once more all the same."""
    assert oidc.safe_next("//evil.example.org") is None
    assert oidc.safe_next("/x\\y") is None
    assert oidc.safe_next("/schnell?x=1#y") == "/schnell?x=1#y"
    attempt = oidc.new_attempt()
    packed = oidc.pack_attempt(attempt, None, None, "//evil.example.org")
    assert oidc.read_attempt(packed)["next"] == "//evil.example.org"
    configure(client)
    browser = fresh_browser(client)
    values = start_with(browser, provider, None)
    browser.cookies.set(oidc.COOKIE_NAME, oidc.pack_attempt(
        oidc.Attempt(values["state"], values["nonce"], oidc.read_attempt(browser.cookies.get(oidc.COOKIE_NAME))["verifier"]),
        None, None, "//evil.example.org"), path=oidc.COOKIE_PATH)
    assert come_back(browser, values["state"]).headers["location"] == "/"


def test_after_nexpapers_own_second_factor_the_page_still_comes(client: TestClient, operator: Account,
                                                                provider: FakeProvider) -> None:  # noqa: F811
    from app.services import totp as totp_service

    configure(client)
    seed = client.post("/api/v1/auth/totp/begin").json()["secret"]
    assert client.post("/api/v1/auth/totp/confirm", json={"code": totp_service.code_at(seed, time.time()),
                                                       "password": PASSWORD}).status_code == 200
    with SessionLocal() as db:
        db.query(Account).filter(Account.name == "tester").update({"oidc_subject": "person-1"})
        db.commit()
    browser = fresh_browser(client)
    values = start_with(browser, provider, ASKED)
    location = come_back(browser, values["state"]).headers["location"]
    assert location == "/login?step=code&next=" + quote(ASKED, safe="")
    assert parse_qs(urlsplit(location).query)["next"] == [ASKED]


def test_after_setting_a_second_factor_up_the_page_still_comes(client: TestClient, operator: Account,
                                                               provider: FakeProvider) -> None:  # noqa: F811
    configure(client)
    require_second_factor()
    browser = fresh_browser(client)
    values = start_with(browser, provider, ASKED)
    location = come_back(browser, values["state"]).headers["location"]
    assert parse_qs(urlsplit(location).query)["next"] == [ASKED] and location.startswith("/login?")
