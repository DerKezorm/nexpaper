# ruff: noqa: F811 - the fixtures of the mailbox come from test_intake_mail
"""The mailbox against what a stranger can send and what a hostile server can do: mails that cost too much to take apart
(refused by a look at their bytes, or killed in their own process), a mail never taken twice nor lost when two folders
share UIDs, a deadline from the first byte and a cap on what one answer may hold, "afterwards" only for a mail taken whole,
the daily amounts, unknown senders left in the mailbox, the verdict of the mailbox's own server, and the edges."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import clock, mail_worker
from app.db import SessionLocal
from app.models import Account
from app.services import intake, intake_mail, settings_service

from . import imap_server
from .conftest import make_account
from .files import make_pdf
from .test_intake_mail import (  # noqa: F401 - fixtures
    PDF,
    api_test,
    certificate,
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

FLAGGED = "\\Flagged"
SEEN = "\\Seen"


def raw_mail(headers: str, body: str = "x") -> bytes:
    return (headers + "\r\n\r\n" + body + "\r\n").encode()


def state() -> dict[str, Any]:
    with SessionLocal() as db:
        return dict(settings_service.get(db, "mail_state") or {})


def last() -> dict[str, Any]:
    with SessionLocal() as db:
        return dict(settings_service.get(db, "mail_last") or {})


def owner_names() -> list[str]:
    with SessionLocal() as db:
        names = {row.id: row.name for row in db.query(Account)}
    return [names.get(d.owner_id, "") for d in docs()]


# --- H1: a mail that costs too much ---------------------------------------------------------------------------------------

BASE = "From: a@example.org\r\nTo: paper@example.com\r\nSubject: s\r\nMIME-Version: 1.0"
COSTLY = {
    "a header line over 8 KB": raw_mail('From: "' + '"' * 9000 + "\r\nTo: paper@example.com"),
    "more than 100 addresses": raw_mail("From: a@example.org\r\nTo: " + ", ".join(f"u{i}@example.com" for i in range(101))),
    "too many header lines": raw_mail(BASE + "\r\n" + "X-A: 1\r\n" * 600 + "X-B: 2"),
    "more than 100 parameters": raw_mail(
        BASE + "\r\nContent-Type: application/pdf; " + "; ".join(f"p{i}=a" for i in range(101))),
    "a file name over 1 KB": raw_mail(
        BASE + '\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename="'
        + "=?utf-8?q?a?= " * 80 + '"'),
    "more than 100 parts": raw_mail(BASE + "\r\nContent-Type: multipart/mixed; boundary=B",
                                    "".join("--B\r\nContent-Type: text/plain\r\n\r\nx\r\n" for _ in range(102))
                                    + "--B--"),
}


@pytest.mark.parametrize("name", sorted(COSTLY))
def test_a_mail_that_costs_too_much_is_refused_by_a_look_at_its_bytes(name: str) -> None:
    assert intake_mail.too_elaborate(COSTLY[name]) is True


def test_ordinary_mails_pass_the_look() -> None:
    message = mail(files=[PDF, ("Quittung März.pdf", make_pdf(), "application/pdf")])
    assert intake_mail.too_elaborate(message.as_bytes()) is False
    many = mail(to=", ".join(f"u{i}@example.com" for i in range(60)))
    assert intake_mail.too_elaborate(many.as_bytes()) is False


def test_a_costly_mail_is_skipped_for_good_said_in_the_log_and_in_the_last_run(
        mailbox: imap_server.Store, operator: Account, caplog: pytest.LogCaptureFixture) -> None:
    deliver(mailbox, COSTLY["a header line over 8 KB"])
    deliver(mailbox, mail(sender="b@example.org", files=[PDF]))
    done = intake_mail.fetch()
    assert done.skipped == 1 and done.files == 1
    assert "taking it apart costs too much" in caplog.text
    assert last()["skipped"] == 1
    again = intake_mail.fetch()
    assert again.skipped == 0 and len(docs()) == 1, "never tried again"
    assert mailbox.inbox().mails[0].flags == set(), "the costly mail itself is not touched"


def test_a_mail_that_takes_too_long_in_its_process_is_killed_and_skipped(mailbox: imap_server.Store, operator: Account,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intake_mail, "WORKER_SECONDS", 0.001)
    deliver(mailbox, mail(sender="b@example.org", files=[PDF]))
    started = time.monotonic()
    done = intake_mail.fetch()
    assert done.skipped == 1 and docs() == []
    assert time.monotonic() - started < 20
    assert state()["last"] == 1 and state()["retry"] == {}


def test_the_mail_worker_stands_alone_and_gives_back_only_what_it_was_asked(tmp_path: Any) -> None:
    import ast
    from pathlib import Path

    tree = ast.parse(Path(mail_worker.__file__).read_text(encoding="utf-8"))
    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not any(name.startswith(("app", "sqlalchemy", ".")) for name in imported), imported


def test_a_mail_that_brings_the_run_down_is_tried_three_times_then_flagged(mailbox: imap_server.Store,
                                                                           operator: Account,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    deliver(mailbox, mail(sender="b@example.org", files=[PDF]))

    def falls(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("the server went down while it took the mail apart")

    monkeypatch.setattr(intake_mail, "take_mail", falls)
    for run in range(intake_mail.MAX_TRIES):
        with pytest.raises(intake_mail.MailFailure):
            intake_mail.fetch()
        # Written before the mail was taken apart: the place is kept, the try is counted.
        assert state()["last"] == 1 and state()["retry"] == {"1": run + 1}
    done = intake_mail.fetch()
    assert done.flagged == 1 and state()["retry"] == {}
    assert mailbox.inbox().mails[0].flags == {FLAGGED}
    assert intake_mail.fetch().flagged == 0, "and then left alone"


# --- H2: two folders with the same UIDs -------------------------------------------------------------------------------


def test_a_second_folder_with_the_same_uids_is_not_taken_for_the_first(server: imap_server.Server,
                                                                      store: imap_server.Store,
                                                                      operator: Account) -> None:
    store.folders["Rechnungen"] = imap_server.Folder(validity=store.inbox().validity)
    set_up(server.port, store.password, mail_after="delete")
    deliver(store, mail(sender="a@example.org", files=[("Alt.pdf", make_pdf(["alt"]), "application/pdf")]))
    intake_mail.fetch()
    assert store.inbox().mails == []
    store.folders["Rechnungen"].add(mail(sender="a@example.org",
                                         files=[("Neu.pdf", make_pdf(["neu"]), "application/pdf")]).as_bytes())
    set_up(server.port, store.password, mail_after="delete", mail_folder="Rechnungen")
    done = intake_mail.fetch()
    assert done.files == 1 and sorted(d.title for d in docs()) == ["Alt", "Neu"]
    assert store.folders["Rechnungen"].mails == [], "deleted only once it was taken"
    keys = sorted(item.key for item in items())
    assert keys[0].split(":")[0] != keys[1].split(":")[0], "the mailbox is part of the key"


# --- M1: the deadline from the first byte, and answers of a bounded size ---------------------------------------------------


@pytest.fixture
def hostile() -> Iterator[tuple[int, list[bytes]]]:
    """A server that speaks as told: the lines to send, then silence."""
    listener, port = imap_server.silent_port()
    script: list[bytes] = []
    stop = threading.Event()

    def serve() -> None:
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except OSError:
                continue
            with conn:
                for chunk in script:
                    if stop.is_set():
                        break
                    try:
                        if chunk == b"WAIT":
                            time.sleep(0.1)
                        else:
                            conn.sendall(chunk)
                    except OSError:
                        break
                while not stop.is_set():
                    time.sleep(0.05)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield port, script
    stop.set()
    listener.close()
    thread.join(3)


def test_a_greeting_that_trickles_runs_into_the_deadline(hostile: tuple[int, list[bytes]], client: TestClient,
                                                         operator: Account, trusted: None,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    port, script = hostile
    for byte in b"* OK " + b"x" * 200:
        script += [bytes([byte]), b"WAIT"]
    monkeypatch.setattr(intake_mail, "RUN_SECONDS", 0.6)
    set_up(port, "x", mail_security="none")
    started = time.monotonic()
    answer = api_test(client)
    assert answer.json()["detail"]["code"] == "mail_timeout"
    assert time.monotonic() - started < 5


def test_a_flood_of_untagged_lines_is_cut_off(hostile: tuple[int, list[bytes]], client: TestClient, operator: Account,
                                              trusted: None, monkeypatch: pytest.MonkeyPatch) -> None:
    port, script = hostile
    script += [b"* OK [CAPABILITY IMAP4rev1] hi\r\n"] + [b"* OK flood\r\n" * 50] * 10
    monkeypatch.setattr(intake_mail, "MAX_LINES", 100)
    set_up(port, "x", mail_security="none")
    answer = api_test(client)
    assert answer.json()["detail"]["code"] == "mail_protocol"


def test_the_connection_goes_to_the_address_checked_never_to_the_name(store: imap_server.Store,
                                                                      certificate: Any, client: TestClient,
                                                                      operator: Account, trusted: None,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    running = imap_server.start(store, certificate, implicit_tls=False)
    real = socket.getaddrinfo
    looked: list[str] = []

    def lookup(host: Any, *args: Any, **kwargs: Any) -> Any:
        looked.append(str(host))
        if host == "localhost":
            raise socket.gaierror("a second lookup of the name")
        return real(host, *args, **kwargs)

    try:
        monkeypatch.setattr(intake_mail, "resolver", lambda host, port: ["127.0.0.1"])
        monkeypatch.setattr(socket, "getaddrinfo", lookup)
        set_up(running.port, store.password, mail_security="none", mail_host="localhost")
        assert api_test(client).status_code == 200
    finally:
        imap_server.stop(running)
    assert "localhost" not in looked


def test_without_tls_a_name_that_points_at_this_machine_is_not_enough(client: TestClient, operator: Account,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intake_mail, "resolver", lambda host, port: ["127.0.0.1"])
    set_up(143, "x", mail_security="none", mail_host="imap.example.com")
    answer = api_test(client)
    assert answer.json()["detail"]["code"] == "mail_plain_not_local"


# --- M2: afterwards only for a mail taken whole ----------------------------------------------------------------------------


def test_a_part_that_fails_leaves_the_mail_and_is_taken_next_time(server: imap_server.Server, store: imap_server.Store,
                                                                   operator: Account,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    set_up(server.port, store.password, mail_after="delete")
    deliver(store, mail(sender="a@example.org", files=[("eins.pdf", make_pdf(["1"]), "application/pdf"),
                                                       ("zwei.pdf", make_pdf(["2"]), "application/pdf")]))
    real = intake.take
    calls: list[int] = []

    def full_once(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise OSError(28, "No space left on device")
        return real(*args, **kwargs)

    monkeypatch.setattr(intake, "take", full_once)
    intake_mail.fetch()
    assert [d.title for d in docs()] == ["zwei"]
    assert len(store.inbox().mails) == 1, "not deleted while a part is missing"
    done = intake_mail.fetch()
    assert sorted(d.title for d in docs()) == ["eins", "zwei"] and done.files == 1
    assert store.inbox().mails == [], "deleted once it was taken whole"


def test_a_part_that_always_fails_is_tried_three_times_then_the_mail_is_flagged(
        server: imap_server.Server, store: imap_server.Store, operator: Account,
        monkeypatch: pytest.MonkeyPatch) -> None:
    set_up(server.port, store.password, mail_after="delete")
    deliver(store, mail(sender="a@example.org", files=[PDF]))

    def full(*args: Any, **kwargs: Any) -> Any:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(intake, "take", full)
    for _ in range(intake_mail.MAX_TRIES):
        intake_mail.fetch()
    assert store.inbox().mails[0].flags == set()
    assert intake_mail.fetch().flagged == 1
    assert store.inbox().mails[0].flags == {FLAGGED} and docs() == []


def test_more_parts_than_taken_leave_the_mail_flagged(server: imap_server.Server, store: imap_server.Store,
                                                      operator: Account) -> None:
    set_up(server.port, store.password, mail_after="delete")
    files = [(f"t{n:02}.pdf", make_pdf([str(n)]), "application/pdf") for n in range(25)]
    deliver(store, mail(sender="a@example.org", files=files))
    done = intake_mail.fetch()
    assert done.files == intake_mail.MAX_ATTACHMENTS and done.flagged == 1
    assert len(store.inbox().mails) == 1 and store.inbox().mails[0].flags == {FLAGGED}


# --- M3: amounts, unknown senders, the mailbox's own server ----------------------------------------------------------------


def test_a_person_receives_at_most_the_daily_amount_the_rest_waits_for_the_next_day(
        mailbox: imap_server.Store, operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    make_account("jule")
    one = len(make_pdf(["eins"]))
    monkeypatch.setattr(intake_mail, "PERSON_DAY_BYTES", one + 10)
    for name in ("eins", "zwei"):
        deliver(mailbox, mail(sender="x@example.org", to="paper+jule@example.com",
                              files=[(f"{name}.pdf", make_pdf([name]), "application/pdf")]))
    done = intake_mail.fetch()
    assert done.deferred == 1 and [d.title for d in docs()] == ["eins"]
    assert mailbox.inbox().mails[1].flags == set(), "left as it is"
    assert intake_mail.fetch().deferred == 0 and len(docs()) == 1, "not tried again the same day"
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    monkeypatch.setattr(clock, "now", lambda: tomorrow)
    intake_mail.fetch()
    assert sorted(d.title for d in docs()) == ["eins", "zwei"]


def test_a_run_and_a_day_take_at_most_their_amount(mailbox: imap_server.Store, operator: Account,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("a", "b", "c"):
        deliver(mailbox, mail(sender="x@example.org", files=[(f"{name}.pdf", make_pdf([name]), "application/pdf")]))
    size = max(len(m.data) for m in mailbox.inbox().mails)
    monkeypatch.setattr(intake_mail, "RUN_BYTES", size + 10)
    first = intake_mail.fetch()
    assert first.files == 1 and first.more is True
    monkeypatch.setattr(intake_mail, "DAY_BYTES", 1)
    assert intake_mail.fetch().files == 0, "the day's amount is reached"
    assert len(docs()) == 1


def test_unknown_senders_can_be_left_in_the_mailbox(mailbox: imap_server.Store, operator: Account,
                                                    client: TestClient) -> None:
    answer = client.put("/api/v1/settings/intake", json={"mail_drop_unknown": True})
    assert answer.json()["mail"]["drop_unknown"] is True
    deliver(mailbox, mail(sender="fremd@example.org", files=[PDF]))
    done = intake_mail.fetch()
    assert done.dropped == 1 and docs() == [] and mailbox.inbox().mails[0].flags == set()


@pytest.mark.parametrize(("results", "owner"), [
    ("mx.example.com; spf=fail smtp.mailfrom=example.org", "jule"),
    ("example.com; dmarc=fail header.from=example.org", "tester"),
    ("mx.example.com; spf=pass; dmarc=pass", "jule"),
    ("mx.evil.example.org; spf=fail", "jule"),
    ("example.com.evil.example.org; dmarc=fail", "jule"),
])
def test_the_verdict_of_the_mailboxs_own_server_counts_and_nobody_elses(mailbox: imap_server.Store,
                                                                         operator: Account, results: str,
                                                                         owner: str) -> None:
    make_account("jule")
    message = mail(sender="x@example.org", to="paper+jule@example.com", files=[PDF])
    message["Authentication-Results"] = results
    deliver(mailbox, message)
    intake_mail.fetch()
    assert owner_names() == [owner]


# --- N4: the edges ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("to", "owner"), [
    ("paper+jule+steuer@example.com", "jule"),
    ("paper+jule@example.com, paper+lea@example.com", "tester"),
    ("paper+jule@example.com, Paper+JULE@example.com", "jule"),
    ("paper+lea@example.net", "jule"),
    ("paper+lea@example.com.example.net", "jule"),
])
def test_the_plus_address_is_read_one_way(mailbox: imap_server.Store, operator: Account, to: str, owner: str) -> None:
    from .test_intake_mail import confirmed_sender

    # The sender is known as jule's: a plus address that names nobody clearly is not overruled by it.
    confirmed_sender(make_account("jule"), "jule.privat@example.org")
    make_account("lea")
    deliver(mailbox, mail(sender="jule.privat@example.org", to=to, files=[PDF]))
    intake_mail.fetch()
    assert owner_names() == [owner]


def test_switched_off_while_fetching_it_stops_between_two_mails(mailbox: imap_server.Store, operator: Account,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("a", "b", "c"):
        deliver(mailbox, mail(sender="x@example.org", files=[(f"{name}.pdf", make_pdf([name]), "application/pdf")]))
    real = intake_mail.take_mail

    def and_off(*args: Any, **kwargs: Any) -> Any:
        taken = real(*args, **kwargs)
        with SessionLocal() as db:
            settings_service.save(db, {"mail_on": False})
        return taken

    monkeypatch.setattr(intake_mail, "take_mail", and_off)
    done = intake_mail.fetch()
    assert done.files == 1 and done.more is True


@pytest.mark.parametrize("after", ["move", "delete"])
def test_a_first_start_takes_only_the_unread_mails_whatever_comes_after(server: imap_server.Server,
                                                                        store: imap_server.Store,
                                                                        operator: Account, after: str) -> None:
    set_up(server.port, store.password, mail_after=after)
    old = deliver(store, mail(sender="x@example.org", files=[("Alt.pdf", make_pdf(["alt"]), "application/pdf")]),
                  flags={SEEN})
    deliver(store, mail(sender="x@example.org", files=[("Neu.pdf", make_pdf(["neu"]), "application/pdf")]))
    intake_mail.fetch()
    assert [d.title for d in docs()] == ["Neu"]
    assert [m.uid for m in store.inbox().mails] == [old], "the old mail is history, untouched"


def test_one_message_of_the_worker_is_built_by_hand_to_check_the_nesting() -> None:
    import email
    import email.policy

    def nested(depth: int) -> EmailMessage:
        inner = mail(sender="x@example.org", files=[("tief.pdf", make_pdf(["tief"]), "application/pdf")])
        for _ in range(depth):
            outer = mail(sender="x@example.org")
            outer.add_attachment(inner)
            inner = outer
        return inner

    shallow = email.message_from_bytes(nested(2).as_bytes(), policy=email.policy.default)
    deep = email.message_from_bytes(nested(6).as_bytes(), policy=email.policy.default)
    assert [name for name, _data in mail_worker.leaves(shallow, 8, 300, 0)] == ["tief.pdf"]
    assert mail_worker.leaves(deep, 8, 300, 0) == [], "deeper than the limit is not looked into"
