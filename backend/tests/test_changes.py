"""The feed of changes: a program that follows it ends up with exactly what the caller may see."""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal, engine
from app.models import Account, Document, Tombstone
from app.services import changes, documents, vaults

from .conftest import make_account, new_client
from .papers import add_document, freeze, own_vault, shared_vault


def pull(who: TestClient, since: int = 0, limit: int = 100) -> tuple[list[dict[str, Any]], int]:
    """Everything after ``since``, page by page; returns the items and the number to ask for next."""
    items: list[dict[str, Any]] = []
    while True:
        answer = who.get(f"/api/v1/changes?since={since}&limit={limit}")
        assert answer.status_code == 200, answer.text
        body = answer.json()
        items += body["items"]
        since = body["next"]
        if not body["more"]:
            return items, since


def kinds_of(items: list[dict[str, Any]]) -> list[tuple[str, int | None]]:
    return [(i["type"], (i["document"] or {}).get("id") or i["document_id"] or i["vault_id"]) for i in items]


@pytest.fixture
def world(client: TestClient, operator: Account) -> dict[str, Any]:
    tom, lea, out = make_account("tom"), make_account("lea"), make_account("outsider")
    vault = shared_vault("Household", operator, (tom, "edit"), (lea, "read"))
    return {"operator": operator, "tom": tom, "lea": lea, "out": out, "vault": vault}


def test_the_first_pull_gives_every_visible_document_and_the_next_gives_only_what_changed(
    client: TestClient, world: dict[str, Any],
) -> None:
    docs = [add_document(world["vault"], world["operator"], f"Doc {i}", content=None) for i in range(5)]
    secret = add_document(own_vault(world["out"]), world["out"], "Not for you", content=None)
    items, cursor = pull(client, 0, limit=2)
    assert [i["document"]["id"] for i in items] == docs and all(i["type"] == "document" for i in items)
    assert secret not in [i["document"]["id"] for i in items]
    assert pull(client, cursor) == ([], cursor), "nothing changed: nothing comes, the number stays"
    client.patch(f"/api/v1/documents/{docs[2]}", json={"title": "Changed"})
    items, newer = pull(client, cursor)
    assert kinds_of(items) == [("document", docs[2])] and items[0]["document"]["title"] == "Changed"
    assert newer > cursor and items[0]["seq"] == newer
    # A change that changes nothing makes nothing.
    client.patch(f"/api/v1/documents/{docs[2]}", json={"title": "Changed"})
    assert pull(client, newer)[0] == []
    # Every kind of change is in the feed: a note, a share, a link, the trash.
    stage = newer
    for action in (
        lambda: client.post(f"/api/v1/documents/{docs[0]}/notes", json={"text": "hello"}),
        lambda: client.put(f"/api/v1/documents/{docs[1]}/shares/{world['out'].id}", json={"right": "read"}),
        lambda: client.post(f"/api/v1/documents/{docs[3]}/links", json={"recipient": "x", "days": 1}),
        lambda: client.delete(f"/api/v1/documents/{docs[4]}"),
    ):
        action()
        items, stage = pull(client, stage)
        assert len(items) == 1 and items[0]["type"] == "document"
    assert items[0]["document"]["status"] == "trash", "a trashed document is still a document, in the trash"


def test_a_document_that_changes_between_two_pages_comes_once_with_its_new_state(
    client: TestClient, world: dict[str, Any],
) -> None:
    docs = [add_document(world["vault"], world["operator"], f"Doc {i}", content=None) for i in range(4)]
    first = client.get("/api/v1/changes?since=0&limit=2").json()
    assert first["more"] is True and [i["document"]["id"] for i in first["items"]] == docs[:2]
    client.patch(f"/api/v1/documents/{docs[0]}", json={"title": "Moved to the end"})
    rest, cursor = pull(client, first["next"], limit=2)
    assert [i["document"]["id"] for i in rest] == [docs[2], docs[3], docs[0]]
    assert rest[-1]["document"]["title"] == "Moved to the end"
    assert pull(client, cursor)[0] == []


