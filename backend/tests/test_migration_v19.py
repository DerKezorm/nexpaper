"""Schema 18 to schema 19 (``db._step_pdf_passwords``): the table of the kept PDF passwords and the mark on a version
whose original is an encrypted PDF. Every version there is keeps its files and is marked as not protected."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app import db as database

from .test_schema import RECORDS, schema_of, scratch, version_of  # noqa: F401 - the fixture is used by name


def test_the_table_and_the_column_come_and_nothing_else_changes(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(database, "SCHEMA_VERSION", 19)
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v18.sql").read_text(encoding="utf-8"))
        connection.execute("INSERT INTO users (id, name, display_name, whats_new_seen, role, sign_in, password_hash, "
                           "email, oidc_subject, language, created_at, failed_logins, totp_secret_enc, totp_recovery, "
                           "totp_last_step) VALUES (1, 'jule', 'Jule', '', 'member', 'password', '', '', '', 'de', "
                           "'2026-10-01 08:00:00', 0, '', '', 0)")
        connection.execute("INSERT INTO vaults (id, name, folder, icon, created_at) VALUES (1, 'v', 'v', 'user', "
                           "'2026-11-12 08:00:00')")
        connection.execute(
            "INSERT INTO documents (id, vault_id, title, status, source, added_at, pages, current_version, change_seq, "
            "currency, trashed_status, duplicate_kind, process_error, files_state) VALUES "
            "(1, 1, 't', 'filed', 'upload', '2026-11-12 08:00:00', 1, 1, 1, 'EUR', '', '', '', '')")
        connection.execute("INSERT INTO versions (id, document_id, n, original_path, archive_path, sha256, size, pages, "
                           "created_at, note, phash, archive_sha256) VALUES (1, 1, 1, 'v/a.pdf', '', 'ab', 3, 1, "
                           "'2026-11-12 08:00:00', '', '', '')")
        connection.execute("PRAGMA user_version = 18")
        connection.commit()
        before = schema_of(connection)
    database.init_db()
    assert version_of(scratch) == 19
    with closing(sqlite3.connect(scratch)) as connection:
        after = schema_of(connection)
        assert set(after) - set(before) == {"pdf_passwords"}
        changed = {name for name in before if after[name] != before[name]}
        assert changed == {"versions"}
        assert after["versions"][:-1] == before["versions"]
        assert after["versions"][-1] == ("original_protected", "VARCHAR(10)", 1, "''", 0)
        assert connection.execute("SELECT original_path, original_protected FROM versions").fetchall() == [
            ("v/a.pdf", "")]
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert "ix_pdf_passwords_user_id" in indexes
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("INSERT INTO pdf_passwords (user_id, name, sealed, created_at) VALUES "
                           "(1, 'Gehalt', 'ab', '2026-11-12 08:00:00')")
        connection.execute("DELETE FROM users WHERE id = 1")
        assert connection.execute("SELECT count(*) FROM pdf_passwords").fetchone()[0] == 0, "goes with the person"
    # A second start takes no step again.
    database.init_db()
    assert version_of(scratch) == 19
