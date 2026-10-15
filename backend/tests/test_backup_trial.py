"""The trial run of a restore is the start, rehearsed; a restore that fails does not stop the server; a damaged or
oversized archive is told as what it is; the passwords of the three acts that carry the archive away or throw it away;
what a restore brings back to life."""

from __future__ import annotations

import json
import secrets
import shutil
import sqlite3
import struct
import zipfile
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import clock
from app import db as database
from app.db import SessionLocal
from app.main import app
from app.models import ApiKey, Device, Link
from app.services import backups, filecheck, tell
from app.services.backups import DATABASE_ENTRY, MANIFEST

from .conftest import PASSWORD, make_account
from .papers import PDF, add_document, own_vault
from .test_backup_safety import agreeing, made_here, with_manifest, write_archive


@pytest.fixture(autouse=True)
def no_leftovers() -> None:
    shutil.rmtree(backups.pending_folder(), ignore_errors=True)
    shutil.rmtree(backups.failed_folder(), ignore_errors=True)


def database_with(entries: dict[str, bytes], tmp_path: Path, *statements: str, version: int | None = None) -> dict:
    """The entries with the database changed by ``statements`` (and a version, when one is given), and a manifest that
    names that database: the archive is whole, only the database in it is not what a start can use."""
    copy = tmp_path / "changed.db"
    copy.write_bytes(entries[DATABASE_ENTRY])
    with closing(sqlite3.connect(copy)) as connection:
        for statement in statements:
            connection.execute(statement)
        if version is not None:
            connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()
    return agreeing({**entries, DATABASE_ENTRY: copy.read_bytes()})


#: A database as it stood before step 11 (the deadlines): its table gone, ``document_dates`` as in schema 10
#: (a column with a foreign key cannot be dropped in SQLite, so the table is made anew). Together with
#: ``UNDO_KEEPING`` and ``UNDO_LAST_STEP`` it takes a database back to schema 10.
UNDO_DEADLINES = (
    "DROP TABLE deadline_snoozes",
    (
        "CREATE TABLE dd10 ( id INTEGER NOT NULL, document_id INTEGER NOT NULL, kind VARCHAR(16) NOT NULL, "
        "date DATE NOT NULL, PRIMARY KEY (id), CONSTRAINT uq_document_dates_kind UNIQUE (document_id, kind), "
        "FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE )"
    ),
    "INSERT INTO dd10 SELECT id, document_id, kind, date FROM document_dates",
    "DROP TABLE document_dates",
    "ALTER TABLE dd10 RENAME TO document_dates",
    "CREATE INDEX ix_document_dates_document_id ON document_dates (document_id)",
)


#: What takes a database back from schema 12 to 11 (step 12, keeping documents): the columns it adds.
UNDO_KEEPING = ("ALTER TABLE kinds DROP COLUMN keep_years", "ALTER TABLE kinds DROP COLUMN keep_new_only",
                "ALTER TABLE document_dates DROP COLUMN manual")


#: A database as it stood before the last step (13, the reminders): its three tables gone.
UNDO_LAST_STEP = (
    "DROP TABLE reminders_sent",
    "DROP TABLE reminder_mutes",
    "DROP TABLE reminder_settings",
)


def update_copies() -> list[backups.Entry]:
    return [entry for entry in backups.entries() if entry.kind == backups.UPDATE]


def refused(client: TestClient, name: str) -> None:
    """The archive cannot be used: the trial run says so, the restore refuses, and nothing is laid out or kept."""
    assert backups.check(name).usable is False
    answer = client.post(f"/api/v1/backups/{name}/check")
    assert answer.status_code == 200 and answer.json()["usable"] is False
    restore = client.post(f"/api/v1/backups/{name}/restore", json={"password": PASSWORD})
    assert restore.status_code == 400 and restore.json()["detail"]["code"] == "backup_damaged", restore.text
    assert not backups.pending_folder().exists()
    assert update_copies() == [], "nothing was kept as the way back: nothing was going to change"


# --- The start, rehearsed ---------------------------------------------------------------------------------------------


def test_a_control_a_database_as_made_here_passes_the_rehearsal(client: TestClient, operator: object) -> None:
    brief = backups.check(write_archive(made_here()))
    assert brief.usable and brief.schema == database.SCHEMA_VERSION


