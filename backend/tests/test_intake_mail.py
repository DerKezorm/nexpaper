"""The mailbox for documents, against a real IMAP server in this process (``imap_server.py``), with made-up mails.

Whose a mail is (a confirmed sender address, ``paper+<account>@``, else the operator marked unknown), what is taken
(PDF, pictures, XML, also inside forwarded mails; file names in every encoding), the limits, what happens afterwards
(read, moved, deleted), exactly once (a restart, new UIDs), the ways a connection fails, the operator's lock and the
addresses a mailbox must never be looked for at."""

from __future__ import annotations

import base64
import secrets
from collections.abc import Iterator
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import clock
from app.db import SessionLocal
from app.models import Account, Document, IntakeItem, MailSender
from app.security import encrypt_secret
from app.services import intake_mail, settings_service

from . import imap_server
from .conftest import make_account, new_client
from .files import invoice_xml, make_image, make_pdf
from .intake import limit


@pytest.fixture(scope="module")
def certificate(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    return imap_server.make_certificate(tmp_path_factory.mktemp("imap"))


@pytest.fixture
def store() -> imap_server.Store:
    made = imap_server.Store()
    made.password = secrets.token_urlsafe(12)
    return made


@pytest.fixture
def trusted(monkeypatch: pytest.MonkeyPatch, certificate: tuple[Path, Path]) -> None:
    import ssl

    def context() -> ssl.SSLContext:
        made = ssl.create_default_context(cafile=str(certificate[0]))
        return made

    monkeypatch.setattr(intake_mail, "context", context)


@pytest.fixture
def server(store: imap_server.Store, certificate: tuple[Path, Path], trusted: None) -> Iterator[imap_server.Server]:
    running = imap_server.start(store, certificate, implicit_tls=True)
    yield running
    imap_server.stop(running)


def set_up(port: int, password: str, **extra: Any) -> None:
    values = {"mail_on": True, "mail_host": "127.0.0.1", "mail_port": port, "mail_security": "tls",
              "mail_user": "paper@example.com", "mail_password_enc": encrypt_secret(password, intake_mail.PASSWORD_CONTEXT),
              "mail_address": "paper@example.com", "mail_private": True, "mail_after": "read"}
    values.update(extra)
    with SessionLocal() as db:
        settings_service.save(db, values)


@pytest.fixture
def mailbox(server: imap_server.Server, store: imap_server.Store, operator: Account) -> imap_server.Store:
    set_up(server.port, store.password)
    return store


def mail(sender: str = "tom.privat@example.com", to: str = "paper@example.com", subject: str = "Rechnung",
         files: list[tuple[str, bytes, str]] | None = None, message_id: str | None = None,
         text: str = "Anbei die Rechnung.") -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = message_id or make_msgid(domain="example.com")
    message.set_content(text)
    for name, data, ctype in files or []:
        maintype, subtype = ctype.split("/")
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return message


def deliver(store: imap_server.Store, message: EmailMessage | bytes, flags: set[str] | None = None) -> int:
    data = message if isinstance(message, bytes) else message.as_bytes()
    return store.inbox().add(data, flags)


def confirmed_sender(account: Account, address: str) -> None:
    with SessionLocal() as db:
        db.add(MailSender(user_id=account.id, address=address, address_key=address.casefold(), confirmed_at=clock.now()))
        db.commit()


def docs() -> list[Document]:
    with SessionLocal() as db:
        found = list(db.scalars(select(Document).order_by(Document.id)))
        for row in found:
            db.expunge(row)
        return found


def items() -> list[IntakeItem]:
    with SessionLocal() as db:
        found = list(db.scalars(select(IntakeItem).order_by(IntakeItem.id)))
        for row in found:
            db.expunge(row)
        return found


PDF = ("Rechnung.pdf", make_pdf(), "application/pdf")


# --- Whose a mail is ---------------------------------------------------------------------------------------------------


def test_a_mail_from_a_confirmed_sender_comes_into_their_inbox(mailbox: imap_server.Store) -> None:
    tom = make_account("tom")
    confirmed_sender(tom, "Tom.Privat@example.com")
    uid = deliver(mailbox, mail(files=[PDF]))
    done = intake_mail.fetch()
    assert (done.mails, done.files, done.unknown) == (1, 1, 0)
    [document] = docs()
    assert document.owner_id == tom.id and document.source == "mail" and document.title == "Rechnung"
    assert document.status == "processing"
    [item] = items()
    assert item.unknown is False and item.key.endswith(f":1000:{uid}:0")
    assert item.detail == {"from": "tom.privat@example.com", "subject": "Rechnung", "file": "Rechnung.pdf"}
    assert "\\Seen" in mailbox.inbox().mails[0].flags, "marked read afterwards"


def test_the_plus_address_names_the_account(mailbox: imap_server.Store) -> None:
    jule = make_account("jule")
    deliver(mailbox, mail(sender="someone@example.org", to="Paper+Jule@Example.com", files=[PDF]))
    deliver(mailbox, mail(sender="someone@example.org", to="paper+niemand@example.com", files=[PDF]))
    intake_mail.fetch()
    owners = [d.owner_id for d in docs()]
    with SessionLocal() as db:
        operator_id = db.scalar(select(Account.id).where(Account.name == "tester"))
    assert owners == [jule.id, operator_id]
    assert [i.unknown for i in items()] == [False, True]


def test_an_unconfirmed_sender_address_does_not_count(mailbox: imap_server.Store, operator: Account) -> None:
    tom = make_account("tom")
    with SessionLocal() as db:
        db.add(MailSender(user_id=tom.id, address="tom.privat@example.com", address_key="tom.privat@example.com",
                          token_hash="0" * 64, expires_at=clock.now()))
        db.commit()
    deliver(mailbox, mail(files=[PDF]))
    intake_mail.fetch()
    [document] = docs()
    assert document.owner_id == operator.id
    [item] = items()
    assert item.unknown is True


def test_an_address_of_two_people_belongs_to_nobody(mailbox: imap_server.Store, operator: Account) -> None:
    for name in ("tom", "lea"):
        confirmed_sender(make_account(name), "familie@example.com")
    deliver(mailbox, mail(sender="familie@example.com", files=[PDF]))
    intake_mail.fetch()
    assert [d.owner_id for d in docs()] == [operator.id]


def test_the_confirmed_address_of_the_account_counts(mailbox: imap_server.Store) -> None:
    lea = make_account("lea")
    with SessionLocal() as db:
        row = db.get(Account, lea.id)
        assert row is not None
        row.email, row.email_confirmed_at = "lea@example.com", clock.now()
        db.commit()
    deliver(mailbox, mail(sender="Lea <LEA@example.com>", files=[PDF]))
    intake_mail.fetch()
    assert [d.owner_id for d in docs()] == [lea.id]


def test_the_origin_tells_the_owner_where_it_came_from(mailbox: imap_server.Store, client: TestClient,
                                                       operator: Account) -> None:
    deliver(mailbox, mail(sender="fremd@example.org", subject="Mahnung", files=[PDF]))
    intake_mail.fetch()
    [document] = docs()
    body = client.get(f"/api/v1/documents/{document.id}/origin").json()
    assert body["source"] == "mail" and body["unknown"] is True
    assert body["sender"] == "fremd@example.org" and body["subject"] == "Mahnung" and body["file"] == "Rechnung.pdf"
    with new_client(make_account("fremder")) as stranger:
        assert stranger.get(f"/api/v1/documents/{document.id}/origin").status_code == 404


# --- What is taken -----------------------------------------------------------------------------------------------------


def test_forwarded_mails_pictures_and_xml_are_taken_text_and_logos_are_not(mailbox: imap_server.Store) -> None:
    tom = make_account("tom")
    confirmed_sender(tom, "tom.privat@example.com")
    inner = mail(sender="rechnung@stadtwerke.example.com", to="tom.privat@example.com", subject="Strom",
                 files=[("Strom Oktober.pdf", make_pdf(["Strom"]), "application/pdf")])
    outer = mail(subject="WG: Strom", files=[("Quittung.png", make_image("png"), "image/png"),
                                              ("rechnung.xml", invoice_xml(), "application/xml"),
                                              ("notiz.txt", b"nur Text", "text/plain")])
    outer.add_attachment(inner)
    logo = make_image("png", size=(20, 20))
    related = EmailMessage()
    related.set_content("<p>Gruss</p><img src='cid:logo@example.com'>", subtype="html")
    related.add_related(logo, maintype="image", subtype="png", cid="<logo@example.com>")
    outer.attach(related)
    deliver(mailbox, outer)
    done = intake_mail.fetch()
    titles = sorted(d.title for d in docs())
    assert titles == ["Quittung", "Strom Oktober", "rechnung"], titles
    assert done.files == 3 and all(d.owner_id == tom.id for d in docs())


def test_webp_and_avif_pictures_are_taken_even_without_a_file_name(mailbox: imap_server.Store) -> None:
    """A phone that mails a picture without naming it: only the kind of the part says it is a document."""
    tom = make_account("tom")
    confirmed_sender(tom, "tom.privat@example.com")
    message = mail(subject="Zwei Fotos")
    for kind in ("webp", "avif"):
        message.add_attachment(make_image(kind), maintype="image", subtype=kind, disposition="inline")
    message.add_attachment(b"GIF89a", maintype="image", subtype="gif", disposition="inline")
    deliver(mailbox, message)
    done = intake_mail.fetch()
    assert done.files == 2 and len(docs()) == 2 and all(d.owner_id == tom.id for d in docs())


def test_file_names_in_every_encoding(mailbox: imap_server.Store, operator: Account) -> None:
    pdf = make_pdf()
    raw = (
        "From: someone@example.org\r\nTo: paper@example.com\r\nSubject: Namen\r\nMessage-ID: <n1@example.com>\r\n"
        "MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=XX\r\n\r\n"
        "--XX\r\nContent-Type: text/plain\r\n\r\nHallo\r\n"
        "--XX\r\nContent-Type: application/pdf\r\nContent-Transfer-Encoding: base64\r\n"
        "Content-Disposition: attachment; filename*=utf-8''Rechnung%20M%C3%A4rz.pdf\r\n\r\n"
        + base64.b64encode(pdf).decode() + "\r\n"
        "--XX\r\nContent-Type: application/pdf\r\nContent-Transfer-Encoding: base64\r\n"
        'Content-Disposition: attachment; filename="=?UTF-8?B?R2Vow6RsdCBTZXB0ZW1iZXIucGRm?="\r\n\r\n'
        + base64.b64encode(pdf + b"\n").decode() + "\r\n"
        "--XX\r\nContent-Type: application/pdf; name=\"=?ISO-8859-1?Q?K=FCndigung.pdf?=\"\r\n"
        "Content-Transfer-Encoding: base64\r\n\r\n"
        + base64.b64encode(pdf + b"\n\n").decode() + "\r\n"
        "--XX--\r\n"
    ).encode()
    deliver(mailbox, raw)
    intake_mail.fetch()
    assert sorted(d.title for d in docs()) == ["Gehält September", "Kündigung", "Rechnung März"]


def test_names_and_subjects_of_nothing_but_direction_characters_give_the_title_document(
        mailbox: imap_server.Store, operator: Account) -> None:
    turn, back = chr(0x202E), chr(0x202C)
    deliver(mailbox, mail(sender="a@example.org", subject="Strom", message_id="<d1@example.com>",
                          files=[(f"{turn}{back}.pdf", make_pdf(["eins"]), "application/pdf")]))
    nameless = mail(sender="b@example.org", subject=f"{turn}{back}", message_id="<d2@example.com>")
    nameless.add_attachment(make_pdf(["zwei"]), maintype="application", subtype="pdf")
    deliver(mailbox, nameless)
    intake_mail.fetch()
    assert [d.title for d in docs()] == ["Document", "Document"]


def test_broken_parts_are_passed_over(mailbox: imap_server.Store, operator: Account) -> None:
    raw = (
        "From: someone@example.org\r\nTo: paper@example.com\r\nSubject: kaputt\r\n"
        "MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=XX\r\n\r\n"
        "--XX\r\nContent-Type: application/pdf\r\nContent-Transfer-Encoding: base64\r\n"
        "Content-Disposition: attachment; filename=kaputt.pdf\r\n\r\n!!!! nicht base64 !!!!\r\n"
        "--XX\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename=\"ok.pdf\r\n\r\n"
        "--XX\r\nContent-Type: application/pdf\r\nContent-Transfer-Encoding: base64\r\n"
        "Content-Disposition: attachment; filename=gut.pdf\r\n\r\n"
        + base64.b64encode(make_pdf()).decode() + "\r\n"
        "--XX"
    ).encode()
    deliver(mailbox, raw)
    done = intake_mail.fetch()
    assert [d.title for d in docs()] == ["gut"] and done.mails == 1


def test_a_mail_too_large_is_left_alone(mailbox: imap_server.Store, monkeypatch: pytest.MonkeyPatch,
                                        operator: Account) -> None:
    monkeypatch.setattr(intake_mail, "MAIL_MAX", 2000)
    deliver(mailbox, mail(sender="a@example.org", files=[("gross.pdf", make_pdf(["x"] * 3) + b"0" * 4000,
                                                          "application/pdf")]))
    done = intake_mail.fetch()
    assert done.passed == 1 and done.flagged == 1 and docs() == []
    assert mailbox.inbox().mails[0].flags == {"\\Flagged"}, "left in the mailbox, flagged"
    assert intake_mail.fetch().passed == 0, "and not fetched again"


def test_the_limits_of_a_mail(mailbox: imap_server.Store, monkeypatch: pytest.MonkeyPatch, operator: Account) -> None:
    monkeypatch.setattr(intake_mail, "MAX_ATTACHMENTS", 2)
    limit(upload_max_mb=1)
    big = b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 1)
    deliver(mailbox, mail(sender="a@example.org", files=[("zu-gross.pdf", big, "application/pdf"),
                                                         ("eins.pdf", make_pdf(["1"]), "application/pdf"),
                                                         ("zwei.pdf", make_pdf(["2"]), "application/pdf")]))
    done = intake_mail.fetch()
    assert [d.title for d in docs()] == ["eins"], "the large one over the limit, the third over the count"
    assert done.passed == 2 and done.flagged == 1
    assert mailbox.inbox().mails[0].flags == {"\\Flagged"}, "not taken whole: not read, flagged"


