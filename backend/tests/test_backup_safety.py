"""What a restore takes from an archive: only a database this nexpaper can start with, nothing but the three parts of an
archive of ours, and never more bytes than a backup may hold, counted while reading. Every archive here is small."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, create_engine, text

from app import db as database
from app.config import get_settings
from app.models import Account
from app.services import backups

from .conftest import PASSWORD

#: A name the backup list takes for one of its own.
NAME = "nexpaper-2020-01-01-000000.zip"


def made_here() -> dict[str, bytes]:
    """The entries of a real backup of the test database."""
    path = backups.create(kind=backups.MANUAL)
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    path.unlink()
    return entries


def write_archive(entries: dict[str, bytes], name: str = NAME) -> str:
    (backups.folder() / name).unlink(missing_ok=True)
    with zipfile.ZipFile(backups.folder() / name, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry, data in entries.items():
            archive.writestr(entry, data)
    return name


def with_schema(database_bytes: bytes, version: int, tmp_path: Path) -> bytes:
    copy = tmp_path / "copy.db"
    copy.write_bytes(database_bytes)
    with sqlite3.connect(copy) as connection:
        connection.execute(f"PRAGMA user_version = {version}")
    connection.close()
    return copy.read_bytes()


def agreeing(entries: dict[str, bytes]) -> dict[str, bytes]:
    """The manifest made to agree with the database inside again, after a test changed the database: a manifest that
    names another checksum is a damaged archive, which is a test of its own."""
    import hashlib

    database_bytes = entries[backups.DATABASE_ENTRY]
    return with_manifest(entries, bytes=len(database_bytes), sha256=hashlib.sha256(database_bytes).hexdigest())


def with_manifest(entries: dict[str, bytes], **change: object) -> dict[str, bytes]:
    manifest = {**json.loads(entries[backups.MANIFEST]), **change}
    return {**entries, backups.MANIFEST: json.dumps(manifest).encode()}


@pytest.fixture(autouse=True)
def no_pending() -> None:
    import shutil

    shutil.rmtree(backups.pending_folder(), ignore_errors=True)


def test_an_archive_holds_the_database_the_manifest_and_the_secret_and_no_documents(
        client: TestClient, operator: Account) -> None:
    """The documents lie under ``<data>/dokumente`` and belong to the server's usual file backup."""
    folder = get_settings().data_dir / "dokumente"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "2026-03-14 Rechnung.pdf").write_bytes(b"%PDF-1.4 a made-up bill")
    # The tests give the secret in the environment; the file a server makes for itself is put there by hand.
    secret = get_settings().data_dir / "secret.key"
    secret.write_text("a-made-up-secret", encoding="utf-8")
    try:
        entries = made_here()
    finally:
        (folder / "2026-03-14 Rechnung.pdf").unlink()
        secret.unlink()
    assert set(entries) == {backups.MANIFEST, backups.DATABASE_ENTRY, backups.SECRET_ENTRY}
    manifest = json.loads(entries[backups.MANIFEST])
    assert manifest["bytes"] == len(entries[backups.DATABASE_ENTRY])
    assert "media" not in manifest and "files" not in manifest


def test_a_backup_from_a_newer_nexpaper_is_not_restored(client: TestClient, operator: Account, tmp_path: Path) -> None:
    entries = made_here()
    entries[backups.DATABASE_ENTRY] = with_schema(entries[backups.DATABASE_ENTRY], database.SCHEMA_VERSION + 98,
                                                  tmp_path)
    name = write_archive(agreeing(entries))
    brief = client.post(f"/api/v1/backups/{name}/check").json()
    assert brief["schema"] == database.SCHEMA_VERSION + 98
    assert brief["database_ok"] is False and brief["usable"] is False and brief["too_new"] is True
    refused = client.post(f"/api/v1/backups/{name}/restore", json={"password": PASSWORD})
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "backup_too_new"
    assert not backups.pending_folder().exists(), "nothing laid out for the next start"


def test_a_database_without_a_version_is_not_restored(client: TestClient, operator: Account, tmp_path: Path) -> None:
    entries = made_here()
    entries[backups.DATABASE_ENTRY] = with_schema(entries[backups.DATABASE_ENTRY], 0, tmp_path)
    brief = backups.check(write_archive(agreeing(entries)))
    assert (brief.schema, brief.usable) == (0, False)


