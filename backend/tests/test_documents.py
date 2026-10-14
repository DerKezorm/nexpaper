"""Documents: reading, fields, moving, the trash, notes, the history, and who may do which of it."""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Account, Document, DocumentTag, Job, Kind, Tombstone, Version
from app.services import documents, jobs, storage

from .conftest import make_account, new_client
from .papers import PDF, add_document, document, freeze, own_vault, shared_vault


@pytest.fixture
def household(client: TestClient, operator: Account) -> dict[str, object]:
    """A shared vault with a manager (the operator), an editor, a reader, and somebody outside."""
    tom, lea, out = make_account("tom"), make_account("lea"), make_account("outsider")
    vault = shared_vault("Household", operator, (tom, "edit"), (lea, "read"))
    return {"vault": vault, "operator": operator, "tom": tom, "lea": lea, "out": out}


def kind_id(client: TestClient, key: str) -> int:
    return next(k["id"] for k in client.get("/api/v1/kinds").json() if k["key"] == key)


def test_a_member_reads_a_document_and_its_fields(client: TestClient, household: dict[str, object]) -> None:
    vault, operator = household["vault"], household["operator"]
    doc = add_document(vault, operator, "Strom Oktober", sender="Stadtwerke Lindenau", date=date(2026, 10, 6),  # type: ignore[arg-type]
                       amount=8640, tags=["Strom", "strom", "Haus"], kind_id=kind_id(client, "invoice"))
    shown = client.get(f"/api/v1/documents/{doc}").json()
    assert shown["title"] == "Strom Oktober" and shown["sender"]["name"] == "Stadtwerke Lindenau"
    assert shown["date"] == "2026-10-06" and shown["amount"] == 8640 and shown["currency"] == "EUR"
    assert shown["tags"] == ["Haus", "Strom"], "the same tag in two spellings is one"
    assert shown["kind"]["key"] == "invoice" and shown["status"] == "filed"
    assert shown["my_right"] == "manage" and shown["via_share"] is False and shown["can_share"] is True
    assert shown["owner"]["name"] == "tester" and set(shown["owner"]) == {"id", "name", "display_name"}
    with new_client(household["lea"]) as reader:  # type: ignore[arg-type]
        assert reader.get(f"/api/v1/documents/{doc}").json()["my_right"] == "read"
    with new_client(household["out"]) as outsider:  # type: ignore[arg-type]
        assert outsider.get(f"/api/v1/documents/{doc}").status_code == 404
        assert outsider.get(f"/api/v1/documents/{doc}").json() == outsider.get("/api/v1/documents/987654").json()


def test_the_list_shows_only_what_the_caller_may_see_and_pages_without_losing_any(
    client: TestClient, household: dict[str, object],
) -> None:
    vault, operator, outsider = household["vault"], household["operator"], household["out"]
    ids = [add_document(vault, operator, f"Doc {i}", content=None) for i in range(7)]
    own = add_document(own_vault(outsider), outsider, "Private")  # type: ignore[arg-type]
    seen: list[int] = []
    after = 0
    while True:
        page = client.get(f"/api/v1/documents?limit=3&after={after}").json()
        seen += [d["id"] for d in page["items"]]
        if page["next"] is None:
            break
        after = page["next"]
    assert seen == ids
    with new_client(outsider) as stranger:  # type: ignore[arg-type]
        assert [d["id"] for d in stranger.get("/api/v1/documents").json()["items"]] == [own]
        assert stranger.get(f"/api/v1/documents?vault_id={vault}").json()["items"] == []
    for wrong in ("limit=0", "limit=501", "after=-1", "vault_id=0", "status=deleted"):
        assert client.get(f"/api/v1/documents?{wrong}").status_code == 422, wrong