def test_moving_to_a_vault_the_caller_is_not_in_comes_as_a_marker_without_contents(
    client: TestClient, world: dict[str, Any],
) -> None:
    doc = add_document(world["vault"], world["operator"], "Secret title", content=None)
    other = shared_vault("Management", world["operator"])
    with new_client(world["tom"]) as tom, new_client(world["lea"]) as lea:
        _, tom_cursor = pull(tom)
        _, lea_cursor = pull(lea)
        _, boss_cursor = pull(client)
        client.post(f"/api/v1/documents/{doc}/move", json={"vault_id": other})
        gone, _ = pull(tom, tom_cursor)
        assert kinds_of(gone) == [("gone", doc)]
        assert set(gone[0]) == {"seq", "type", "document", "document_id", "vault_id"} and gone[0]["document"] is None
        assert "Secret title" not in str(gone)
        assert kinds_of(pull(lea, lea_cursor)[0]) == [("gone", doc)]
        assert kinds_of(pull(client, boss_cursor)[0]) == [("document", doc)], "who still sees it gets the document"
        # And back: the members of the household get it as a document again.
        client.post(f"/api/v1/documents/{doc}/move", json={"vault_id": world["vault"]})
        assert kinds_of(pull(tom, tom_cursor)[0]) == [("document", doc)], "the marker is replaced by the document"


def test_the_marker_of_a_vault_says_lost_or_refresh_and_never_tells_a_stranger_anything(
    client: TestClient, world: dict[str, Any],
) -> None:
    vault, tom, out = world["vault"], world["tom"], world["out"]
    one = add_document(vault, world["operator"], "One", content=None)
    with new_client(tom) as tom_session, new_client(out) as stranger:
        _, tom_cursor = pull(tom_session)
        _, out_cursor = pull(stranger)
        client.put(f"/api/v1/vaults/{vault}/members/{tom.id}", json={"right": "read"})
        assert kinds_of(pull(tom_session, tom_cursor)[0]) == [("vault_refresh", vault)]
        client.put(f"/api/v1/vaults/{vault}/members/{out.id}", json={"right": "read"})
        refreshed, out_next = pull(stranger, out_cursor)
        # A program that starts from 0 holds nothing it would have to drop or fetch anew: the documents, no markers.
        assert out_cursor == 0 and kinds_of(refreshed) == [("document", one)]
        # The documents of the vault are fetched with the list; the feed went on from here.
        assert [d["title"] for d in stranger.get(f"/api/v1/documents?vault_id={vault}").json()["items"]] == ["One"]
        client.delete(f"/api/v1/vaults/{vault}/members/{tom.id}")
        assert kinds_of(pull(tom_session, tom_cursor)[0]) == [("vault_lost", vault)], "the refresh is no longer true"
        client.delete(f"/api/v1/vaults/{vault}/members/{out.id}")
        lost, _ = pull(stranger, out_next)
        assert kinds_of(lost) == [("vault_lost", vault)]
        # Somebody who was never in the vault hears nothing about it.
        with person_session("bystander") as bystander:
            assert pull(bystander)[0] == []


def person_session(name: str) -> TestClient:
    return new_client(make_account(name))


def test_a_share_that_ends_comes_as_a_marker_for_that_person_only(client: TestClient, world: dict[str, Any]) -> None:
    doc = add_document(world["vault"], world["operator"], "Shared once", content=None)
    out = world["out"]
    client.put(f"/api/v1/documents/{doc}/shares/{out.id}", json={"right": "read"})
    with new_client(out) as guest, new_client(world["tom"]) as tom:
        items, cursor = pull(guest)
        assert kinds_of(items) == [("document", doc)] and items[0]["document"]["via_share"] is True
        _, tom_cursor = pull(tom)
        client.delete(f"/api/v1/documents/{doc}/shares/{out.id}")
        assert kinds_of(pull(guest, cursor)[0]) == [("gone", doc)]
        assert kinds_of(pull(tom, tom_cursor)[0]) == [("document", doc)], "the change shows to the others as a change"


