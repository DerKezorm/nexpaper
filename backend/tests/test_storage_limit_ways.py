"""The storage limit of an account on every way in (Bauplan E47): the intake folder and the mailbox lose nothing (the
file stays in the folder, the mail unread in the mailbox) and take it once there is room; the import from Paperless
skips the document with ``storage_full`` and a later run takes it; an upload request refuses the file with
``request_no_room``. The account hears "Speicher voll, x Dokumente warten" (push and mail as nexpaper's other
notices), the log has a line."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import clock
from app.db import SessionLocal
from app.models import Account, Document, PaperlessItem
from app.services import intake_folder, intake_mail, quota, settings_service, tell

from . import files, imap_server
from .conftest import make_account, new_client
from .fake_paperless import Doc
from .test_intake_folder import Clock, folder, settle, ticks  # noqa: F401 - fixtures
from .test_intake_mail import (  # noqa: F401 - fixtures
    certificate,
    deliver,
    mail,
    mailbox,
    server,
    store,
    trusted,
)
from .test_paperless import connect, fake, run_import, run_state  # noqa: F401 - fixtures
from .test_upload_requests import jule, make, send, stranger, token_of  # noqa: F401 - fixtures


@pytest.fixture(autouse=True)
def told(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[int, tell.Notice]]]:
    """What the accounts were told (``tell.person``), in order; nothing waits from a test before."""
    said: list[tuple[int, tell.Notice]] = []
    quota.forget()
    monkeypatch.setattr(tell, "person", lambda account_id, notice: said.append((account_id, notice)))
    yield said
    quota.forget()


def limit(account: Account, size: int | None) -> None:
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None
        row.storage_limit = size
        db.commit()


def owned(account: Account) -> list[Document]:
    with SessionLocal() as db:
        found = list(db.scalars(select(Document).where(Document.owner_id == account.id).order_by(Document.id)))
        for row in found:
            db.expunge(row)
        return found


# --- What waits, and telling the account -----------------------------------------------------------------------------


def test_the_account_hears_how_many_wait_once_and_again_only_when_more_wait_after_an_hour(
        told: list[tuple[int, tell.Notice]], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    now = [1000.0]
    monkeypatch.setattr(clock, "monotonic", lambda: now[0])
    with caplog.at_level(logging.WARNING, logger="nexpaper.quota"):
        quota.waiting(quota.FOLDER, {7: 2})
    assert [(account, notice.texts["de"]) for account, notice in told] == [
        (7, ("Speicher voll", "2 Dokumente warten, bis in deinem Konto wieder Platz ist."))]
    assert "Storage full: documents wait account_id=7 waiting=2 way=folder" in caplog.text
    (_account, notice), = told
    assert (notice.url, notice.tag) == ("/", "storage-full")
    assert notice.texts["en"] == ("Storage full", "2 documents are waiting until there is room in your account again.")
    assert notice.texts["fr"][0] == "Stockage plein"
    assert "2 documents are waiting" in notice.mail_body and notice.mail_body.endswith("{where}\n")
    # The same again, every round: nothing new. More on another way, within the hour: nothing yet.
    quota.waiting(quota.FOLDER, {7: 2})
    quota.waiting(quota.MAIL, {7: 1})
    assert len(told) == 1 and quota.waiting_now(7) == 3
    now[0] += quota.TELL_AGAIN_SECONDS
    quota.waiting(quota.MAIL, {7: 1})
    assert [notice.texts["de"][1] for _a, notice in told][1] == "3 Dokumente warten, bis in deinem Konto wieder Platz ist."
    # Room again: nothing waits, and the next time it fills up the account hears it at once.
    quota.waiting(quota.FOLDER, {})
    quota.waiting(quota.MAIL, {})
    assert quota.waiting_now(7) == 0
    quota.waiting(quota.PAPERLESS, {7: 1})
    assert told[-1][1].texts["de"][1] == "Ein Dokument wartet, bis in deinem Konto wieder Platz ist."
    assert len(told) == 3


def test_a_notice_speaks_french_where_it_has_french_words_else_as_before() -> None:
    notice = quota.notice(4)
    assert tell.words(notice, "fr-CH")[0] == "Stockage plein"
    assert tell.words(notice, "de")[0] == "Speicher voll"
    assert tell.words(notice, "nl")[0] == "Storage full"
    plain = tell.Notice(texts={"de": ("A", "a"), "en": ("B", "b")}, url="/", tag="x", mail_subject="", mail_body="")
    assert tell.words(plain, "fr") == ("B", "b")


# --- The intake folder ------------------------------------------------------------------------------------------------


def test_a_file_of_the_intake_folder_waits_in_the_folder_while_the_storage_is_full(
        operator: Account, ticks: Clock, folder: Any, told: list[tuple[int, tell.Notice]]) -> None:  # noqa: F811
    tom = make_account("tom")
    intake_folder.scan()
    limit(tom, 1)
    (folder / "tom" / "a.pdf").write_bytes(files.make_pdf(["eins"]))
    (folder / "tom" / "b.pdf").write_bytes(files.make_pdf(["zwei"]))
    first = settle(ticks)
    assert first.taken == {} and first.full == {tom.id: 2}
    assert (folder / "tom" / "a.pdf").exists() and (folder / "tom" / "b.pdf").exists() and owned(tom) == []
    assert not (folder / "tom" / intake_folder.REJECTED).exists(), "nothing is set aside"
    assert [(account, notice.texts["de"][1]) for account, notice in told] == [
        (tom.id, "2 Dokumente warten, bis in deinem Konto wieder Platz ist.")]
    # Room for one: one comes in, the other waits.
    limit(tom, len((folder / "tom" / "a.pdf").read_bytes()) + 10)
    second = intake_folder.scan()
    assert second.taken == {"tom": 1} and second.full == {tom.id: 1} and len(owned(tom)) == 1
    # No limit: the last comes in, nothing waits.
    limit(tom, None)
    assert intake_folder.scan().taken == {"tom": 1}
    assert len(owned(tom)) == 2 and quota.waiting_now(tom.id) == 0
    assert not (folder / "tom" / "a.pdf").exists() and not (folder / "tom" / "b.pdf").exists()


def test_every_file_of_a_person_without_room_waits_not_only_the_turns_of_a_round(
        operator: Account, ticks: Clock, folder: Any, told: list[tuple[int, tell.Notice]]) -> None:  # noqa: F811
    """A full account's files are not even opened; all of them count as waiting, more than one round takes per person."""
    tom = make_account("tom")
    intake_folder.scan()
    limit(tom, 0)
    count = intake_folder.PER_PERSON + 2
    for number in range(count):
        (folder / "tom" / f"{number}.pdf").write_bytes(files.make_pdf([f"Seite {number}"]))
    assert settle(ticks).full == {tom.id: count}
    assert quota.waiting_now(tom.id) == count and owned(tom) == []
    assert told[-1][1].texts["de"][1] == f"{count} Dokumente warten, bis in deinem Konto wieder Platz ist."