def test_fields_change_and_the_history_names_the_fields_not_the_values(
    client: TestClient, household: dict[str, object],
) -> None:
    vault, operator = household["vault"], household["operator"]
    doc = add_document(vault, operator, "Old title")
    changed = client.patch(f"/api/v1/documents/{doc}", json={
        "title": "  New   title ", "sender": "Elektro Brandt", "kind_id": kind_id(client, "invoice"),
        "date": "2026-10-06", "amount": 22491, "tags": ["Handwerker", "heizung"], "status": "inbox",
        "dates": [{"kind": "due", "date": "2026-10-20"}, {"kind": "warranty_end", "date": "2028-10-06"}],
    })
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["title"] == "New title" and body["sender"]["name"] == "Elektro Brandt" and body["amount"] == 22491
    assert body["tags"] == ["Handwerker", "heizung"] and body["status"] == "inbox"
    assert body["dates"] == [{"kind": "due", "date": "2026-10-20"}, {"kind": "warranty_end", "date": "2028-10-06"}]
    events = client.get(f"/api/v1/documents/{doc}/events").json()
    assert [e["action"] for e in events] == ["changed", "created"]
    assert set(events[0]["detail"]["fields"]) == {"title", "sender", "kind", "date", "amount", "status", "tags", "dates"}
    text = str(events)
    for secret in ("New title", "Elektro", "22491", "Handwerker"):
        assert secret not in text
    # Clearing works with null; fields that are not sent stay.
    cleared = client.patch(f"/api/v1/documents/{doc}", json={"sender": None, "amount": None, "date": None, "dates": []})
    assert cleared.json()["sender"] is None and cleared.json()["amount"] is None and cleared.json()["dates"] == []
    assert cleared.json()["title"] == "New title" and cleared.json()["tags"] == ["Handwerker", "heizung"]


def test_a_change_that_changes_nothing_takes_no_number_and_leaves_no_line(
    client: TestClient, household: dict[str, object],
) -> None:
    doc = add_document(household["vault"], household["operator"], "Same")  # type: ignore[arg-type]
    before = document(doc).change_seq
    again = client.patch(f"/api/v1/documents/{doc}", json={"title": "Same", "tags": [], "dates": []})
    assert again.status_code == 200
    assert document(doc).change_seq == before
    assert len(client.get(f"/api/v1/documents/{doc}/events").json()) == 1


@pytest.mark.parametrize("patch", [
    {"title": ""}, {"title": "   "}, {"title": "x" * 201}, {"title": "a\u0000b"}, {"title": None},
    {"amount": 10**13}, {"amount": 1.5}, {"amount": "12"}, {"date": "1800-01-01"}, {"date": "2999-01-01"},
    {"date": "not a date"}, {"kind_id": 999999}, {"kind_id": 0}, {"status": "trash"}, {"status": "processing"},
    {"tags": ["a" * 41]}, {"tags": [""]}, {"tags": [f"t{i}" for i in range(31)]}, {"tags": None},
    {"dates": [{"kind": "birthday", "date": "2026-01-01"}]}, {"dates": None}, {"sender": "x" * 161},
    {"sender": "a\u202eb"}, {"unknown": 1}, {"owner_id": 1}, {"vault_id": 2}, {"change_seq": 1},
])
def test_wrong_input_is_refused_and_changes_nothing(client: TestClient, household: dict[str, object], patch: dict) -> None:
    doc = add_document(household["vault"], household["operator"], "Keep")  # type: ignore[arg-type]
    before = document(doc)
    answer = client.patch(f"/api/v1/documents/{doc}", json=patch)
    assert answer.status_code == 422, (patch, answer.text)
    after = document(doc)
    assert (after.title, after.amount, after.change_seq) == (before.title, before.amount, before.change_seq)


def test_who_may_change_what(client: TestClient, household: dict[str, object]) -> None:
    vault, operator = household["vault"], household["operator"]
    doc = add_document(vault, operator, "Contract")
    other_vault = shared_vault("Other", operator, (household["tom"], "edit"))  # type: ignore[arg-type]
    changes = (
        ("patch", f"/api/v1/documents/{doc}", {"title": "x"}),
        ("post", f"/api/v1/documents/{doc}/move", {"vault_id": other_vault}),
        ("delete", f"/api/v1/documents/{doc}", None),
        ("post", f"/api/v1/documents/{doc}/restore", None),
    )
    with new_client(household["lea"]) as reader, new_client(household["out"]) as outsider:  # type: ignore[arg-type]
        for method, path, body in changes:
            kwargs = {"json": body} if body is not None else {}
            assert getattr(reader, method)(path, **kwargs).status_code == 403, (method, path)
            assert getattr(outsider, method)(path, **kwargs).status_code == 404, (method, path)
    with new_client(household["tom"]) as editor:  # type: ignore[arg-type]
        assert editor.patch(f"/api/v1/documents/{doc}", json={"title": "By Tom"}).status_code == 200
    assert document(doc).title == "By Tom"


