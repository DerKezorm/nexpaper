"""Schema 16 to schema 17 (``db._step_helpers``, K1): the note on a sender, the sentence of a follow-up, and the table of
pinned documents. What was there stays as it was; the backup holds the new table and column, and its trial passes."""

from __future__ import annotations

import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import db as database
from app.models import Account
from app.services import backups

from .conftest import make_account, new_client
from .papers import Date, add_document, own_vault
from .test_schema import RECORDS, schema_of, scratch, version_of  # noqa: F401 - the fixture is used by name


def old_database(path: Path) -> None:
    """A database of schema 16 with a person, a vault, a sender, a document and a dated term."""
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript((RECORDS / "v16.sql").read_text(encoding="utf-8"))
        connection.execute("INSERT INTO users (id, name, display_name, whats_new_seen, role, sign_in, password_hash, "
                           "email, oidc_subject, language, created_at, failed_logins, totp_secret_enc, totp_recovery, "
                           "totp_last_step) VALUES (1, 'jule', 'Jule', '', 'member', 'password', '', '', '', 'de', "
                           "'2026-10-01 08:00:00', 0, '', '', 0)")
        connection.execute("INSERT INTO vaults (id, name, folder, icon, created_at) VALUES (1, 'v', 'v', 'user', "
                           "'2026-11-12 08:00:00')")
        connection.execute("INSERT INTO senders (id, vault_id, name, key) VALUES (1, 1, 'Stadtwerke', 'stadtwerke')")
        connection.execute(
            "INSERT INTO documents (id, vault_id, title, sender_id, status, source, added_at, pages, current_version, "
            "change_seq, currency, trashed_status, duplicate_kind, process_error, files_state) VALUES "
            "(1, 1, 'Strom', 1, 'filed', 'upload', '2026-11-12 08:00:00', 0, 1, 1, 'EUR', '', '', '', '')")
        connection.execute("INSERT INTO document_dates (document_id, kind, date, manual) VALUES (1, 'due', "
                           "'2026-12-01', 0)")
        connection.execute("PRAGMA user_version = 16")
        connection.commit()


def test_the_column_the_column_and_the_table_come_and_nothing_else_changes(scratch: Path,  # noqa: F811
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "SCHEMA_VERSION", 17)
    old_database(scratch)
    with closing(sqlite3.connect(scratch)) as connection:
        before = schema_of(connection)
    database.init_db()
    assert version_of(scratch) == 17
    with closing(sqlite3.connect(scratch)) as connection:
        after = schema_of(connection)
        assert set(after) - set(before) == {"pins"}
        changed = {name for name in before if before[name] != after[name]}
        assert changed == {"senders", "document_dates"}
        assert after["senders"][:-1] == before["senders"] and after["senders"][-1] == ("memo", "VARCHAR(500)", 1,
                                                                                         "''", 0)
        assert after["document_dates"][-1] == ("note", "VARCHAR(200)", 1, "''", 0)
        assert connection.execute("SELECT name, memo FROM senders").fetchall() == [("Stadtwerke", "")]
        assert connection.execute("SELECT kind, date, note FROM document_dates").fetchall() == [
            ("due", "2026-12-01", "")]
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert "ix_pins_document" in indexes
        # One pin per person and document; gone with either.
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("INSERT INTO pins (user_id, document_id, created_at) VALUES (1, 1, '2026-11-12 08:00:00')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO pins (user_id, document_id, created_at) VALUES (1, 1, "
                               "'2026-11-12 08:00:00')")
        connection.execute("DELETE FROM users WHERE id = 1")
        assert connection.execute("SELECT count(*) FROM pins").fetchone() == (0,)
    # A second start takes no step again.
    database.init_db()
    assert version_of(scratch) == 17


def test_the_backup_holds_pins_notes_and_sentences_and_its_trial_passes(client: TestClient, tmp_path: Path) -> None:
    jule: Account = make_account("jule")
    doc = add_document(own_vault(jule), jule, "Strom", sender="Stadtwerke", dates=[("follow_up", Date(2026, 12, 1))])
    with new_client(jule) as browser:
        assert browser.put(f"/api/v1/documents/{doc}/pin").status_code == 200
        sender = browser.get(f"/api/v1/documents/{doc}").json()["sender"]["id"]
        assert browser.put(f"/api/v1/senders/{sender}/memo", json={"memo": "Kunde 1"}).status_code == 200
        assert browser.patch(f"/api/v1/documents/{doc}", json={"set_dates": [
            {"kind": "follow_up", "note": "nachfragen"}]}).status_code == 200
    path = backups.create(kind=backups.MANUAL)
    try:
        with zipfile.ZipFile(path) as archive:
            copy = tmp_path / "copy.db"
            copy.write_bytes(archive.read(backups.DATABASE_ENTRY))
        with closing(sqlite3.connect(copy)) as connection:
            found: list[Any] = [
                connection.execute("SELECT user_id, document_id FROM pins").fetchall(),
                connection.execute("SELECT memo FROM senders").fetchall(),
                connection.execute("SELECT kind, note FROM document_dates").fetchall(),
            ]
        assert found == [[(jule.id, doc)], [("Kunde 1",)], [("follow_up", "nachfragen")]]
        brief = backups.check(path.name)
        assert brief.usable and brief.schema == database.SCHEMA_VERSION
    finally:
        path.unlink(missing_ok=True)