# --- The mailbox ------------------------------------------------------------------------------------------------------


def test_a_mail_waits_unread_in_the_mailbox_while_the_storage_is_full_and_comes_in_with_room(
        mailbox: imap_server.Store, told: list[tuple[int, tell.Notice]]) -> None:  # noqa: F811
    jule_account = make_account("jule")
    limit(jule_account, 1)
    two = [("a.pdf", files.make_pdf(["eins"]), "application/pdf"), ("b.pdf", files.make_pdf(["zwei"]), "application/pdf")]
    deliver(mailbox, mail(sender="someone@example.org", to="paper+jule@example.com", files=two))
    first = intake_mail.fetch()
    assert (first.files, first.full) == (0, 1) and owned(jule_account) == []
    assert "\\Seen" not in mailbox.inbox().mails[0].flags, "left unread"
    assert [(account, notice.texts["de"][1]) for account, notice in told] == [
        (jule_account.id, "2 Dokumente warten, bis in deinem Konto wieder Platz ist.")]
    # Still full: the mail is not fetched again.
    again = intake_mail.fetch()
    assert (again.files, again.full) == (0, 0) and owned(jule_account) == []
    with SessionLocal() as db:
        kept = settings_service.get(db, "mail_state")
    [(owner, count, size)] = kept["full"].values()
    assert (owner, count) == (jule_account.id, 2) and size == sum(len(data) for _name, data, _kind in two)
    limit(jule_account, None)
    done = intake_mail.fetch()
    assert done.files == 2 and len(owned(jule_account)) == 2
    assert "\\Seen" in mailbox.inbox().mails[0].flags
    with SessionLocal() as db:
        assert settings_service.get(db, "mail_state")["full"] == {}
    assert quota.waiting_now(jule_account.id) == 0


