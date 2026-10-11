""""Ready for the internet?" checks itself, each point good and not; the switch that turns the second factor off for
everybody asks for the password."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import Account
from app.services import notices, readiness, settings_service, totp

from .conftest import PASSWORD, TAB, make_account, sign_in

WRONG = PASSWORD[::-1]


def points(client: TestClient, **kwargs: object) -> dict[str, dict]:
    answer = client.get("/api/v1/settings/readiness", **kwargs)  # type: ignore[arg-type]
    assert answer.status_code == 200, answer.text
    return {point["key"]: point for point in answer.json()["points"]}


def enrol(client: TestClient) -> str:
    seed = client.post("/api/v1/auth/totp/begin").json()["secret"]
    done = client.post("/api/v1/auth/totp/confirm", json={"code": totp.code_at(seed, time.time()), "password": PASSWORD})
    assert done.status_code == 200, done.text
    return seed


def https_client(account: Account) -> TestClient:
    browser = TestClient(app, base_url="https://testserver", headers=TAB)
    sign_in(browser, account)
    return browser


def save(values: dict) -> None:
    with SessionLocal() as db:
        settings_service.save(db, values)


# --- Ready for the internet? ------------------------------------------------------------------------------------------


def test_only_the_operator_sees_the_check(client: TestClient, operator: Account) -> None:
    anna = TestClient(app, base_url="http://testserver", headers=TAB)
    sign_in(anna, make_account("anna"))
    assert anna.get("/api/v1/settings/readiness").status_code == 403


def test_https_needs_the_public_address_and_the_request_on_https(client: TestClient, operator: Account) -> None:
    assert points(client)["https"]["state"] == "bad"
    save({"public_url": "http://paper.example.com"})
    assert points(client)["https"]["state"] == "bad"
    save({"public_url": "https://paper.example.com"})
    assert points(client)["https"]["state"] == "warn", "the address says https, the request did not come over it"
    assert points(https_client(operator))["https"]["state"] == "ok"
    assert points(client, headers={"X-Forwarded-Proto": "https"})["https"]["state"] == "ok"


@pytest.mark.parametrize(("forwarded", "https"), [
    ("https, http", False), ("http, https", True), ("HTTPS", True), ("gopher", False),
])
def test_the_check_reads_the_proxy_as_the_cookie_does(client: TestClient, operator: Account, forwarded: str,
                                                      https: bool) -> None:
    """The rightmost value counts (the left ones a sender may have written), without regard to case, and only http
    or https: the same reading as the ``Secure`` flag of the cookies, so the check never says what the cookie does
    not do."""
    save({"public_url": "https://paper.example.com"})
    found = points(client, headers={"X-Forwarded-Proto": forwarded})
    assert found["https"]["state"] == ("ok" if https else "warn"), forwarded
    assert found["cookies"]["state"] == found["https"]["state"], forwarded


def test_the_second_factor_for_everybody_and_for_the_operator(client: TestClient, operator: Account) -> None:
    found = points(client)
    assert found["two_factor"]["state"] == "bad" and found["own_account"]["state"] == "bad"
    enrol(client)
    assert points(client)["own_account"]["state"] == "ok"
    assert client.put("/api/v1/settings", json={"two_factor_required": True}).status_code == 200
    assert points(client)["two_factor"]["state"] == "ok"


def test_the_brake_and_the_proxy(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    found = points(client)
    assert found["brake"]["state"] == "ok" and found["proxy"]["state"] == "ok"
    behind = points(client, headers={"X-Forwarded-For": "203.0.113.5"})
    assert behind["brake"]["state"] == "warn" and behind["proxy"]["state"] == "warn"
    monkeypatch.setattr(get_settings(), "trusted_proxies", "172.18.0.0/16")
    proxy = TestClient(app, base_url="http://testserver", headers=TAB, client=("172.18.0.2", 50000))
    sign_in(proxy, operator)
    trusted = points(proxy, headers={"X-Forwarded-For": "203.0.113.5"})
    assert trusted["proxy"]["state"] == "ok" and trusted["brake"]["state"] == "ok"


def test_the_secret_key_is_there_and_only_the_owners(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(readiness, "CHECK_MODE", False)
    assert points(client)["secrets"] == {"key": "secrets", "state": "ok", "values": {"source": "environment"}}
    monkeypatch.setattr(get_settings(), "secret_key", "")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(get_settings(), "data_dir", elsewhere)
    assert points(client)["secrets"]["state"] == "bad" and points(client)["secrets"]["values"]["missing"] is True
    # Where modes say something: a key the group or the world may read is red, one only the owner reads is green.
    loose = elsewhere / "secret.key"
    loose.write_bytes(b"x")
    loose.chmod(0o644)
    monkeypatch.setattr(readiness, "CHECK_MODE", True)
    assert points(client)["secrets"]["state"] == "bad"
    if os.name != "nt":
        loose.chmod(0o600)
        assert points(client)["secrets"]["state"] == "ok"


def test_the_backups_point_asks_for_a_schedule(client: TestClient, operator: Account) -> None:
    assert points(client)["backups"]["state"] == "ok", "daily from the start"
    save({"backup_schedule": "off"})
    found = points(client)["backups"]
    assert found["state"] == "warn" and found["values"] == {"schedule": "off"}
    save({"backup_schedule": "weekly"})
    assert points(client)["backups"]["state"] == "ok"


def test_cookies_are_secure_only_over_https(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    assert points(client)["cookies"]["state"] == "warn"
    assert points(https_client(operator))["cookies"]["state"] == "ok"
    monkeypatch.setattr(get_settings(), "cookie_secure", "off")
    assert points(https_client(operator))["cookies"]["state"] == "bad"


def test_the_cookies_name_how_long_a_sign_in_lasts(client: TestClient, operator: Account,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """#job-215: the sentence says the number of NEXPAPER_SESSION_DAYS, and so does the sign-in page before anybody is
    signed in (the interface had 30 days fixed in its texts)."""
    monkeypatch.setattr(get_settings(), "session_days", 9)
    for found in (points(client), points(https_client(operator))):
        assert found["cookies"]["values"]["days"] == 9
    stranger = TestClient(app, base_url="http://testserver", headers=TAB)
    assert stranger.get("/api/v1/auth/methods").json()["session_days"] == 9


def test_everything_green_at_once(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness, "CHECK_MODE", False)
    enrol(client)
    client.put("/api/v1/settings", json={"two_factor_required": True, "public_url": "https://paper.example.com"})
    browser = https_client(operator)
    answer = browser.get("/api/v1/settings/readiness").json()
    assert answer["open"] == 0, answer
    assert all(point["state"] == "ok" for point in answer["points"]) and len(answer["points"]) == 8


# --- The switches that make signing in weaker ----------------------------------------------------------------------


def test_turning_the_second_factor_off_for_everybody_asks_for_the_password(client: TestClient, operator: Account) -> None:
    enrol(client)
    assert client.put("/api/v1/settings", json={"two_factor_required": True}).status_code == 200
    refused = client.put("/api/v1/settings", json={"two_factor_required": False})
    assert refused.status_code == 401 and refused.json()["detail"]["code"] == "wrong_password"
    wrong = client.put("/api/v1/settings", json={"two_factor_required": False, "current_password": WRONG})
    assert wrong.status_code == 401
    off = client.put("/api/v1/settings", json={"two_factor_required": False, "current_password": PASSWORD})
    assert off.status_code == 200 and off.json()["two_factor_required"] is False
    # Turning it on again asks for nothing: it makes signing in stronger.
    assert client.put("/api/v1/settings", json={"two_factor_required": True}).status_code == 200


def test_the_operators_reset_tells_the_person(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    told: list[tuple[str, str]] = []
    monkeypatch.setattr(notices, "factor_reset", lambda account, by: told.append((account.name, by)))
    anna = TestClient(app, base_url="http://testserver", headers=TAB)
    member = make_account("anna")
    sign_in(anna, member)
    enrol(anna)
    assert client.post(f"/api/v1/accounts/{member.id}/totp/reset", json={"current_password": WRONG}).status_code == 401
    assert told == []
    assert client.post(f"/api/v1/accounts/{member.id}/totp/reset", json={"current_password": PASSWORD}).status_code == 200
    assert told == [("anna", "tester")]


# --- The list of proxies is looked at, and so is the brake (B10) ----------------------------------------------------


@pytest.mark.parametrize("spec", ["0.0.0.0/0", "::/0", "203.0.113.5", "8.8.8.0/24", "10.0.0.0/8, 0.0.0.0/0", "2001:db8::/32",
                                  "172.32.0.0/12", "::ffff:0.0.0.0/96", "192.0.0.0/8"])
def test_a_list_of_proxies_with_a_public_network_is_red(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch, spec: str
) -> None:
    monkeypatch.setattr(get_settings(), "trusted_proxies", spec)
    found = points(client)
    assert found["proxy"]["state"] == "bad" and found["brake"]["state"] == "bad", spec
    assert found["proxy"]["values"]["networks"] and found["brake"]["values"]["networks"]
    assert client.get("/api/v1/settings/readiness").json()["open"] >= 2


@pytest.mark.parametrize("spec", ["", "127.0.0.1", "172.16.0.0/12", "172.18.0.2", "10.0.0.0/8, 192.168.0.0/16", "::1", "fd00::/8",
                                  "100.64.0.0/10", "not an address, 172.19.0.0/16", "192.168.1.1, "])
def test_a_list_of_private_networks_is_green(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch, spec: str
) -> None:
    monkeypatch.setattr(get_settings(), "trusted_proxies", spec)
    found = points(client)
    assert found["proxy"]["state"] == "ok" and found["brake"]["state"] == "ok", spec


def test_the_brake_point_tries_the_mechanism_and_not_the_one_in_use(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import security

    # A brake that never rests anybody: the check says so.
    monkeypatch.setattr(security.Brake, "wait_seconds", lambda *_args, **_kwargs: 0)
    broken = points(client)["brake"]
    assert broken["state"] == "bad" and broken["values"] == {"broken": True}
    monkeypatch.undo()
    # Nor does one that cannot forget a sender after a success.
    monkeypatch.setattr(security.Brake, "succeeded", lambda *_args, **_kwargs: None)
    assert points(client)["brake"]["state"] == "bad"
    monkeypatch.undo()
    # And a check does not leave anything behind in the brake that sign-ins use.
    before = dict(security.brake._fails)
    assert points(client)["brake"]["state"] == "ok"
    assert security.brake._fails == before


def test_the_probe_of_the_brake_is_quiet(
    client: TestClient, operator: Account, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    with caplog.at_level(logging.DEBUG):
        points(client)
    assert "Brake engaged" not in caplog.text
