# ruff: noqa: F811 - the fixtures of the mailbox come from test_intake_mail
"""The text of a mail as a document (Settings, Inputs, Mailbox, "Mails ohne Anhang als Dokument nehmen"), against the
test mailbox (``imap_server.py``) with made-up mails: off changes nothing; on, a mail with nothing to take that belongs
to a person for sure becomes a PDF of its text in their inbox; never for a stranger, an unknown plus address or a
sender whose DMARC failed; HTML is read from its markup only (nothing is fetched: a port on 127.0.0.1 listens and hears
nothing), deep or very long text has its limits, broken character sets and a hostile subject are made plain, and the
same mail twice is one document."""

from __future__ import annotations

import socket
import threading
import time
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import mail_sheet, mail_worker
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
BODY = ("Hallo Tom,\n\nvielen Dank für Ihre Bestellung 4711-2026 bei Gartenbedarf Lindenau.\n"
        "Lieferung: Mittwoch, 04.11.2026\nSumme: 129,90 EUR\n\nViele Grüße\nIhr Team")


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


def plain_mail(sender: str = "tom.privat@example.com", to: str = "paper@example.com", subject: str = "WG: Bestellung",
               body: str = BODY, date: str = "Tue, 03 Nov 2026 10:15:00 +0100", message_id: str | None = None,
               ) -> EmailMessage:
    message = mail(sender=sender, to=to, subject=subject, text=body, message_id=message_id)
    message["Date"] = date
    return message


def html_mail(markup: str, sender: str = "tom.privat@example.com", subject: str = "Fwd: Buchung") -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "paper@example.com"
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain="example.com")
    message.set_content(markup, subtype="html")
    return message


@pytest.fixture
def tom(mailbox: imap_server.Store) -> Account:
    made = make_account("tom")
    confirmed_sender(made, "tom.privat@example.com")
    return made


# --- Off and on -------------------------------------------------------------------------------------------------------


def test_off_from_the_start_and_off_changes_nothing(mailbox: imap_server.Store, tom: Account, client: TestClient,
                                                    operator: Account) -> None:
    assert client.get("/api/v1/settings/intake").json()["mail"]["text"] is False
    deliver(mailbox, plain_mail())
    done = intake_mail.fetch()
    assert (done.mails, done.files, done.texts) == (0, 0, 0) and docs() == [] and items() == []
    assert mailbox.inbox().mails[0].flags == set(), "left as it was, as before"


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
        created = db.scalar(select(Event).where(Event.document_id == document.id, Event.action == "created"))
        assert created is not None and created.detail == {"mail_text": True, "source": "mail"}
    text = text_of(document.id)
    assert "Bestellung 4711-2026 bei Gartenbedarf Lindenau." in text and "Viele Grüße\nIhr Team" in text
    assert text.startswith("Von: tom.privat@example.com\nAn: paper@example.com\nBetreff: WG: Bestellung\nDatum: 2026-11-03")
    found = client.get("/api/v1/search", params={"q": "Gartenbedarf"})
    assert found.status_code == 200 and found.json()["items"] == [], "the operator does not see Tom's document"
    with new_client(tom) as as_tom:
        hits = as_tom.get("/api/v1/search", params={"q": "Gartenbedarf"}).json()["items"]
        assert [hit["document"]["id"] for hit in hits] == [document.id]
        assert as_tom.get(f"/api/v1/documents/{document.id}").json()["amount"] == 12990, "proposals read its text"


def test_the_pdf_shows_the_head_and_the_text(mailbox: imap_server.Store, tom: Account) -> None:
    import pypdfium2

    text_on()
    deliver(mailbox, plain_mail(subject="AW: Fwd: Ihre Buchung"))
    intake_mail.fetch()
    [document] = docs()
    assert document.title == "Ihre Buchung"
    path = storage.safe_path(text_and_version(document.id).original_path)
    pdf = pypdfium2.PdfDocument(str(path))
    try:
        page = pdf[0]
        shown = page.get_textpage().get_text_bounded()
    finally:
        pdf.close()
    for wanted in ("Von", "tom.privat@example.com", "An", "Betreff", "Datum", "2026-11-03 10:15 +01:00",
                   "Gartenbedarf Lindenau", "Seite 1 von 1"):
        assert wanted in shown, wanted


def text_and_version(document_id: int) -> Version:
    with SessionLocal() as db:
        version = db.scalar(select(Version).where(Version.document_id == document_id, Version.n == 1))
        assert version is not None
        db.expunge(version)
        return version


