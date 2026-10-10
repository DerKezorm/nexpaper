"""The search index stays right whatever happens to a document: fields, sender (also renamed for all), tags, notes, a
new text, the trash, moving, deleting for good; many documents at once go through a job; a database from before the
index gets one at the next start."""

from __future__ import annotations

import random
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app import db as database
from app.db import SessionLocal
from app.models import Account, Document, Job, SearchEntry
from app.services import changes, documents, jobs, search_index

from .conftest import make_account, new_client
from .papers import add_document, own_vault, shared_vault
from .searching import found, give_text
from .test_schema import RECORDS, scratch, version_of  # noqa: F401 - the fixture is used by name


def index_ids(token: str, table: str = "doc_fts") -> set[int]:
    with SessionLocal() as db:
        return set(db.scalars(text(f"SELECT rowid FROM {table} WHERE {table} MATCH :q"), {"q": f'"{token}"'}))  # noqa: S608


def all_current() -> None:
    """Every document has an entry made for its last change."""
    with SessionLocal() as db:
        assert search_index.stale_ids(db, 10) == []


class Model:
    """What each document holds, as the test made it: field -> set of words."""

    def __init__(self) -> None:
        self.words: dict[int, dict[str, set[str]]] = {}
        self.gone: set[int] = set()

    def holders(self, word: str) -> set[int]:
        return {doc for doc, fields in self.words.items() if doc not in self.gone and any(word in v for v in fields.values())}

    def every_word(self) -> set[str]:
        return {w for fields in self.words.values() for values in fields.values() for w in values}


def test_the_index_follows_every_change_in_any_order(operator: Account) -> None:
    rng = random.Random(20261009)
    jule = make_account("jule")
    household = shared_vault("Haushalt", operator, (jule, "edit"))
    mine = own_vault(jule)

    def word() -> str:
        return "".join(rng.choice("bcdfghjklmnpqrstvwxz") for _ in range(9))

    model = Model()
    with new_client(jule) as client:
        ids = []
        for _ in range(5):
            title, sender = word(), word()
            made = add_document(mine, jule, title, sender=sender)
            ids.append(made)
            model.words[made] = {"title": {title}, "sender": {sender}, "text": set(), "notes": set(), "tags": set()}
        notes: dict[int, list[tuple[int, str]]] = {i: [] for i in ids}
        done: set[str] = set()
        for step in range(60):
            alive = [i for i in ids if i not in model.gone]
            doc = rng.choice(alive)
            fields = model.words[doc]
            action = rng.choice(["title", "sender", "tags", "note", "edit_note", "drop_note", "text", "trash", "move",
                                 "rename_sender", "gone"])
            if action == "gone" and len(alive) <= 3:
                action = "text"
            done.add(action)
            if action == "title":
                value = word()
                assert client.patch(f"/api/v1/documents/{doc}", json={"title": value}).status_code in (200, 409)
                if client.get(f"/api/v1/documents/{doc}").json()["status"] != "trash":
                    fields["title"] = {value}
            elif action == "sender":
                value = word()
                if client.patch(f"/api/v1/documents/{doc}", json={"sender": value}).status_code == 200:
                    fields["sender"] = {value}
            elif action == "tags":
                values = [word() for _ in range(rng.randint(0, 2))]
                if client.patch(f"/api/v1/documents/{doc}", json={"tags": values}).status_code == 200:
                    fields["tags"] = set(values)
            elif action == "note":
                value = word()
                answer = client.post(f"/api/v1/documents/{doc}/notes", json={"text": value})
                if answer.status_code == 201:
                    notes[doc].append((answer.json()["id"], value))
            elif action == "edit_note" and notes[doc]:
                index = rng.randrange(len(notes[doc]))
                value = word()
                note_id, _old = notes[doc][index]
                assert client.put(f"/api/v1/documents/{doc}/notes/{note_id}", json={"text": value}).status_code == 200
                notes[doc][index] = (note_id, value)
            elif action == "drop_note" and notes[doc]:
                note_id, _old = notes[doc].pop(rng.randrange(len(notes[doc])))
                assert client.delete(f"/api/v1/documents/{doc}/notes/{note_id}").status_code == 204
            elif action == "text":
                value = word()
                give_text(doc, f"Seite eins {value}", "Seite zwei")
                fields["text"] = {value}
            elif action == "trash":
                current = client.get(f"/api/v1/documents/{doc}").json()["status"]
                path = "restore" if current == "trash" else ""
                answer = client.post(f"/api/v1/documents/{doc}/restore") if path else client.delete(f"/api/v1/documents/{doc}")
                assert answer.status_code == 200
            elif action == "move":
                current = client.get(f"/api/v1/documents/{doc}").json()
                target = mine if current["vault_id"] == household else household
                assert client.post(f"/api/v1/documents/{doc}/move", json={"vault_id": target}).status_code in (200, 409)
            elif action == "rename_sender":
                current = client.get(f"/api/v1/documents/{doc}").json()
                if current["sender"]:
                    value = word()
                    answer = client.patch(f"/api/v1/senders/{current['sender']['id']}", json={"name": value})
                    assert answer.status_code == 200
                    old = current["sender"]["name"].lower()
                    # Every document of this vault with that sender is renamed with it.
                    for other in ids:
                        if other not in model.gone and old in model.words[other]["sender"]:
                            other_doc = client.get(f"/api/v1/documents/{other}").json()
                            if other_doc["vault_id"] == current["vault_id"]:
                                model.words[other]["sender"] = {value}
            elif action == "gone":
                with SessionLocal() as db:
                    changes.write_lock(db)
                    row = db.get(Document, doc)
                    assert row is not None
                    documents.delete_for_good(db, row)
                    db.commit()
                model.gone.add(doc)
            fields["notes"] = {value for _id, value in notes[doc]}
            jobs.run_pending(kinds=(jobs.INDEX,))
            # Every word of every document, in both indexes: exactly the documents that hold it now.
            for token in model.every_word():
                assert index_ids(token) == model.holders(token), (step, action, token)
                assert index_ids(token[2:7], "doc_tri") == model.holders(token), (step, action, token)
            all_current()
        # The sequence went through every kind of change (a floor: else the seed would test little).
        assert done == {"title", "sender", "tags", "note", "edit_note", "drop_note", "text", "trash", "move",
                        "rename_sender", "gone"}
        # The search itself agrees (the trash aside).
        for doc in [i for i in ids if i not in model.gone][:2]:
            title = next(iter(model.words[doc]["title"]))
            shown = client.get(f"/api/v1/documents/{doc}").json()
            assert (shown["title"] in found(client, title)) is (shown["status"] != "trash")
    with SessionLocal() as db:
        assert db.scalar(select(SearchEntry).where(SearchEntry.document_id.in_(model.gone))) is None


