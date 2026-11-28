"""Schema 20 to schema 21 (``db._step_reference``): the reference of a document and, at the vaults, what each calls it
and whether it is hidden (issue #13). Three columns with a default; nothing else changes, every row stays."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app import db as database

from .test_schema import (  # noqa: F401 - the fixture is used by name
    RECORDS,
    schema_of,
    scratch,
    version_of,
    without_konten,
)

ADDED = {
    "documents": [("reference", "VARCHAR(100)", 1, "''", 0)],
    "vaults": [("reference_name", "VARCHAR(40)", 1, "''", 0), ("reference_hidden", "BOOLEAN", 1, "0", 0)],
}


def _v20(scratch: Path) -> dict[str, list[tuple[str, str, int, object, int]]]:  # noqa: F811
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v20.sql").read_text(encoding="utf-8"))
        connection.execute("PRAGMA user_version = 20")
        connection.commit()
        return schema_of(connection)


def test_three_columns_come_and_nothing_else_changes(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(database, "SCHEMA_VERSION", 21)
    before = without_konten(_v20(scratch))
    database.init_db()
    assert version_of(scratch) == 21
    with closing(sqlite3.connect(scratch)) as connection:
        after = without_konten(schema_of(connection))
    assert set(after) == set(before)
    for table, columns in before.items():
        assert after[table] == columns + ADDED.get(table, []), table
    # A second start takes no step again.
    database.init_db()
    assert version_of(scratch) == 21


def test_the_rows_there_are_get_no_reference_and_a_shown_field(scratch: Path,  # noqa: F811
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "SCHEMA_VERSION", 21)
    _v20(scratch)
    with closing(sqlite3.connect(scratch)) as connection:
        connection.execute("INSERT INTO vaults (id, name, folder, icon, created_at) VALUES "
                           "(1, 'Praxis', 'praxis', 'folder', '2026-11-12 08:00:00')")
        connection.execute("INSERT INTO documents (id, vault_id, title, currency, status, source, added_at, pages, "
                           "current_version, change_seq) VALUES (1, 1, 'Befund', 'EUR', 'filed', 'upload', "
                           "'2026-11-12 08:00:00', 1, 1, 1)")
        connection.commit()
    database.init_db()
    with closing(sqlite3.connect(scratch)) as connection:
        assert connection.execute("SELECT title, reference FROM documents").fetchall() == [("Befund", "")]
        assert connection.execute("SELECT name, reference_name, reference_hidden FROM vaults").fetchall() == [
            ("Praxis", "", 0)]
