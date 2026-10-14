"""The schema carries its version, and an older database is brought up step by step.

``tests/schema/v<n>.sql`` records the schema of every version. A change to ``models.py`` without a new version fails
``test_the_schema_is_the_recorded_one``. Then:

1. raise ``SCHEMA_VERSION`` in ``app/db.py`` and write the step in ``MIGRATIONS``,
2. record the new schema: ``NEXPAPER_RECORD_SCHEMA=1 python -m pytest tests/test_schema.py``,
3. ``test_every_older_schema_is_brought_up_to_the_current_one`` then runs the step against the old record.

A change the released version before must still open (new tables, a new column with a default) may go into
``db.ADDITIONS`` instead, without a new version: then the record of the current version is made anew, and
``tests/schema/released/`` keeps what the released version made (1.0.1 for the sign-in providers of 1.1.0).
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import Connection, create_engine, text

from app import db as database
from app.models import Base
from app.services import backups

RECORDS = Path(__file__).parent / "schema"


def schema_of(connection: sqlite3.Connection) -> dict[str, list[tuple[str, str, int, object, int]]]:
    """Every table with its columns (name, type, not null, default, primary key), indexes left aside."""
    tables = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {
        table: [(row[1], row[2], row[3], row[4], row[5]) for row in connection.execute(f'PRAGMA table_info("{table}")')]
        for table in tables
    }


def fresh_schema_sql() -> str:
    """The schema the models make, as SQL, one statement per line: what the records hold."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT sql, name FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
            # Tables first, a trigger only once its table is there.
            "ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END, name"
        )).all()
        # A full-text table makes tables of its own (``doc_fts_data`` ...) when it is made: they are not recorded.
        virtual = [row[0] for row in connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND sql LIKE 'CREATE VIRTUAL TABLE%'"))]
    engine.dispose()
    shadows = {f"{name}_{part}" for name in virtual for part in ("config", "content", "data", "docsize", "idx")}
    return "".join(" ".join(sql.split()) + ";\n" for sql, name in rows if name not in shadows)


#: The notes of the backups ``init_db`` made in a test (``scratch`` catches them).
made: list[str] = []


@pytest.fixture
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """``init_db`` against a database of its own, outside the one the other tests share."""
    path = tmp_path / "nexpaper.db"
    engine = create_engine(f"sqlite:///{path}")
    monkeypatch.setattr(database, "engine", engine)
    made.clear()
    monkeypatch.setattr(backups, "create", lambda **kwargs: made.append(kwargs.get("note", "")) or path)
    yield path
    engine.dispose()


def version_of(path: Path) -> int:
    with closing(sqlite3.connect(path)) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


def test_the_schema_is_the_recorded_one() -> None:
    record = RECORDS / f"v{database.SCHEMA_VERSION}.sql"
    current = fresh_schema_sql()
    if os.environ.get("NEXPAPER_RECORD_SCHEMA") == "1":
        RECORDS.mkdir(exist_ok=True)
        record.write_text(current, encoding="utf-8", newline="\n")
    assert record.is_file(), f"No record of schema {database.SCHEMA_VERSION}; see the top of this file."
    assert record.read_text(encoding="utf-8") == current, (
        "models.py changed without a new schema version: raise SCHEMA_VERSION, write the migration, record the schema "
        "(see the top of this file)."
    )


def test_a_new_database_gets_the_current_version(scratch: Path) -> None:
    database.init_db()
    assert version_of(scratch) == database.SCHEMA_VERSION
    # A second start changes nothing and makes no backup.
    database.init_db()
    assert version_of(scratch) == database.SCHEMA_VERSION
    assert made == []


def test_every_older_schema_is_brought_up_to_the_current_one(scratch: Path) -> None:
    current = fresh_schema_sql()
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(current)
        wanted = schema_of(connection)
    older = sorted(int(path.stem[1:]) for path in RECORDS.glob("v*.sql") if int(path.stem[1:]) < database.SCHEMA_VERSION)
    # Nothing to bring up while version 1 is the only one; the first migration records the schema it starts from.
    for version in older:
        # A file of the round before may still be open on Windows unless every connection is closed (``closing``:
        # sqlite3's own ``with`` only commits).
        for leftover in (scratch, scratch.with_name(scratch.name + "-wal"), scratch.with_name(scratch.name + "-shm")):
            leftover.unlink(missing_ok=True)
        with closing(sqlite3.connect(scratch)) as connection:
            connection.executescript((RECORDS / f"v{version}.sql").read_text(encoding="utf-8"))
            connection.execute(f"PRAGMA user_version = {version}")
            connection.commit()
        database.init_db()
        assert version_of(scratch) == database.SCHEMA_VERSION, version
        with closing(sqlite3.connect(scratch)) as connection:
            assert schema_of(connection) == wanted, f"schema {version}, brought up, differs from a new database"


def test_a_step_runs_once_after_a_backup_and_sets_the_version(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database.init_db()
    with sqlite3.connect(scratch) as connection:
        connection.execute("INSERT INTO settings (key, value) VALUES ('kept', '\"yes\"')")
    ran: list[int] = []

    def step(connection: Connection) -> None:
        ran.append(1)
        connection.execute(text('ALTER TABLE users ADD COLUMN "mood_scale" INTEGER DEFAULT 10'))

    monkeypatch.setattr(database, "SCHEMA_VERSION", database.SCHEMA_VERSION + 1)
    monkeypatch.setitem(database.MIGRATIONS, database.SCHEMA_VERSION, step)
    database.init_db()
    assert version_of(scratch) == database.SCHEMA_VERSION
    assert ran == [1]
    assert made == [f"before schema {database.SCHEMA_VERSION}"]
    with sqlite3.connect(scratch) as connection:
        assert "mood_scale" in [row[1] for row in connection.execute("PRAGMA table_info(users)")]
        assert connection.execute("SELECT value FROM settings WHERE key = 'kept'").fetchone() == ('"yes"',)
    database.init_db()
    assert ran == [1], "a step runs once"


def test_a_failing_step_leaves_the_database_as_it_was(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database.init_db()
    before = version_of(scratch)

    def broken(connection: Connection) -> None:
        connection.execute(text('ALTER TABLE users ADD COLUMN "half" INTEGER'))
        raise RuntimeError("the step breaks off")

    monkeypatch.setattr(database, "SCHEMA_VERSION", before + 1)
    monkeypatch.setitem(database.MIGRATIONS, before + 1, broken)
    with pytest.raises(RuntimeError):
        database.init_db()
    assert version_of(scratch) == before
    with sqlite3.connect(scratch) as connection:
        assert "half" not in [row[1] for row in connection.execute("PRAGMA table_info(users)")]


def test_a_missing_step_stops_the_start(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database.init_db()
    monkeypatch.setattr(database, "SCHEMA_VERSION", database.SCHEMA_VERSION + 1)
    with pytest.raises(RuntimeError, match="No migration"):
        database.init_db()
    assert version_of(scratch) == database.SCHEMA_VERSION - 1


def test_a_database_from_a_newer_nexpaper_is_not_touched(scratch: Path) -> None:
    database.init_db()
    with sqlite3.connect(scratch) as connection:
        connection.execute(f"PRAGMA user_version = {database.SCHEMA_VERSION + 1}")
    with pytest.raises(database.SchemaTooNew):
        database.init_db()
    assert version_of(scratch) == database.SCHEMA_VERSION + 1
    assert made == []


def test_a_database_without_a_version_is_not_taken(scratch: Path) -> None:
    with sqlite3.connect(scratch) as connection:
        connection.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY)")
    with pytest.raises(database.SchemaTooNew):
        database.init_db()


def test_two_starts_at_once_take_a_step_once(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two processes on one data folder (an update with two containers): both read the old version, both want to
    migrate. The step adds a column, so a second run would fail; a step that is not idempotent must never run twice."""
    import threading

    database.init_db()
    ran: list[int] = []

    def step(connection: Connection) -> None:
        ran.append(1)
        connection.execute(text('ALTER TABLE users ADD COLUMN "mood_scale" INTEGER DEFAULT 10'))

    monkeypatch.setattr(database, "SCHEMA_VERSION", database.SCHEMA_VERSION + 1)
    monkeypatch.setitem(database.MIGRATIONS, database.SCHEMA_VERSION, step)
    # Both starts have read the old version before either takes the step: they meet at the backup in between.
    both_read = threading.Barrier(2, timeout=10)
    monkeypatch.setattr(backups, "create", lambda **_kwargs: both_read.wait() and scratch)
    failed: list[BaseException] = []

    def start() -> None:
        try:
            database.init_db()
        except BaseException as exc:  # noqa: BLE001 - the test reports whatever went wrong
            failed.append(exc)

    threads = [threading.Thread(target=start) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failed == []
    assert ran == [1]
    assert version_of(scratch) == database.SCHEMA_VERSION


def test_switching_to_wal_waits_for_a_start_that_holds_the_database(tmp_path: Path) -> None:
    """Another start is inside its first transaction (``BEGIN IMMEDIATE`` while it makes the tables): SQLite refuses
    the switch to WAL at once instead of waiting, and a start that took that answer broke off with "database is
    locked". The connection setup tries again until the other one is done."""
    import threading
    import time

    path = tmp_path / "busy.db"
    holder = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    holder.execute("CREATE TABLE probe (id INTEGER)")
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("INSERT INTO probe VALUES (1)")
    release = threading.Timer(0.6, lambda: holder.execute("COMMIT"))
    release.start()
    waiting = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=0.1)
    try:
        started = time.monotonic()
        database._pragmas(waiting, None)
        assert time.monotonic() - started >= 0.4, "it waited for the other start"
        assert waiting.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        release.join()
        waiting.close()
        holder.close()


# --- Additions without a new version (``db.ADDITIONS``) ---------------------------------------------------------------

RELEASED = RECORDS / "released"


def test_a_database_of_1_0_1_gets_the_additions_and_the_later_steps(scratch: Path) -> None:
    """1.1.0 added the tables of the sign-in providers and a column with a default without raising the version (the
    way back to 1.0.1 stayed open for one version). A database 1.0.1 made gets them, then the steps after version 10
    (since 1.4, the deadlines), and ends as a new one would be."""
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RELEASED / "1.0.1.sql").read_text(encoding="utf-8"))
        connection.execute("PRAGMA user_version = 10")
        connection.commit()
    database.init_db()
    assert version_of(scratch) == database.SCHEMA_VERSION
    current = fresh_schema_sql()
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(current)
        wanted = schema_of(connection)
    with closing(sqlite3.connect(scratch)) as connection:
        assert schema_of(connection) == wanted
        # What 1.0.1 writes, naming only its own columns, still goes in.
        connection.execute(
            "INSERT INTO users (id, name, display_name, whats_new_seen, role, sign_in, password_hash, email, oidc_subject, "
            "language, created_at, failed_logins, totp_secret_enc, totp_recovery, totp_last_step) VALUES (1, 'anna', '', "
            "'', 'member', 'password', '', '', '', '', '2026-10-11 08:00:00', 0, '', '', 0)")
        connection.execute(
            "INSERT INTO auth_sessions (token_hash, account_id, created_at, expires_at, last_seen_at, ip, user_agent) "
            "VALUES ('h', 1, '2026-10-11 08:00:00', '2026-10-12 08:00:00', '2026-10-11 08:00:00', '', '')")
        connection.commit()
        assert connection.execute("SELECT second_factor_by_provider FROM auth_sessions").fetchone() == (0,)
    # The steps after 10 made one backup first; a second start changes nothing and makes no other.
    assert made == [f"before schema {database.SCHEMA_VERSION}"]
    database.init_db()
    assert version_of(scratch) == database.SCHEMA_VERSION and made == [f"before schema {database.SCHEMA_VERSION}"]


def test_the_released_record_is_what_1_0_1_made() -> None:
    """The record of 1.0.1 is the schema of version 10 before the additions: without the sign-in tables."""
    text = (RELEASED / "1.0.1.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE users" in text and "oidc_providers" not in text and "second_factor_by_provider" not in text


def test_a_later_step_finds_the_additions_on_a_database_of_1_0_1(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A step of a later version may change the tables of the additions: on a database 1.0.1 made, they are there
    before the first step runs, as they stood when they were added, and the version goes up."""
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RELEASED / "1.0.1.sql").read_text(encoding="utf-8"))
        connection.execute("PRAGMA user_version = 10")
        connection.commit()
    found: list[list[str]] = []

    def step(connection: Connection) -> None:
        found.append([row[1] for row in connection.exec_driver_sql('PRAGMA table_info("oidc_providers")')])
        connection.exec_driver_sql("ALTER TABLE oidc_providers ADD COLUMN later VARCHAR(8) DEFAULT '' NOT NULL")
        connection.exec_driver_sql("SELECT count(*) FROM oidc_links").fetchone()

    monkeypatch.setattr(database, "SCHEMA_VERSION", 11)
    monkeypatch.setitem(database.MIGRATIONS, 11, step)
    database.init_db()
    assert version_of(scratch) == 11
    assert len(found) == 1 and "trusts_second_factor" in found[0] and "later" not in found[0]
    with closing(sqlite3.connect(scratch)) as connection:
        assert "later" in [row[1] for row in connection.execute('PRAGMA table_info("oidc_providers")')]
        assert "second_factor_by_provider" in [row[1] for row in connection.execute("PRAGMA table_info(auth_sessions)")]
    # The next start runs the additions again: they change nothing that is there.
    database.init_db()
    assert version_of(scratch) == 11