def test_a_mail_without_anything_to_take_is_not_touched(mailbox: imap_server.Store, operator: Account) -> None:
    deliver(mailbox, mail(sender="a@example.org", files=[("brief.docx", b"PK\x03\x04" + b"0" * 50,
                                                          "application/octet-stream")]))
    done = intake_mail.fetch()
    assert done.mails == 0 and docs() == [] and mailbox.inbox().mails[0].flags == set()


# --- Afterwards ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("capabilities", [["IMAP4rev1", "UIDPLUS", "MOVE"], ["IMAP4rev1", "UIDPLUS"]])
def test_moved_to_nexpaper(server: imap_server.Server, store: imap_server.Store, operator: Account,
                           capabilities: list[str]) -> None:
    store.capabilities = capabilities
    set_up(server.port, store.password, mail_after="move")
    deliver(store, mail(sender="a@example.org", files=[PDF]))
    keep = deliver(store, mail(sender="a@example.org", text="nichts dran"))
    assert intake_mail.fetch().after == "move"
    assert [m.uid for m in store.inbox().mails] == [keep]
    assert len(store.folders["nexpaper"].mails) == 1
    assert ("UID MOVE" in store.commands) == ("MOVE" in capabilities)


def test_deleted(server: imap_server.Server, store: imap_server.Store, operator: Account) -> None:
    set_up(server.port, store.password, mail_after="delete")
    deliver(store, mail(sender="a@example.org", files=[PDF]))
    intake_mail.fetch()
    assert store.inbox().mails == [] and len(docs()) == 1
    assert "UID EXPUNGE" in store.commands and "EXPUNGE" not in store.commands