def test_a_document_deleted_for_good_comes_as_a_marker_to_the_ones_who_could_see_it(
    client: TestClient, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 10, 8, tzinfo=UTC)
    freeze(monkeypatch, start)
    doc = add_document(world["vault"], world["operator"], "Short lived", content=None)
    private = add_document(own_vault(world["out"]), world["out"], "Mine", content=None)
    client.put(f"/api/v1/documents/{doc}/shares/{world['out'].id}", json={"right": "read"})
    with new_client(world["tom"]) as tom, new_client(world["out"]) as guest, new_client(world["lea"]) as lea:
        cursors = {name: pull(who)[1] for name, who in (("tom", tom), ("out", guest), ("lea", lea))}
        client.delete(f"/api/v1/documents/{doc}")
        assert guest.delete(f"/api/v1/documents/{private}").status_code == 200
        for name, who in (("tom", tom), ("out", guest), ("lea", lea)):
            cursors[name] = pull(who, cursors[name])[1]
        freeze(monkeypatch, start + timedelta(days=31))
        with SessionLocal() as db:
            assert documents.purge_expired(db) == 2
        freeze(monkeypatch, start)  # the sessions were made at this time and would have run out
        assert kinds_of(pull(tom, cursors["tom"])[0]) == [("gone", doc)]
        assert kinds_of(pull(lea, cursors["lea"])[0]) == [("gone", doc)]
        # The guest hears of both of their documents, of nothing else (the household's other documents stay hidden).
        assert sorted(kinds_of(pull(guest, cursors["out"])[0])) == sorted([("gone", doc), ("gone", private)])
        assert [i for i in pull(client, 0)[0] if i["type"] == "document"] == []


def test_following_the_feed_while_others_write_loses_nothing(client: TestClient, world: dict[str, Any]) -> None:
    vault, operator = world["vault"], world["operator"]
    docs = [add_document(vault, operator, f"Doc {i}", content=None) for i in range(6)]
    stop = threading.Event()
    failures: list[BaseException] = []

    def write(who: Account, count: int, shift: int) -> None:
        try:
            with new_client(who) as session:
                for n in range(count):
                    target = docs[(n + shift) % len(docs)]
                    answer = session.patch(f"/api/v1/documents/{target}", json={"title": f"{who.name} {n}"})
                    assert answer.status_code == 200, answer.text
        except BaseException as exc:  # noqa: BLE001 - reported below
            failures.append(exc)

    seen: dict[int, dict[str, Any]] = {}

    def follow() -> None:
        try:
            with new_client(world["lea"]) as reader:
                cursor = 0
                while True:
                    done = stop.is_set()
                    items, cursor = pull(reader, cursor, limit=3)
                    for item in items:
                        if item["document"] is not None:
                            seen[item["document"]["id"]] = item["document"]
                    if done:
                        return
        except BaseException as exc:  # noqa: BLE001 - reported below
            failures.append(exc)

    writers = [threading.Thread(target=write, args=(operator, 25, 0)), threading.Thread(target=write, args=(world["tom"], 25, 3))]
    follower = threading.Thread(target=follow)
    follower.start()
    for thread in writers:
        thread.start()
    for thread in writers:
        thread.join()
    stop.set()
    follower.join()
    assert failures == []
    with SessionLocal() as db:
        final = {d.id: (d.title, d.change_seq) for d in db.scalars(select(Document))}
        seqs = [d.change_seq for d in db.scalars(select(Document))] + [t.seq for t in db.scalars(select(Tombstone))]
    assert len(seqs) == len(set(seqs)), "no number is used twice"
    assert {i: (d["title"], d["change_seq"]) for i, d in seen.items()} == final, "the follower ended with the true state"


