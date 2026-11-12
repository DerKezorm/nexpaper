# ruff: noqa: F811 - the fixtures of the mailbox come from test_intake_mail
"""The text of a mail as a document (Settings, Inputs, Mailbox, "Mails ohne Anhang als Dokument nehmen"), against the
test mailbox (``imap_server.py``) with made-up mails: off changes nothing; on, a mail without any attachment from a
confirmed address of a person, with the trusted server's ``dmarc=pass``, becomes a PDF of its text in that person's
inbox; never for a stranger, never through the plus address alone, never without the verdict, never for a mail with an
attachment (taken or not); at most a number a day; HTML is read from its markup only (nothing is fetched: a port on
127.0.0.1 listens and hears nothing), deep or very long text has its limits, broken character sets and a hostile head
are made plain, and the same mail twice is one document."""

from __future__ import annotations

import base64
import socket
import threading
import time
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import clock, mail_sheet, mail_worker
from app.db import SessionLocal
from app.models import Account, Document, Event, IntakeItem, Version, VersionText
from app.services import intake_mail, mail_text, processing, settings_service, storage

from . import imap_server
from .conftest import make_account, new_client
from .intake import device_token, process_all
from .test_intake_mail import (  # noqa: F401 - fixtures
    PDF,
    certificate,
    confirmed_sender,
    deliver,
    docs,
    items,
    mail,
    mailbox,
    server,
    set_up,
    store,
    trusted,
)

SEEN = "\\Seen"
#: Characters that turn text around or hide (written as numbers: the source stays plain).
RLO, PDF_MARK, ZWSP = chr(0x202E), chr(0x202C), chr(0x200B)
BODY = ("Hallo Tom,\n\nvielen Dank für Ihre Bestellung 4711-2026 vom 28.10.2026 bei Gartenbedarf Lindenau.\n"
        "Lieferung: Mittwoch, 04.11.2026\nSumme: 129,90 EUR\n\nViele Grüße\nIhr Team")
#: The verdict the trusted server (the domain of the mailbox, example.com) writes for a genuine mail of Tom.
PASS = ("example.com; spf=pass smtp.mailfrom=example.com; dkim=pass header.d=example.com; "
        "dmarc=pass (p=none dis=none) header.from=example.com")


def text_on(on: bool = True) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"mail_text": on})


def last() -> dict[str, Any]:
    with SessionLocal() as db:
        return dict(settings_service.get(db, "mail_last") or {})


def text_of(document_id: int) -> str:
    with SessionLocal() as db:
        version = db.scalar(select(Version).where(Version.document_id == document_id, Version.n == 1))
        assert version is not None
        row = db.get(VersionText, version.id)
        return row.text if row is not None else ""


def pdf_text(document_id: int) -> str:
    import pypdfium2

    path = storage.safe_path(text_and_version(document_id).original_path)
    pdf = pypdfium2.PdfDocument(str(path))
    try:
        return "\n".join(pdf[n].get_textpage().get_text_bounded() for n in range(len(pdf)))
    finally:
        pdf.close()


def text_and_version(document_id: int) -> Version:
    with SessionLocal() as db:
        version = db.scalar(select(Version).where(Version.document_id == document_id, Version.n == 1))
        assert version is not None
        db.expunge(version)
        return version


def plain_mail(sender: str = "tom.privat@example.com", to: str = "paper@example.com", subject: str = "WG: Bestellung",
               body: str = BODY, date: str = "Tue, 03 Nov 2026 10:15:00 +0100", message_id: str | None = None,
               auth: str | None = PASS) -> EmailMessage:
    message = mail(sender=sender, to=to, subject=subject, text=body, message_id=message_id)
    message["Date"] = date
    if auth is not None:
        message["Authentication-Results"] = auth
    return message


def html_mail(markup: str, sender: str = "tom.privat@example.com", subject: str = "Fwd: Buchung",
              auth: str | None = PASS) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "paper@example.com"
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain="example.com")
    if auth is not None:
        message["Authentication-Results"] = auth
    message.set_content(markup, subtype="html")
    return message


def raw_mail(head: str, body: bytes, charset: str = "utf-8") -> bytes:
    """A mail written by hand (for heads and character sets the library would not write), from Tom, with the verdict."""
    return (f"From: tom.privat@example.com\r\nTo: paper@example.com\r\nAuthentication-Results: {PASS}\r\n{head}"
            f"MIME-Version: 1.0\r\nContent-Type: text/plain; charset=\"{charset}\"\r\n"
            "Content-Transfer-Encoding: 8bit\r\n\r\n").encode() + body + b"\r\n"


@pytest.fixture
def tom(mailbox: imap_server.Store) -> Account:
    made = make_account("tom")
    confirmed_sender(made, "tom.privat@example.com")
    return made


def untouched(store: imap_server.Store) -> bool:
    return all(m.flags == set() for m in store.inbox().mails)


# --- Off and on -------------------------------------------------------------------------------------------------------


def test_off_from_the_start_and_off_changes_nothing(mailbox: imap_server.Store, tom: Account, client: TestClient,
                                                    operator: Account) -> None:
    assert client.get("/api/v1/settings/intake").json()["mail"]["text"] is False
    deliver(mailbox, plain_mail())
    done = intake_mail.fetch()
    assert (done.mails, done.files, done.texts) == (0, 0, 0) and docs() == [] and items() == []
    assert untouched(mailbox), "left as it was, as before"