def test_a_share_with_edit_changes_fields_but_cannot_move_or_share_on(
    client: TestClient, household: dict[str, object],
) -> None:
    operator, out = household["operator"], household["out"]
    doc = add_document(household["vault"], operator, "Shared")  # type: ignore[arg-type]
    target = shared_vault("Elsewhere", operator, (out, "edit"))  # type: ignore[arg-type]
    assert client.put(f"/api/v1/documents/{doc}/shares/{out.id}", json={"right": "edit"}).status_code == 200  # type: ignore[attr-defined]
    with new_client(out) as guest:  # type: ignore[arg-type]
        shown = guest.get(f"/api/v1/documents/{doc}").json()
        assert shown["via_share"] is True and shown["my_right"] == "edit" and shown["can_share"] is False
        assert guest.patch(f"/api/v1/documents/{doc}", json={"title": "Edited"}).status_code == 200
        assert guest.post(f"/api/v1/documents/{doc}/move", json={"vault_id": target}).status_code == 403
        assert guest.put(f"/api/v1/documents/{doc}/shares/{household['lea'].id}",  # type: ignore[attr-defined]
                         json={"right": "read"}).status_code == 403
        assert guest.get(f"/api/v1/vaults/{household['vault']}").status_code == 404
    client.put(f"/api/v1/documents/{doc}/shares/{out.id}", json={"right": "read"})  # type: ignore[attr-defined]
    with new_client(out) as guest:  # type: ignore[arg-type]
        assert guest.patch(f"/api/v1/documents/{doc}", json={"title": "No"}).status_code == 403


def test_moving_needs_edit_in_both_vaults_and_follows_with_the_file(
    client: TestClient, household: dict[str, object],
) -> None:
    operator, tom = household["operator"], household["tom"]
    mine = own_vault(operator)  # type: ignore[arg-type]
    doc = add_document(mine, operator, "Moving", sender="Anbieter", date=date(2026, 3, 14),  # type: ignore[arg-type]
                       kind_id=kind_id(client, "invoice"))
    # Edit in the target is needed; a reader's vault is not enough.
    readonly = shared_vault("Read only", household["tom"], (operator, "read"))  # type: ignore[arg-type]
    assert client.post(f"/api/v1/documents/{doc}/move", json={"vault_id": readonly}).status_code == 403
    assert client.post(f"/api/v1/documents/{doc}/move", json={"vault_id": 999999}).status_code == 404
    moved = client.post(f"/api/v1/documents/{doc}/move", json={"vault_id": household["vault"]})
    assert moved.status_code == 200 and moved.json()["vault_id"] == household["vault"]
    # Tom, an editor of the household, sees it now; the file is renamed in the background.
    with new_client(tom) as editor:  # type: ignore[arg-type]
        assert editor.get(f"/api/v1/documents/{doc}").status_code == 200
    assert jobs.run_pending() == 1
    with SessionLocal() as db:
        version = db.scalar(select(Version).where(Version.document_id == doc))
        assert version is not None and version.original_path == "Household/2026/Anbieter/2026-03-14 Rechnung.pdf"
        assert storage.safe_path(version.original_path).read_bytes() == PDF
    events = client.get(f"/api/v1/documents/{doc}/events").json()
    assert events[0]["action"] == "moved" and events[0]["detail"]["to"] == household["vault"]


