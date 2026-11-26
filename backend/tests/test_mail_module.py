"""System mail on the shared post module 1.1.0: nexpaper's own mailer is gone (one name is left for the test
"Bestand"), every mail goes through the module; what was there before goes on (a mail waiting in the outbox from
before, the mail server of the settings page, the codes of the routes of before), and what the module adds holds in
nexpaper (the page Server › Mail, one key once, the logo)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import clock
from app.db import SessionLocal, engine
from app.models import Account
from app.models_accounts import MailOutbox
from app.services import post_store, push, settings_service, tell
from app.vendor import nexpost
from app.vendor.nexpost import testing

from .conftest import make_account
from .test_settings import FakeSmtp, smtp, text_of  # noqa: F401 - fixture

APP = Path(__file__).resolve().parents[1] / "app"
MAIL = {"smtp_host": "mail.example.com", "smtp_port": 587, "smtp_security": "starttls", "smtp_user": "",
        "smtp_from": "paper@example.com"}


def mail_server() -> None:
    with SessionLocal() as db:
        settings_service.save(db, MAIL)


def test_no_mail_is_written_by_hand_any_more() -> None:
    """Every system mail goes through the shared post module: no ``smtplib``, no ``EmailMessage`` in nexpaper itself."""
    found = [str(path.relative_to(APP)) for path in APP.rglob("*.py") if "vendor" not in path.parts
             and any(word in path.read_text(encoding="utf-8") for word in ("smtplib", "EmailMessage"))]
    assert found == []
    # Nothing is left of nexpaper's own mailer (Bauplan E51): the test "Bestand" binds kontenpost in its block, and the
    # link of "Forgot your password?" goes to ``kontenpost.send_reset``, the shared post module's letter.
    assert not (APP / "services" / "mailer.py").exists()
    resets = ast.parse((APP / "routers" / "resets.py").read_text(encoding="utf-8"))
    send = next(node for node in ast.walk(resets) if isinstance(node, ast.FunctionDef) and node.name == "_send")
    calls = [ast.unparse(node.func) for node in ast.walk(send) if isinstance(node, ast.Call)]
    assert "kontenpost.send_reset" in calls and not any(call.startswith("mailer.") for call in calls), calls

def test_a_mail_waiting_in_the_outbox_from_before_still_goes_out(smtp: type[FakeSmtp]) -> None:  # noqa: F811
    """A row of the outbox as the version before wrote it (the letter as JSON without headers and key)."""
    mail_server()
    before = {"to": "kim@example.com", "subject": "A new password for nexpaper", "text": "The link.\n", "html": "",
              "kind": "reset"}
    with SessionLocal() as db:
        now = clock.now()
        db.add(MailOutbox(letter=json.dumps(before), created_at=now, next_at=now))
        db.commit()
    assert post_store.run_due() == 1
    (sent,) = smtp.sent
    assert (sent["To"], sent["Subject"], text_of(sent)) == ("kim@example.com", "A new password for nexpaper",
                                                            "The link.\n")


def test_a_key_goes_into_the_outbox_once_and_the_index_keeps_it_so() -> None:
    letter = nexpost.app_letters.write("kim@example.com", kind="deadlines_week", subject="Diese Woche: 1 Frist",
                                       paragraphs=["Eine Frist."], language="de", key="reminder-week:1:2026-10-12")
    with SessionLocal() as db:
        post_store.queue(db, letter)
        post_store.queue(db, letter)
        assert db.query(MailOutbox).count() == 1
        assert post_store.PostStore(db).waiting() == 1
    with engine.connect() as connection:
        indexes = {row[1]: row[2] for row in connection.execute(text("PRAGMA index_list(mail_outbox)"))}
    assert indexes.get("uq_mail_outbox_letter_key") == 1, "unique"


def test_the_page_server_mail_and_the_settings_of_before_are_one_mail_server(client: TestClient,
                                                                              operator: Account) -> None:
    assert client.put("/api/v1/settings", json={**MAIL, "smtp_password": "mail password"}).status_code == 200
    view = client.get("/api/v1/server/mail").json()
    assert (view["host"], view["sender"], view["password_set"], view["configured"]) == (
        "mail.example.com", "paper@example.com", True, True)
    assert "mail password" not in json.dumps(view)
    changed = client.put("/api/v1/server/mail", json={"host": "smtp.example.com", "port": 465, "security": "tls",
                                                       "user": "paper", "sender": "paper@example.com",
                                                       "sender_name": ""})
    assert changed.status_code == 200 and changed.json()["password_set"] is True, "the password stays"
    old = client.get("/api/v1/settings").json()
    assert (old["smtp_host"], old["smtp_port"], old["smtp_security"]) == ("smtp.example.com", 465, "tls")
    with SessionLocal() as db:
        assert post_store.PostStore(db).mail_settings().password == "mail password"


def test_the_test_route_of_before_answers_with_its_codes_and_the_page_with_the_modules(
    client: TestClient, operator: Account, smtp: type[FakeSmtp]  # noqa: F811
) -> None:
    off = client.post("/api/v1/settings/mail-test", json={"to": "dora@example.com"})
    assert off.status_code == 502 and off.json()["detail"]["code"] == "mail_off"
    assert client.post("/api/v1/server/mail/test", json={"to": "dora@example.com"}).json()["detail"]["code"] \
        == "mail_off"
    mail_server()
    smtp.fail = True
    failed = client.post("/api/v1/settings/mail-test", json={"to": "dora@example.com"})
    assert failed.status_code == 502 and failed.json()["detail"]["code"] == "mail_failed"
    page = client.post("/api/v1/server/mail/test", json={"to": "dora@example.com", "language": "fr"})
    assert page.status_code == 502 and page.json()["detail"]["code"] in nexpost.errors.CODES
    assert page.json()["detail"]["code"] != "mail_failed", "the page names what went wrong"
    smtp.fail = False
    assert client.post("/api/v1/server/mail/test", json={"to": "dora@example.com", "language": "fr"}) \
        .status_code == 204
    (sent,) = smtp.sent
    assert sent["Content-Language"] == "fr" and 'src="cid:logo"' in sent.get_body(("html",)).get_content()


def test_the_codes_of_before(monkeypatch: pytest.MonkeyPatch) -> None:
    def code(name: str) -> str:
        return post_store.app_code(nexpost.MailError(name, "x"))

    assert code("mail_off") == "mail_off" and code("mail_address_invalid") == "invalid_email"
    assert {code(name) for name in nexpost.errors.CODES} == {"mail_off", "invalid_email", "mail_failed"}


def test_a_notice_to_the_operators_goes_into_the_outbox_with_the_logo_and_its_words(
    operator: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    mail_server()
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None
        row.email, row.email_confirmed_at = "tester@example.com", clock.now()
        db.commit()
    monkeypatch.setattr(push, "send_to_person", lambda account_id, make_message: None)
    notice = tell.Notice(texts={"de": ("Titel", "Text"), "en": ("Title", "Text")}, url="/settings/storage",
                         tag="probe", mail_subject="nexpaper: a probe", mail_body="Something happened.\n\nSee {where}\n")
    with testing.catch_mail() as caught:
        tell._send(operator.id, notice)
    (letter,) = caught.queued
    assert letter.to == "tester@example.com" and letter.subject == "nexpaper: a probe" and letter.kind == "notice"
    assert letter.text == "Something happened.\n\nSee nexpaper\n", "the words as before, the place without an address"
    assert 'src="cid:logo"' in letter.html
    with SessionLocal() as db:
        assert db.query(MailOutbox).count() == 1


def test_a_letter_to_an_account_only_at_a_confirmed_address(operator: Account) -> None:
    kim = make_account("kim")
    with SessionLocal() as db:
        row = db.get(Account, kim.id)
        assert row is not None
        row.email, row.language = "kim@example.com", "fr"
        db.commit()
        assert post_store.PostStore(db).recipient(kim.id) is None
        row.email_confirmed_at = clock.now()
        db.commit()
        found = post_store.PostStore(db).recipient(kim.id)
    assert found is not None and (found.address, found.language) == ("kim@example.com", "fr")