def test_a_sqlite_file_with_some_version_that_is_not_ours_is_refused(
    client: TestClient, operator: object, tmp_path: Path
) -> None:
    junk = tmp_path / "junk.db"
    with closing(sqlite3.connect(junk)) as connection:
        connection.execute("CREATE TABLE junk (id INTEGER PRIMARY KEY, note TEXT)")
        connection.execute("PRAGMA user_version = 5")
        connection.commit()
    name = write_archive(agreeing({**made_here(), DATABASE_ENTRY: junk.read_bytes()}))
    refused(client, name)


def test_a_database_without_any_table_is_refused(client: TestClient, operator: object, tmp_path: Path) -> None:
    empty = tmp_path / "empty.db"
    with closing(sqlite3.connect(empty)) as connection:
        connection.execute("PRAGMA user_version = 10")
        connection.commit()
    refused(client, write_archive(agreeing({**made_here(), DATABASE_ENTRY: empty.read_bytes()})))


@pytest.mark.parametrize("statement", [
    "CREATE TRIGGER keep_sessions BEFORE DELETE ON auth_sessions BEGIN SELECT RAISE(ABORT, 'no'); END",
    "CREATE TRIGGER spy AFTER INSERT ON settings BEGIN SELECT 1; END",
    "CREATE VIEW everything AS SELECT * FROM users",
    "CREATE VIRTUAL TABLE lookalike USING fts5(title)",
    # The name of the trigger that keeps the search index, with another body: the first thing somebody would try.
    "CREATE TRIGGER documents_search_gone AFTER DELETE ON documents BEGIN DELETE FROM users; END",
    "CREATE VIRTUAL TABLE doc_fts USING fts5(other)",
])
def test_a_trigger_a_view_or_a_virtual_table_nexpaper_did_not_make_is_refused(
    client: TestClient, operator: object, tmp_path: Path, statement: str
) -> None:
    refused(client, write_archive(database_with(made_here(), tmp_path, statement)))


def test_the_trigger_and_the_tables_of_the_search_index_as_nexpaper_makes_them_pass(
    client: TestClient, operator: object, tmp_path: Path
) -> None:
    """The control for the test above: a database that still has its search index (an archive made elsewhere may) is
    not refused for it."""
    from app.models import SEARCH_STATEMENTS

    name = write_archive(database_with(made_here(), tmp_path, *SEARCH_STATEMENTS))
    assert backups.check(name).usable is True