def test_the_trash_keeps_a_document_for_30_days_then_it_is_gone_with_its_files(
    client: TestClient, household: dict[str, object], monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, operator = household["vault"], household["operator"]
    start = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    freeze(monkeypatch, start)
    doc = add_document(vault, operator, "Old bill", sender="Anbieter", date=date(2026, 1, 2))  # type: ignore[arg-type]
    with SessionLocal() as db:
        path = storage.safe_path(db.scalar(select(Version.original_path).where(Version.document_id == doc)))
    assert path.is_file()
    trashed = client.delete(f"/api/v1/documents/{doc}")
    assert trashed.status_code == 200 and trashed.json()["status"] == "trash"
    assert trashed.json()["trash_ends_at"] == "2026-11-07T12:00:00Z"
    assert [d["id"] for d in client.get("/api/v1/documents").json()["items"]] == []
    assert [d["id"] for d in client.get("/api/v1/documents?status=trash").json()["items"]] == [doc]
    # A trashed document cannot be changed; it is restored first.
    assert client.patch(f"/api/v1/documents/{doc}", json={"title": "x"}).status_code == 409
    freeze(monkeypatch, start + timedelta(days=29, hours=23))
    with SessionLocal() as db:
        assert documents.purge_expired(db) == 0
    freeze(monkeypatch, start + timedelta(days=30, minutes=1))
    with SessionLocal() as db:
        assert documents.purge_expired(db) == 1
    assert client.get(f"/api/v1/documents/{doc}").status_code == 404
    assert path.is_file(), "the rows are gone at once, the file goes in the background"
    jobs.run_pending()
    assert not path.exists()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 0


def test_a_restored_document_stands_where_it_stood(client: TestClient, household: dict[str, object]) -> None:
    vault, operator = household["vault"], household["operator"]
    inbox = add_document(vault, operator, "Waiting", status="inbox", content=None)  # type: ignore[arg-type]
    filed = add_document(vault, operator, "Done", content=None)  # type: ignore[arg-type]
    for doc in (inbox, filed):
        client.delete(f"/api/v1/documents/{doc}")
        assert client.delete(f"/api/v1/documents/{doc}").status_code == 200, "trashing twice is harmless"
    assert client.post(f"/api/v1/documents/{inbox}/restore").json()["status"] == "inbox"
    assert client.post(f"/api/v1/documents/{filed}/restore").json()["status"] == "filed"
    assert client.post(f"/api/v1/documents/{filed}/restore").json()["status"] == "filed"
    assert document(filed).trashed_at is None
    actions = [e["action"] for e in client.get(f"/api/v1/documents/{filed}/events").json()]
    assert actions == ["restored", "trashed", "created"]


def test_notes_everybody_who_sees_the_document_may_write_their_own_may_be_changed(
    client: TestClient, household: dict[str, object],
) -> None:
    vault, operator = household["vault"], household["operator"]
    doc = add_document(vault, operator, "Contract", content=None)  # type: ignore[arg-type]
    with new_client(household["lea"]) as reader, new_client(household["tom"]) as editor, \
            new_client(household["out"]) as outsider:  # type: ignore[arg-type]
        written = reader.post(f"/api/v1/documents/{doc}/notes", json={"text": "  Paid on the 3rd  "})
        assert written.status_code == 201 and written.json()["text"] == "Paid on the 3rd" and written.json()["mine"] is True
        note = written.json()["id"]
        assert outsider.get(f"/api/v1/documents/{doc}/notes").status_code == 404
        assert outsider.post(f"/api/v1/documents/{doc}/notes", json={"text": "x"}).status_code == 404
        seen = editor.get(f"/api/v1/documents/{doc}/notes").json()
        assert [n["text"] for n in seen] == ["Paid on the 3rd"] and seen[0]["mine"] is False
        # Only the author changes it; an editor cannot delete another's note, a manager can.
        assert editor.put(f"/api/v1/documents/{doc}/notes/{note}", json={"text": "mine now"}).status_code == 403
        assert editor.delete(f"/api/v1/documents/{doc}/notes/{note}").status_code == 403
        assert reader.put(f"/api/v1/documents/{doc}/notes/{note}", json={"text": "Paid on the 4th"}).status_code == 200
        assert editor.get(f"/api/v1/documents/{doc}/notes").json()[0]["text"] == "Paid on the 4th"
        assert reader.put(f"/api/v1/documents/{doc}/notes/999", json={"text": "x"}).status_code == 404
    assert client.get(f"/api/v1/documents/{doc}/notes").json()[0]["mine"] is True, "a manager may delete any"
    assert client.delete(f"/api/v1/documents/{doc}/notes/{note}").status_code == 204
    assert client.get(f"/api/v1/documents/{doc}/notes").json() == []
    for wrong in ("", "   ", "x" * 5001, "a\u0000b"):
        assert client.post(f"/api/v1/documents/{doc}/notes", json={"text": wrong}).status_code == 422
    assert client.get(f"/api/v1/documents/{doc}").json()["notes"] == 0


def test_the_history_hides_vaults_the_caller_is_not_in(client: TestClient, household: dict[str, object]) -> None:
    operator, lea = household["operator"], household["lea"]
    secret = shared_vault("Secret", operator)  # type: ignore[arg-type]
    doc = add_document(household["vault"], operator, "Travelling", content=None)  # type: ignore[arg-type]
    client.post(f"/api/v1/documents/{doc}/move", json={"vault_id": secret})
    client.post(f"/api/v1/documents/{doc}/move", json={"vault_id": household["vault"]})
    moves = [e for e in client.get(f"/api/v1/documents/{doc}/events").json() if e["action"] == "moved"]
    assert all(m["detail"]["from"] and m["detail"]["to"] for m in moves)
    with new_client(lea) as reader:  # type: ignore[arg-type]
        shown = [e for e in reader.get(f"/api/v1/documents/{doc}/events").json() if e["action"] == "moved"]
        assert sorted((e["detail"]["from"], e["detail"]["to"]) for e in shown if e["detail"]["from"] is None) == [(None, household["vault"])]
        assert {e["detail"]["to"] for e in shown} == {None, household["vault"]}


def test_two_changes_at_the_same_moment_both_land(client: TestClient, household: dict[str, object]) -> None:
    doc = add_document(household["vault"], household["operator"], "Race", content=None)  # type: ignore[arg-type]
    barrier = threading.Barrier(2)
    answers: list[int] = []

    def change(who: Account, body: dict) -> None:
        with new_client(who) as session:
            barrier.wait(timeout=10)
            answers.append(session.patch(f"/api/v1/documents/{doc}", json=body).status_code)

    threads = [
        threading.Thread(target=change, args=(household["operator"], {"title": "Title by one"})),
        threading.Thread(target=change, args=(household["tom"], {"amount": 500})),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert answers == [200, 200]
    result = document(doc)
    assert (result.title, result.amount) == ("Title by one", 500)
    with SessionLocal() as db:
        seqs = list(db.scalars(select(Document.change_seq)))
        assert len(seqs) == len(set(seqs))


def test_a_change_of_a_name_in_a_file_name_queues_one_rename_for_the_document(
    client: TestClient, household: dict[str, object],
) -> None:
    doc = add_document(household["vault"], household["operator"], "Renamed", content=None)  # type: ignore[arg-type]
    for sender in ("One", "Two", "Three"):
        client.patch(f"/api/v1/documents/{doc}", json={"sender": sender})
    client.patch(f"/api/v1/documents/{doc}", json={"title": "Title only"})
    with SessionLocal() as db:
        queued = list(db.scalars(select(Job).where(Job.kind == jobs.RENAME, Job.ref == doc, Job.state == "queued")))
        assert len(queued) == 1


def test_default_kinds_come_once_and_a_deleted_one_stays_deleted(client: TestClient, operator: Account) -> None:
    listed = client.get("/api/v1/kinds").json()
    assert [k["key"] for k in listed][:3] == ["invoice", "contract", "insurance"] and len(listed) == 10
    assert client.delete(f"/api/v1/kinds/{listed[0]['id']}").status_code == 204
    assert len(client.get("/api/v1/kinds").json()) == 9
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Kind)) == 9
        assert db.scalar(select(func.count()).select_from(Tombstone)) == 0
        assert db.scalar(select(func.count()).select_from(DocumentTag)) == 0


