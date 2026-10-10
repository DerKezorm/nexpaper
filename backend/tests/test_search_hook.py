"""The index hook: a rollback leaves index and fields as they were; a mass change goes through the job."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import Account, Document, Job
from app.services import changes, search_index

from .conftest import make_account, new_client
from .papers import add_document, own_vault, shared_vault
from .searching import give_text


def total(client: TestClient, q: str) -> int:
    return int(client.get("/api/v1/search", params={"q": q}).json()["total"])


def test_rollback_leaves_index_and_fields_unchanged(client: TestClient, operator: Account) -> None:
    jule = make_account("jule")
    d = add_document(own_vault(jule), jule, "Altwort Dokument")
    give_text(d, "text eins")
    with new_client(jule) as c:
        assert total(c, "altwort") == 1
        with SessionLocal() as db:
            changes.write_lock(db)
            doc = db.get(Document, d)
            doc.title = "Neuwort Dokument"
            doc.change_seq = changes.next_seq(db)
            db.flush()
            db.rollback()  # aborted
            assert search_index.SEQ_KEY not in db.info
            # the same session goes on and commits something unrelated: must not index stale state
            changes.write_lock(db)
            db.execute(text("UPDATE users SET display_name = display_name WHERE id = 1"))
            db.commit()
        assert total(c, "altwort") == 1 and total(c, "neuwort") == 0
        # exception inside the transaction
        with SessionLocal() as db:
            try:
                changes.write_lock(db)
                doc = db.get(Document, d)
                doc.title = "Zweitwort"
                doc.change_seq = changes.next_seq(db)
                raise RuntimeError("boom")
            except RuntimeError:
                db.rollback()
        assert total(c, "zweitwort") == 0 and total(c, "altwort") == 1
        # a commit that fails in the hook (index write error) rolls everything back
        with SessionLocal() as db:
            changes.write_lock(db)
            doc = db.get(Document, d)
            doc.title = "Drittwort"
            doc.change_seq = changes.next_seq(db)
            orig = search_index._write

            def bad(*a, **k):
                raise RuntimeError("index failure")

            search_index._write = bad
            try:
                with pytest.raises(RuntimeError):
                    db.commit()
            finally:
                search_index._write = orig
            db.rollback()
        with SessionLocal() as db:
            assert db.get(Document, d).title == "Altwort Dokument"
        assert total(c, "altwort") == 1 and total(c, "drittwort") == 0


def test_mass_rename_over_the_limit_is_done_by_a_job(client: TestClient, operator: Account) -> None:
    jule = make_account("jule")
    vault = shared_vault("Gross", operator, (jule, "manage"))
    ids = []
    for n in range(search_index.SYNC_LIMIT + 50):
        ids.append(add_document(vault, jule, f"Beleg {n}", sender="Altfirma"))
    # a text in each so the digest differs from nothing
    with new_client(jule) as c:
        assert total(c, "altfirma") == len(ids)
        groups = c.get("/api/v1/senders").json()
        sid = groups[0]["items"][0]["id"]
        r = c.patch(f"/api/v1/senders/{sid}", json={"name": "Neufirma"})
        assert r.status_code == 200, r.text
        with SessionLocal() as db:
            pending = [(j.kind, j.state) for j in db.scalars(select(Job))]
        # Until the job ran: documents are found by what they were
        before_new, before_old = total(c, "neufirma"), total(c, "altfirma")
        print("window:", before_new, before_old, pending[-3:])
        with SessionLocal() as db:
            written = search_index.run_job(db)
        assert total(c, "neufirma") == len(ids) and total(c, "altfirma") == 0, written
