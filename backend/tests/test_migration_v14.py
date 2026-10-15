"""Schema 13 to schema 14 (``db._step_auto_trash``): every kind gets the switch "expired documents into the trash by
themselves", off. Nothing else changes, and the documents are left alone."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app import db as database

from .test_schema import RECORDS, schema_of, scratch, version_of  # noqa: F401 - the fixture is used by name


def test_every_kind_there_was_gets_the_switch_off(scratch: Path) -> None:  # noqa: F811
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v13.sql").read_text(encoding="utf-8"))
        connection.execute("INSERT INTO kinds (id, \"key\", name, name_key, hue, position, keep_years, keep_new_only) "
                           "VALUES (1, 'invoice', 'Rechnung', 'rechnung', 28, 0, 10, 0)")
        connection.execute("INSERT INTO kinds (id, \"key\", name, name_key, hue, position, keep_years, keep_new_only) "
                           "VALUES (2, 'contract', 'Vertrag', 'vertrag', 28, 1, NULL, 1)")
        connection.execute("PRAGMA user_version = 13")
        connection.commit()
        before = schema_of(connection)
    database.init_db()
    assert version_of(scratch) == database.SCHEMA_VERSION == 14
    with closing(sqlite3.connect(scratch)) as connection:
        after = schema_of(connection)
        assert {name: columns[: len(before[name])] for name, columns in after.items() if name in before} == before
        assert [column[0] for column in after["kinds"][len(before["kinds"]):]] == ["auto_trash"]
        assert set(after) == set(before)
        # Off for every kind there was, with the time they had.
        assert connection.execute("SELECT id, keep_years, keep_new_only, auto_trash FROM kinds ORDER BY id"
                                  ).fetchall() == [(1, 10, 0, 0), (2, None, 1, 0)]
        # A new kind is off from the start; the column cannot be empty.
        connection.execute("INSERT INTO kinds (\"key\", name, name_key, hue, position) VALUES ('', 'Neu', 'neu', 1, 2)")
        assert connection.execute("SELECT auto_trash FROM kinds WHERE name = 'Neu'").fetchone() == (0,)
