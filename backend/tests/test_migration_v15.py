"""Schema 14 to schema 15 (``db._step_related``): four tables of their own for "goes with", and one job that reads the
numbers of the documents there are, once, after the start. Nothing else changes."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app import db as database

from .test_schema import RECORDS, schema_of, scratch, version_of  # noqa: F401 - the fixture is used by name

NEW = {"document_numbers", "numbers_read", "related", "related_dismissed"}


def test_the_tables_come_and_one_job_reads_the_numbers(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(database, "SCHEMA_VERSION", 15)
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v14.sql").read_text(encoding="utf-8"))
        connection.execute("PRAGMA user_version = 14")
        connection.commit()
        before = schema_of(connection)
    database.init_db()
    assert version_of(scratch) == 15
    with closing(sqlite3.connect(scratch)) as connection:
        after = schema_of(connection)
        assert {name: columns for name, columns in after.items() if name in before} == before
        assert set(after) - set(before) == NEW
        jobs = connection.execute("SELECT kind, ref, payload, state FROM jobs").fetchall()
        assert [(kind, ref, json.loads(payload), state) for kind, ref, payload, state in jobs] == [
            ("numbers", 0, {"after": 0}, "queued")]
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert {"ix_document_numbers_compare", "ix_related_high", "ix_related_dismissed_high"} <= indexes
    # A second start takes no step again and queues nothing more.
    database.init_db()
    with closing(sqlite3.connect(scratch)) as connection:
        assert connection.execute("SELECT count(*) FROM jobs").fetchone() == (1,)


def test_a_pair_is_once_and_goes_with_either_document(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(database, "SCHEMA_VERSION", 15)
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v14.sql").read_text(encoding="utf-8"))
        connection.execute("PRAGMA user_version = 14")
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
        connection.execute("INSERT INTO related (low_id, high_id, created_at) VALUES (1, 2, '2026-11-12 08:00:00')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO related (low_id, high_id, created_at) VALUES (1, 2, '2026-11-12 08:00:00')")
        connection.execute("INSERT INTO related (low_id, high_id, created_at) VALUES (2, 3, '2026-11-12 08:00:00')")
        connection.execute("DELETE FROM documents WHERE id = 2")
        assert connection.execute("SELECT count(*) FROM related").fetchone() == (0,)