def test_many_documents_at_once_are_indexed_by_a_job_right_after(operator: Account,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_index, "SYNC_LIMIT", 5)
    jule = make_account("jule")
    vault = own_vault(jule)
    made = [add_document(vault, jule, f"Brief {n}", sender="Altname Werke") for n in range(8)]
    with new_client(jule) as client:
        sender = client.get(f"/api/v1/documents/{made[0]}").json()["sender"]["id"]
        assert client.patch(f"/api/v1/senders/{sender}", json={"name": "Neuname Werke"}).status_code == 200
        with SessionLocal() as db:
            waiting = db.scalars(select(Job).where(Job.kind == jobs.INDEX, Job.state == "queued")).all()
            assert len(waiting) == 1
        # Until the job ran, the index still knows the old name.
        assert found(client, "neuname") == set()
        jobs.run_pending(kinds=(jobs.INDEX,))
        assert found(client, "neuname") == {f"Brief {n}" for n in range(8)}
        assert found(client, "altname") == set()
    all_current()


def test_a_change_the_index_does_not_hold_writes_no_entry(operator: Account) -> None:
    jule = make_account("jule")
    made = add_document(own_vault(jule), jule, "Wasserrechnung")
    give_text(made, "Wasser und Abwasser")
    with SessionLocal() as db:
        before = db.get(SearchEntry, made)
        assert before is not None
        digest = before.digest
    written: list[int] = []
    real = search_index._write

    def counting(db: Session, document_id: int, fields: search_index.Fields) -> None:
        written.append(document_id)
        real(db, document_id, fields)

    search_index._write = counting
    try:
        with new_client(jule) as client:
            assert client.patch(f"/api/v1/documents/{made}", json={"amount": 1234, "date": "2026-02-03"}).status_code == 200
            assert written == []
            assert client.patch(f"/api/v1/documents/{made}", json={"title": "Wasser Februar"}).status_code == 200
            assert written == [made]
    finally:
        search_index._write = real
    with SessionLocal() as db:
        entry = db.get(SearchEntry, made)
        assert entry is not None and entry.digest != digest
    all_current()