def test_the_plus_address_counts_too(mailbox: imap_server.Store, operator: Account) -> None:
    jule = make_account("jule")
    text_on()
    deliver(mailbox, plain_mail(sender="shop@example.org", to="paper+jule@example.com"))
    intake_mail.fetch()
    assert [d.owner_id for d in docs()] == [jule.id]


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


# --- Whose -----------------------------------------------------------------------------------------------------------


def test_never_for_a_stranger_nor_an_unknown_plus_address(mailbox: imap_server.Store, tom: Account,
                                                          operator: Account) -> None:
    text_on()
    deliver(mailbox, plain_mail(sender="fremd@example.org"))
    deliver(mailbox, plain_mail(sender="fremd@example.org", to="paper+niemand@example.com"))
    deliver(mailbox, plain_mail(sender="fremd@example.org", to="paper+tom@example.com, paper+lea@example.com"))
    done = intake_mail.fetch()
    assert (done.files, done.texts) == (0, 0) and docs() == [] and items() == []
    assert all(m.flags == set() for m in mailbox.inbox().mails), "left in the mailbox as before"


def test_a_forged_sender_gives_no_document(mailbox: imap_server.Store, tom: Account) -> None:
    text_on()
    forged = plain_mail()
    forged["Authentication-Results"] = "example.com; spf=fail smtp.mailfrom=example.com; dmarc=fail header.from=example.com"
    deliver(mailbox, forged)
    done = intake_mail.fetch()
    assert (done.files, done.texts) == (0, 0) and docs() == []


def test_a_verdict_written_by_somebody_else_does_not_count_and_the_text_is_taken(mailbox: imap_server.Store,
                                                                                 tom: Account) -> None:
    text_on()
    message = plain_mail()
    message["Authentication-Results"] = "mx.example.net; dmarc=fail"
    deliver(mailbox, message)
    assert intake_mail.fetch().texts == 1


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
    for never in ("GEHEIM-SKRIPT", "fetch(", "Kopf", "font-face", "Zaehlpixel", "cid:", "127.0.0.1", "Objekttext"):
        assert never not in text, never


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
    inner = plain_mail(sender="shop@example.org", to="tom.privat@example.com", subject="Bestellbestätigung")
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


def test_a_text_over_200_kb_is_cut_and_says_so_in_its_last_line(mailbox: imap_server.Store, tom: Account) -> None:
    text_on()
    line = "Zeile mit etwas Text, die sich oft wiederholt, damit die Mail groß wird. "
    deliver(mailbox, plain_mail(body="\n".join(f"{n:05d} {line}" for n in range(4000))))
    assert intake_mail.fetch().texts == 1
    [document] = docs()
    text = text_of(document.id)
    assert text.rstrip().endswith(mail_sheet.LABELS["de"]["cut"])
    assert len(text.encode("utf-8")) <= mail_text.TEXT_MAX + 2048
    assert "00000 Zeile" in text and "03999 Zeile" not in text
    with SessionLocal() as db:
        row = db.get(Document, document.id)
        assert row is not None
    process_all()
    with SessionLocal() as db:
        row = db.get(Document, document.id)
        assert row is not None and row.status == "inbox" and 1 < row.pages <= mail_sheet.MAX_PAGES


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
    assert mailbox.inbox().mails[0].flags == set()


def test_broken_character_sets_are_read_as_well_as_they_go(mailbox: imap_server.Store, tom: Account) -> None:
    text_on()
    body = "Grüße aus Lindenau, die Rechnung folgt per Post. Größe: 42 m²".encode()
    for charset in ("x-unknown-8bit", "base64", "us-ascii", "utf-8"):
        raw = (f"From: tom.privat@example.com\r\nTo: paper@example.com\r\nSubject: Zeichensatz {charset}\r\n"
               f"Message-ID: <{charset}@example.com>\r\nMIME-Version: 1.0\r\n"
               f"Content-Type: text/plain; charset=\"{charset}\"\r\nContent-Transfer-Encoding: 8bit\r\n\r\n").encode()
        deliver(mailbox, raw + body + b"\r\n")
    broken = (b"From: tom.privat@example.com\r\nTo: paper@example.com\r\nSubject: kaputt\r\nMIME-Version: 1.0\r\n"
              b"Content-Type: text/plain; charset=utf-8\r\n\r\nHalb kaputt \xff\xfe aber genug Text darin.\r\n")
    deliver(mailbox, broken)
    assert intake_mail.fetch().texts == 5
    texts = [text_of(d.id) for d in docs()]
    for text in texts[:4]:
        assert "Grüße aus Lindenau" in text
    assert "Halb kaputt" in texts[4] and "aber genug Text darin." in texts[4]


