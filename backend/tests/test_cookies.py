"""The cookies of a sign-in: never readable by scripts, sent only with the site's own navigations, and only over https
when the request came over https (directly or, as the proxy says, behind it)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.security import DEVICE_COOKIE, SESSION_COOKIE

from .conftest import PASSWORD, TAB, make_account


def cookies_of(answer: httpx.Response) -> dict[str, str]:
    """Each Set-Cookie line by the cookie's name, in lower case."""
    out = {}
    for line in answer.headers.get_list("set-cookie"):
        out[line.split("=", 1)[0]] = line.lower()
    return out


def sign_in(base_url: str, headers: dict[str, str] | None = None) -> dict[str, str]:
    make_account("rosa")
    with TestClient(app, base_url=base_url, headers={**TAB, **(headers or {})}) as browser:
        answer = browser.post("/api/v1/auth/login", json={"name": "rosa", "password": PASSWORD})
    assert answer.status_code == 200, answer.text
    return cookies_of(answer)


@pytest.mark.parametrize("name", [SESSION_COOKIE, DEVICE_COOKIE])
def test_plain_http_cookies_are_http_only_and_lax_without_secure(name: str) -> None:
    line = sign_in("http://testserver")[name]
    assert "httponly" in line and "samesite=lax" in line
    assert "secure" not in line.replace("samesite", "")


@pytest.mark.parametrize("name", [SESSION_COOKIE, DEVICE_COOKIE])
def test_over_https_the_cookies_are_secure(name: str) -> None:
    line = sign_in("https://testserver")[name]
    assert "httponly" in line and "samesite=lax" in line and "; secure" in line


@pytest.mark.parametrize("name", [SESSION_COOKIE, DEVICE_COOKIE])
def test_behind_a_proxy_that_speaks_https_the_cookies_are_secure(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "trusted_proxies", "127.0.0.1")
    line = sign_in("http://testserver", {"X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.7"})[name]
    assert "httponly" in line and "samesite=lax" in line and "; secure" in line


def test_the_device_cookie_goes_to_the_sign_in_only() -> None:
    assert "path=/api/v1/auth" in sign_in("http://testserver")[DEVICE_COOKIE]