def test_a_database_without_the_index_gets_it_at_the_next_start(scratch: Path) -> None:  # noqa: F811
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v5.sql").read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO users (id, name, display_name, whats_new_seen, role, sign_in, password_hash, email, oidc_subject, "
            "language, created_at, failed_logins, totp_secret_enc, totp_recovery, totp_last_step, signed_in_before, "
            "passkey_handle, ai_allowed, email_from_provider) VALUES (1, 'jule', '', '', 'member', 'password', 'x', '', '', "
            "'', '2026-01-01 00:00:00.000000', 0, '', '', 0, 0, '', 1, 0)")
        connection.execute("INSERT INTO vaults (id, name, folder, icon, personal_of, created_at, created_by) "
                           "VALUES (1, 'jule', 'jule', 'user', 1, '2026-01-01 00:00:00.000000', 1)")
        connection.execute("INSERT INTO vault_members (vault_id, user_id, \"right\") VALUES (1, 1, 'manage')")
        connection.execute("INSERT INTO senders (id, vault_id, name, key, created_by) VALUES (1, 1, 'Stadtwerke Lindenau', "
                           "'stadtwerke lindenau', 1)")
        for number, title in enumerate(("Stromrechnung März", "Gasrechnung April"), start=1):
            connection.execute(
                "INSERT INTO documents (id, vault_id, owner_id, title, sender_id, currency, status, source, added_at, pages, "
                "current_version, change_seq, trashed_status, duplicate_kind, process_error) VALUES (?, 1, 1, ?, 1, 'EUR', "
                "'filed', 'upload', '2026-01-01 00:00:00.000000', 1, 1, ?, '', '', '')", (number, title, number))
        connection.execute("INSERT INTO notes (document_id, user_id, text, created_at) VALUES (2, 1, 'Zählerfoto liegt bei', "
                           "'2026-01-01 00:00:00.000000')")
        # The first has a PDF, the second is an e-invoice that is XML only.
        for number, path in ((1, "jule/Strom.pdf"), (2, "jule/Gas.xml")):
            connection.execute(
                "INSERT INTO versions (id, document_id, n, original_path, archive_path, sha256, size, pages, created_at, "
                "note, phash) VALUES (?, ?, 1, ?, '', '', 10, 1, '2026-01-01 00:00:00.000000', '', '')",
                (number, number, path))
        connection.execute("PRAGMA user_version = 5")
        connection.commit()
    database.init_db()
    assert version_of(scratch) == database.SCHEMA_VERSION
    engine = create_engine(f"sqlite:///{scratch}")
    try:
        with Session(engine) as db:
            # The step queued the job of the index, and the reading of the text of the PDF (not of the XML).
            queued = db.execute(select(Job.kind, Job.ref).where(Job.state == "queued").order_by(Job.id)).all()
            assert [tuple(row) for row in queued] == [("index", 0), ("text", 1)]
            assert search_index.stale_ids(db, 10) == [1, 2]
            assert search_index.run_job(db) == 2
            assert search_index.stale_ids(db, 10) == []
            hits = lambda q: set(db.scalars(text("SELECT rowid FROM doc_tri WHERE doc_tri MATCH :q"), {"q": q}))
            assert hits('"rechnung"') == {1, 2}
            assert hits('"stadtwerke"') == {1, 2}
            assert hits('"zahlerfoto"') == {2}
            # Each entry carries the scope of its vault.
            assert set(db.scalars(text("SELECT rowid FROM doc_fts WHERE doc_fts MATCH '{scope} : \"v1v\"'"))) == {1, 2}
            # A second start finds nothing to do.
            search_index.queue_if_stale(db)
            assert db.scalars(select(Job.kind).where(Job.state == "queued")).all() == ["index", "text"]
    finally:
        engine.dispose()


def test_the_start_queues_the_job_when_an_entry_lags_behind(operator: Account, client: TestClient) -> None:
    jule = make_account("jule")
    made = add_document(own_vault(jule), jule, "Kaminkehrer")
    with SessionLocal() as db:
        search_index.remove(db, made)
        db.commit()
        assert search_index.stale_ids(db, 10) == [made]
        jobs.recover(db)
        assert db.scalars(select(Job.kind).where(Job.state == "queued", Job.kind == jobs.INDEX)).all() == ["index"]
    jobs.run_pending(kinds=(jobs.INDEX,))
    with new_client(jule) as browser:
        assert found(browser, "kaminkehrer") == {"Kaminkehrer"}