def test_the_text_of_a_mail_waits_too(mailbox: imap_server.Store, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """A mail that becomes a document of its text (``mail_text``) is held to the limit as an attachment is."""
    from app.services import mail_text

    taken = intake_mail.Taken()
    tom = make_account("tom")
    limit(tom, 1)

    class Made:
        error, empty, subject, day, texts = "", False, "Hallo", None, ["Hallo"]

        def __init__(self, path: Any) -> None:
            self.pdf = path

    def read(_raw: bytes, where: Any, _language: str) -> Made:
        made = where / "mail.pdf"
        made.write_bytes(files.make_pdf(["Hallo"]))
        return Made(made)

    monkeypatch.setattr(mail_text, "read", read)
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as where:
        mail_text.take(taken, b"", Path(where), key="INBOX:1:1:text", owner=tom.id, marker="", sender="a@example.com",
                       subject="Hallo", budget=None, texts_left=None)
    assert (taken.full, taken.files, taken.deferred) == (1, 0, False) and taken.need > 1 and owned(tom) == []


# --- Paperless --------------------------------------------------------------------------------------------------------


def test_a_document_of_paperless_is_skipped_while_the_storage_is_full_and_a_later_run_takes_it(
        client: TestClient, operator: Account, fake: Any, told: list[tuple[int, tell.Notice]]) -> None:  # noqa: F811
    made, paperless_server = fake
    made.users = {2: {"username": "tom", "groups": []}}
    made.add(Doc(1, "Strom", files.make_pdf(["Strom"]), owner=2, content="Strom"))
    made.add(Doc(2, "Wasser", files.make_pdf(["Wasser"]), owner=2, content="Wasser"))
    tom = make_account("tom")
    limit(tom, 1)
    connect(client, made, paperless_server)
    body = {"where": "owner", "people": [{"paperless_id": 2, "user_id": tom.id}]}
    assert client.post("/api/v1/settings/paperless/start", json=body).status_code in (200, 202)
    run_import()
    assert owned(tom) == []
    state = run_state(client)
    assert (state["taken"], state["skipped"], state["reasons"]) == (0, 2, {"storage_full": 2})
    with SessionLocal() as db:
        assert sorted(db.scalars(select(PaperlessItem.reason))) == ["storage_full", "storage_full"]
    assert [(account, notice.texts["de"][1]) for account, notice in told] == [
        (tom.id, "2 Dokumente warten, bis in deinem Konto wieder Platz ist.")]
    limit(tom, None)
    client.post("/api/v1/settings/paperless/start", json=body)
    run_import()
    assert len(owned(tom)) == 2 and run_state(client)["taken"] == 2
    assert quota.waiting_now(tom.id) == 0


# --- Upload requests --------------------------------------------------------------------------------------------------


def test_an_upload_request_refuses_a_file_while_the_storage_of_its_person_is_full(
        jule: Account, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.services import upload_requests

    with new_client(jule) as browser:
        token = token_of(make(browser))
    limit(jule, 1)
    with stranger() as outside, caplog.at_level(logging.INFO, logger="nexpaper.requests"):
        # Some room, but not for this file: refused once it is there.
        refused = send(outside, token)
        assert (refused.status_code, refused.json()["detail"]["code"]) == (507, "request_no_room")
        # No room at all: refused before a byte of it is read, the file never reaches the person.
        limit(jule, 0)
        real = upload_requests.take_file

        def never(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("the file was read although there is no room")

        monkeypatch.setattr(upload_requests, "take_file", never)
        before = send(outside, token)
        assert (before.status_code, before.json()["detail"]["code"]) == (507, "request_no_room")
        monkeypatch.setattr(upload_requests, "take_file", real)
    assert owned(jule) == []
    assert caplog.text.count("Upload request refused a file, the storage of its person is full") == 2
    limit(jule, None)
    with stranger() as outside:
        assert send(outside, token).status_code == 201
    assert len(owned(jule)) == 1