def test_nothing_is_written_to_the_copy_before_the_foreign_objects_are_looked_for(
    client: TestClient, operator: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A trigger fires at a write; so no step of the start (which writes) may run before the list of triggers and views
    has been read. The steps are counted: for an archive with a trigger of its own none ran."""
    ran: list[int] = []
    real = database._init

    def counting(schema: object, **kwargs: object) -> None:
        ran.append(1)
        real(schema, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(database, "_init", counting)
    name = write_archive(database_with(
        made_here(), tmp_path, "CREATE TRIGGER spy AFTER INSERT ON settings BEGIN SELECT 1; END",
        version=database.SCHEMA_VERSION - 1, ))
    assert backups.check(name).usable is False
    assert ran == [], "the start was run on a database with a trigger that is not ours"
    # The control: without the trigger the steps do run.
    ok = write_archive(database_with(made_here(), tmp_path, *UNDO_LAST_STEP,
                                     version=database.SCHEMA_VERSION - 1), "nexpaper-2020-01-03-000000.zip")
    assert backups.check(ok).usable is True and ran == [1]


def test_a_database_that_lacks_a_table_or_a_column_is_refused(
    client: TestClient, operator: object, tmp_path: Path
) -> None:
    refused(client, write_archive(database_with(made_here(), tmp_path, "DROP TABLE notes")))
    name = write_archive(database_with(made_here(), tmp_path, "ALTER TABLE documents DROP COLUMN files_state"),
                         "nexpaper-2020-01-02-000000.zip")
    assert backups.check(name).usable is False


def test_a_step_that_cannot_run_on_the_database_refuses_the_archive(
    client: TestClient, operator: object, tmp_path: Path
) -> None:
    """The last step adds a column the database has already: the start would stop there, so the trial run does."""
    name = write_archive(database_with(made_here(), tmp_path, version=database.SCHEMA_VERSION - 1))
    refused(client, name)


def test_the_steps_of_the_rehearsal_run_on_the_copy_and_never_on_the_live_database(
    client: TestClient, operator: object, tmp_path: Path
) -> None:
    """An older database passes (its steps run on the scratch copy), and the live one is not touched by that."""
    entries = database_with(made_here(), tmp_path, *UNDO_LAST_STEP, version=database.SCHEMA_VERSION - 1)
    brief = backups.check(write_archive(entries))
    assert brief.usable and brief.schema == database.SCHEMA_VERSION - 1
    with SessionLocal() as db:
        assert db.connection().exec_driver_sql("PRAGMA user_version").scalar() == database.SCHEMA_VERSION
    assert [path.name for path in backups.folder().glob(".check-*")] == []


# --- A restore that cannot be applied --------------------------------------------------------------------------------


def staged(tmp_path: Path) -> tuple[str, int]:
    """A backup staged for the next start, and the number of accounts the live database has after it was made."""
    make_account("jule")
    name = backups.create(kind=backups.MANUAL).name
    make_account("tom")
    backups.stage_restore(name)
    assert backups.pending_folder().is_dir()
    return name, 3


def accounts_now() -> int:
    from app.models import Account

    with SessionLocal() as db:
        return len(db.scalars(select(Account.id)).all())


def test_a_restore_that_fails_at_the_start_leaves_the_database_and_the_server_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _name, _live = staged(tmp_path)
    before = accounts_now()
    told: list[tell.Notice] = []
    monkeypatch.setattr(tell, "operator", told.append)

    def broken(_database: Path) -> None:
        raise RuntimeError("forced for the test")

    monkeypatch.setattr(backups, "_end_restored_sessions", broken)
    with TestClient(app) as started:
        assert started.get("/api/v1/health").status_code == 200, "the server started"
    assert not backups.pending_folder().exists()
    assert (backups.failed_folder() / "nexpaper.db").is_file(), "put aside, not thrown away"
    note = json.loads((backups.failed_folder() / "failed.json").read_text(encoding="utf-8"))
    assert note["error"] == "RuntimeError" and "forced" not in json.dumps(note)
    assert accounts_now() == before, "the live database is as it was, tom (made after the backup) is still there"
    live = backups.folder().parent
    assert [path.name for path in live.glob("*.restoring")] == []
    # The operators were told, once, in both languages, with no dash.
    assert len(told) == 1 and told[0].tag == "restore-failed"
    assert set(told[0].texts) == {"de", "en"}
    assert all("–" not in text and "—" not in text for pair in told[0].texts.values() for text in pair)
    assert backups.report_failed_restore() is False


def test_a_failed_restore_is_put_aside_by_apply_pending_itself(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    staged(tmp_path)
    before = accounts_now()
    with monkeypatch.context() as broken:
        broken.setattr(backups, "_end_restored_sessions", lambda _path: 1 / 0)
        assert backups.apply_pending() is False
    assert backups.failed_folder().is_dir() and not backups.pending_folder().exists()
    assert accounts_now() == before
    # An earlier failure is replaced by a later one, not piled up.
    backups.stage_restore(_latest_name())
    with monkeypatch.context() as broken:
        broken.setattr(backups, "_end_restored_sessions", lambda _path: 1 / 0)
        assert backups.apply_pending() is False
    assert [path.name for path in backups.folder().glob("restore-failed*")] == ["restore-failed"]


def _latest_name() -> str:
    return next(entry.name for entry in backups.entries() if entry.kind == backups.MANUAL)


def test_a_good_restore_still_swaps_the_database_and_leaves_nothing_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged(tmp_path)
    assert accounts_now() == 2
    assert backups.apply_pending() is True
    assert accounts_now() == 1, "tom was made after the backup and is gone"
    assert not backups.pending_folder().exists() and not backups.failed_folder().exists()
    assert list(backups.folder().parent.glob("*.restoring")) == []


@pytest.mark.parametrize("keep", ["nexpaper.db", MANIFEST])
def test_a_half_written_pending_folder_is_thrown_away_and_never_applied(keep: str) -> None:
    make_account("jule")
    before = accounts_now()
    pending = backups.pending_folder()
    pending.mkdir(parents=True)
    (pending / keep).write_bytes(b"not a database, not a manifest")
    assert backups.apply_pending() is False
    assert not pending.exists() and not backups.failed_folder().exists()
    assert accounts_now() == before


# --- The manifest has a size -----------------------------------------------------------------------------------------


def padded_manifest(entries: dict[str, bytes], size: int) -> dict[str, bytes]:
    body = json.dumps(json.loads(entries[MANIFEST])).encode()
    return {**entries, MANIFEST: body + b" " * (size - len(body))}


def test_a_manifest_larger_than_64_kilobytes_is_refused_and_one_at_the_limit_passes(
    client: TestClient, operator: object
) -> None:
    entries = made_here()
    assert backups.MANIFEST_MAX == 64 * 1024
    for size, ok in ((64 * 1024, True), (64 * 1024 + 1, False), (3 * 1024 * 1024, False)):
        name = write_archive(padded_manifest(entries, size), "nexpaper-2020-05-01-000000.zip")
        listed = [entry["name"] for entry in client.get("/api/v1/backups").json()]
        assert (name in listed) is ok, size
        answer = client.post(f"/api/v1/backups/{name}/check")
        if ok:
            assert answer.status_code == 200 and answer.json()["usable"] is True
        else:
            assert answer.status_code == 400 and answer.json()["detail"]["code"] == "backup_invalid", answer.text


def test_an_upload_with_a_manifest_that_is_too_large_is_turned_away(client: TestClient, operator: object) -> None:
    import base64

    name = write_archive(padded_manifest(made_here(), 200 * 1024), "nexpaper-2020-06-01-000000.zip")
    data = (backups.folder() / name).read_bytes()
    (backups.folder() / name).unlink()
    sent = client.post("/api/v1/backups/upload", content=data,
                       headers={"X-Nexpaper-Password": base64.b64encode(PASSWORD.encode()).decode()})
    assert sent.status_code == 400 and sent.json()["detail"]["code"] == "backup_invalid"


def test_the_manifest_is_read_in_pieces_that_have_a_size(
    client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never a read to the end: what is read is counted, whatever the archive says about its own size."""
    name = write_archive(padded_manifest(made_here(), 1024 * 1024), "nexpaper-2020-06-02-000000.zip")
    seen: list[int] = []
    real = zipfile.ZipExtFile.read

    def counting(self: zipfile.ZipExtFile, size: int = -1) -> bytes:
        seen.append(size)
        return real(self, size)

    monkeypatch.setattr(zipfile.ZipExtFile, "read", counting)
    with zipfile.ZipFile(backups.folder() / name) as archive, pytest.raises(backups.BackupError):
        backups._manifest(archive)
    assert -1 not in seen and all(0 < size <= backups.MANIFEST_MAX + 1 for size in seen)


# --- A damaged archive -----------------------------------------------------------------------------------------------


def archive_with_flipped_byte(entries: dict[str, bytes], compression: int, name: str) -> str:
    """The archive written with ``compression``, then one byte inside the data of the database turned over."""
    path = backups.folder() / name
    path.unlink(missing_ok=True)
    with zipfile.ZipFile(path, "w", compression) as archive:
        for entry, data in entries.items():
            archive.writestr(entry, data)
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(DATABASE_ENTRY)
    raw = bytearray(path.read_bytes())
    name_length, extra_length = struct.unpack("<HH", raw[info.header_offset + 26: info.header_offset + 30])
    start = info.header_offset + 30 + name_length + extra_length
    middle = start + info.compress_size // 2
    raw[middle] ^= 0xFF
    path.write_bytes(bytes(raw))
    return name


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_a_byte_turned_over_in_the_archive_is_told_as_damaged_and_never_a_server_error(
    client: TestClient, operator: object, compression: int
) -> None:
    name = archive_with_flipped_byte(made_here(), compression, "nexpaper-2020-07-01-000000.zip")
    answer = client.post(f"/api/v1/backups/{name}/check")
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "backup_damaged", answer.text
    restore = client.post(f"/api/v1/backups/{name}/restore", json={"password": PASSWORD})
    assert restore.status_code == 400 and restore.json()["detail"]["code"] == "backup_damaged", restore.text
    assert not backups.pending_folder().exists() and update_copies() == []


def test_a_database_that_is_not_the_one_the_manifest_names_is_damaged(
    client: TestClient, operator: object, tmp_path: Path
) -> None:
    """The ZIP is whole (its own checksums agree), the manifest names another database: swapped or cut and mended."""
    entries = made_here()
    other = tmp_path / "other.db"
    other.write_bytes(entries[DATABASE_ENTRY])
    with closing(sqlite3.connect(other)) as connection:
        connection.execute("CREATE TABLE addition (id INTEGER)")
        connection.commit()
    swapped = {**entries, DATABASE_ENTRY: other.read_bytes()}
    name = write_archive(swapped)
    answer = client.post(f"/api/v1/backups/{name}/check")
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "backup_damaged", answer.text
    # Only the size is wrong.
    sized = write_archive(with_manifest(entries, bytes=len(entries[DATABASE_ENTRY]) + 1), "nexpaper-2020-07-02-000000.zip")
    assert client.post(f"/api/v1/backups/{sized}/check").json()["detail"]["code"] == "backup_damaged"
    # The restore re-reads the archive; it stops there too, with nothing laid out.
    with pytest.raises(backups.BackupError) as caught:
        backups.stage_restore(name)
    assert caught.value.code == "backup_damaged" and not backups.pending_folder().exists()


def test_the_restore_compares_what_it_unpacks_with_the_manifest_itself(
    client: TestClient, operator: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Between the trial run and the unpacking for the restore the archive could have changed; the restore does not
    lean on the answer of the trial run. Here the trial run is made to say yes to an archive whose database is not the
    one the manifest names."""
    entries = made_here()
    other = tmp_path / "other.db"
    other.write_bytes(entries[DATABASE_ENTRY])
    with closing(sqlite3.connect(other)) as connection:
        connection.execute("CREATE TABLE addition (id INTEGER)")
        connection.commit()
    name = write_archive({**entries, DATABASE_ENTRY: other.read_bytes()})
    good = backups.check(write_archive(entries, "nexpaper-2020-07-03-000000.zip"))
    monkeypatch.setattr(backups, "check", lambda *_args, **_kwargs: good)
    with pytest.raises(backups.BackupError) as caught:
        backups.stage_restore(name)
    assert caught.value.code == "backup_damaged" and not backups.pending_folder().exists()


def test_the_manifest_of_an_archive_made_elsewhere_may_leave_the_checksum_out(
    client: TestClient, operator: object
) -> None:
    entries = made_here()
    name = write_archive(with_manifest(entries, sha256="", bytes=0))
    assert backups.check(name).usable


# --- Passwords: the three acts that carry the archive away or throw it away ---------------------------------------


def a_backup(client: TestClient) -> str:
    return client.post("/api/v1/backups", json={"note": "for the password tests"}).json()["name"]


def test_restoring_asks_for_the_password_and_lays_nothing_out_without_it(client: TestClient, operator: object) -> None:
    name = a_backup(client)
    answer = client.post(f"/api/v1/backups/{name}/restore", json={"password": "this is not the password"})
    assert answer.status_code == 401 and answer.json()["detail"]["code"] == "wrong_password"
    assert not backups.pending_folder().exists() and update_copies() == []


def test_downloading_asks_for_the_password_and_gives_nothing_without_it(client: TestClient, operator: object) -> None:
    name = a_backup(client)
    answer = client.post(f"/api/v1/backups/{name}/download", json={"password": "this is not the password"})
    assert answer.status_code == 401 and answer.json()["detail"]["code"] == "wrong_password"
    assert answer.headers.get("content-type", "").startswith("application/json")
    assert b"PK" not in answer.content[:2]


def test_deleting_asks_for_the_password_and_keeps_the_copy_without_it(client: TestClient, operator: object) -> None:
    name = a_backup(client)
    answer = client.request("DELETE", f"/api/v1/backups/{name}", json={"password": "this is not the password"})
    assert answer.status_code == 401 and answer.json()["detail"]["code"] == "wrong_password"
    assert (backups.folder() / name).is_file()
    assert client.request("DELETE", f"/api/v1/backups/{name}", json={"password": PASSWORD}).status_code == 204
    assert not (backups.folder() / name).exists()


def test_the_copy_of_the_present_state_is_made_before_a_restore_and_named_for_it(
    client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The way back: the state of before the restore is kept as an ``update`` copy, and it is a good archive."""
    name = a_backup(client)
    monkeypatch.setattr(backups, "restart_soon", lambda: None)
    assert client.post(f"/api/v1/backups/{name}/restore", json={"password": PASSWORD}).status_code == 202
    copies = update_copies()
    assert len(copies) == 1 and copies[0].note == f"before restoring {name}"
    assert backups.check(copies[0].name).usable


# --- What a restore brings back ---------------------------------------------------------------------------------------


def test_the_trial_run_counts_what_a_restore_brings_back_to_life(client: TestClient, operator: object) -> None:
    jule = make_account("jule")
    document_id = add_document(own_vault(jule), jule, "Rechnung")
    now = clock.now()
    with SessionLocal() as db:
        devices = [Device(account_id=jule.id, name=f"phone {n}", token_hash=secrets.token_hex(32), prefix="npd_x")
                   for n in range(3)]
        keys = [ApiKey(account_id=jule.id, name=f"key {n}", scope="read", token_hash=secrets.token_hex(32),
                       prefix="npk_x", expires_at=expiry)
                for n, expiry in enumerate((None, None, now - timedelta(days=1)))]
        links = [Link(document_id=document_id, recipient=f"someone {n}", token_hash=secrets.token_hex(32),
                      until=now + timedelta(days=7)) for n in range(2)]
        db.add_all([*devices, *keys, *links])
        db.commit()
        ids = {"devices": [d.id for d in devices], "keys": [k.id for k in keys], "links": [link.id for link in links]}
    name = backups.create(kind=backups.MANUAL).name
    quiet = backups.check(name)
    assert (quiet.revived_devices, quiet.revived_keys, quiet.revived_links) == (0, 0, 0)
    with SessionLocal() as db:
        # Devices: one revoked, one removed, one kept. Keys: one blocked, one kept (the third had run out already).
        # Links: one revoked, one kept.
        db.get(Device, ids["devices"][0]).revoked_at = now  # type: ignore[union-attr]
        db.delete(db.get(Device, ids["devices"][1]))
        db.get(ApiKey, ids["keys"][0]).blocked_at = now  # type: ignore[union-attr]
        db.get(Link, ids["links"][0]).revoked_at = now  # type: ignore[union-attr]
        db.commit()
    brief = client.post(f"/api/v1/backups/{name}/check").json()
    assert brief["usable"] is True
    assert (brief["revived_devices"], brief["revived_keys"], brief["revived_links"]) == (2, 1, 1)


# --- Time for reading, inside a large file -----------------------------------------------------------------------------


def test_the_time_for_comparing_files_runs_out_inside_a_large_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time as real_time

    jule = make_account("jule")
    add_document(own_vault(jule), jule, "Rechnung gross", content=PDF + b"x" * 40_000)
    name = backups.create(kind=backups.MANUAL).name
    clockwork = iter(float(n) for n in range(1, 1000))
    fake = SimpleNamespace(monotonic=lambda: next(clockwork), sleep=real_time.sleep, time=real_time.time,
                           time_ns=real_time.time_ns)
    monkeypatch.setattr(filecheck, "_CHUNK", 1024)
    monkeypatch.setattr(backups, "time", fake)
    monkeypatch.setattr(filecheck, "time", fake)
    short = backups.check(name, hash_seconds=4.5)
    assert short.documents == 1 and short.not_compared >= 1
    assert short.missing_documents == 0 and short.changed_documents == 0, "not read, so neither good nor bad"
    clockwork = iter(float(n) for n in range(1, 1000))
    generous = backups.check(name, hash_seconds=10_000)
    assert generous.not_compared == 0 and generous.changed_documents == 0