@pytest.mark.parametrize(("capabilities", "after", "instead"), [
    (["IMAP4rev1", "MOVE"], "delete", "move"),
    (["IMAP4rev1"], "delete", "read"),
    (["IMAP4rev1"], "move", "read"),
])
def test_without_uidplus_no_other_deleted_mail_goes(server: imap_server.Server, store: imap_server.Store,
                                                    operator: Account, client: TestClient, capabilities: list[str],
                                                    after: str, instead: str) -> None:
    store.capabilities = capabilities
    set_up(server.port, store.password, mail_after=after)
    # A mail somebody else marked deleted in their mail program, not expunged yet.
    theirs = deliver(store, mail(sender="a@example.org", text="nichts dran"), flags={"\\Deleted"})
    deliver(store, mail(sender="a@example.org", files=[PDF]))
    assert api_test(client).json() == {"mails": 2, "after": instead}, "the test says what will happen instead"
    assert intake_mail.fetch().after == instead
    assert "EXPUNGE" not in store.commands and "UID EXPUNGE" not in store.commands
    assert theirs in [m.uid for m in store.inbox().mails], "a mail nexpaper never touched stays"
    assert len(docs()) == 1


# --- Exactly once ------------------------------------------------------------------------------------------------------


def test_each_mail_once(mailbox: imap_server.Store, operator: Account) -> None:
    deliver(mailbox, mail(sender="a@example.org", files=[PDF]))
    intake_mail.fetch()
    mailbox.inbox().mails[0].flags.clear()
    intake_mail.fetch()
    assert len(docs()) == 1
    deliver(mailbox, mail(sender="a@example.org", files=[PDF]))
    assert intake_mail.fetch().files == 1 and len(docs()) == 2