def test_notes_changed_and_deleted_are_in_the_history_without_their_text(
    client: TestClient, household: dict[str, object],
) -> None:
    doc = add_document(household["vault"], household["operator"], "Noted", content=None)  # type: ignore[arg-type]
    note = client.post(f"/api/v1/documents/{doc}/notes", json={"text": "first words"}).json()["id"]
    assert client.put(f"/api/v1/documents/{doc}/notes/{note}", json={"text": "second words"}).status_code == 200
    # The same text again changes nothing and says nothing.
    assert client.put(f"/api/v1/documents/{doc}/notes/{note}", json={"text": "second words"}).status_code == 200
    assert client.delete(f"/api/v1/documents/{doc}/notes/{note}").status_code == 204
    history = client.get(f"/api/v1/documents/{doc}/events").json()
    assert [e["action"] for e in history[:3]] == ["note_deleted", "note_changed", "note_added"]
    assert all(e["detail"] == {"note": note} for e in history[:3])
    assert "words" not in str(history)


def test_the_documents_shared_one_by_one_are_found_beyond_the_first_page(
    client: TestClient, household: dict[str, object],
) -> None:
    """The vaults page asks for these alone: with more than 200 documents in the own vaults the shared ones came last
    and fell off the page."""
    tom = household["tom"]
    mine = own_vault(tom)  # type: ignore[arg-type]
    with SessionLocal() as db:
        for n in range(230):
            documents.create(db, vault_id=mine, owner_id=tom.id, title=f"Own {n}")  # type: ignore[attr-defined]
    lea = make_account("lea2")
    shared = add_document(own_vault(lea), lea, "From Lea", content=None)
    with new_client(lea) as as_lea:
        assert as_lea.put(f"/api/v1/documents/{shared}/shares/{tom.id}", json={"right": "read"}).status_code == 200  # type: ignore[attr-defined]
    with new_client(tom) as as_tom:  # type: ignore[arg-type]
        assert shared not in [d["id"] for d in as_tom.get("/api/v1/documents?limit=200").json()["items"]]
        only = as_tom.get("/api/v1/documents?via_share=true&limit=5").json()
        assert [d["id"] for d in only["items"]] == [shared] and only["next"] is None
        assert all(d["via_share"] for d in only["items"])
        rest = as_tom.get("/api/v1/documents?via_share=false&limit=500").json()["items"]
        assert len(rest) == 230 and shared not in [d["id"] for d in rest]


