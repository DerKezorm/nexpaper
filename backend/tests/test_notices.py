"""A notice when an account signs in from a new device: a push to its devices and a mail. Not from a browser that
signed in as it before, not for the very first sign-in of an account, not when the person switched it off. It names
device, browser, the network (never the whole address) and the time, and leads to the own account, Security."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient

from app import clock
from app.db import SessionLocal
from app.main import app
from app.models import Account
from app.security import DEVICE_COOKIE
from app.services import mailer, notices, settings_service

from .conftest import PASSWORD, make_account
from .fake_push import FakePushService
from .test_oidc import FakeProvider, configure, fresh_browser, provider, sign_in_via_oidc  # noqa: F401 - fixture

FIREFOX = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0"
SAFARI = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
          "Version/18.0 Mobile/15E148 Safari/604.1")


def browser(address: str = "203.0.113.57", agent: str = FIREFOX) -> TestClient:
    return TestClient(app, base_url="http://testserver", client=(address, 50000),
                      headers={"X-Nexpaper-Client": "tab-notices00", "User-Agent": agent})


def log_in(client: TestClient, name: str = "anna") -> None:
    answer = client.post("/api/v1/auth/login", json={"name": name, "password": PASSWORD})
    assert answer.status_code == 200, answer.text


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[EmailMessage]]:
    sent: list[EmailMessage] = []
    monkeypatch.setattr(mailer, "send_message", lambda _db, message: sent.append(message))
    with SessionLocal() as db:
        settings_service.save(db, {"smtp_host": "mail.example.com", "smtp_from": "paper@example.com"})
    yield sent


@pytest.fixture
def anna(push_service: FakePushService, monkeypatch: pytest.MonkeyPatch) -> Account:
    """Anna, who signed in once on her laptop (which knows her from now on) and signed it up for pushes."""
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 10, 7, 19, 14, tzinfo=UTC))
    row = make_account("anna")
    with SessionLocal() as db:
        found = db.get(Account, row.id)
        assert found is not None
        found.email = "anna@example.com"
        found.profile = {"timezone": "Europe/Berlin"}
        db.commit()
    with browser("192.168.1.20") as laptop:
        log_in(laptop)
        assert laptop.post("/api/v1/push/devices", json=push_service.device().subscription(),
                           headers={"X-Nexpaper-Language": "de"}).status_code == 201
    notices.settle()
    return row


def test_a_new_device_is_told_to_the_others_and_by_mail(anna: Account, push_service: FakePushService,
                                                        mails: list[EmailMessage]) -> None:
    assert push_service.received == [] and mails == [], "nothing for the very first sign-in"
    with browser("203.0.113.57", SAFARI) as phone:
        log_in(phone)
    notices.settle()
    [came] = push_service.received
    assert came.message["title"] == "Neue Anmeldung bei nexpaper"
    assert came.message["body"] == ("Safari unter iPhone, 7. Oktober, 21:14, Netz 203.0.113.0/24. "
                                    "Warst du das nicht? Tippe hier.")
    assert came.message["url"] == came.message["desk"] == "/konto?tab=security"
    [mail] = mails
    assert mail["To"] == "anna@example.com" and mail["Subject"] == "New sign-in to nexpaper"
    text = mail.get_content()
    assert "Safari on iPhone" in text and "network 203.0.113.0/24" in text and "7 October, 21:14" in text
    assert "203.0.113.57" not in text and "203.0.113.57" not in str(came.message)


def test_the_very_first_sign_in_of_an_account_is_no_news(mails: list[EmailMessage],
                                                          push_service: FakePushService) -> None:
    row = make_account("mia")
    with SessionLocal() as db:
        found = db.get(Account, row.id)
        assert found is not None
        found.email = "mia@example.com"
        db.commit()
    with browser("203.0.113.57") as first:
        log_in(first, "mia")
    notices.settle()
    assert mails == []
    with browser("203.0.113.58") as second:
        log_in(second, "mia")
    notices.settle()
    assert len(mails) == 1, "the second browser is news"


def test_a_browser_that_signed_in_before_is_no_news(anna: Account, push_service: FakePushService,
                                                    mails: list[EmailMessage]) -> None:
    with browser("203.0.113.57") as phone:
        log_in(phone)
        phone.post("/api/v1/auth/logout")
        log_in(phone)
        log_in(phone)
    notices.settle()
    assert len(push_service.received) == 1 and len(mails) == 1


def test_a_shared_browser_remembers_several_accounts(anna: Account, push_service: FakePushService,
                                                     mails: list[EmailMessage]) -> None:
    make_account("ben")
    with browser("203.0.113.57") as tablet:
        log_in(tablet, "anna")
        log_in(tablet, "ben")
        log_in(tablet, "anna")
    notices.settle()
    assert len(push_service.received) == 1, "anna is told once, not again after ben used the tablet"


def test_switched_off_nothing_is_said(anna: Account, push_service: FakePushService, mails: list[EmailMessage]) -> None:
    with browser("203.0.113.57") as phone:
        log_in(phone)
        assert phone.put("/api/v1/me/preferences", json={"notify_login": False}).json()["notify_login"] is False
    with browser("203.0.113.58") as another:
        log_in(another)
    notices.settle()
    assert len(push_service.received) == 1 and len(mails) == 1, "only the sign-in before it was switched off"


def test_a_forged_or_foreign_device_cookie_is_news(anna: Account, push_service: FakePushService,
                                                   mails: list[EmailMessage]) -> None:
    from app import security

    with browser("203.0.113.57") as forged:
        forged.cookies.set(DEVICE_COOKIE, f"{anna.id}.abc." + "0f" * 16, path="/api/v1/auth")
        log_in(forged)
    ben = make_account("ben")
    with browser("203.0.113.58") as foreign:
        foreign.cookies.set(DEVICE_COOKIE, security.device_token(ben.id), path="/api/v1/auth")
        log_in(foreign)
    notices.settle()
    assert len(push_service.received) == 2


def test_without_a_mail_server_or_address_only_the_push_goes(anna: Account, push_service: FakePushService,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[EmailMessage] = []
    monkeypatch.setattr(mailer, "send_message", lambda _db, message: sent.append(message))
    with browser("203.0.113.57") as phone:
        log_in(phone)
    notices.settle()
    assert len(push_service.received) == 1 and sent == []


def test_the_link_in_the_mail_is_the_public_address_never_the_one_asked_by(anna: Account,
                                                                           mails: list[EmailMessage]) -> None:
    with TestClient(app, base_url="https://evil.example.org", client=("203.0.113.57", 50000),
                    headers={"X-Nexpaper-Client": "tab-notices00"}) as stranger:
        log_in(stranger)
    notices.settle()
    assert "evil.example.org" not in mails[0].get_content() and "http" not in mails[0].get_content()
    with SessionLocal() as db:
        settings_service.save(db, {"public_url": "https://paper.example.com"})
    with browser("203.0.113.58") as another:
        log_in(another)
    notices.settle()
    assert "https://paper.example.com/konto?tab=security" in mails[1].get_content()


def test_a_flood_of_sign_ins_is_no_flood_of_notices(anna: Account, push_service: FakePushService,
                                                    mails: list[EmailMessage]) -> None:
    for number in range(notices.PER_HOUR + 5):
        with browser(f"203.0.113.{number + 1}") as stranger:
            log_in(stranger)
    notices.settle()
    assert len(mails) == notices.PER_HOUR


def test_the_network_never_the_address(anna: Account) -> None:
    assert notices.network_of("203.0.113.57", "de") == "Netz 203.0.113.0/24"
    assert notices.network_of("2001:db8:aa:bb::1", "en") == "network 2001:db8:aa::/48"
    assert notices.network_of("::ffff:192.168.1.20", "de") == "eigenes Netz 192.168.1.0/24"
    assert notices.network_of("testclient", "en") == "unknown network"
    assert notices.device_name("", "de") == "Ein Browser unter einem unbekannten System"


def test_a_sign_in_through_the_provider_is_told_too(client: TestClient, operator: Account, provider: FakeProvider,  # noqa: F811
                                                    push_service: FakePushService) -> None:
    configure(client)
    first = fresh_browser(client)
    assert sign_in_via_oidc(first, provider).status_code == 303
    assert first.post("/api/v1/push/devices", json=push_service.device().subscription()).status_code == 201
    again = fresh_browser(client)
    assert sign_in_via_oidc(again, provider).status_code == 303
    notices.settle()
    assert len(push_service.received) == 1, "a second browser through the provider is new"
    # The first browser again, through the provider: it carries its device cookie to the return from the provider.
    assert first.cookies.get(DEVICE_COOKIE, path="/api/v1/oidc/callback")
    assert sign_in_via_oidc(first, provider).status_code == 303
    notices.settle()
    assert len(push_service.received) == 1


def test_the_device_cookie_goes_to_the_two_sign_ins_only(anna: Account) -> None:
    with browser() as phone:
        answer = phone.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD})
    lines = [line.lower() for line in answer.headers.get_list("set-cookie") if line.startswith(DEVICE_COOKIE + "=")]
    assert sorted(line.split("path=")[1].split(";")[0] for line in lines) == ["/api/v1/auth", "/api/v1/oidc/callback"]
    assert all("httponly" in line and "samesite=lax" in line for line in lines)


def test_nothing_a_person_stored_shows_in_a_notice(anna: Account, push_service: FakePushService,
                                                   mails: list[EmailMessage]) -> None:
    """A notice names the device, the time and the network, and nothing the person keeps: not even their own name for
    the account (the display name stays out of the text of the push)."""
    word = "Qx" + uuid.uuid4().hex[:8] + "Zy"
    with browser("192.168.1.20") as laptop:
        log_in(laptop)
        assert laptop.put("/api/v1/me/profile", json={"display_name": word}).status_code == 200
    with browser("203.0.113.57") as phone:
        log_in(phone)
    notices.settle()
    assert word not in str(push_service.received[0].message) and word not in mails[0].get_content()