def test_on_the_text_of_a_mail_of_a_confirmed_sender_becomes_a_document(mailbox: imap_server.Store, tom: Account,
                                                                       client: TestClient, operator: Account,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.put("/api/v1/settings/intake", json={"mail_text": True}).json()["mail"]["text"] is True
    deliver(mailbox, plain_mail())
    done = intake_mail.fetch()
    assert (done.mails, done.files, done.texts, done.unknown) == (1, 1, 1, 0)
    [document] = docs()
    assert document.owner_id == tom.id and document.source == "mail" and document.title == "Bestellung"
    assert str(document.date) == "2026-11-03"
    [item] = items()
    assert item.key.endswith(":text") and item.unknown is False and item.detail["text"] is True
    assert SEEN in mailbox.inbox().mails[0].flags, "afterwards like a mail whose attachment was taken"
    assert last()["texts"] == 1
    assert client.get("/api/v1/settings/intake").json()["mail"]["last"]["texts"] == 1
    asked: list[str] = []
    spawn = processing.spawn
    monkeypatch.setattr(processing, "spawn", lambda request, timeout: asked.append(request["op"]) or spawn(request,
                                                                                                           timeout))
    process_all()
    assert "recognize" not in asked and "blanks" not in asked, "its text is the mail's, nothing is recognised"
    with SessionLocal() as db:
        row = db.get(Document, document.id)
        assert row is not None and row.status == "inbox" and row.process_error == "" and row.pages == 1
        assert str(row.date) == "2026-11-03", "the date of the mail, not one from its text"
        # Proposals made anew (a rule, the AI) with another date in the text leave the mail's date.
        from app.services import sorting

        sorting.propose(db, row, "Rechnungsdatum: 28.10.2026")
        db.commit()
        assert str(row.date) == "2026-11-03"
        created = db.scalar(select(Event).where(Event.document_id == document.id, Event.action == "created"))
        assert created is not None and created.detail == {"mail_text": True, "source": "mail"}
    text = text_of(document.id)
    assert "Bestellung 4711-2026 vom 28.10.2026 bei Gartenbedarf Lindenau." in text and "Viele Grüße\nIhr Team" in text
    assert text.startswith("Von: tom.privat@example.com\nAn: paper@example.com\nBetreff: WG: Bestellung\nDatum: 2026-11-03")
    found = client.get("/api/v1/search", params={"q": "Gartenbedarf"})
    assert found.status_code == 200 and found.json()["items"] == [], "the operator does not see Tom's document"
    with new_client(tom) as as_tom:
        hits = as_tom.get("/api/v1/search", params={"q": "Gartenbedarf"}).json()["items"]
        assert [hit["document"]["id"] for hit in hits] == [document.id]
        assert as_tom.get(f"/api/v1/documents/{document.id}").json()["amount"] == 12990, "proposals read its text"


def test_the_pdf_shows_the_head_and_the_text(mailbox: imap_server.Store, tom: Account) -> None:
    text_on()
    deliver(mailbox, plain_mail(subject="AW: Fwd: Ihre Buchung"))
    intake_mail.fetch()
    [document] = docs()
    assert document.title == "Ihre Buchung"
    shown = pdf_text(document.id)
    for wanted in ("Von", "tom.privat@example.com", "An", "Betreff", "Datum", "2026-11-03 10:15 +01:00",
                   "Gartenbedarf Lindenau", "Seite 1 von 1"):
        assert wanted in shown, wanted


def test_the_own_plus_address_is_fine(mailbox: imap_server.Store, tom: Account) -> None:
    text_on()
    deliver(mailbox, plain_mail(to="paper+tom@example.com"))
    assert intake_mail.fetch().texts == 1
    assert [d.owner_id for d in docs()] == [tom.id]


# --- Whose -----------------------------------------------------------------------------------------------------------


def test_the_plus_address_alone_is_never_enough(mailbox: imap_server.Store, tom: Account, operator: Account) -> None:
    """Probe p01 of the review: a stranger writes to paper+tom (even with a verdict for his own domain)."""
    text_on()
    deliver(mailbox, plain_mail(sender="spam@example.org", to="paper+tom@example.com", subject="Gewinnspiel",
                                auth="example.com; dmarc=pass header.from=example.org"))
    deliver(mailbox, plain_mail(sender="spam@example.org", to="paper+tom@example.com", auth=None))
    done = intake_mail.fetch()
    assert (done.files, done.texts) == (0, 0) and docs() == [] and items() == []
    assert untouched(mailbox), "left in the mailbox, as with the switch off"


@pytest.mark.parametrize("header", ["Cc", "Delivered-To", "X-Original-To", "Envelope-To", "X-Forwarded-To"])
def test_a_plus_address_in_any_other_header_gives_nothing(mailbox: imap_server.Store, tom: Account,
                                                          header: str) -> None:
    """Probe p02: the plus address written into a header by the sender himself."""
    text_on()
    message = plain_mail(sender="spam@example.org", to="paper@example.com",
                         auth="example.com; dmarc=pass header.from=example.org")
    message[header] = "paper+tom@example.com"
    deliver(mailbox, message)
    done = intake_mail.fetch()
    assert (done.files, done.texts) == (0, 0) and docs() == []


def test_a_confirmed_sender_does_not_fill_somebody_elses_inbox(mailbox: imap_server.Store, tom: Account) -> None:
    """Probe p06: Tom, genuine, writes to paper+lea."""
    make_account("lea")
    text_on()
    deliver(mailbox, plain_mail(to="paper+lea@example.com"))
    deliver(mailbox, plain_mail(to="paper+tom@example.com, paper+lea@example.com"))
    done = intake_mail.fetch()
    assert (done.files, done.texts) == (0, 0) and docs() == []
    assert untouched(mailbox)


def test_never_for_a_stranger_nor_an_unknown_plus_address(mailbox: imap_server.Store, tom: Account,
                                                          operator: Account) -> None:
    text_on()
    deliver(mailbox, plain_mail(sender="fremd@example.org"))
    deliver(mailbox, plain_mail(sender="fremd@example.org", to="paper+niemand@example.com"))
    deliver(mailbox, plain_mail(sender="fremd@example.org", to="paper+tom@example.com, paper+lea@example.com"))
    done = intake_mail.fetch()
    assert (done.files, done.texts) == (0, 0) and docs() == [] and items() == []
    assert untouched(mailbox), "left in the mailbox as before"


@pytest.mark.parametrize("auth", [
    None,
    "example.com; dmarc=none header.from=example.com",
    "example.com; dmarc=temperror header.from=example.com",
    "example.com; dmarc=permerror header.from=example.com",
    "example.com; spf=fail; dkim=fail; dmarc=fail (p=quarantine) header.from=example.com",
    "example.com; dmarc=pass header.from=example.org",
    "example.com; dmarc=pass",
    "example.com; spf=pass smtp.mailfrom=example.com; dkim=pass header.d=example.com",
    "mx.example.net; dmarc=pass header.from=example.com",
    "example.comx; dmarc=pass header.from=example.com",
])
def test_without_the_trusted_servers_pass_there_is_no_document(mailbox: imap_server.Store, tom: Account,
                                                              auth: str | None) -> None:
    """Probe p03: the confirmed address in From, but the trusted server did not say pass for its domain."""
    text_on()
    deliver(mailbox, plain_mail(auth=auth))
    done = intake_mail.fetch()
    assert (done.files, done.texts) == (0, 0) and docs() == []
    assert untouched(mailbox), "as with the switch off"


def test_a_pass_of_the_senders_own_beside_the_real_verdict_does_not_help(mailbox: imap_server.Store,
                                                                         tom: Account) -> None:
    text_on()
    message = plain_mail(auth="example.com; dmarc=none header.from=example.com")
    for _ in range(3):
        message["Authentication-Results"] = PASS
    deliver(mailbox, message)
    assert intake_mail.fetch().texts == 0 and docs() == []


def test_only_the_trusted_servers_verdict_counts(mailbox: imap_server.Store, tom: Account) -> None:
    """X8: another server's verdict beside the trusted one changes nothing, in either direction."""
    text_on()
    message = plain_mail(auth="mx.example.net; dmarc=fail header.from=example.com")
    message["Authentication-Results"] = PASS
    deliver(mailbox, message)
    assert intake_mail.fetch().texts == 1
    mailbox_name = "paper@example.com"
    assert intake_mail.failed_check(["mx.example.net; dmarc=pass", "example.com; dmarc=fail"], mailbox_name)
    assert not intake_mail.failed_check(["mx.example.net; dmarc=fail", "example.com; dmarc=pass"], mailbox_name)
    sender = "tom.privat@example.com"
    assert intake_mail.passed_check(["mx.example.net; dmarc=fail", PASS], mailbox_name, sender)
    assert not intake_mail.passed_check(["mx.example.net; dmarc=pass header.from=example.com"], mailbox_name, sender)
    assert intake_mail.passed_check(["mx.example.com; dmarc=pass header.from=example.com"], mailbox_name, sender)
    assert intake_mail.passed_check(["mx.trusted.example; dmarc=pass header.from=example.com"], mailbox_name, sender,
                                    "trusted.example")
    assert not intake_mail.passed_check([PASS], "", sender), "no mailbox and no trusted server: no verdict"


@pytest.mark.parametrize("head", ["From: tom.privat@example.com, evil@example.org\r\n",
                                  "From: evil@example.org\r\nFrom: tom.privat@example.com\r\n",
                                  "From: tom.privat@example.com\r\nFrom: evil@example.org\r\n"])
def test_exactly_one_address_in_from(mailbox: imap_server.Store, tom: Account, head: str) -> None:
    text_on()
    raw = (head + f"To: paper@example.com\r\nAuthentication-Results: {PASS}\r\nSubject: zwei\r\nMIME-Version: 1.0\r\n"
           "Content-Type: text/plain; charset=utf-8\r\n\r\n" + BODY + "\r\n").encode()
    deliver(mailbox, raw)
    assert intake_mail.fetch().texts == 0 and docs() == []


def test_a_blocked_account_gets_nothing(mailbox: imap_server.Store, tom: Account, operator: Account) -> None:
    """X11: a blocked account gets no text from its own address, and attachments to its plus address go to the
    operator, marked unknown."""
    lea = make_account("lea")
    confirmed_sender(lea, "lea@example.com")
    with SessionLocal() as db:
        row = db.get(Account, lea.id)
        assert row is not None
        row.blocked_at = clock.now()
        db.commit()
    text_on()
    deliver(mailbox, plain_mail(sender="lea@example.com", auth=PASS))
    assert intake_mail.fetch().texts == 0 and docs() == []
    deliver(mailbox, mail(sender="spam@example.org", to="paper+lea@example.com", files=[PDF]))
    intake_mail.fetch()
    [document] = docs()
    assert document.owner_id == operator.id
    assert [i.unknown for i in items()] == [True]


def test_at_most_a_number_of_texts_a_day_per_person(mailbox: imap_server.Store, tom: Account,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """Probe p16, with the limit set low; the rest waits for the next day."""
    assert mail_text.PERSON_DAY_TEXTS == 50
    monkeypatch.setattr(mail_text, "PERSON_DAY_TEXTS", 2)
    text_on()
    for n in range(3):
        deliver(mailbox, plain_mail(subject=f"Bestellung {n}", body=f"{BODY}\nNummer {n}"))
    done = intake_mail.fetch()
    assert (done.texts, done.deferred) == (2, 1) and len(docs()) == 2
    assert mailbox.inbox().mails[2].flags == set(), "the third one waits"
    with SessionLocal() as db:
        assert settings_service.get(db, "mail_budget")["texts"] == {str(tom.id): 2}


# --- With an attachment ---------------------------------------------------------------------------------------------


def test_a_mail_with_an_attachment_taken_stays_as_it_was(mailbox: imap_server.Store, tom: Account) -> None:
    text_on()
    deliver(mailbox, mail(files=[PDF], text=BODY))
    done = intake_mail.fetch()
    assert (done.files, done.texts) == (1, 0)
    [item] = items()
    assert item.key.endswith(":0") and "text" not in item.detail
    assert len(docs()) == 1


def test_a_part_over_a_limit_is_no_reason_for_the_text(mailbox: imap_server.Store, tom: Account,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    text_on()
    monkeypatch.setattr(intake_mail, "MAX_ATTACHMENTS", 0)
    deliver(mailbox, mail(files=[PDF], text=BODY))
    done = intake_mail.fetch()
    assert (done.files, done.texts) == (0, 0) and docs() == []


def with_attachment(name: str, data: bytes, ctype: str) -> EmailMessage:
    message = plain_mail(subject=f"mit {name}")
    maintype, subtype = ctype.split("/")
    message.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return message


@pytest.mark.parametrize("after", ["delete", "move", "read"])
def test_a_mail_with_an_attachment_nexpaper_does_not_take_stays_as_with_the_switch_off(
        mailbox: imap_server.Store, tom: Account, after: str) -> None:
    """Probes p18 and p08: a Word file, a text file, a broken and an empty PDF. No text, the mail stays where it is,
    unmarked, whatever "afterwards" says."""
    with SessionLocal() as db:
        settings_service.save(db, {"mail_after": after})
    text_on()
    deliver(mailbox, with_attachment("Vertrag.docx", b"PK\x03\x04" + b"x" * 500,
                                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
    deliver(mailbox, with_attachment("Notiz.txt", b"Hallo " * 50, "text/plain"))
    deliver(mailbox, with_attachment("kaputt.pdf", b"not a pdf at all" * 10, "application/pdf"))
    deliver(mailbox, with_attachment("leer.pdf", b"", "application/pdf"))
    done = intake_mail.fetch()
    assert (done.files, done.texts) == (0, 0) and docs() == [] and items() == []
    assert len(mailbox.inbox().mails) == 4 and untouched(mailbox)
    assert "nexpaper" not in mailbox.folders


def test_a_small_picture_of_a_signature_is_no_attachment(mailbox: imap_server.Store, tom: Account) -> None:
    text_on()
    logo = plain_mail(subject="mit kleinem Logo")
    logo.add_related(b"\x89PNG\r\n\x1a\n" + bytes(100), maintype="image", subtype="png", cid="<logo@example.com>")
    deliver(mailbox, logo)
    assert intake_mail.fetch().texts == 1


def test_the_worker_counts_attachments() -> None:
    import email
    import email.policy

    def count(message: EmailMessage) -> int:
        parsed = email.message_from_bytes(message.as_bytes(), policy=email.policy.default)
        return mail_worker.attachments(parsed, 8, 300, intake_mail.INLINE_PICTURE_MIN)

    assert count(plain_mail()) == 0
    assert count(with_attachment("leer.pdf", b"", "application/pdf")) == 1
    assert count(with_attachment("a.docx", b"PK" * 10, "application/octet-stream")) == 1
    forwarded = plain_mail(body="siehe unten")
    forwarded.add_attachment(plain_mail())
    assert count(forwarded) == 0, "a forwarded mail is content"
    inner = with_attachment("Rechnung.pdf", PDF[1], "application/pdf")
    carrier = plain_mail(body="siehe unten")
    carrier.add_attachment(inner)
    assert count(carrier) == 1, "what a forwarded mail carries counts"


# --- HTML -------------------------------------------------------------------------------------------------------------


class Listener:
    """A port on 127.0.0.1 that counts who comes."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        for port in [*range(18790, 18799), 0]:
            try:
                self.sock.bind(("127.0.0.1", port))
                break
            except OSError:
                continue
        self.sock.listen(5)
        self.sock.settimeout(0.2)
        self.port = int(self.sock.getsockname()[1])
        self.came = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                conn, _addr = self.sock.accept()
            except OSError:
                continue
            self.came += 1
            conn.close()

    def close(self) -> None:
        self.stop.set()
        self.thread.join(2)
        self.sock.close()


def hostile_html(port: int) -> str:
    base = f"http://127.0.0.1:{port}"
    return f"""<!doctype html><html><head><title>Kopf</title>
<link rel="stylesheet" href="{base}/style.css"><style>@import url({base}/more.css);
@font-face {{ font-family: x; src: url({base}/font.woff2); }} body {{ background: url({base}/bg.png); }}</style>
<meta http-equiv="refresh" content="0; url={base}/go"><script src="{base}/app.js"></script>
<script>fetch("{base}/run"); document.write("GEHEIM-SKRIPT");</script></head>
<body background="{base}/body.png"><img src="{base}/pixel.gif" alt="Zaehlpixel"><img src="cid:logo@example.com">
<iframe src="{base}/frame"></iframe><object data="{base}/obj">Objekttext</object>
<p>Ihre Buchung <b>B-2026-118</b> ist bestätigt.</p><p>Zimmer &amp; Frühstück, 2 Nächte</p>
<form action="{base}/send" method="post"><input name="q" value="Eingabe"><button>Senden</button></form>
<p>Details: <a href="https://example.com/buchung/118">online ansehen</a>, <a href="javascript:alert(1)">Klick</a>,
<a href="mailto:hotel@example.com">hotel@example.com</a></p><ul><li>Anreise 12.11.</li><li>Abreise 14.11.</li></ul>
</body></html>"""


def test_html_is_read_from_its_markup_and_nothing_is_fetched(mailbox: imap_server.Store, tom: Account) -> None:
    text_on()
    listener = Listener()
    try:
        deliver(mailbox, html_mail(hostile_html(listener.port)))
        assert intake_mail.fetch().texts == 1
        process_all()
        time.sleep(0.5)
        assert listener.came == 0, "no picture, style sheet, font, frame or script was fetched"
    finally:
        listener.close()
    [document] = docs()
    text = text_of(document.id)
    assert "Ihre Buchung B-2026-118 ist bestätigt." in text and "Zimmer & Frühstück, 2 Nächte" in text
    assert "online ansehen (https://example.com/buchung/118)" in text
    assert "Klick" in text and "javascript" not in text and "(hotel@example.com)" not in text
    assert "- Anreise 12.11.\n- Abreise 14.11." in text
    for never in ("GEHEIM-SKRIPT", "fetch(", "Kopf", "font-face", "Zaehlpixel", "cid:", "127.0.0.1", "Objekttext",
                  "Eingabe"):
        assert never not in text, never


def test_svg_math_select_and_text_areas_are_left_out() -> None:
    """X7."""
    for tag in ("svg", "math", "select", "textarea", "script", "style", "title", "template", "noscript", "object"):
        text = mail_worker.html_text(f"<p>davor</p><{tag}>VERBORGEN-{tag}</{tag}><p>danach</p>", 10_000)
        assert "davor" in text and "danach" in text and "VERBORGEN" not in text, tag


def test_a_link_address_is_written_only_up_to_its_limit() -> None:
    """X14."""
    long = "https://example.com/" + "a" * 600
    text = mail_worker.html_text(f'<p><a href="{long}">lang</a> <a href="https://example.com/kurz">kurz</a></p>',
                                 10_000)
    assert "lang" in text and "a" * 100 not in text
    assert "kurz (https://example.com/kurz)" in text
    exact = "https://example.com/" + "b" * (500 - len("https://example.com/"))
    assert f"({exact})" in mail_worker.html_text(f'<a href="{exact}">x</a>', 10_000)


def test_the_text_part_wins_over_the_html_part(mailbox: imap_server.Store, tom: Account) -> None:
    text_on()
    message = plain_mail(body="Die schlichte Fassung dieser Mail, lang genug.")
    message.add_alternative("<p>Die HTML-Fassung</p>", subtype="html")
    deliver(mailbox, message)
    intake_mail.fetch()
    [document] = docs()
    assert "Die schlichte Fassung" in text_of(document.id) and "HTML-Fassung" not in text_of(document.id)


def test_a_forwarded_mail_is_the_content_and_nothing_is_cut_away(mailbox: imap_server.Store, tom: Account) -> None:
    text_on()
    inner = plain_mail(sender="shop@example.org", to="tom.privat@example.com", subject="Bestellbestätigung",
                       auth=None)
    outer = plain_mail(subject="Fwd: Bestellbestätigung", body="siehe unten")
    outer.add_attachment(inner)
    deliver(mailbox, outer)
    assert intake_mail.fetch().texts == 1
    [document] = docs()
    text = text_of(document.id)
    assert document.title == "Bestellbestätigung"
    assert "siehe unten" in text and "Weitergeleitete Mail:\nVon: shop@example.org" in text
    assert "Bestellung 4711-2026" in text


# --- Limits -----------------------------------------------------------------------------------------------------------


def test_deeply_nested_html_is_read_within_the_limits(mailbox: imap_server.Store, tom: Account) -> None:
    text_on()
    deep = "<div><span><table><tr><td>" * 20_000 + "Tief unten steht der Text der Mail." + "</td></tr></table>" * 50
    deliver(mailbox, html_mail(deep))
    started = time.monotonic()
    assert intake_mail.fetch().texts == 1
    assert time.monotonic() - started < intake_mail.WORKER_SECONDS * 2 + 10
    [document] = docs()
    assert "Tief unten steht der Text der Mail." in text_of(document.id)


def test_a_text_over_200_kb_is_cut_and_says_so_in_its_last_line(mailbox: imap_server.Store, tom: Account,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    text_on()
    line = "Zeile mit etwas Text, die sich oft wiederholt, damit die Mail groß wird. "
    deliver(mailbox, plain_mail(body="\n".join(f"{n:05d} {line}" for n in range(4000))))
    assert intake_mail.fetch().texts == 1
    [document] = docs()
    text = text_of(document.id)
    assert text.rstrip().endswith(mail_sheet.LABELS["de"]["cut"])
    assert len(text.encode("utf-8")) <= 200 * 1024 + 2048
    assert "00000 Zeile" in text and "03999 Zeile" not in text
    asked: list[str] = []
    spawn = processing.spawn
    monkeypatch.setattr(processing, "spawn", lambda request, timeout: asked.append(request["op"]) or spawn(request,
                                                                                                           timeout))
    process_all()
    assert "recognize" not in asked and "blanks" not in asked, "a page of a mail is never a separator sheet"
    with SessionLocal() as db:
        row = db.get(Document, document.id)
        assert row is not None and row.status == "inbox" and 1 < row.pages <= 200


def test_the_pdf_stops_at_200_pages_and_says_so(tmp_path: Any) -> None:
    """X13: a text of very many short lines, against the number itself."""
    made = mail_sheet.write({"from": "a@example.com", "subject": "lang"}, "\n".join("z" for _ in range(30_000)),
                            tmp_path / "lang.pdf", "de")
    assert made["pages"] == 200 and made["cut"] is True and len(made["texts"]) == 200
    assert made["texts"][-1].endswith(mail_sheet.LABELS["de"]["cut"])


def test_one_text_part_is_read_up_to_4_mb() -> None:
    """X9."""
    from email.message import Message

    part = Message()
    part.set_payload(b"a" * (5 * 1024 * 1024))
    part.set_type("text/plain")
    part.set_param("charset", "utf-8")
    assert len(mail_worker.decoded(part)) == 4 * 1024 * 1024


def test_only_common_character_sets_are_used() -> None:
    """N2: punycode and its kin are read as UTF-8, and fast."""
    from email.message import Message

    for name in ("punycode", "idna", "utf-7", "rot13", "base64", "unicode_escape", "x-unknown"):
        assert mail_worker.charset_of(name) is None, name
    for name in ("UTF-8", "us-ascii", "ISO-8859-15", "windows-1252", "latin1", "utf-16", "shift_jis", "gb18030"):
        assert mail_worker.charset_of(name) is not None, name
    part = Message()
    part.set_payload(("ä" * 2_000_000).encode("utf-8"))
    part.set_type("text/plain")
    part.set_param("charset", "punycode")
    started = time.monotonic()
    assert mail_worker.decoded(part).startswith("ää")
    assert time.monotonic() - started < 3


def test_a_mail_whose_text_takes_too_long_is_skipped_and_left_alone(mailbox: imap_server.Store, tom: Account,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    text_on()
    deliver(mailbox, plain_mail())
    real = intake_mail._work

    def slow(raw: bytes, folder: Any, request: dict[str, Any]) -> Any:
        if request.get("op") == "text":
            monkeypatch.setattr(intake_mail, "WORKER_SECONDS", 0.001)
        return real(raw, folder, request)

    monkeypatch.setattr(intake_mail, "_work", slow)
    done = intake_mail.fetch()
    assert (done.skipped, done.files) == (1, 0) and docs() == []
    assert untouched(mailbox)


def test_broken_character_sets_are_read_as_well_as_they_go(mailbox: imap_server.Store, tom: Account) -> None:
    text_on()
    body = "Grüße aus Lindenau, die Rechnung folgt per Post. Größe: 42 m²".encode()
    for charset in ("x-unknown-8bit", "base64", "us-ascii", "utf-8", "punycode"):
        deliver(mailbox, raw_mail(f"Subject: Zeichensatz {charset}\r\nMessage-ID: <{charset}@example.com>\r\n", body,
                                  charset))
    deliver(mailbox, raw_mail("Subject: kaputt\r\n", b"Halb kaputt \xff\xfe aber genug Text darin."))
    assert intake_mail.fetch().texts == 6
    texts = [text_of(d.id) for d in docs()]
    for text in texts[:5]:
        assert "Grüße aus Lindenau" in text
    assert "Halb kaputt" in texts[5] and "aber genug Text darin." in texts[5]


@pytest.mark.parametrize("markup", ["<p><img src=\"cid:a@example.com\"><img src=\"https://example.com/b.png\"></p>",
                                    "<p>Gruß, Tom</p>", "<p>   </p>"])
def test_pictures_only_or_a_short_signature_is_no_document(mailbox: imap_server.Store, tom: Account,
                                                           markup: str) -> None:
    text_on()
    deliver(mailbox, html_mail(markup))
    done = intake_mail.fetch()
    assert (done.files, done.texts) == (0, 0) and docs() == []


def encoded(text: str) -> str:
    return "=?utf-8?b?" + base64.b64encode(text.encode()).decode() + "?="


def test_a_subject_with_line_breaks_and_direction_characters_is_made_plain(mailbox: imap_server.Store,
                                                                           tom: Account) -> None:
    text_on()
    subject = encoded(f"WG: Rechnung\n{RLO}fdp.exe{PDF_MARK}\r\nX-Injected: 1{ZWSP}")
    deliver(mailbox, raw_mail(f"Subject: {subject}\r\nMessage-ID: <subject@example.com>\r\n", BODY.encode()))
    assert intake_mail.fetch().texts == 1
    [document] = docs()
    assert document.title == "Rechnung fdp.exe X-Injected: 1"
    text = text_of(document.id)
    assert RLO not in text and ZWSP not in text
    assert "Betreff: WG: Rechnung fdp.exe X-Injected: 1\n" in text


def test_from_and_to_are_made_plain_in_the_pdf_and_the_text(mailbox: imap_server.Store, tom: Account) -> None:
    """X2 and X3: the names in From and To with line breaks and direction characters."""
    text_on()
    # A name in From that carries a line break names no address at all (no document); here it carries the rest.
    sender = encoded(f"Tom{RLO}Privat{ZWSP} X-Evil: 1") + " <tom.privat@example.com>"
    to = encoded(f"Ablage{ZWSP} X-To: 2{RLO}") + " <paper@example.com>"
    raw = (f"From: {sender}\r\nTo: {to}\r\nAuthentication-Results: {PASS}\r\nSubject: Kopf\r\n"
           "Date: Tue, 03 Nov 2026 10:15:00 +0100\r\n"
           "MIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n" + BODY + "\r\n").encode()
    deliver(mailbox, raw)
    assert intake_mail.fetch().texts == 1
    [document] = docs()
    head = text_of(document.id).split("\n\n", 1)[0].split("\n")
    assert [line.split(":", 1)[0] for line in head] == ["Von", "An", "Betreff", "Datum"], "one line each"
    assert "TomPrivat X-Evil: 1" in head[0] and head[0].endswith("<tom.privat@example.com>")
    assert "Ablage X-To: 2" in head[1] and head[1].endswith("<paper@example.com>")
    for char in (RLO, ZWSP):
        assert char not in head[0] and char not in head[1]
    shown = pdf_text(document.id)
    for char in (RLO, ZWSP):
        assert char not in shown
    assert "TomPrivat X-Evil: 1" in shown and "Ablage X-To: 2" in shown


def test_a_long_head_is_cut(mailbox: imap_server.Store, tom: Account) -> None:
    text_on()
    message = plain_mail(subject="S" * 900)
    message.replace_header("To", ", ".join(f"empf{n}@example.com" for n in range(60)))
    deliver(mailbox, message)
    assert intake_mail.fetch().texts == 1
    [document] = docs()
    assert len(document.title) <= 200
    head = text_of(document.id).split("\n\n", 1)[0]
    assert all(len(line) <= 410 for line in head.split("\n")), "a head field is cut at a few hundred characters"
    assert head.split("\n")[1].startswith("An: empf0@example.com, ")


def test_a_head_field_takes_at_most_four_lines_in_the_pdf(tmp_path: Any) -> None:
    """X16: the PDF cuts a long field after four lines and says so with dots."""
    to = ", ".join(f"empf{n}@example.com" for n in range(19))
    made = mail_sheet.write({"from": "a@example.com", "to": to, "subject": "s"}, "Text der Mail, lang genug.",
                            tmp_path / "kopf.pdf", "de")
    assert made["pages"] == 1
    import pypdfium2

    pdf = pypdfium2.PdfDocument(str(tmp_path / "kopf.pdf"))
    try:
        shown = pdf[0].get_textpage().get_text_bounded()
    finally:
        pdf.close()
    assert "empf0@example.com" in shown and "..." in shown
    assert "empf18@example.com" not in shown, "the fifth line and after are left out"
    assert "empf18@example.com" in made["texts"][0], "the text of the document keeps the whole field"


def test_a_subject_of_nothing_visible_gives_the_date_as_title(mailbox: imap_server.Store, tom: Account) -> None:
    """N1: once, no 422, no three tries."""
    text_on()
    for subject, message_id in ((encoded(RLO), "<rlo@example.com>"), (encoded(ZWSP * 2), "<zw@example.com>")):
        deliver(mailbox, raw_mail(f"Subject: {subject}\r\nDate: Tue, 03 Nov 2026 10:15:00 +0100\r\n"
                                  f"Message-ID: {message_id}\r\n", BODY.encode()))
    done = intake_mail.fetch()
    assert done.texts == 2
    assert [d.title for d in docs()] == ["Mail vom 03.11.2026", "Mail vom 03.11.2026"]
    assert all(SEEN in m.flags for m in mailbox.inbox().mails)
    with SessionLocal() as db:
        assert settings_service.get(db, "mail_state")["retry"] == {}


@pytest.mark.parametrize(("subject", "title"), [("WG: AW: Fwd: Rechnung", "Rechnung"), ("Re[2]: Termin", "Termin"),
                                                ("FW: ", "Mail vom 03.11.2026"), ("Wegweiser", "Wegweiser"),
                                                ("", "Mail vom 03.11.2026")])
def test_the_title_is_the_subject_without_what_forwarding_puts_in_front(subject: str, title: str) -> None:
    from datetime import date

    assert mail_text.title_of(subject, "de", date(2026, 11, 3)) == title
    assert mail_text.title_of("", "en", date(2026, 11, 3)) == "Mail of 2026-11-03"
    for nothing in (RLO, ZWSP * 2, chr(0x2060) * 3, "WG: " + chr(0xAD), " " + RLO + PDF_MARK + " "):
        assert mail_text.title_of(nothing, "de", date(2026, 11, 3)) == "Mail vom 03.11.2026", repr(nothing)


def test_the_date_of_the_mail_has_its_years() -> None:
    """X4."""
    import email
    import email.policy

    def date_of(value: str) -> tuple[str, str]:
        message = email.message_from_bytes(f"Date: {value}\r\n\r\nx".encode(), policy=email.policy.default)
        return mail_worker.mail_date(message)

    assert date_of("Tue, 03 Nov 2026 10:15:00 +0100") == ("2026-11-03", "2026-11-03 10:15 +01:00")
    assert date_of("Wed, 01 Jan 2100 00:00:00 +0000")[0] == "2100-01-01"
    for outside in ("Sat, 01 Jan 2101 00:00:00 +0000", "Wed, 31 Dec 1969 12:00:00 +0000", "Unsinn"):
        assert date_of(outside) == ("", ""), outside


def test_the_same_mail_twice_is_one_document(mailbox: imap_server.Store, tom: Account) -> None:
    text_on()
    message = plain_mail(message_id="<twice@example.com>")
    deliver(mailbox, message)
    deliver(mailbox, message)
    done = intake_mail.fetch()
    assert (done.mails, done.files) == (2, 1) and len(docs()) == 1
    assert all(SEEN in m.flags for m in mailbox.inbox().mails), "both are done"
    again = intake_mail.fetch()
    assert again.files == 0 and len(docs()) == 1


def test_the_daily_amount_of_a_person_counts_the_text_too(mailbox: imap_server.Store, tom: Account,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    text_on()
    monkeypatch.setattr(intake_mail, "PERSON_DAY_BYTES", 10)
    deliver(mailbox, plain_mail())
    done = intake_mail.fetch()
    assert (done.deferred, done.files) == (1, 0) and docs() == []


# --- The switch and the reading -----------------------------------------------------------------------------------------


def test_only_the_operator_in_a_browser_changes_the_switch(client: TestClient, operator: Account) -> None:
    member = make_account("lea")
    with new_client(member) as lea:
        assert lea.put("/api/v1/settings/intake", json={"mail_text": True}).status_code == 403
    token = device_token(client)
    with TestClient(client.app, base_url="http://testserver") as bare:
        sent = bare.put("/api/v1/settings/intake", json={"mail_text": True},
                        headers={"Authorization": f"Bearer {token}"})
        assert sent.status_code in (401, 403)
    assert client.put("/api/v1/settings/intake", json={"mail_text": "yes"}).status_code == 422
    with SessionLocal() as db:
        assert settings_service.get(db, "mail_text") is False


def test_a_document_of_an_attachment_is_read_as_before(mailbox: imap_server.Store, tom: Account) -> None:
    """X6: a PDF from the mailbox has a text of its own after reading, but it is never taken as a mail's text."""
    text_on()
    deliver(mailbox, mail(files=[PDF]))
    intake_mail.fetch()
    process_all()
    [document] = docs()
    with SessionLocal() as db:
        row = db.get(Document, document.id)
        version = db.scalar(select(Version).where(Version.document_id == document.id))
        assert row is not None and version is not None and version.note == "mail"
        assert db.get(VersionText, version.id) is not None, "read, with a text"
        assert mail_text.given(db, row, version) is None
        assert mail_text.given_outcome(db, row, version) is None
        [item] = db.scalars(select(IntakeItem)).all()
        assert "text" not in item.detail


def test_html_breaks_lines_at_blocks_and_keeps_preformatted_text() -> None:
    text = mail_worker.html_text("<h1>Titel</h1><p>Erster<br>Zweiter</p><table><tr><td>A</td><td>B</td></tr></table>"
                                 "<pre>  eingerückt</pre>", 10_000)
    lines = [line for line in text.split("\n") if line]
    assert lines == ["Titel", "Erster", "Zweiter", "A B", "eingerückt"]


def test_tidy_takes_out_control_characters() -> None:
    dirty = "\n\na" + chr(0) + "b" + chr(27) + "c" + chr(0x85) + "d\r\ne\tf\n\n\n\ng" + RLO + "h\n\n"
    assert mail_worker.tidy(dirty) == "abcd\ne    f\n\ngh"