def test_an_older_schema_is_taken_and_brought_up_at_the_start(
    client: TestClient, operator: Account, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entries = made_here()
    name = write_archive(entries)

    def step(connection: Connection) -> None:
        connection.execute(text("CREATE TABLE probe_later (id INTEGER PRIMARY KEY)"))

    monkeypatch.setattr(database, "SCHEMA_VERSION", database.SCHEMA_VERSION + 1)
    monkeypatch.setitem(database.MIGRATIONS, database.SCHEMA_VERSION, step)
    brief = backups.check(name)
    assert brief.usable and brief.schema == database.SCHEMA_VERSION - 1
    # What the start after the restore does with it, on a file of its own.
    restored = tmp_path / "restored.db"
    restored.write_bytes(entries[backups.DATABASE_ENTRY])
    engine = create_engine(f"sqlite:///{restored}")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(backups, "create", lambda **_kwargs: restored)
    database.init_db()
    engine.dispose()
    with sqlite3.connect(restored) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
        assert connection.execute("SELECT count(*) FROM sqlite_master WHERE name = 'probe_later'").fetchone()[0] == 1
    connection.close()


@pytest.mark.parametrize("escaping", ["../../escaped", "/escaped", "..\\escaped", "sub/escaped", "C:escaped",
                                      "media/photo00001", "dokumente/escaped"])
def test_an_entry_that_is_not_one_of_the_three_makes_the_archive_unusable_and_is_never_unpacked(
    client: TestClient, operator: Account, escaping: str
) -> None:
    name = write_archive({**made_here(), escaping: b"not a part of ours"})
    assert backups.check(name).usable is False
    with pytest.raises(backups.BackupError):
        backups.stage_restore(name)
    found = [path for path in backups.folder().parent.rglob("*escaped*")]
    assert found == [], found
    assert not backups.pending_folder().exists()


def test_an_archive_that_unpacks_to_more_than_a_backup_may_hold_is_refused(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zeros pack to almost nothing: a few hundred bytes in the archive, kilobytes when read."""
    monkeypatch.setattr(backups, "SECRET_MAX", 64)
    entries = made_here()
    entries[backups.SECRET_ENTRY] = b"\0" * 4096
    name = write_archive(entries)
    assert (backups.folder() / name).stat().st_size < 64 * 1024
    with pytest.raises(backups.BackupError) as refused:
        backups.stage_restore(name)
    assert refused.value.code == "backup_too_large"
    assert not backups.pending_folder().exists()

    monkeypatch.setattr(backups, "DATABASE_MAX", 1000)
    name = write_archive(made_here())
    with pytest.raises(backups.BackupError) as refused:
        backups.check(name)
    assert refused.value.code == "backup_too_large"


def test_the_whole_counts_too(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    entries = made_here()
    entries[backups.SECRET_ENTRY] = b"x" * 200
    monkeypatch.setattr(backups, "RESTORE_MAX", len(entries[backups.DATABASE_ENTRY]) + 50)
    name = write_archive(entries)
    with pytest.raises(backups.BackupError) as refused:
        backups.stage_restore(name)
    assert refused.value.code == "backup_too_large"


def test_two_backups_in_the_same_second_get_names_of_their_own(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    monkeypatch.setattr(backups, "_stamp", lambda _moment: "2020-01-01-000000")
    start = threading.Barrier(2)
    made: list[Path] = []
    failed: list[BaseException] = []

    def one() -> None:
        start.wait()
        try:
            made.append(backups.create(kind=backups.MANUAL))
        except BaseException as exc:  # noqa: BLE001 - the test reports whatever went wrong
            failed.append(exc)

    threads = [threading.Thread(target=one) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failed == []
    assert len({path.name for path in made}) == 2
    for path in made:
        with zipfile.ZipFile(path) as archive:
            assert backups.MANIFEST in archive.namelist()
        path.unlink()


def test_check_reads_a_database_it_was_handed_whole(client: TestClient, operator: Account) -> None:
    """The control for the tests above: the archive as made is usable."""
    brief = backups.check(write_archive(made_here()))
    assert brief.usable and brief.schema == database.SCHEMA_VERSION and brief.missing_documents == 0


# --- A manifest of the wrong shape -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [{"accounts": "3"}, {"bytes": 1.5}, {"bytes": True}, {"accounts": -1}, {"version": 7}, {"created": None},
     {"kind": ["manual"]}, {"note": {"a": 1}}, {"unknown": 1}, {"kind": "k" * 100}, {"sha256": 7},
     {"media": {"photo00001": [5, "a" * 64]}}, {"files": 1}],
)
def test_a_manifest_with_a_field_of_the_wrong_kind_is_unusable_and_never_a_server_error(
    client: TestClient, operator: Account, change: dict
) -> None:
    name = write_archive(with_manifest(made_here(), **change))
    answer = client.post(f"/api/v1/backups/{name}/check")
    assert answer.status_code == 200, (change, answer.text)
    assert answer.json()["usable"] is False and answer.json()["database_ok"] is False, change
    refused = client.post(f"/api/v1/backups/{name}/restore", json={"password": PASSWORD})
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "backup_damaged"
    assert not backups.pending_folder().exists()
    listed = [entry["name"] for entry in client.get("/api/v1/backups").json()]
    assert name not in listed, "it does not pass for one of ours in the list"


def test_a_manifest_that_is_not_json_or_not_an_object_is_refused_as_invalid(client: TestClient, operator: Account) -> None:
    entries = made_here()
    for broken in (b"not json", b"[]", b"7", b'"x"', b"null"):
        name = write_archive({**entries, backups.MANIFEST: broken})
        answer = client.post(f"/api/v1/backups/{name}/check")
        assert answer.status_code in (200, 400), (broken, answer.status_code)
        if answer.status_code == 200:
            assert answer.json()["usable"] is False
        else:
            assert answer.json()["detail"]["code"] == "backup_invalid"


def test_an_uploaded_archive_with_a_manifest_of_the_wrong_shape_is_turned_away(
    client: TestClient, operator: Account, tmp_path: Path
) -> None:
    import base64

    name = write_archive(with_manifest(made_here(), accounts="many"), "nexpaper-2020-01-02-000000.zip")
    data = (backups.folder() / name).read_bytes()
    sent = client.post("/api/v1/backups/upload", content=data,
                       headers={"X-Nexpaper-Password": base64.b64encode(PASSWORD.encode()).decode()})
    assert sent.status_code == 400 and sent.json()["detail"]["code"] == "backup_invalid"


def test_a_good_manifest_still_passes(client: TestClient, operator: Account) -> None:
    name = write_archive(with_manifest(made_here(), note="a note"))
    answer = client.post(f"/api/v1/backups/{name}/check")
    assert answer.status_code == 200 and answer.json()["usable"] is True