def test_a_restart_before_the_place_was_kept_takes_nothing_twice(mailbox: imap_server.Store, operator: Account,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    deliver(mailbox, mail(sender="a@example.org", files=[PDF, ("Zwei.pdf", make_pdf(["2"]), "application/pdf")]))
    real = intake_mail._after

    def stops(*args: Any) -> None:
        # The server stops right after the documents were written: nothing after them happened.
        raise RuntimeError("stopped")

    monkeypatch.setattr(intake_mail, "_after", stops)
    with pytest.raises(intake_mail.MailFailure):
        intake_mail.fetch()
    assert len(docs()) == 2 and mailbox.inbox().mails[0].flags == set()
    monkeypatch.setattr(intake_mail, "_after", real)
    done = intake_mail.fetch()
    assert done.files == 0 and done.mails == 1 and len(docs()) == 2
    assert "\\Seen" in mailbox.inbox().mails[0].flags


def test_new_uids_do_not_bring_the_same_mail_again(mailbox: imap_server.Store, operator: Account) -> None:
    first = mail(sender="a@example.org", files=[PDF], message_id="<einmal@example.com>")
    deliver(mailbox, first)
    intake_mail.fetch()
    # The server renumbers its mailbox: everything has new UIDs, and the mails are unread again.
    inbox = mailbox.inbox()
    inbox.validity, inbox.mails, inbox.next_uid = 5000, [], 1
    deliver(mailbox, first)
    deliver(mailbox, mail(sender="a@example.org", files=[("Neu.pdf", make_pdf(["neu"]), "application/pdf")]))
    done = intake_mail.fetch()
    assert done.files == 1 and sorted(d.title for d in docs()) == ["Neu", "Rechnung"]


def test_a_fresh_start_marking_read_takes_the_unread_mails_only(mailbox: imap_server.Store, operator: Account) -> None:
    deliver(mailbox, mail(sender="a@example.org", files=[("Alt.pdf", make_pdf(["alt"]), "application/pdf")]),
            flags={"\\Seen"})
    deliver(mailbox, mail(sender="a@example.org", files=[("Ungelesen.pdf", make_pdf(["neu"]), "application/pdf")]))
    intake_mail.fetch()
    assert [d.title for d in docs()] == ["Ungelesen"]
    intake_mail.fetch()
    deliver(mailbox, mail(sender="a@example.org", files=[("Danach.pdf", make_pdf(["danach"]), "application/pdf")]),
            flags={"\\Seen"})
    intake_mail.fetch()
    assert [d.title for d in docs()] == ["Ungelesen", "Danach"], "after the start, read or not"


def test_a_run_takes_a_few_and_leaves_the_rest_for_the_next(mailbox: imap_server.Store, operator: Account,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intake_mail, "PER_RUN", 2)
    for number in range(5):
        deliver(mailbox, mail(sender="a@example.org", files=[(f"d{number}.pdf", make_pdf([str(number)]),
                                                              "application/pdf")]))
    assert intake_mail.fetch().more is True
    intake_mail.fetch()
    last = intake_mail.fetch()
    assert last.more is False and len(docs()) == 5


# --- Connections ------------------------------------------------------------------------------------------------------


def api_test(client: TestClient) -> Any:
    return client.post("/api/v1/settings/intake/mail/test")


def test_the_test_counts_new_mails_and_takes_nothing(mailbox: imap_server.Store, client: TestClient) -> None:
    deliver(mailbox, mail(sender="a@example.org", files=[PDF]))
    deliver(mailbox, mail(sender="a@example.org", files=[PDF]))
    answer = api_test(client)
    assert answer.status_code == 200 and answer.json() == {"mails": 2, "after": "read"}
    assert docs() == [] and all(m.flags == set() for m in mailbox.inbox().mails)
    answer = client.post("/api/v1/settings/intake/mail/fetch")
    assert answer.status_code == 200 and answer.json()["files"] == 2
    assert client.get("/api/v1/settings/intake").json()["mail"]["last"]["files"] == 2


def test_a_wrong_password(mailbox: imap_server.Store, client: TestClient) -> None:
    set_up(int(settings_port()), "falsch")
    answer = api_test(client)
    assert answer.status_code == 502 and answer.json()["detail"]["code"] == "mail_login_failed"
    last = client.get("/api/v1/settings/intake").json()["mail"]["last"]
    assert last["at"] is None and last["ok"] is True, "a test is no run"
    with pytest.raises(intake_mail.MailFailure):
        intake_mail.fetch()
    last = client.get("/api/v1/settings/intake").json()["mail"]["last"]
    assert last["ok"] is False and last["code"] == "mail_login_failed"


def settings_port() -> int:
    with SessionLocal() as db:
        return int(settings_service.get(db, "mail_port"))


def test_nobody_listening(client: TestClient, operator: Account, trusted: None) -> None:
    holder, port = imap_server.refused_port()
    try:
        set_up(port, "x")
        answer = api_test(client)
    finally:
        holder.close()
    assert answer.status_code == 502 and answer.json()["detail"]["code"] == "mail_unreachable"


def test_a_server_that_says_nothing_runs_into_the_deadline(client: TestClient, operator: Account, trusted: None,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intake_mail, "STEP_SECONDS", 5.0)
    monkeypatch.setattr(intake_mail, "RUN_SECONDS", 0.5)
    listener, port = imap_server.silent_port()
    try:
        set_up(port, "x", mail_security="starttls")
        answer = api_test(client)
    finally:
        listener.close()
    assert answer.status_code == 502 and answer.json()["detail"]["code"] == "mail_timeout"


def test_a_certificate_nobody_vouches_for(store: imap_server.Store, certificate: tuple[Path, Path],
                                         client: TestClient, operator: Account) -> None:
    running = imap_server.start(store, certificate, implicit_tls=True)
    try:
        set_up(running.port, store.password)
        answer = api_test(client)
    finally:
        imap_server.stop(running)
    assert answer.status_code == 502 and answer.json()["detail"]["code"] == "mail_tls_failed"
    assert store.logins == []


def test_starttls(store: imap_server.Store, certificate: tuple[Path, Path], client: TestClient, operator: Account,
                  trusted: None) -> None:
    running = imap_server.start(store, certificate, implicit_tls=False, starttls=True)
    try:
        set_up(running.port, store.password, mail_security="starttls", mail_port=running.port)
        deliver(store, mail(sender="a@example.org", files=[PDF]))
        assert api_test(client).json() == {"mails": 1, "after": "read"}
        assert "STARTTLS" in store.commands and store.commands.index("STARTTLS") < store.commands.index("LOGIN")
    finally:
        imap_server.stop(running)


def test_starttls_that_the_server_does_not_offer_sends_no_password(store: imap_server.Store,
                                                                   certificate: tuple[Path, Path],
                                                                   client: TestClient, operator: Account,
                                                                   trusted: None) -> None:
    running = imap_server.start(store, certificate, implicit_tls=False, starttls=False)
    try:
        set_up(running.port, store.password, mail_security="starttls")
        answer = api_test(client)
    finally:
        imap_server.stop(running)
    assert answer.json()["detail"]["code"] == "mail_tls_failed"
    assert store.logins == [] and "LOGIN" not in store.commands


def test_without_tls_only_on_this_machine(store: imap_server.Store, certificate: tuple[Path, Path],
                                          client: TestClient, operator: Account, trusted: None,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    running = imap_server.start(store, certificate, implicit_tls=False)
    try:
        set_up(running.port, store.password, mail_security="none")
        assert api_test(client).json() == {"mails": 0, "after": "read"}
        # "localhost" that a resolver turns into an address elsewhere is refused before anything is said.
        monkeypatch.setattr(intake_mail, "resolver", lambda host, port: ["93.184.216.34"])
        set_up(running.port, store.password, mail_security="none", mail_host="localhost")
        answer = api_test(client)
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "mail_plain_not_local"
    finally:
        imap_server.stop(running)
    answer = client.put("/api/v1/settings/intake", json={"mail_host": "imap.example.com", "mail_security": "none"})
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "mail_plain_not_local"


def test_an_answer_larger_than_a_mail_is_refused(mailbox: imap_server.Store, client: TestClient) -> None:
    deliver(mailbox, mail(sender="a@example.org", files=[PDF]))
    mailbox.huge_literal = 10**12
    with pytest.raises(intake_mail.MailFailure) as caught:
        intake_mail.fetch()
    assert caught.value.code in ("mail_protocol", "mail_unreachable")
    assert docs() == []


def test_two_runs_at_once(mailbox: imap_server.Store, client: TestClient) -> None:
    assert intake_mail._lock.acquire(blocking=False)
    try:
        answer = client.post("/api/v1/settings/intake/mail/fetch")
        assert answer.status_code == 409 and answer.json()["detail"]["code"] == "mail_busy"
        assert api_test(client).status_code == 409
    finally:
        intake_mail._lock.release()


# --- The operator's lock and the addresses -----------------------------------------------------------------------------


def test_switched_off_nothing_connects(mailbox: imap_server.Store, client: TestClient) -> None:
    deliver(mailbox, mail(sender="a@example.org", files=[PDF]))
    with SessionLocal() as db:
        settings_service.save(db, {"mail_on": False})
    for path in ("/api/v1/settings/intake/mail/test", "/api/v1/settings/intake/mail/fetch"):
        answer = client.post(path)
        assert answer.status_code == 409 and answer.json()["detail"]["code"] == "mailbox_off"
    from app.services import intake

    intake._mail_round()
    assert mailbox.connections == 0 and docs() == []


@pytest.mark.parametrize(("address", "private", "code"), [
    ("169.254.169.254", True, "mail_address_refused"),
    ("fd00:ec2::254", True, "mail_address_refused"),
    ("64:ff9b::a9fe:a9fe", True, "mail_address_refused"),
    ("100.100.100.200", True, "mail_address_refused"),
    ("fe80::1", True, "mail_address_refused"),
    ("10.0.0.5", False, "mail_address_private"),
    ("192.168.1.20", False, "mail_address_private"),
    ("127.0.0.1", False, "mail_address_private"),
    ("::ffff:10.0.0.5", False, "mail_address_private"),
])
def test_addresses_that_are_never_reached(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch,
                                          address: str, private: bool, code: str) -> None:
    looked: list[str] = []

    def resolve(host: str, port: int) -> list[str]:
        looked.append(host)
        return [address]

    monkeypatch.setattr(intake_mail, "resolver", resolve)
    set_up(993, "x", mail_host="imap.example.com", mail_private=private)
    answer = api_test(client)
    assert looked == ["imap.example.com"]
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == code, answer.text


def test_one_bad_address_among_good_ones_is_enough_to_refuse(client: TestClient, operator: Account,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intake_mail, "resolver", lambda host, port: ["93.184.216.34", "169.254.169.254"])
    set_up(993, "x", mail_host="imap.example.com")
    assert api_test(client).json()["detail"]["code"] == "mail_address_refused"


# --- The settings ------------------------------------------------------------------------------------------------------


def test_the_password_is_never_given_back_and_goes_only_to_its_server(client: TestClient, operator: Account) -> None:
    secret = secrets.token_urlsafe(16)
    answer = client.put("/api/v1/settings/intake", json={
        "mail_on": True, "mail_host": "imap.example.com", "mail_port": 993, "mail_user": "paper@example.com",
        "mail_password": secret, "mail_address": "paper@example.com", "mail_after": "move"})
    assert answer.status_code == 200, answer.text
    assert secret not in answer.text and answer.json()["mail"]["password_set"] is True
    with SessionLocal() as db:
        stored = settings_service.get(db, "mail_password_enc")
    assert stored and secret not in stored
    # The user changes: the password stays.
    body = client.put("/api/v1/settings/intake", json={"mail_user": "anders@example.com"}).json()
    assert body["mail"]["password_set"] is True
    # The server changes without a new password: it is forgotten.
    body = client.put("/api/v1/settings/intake", json={"mail_host": "imap.example.org"}).json()
    assert body["mail"]["password_set"] is False
    client.put("/api/v1/settings/intake", json={"mail_password": secret})
    body = client.put("/api/v1/settings/intake", json={"mail_port": 143, "mail_security": "starttls"}).json()
    assert body["mail"]["password_set"] is False


@pytest.mark.parametrize(("field", "value", "code"), [
    ("mail_host", "imap.example.com/x", "mail_host_invalid"),
    ("mail_host", "https://imap.example.com", "mail_host_invalid"),
    ("mail_host", "a" * 70 + ".example.com", "mail_host_invalid"),
    ("mail_folder", "Ordner\nmit Zeile", "mail_folder_invalid"),
    ("mail_folder", "", "mail_folder_invalid"),
    ("mail_address", "kein-at", "invalid_email"),
])
def test_what_is_not_valid(client: TestClient, operator: Account, field: str, value: str, code: str) -> None:
    answer = client.put("/api/v1/settings/intake", json={field: value})
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == code


def test_a_member_and_a_device_do_not_reach_the_mailbox(client: TestClient, operator: Account,
                                                        mailbox: imap_server.Store) -> None:
    with new_client(make_account("jule")) as member:
        for method, path in (("GET", "/api/v1/settings/intake"), ("POST", "/api/v1/settings/intake/mail/test"),
                             ("POST", "/api/v1/settings/intake/mail/fetch")):
            assert member.request(method, path).status_code == 403
    token = client.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with TestClient(client.app, base_url="http://testserver") as device:
        answer = device.post("/api/v1/settings/intake/mail/fetch", headers={"Authorization": f"Bearer {token}"})
        assert answer.status_code == 403 and answer.json()["detail"]["code"] == "browser_only"
    assert mailbox.connections == 0


def test_the_details_of_the_origin_only_for_the_owner_and_the_managers(mailbox: imap_server.Store,
                                                                       operator: Account) -> None:
    from .papers import shared_vault

    jule = make_account("jule")
    reader = make_account("leser")
    household = shared_vault("Haushalt", jule, (reader, "read"))
    with SessionLocal() as db:
        row = db.get(Account, jule.id)
        assert row is not None
        row.profile = {"default_vault": household}
        db.commit()
    deliver(mailbox, mail(sender="someone@example.org", to="paper+jule@example.com", subject="Vertrag", files=[PDF]))
    intake_mail.fetch()
    [document] = docs()
    assert document.vault_id == household
    with new_client(reader) as other:
        body = other.get(f"/api/v1/documents/{document.id}/origin").json()
        assert body["source"] == "mail" and body["sender"] == "" and body["subject"] == "" and body["file"] == ""
    with new_client(jule) as owner:
        assert owner.get(f"/api/v1/documents/{document.id}/origin").json()["subject"] == "Vertrag"


def test_a_restart_with_a_mail_without_message_id_takes_nothing_twice(mailbox: imap_server.Store, operator: Account,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    message = mail(sender="a@example.org", files=[PDF])
    del message["Message-ID"]
    deliver(mailbox, message)
    real = intake_mail._after

    def stops(*args: Any) -> None:
        raise RuntimeError("stopped")

    monkeypatch.setattr(intake_mail, "_after", stops)
    with pytest.raises(intake_mail.MailFailure):
        intake_mail.fetch()
    monkeypatch.setattr(intake_mail, "_after", real)
    done = intake_mail.fetch()
    assert done.files == 0 and len(docs()) == 1
