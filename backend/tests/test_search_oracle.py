"""After random sequences of every kind of change (fields, notes, trash, moves, shares, members) the search equals a
brute-force oracle, for two people."""

from __future__ import annotations

import random

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import (
    TRASH,
    Account,
    Document,
    DocumentTag,
    Note,
    Sender,
    Tag,
    VaultMember,
    Version,
    VersionText,
)
from app.services import documents, searchtext

from .conftest import make_account, new_client
from .papers import add_document, own_vault, shared_vault
from .searching import give_text


@pytest.fixture(autouse=True)
def no_brake(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests search far more often than a person can: the brake of the search (tested in ``test_search.py``)
    stays out of the way."""
    from app.services import brakes

    monkeypatch.setitem(brakes.LIMITS, "search", 100_000)

WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima",
         "mike", "straße", "müller", "ab", "xy"]


def oracle(uid: int, word: str, trash: bool = False) -> set[int]:
    w = searchtext.fold(word)
    out = set()
    with SessionLocal() as db:
        vaults = set(db.scalars(select(VaultMember.vault_id).where(VaultMember.user_id == uid)))
        from app.models import Share
        shared = set(db.scalars(select(Share.document_id).where(Share.user_id == uid)))
        for d in db.scalars(select(Document)):
            if d.vault_id not in vaults and d.id not in shared:
                continue
            if trash:
                if d.status != TRASH or d.owner_id != uid:
                    continue
            elif d.status == TRASH:
                continue
            sender = db.scalar(select(Sender.name).where(Sender.id == d.sender_id)) if d.sender_id else ""
            body = db.scalar(select(VersionText.text).join(Version, Version.id == VersionText.version_id)
                             .where(Version.document_id == d.id, Version.n == d.current_version)) or ""
            notes = " ".join(db.scalars(select(Note.text).where(Note.document_id == d.id)))
            tags = " ".join(db.scalars(select(Tag.name).join(DocumentTag, DocumentTag.tag_id == Tag.id)
                                       .where(DocumentTag.document_id == d.id)))
            fields = [searchtext.fold(x or "") for x in (d.title, sender, body.replace("\f", "\n"), notes, tags)]
            if len(w) >= searchtext.MIDDLE_MIN:
                hit = any(w in f for f in fields)
            else:
                # whole-word / start of a word match for short words
                import re
                hit = any(re.search(r"(?<![^\W_])" + re.escape(w) + (r"(?![^\W_])" if len(w) == 1 else ""), f) for f in fields)
            if hit:
                out.add(d.id)
    return out


def result(client: TestClient, word: str, trash: bool = False) -> set[int]:
    got = set()
    cursor = None
    while True:
        params = {"q": word, "limit": 100, "trash": "true" if trash else "false"}
        if cursor:
            params["cursor"] = cursor
        r = client.get("/api/v1/search", params=params)
        assert r.status_code == 200, r.text
        j = r.json()
        got |= {i["document"]["id"] for i in j["items"]}
        if not j["next"]:
            assert j["total"] == len(got), (word, j["total"], len(got))
            return got
        cursor = j["next"]


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_random_changes_keep_the_index_right(client: TestClient, operator: Account, seed: int) -> None:
    rng = random.Random(seed)
    jule, tom = make_account("jule"), make_account("tom")
    shared = shared_vault("Haushalt", operator, (jule, "manage"), (tom, "edit"))
    mine = own_vault(jule)
    toms = own_vault(tom)
    vaults = [shared, mine]
    docs: list[int] = []
    for _ in range(8):
        docs.append(add_document(rng.choice(vaults), jule, f"{rng.choice(WORDS)} {rng.choice(WORDS)}",
                                 sender=rng.choice(["Hansa " + rng.choice(WORDS), None])))
        give_text(docs[-1], " ".join(rng.choices(WORDS, k=6)), " ".join(rng.choices(WORDS, k=3)))
    with new_client(jule) as jc, new_client(tom) as tc, new_client(operator) as oc:
        for step in range(60):
            op = rng.choice(["title", "sender", "tags", "note", "note_edit", "note_del", "trash", "restore", "move",
                             "text", "rename_sender", "rename_tag", "share", "unshare", "member", "new", "purge",
                             "move_tom"])
            d = rng.choice(docs) if docs else None
            if op == "new":
                docs.append(add_document(rng.choice(vaults), jule, rng.choice(WORDS)))
                give_text(docs[-1], rng.choice(WORDS))
            elif d is None:
                continue
            elif op == "title":
                jc.patch(f"/api/v1/documents/{d}", json={"title": f"{rng.choice(WORDS)} {rng.choice(WORDS)}"})
            elif op == "sender":
                jc.patch(f"/api/v1/documents/{d}", json={"sender": rng.choice(["Firma " + rng.choice(WORDS), "", None])})
            elif op == "tags":
                jc.patch(f"/api/v1/documents/{d}", json={"tags": rng.sample(WORDS[:8], rng.randint(0, 3))})
            elif op == "note":
                jc.post(f"/api/v1/documents/{d}/notes", json={"text": f"Notiz {rng.choice(WORDS)}"})
            elif op == "note_edit":
                _r = jc.get(f"/api/v1/documents/{d}/notes"); notes = _r.json() if _r.status_code == 200 else []
                if notes:
                    jc.put(f"/api/v1/documents/{d}/notes/{notes[0]['id']}", json={"text": f"Neu {rng.choice(WORDS)}"})
            elif op == "note_del":
                _r = jc.get(f"/api/v1/documents/{d}/notes"); notes = _r.json() if _r.status_code == 200 else []
                if notes:
                    jc.delete(f"/api/v1/documents/{d}/notes/{notes[-1]['id']}")
            elif op == "trash":
                jc.delete(f"/api/v1/documents/{d}")
            elif op == "restore":
                jc.post(f"/api/v1/documents/{d}/restore")
            elif op == "move":
                jc.post(f"/api/v1/documents/{d}/move", json={"vault_id": rng.choice(vaults)})
            elif op == "move_tom":
                tc.post(f"/api/v1/documents/{d}/move", json={"vault_id": rng.choice([shared, toms])})
            elif op == "text":
                give_text(d, " ".join(rng.choices(WORDS, k=5)))
            elif op == "rename_sender":
                groups = jc.get("/api/v1/senders").json()
                if groups and groups[0].get("items"):
                    jc.patch(f"/api/v1/senders/{groups[0]['items'][0]['id']}", json={"name": "Umbenannt " + rng.choice(WORDS)})
                elif groups:
                    pass
            elif op == "rename_tag":
                groups = jc.get("/api/v1/tags").json()
                if groups and groups[0].get("items"):
                    jc.patch(f"/api/v1/tags/{groups[0]['items'][0]['id']}", json={"name": "T" + rng.choice(WORDS)})
            elif op == "share":
                jc.put(f"/api/v1/documents/{d}/shares/{tom.id}", json={"right": "read"})
            elif op == "unshare":
                jc.delete(f"/api/v1/documents/{d}/shares/{tom.id}")
            elif op == "member":
                if rng.random() < 0.5:
                    oc.delete(f"/api/v1/vaults/{shared}/members/{tom.id}")
                else:
                    oc.put(f"/api/v1/vaults/{shared}/members/{tom.id}", json={"right": "edit"})
            elif op == "purge":
                with SessionLocal() as db:
                    from app.services import changes
                    changes.write_lock(db)
                    doc = db.get(Document, d)
                    if doc is not None and doc.status == TRASH:
                        documents.delete_for_good(db, doc)
                        db.commit()
                        docs.remove(d)
                    else:
                        db.rollback()
            # check after every step, for both people, for a handful of words
            for client_, acc in ((jc, jule), (tc, tom)):
                for word in rng.sample(WORDS, 5):
                    expect = oracle(acc.id, word)
                    got = result(client_, word)
                    assert got == expect, (seed, step, op, acc.name, word, sorted(got ^ expect))
                if step % 7 == 0:
                    word = rng.choice(WORDS)
                    assert result(client_, word, trash=True) == oracle(acc.id, word, trash=True), (seed, step, op, "trash")
    # consistency of the physical tables
    with SessionLocal() as db:
        ids = set(db.scalars(select(Document.id)))
        fts = {r[0] for r in db.execute(text("SELECT rowid FROM doc_fts_docsize"))}
        tri = {r[0] for r in db.execute(text("SELECT rowid FROM doc_tri_docsize"))}
        assert fts == ids and tri == ids, (len(ids), len(fts), len(tri), sorted(fts ^ ids)[:5])


def test_account_deletion_with_documents_leaves_no_index(client: TestClient, operator: Account) -> None:
    from .conftest import PASSWORD
    jule = make_account("jule")
    d = add_document(own_vault(jule), jule, "Alpha")
    give_text(d, "bravo charlie")
    answer = client.request("DELETE", f"/api/v1/accounts/{jule.id}", json={
        "current_password": PASSWORD, "confirm_name": jule.name, "documents": "delete_documents"})
    assert answer.status_code == 204, answer.text
    with SessionLocal() as db:
        for t in ("doc_fts_docsize", "doc_tri_docsize"):
            assert db.scalar(text(f"SELECT count(*) FROM {t}")) == 0, t  # noqa: S608 - fixed names
        assert db.scalar(text("SELECT count(*) FROM search_entries")) == 0
        assert db.scalar(text("SELECT count(*) FROM version_texts")) == 0
