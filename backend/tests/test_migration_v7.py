"""Schema 6 to schema 7 (``db._step_paperless_export``): the tables of the Paperless import and of the exports come, and
nothing that was there changes. A document taken over afterwards can be written down, and a document deleted for good
leaves its Paperless number behind (the next run does not take it again)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app import db as database

from .test_schema import RECORDS, schema_of, scratch, version_of  # noqa: F401 - the fixture is used by name


def test_the_new_tables_come_and_the_documents_stay(scratch: Path) -> None:  # noqa: F811
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v6.sql").read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO users (id, name, display_name, whats_new_seen, role, sign_in, password_hash, email, oidc_subject, "
            "language, created_at, failed_logins, totp_secret_enc, totp_recovery, totp_last_step, signed_in_before, "
            "passkey_handle, ai_allowed, email_from_provider) VALUES (1, 'jule', '', '', 'member', 'password', 'x', '', '', "
            "'', '2026-01-01 00:00:00.000000', 0, '', '', 0, 0, '', 1, 0)")
        connection.execute("INSERT INTO vaults (id, name, folder, icon, personal_of, created_at, created_by) "
                           "VALUES (1, 'jule', 'jule', 'user', 1, '2026-01-01 00:00:00.000000', 1)")
        connection.execute(
            "INSERT INTO documents (id, vault_id, owner_id, title, currency, status, source, added_at, pages, "
            "current_version, change_seq, trashed_status, duplicate_kind, process_error) VALUES (1, 1, 1, 'Strom', "
            "'EUR', 'filed', 'upload', '2026-01-01 00:00:00.000000', 1, 1, 1, '', '', '')")
        connection.execute("PRAGMA user_version = 6")
        connection.commit()
        before = schema_of(connection)
    database.init_db()
    assert version_of(scratch) == database.SCHEMA_VERSION
    with closing(sqlite3.connect(scratch)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        after = schema_of(connection)
        # What was there stays as it was; a later step may add columns at the end (schema 8 adds one to uploads).
        assert {name: columns[: len(before[name])] for name, columns in after.items() if name in before} == before
        assert {"paperless_items", "exports", "export_links"} <= set(after)
        assert connection.execute("SELECT title FROM documents").fetchall() == [("Strom",)]
        connection.execute("INSERT INTO paperless_items (origin, paperless_id, document_id, state, reason, inbox, at) "
                           "VALUES ('o', 41, 1, 'done', '', 0, '2026-01-02 00:00:00.000000')")
        connection.execute("DELETE FROM documents WHERE id = 1")
        assert connection.execute("SELECT paperless_id, document_id FROM paperless_items").fetchall() == [(41, None)]
        connection.execute("INSERT INTO exports (user_id, state, params, vault_ids, language, documents, size, total, "
                           "file, error, created_at, expires_at) VALUES (1, 'ready', '{}', '[]', 'de', 0, 0, 0, '', '', "
                           "'2026-01-02 00:00:00.000000', '2026-01-09 00:00:00.000000')")
        connection.execute("INSERT INTO export_links (export_id, recipient, token_hash, token_enc, until, opened_count, "
                           "created_by, created_at) VALUES (1, 'x', 'h', '', '2026-01-09 00:00:00.000000', 0, 1, "
                           "'2026-01-02 00:00:00.000000')")
        connection.execute("DELETE FROM exports WHERE id = 1")
        assert connection.execute("SELECT count(*) FROM export_links").fetchone() == (0,)
