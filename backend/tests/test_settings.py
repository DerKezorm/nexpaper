"""The operator's settings, invitation mail through a fake SMTP server, and what a backup keeps of the sign-in."""

from __future__ import annotations

import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Any, ClassVar, Self

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Account, AuthSession, Setting
from app.security import decrypt_secret
from app.services import backups, mailer, settings_service

from .conftest import PASSWORD, make_account, sign_in


class FakeSmtp:
    sent: ClassVar[list[EmailMessage]] = []
    logins: ClassVar[list[tuple[str, str]]] = []
    tls: ClassVar[list[bool]] = []
    fail = False

    def __init__(self, host: str, port: int, timeout: float = 0, context: Any = None) -> None:
        self.host, self.port = host, port

    def __enter__(self) -> Self:
        if FakeSmtp.fail:
            raise smtplib.SMTPConnectError(421, b"mail.example.com says no to secret@example.com")
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def starttls(self, context: Any = None) -> None:
        FakeSmtp.tls.append(True)

    def login(self, user: str, password: str) -> None:
        FakeSmtp.logins.append((user, password))

    def send_message(self, message: EmailMessage) -> None:
        FakeSmtp.sent.append(message)


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSmtp]:
    FakeSmtp.sent, FakeSmtp.logins, FakeSmtp.tls, FakeSmtp.fail = [], [], [], False
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSmtp)
    return FakeSmtp


MAIL = {
    "smtp_host": "mail.example.com", "smtp_port": 587, "smtp_security": "starttls", "smtp_user": "paper",
    "smtp_password": "mail password", "smtp_from": "paper@example.com",
}


def test_settings_are_the_operators_and_the_password_is_never_shown(client: TestClient, operator: Account) -> None:
    before = client.get("/api/v1/settings").json()
    assert before["api_keys_allowed"] is False and before["password_login"] is True
    assert before["backup_schedule"] == "daily" and before["smtp_password_set"] is False
    saved = client.put("/api/v1/settings", json=MAIL).json()
    assert saved["smtp_password_set"] is True and "mail password" not in str(saved)
    with SessionLocal() as db:
        stored = db.get(Setting, "smtp_password_enc")
        assert stored is not None and "mail password" not in str(stored.value)
        assert decrypt_secret(str(stored.value)) == "mail password"
    # Left out keeps the password, empty removes it.
    assert client.put("/api/v1/settings", json={"smtp_port": 465}).json()["smtp_password_set"] is True
    assert client.put("/api/v1/settings", json={"smtp_password": ""}).json()["smtp_password_set"] is False
    member = TestClient(client.app, headers={"X-Nexpaper-Client": "tab-member00"})
    sign_in(member, make_account("member"))
    assert member.get("/api/v1/settings").status_code == 403
    assert member.put("/api/v1/settings", json={"api_keys_allowed": True}).status_code == 403


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://Notes.example.com/", "https://Notes.example.com"),
        ("http://10.0.0.5:8470", "http://10.0.0.5:8470"),
        ("", ""),
    ],
)
def test_the_public_address(client: TestClient, operator: Account, value: str, expected: str) -> None:
    assert client.put("/api/v1/settings", json={"public_url": value}).json()["public_url"] == expected


@pytest.mark.parametrize(
    "value", ["paper.example.com", "javascript:alert(1)", "https://a@b.example.com", "https://x.example.com/path"]
)
def test_a_public_address_that_is_not_one_is_refused(client: TestClient, operator: Account, value: str) -> None:
    refused = client.put("/api/v1/settings", json={"public_url": value})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "invalid_url"


def test_invitation_links_use_the_public_address(client: TestClient, operator: Account) -> None:
    client.put("/api/v1/settings", json={"public_url": "https://paper.example.com"})
    assert client.post("/api/v1/invites", json={}).json()["link"].startswith("https://paper.example.com/invite/")


