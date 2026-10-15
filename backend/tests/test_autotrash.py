"""Expired documents into the trash by themselves (D4): a switch per kind (off from the start, only with a keeping
time, set by whoever sets the time), a daily task that puts the filed, expired documents of such kinds in the trash
once, never twice, never more than the brake of the day, with a line in the history and a line in the weekly mail.

The clock is given to the run (``autotrash.run(db, today)``) and to the reminders; nothing here waits for a day.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import zipfile
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import db as database
from app.db import SessionLocal
from app.models import Account, Counter, Document, Event, Kind
from app.services import autotrash, backups

from .conftest import TAB, make_account, new_client
from .intake import device_token, upload_key
from .papers import add_document, document, freeze, own_vault, shared_vault
from .test_keeping import kind_id, set_keep

DAY = timedelta(days=1)
NOW = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
TODAY = date(2026, 10, 14)
OVER = date(2025, 12, 31)


@pytest.fixture(autouse=True)
def clock_stands(monkeypatch: pytest.MonkeyPatch) -> None:
    freeze(monkeypatch, NOW)


def switch(session: TestClient, kind: int, enabled: bool = True) -> dict[str, object]:
    answer = session.put(f"/api/v1/kinds/{kind}/auto-trash", json={"enabled": enabled})
    assert answer.status_code == 200, answer.text
    return answer.json()  # type: ignore[no-any-return]


def run_day(today: date = TODAY, **kwargs: int) -> int:
    with SessionLocal() as db:
        return autotrash.run(db, today, **kwargs)


def lines(document_id: int) -> list[Event]:
    with SessionLocal() as db:
        return list(db.scalars(select(Event).where(Event.document_id == document_id,
                                                   Event.action == autotrash.AUTO_TRASHED)))


@pytest.fixture
def invoices(client: TestClient, operator: Account) -> int:
    """The kind "invoice" of the server with a keeping time of one year and the switch on."""
    kind = kind_id(client, "invoice")
    set_keep(client, kind, 1)
    switch(client, kind)
    return kind


# --- The switch -------------------------------------------------------------------------------------------------------


def test_the_switch_is_off_from_the_start_and_needs_a_keeping_time(client: TestClient, operator: Account) -> None:
    kind = kind_id(client, "invoice")
    assert all(k["auto_trash"] is False for k in client.get("/api/v1/kinds").json())
    state = client.post(f"/api/v1/kinds/{kind}/auto-trash/preview").json()
    assert state["kind"]["auto_trash"] is False and state["due"] == 0
    refused = client.put(f"/api/v1/kinds/{kind}/auto-trash", json={"enabled": True})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "no_keeping_time"
    set_keep(client, kind, 10)
    assert switch(client, kind)["kind"]["auto_trash"] is True  # type: ignore[index]
    ordered = next(k for k in client.get("/api/v1/order/kinds").json()["items"] if k["id"] == kind)
    assert ordered["auto_trash"] is True
    # Taking the time away takes the switch with it; setting a time again does not bring it back.
    set_keep(client, kind, None)
    assert client.post(f"/api/v1/kinds/{kind}/auto-trash/preview").json()["kind"]["auto_trash"] is False
    set_keep(client, kind, 3)
    assert client.post(f"/api/v1/kinds/{kind}/auto-trash/preview").json()["kind"]["auto_trash"] is False
    # Switching off what is off is no error.
    assert switch(client, kind, False)["kind"]["auto_trash"] is False  # type: ignore[index]
    assert client.put(f"/api/v1/kinds/{kind}/auto-trash", json={"enabled": "yes"}).status_code == 422
    assert client.put(f"/api/v1/kinds/{kind}/auto-trash", json={}).status_code == 422
    assert client.put(f"/api/v1/kinds/{kind}/auto-trash", json={"enabled": True, "x": 1}).status_code == 422
    assert client.put(f"/api/v1/kinds/{2**31 - 1}/auto-trash", json={"enabled": True}).status_code == 404


def test_the_servers_kinds_are_the_operators(client: TestClient, operator: Account) -> None:
    kind = kind_id(client, "invoice")
    set_keep(client, kind, 2)
    member = make_account("jule")
    with new_client(member) as jule:
        assert jule.put(f"/api/v1/kinds/{kind}/auto-trash", json={"enabled": True}).status_code == 403
        assert jule.post(f"/api/v1/kinds/{kind}/auto-trash/preview").status_code == 403
    token = device_token(client)
    with TestClient(client.app, base_url="http://testserver") as device:
        headers = {"Authorization": f"Bearer {token}"}
        assert device.put(f"/api/v1/kinds/{kind}/auto-trash", json={"enabled": True}, headers=headers).status_code == 403
        assert device.post(f"/api/v1/kinds/{kind}/auto-trash/preview", headers=headers).status_code == 403
    assert client.post(f"/api/v1/kinds/{kind}/auto-trash/preview").json()["kind"]["auto_trash"] is False


def test_a_vaults_kinds_need_manage_there(client: TestClient, operator: Account) -> None:
    editor, reader, stranger, manager = (make_account(n) for n in ("editor", "reader", "stranger", "manager"))
    vault = shared_vault("Haushalt", operator, (editor, "edit"), (reader, "read"), (manager, "manage"))
    kind = client.post("/api/v1/kinds", json={"name": "Beleg", "vault_id": vault}).json()["id"]
    set_keep(client, kind, 6)
    with new_client(stranger) as session:
        assert session.put(f"/api/v1/kinds/{kind}/auto-trash", json={"enabled": True}).status_code == 404
        assert session.post(f"/api/v1/kinds/{kind}/auto-trash/preview").status_code == 404
    for who in (reader, editor):
        with new_client(who) as session:
            assert session.put(f"/api/v1/kinds/{kind}/auto-trash", json={"enabled": True}).status_code == 403
            assert session.post(f"/api/v1/kinds/{kind}/auto-trash/preview").status_code == 403
    with new_client(manager) as session:
        token = device_token(session)
    with TestClient(client.app, base_url="http://testserver") as program:
        for secret in (upload_key(manager, "read"), upload_key(manager, "upload")):
            headers = {"Authorization": f"Bearer {secret}"}
            assert program.put(f"/api/v1/kinds/{kind}/auto-trash", json={"enabled": True},
                               headers=headers).status_code in (401, 403)
            assert program.post(f"/api/v1/kinds/{kind}/auto-trash/preview", headers=headers).status_code in (401, 403)
        headers = {"Authorization": f"Bearer {token}"}
        answer = program.put(f"/api/v1/kinds/{kind}/auto-trash", json={"enabled": True}, headers=headers)
        assert answer.status_code == 200 and answer.json()["kind"]["auto_trash"] is True
    with TestClient(client.app, base_url="http://testserver") as nobody:
        assert nobody.post(f"/api/v1/kinds/{kind}/auto-trash/preview", headers=TAB).status_code == 401
    assert client.post(f"/api/v1/kinds/{kind}/auto-trash/preview").json()["kind"]["auto_trash"] is True


def test_the_question_counts_what_the_person_may_see(client: TestClient, operator: Account) -> None:
    kind = kind_id(client, "invoice")
    set_keep(client, kind, 1)
    lea = make_account("lea")
    add_document(own_vault(operator), operator, "Alt", kind_id=kind, date=date(2020, 1, 1), content=None)
    add_document(own_vault(operator), operator, "Neu", kind_id=kind, date=date(2026, 1, 1), content=None)
    add_document(own_vault(operator), operator, "Im Eingang", kind_id=kind, date=date(2020, 1, 1), status="inbox",
                 content=None)
    add_document(own_vault(lea), lea, "Leas", kind_id=kind, date=date(2020, 1, 1), content=None)
    # Lea's document is changed all the same by the server's kind, but the operator is not told about it.
    assert client.post(f"/api/v1/kinds/{kind}/auto-trash/preview").json()["due"] == 1
    assert switch(client, kind)["due"] == 1
    assert run_day() == 2, "both filed expired documents go, the one in the inbox stays"


# --- What it does -----------------------------------------------------------------------------------------------------


def test_it_puts_only_filed_expired_documents_of_marked_kinds_in_the_trash(client: TestClient, operator: Account,
                                                                           invoices: int) -> None:
    mine = own_vault(operator)
    contract = kind_id(client, "contract")
    set_keep(client, contract, 1)  # a time, but not the switch
    old = add_document(mine, operator, "Alt", kind_id=invoices, date=date(2020, 5, 1), content=None)
    by_hand = add_document(mine, operator, "Von Hand", kind_id=invoices, content=None,
                           dates=[("keep_until", date(2024, 1, 31))])
    young = add_document(mine, operator, "Jung", kind_id=invoices, date=date(2026, 1, 5), content=None)
    plain = add_document(mine, operator, "Ohne Art", date=date(2020, 5, 1), content=None)
    other = add_document(mine, operator, "Vertrag", kind_id=contract, date=date(2020, 5, 1), content=None)
    waiting = add_document(mine, operator, "Im Eingang", kind_id=invoices, date=date(2020, 5, 1), status="inbox",
                           content=None)
    gone = add_document(mine, operator, "Schon weg", kind_id=invoices, date=date(2020, 5, 1), content=None)
    assert client.delete(f"/api/v1/documents/{gone}").status_code == 200
    seq = document(old).change_seq
    assert run_day() == 2
    for expired in (old, by_hand):
        found = document(expired)
        assert (found.status, found.trashed_status, found.trashed_at) == ("trash", "filed", NOW)
    assert document(old).change_seq > seq
    for stays in (young, plain, other, waiting):
        assert document(stays).status in ("filed", "inbox")
    # The history says who did it: nobody (nexpaper itself), and until when it was to be kept.
    (line,) = lines(old)
    assert line.user_id is None and line.by_link == "" and line.detail == {"keep_until": "2021-12-31"}
    assert lines(by_hand)[0].detail == {"keep_until": "2024-01-31"}
    assert lines(gone) == [] and lines(waiting) == []
    shown = client.get(f"/api/v1/documents/{old}/events").json()
    assert shown[0]["action"] == "auto_trashed" and shown[0]["by"] is None
    # The trash knows it: 30 days, and it comes back.
    assert client.post(f"/api/v1/documents/{old}/restore").status_code == 200
    assert document(old).status == "filed"
    # The feed of the programs saw the change.
    feed = client.get("/api/v1/changes", params={"since": seq}).json()
    assert old in [item["document"]["id"] for item in feed["items"] if item.get("document")]


def test_a_kind_without_the_switch_loses_nothing(client: TestClient, operator: Account) -> None:
    kind = kind_id(client, "invoice")
    set_keep(client, kind, 1)
    doc = add_document(own_vault(operator), operator, "Alt", kind_id=kind, date=date(2020, 5, 1), content=None)
    assert run_day() == 0
    assert document(doc).status == "filed"
    switch(client, kind)
    switch(client, kind, False)
    assert run_day() == 0 and document(doc).status == "filed"
    # What the switch does not touch: the list of what may go still has it.
    assert client.get("/api/v1/keeping").json()["total"] == 1


def test_the_time_may_not_be_over_yet(client: TestClient, operator: Account, invoices: int) -> None:
    mine = own_vault(operator)
    doc = add_document(mine, operator, "Heute", kind_id=invoices, content=None, dates=[("keep_until", TODAY)])
    assert run_day() == 0, "a term is over on the day after its date"
    assert document(doc).status == "filed"
    assert run_day(TODAY + DAY) == 1
    assert document(doc).status == "trash"


def test_a_document_is_put_in_the_trash_once_only(client: TestClient, operator: Account, invoices: int) -> None:
    doc = add_document(own_vault(operator), operator, "Alt", kind_id=invoices, date=date(2020, 5, 1), content=None)
    assert run_day() == 1
    assert client.post(f"/api/v1/documents/{doc}/restore").status_code == 200
    assert run_day() == 0 and run_day(TODAY + DAY) == 0 and run_day(TODAY + 40 * DAY) == 0
    assert document(doc).status == "filed" and len(lines(doc)) == 1
    # Put in the trash by the person, it is theirs: restored again it stays too.
    assert client.delete(f"/api/v1/documents/{doc}").status_code == 200
    assert client.post(f"/api/v1/documents/{doc}/restore").status_code == 200
    assert run_day(TODAY + 50 * DAY) == 0


def test_two_runs_at_the_same_time_take_each_document_once(client: TestClient, operator: Account, invoices: int,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(autotrash, "BATCH", 2)
    mine = own_vault(operator)
    ids = [add_document(mine, operator, f"Alt {n}", kind_id=invoices, date=date(2020, 5, 1), content=None)
           for n in range(9)]
    start = threading.Barrier(3)
    done: list[int] = []

    def one() -> None:
        start.wait()
        done.append(run_day())

    threads = [threading.Thread(target=one) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(30)
    assert sorted(done) != [] and sum(done) == 9, done
    assert all(len(lines(i)) == 1 for i in ids)
    assert all(document(i).status == "trash" for i in ids)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Event).where(Event.action == autotrash.AUTO_TRASHED)) == 9


def test_the_brake_holds_for_the_day_across_runs_and_restarts(client: TestClient, operator: Account,
                                                              invoices: int) -> None:
    mine = own_vault(operator)
    ids = [add_document(mine, operator, f"Alt {n}", kind_id=invoices, date=date(2020, 5, 1), content=None)
           for n in range(5)]
    assert run_day(limit=2) == 2
    # Another run the same day (a restart, the next hour): the count of the day is in the database.
    assert run_day(limit=2) == 0
    assert sum(1 for i in ids if document(i).status == "trash") == 2
    with SessionLocal() as db:
        assert db.get(Counter, autotrash.DONE_COUNTER).value == 2  # type: ignore[union-attr]
    # A clock that jumps back does not give the day's brake again.
    assert run_day(TODAY - DAY, limit=2) == 0
    # The next day: two more, then the rest on the day after.
    assert run_day(TODAY + DAY, limit=2) == 2
    assert run_day(TODAY + 2 * DAY, limit=2) == 1
    assert run_day(TODAY + 3 * DAY, limit=2) == 0
    assert all(document(i).status == "trash" for i in ids)


def test_the_brake_is_500_a_day(client: TestClient, operator: Account, invoices: int,
                                monkeypatch: pytest.MonkeyPatch) -> None:
    assert autotrash.DAY_LIMIT == 500
    monkeypatch.setattr(autotrash, "DAY_LIMIT", 3)
    mine = own_vault(operator)
    for n in range(4):
        add_document(mine, operator, f"Alt {n}", kind_id=invoices, date=date(2020, 5, 1), content=None)
    assert run_day() == 3
    assert run_day(TODAY + DAY) == 1


def test_switching_off_between_two_runs_stops_it(client: TestClient, operator: Account, invoices: int) -> None:
    mine = own_vault(operator)
    first = add_document(mine, operator, "Eins", kind_id=invoices, date=date(2020, 5, 1), content=None)
    second = add_document(mine, operator, "Zwei", kind_id=invoices, date=date(2020, 5, 1), content=None)
    assert run_day(limit=1) == 1
    switch(client, invoices, False)
    assert run_day(TODAY + DAY, limit=1) == 0
    assert sorted(document(i).status for i in (first, second)) == ["filed", "trash"]


def test_a_document_in_another_vault_is_judged_by_its_own_kind(client: TestClient, operator: Account) -> None:
    editor = make_account("editor")
    household = shared_vault("Haushalt", operator, (editor, "edit"))
    marked = client.post("/api/v1/kinds", json={"name": "Beleg", "vault_id": household}).json()["id"]
    plain = client.post("/api/v1/kinds", json={"name": "Beleg", "vault_id": own_vault(operator)}).json()["id"]
    for kind in (marked, plain):
        set_keep(client, kind, 1)
    switch(client, marked)
    a = add_document(household, operator, "Haus", kind_id=marked, date=date(2020, 5, 1), content=None)
    b = add_document(own_vault(operator), operator, "Mein", kind_id=plain, date=date(2020, 5, 1), content=None)
    assert run_day() == 1
    assert (document(a).status, document(b).status) == ("trash", "filed")
    # A kind a document brings along to another vault does not bring the switch (the manager there decides).
    c = add_document(household, operator, "Zieht um", kind_id=marked, date=date(2020, 5, 1), content=None)
    other = shared_vault("Büro", operator)
    assert client.post(f"/api/v1/documents/{c}/move", json={"vault_id": other}).status_code == 200
    moved = document(c)
    with SessionLocal() as db:
        kind = db.get(Kind, moved.kind_id)
        assert kind is not None and kind.vault_id == other and kind.keep_years == 1 and kind.auto_trash is False


def test_the_loop_runs_once_and_stops(client: TestClient, operator: Account, invoices: int,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    doc = add_document(own_vault(operator), operator, "Alt", kind_id=invoices, date=date(2020, 5, 1), content=None)

    async def go() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(autotrash.run_forever(stop))
        for _ in range(100):
            await asyncio.sleep(0.05)
            if document(doc).status == "trash":
                break
        stop.set()
        await asyncio.wait_for(task, 5)

    asyncio.run(go())
    assert document(doc).status == "trash"


def test_the_task_changes_nothing_of_a_document_beyond_the_trash(client: TestClient, operator: Account,
                                                                 invoices: int) -> None:
    doc = add_document(own_vault(operator), operator, "Alt", kind_id=invoices, date=date(2020, 5, 1), content=None)
    before = document(doc)
    run_day()
    after = document(doc)
    changed = {c.name for c in Document.__table__.columns if getattr(before, c.name) != getattr(after, c.name)}
    assert changed == {"status", "trashed_status", "trashed_at", "change_seq"}


def test_the_backup_holds_the_switch_the_marks_and_the_count_of_the_day(client: TestClient, operator: Account,
                                                                        invoices: int, tmp_path: Path) -> None:
    doc = add_document(own_vault(operator), operator, "Alt", kind_id=invoices, date=date(2020, 5, 1), content=None)
    assert run_day() == 1
    path = backups.create(kind=backups.MANUAL)
    try:
        with zipfile.ZipFile(path) as archive:
            copy = tmp_path / "copy.db"
            copy.write_bytes(archive.read(backups.DATABASE_ENTRY))
        with closing(sqlite3.connect(copy)) as connection:
            assert connection.execute("SELECT auto_trash FROM kinds WHERE id = ?", (invoices,)).fetchone() == (1,)
            assert connection.execute("SELECT count(*) FROM events WHERE document_id = ? AND action = 'auto_trashed'",
                                      (doc,)).fetchone() == (1,)
            assert connection.execute("SELECT value FROM counters WHERE name = ?",
                                      (autotrash.DONE_COUNTER,)).fetchone() == (1,)
        brief = backups.check(path.name)
        assert brief.usable and brief.schema == database.SCHEMA_VERSION
    finally:
        path.unlink(missing_ok=True)