def test_an_id_that_was_used_once_never_comes_again(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Programs that keep a copy go by the ids; a document deleted for good must not hand its id to the next one."""
    vault = own_vault(operator)
    start = datetime(2026, 10, 8, tzinfo=UTC)
    freeze(monkeypatch, start)
    first = add_document(vault, operator, "One", content=None)
    highest = add_document(vault, operator, "Two", content=None)
    note = client.post(f"/api/v1/documents/{highest}/notes", json={"text": "x"}).json()["id"]
    link = client.post(f"/api/v1/documents/{highest}/links", json={"recipient": "r", "days": 1}).json()["id"]
    client.delete(f"/api/v1/documents/{highest}")
    freeze(monkeypatch, start + timedelta(days=31))
    with SessionLocal() as db:
        assert documents.purge_expired(db) == 1
    freeze(monkeypatch, start)
    again = add_document(vault, operator, "Three", content=None)
    assert again > highest > first
    assert client.post(f"/api/v1/documents/{again}/notes", json={"text": "y"}).json()["id"] > note
    assert client.post(f"/api/v1/documents/{again}/links", json={"recipient": "r", "days": 1}).json()["id"] > link
    shared = client.post("/api/v1/vaults", json={"name": "Temp"}).json()["id"]
    assert client.delete(f"/api/v1/vaults/{shared}").status_code == 204
    assert client.post("/api/v1/vaults", json={"name": "Temp"}).json()["id"] > shared