def test_a_key_and_a_device_read_the_feed_and_nobody_else_does(client: TestClient, world: dict[str, Any]) -> None:
    doc = add_document(world["vault"], world["operator"], "Doc", content=None)
    token = client.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    client.put("/api/v1/settings", json={"api_keys_allowed": True})
    secret = client.post("/api/v1/api-keys", json={"name": "script", "scope": "read"}).json()["secret"]
    with TestClient(client.app, base_url="http://testserver") as program:
        for bearer in (token, secret):
            answer = program.get("/api/v1/changes", headers={"Authorization": f"Bearer {bearer}"})
            assert answer.status_code == 200 and [i["document"]["id"] for i in answer.json()["items"]] == [doc]
        assert program.get("/api/v1/changes").status_code == 401
        assert program.get("/api/v1/changes", headers={"Authorization": "Bearer npk_" + "x" * 43}).status_code == 401
    for wrong in ("since=-1", "since=x", "limit=0", "limit=501", f"since={2**63}"):
        assert client.get(f"/api/v1/changes?{wrong}").status_code == 422, wrong


# --- Found in the review --------------------------------------------------------------------------------------------


def test_a_write_between_the_two_reads_of_a_page_is_not_lost(
    client: TestClient, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The page reads the documents and then the markers. A writer that commits in between (a change to a document and a
    marker with a higher number) must not make the page jump past the change: both reads see one moment."""
    operator, tom = world["operator"], world["tom"]
    doc = add_document(world["vault"], operator, "Doc", content=None)
    other = shared_vault("Other", operator)
    with new_client(tom) as as_tom:
        _, cursor = pull(as_tom)
    real = Session.scalars
    state = {"calls": 0}

    def between(self: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
        found = real(self, statement, *args, **kwargs)
        state["calls"] += 1
        if state["calls"] == 1 and getattr(self, "_watched", False):
            with SessionLocal() as writer:
                documents.update_fields(writer, operator.id, doc, {"title": "changed"})
            with SessionLocal() as writer:
                vaults.set_member(writer, operator.id, other, tom.id, "read")
            with SessionLocal() as writer:
                vaults.remove_member(writer, operator.id, other, tom.id)
        return found

    monkeypatch.setattr(Session, "scalars", between)
    with SessionLocal() as db:
        db._watched = True  # type: ignore[attr-defined]
        with changes.snapshot(db):
            page = changes.feed(db, tom.id, cursor, 500)
    monkeypatch.undo()
    assert state["calls"] >= 2
    with SessionLocal() as db, changes.snapshot(db):
        later = changes.feed(db, tom.id, page.next, 500)
    delivered = [i.document.id for i in [*page.items, *later.items] if i.document is not None]
    assert doc in delivered, "the change came on this page or on the next one"
    assert [i.type for i in later.items] == ["document", "vault_lost"]


def test_a_fresh_program_gets_no_markers_and_a_late_member_learns_nothing_of_before(
    client: TestClient, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 10, 8, tzinfo=UTC)
    freeze(monkeypatch, start)
    vault, operator = world["vault"], world["operator"]
    early = [add_document(vault, operator, f"Early {i}", content=None) for i in range(2)]
    for doc in early:
        client.delete(f"/api/v1/documents/{doc}")
    freeze(monkeypatch, start + timedelta(days=31))
    with SessionLocal() as db:
        assert documents.purge_expired(db) == 2
    freeze(monkeypatch, start)
    late = make_account("late")
    client.put(f"/api/v1/vaults/{vault}/members/{late.id}", json={"right": "read"})
    with new_client(late) as as_late:
        items, _ = pull(as_late)
    assert items == [], "no ids of documents that were gone before"


def test_markers_older_than_ninety_days_go_and_an_older_number_starts_again(
    client: TestClient, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    freeze(monkeypatch, start)
    vault, operator = world["vault"], world["operator"]
    doc = add_document(vault, operator, "Doc", content=None)
    other = shared_vault("Other", operator)
    with new_client(world["tom"]) as as_tom:
        _, old_cursor = pull(as_tom)
        client.post(f"/api/v1/documents/{doc}/move", json={"vault_id": other})
        _, cursor = pull(as_tom, old_cursor)
        # 89 days on, nothing is removed.
        freeze(monkeypatch, start + timedelta(days=89))
        with SessionLocal() as db:
            assert changes.prune_markers(db) == 0
        freeze(monkeypatch, start)  # the sessions were made at this time
        assert kinds_of(pull(as_tom, old_cursor)[0]) == [("gone", doc)]
        freeze(monkeypatch, start + timedelta(days=91))
        with SessionLocal() as db:
            assert changes.prune_markers(db) == 1
            assert db.scalar(select(func.count()).select_from(Tombstone).where(Tombstone.kind == "gone")) == 0
        freeze(monkeypatch, start)  # the sessions were made at this time
        answer = as_tom.get(f"/api/v1/changes?since={old_cursor}")
        assert answer.status_code == 410 and answer.json()["detail"]["code"] == "sync_from_start"
        # A number at or after the removed markers goes on, and so does a new start.
        assert as_tom.get(f"/api/v1/changes?since={cursor}").status_code == 200
        assert as_tom.get("/api/v1/changes?since=0").status_code == 200
        # Pruning again remembers the highest number removed, never a lower one.
        with SessionLocal() as db:
            assert changes.prune_markers(db) == 0
            assert changes.pruned_below(db) == cursor


def test_leaving_a_vault_while_a_share_remains_brings_the_document_back_after_the_marker(
    client: TestClient, world: dict[str, Any],
) -> None:
    vault, operator, out = world["vault"], world["operator"], world["out"]
    doc = add_document(vault, operator, "Shared and member", content=None)
    hidden = add_document(vault, operator, "Only member", content=None)
    client.put(f"/api/v1/documents/{doc}/shares/{out.id}", json={"right": "read"})
    client.put(f"/api/v1/vaults/{vault}/members/{out.id}", json={"right": "read"})
    with new_client(out) as guest:
        _, cursor = pull(guest)
        client.delete(f"/api/v1/vaults/{vault}/members/{out.id}")
        items, _ = pull(guest, cursor)
        assert kinds_of(items) == [("vault_lost", vault), ("document", doc)]
        assert guest.get(f"/api/v1/documents/{doc}").status_code == 200
        assert guest.get(f"/api/v1/documents/{hidden}").status_code == 404


def test_a_document_shared_with_somebody_stays_hidden_from_a_third(client: TestClient, world: dict[str, Any]) -> None:
    """Mutation M02: the share part of the visibility rule without its person would show every shared document to
    everybody, in the list, the feed and one by one."""
    private = add_document(own_vault(world["tom"]), world["tom"], "Tom only", content=None)
    with new_client(world["tom"]) as as_tom:
        assert as_tom.put(f"/api/v1/documents/{private}/shares/{world['lea'].id}",
                          json={"right": "read"}).status_code == 200
    third = make_account("third")
    with new_client(third) as as_third, new_client(world["lea"]) as as_lea:
        assert as_third.get(f"/api/v1/documents/{private}").status_code == 404
        assert as_third.get("/api/v1/documents").json()["items"] == []
        assert as_third.get("/api/v1/documents?via_share=true").json()["items"] == []
        assert pull(as_third)[0] == []
        assert as_lea.get(f"/api/v1/documents/{private}").status_code == 200
        assert [i["document"]["id"] for i in pull(as_lea)[0] if i["document"]] == [private]


def test_the_write_lock_keeps_every_other_writer_out_until_it_ends(client: TestClient) -> None:
    """Mutation M25: without it, what a route checks and what it writes would not belong to one moment."""
    with SessionLocal() as db:
        changes.write_lock(db)
        other = sqlite3.connect(engine.url.database, timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
        finally:
            other.close()
        db.rollback()
    free = sqlite3.connect(engine.url.database, timeout=0)
    try:
        free.execute("BEGIN IMMEDIATE")
        free.rollback()
    finally:
        free.close()
