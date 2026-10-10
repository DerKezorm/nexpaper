"""The addresses a person forwards documents from: added from the own browser, counted only once the link mailed to them
was opened (once, within 24 hours), removed only by their person; and what My account tells about the mailbox."""

from __future__ import annotations

import threading
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import clock
from app.db import SessionLocal
from app.models import Account, MailSender
from app.services import mail_senders, settings_service

from .conftest import TAB, make_account, new_client
from .test_emails import PUBLIC, mail_on
from .test_settings import FakeSmtp, smtp  # noqa: F401 - fixture


def link_of(smtp_class: type[FakeSmtp]) -> str:
    text = smtp_class.sent[-1].get_content()
    line = next(line for line in text.splitlines() if line.startswith(PUBLIC + "/absender/"))
    return line.rsplit("/", 1)[1]


def rows() -> list[MailSender]:
    with SessionLocal() as db:
        found = list(db.scalars(select(MailSender).order_by(MailSender.id)))
        for row in found:
            db.expunge(row)
        return found


def test_an_address_counts_once_its_link_was_opened(client: TestClient, operator: Account,
                                                     smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    with SessionLocal() as db:
        settings_service.save(db, {"mail_on": True, "mail_address": "paper@example.com"})
    answer = client.post("/api/v1/me/mail-senders", json={"address": "Tester.Privat@example.com"})
    assert answer.status_code == 201, answer.text
    assert answer.json()["confirmed"] is False and answer.json()["until"]
    [sent] = smtp.sent
    assert sent["To"] == "Tester.Privat@example.com" and "paper@example.com" in sent.get_content()
    with SessionLocal() as db:
        assert mail_senders.owners(db, "tester.privat@example.com") == set(), "not before the link"
    token = link_of(smtp)
    [row] = rows()
    assert row.token_hash and token not in row.token_hash, "only the hash is kept"
    with TestClient(client.app, base_url="http://testserver", headers=TAB) as somebody:
        shown = somebody.get(f"/api/v1/mail-senders/confirm/{token}")
        assert shown.status_code == 200 and shown.json() == {"name": "tester", "address": "Tester.Privat@example.com"}
        assert somebody.post(f"/api/v1/mail-senders/confirm/{token}").status_code == 200
        assert somebody.post(f"/api/v1/mail-senders/confirm/{token}").status_code == 404, "once"
    with SessionLocal() as db:
        assert mail_senders.owners(db, "TESTER.privat@example.com") == {operator.id}
    body = client.get("/api/v1/me/intake").json()
    assert body["senders"][0]["confirmed"] is True and body["senders"][0]["until"] is None
    assert body["mail_on"] is True and body["plus_address"] == "paper+tester@example.com"
    again = client.post("/api/v1/me/mail-senders", json={"address": "tester.privat@EXAMPLE.com"})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "sender_exists"


def test_two_presses_of_one_link_confirm_once(client: TestClient, operator: Account,
                                              smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    client.post("/api/v1/me/mail-senders", json={"address": "a@example.com"})
    token = link_of(smtp)
    results: list[object] = []

    def press() -> None:
        with SessionLocal() as db:
            results.append(mail_senders.confirm(db, token))

    threads = [threading.Thread(target=press) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(1 for result in results if result is not None) == 1


def test_a_link_runs_out(client: TestClient, operator: Account, smtp: type[FakeSmtp],  # noqa: F811
                         monkeypatch: object) -> None:
    mail_on()
    client.post("/api/v1/me/mail-senders", json={"address": "a@example.com"})
    token = link_of(smtp)
    with SessionLocal() as db:
        row = db.scalar(select(MailSender))
        assert row is not None
        row.expires_at = clock.now() - timedelta(seconds=1)
        db.commit()
    assert client.post(f"/api/v1/mail-senders/confirm/{token}").status_code == 404
    assert client.get("/api/v1/me/intake").json()["senders"] == [], "a link that ran out unopened is gone"


def test_without_a_mail_server_nothing_is_added(client: TestClient, operator: Account) -> None:
    answer = client.post("/api/v1/me/mail-senders", json={"address": "a@example.com"})
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "mail_off"
    assert rows() == []
    assert client.get("/api/v1/me/intake").json()["can_confirm"] is False


def test_the_own_account_address_counts_already(client: TestClient, operator: Account,
                                                smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None
        row.email, row.email_confirmed_at = "tester@example.com", clock.now()
        db.commit()
    answer = client.post("/api/v1/me/mail-senders", json={"address": "Tester@example.com"})
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "sender_is_account"
    assert client.get("/api/v1/me/intake").json()["account_address"] == "tester@example.com"


def test_not_a_mail_address(client: TestClient, operator: Account) -> None:
    for address in ("kein-at", "a@b", "a b@example.com", ""):
        answer = client.post("/api/v1/me/mail-senders", json={"address": address})
        assert answer.status_code == 422, address


def test_only_the_person_removes_their_address_and_only_from_a_browser(client: TestClient, operator: Account,
                                                                        smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    sender = client.post("/api/v1/me/mail-senders", json={"address": "a@example.com"}).json()["id"]
    with new_client(make_account("jule")) as jule:
        assert jule.delete(f"/api/v1/me/mail-senders/{sender}").status_code == 404
        assert jule.get("/api/v1/me/intake").json()["senders"] == []
    token = client.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with TestClient(client.app, base_url="http://testserver") as device:
        headers = {"Authorization": f"Bearer {token}"}
        assert device.delete(f"/api/v1/me/mail-senders/{sender}", headers=headers).status_code == 403
        assert device.post("/api/v1/me/mail-senders", headers=headers, json={"address": "b@example.com"}).status_code == 403
        assert device.get("/api/v1/me/intake", headers=headers).status_code == 200
    assert client.delete(f"/api/v1/me/mail-senders/{sender}").status_code == 204
    assert rows() == []


def test_many_links_are_braked(client: TestClient, operator: Account, smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    codes = [client.post("/api/v1/me/mail-senders", json={"address": f"a{n}@example.com"}).status_code
             for n in range(mail_senders.PER_ACCOUNT + 1)]
    assert codes[:-1] == [201] * mail_senders.PER_ACCOUNT and codes[-1] == 429


def test_a_wrong_link_counts_against_the_sender(client: TestClient, operator: Account) -> None:
    with TestClient(client.app, base_url="http://testserver", headers=TAB) as somebody:
        codes = [somebody.post("/api/v1/mail-senders/confirm/" + "x" * 30).status_code for _ in range(8)]
    assert codes[0] == 404 and 429 in codes


def test_the_token_of_a_link_never_reaches_the_log() -> None:
    from app.services import logs

    token = "Ab3_" + "x" * 30
    for path in (f"/absender/{token}", f"/api/v1/mail-senders/confirm/{token}"):
        assert token not in logs.redact(f"GET {path} 200")


def test_a_link_that_was_used_is_gone_from_the_database(client: TestClient, operator: Account,
                                                       smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    client.post("/api/v1/me/mail-senders", json={"address": "a@example.com"})
    token = link_of(smtp)
    assert client.post(f"/api/v1/mail-senders/confirm/{token}").status_code == 200
    [row] = rows()
    assert row.token_hash == "" and row.expires_at is None and row.confirmed_at is not None
