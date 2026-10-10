"""Schema 5 to schema 6 with documents that were read before there was text: each gets a job ``text`` (the SQL of
``db._step_search``), also those that came in through the mailbox or the intake folder (schema 5), except a document
still being read (its run reads the text anyway) and an e-invoice that is XML only (it has no text to read). The job
``index`` comes once."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app import db as database

from .test_schema import RECORDS, scratch, version_of  # noqa: F401 - the fixture is used by name

DOCUMENTS = [
    # id, status, original
    (1, "filed", "jule/Strom.pdf"),
    (2, "inbox", "jule/Quittung.jpg"),
    (3, "processing", "jule/Neu.pdf"),
    (4, "filed", "jule/Rechnung.XML"),
    (5, "trash", "jule/Alt.pdf"),
    (6, "inbox", "jule/Anhang.pdf"),
    (7, "filed", "jule/Scan.pdf"),
]
#: Where a document came from, when not from an upload: the mailbox and the intake folder of schema 5.
SOURCES = {6: "mail", 7: "folder"}


def test_documents_read_before_get_a_job_that_reads_their_text(scratch: Path) -> None:  # noqa: F811
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v5.sql").read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO users (id, name, display_name, whats_new_seen, role, sign_in, password_hash, email, oidc_subject, "
            "language, created_at, failed_logins, totp_secret_enc, totp_recovery, totp_last_step, signed_in_before, "
            "passkey_handle, ai_allowed, email_from_provider) VALUES (1, 'jule', '', '', 'member', 'password', 'x', '', '', "
            "'', '2026-01-01 00:00:00.000000', 0, '', '', 0, 0, '', 1, 0)")
        connection.execute("INSERT INTO vaults (id, name, folder, icon, personal_of, created_at, created_by) "
                           "VALUES (1, 'jule', 'jule', 'user', 1, '2026-01-01 00:00:00.000000', 1)")
        for number, status, path in DOCUMENTS:
            connection.execute(
                "INSERT INTO documents (id, vault_id, owner_id, title, currency, status, source, added_at, pages, "
                "current_version, change_seq, trashed_status, duplicate_kind, process_error) VALUES (?, 1, 1, ?, 'EUR', "
                "?, ?, '2026-01-01 00:00:00.000000', 1, 2, ?, '', '', '')", (number, f"Dokument {number}", status,
                                                                               SOURCES.get(number, "upload"), number))
            # Two versions each: the job is about the document (its current version), once.
            for n in (1, 2):
                connection.execute(
                    "INSERT INTO versions (document_id, n, original_path, archive_path, sha256, size, pages, created_at, "
                    "note, phash) VALUES (?, ?, ?, '', '', 10, 1, '2026-01-01 00:00:00.000000', '', '')",
                    (number, n, path.replace(".", f" v{n}.")))
        connection.execute(
            "INSERT INTO intake_items (document_id, source, \"key\", state, sha256, size, mtime_ns, message, unknown, detail, "
            "at) VALUES (6, 'mail', 'box:1:1:1', 'taken', '', 10, 0, '', 0, NULL, '2026-01-01 00:00:00.000000')")
        connection.execute("PRAGMA user_version = 5")
        connection.commit()
    database.init_db()
    assert version_of(scratch) == database.SCHEMA_VERSION
    with closing(sqlite3.connect(scratch)) as connection:
        jobs = connection.execute("SELECT kind, ref, state, attempts FROM jobs ORDER BY id").fetchall()
    assert jobs == [("index", 0, "queued", 0), ("text", 1, "queued", 0), ("text", 2, "queued", 0),
                    ("text", 5, "queued", 0), ("text", 6, "queued", 0), ("text", 7, "queued", 0)]