@pytest.mark.parametrize("markup", ["<p><img src=\"cid:a@example.com\"><img src=\"https://example.com/b.png\"></p>",
                                    "<p>Gruß, Tom</p>", "<p>   </p>"])
def test_pictures_only_or_a_short_signature_is_no_document(mailbox: imap_server.Store, tom: Account,
                                                           markup: str) -> None:
    text_on()
    deliver(mailbox, html_mail(markup))
    done = intake_mail.fetch()
    assert (done.files, done.texts) == (0, 0) and docs() == []


def test_a_subject_with_line_breaks_and_direction_characters_is_made_plain(mailbox: imap_server.Store,
                                                                           tom: Account) -> None:
    text_on()
    raw = ("From: tom.privat@example.com\r\nTo: paper@example.com\r\n"
           "Subject: =?utf-8?b?" + __import__("base64").b64encode(
               "WG: Rechnung\n\u202efdp.exe\u202c\r\nX-Injected: 1\u200b".encode()).decode() + "?=\r\n"
           "Message-ID: <subject@example.com>\r\nMIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
           + BODY + "\r\n").encode()
    deliver(mailbox, raw)
    assert intake_mail.fetch().texts == 1
    [document] = docs()
    assert document.title == "Rechnung fdp.exe X-Injected: 1"
    text = text_of(document.id)
    assert "\u202e" not in text and "\u200b" not in text
    assert "Betreff: WG: Rechnung fdp.exe X-Injected: 1\n" in text


def test_a_long_head_is_cut(mailbox: imap_server.Store, tom: Account) -> None:
    text_on()
    message = plain_mail(subject="S" * 900)
    message.replace_header("To", ", ".join(f"empf{n}@example.com" for n in range(60)))
    deliver(mailbox, message)
    assert intake_mail.fetch().texts == 1
    [document] = docs()
    assert len(document.title) <= 200
    head = text_of(document.id).split("\n\n", 1)[0]
    assert all(len(line) <= mail_worker.TO_MAX + 10 for line in head.split("\n"))


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


# --- The switch -------------------------------------------------------------------------------------------------------


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


def test_the_reading_of_documents_is_wrapped_once() -> None:
    assert mail_text.installed()
    mail_text.install()
    assert mail_text.installed()
    assert len(processing.STEPS) == 3


def test_document_without_a_kept_text_is_read_as_before(mailbox: imap_server.Store, tom: Account) -> None:
    text_on()
    deliver(mailbox, mail(files=[PDF]))
    intake_mail.fetch()
    [document] = docs()
    with SessionLocal() as db:
        row = db.get(Document, document.id)
        version = db.scalar(select(Version).where(Version.document_id == document.id))
        assert row is not None and version is not None
        assert mail_text.given(db, row, version) is None
        [item] = db.scalars(select(IntakeItem)).all()
        assert "text" not in item.detail


# --- The worker's reading, piece by piece ------------------------------------------------------------------------------


@pytest.mark.parametrize(("subject", "title"), [("WG: AW: Fwd: Rechnung", "Rechnung"), ("Re[2]: Termin", "Termin"),
                                                ("FW: ", "Mail ohne Betreff"), ("Wegweiser", "Wegweiser"),
                                                ("", "Mail ohne Betreff")])
def test_the_title_is_the_subject_without_what_forwarding_puts_in_front(subject: str, title: str) -> None:
    assert mail_text.title_of(subject, "de") == title


def test_html_breaks_lines_at_blocks_and_keeps_preformatted_text() -> None:
    text = mail_worker.html_text("<h1>Titel</h1><p>Erster<br>Zweiter</p><table><tr><td>A</td><td>B</td></tr></table>"
                                 "<pre>  eingerückt</pre>", 10_000)
    lines = [line for line in text.split("\n") if line]
    assert lines == ["Titel", "Erster", "Zweiter", "A B", "eingerückt"]


def test_tidy_takes_out_control_characters() -> None:
    assert mail_worker.tidy("\n\na\x00b\x1bc\x85d\r\ne\tf\n\n\n\ng\u202eh\n\n") == "abcd\ne    f\n\ngh"
