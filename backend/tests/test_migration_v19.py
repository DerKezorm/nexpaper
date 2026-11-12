"""Schema 18 to schema 19 (``db._step_upload_requests``): one table of its own for the upload requests (U1); nothing else
changes. The trial run of a restore counts the requests a restore would open again."""

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
from app.models import UploadRequest
from app.services import backups

from .conftest import make_account
from .test_schema import RECORDS, schema_of, scratch, version_of  # noqa: F401 - the fixture is used by name


def test_the_table_comes_and_nothing_else_changes(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(database, "SCHEMA_VERSION", 19)
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v18.sql").read_text(encoding="utf-8"))
        connection.execute("PRAGMA user_version = 18")
        connection.commit()
        before = schema_of(connection)
    database.init_db()
    assert version_of(scratch) == 19
    with closing(sqlite3.connect(scratch)) as connection:
        after = schema_of(connection)
        assert {name: columns for name, columns in after.items() if name in before} == before
        assert set(after) - set(before) == {"upload_requests"}
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert "ix_upload_requests_user" in indexes
    # A second start takes no step again.
    database.init_db()
    assert version_of(scratch) == 19


def test_a_token_is_once_and_a_request_goes_with_its_person(scratch: Path,  # noqa: F811
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "SCHEMA_VERSION", 19)
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v18.sql").read_text(encoding="utf-8"))
        connection.execute("PRAGMA user_version = 18")
        connection.commit()
    database.init_db()
    with closing(sqlite3.connect(scratch)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        columns = [row[1] for row in connection.execute("PRAGMA table_info(users)")]
        values = {"id": 1, "name": "jule"}
        # Every other column of the account as the schema wants it (not null without a default: a plain value).
        for row in connection.execute("PRAGMA table_info(users)"):
            if row[1] not in values and row[3] and row[4] is None:
                values[row[1]] = "2026-11-12 08:00:00" if "DATETIME" in row[2] else 0 if row[2] in (
                    "INTEGER", "BOOLEAN") else ""
        assert set(values) <= set(columns)
        # The names are the schema's own columns (checked just above), never a value from outside.
        statement = f"INSERT INTO users ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})"  # noqa: S608
        connection.execute(statement, tuple(values.values()))
        add = ("INSERT INTO upload_requests (user_id, name, token_hash, token_enc, address, until, max_files, "
               "received, created_at) VALUES (1, 'x', ?, '', 'https://paper.example.com', '2026-12-01 00:00:00', 10, "
               "0, '2026-11-12 08:00:00')")
        connection.execute(add, ("h1",))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(add, ("h1",))
        connection.execute("DELETE FROM users WHERE id = 1")
        assert connection.execute("SELECT count(*) FROM upload_requests").fetchone()[0] == 0


def test_the_trial_run_counts_the_requests_a_restore_opens_again(client: TestClient, operator: object) -> None:
    jule = make_account("jule")
    now = clock.now()
    with SessionLocal() as db:
        rows = [UploadRequest(user_id=jule.id, name=f"r{n}", token_hash=secrets.token_hex(32), token_enc="",
                              address="https://paper.example.com", until=now + timedelta(days=7), max_files=10,
                              received=0, created_at=now) for n in range(3)]
        rows.append(UploadRequest(user_id=jule.id, name="old", token_hash=secrets.token_hex(32), token_enc="",
                                  address="https://paper.example.com", until=now - timedelta(days=1), max_files=10,
                                  received=0, created_at=now - timedelta(days=8)))
        db.add_all(rows)
        db.commit()
        ids = [row.id for row in rows]
    name = backups.create(kind=backups.MANUAL).name
    assert backups.check(name).revived_upload_requests == 0
    with SessionLocal() as db:
        db.get(UploadRequest, ids[0]).revoked_at = now  # type: ignore[union-attr]
        db.delete(db.get(UploadRequest, ids[1]))
        # One that ran out in the backup is no matter of the restore.
        db.get(UploadRequest, ids[3]).revoked_at = now  # type: ignore[union-attr]
        db.commit()
    brief = client.post(f"/api/v1/backups/{name}/check").json()
    assert brief["usable"] is True and brief["revived_upload_requests"] == 2


def test_the_trial_run_names_a_request_used_up_since_the_backup(client: TestClient, operator: object) -> None:
    """A request that took all its files after the backup takes files again once the backup is restored."""
    jule = make_account("jule")
    now = clock.now()
    with SessionLocal() as db:
        row = UploadRequest(user_id=jule.id, name="voll", token_hash=secrets.token_hex(32), token_enc="",
                            address="https://paper.example.com", until=now + timedelta(days=7), max_files=2,
                            received=1, created_at=now)
        done = UploadRequest(user_id=jule.id, name="war voll", token_hash=secrets.token_hex(32), token_enc="",
                             address="https://paper.example.com", until=now + timedelta(days=7), max_files=2,
                             received=2, created_at=now)
        db.add_all([row, done])
        db.commit()
        row_id = row.id
    name = backups.create(kind=backups.MANUAL).name
    assert backups.check(name).revived_upload_requests == 0
    with SessionLocal() as db:
        db.get(UploadRequest, row_id).received = 2  # type: ignore[union-attr]
        db.commit()
    brief = client.post(f"/api/v1/backups/{name}/check").json()
    # The one used up since counts; the one used up already in the backup does not.
    assert brief["revived_upload_requests"] == 1
