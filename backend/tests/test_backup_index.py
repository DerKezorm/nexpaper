"""A backup leaves the search index out and a restore builds it anew; the trial run names the documents whose files are
missing or have another checksum on the disk, and the documents of today the archive does not know."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import db as database
from app.config import get_settings
from app.db import SessionLocal
from app.models import Account, Document, Job, Version, VersionText
from app.services import backups, filecheck, jobs, search_index, storage

from .conftest import PASSWORD, make_account
from .papers import PDF, add_document, own_vault


def indexed_ids() -> set[int]:
    with SessionLocal() as db:
        return set(db.scalars(text("SELECT rowid FROM doc_fts WHERE doc_fts MATCH 'rechnung'")))


def unpack(path: Path, into: Path) -> Path:
    with zipfile.ZipFile(path) as archive:
        target = into / "inside.db"
        target.write_bytes(archive.read(backups.DATABASE_ENTRY))
    return target


def put_back(path: Path, inside: Path, name: str) -> None:
    """The archive with the database ``inside`` in it, under ``name``, and a manifest that names that database."""
    import hashlib

    with zipfile.ZipFile(path) as archive:
        entries = {entry: archive.read(entry) for entry in archive.namelist()}
    data = inside.read_bytes()
    manifest = {**json.loads(entries[backups.MANIFEST]), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    entries[backups.DATABASE_ENTRY] = data
    entries[backups.MANIFEST] = json.dumps(manifest).encode()
    with zipfile.ZipFile(backups.folder() / name, "w") as archive:
        for entry, content in entries.items():
            archive.writestr(entry, content)


def made_documents() -> tuple[Account, list[int]]:
    jule = make_account("jule")
    ids = [add_document(own_vault(jule), jule, f"Rechnung {number}", content=PDF + str(number).encode())
           for number in range(1, 4)]
    return jule, ids


def test_the_archive_has_no_index_and_the_live_database_keeps_its_own(operator: Account, tmp_path: Path) -> None:
    _jule, ids = made_documents()
    assert indexed_ids() == set(ids), "the index of the running database is complete"
    path = backups.create(kind=backups.MANUAL)
    inside = unpack(path, tmp_path)
    with closing(sqlite3.connect(inside)) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        assert not {name for name in names if name.startswith(("doc_fts", "doc_tri"))}
        assert "documents_search_gone" not in names
        assert connection.execute("SELECT count(*) FROM search_entries").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM documents").fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM version_texts").fetchone()[0] >= 0
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read(backups.MANIFEST))
    assert manifest["documents"] == 3 and manifest["with_index"] is False
    assert indexed_ids() == set(ids), "making a backup took nothing from the live index"
    assert [entry.documents for entry in backups.entries()] == [3]


def test_the_archive_is_small_whatever_the_index_holds(operator: Account, tmp_path: Path) -> None:
    jule = make_account("jule")
    vault = own_vault(jule)
    words = " ".join(f"wort{number:05d}" for number in range(4000))
    for number in range(30):
        made = add_document(vault, jule, f"Rechnung {number}", content=PDF + str(number).encode())
        with SessionLocal() as db:
            version = db.scalar(select(Version).where(Version.document_id == made))
            db.add(VersionText(version_id=version.id, document_id=made, text=f"{number} {words}", pages=1,
                               digest=search_index.text_digest(f"{number} {words}")))
            db.flush()
            search_index.refresh(db, [made])
            db.commit()
    with SessionLocal() as db:
        index = db.scalar(text("SELECT sum(length(block)) FROM doc_tri_data")) or 0
        assert index > 500_000, "the index of the live database is large"
        live = db.scalar(text("PRAGMA page_count")) * db.scalar(text("PRAGMA page_size"))
    inside = unpack(backups.create(kind=backups.MANUAL), tmp_path)
    with closing(sqlite3.connect(inside)) as connection:
        size = connection.execute("PRAGMA page_count").fetchone()[0] * connection.execute("PRAGMA page_size").fetchone()[0]
    # The text of the documents stays (it is what the index is rebuilt from); the index goes.
    assert size < live - 0.9 * index, f"the copy has {size} bytes, the live database {live} with an index of {index}"


def test_a_restore_builds_the_search_anew_and_the_trial_run_says_so(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    jule, ids = made_documents()
    with SessionLocal() as db:
        filecheck.start(db)
    while True:
        with SessionLocal() as db:
            if filecheck.run_portion(db):
                break
    with SessionLocal() as db:
        assert not filecheck.due(db), "just checked: not due for a week"
    name = backups.create().name
    later = add_document(own_vault(jule), jule, "Rechnung später", content=PDF + b"later")
    brief = client.post(f"/api/v1/backups/{name}/check").json()
    assert brief["usable"] and brief["documents"] == 3
    assert brief["missing_documents"] == 0 and brief["changed_documents"] == 0
    assert brief["newer_documents"] == 1 and brief["rebuilds_index"] is True
    monkeypatch.setattr(backups, "restart_soon", lambda: None)
    assert client.post(f"/api/v1/backups/{name}/restore", json={"password": PASSWORD}).status_code == 202
    assert backups.apply_pending() is True
    database.init_db()
    with SessionLocal() as db:
        assert filecheck.due(db), "the files may not be the ones the backup knew: the check runs again at once"
    # The tables are there again, empty; the start finds the documents without an entry and queues the job.
    with SessionLocal() as db:
        assert db.scalar(text("SELECT count(*) FROM doc_fts")) == 0
        assert search_index.stale_ids(db, 10) == ids
        jobs.recover(db)
        assert db.scalars(select(Job.kind).where(Job.state == "queued", Job.kind == jobs.INDEX)).all() == ["index"]
    jobs.run_pending(kinds=(jobs.INDEX,))
    assert indexed_ids() == set(ids)
    with SessionLocal() as db:
        assert db.get(Document, later) is None
        assert search_index.stale_ids(db, 10) == []
        # The trigger that drops the entries of a deleted document is back.
        db.delete(db.get(Document, ids[0]))
        db.commit()
    assert indexed_ids() == set(ids[1:])


def test_the_trial_run_names_missing_and_changed_files(client: TestClient, operator: Account) -> None:
    _jule, ids = made_documents()
    name = backups.create().name
    with SessionLocal() as db:
        gone = db.scalar(select(Version.original_path).where(Version.document_id == ids[0]))
        altered = db.scalar(select(Version.original_path).where(Version.document_id == ids[1]))
    storage.safe_path(gone).unlink()
    storage.safe_path(altered).write_bytes(PDF + b"someone wrote here")
    brief = backups.check(name)
    assert (brief.documents, brief.missing_documents, brief.changed_documents, brief.not_compared) == (3, 1, 1, 0)
    assert brief.usable
    # Without time for reading, a file that is there counts as not compared, never as whole or as changed.
    quick = backups.check(name, hash_seconds=0)
    assert (quick.missing_documents, quick.changed_documents, quick.not_compared) == (1, 0, 2)


def test_a_document_still_being_read_is_not_looked_for(client: TestClient, operator: Account) -> None:
    _jule, ids = made_documents()
    with SessionLocal() as db:
        db.get(Document, ids[0]).status = "processing"
        db.commit()
    name = backups.create().name
    with SessionLocal() as db:
        path = db.scalar(select(Version.original_path).where(Version.document_id == ids[0]))
    storage.safe_path(path).unlink()
    assert backups.check(name).missing_documents == 0


def test_a_path_in_a_foreign_database_that_leaves_the_folder_counts_as_missing_and_reads_nothing(
    client: TestClient, operator: Account, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(PDF)
    _jule, ids = made_documents()
    path = backups.create(kind=backups.MANUAL)
    inside = unpack(path, tmp_path)
    with closing(sqlite3.connect(inside)) as connection:
        connection.execute("UPDATE versions SET original_path = ? WHERE document_id = ?", (str(outside), ids[0]))
        connection.execute("UPDATE versions SET original_path = ? WHERE document_id = ?", ("../../etc/passwd", ids[1]))
        connection.commit()
    name = "nexpaper-2020-02-02-000000.zip"
    put_back(path, inside, name)
    brief = backups.check(name)
    assert brief.usable and brief.missing_documents == 2


def test_an_archive_from_before_there_were_documents_has_none_to_look_for(client: TestClient, operator: Account,
                                                                          tmp_path: Path) -> None:
    """The first schema, as recorded: the trial run brings it up on its scratch copy, as the start would, and finds no
    documents."""
    from .test_schema import RECORDS

    path = backups.create(kind=backups.MANUAL)
    inside = tmp_path / "inside.db"
    with closing(sqlite3.connect(inside)) as connection:
        connection.executescript((RECORDS / "v1.sql").read_text(encoding="utf-8"))
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    name = "nexpaper-2020-03-03-000000.zip"
    put_back(path, inside, name)
    brief = backups.check(name)
    assert brief.usable and brief.schema == 1
    assert brief.documents == 0 and brief.missing_documents == 0 and brief.rebuilds_index is False


def test_the_backup_of_a_server_with_no_index_tables_yet_still_works(operator: Account) -> None:
    with SessionLocal() as db:
        db.execute(text("DROP TRIGGER IF EXISTS documents_search_gone"))
        db.execute(text("DROP TABLE IF EXISTS doc_fts"))
        db.execute(text("DROP TABLE IF EXISTS doc_tri"))
        db.commit()
    try:
        path = backups.create(kind=backups.MANUAL)
        assert path.is_file()
    finally:
        database.init_db()


def test_data_folder_setting_is_the_test_one() -> None:
    assert "nexpaper-tests-" in str(get_settings().data_dir)