def test_an_invitation_goes_out_by_mail(client: TestClient, operator: Account, smtp: type[FakeSmtp]) -> None:
    # Mail links to the public address, never to one the request names.
    client.put("/api/v1/settings", json=MAIL | {"public_url": "https://paper.example.com"})
    made = client.post("/api/v1/invites", json={"email": "dora@example.com", "send": True}).json()
    assert made["sent"] is True
    [message] = smtp.sent
    assert message["To"] == "dora@example.com" and message["From"] == "paper@example.com"
    assert made["link"] in message.get_content() and "tester invites you" in message.get_content()
    assert smtp.logins == [("paper", "mail password")] and smtp.tls == [True]


def test_mail_carries_a_date_header(client: TestClient, operator: Account, smtp: type[FakeSmtp]) -> None:
    """smtplib adds no Date; without one some providers drop the mail in silence while the app says it was sent."""
    client.put("/api/v1/settings", json=MAIL | {"public_url": "https://paper.example.com"})
    assert client.post("/api/v1/invites", json={"email": "dora@example.com", "send": True}).json()["sent"] is True
    [message] = smtp.sent
    dates = message.get_all("Date") or []
    assert len(dates) == 1
    sent_at = parsedate_to_datetime(dates[0])
    assert sent_at.tzinfo is not None and abs((datetime.now(UTC) - sent_at).total_seconds()) < 300
    assert len(message.get_all("Message-ID") or []) == 1


def test_a_failing_mail_server_says_so_without_its_answer(
    client: TestClient, operator: Account, smtp: type[FakeSmtp], caplog: pytest.LogCaptureFixture
) -> None:
    client.put("/api/v1/settings", json=MAIL)
    smtp.fail = True
    failed = client.post("/api/v1/settings/mail-test", json={"to": "dora@example.com"})
    assert failed.status_code == 502 and failed.json()["detail"]["code"] == "mail_failed"
    # The server's answer can quote addresses; only its kind goes to the log.
    assert "secret@example.com" not in caplog.text and "SMTPConnectError" in caplog.text
    smtp.fail = False
    assert client.post("/api/v1/settings/mail-test", json={"to": "dora@example.com"}).status_code == 204
    assert client.post("/api/v1/settings/mail-test", json={"to": "not an address"}).status_code == 422


def test_mail_off_without_a_server() -> None:
    with SessionLocal() as db:
        assert mailer.configured(db) is False
        with pytest.raises(mailer.MailError) as caught:
            mailer.send_test(db, "dora@example.com")
    assert caught.value.code == "mail_off"


def test_a_backup_keeps_the_secret_key_and_a_restore_signs_everybody_out(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_file = get_settings().data_dir / "secret.key"
    key_file.write_text("the key of this server", encoding="utf-8")
    try:
        client.put("/api/v1/settings", json=MAIL)
        name = backups.create().name
        key_file.write_text("a key made later", encoding="utf-8")
        monkeypatch.setattr(backups, "restart_soon", lambda: None)
        assert client.post(f"/api/v1/backups/{name}/restore", json={"password": PASSWORD}).status_code == 202
        with SessionLocal() as db:
            assert db.scalar(select(AuthSession)) is not None
        assert backups.apply_pending() is True
        assert key_file.read_text(encoding="utf-8") == "the key of this server"
        with SessionLocal() as db:
            assert db.scalar(select(AuthSession)) is None
            assert db.scalar(select(Account).where(Account.name == "tester")) is not None
            assert settings_service.get(db, "smtp_host") == "mail.example.com"
    finally:
        key_file.unlink(missing_ok=True)


@pytest.mark.parametrize(("value", "status"), [(1, 200), (100, 200), (365, 200), (0, 422), (366, 422)])
def test_backups_to_keep_go_up_to_365_as_the_interface_offers(client: TestClient, operator: Account, value: int,
                                                              status: int) -> None:
    """The interface offers 1 to 365 and the backup job reads up to 365; the setting must take the same (0.2.1 took
    only up to 100 and refused what the interface let through)."""
    answer = client.put("/api/v1/settings", json={"backup_keep": value})
    assert answer.status_code == status, answer.text
    if status == 200:
        assert answer.json()["backup_keep"] == value
        with SessionLocal() as db:
            assert backups.keep(db) == value
