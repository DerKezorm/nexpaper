"""Many documents changed at once from the archive's table (A1, ``POST /api/v1/documents/bulk``): every document on its
own with the right a single change needs, a line in its history and a new change number; the answer counts honestly
and never tells a document the caller may not see from one they may only read."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Account, Document, Event, Kind, Sender, Tag
from app.services import documents

from .conftest import make_account, new_client
from .papers import add_document, own_vault, shared_vault
from .test_search_rights import raw_key

PATH = "/api/v1/documents/bulk"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def names_of(document_id: int) -> list[str]:
    """The tags a document carries, by name."""
    from app.models import DocumentTag

    with SessionLocal() as db:
        return sorted(db.scalars(select(Tag.name).join(DocumentTag, DocumentTag.tag_id == Tag.id)
                                 .where(DocumentTag.document_id == document_id)))


def events_of(document_id: int, action: str | None = None) -> list[Event]:
    with SessionLocal() as db:
        found = list(db.scalars(select(Event).where(Event.document_id == document_id).order_by(Event.id)))
        for event in found:
            db.expunge(event)
    return [e for e in found if action is None or e.action == action]


def seq_of(document_id: int) -> int:
    with SessionLocal() as db:
        row = db.get(Document, document_id)
        assert row is not None
        return row.change_seq


def bulk(client: TestClient, ids: list[int], action: str, **more: Any) -> dict[str, Any]:
    answer = client.post(PATH, json={"ids": ids, "action": action, **more})
    assert answer.status_code == 200, answer.text
    return answer.json()  # type: ignore[no-any-return]


@pytest.fixture
def town(client: TestClient, operator: Account) -> dict[str, Any]:
    """A household: jule manages it, tom may change things, lea may only read. jule's own vault, one document of it
    shared with tom to read and one to change."""
    jule, tom, lea = (make_account(n) for n in ("jule", "tom", "lea"))
    house = shared_vault("Haushalt", operator, (jule, "manage"), (tom, "edit"), (lea, "read"))
    office = shared_vault("Büro", operator, (jule, "manage"), (tom, "edit"))
    archive = shared_vault("Ablage", operator, (jule, "manage"), (tom, "read"))
    mine = own_vault(jule)
    one = add_document(house, jule, "Strom Oktober", sender="Stadtwerke Lindenau", tags=["strom"], amount=4200)
    two = add_document(house, tom, "Gas November", sender="Stadtwerke Lindenau")
    private = add_document(mine, jule, "Arztbrief")
    seen = add_document(mine, jule, "Versicherung")
    shared_edit = add_document(mine, jule, "Mietvertrag")
    with new_client(jule) as c:
        assert c.put(f"/api/v1/documents/{seen}/shares/{tom.id}", json={"right": "read"}).status_code == 200
        assert c.put(f"/api/v1/documents/{shared_edit}/shares/{tom.id}", json={"right": "edit"}).status_code == 200
    return {"jule": jule, "tom": tom, "lea": lea, "house": house, "office": office, "archive": archive, "mine": mine,
            "one": one, "two": two, "private": private, "seen": seen, "shared_edit": shared_edit}


def test_mixed_rights_change_only_what_the_caller_may_change_and_count_honestly(town: dict[str, Any]) -> None:
    t = town
    before = {d: seq_of(d) for d in (t["private"], t["seen"])}
    with new_client(t["tom"]) as c:
        done = bulk(c, [t["one"], t["two"], t["private"], t["seen"], t["shared_edit"], 2**31 - 1], "add_tag",
                    tag="steuer2026")
    assert done["changed"] == [t["one"], t["two"], t["shared_edit"]]
    assert done["reasons"] == {"forbidden": 3}
    skipped = {s["id"]: s for s in done["skipped"]}
    # Not to see, only to read, not there at all: one and the same answer.
    assert skipped[t["private"]] == {"id": t["private"], "reason": "forbidden"}
    assert skipped[t["seen"]] == {"id": t["seen"], "reason": "forbidden"}
    assert skipped[2**31 - 1] == {"id": 2**31 - 1, "reason": "forbidden"}
    for d in (t["one"], t["two"], t["shared_edit"]):
        assert "steuer2026" in names_of(d)
        changed = events_of(d, "changed")
        assert len(changed) == 1 and changed[0].user_id == t["tom"].id and changed[0].detail == {"fields": ["tags"]}
    for d, seq in before.items():
        assert seq_of(d) == seq and "steuer2026" not in names_of(d) and events_of(d, "changed") == []


def test_every_change_takes_a_new_number(town: dict[str, Any]) -> None:
    t = town
    old = [seq_of(t["one"]), seq_of(t["two"])]
    with new_client(t["jule"]) as c:
        bulk(c, [t["one"], t["two"]], "add_tag", tag="haus")
    new = [seq_of(t["one"]), seq_of(t["two"])]
    assert new[0] > max(old) and new[1] > max(old) and new[0] != new[1]


def test_a_reader_changes_nothing(town: dict[str, Any]) -> None:
    t = town
    with new_client(t["lea"]) as c:
        done = bulk(c, [t["one"], t["two"]], "trash")
    assert done == {"changed": [], "skipped": [{"id": t["one"], "reason": "forbidden"},
                                               {"id": t["two"], "reason": "forbidden"}], "reasons": {"forbidden": 2}}
    with SessionLocal() as db:
        assert {db.get(Document, d).status for d in (t["one"], t["two"])} == {"filed"}  # type: ignore[union-attr]


def test_a_stranger_learns_nothing(town: dict[str, Any]) -> None:
    t = town
    out = make_account("outsider")
    with new_client(out) as c:
        mine = add_document(own_vault(out), out, "Eigenes")
        done = bulk(c, [t["one"], 2**31 - 2, mine], "add_tag", tag="x")
    assert done["changed"] == [mine]
    assert done["skipped"] == [{"id": t["one"], "reason": "forbidden"}, {"id": 2**31 - 2, "reason": "forbidden"}]
    assert "x" not in names_of(t["one"])


def test_more_than_500_are_refused_and_nothing_changes(town: dict[str, Any]) -> None:
    t = town
    with new_client(t["jule"]) as c:
        answer = c.post(PATH, json={"ids": [t["one"]] * 501, "action": "add_tag", "tag": "zu-viel"})
        assert answer.status_code == 422
        assert c.post(PATH, json={"ids": [], "action": "trash"}).status_code == 422
        assert c.post(PATH, json={"ids": [t["one"]], "action": "delete"}).status_code == 422
        assert c.post(PATH, json={"ids": [t["one"]], "action": "add_tag"}).json()["detail"]["code"] == "invalid_input"
        assert c.post(PATH, json={"ids": [t["one"]], "action": "add_tag", "tag": "a\x00b"}).status_code == 422
    assert "zu-viel" not in names_of(t["one"])


def test_500_at_once_go_through(town: dict[str, Any]) -> None:
    t = town
    with SessionLocal() as db:
        ids = [documents.create(db, vault_id=t["house"], owner_id=t["jule"].id, title=f"Beleg {n}").id
               for n in range(500)]
    with new_client(t["jule"]) as c:
        done = bulk(c, ids, "add_tag", tag="massen")
    assert len(done["changed"]) == 500 and done["skipped"] == []


def test_the_same_number_twice_counts_once(town: dict[str, Any]) -> None:
    t = town
    with new_client(t["jule"]) as c:
        done = bulk(c, [t["one"], t["two"], t["one"], t["two"], t["one"]], "add_tag", tag="doppelt")
    assert done["changed"] == [t["one"], t["two"]] and done["skipped"] == []
    assert len(events_of(t["one"], "changed")) == 1


def test_unchanged_is_counted_as_such(town: dict[str, Any]) -> None:
    t = town
    with new_client(t["jule"]) as c:
        done = bulk(c, [t["one"], t["two"]], "add_tag", tag="Strom")  # `one` has it already (other case)
        assert done["changed"] == [t["two"]] and done["reasons"] == {"unchanged": 1}
        done = bulk(c, [t["one"], t["two"]], "remove_tag", tag="STROM")
        assert done["changed"] == [t["one"], t["two"]]
        done = bulk(c, [t["one"]], "remove_tag", tag="strom")
        assert done["reasons"] == {"unchanged": 1}
    assert names_of(t["one"]) == [] and names_of(t["two"]) == []


def test_the_trash(town: dict[str, Any]) -> None:
    t = town
    with new_client(t["jule"]) as c:
        assert c.delete(f"/api/v1/documents/{t['two']}").status_code == 200
        done = bulk(c, [t["one"], t["two"]], "add_tag", tag="weg")
        assert done["changed"] == [t["one"]] and done["skipped"] == [{"id": t["two"], "reason": "in_trash"}]
        done = bulk(c, [t["one"], t["two"]], "trash")
        assert done["changed"] == [t["one"]] and done["skipped"] == [{"id": t["two"], "reason": "unchanged"}]
    with SessionLocal() as db:
        assert db.get(Document, t["one"]).status == "trash"  # type: ignore[union-attr]
    assert len(events_of(t["one"], "trashed")) == 1 and len(events_of(t["two"], "trashed")) == 1


def _vault_kind(vault_id: int, name: str) -> int:
    with SessionLocal() as db:
        row = Kind(vault_id=vault_id, name=name, name_key=name.casefold(), key="", hue=10, position=99)
        db.add(row)
        db.commit()
        return row.id


def _server_kind() -> int:
    from app.services import catalog

    with SessionLocal() as db:
        catalog.ensure_kinds(db)
        db.commit()
        return int(db.scalar(select(Kind.id).where(Kind.vault_id.is_(None)).order_by(Kind.id)) or 0)


def test_a_kind_of_a_vault_only_for_its_documents(town: dict[str, Any]) -> None:
    t = town
    office_doc = add_document(t["office"], t["jule"], "Büromiete")
    house_kind = _vault_kind(t["house"], "Nebenkosten")
    with new_client(t["jule"]) as c:
        done = bulk(c, [t["one"], office_doc, t["two"]], "kind", kind_id=house_kind)
        assert done["changed"] == [t["one"], t["two"]]
        assert done["skipped"] == [{"id": office_doc, "reason": "kind_elsewhere"}]
        server = _server_kind()
        done = bulk(c, [t["one"], office_doc], "kind", kind_id=server)
        assert done["changed"] == [t["one"], office_doc]
        done = bulk(c, [t["one"]], "kind", kind_id=server)
        assert done["reasons"] == {"unchanged": 1}


def test_a_kind_the_caller_may_not_know_refuses_the_whole_call(town: dict[str, Any]) -> None:
    t = town
    stranger = make_account("fremd")
    hidden = _vault_kind(own_vault(stranger), "Geheim")
    with new_client(t["tom"]) as c:
        for kind_id in (hidden, 2**31 - 1):
            answer = c.post(PATH, json={"ids": [t["one"]], "action": "kind", "kind_id": kind_id})
            assert answer.status_code == 422 and answer.json()["detail"]["code"] == "kind_unknown"
    assert events_of(t["one"], "changed") == []


def test_moving_takes_sender_kind_and_tags_by_name(town: dict[str, Any]) -> None:
    t = town
    with new_client(t["tom"]) as c:
        done = bulk(c, [t["one"], t["shared_edit"], t["private"]], "move", vault_id=t["office"])
    # Through a share alone a document does not leave its vault, as with a single move.
    assert done["changed"] == [t["one"]]
    assert done["skipped"] == [{"id": t["shared_edit"], "reason": "forbidden"},
                               {"id": t["private"], "reason": "forbidden"}]
    with SessionLocal() as db:
        moved = db.get(Document, t["one"])
        assert moved is not None and moved.vault_id == t["office"]
        sender = db.get(Sender, moved.sender_id)
        assert sender is not None and sender.vault_id == t["office"] and sender.name == "Stadtwerke Lindenau"
    assert names_of(t["one"]) == ["strom"]
    assert [e.detail for e in events_of(t["one"], "moved")] == [{"from": t["house"], "to": t["office"]}]
    with new_client(t["tom"]) as c:
        assert bulk(c, [t["one"]], "move", vault_id=t["office"])["reasons"] == {"unchanged": 1}


def test_moving_into_a_vault_without_the_right_refuses_the_whole_call(town: dict[str, Any]) -> None:
    t = town
    with new_client(t["tom"]) as c:
        read_only = c.post(PATH, json={"ids": [t["one"]], "action": "move", "vault_id": t["archive"]})
        assert read_only.status_code == 403
        unseen = c.post(PATH, json={"ids": [t["one"]], "action": "move", "vault_id": t["mine"]})
        nothing = c.post(PATH, json={"ids": [t["one"]], "action": "move", "vault_id": 2**31 - 1})
        assert unseen.status_code == nothing.status_code == 404
        assert unseen.json() == nothing.json()
    assert events_of(t["one"], "moved") == []


def test_a_device_may_a_key_may_not(client: TestClient, town: dict[str, Any]) -> None:
    t = town
    assert client.put("/api/v1/settings", json={"api_keys_allowed": True}).status_code == 200
    with new_client(t["tom"]) as c:
        token = c.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with TestClient(app, base_url="http://testserver") as program:
        done = program.post(PATH, json={"ids": [t["one"], t["private"]], "action": "add_tag", "tag": "handy"},
                            headers=bearer(token))
        assert done.status_code == 200 and done.json()["changed"] == [t["one"]]
        for scope in ("read", "upload"):
            key = raw_key(t["tom"], scope)
            answer = program.post(PATH, json={"ids": [t["two"]], "action": "add_tag", "tag": "schluessel"},
                                  headers=bearer(key))
            # A key only reads: a route that changes wants a device (as every changing route answers a key).
            assert answer.status_code == 401, (scope, answer.text)
            assert answer.json()["detail"]["code"] == "token_wrong_kind"
        # Without a session or a token, nothing (a request without the tab header is refused before that).
        assert program.post(PATH, json={"ids": [t["two"]], "action": "trash"}).status_code in (400, 401)
    with TestClient(app, base_url="http://testserver", headers={"X-Nexpaper-Client": "tab-tests000"}) as anonymous:
        assert anonymous.post(PATH, json={"ids": [t["two"]], "action": "trash"}).status_code == 401
    assert "schluessel" not in names_of(t["two"])


def test_two_calls_at_the_same_moment_lose_nothing(town: dict[str, Any]) -> None:
    """Two people tag the same documents at once, each with another tag, and a third tag twice: every document ends
    with all of them, and each change is counted by exactly one of the calls."""
    t = town
    with SessionLocal() as db:
        ids = [documents.create(db, vault_id=t["house"], owner_id=t["jule"].id, title=f"Beleg {n}").id
               for n in range(25)]
    results: dict[str, dict[str, Any]] = {}
    failures: list[BaseException] = []

    def run(who: Account, key: str, tag: str) -> None:
        try:
            with new_client(who) as c:
                results[key] = bulk(c, ids, "add_tag", tag=tag)
        except BaseException as exc:  # noqa: BLE001 - reported below
            failures.append(exc)

    threads = [threading.Thread(target=run, args=(t["jule"], "a", "eins")),
               threading.Thread(target=run, args=(t["tom"], "b", "zwei")),
               threading.Thread(target=run, args=(t["jule"], "c", "drei")),
               threading.Thread(target=run, args=(t["tom"], "d", "drei"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not failures, failures
    for d in ids:
        assert names_of(d) == ["drei", "eins", "zwei"]
        assert len(events_of(d, "changed")) == 3
    assert len(results["a"]["changed"]) == len(results["b"]["changed"]) == 25
    # "drei" twice: each document changed by one of the two calls, unchanged for the other.
    assert sorted(results["c"]["changed"] + results["d"]["changed"]) == sorted(ids)
    assert results["c"]["reasons"].get("unchanged", 0) + results["d"]["reasons"].get("unchanged", 0) == 25


def test_dates_stay_as_they_were(town: dict[str, Any]) -> None:
    """A tag added to many leaves every other field alone (a whole list of tags is never sent back from a page)."""
    t = town
    with SessionLocal() as db:
        row = db.get(Document, t["one"])
        assert row is not None
        before = (row.title, row.sender_id, row.kind_id, row.date, row.amount)
    with new_client(t["jule"]) as c:
        bulk(c, [t["one"]], "add_tag", tag="neu")
    with SessionLocal() as db:
        row = db.get(Document, t["one"])
        assert row is not None and (row.title, row.sender_id, row.kind_id, row.date, row.amount) == before
    assert names_of(t["one"]) == ["neu", "strom"]
