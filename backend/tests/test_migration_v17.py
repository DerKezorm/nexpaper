"""Schema 16 to schema 17 (``db._step_link_documents``): one table of its own for the further documents of a link (N2);
nothing else changes, and no link shows more than it did. The trial run of a restore counts the further documents a
restore would put back on a link."""

from __future__ import annotations

import secrets
import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import clock
from app import db as database
from app.db import SessionLocal
from app.models import Link, LinkDocument, Related
from app.services import backups

from .conftest import make_account
from .papers import add_document, own_vault
from .test_schema import RECORDS, schema_of, scratch, version_of  # noqa: F401 - the fixture is used by name


def test_the_table_comes_and_nothing_else_changes(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(database, "SCHEMA_VERSION", 17)
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v16.sql").read_text(encoding="utf-8"))
        connection.execute("PRAGMA user_version = 16")
        connection.commit()
        before = schema_of(connection)
    database.init_db()
    assert version_of(scratch) == 17
    with closing(sqlite3.connect(scratch)) as connection:
        after = schema_of(connection)
        assert {name: columns for name, columns in after.items() if name in before} == before
        assert set(after) - set(before) == {"link_documents"}
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert "ix_link_documents_document" in indexes
    # A second start takes no step again.
    database.init_db()
    assert version_of(scratch) == 17


def test_a_row_is_once_and_goes_with_its_link_or_its_document(scratch: Path,  # noqa: F811
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "SCHEMA_VERSION", 17)
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v16.sql").read_text(encoding="utf-8"))
        connection.execute("PRAGMA user_version = 16")
        connection.commit()
    database.init_db()
    with closing(sqlite3.connect(scratch)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("INSERT INTO vaults (id, name, folder, icon, created_at) VALUES (1, 'v', 'v', 'user', "
                           "'2026-11-12 08:00:00')")
        for document_id in (1, 2, 3):
            connection.execute(
                "INSERT INTO documents (id, vault_id, title, status, source, added_at, pages, current_version, "
                "change_seq, currency, trashed_status, duplicate_kind, process_error, files_state) VALUES "
                "(?, 1, 't', 'filed', 'upload', '2026-11-12 08:00:00', 0, 1, ?, 'EUR', '', '', '', '')",
                (document_id, document_id))
        for link_id in (1, 2):
            connection.execute(
                "INSERT INTO links (id, document_id, recipient, token_hash, token_enc, until, allow_download, "
                "opened_count, created_at) VALUES (?, 1, 'r', ?, '', '2026-12-01 00:00:00', 1, 0, "
                "'2026-11-12 08:00:00')", (link_id, f"h{link_id}"))
        add = ("INSERT INTO link_documents (link_id, document_id, number, created_at) "
               "VALUES (?, ?, ?, '2026-11-12 08:00:00')")
        connection.execute(add, (1, 2, 1))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(add, (1, 2, 2))
        # The number within a link is once per link, and every link starts at 1.
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(add, (1, 3, 1))
        connection.execute(add, (1, 3, 2))
        connection.execute(add, (2, 2, 1))
        connection.execute("DELETE FROM documents WHERE id = 3")
        assert connection.execute("SELECT link_id, document_id FROM link_documents ORDER BY id").fetchall() == [
            (1, 2), (2, 2)]
        connection.execute("DELETE FROM links WHERE id = 1")
        assert connection.execute("SELECT link_id, document_id FROM link_documents").fetchall() == [(2, 2)]


def test_the_trial_run_counts_the_further_documents_a_restore_puts_back(client: TestClient, operator: object) -> None:
    jule = make_account("jule")
    vault = own_vault(jule)
    main, one, two, three = (add_document(vault, jule, title) for title in ("Haupt", "Eins", "Zwei", "Drei"))
    now = clock.now()
    with SessionLocal() as db:
        for other in (one, two, three):
            db.add(Related(low_id=main, high_id=other, created_at=now))
        kept = Link(document_id=main, recipient="a", token_hash=secrets.token_hex(32), until=now + timedelta(days=7))
        revoked = Link(document_id=main, recipient="b", token_hash=secrets.token_hex(32),
                       until=now + timedelta(days=7))
        db.add_all([kept, revoked])
        db.flush()
        db.add_all([LinkDocument(link_id=kept.id, document_id=one, number=1, created_at=now),
                    LinkDocument(link_id=kept.id, document_id=two, number=2, created_at=now),
                    LinkDocument(link_id=revoked.id, document_id=three, number=1, created_at=now)])
        db.commit()
        ids = (kept.id, revoked.id)
    name = backups.create(kind=backups.MANUAL).name
    quiet = backups.check(name)
    assert (quiet.revived_links, quiet.revived_link_documents) == (0, 0)
    with SessionLocal() as db:
        # One further document taken out of the link that stays; the other link revoked with the one it showed.
        db.query(LinkDocument).filter(LinkDocument.link_id == ids[0], LinkDocument.document_id == one).delete()
        db.get(Link, ids[1]).revoked_at = now  # type: ignore[union-attr]
        db.commit()
    brief = client.post(f"/api/v1/backups/{name}/check").json()
    assert brief["usable"] is True
    assert (brief["revived_links"], brief["revived_link_documents"]) == (1, 2)
