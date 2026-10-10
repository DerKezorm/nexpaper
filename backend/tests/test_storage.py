"""The readable place on the disk: names that cannot be attacks, files that follow their fields, nothing overwritten."""

from __future__ import annotations

import hashlib
import os
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Account, Job, Version
from app.names import clean_segment
from app.services import jobs, storage

from .conftest import make_account
from .papers import PDF, add_document, own_vault, shared_vault


def path_of(document_id: int, n: int = 1) -> str:
    with SessionLocal() as db:
        found = db.scalar(select(Version.original_path).where(Version.document_id == document_id, Version.n == n))
        assert found is not None
        return found


@pytest.mark.parametrize(("typed", "expected"), [
    ("Stadtwerke Lindenau", "Stadtwerke Lindenau"),
    ("../../etc/passwd", "etc passwd"),
    ("..", "x"), (".", "x"), ("...", "x"), ("", "x"), ("   ", "x"), (" . ", "x"),
    ("a/b\\c", "a b c"), ("C:\\Windows", "C Windows"), ("/abs/olute", "abs olute"),
    ("CON", "_CON"), ("con.txt", "_con.txt"), ("NUL", "_NUL"), ("com1", "_com1"), ("LPT9.log", "_LPT9.log"),
    ("COM\u00b9", "_COM\u00b9"), ("conn", "conn"),
    ("trailing dot.", "trailing dot"), ("trailing space ", "trailing space"), (".hidden", "hidden"),
    ("a\u0000b", "a b"), ("a\nb\tc", "a b c"), ("tab\u200bbed", "tab bed"), ("rtl\u202eevil", "rtl evil"),
    ('a<b>c:d"e|f?g*h', "a b c d e f g h"),
    ("x" * 500, "x" * 48), ("Ä" * 100, "Ä" * 48), ("e\u0301", "\u00e9"),
    ("lone\ud800surrogate", "lone surrogate"),
])
def test_what_a_person_types_becomes_one_safe_segment(typed: str, expected: str) -> None:
    cleaned = clean_segment(typed, "x")
    assert cleaned == expected or (expected == "lone surrogate" and cleaned.startswith("lone")), (typed, cleaned)
    assert "/" not in cleaned and "\\" not in cleaned and cleaned not in ("", ".", "..") and len(cleaned) <= 49
    assert not cleaned.endswith((" ", ".")) and not cleaned.startswith(" ")
    assert all(ord(c) >= 32 and ord(c) != 127 for c in cleaned)


@pytest.mark.parametrize("rel", [
    "", "/etc/passwd", "\\windows\\system32", "../outside.pdf", "a/../../outside.pdf", "a/./b.pdf", "a//b.pdf",
    "C:/Windows/x.pdf", "c:x.pdf", "a/b/..", "a\x00b.pdf", "..\\..\\x.pdf", "./x.pdf", "x/",
])
def test_a_stored_path_that_leaves_the_folder_is_refused(rel: str) -> None:
    with pytest.raises(storage.StorageError):
        storage.safe_path(rel)


def test_a_link_inside_the_folder_pointing_out_is_refused(tmp_path: Path) -> None:
    root = storage.root()
    root.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.pdf").write_bytes(b"secret")
    link = root / "trap"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        # Windows without the right to make symbolic links: a junction does the same without it.
        import subprocess

        command = ["cmd", "/c", "mklink", "/J", str(link), str(outside)]
        made = subprocess.run(command, capture_output=True, check=False) if os.name == "nt" else None
        if made is None or made.returncode != 0:
            pytest.skip("neither symbolic links nor junctions are possible here")
    try:
        with pytest.raises(storage.StorageError):
            storage.safe_path("trap/secret.pdf")
    finally:
        if os.path.islink(link):
            link.unlink()
        else:
            os.rmdir(link)


def test_a_path_that_resolves_outside_the_folder_is_refused_without_any_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same check as the test above, with the way out put in by hand: it does not depend on the right to make links,
    so it runs on every machine (a junction or a symbolic link is only one way a path ends up outside)."""
    root = storage.root()
    root.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    real = Path.resolve

    def resolve(self: Path, *args: object, **kwargs: object) -> Path:
        found = real(self, *args, **kwargs)  # type: ignore[arg-type]
        return outside / found.name if found.name == "trap.pdf" else found

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(storage.StorageError):
        storage.safe_path("Household/trap.pdf")
    assert storage.safe_path("Household/fine.pdf").is_relative_to(real(root))


def test_a_sibling_folder_with_the_same_beginning_is_not_inside_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``dokumente-other`` starts with ``dokumente`` and is not in it: a check on the beginning of the text would let it
    through, the check on the parents does not."""
    root = storage.root()
    root.mkdir(parents=True, exist_ok=True)
    sibling = root.parent / (root.name + "-other")
    sibling.mkdir(exist_ok=True)
    real = Path.resolve

    def resolve(self: Path, *args: object, **kwargs: object) -> Path:
        found = real(self, *args, **kwargs)  # type: ignore[arg-type]
        return sibling / found.name if found.name == "trap.pdf" else found

    monkeypatch.setattr(Path, "resolve", resolve)
    try:
        with pytest.raises(storage.StorageError):
            storage.safe_path("trap.pdf")
    finally:
        sibling.rmdir()


def test_a_document_lands_where_its_fields_say_and_the_checksum_is_the_files(operator: Account) -> None:
    vault = shared_vault("Household", operator)
    doc = add_document(vault, operator, "Anything", sender="Stadtwerke Lindenau", date=date(2026, 3, 14), kind_id=None)
    rel = path_of(doc)
    assert rel == "Household/2026/Stadtwerke Lindenau/2026-03-14 Document.pdf"
    path = storage.safe_path(rel)
    assert path.read_bytes() == PDF and path.is_relative_to(get_settings().data_dir / "dokumente")
    with SessionLocal() as db:
        version = db.scalar(select(Version).where(Version.document_id == doc))
        assert version is not None and version.sha256 == hashlib.sha256(PDF).hexdigest() and version.size == len(PDF)


def test_attacks_in_the_sender_and_the_title_stay_inside_the_folder(operator: Account) -> None:
    vault = own_vault(operator)
    root = (get_settings().data_dir / "dokumente").resolve()
    for sender in ("../../../etc", "..\\..\\x", "CON", "x" * 160, "/abs", "a/b/c", "NUL.pdf", "....", "C:\\x"):
        doc = add_document(vault, operator, "../../evil title", sender=sender, date=date(2026, 1, 1))
        full = storage.safe_path(path_of(doc)).resolve()
        assert root in full.parents, sender
        assert len(path_of(doc).split("/")) == 4
        assert full.read_bytes() == PDF
    assert not (get_settings().data_dir / "etc").exists()


def test_two_documents_with_the_same_fields_get_a_counter_and_neither_overwrites_the_other(operator: Account) -> None:
    vault = own_vault(operator)
    first = add_document(vault, operator, "One", sender="Anbieter", date=date(2026, 5, 5), content=b"first")
    second = add_document(vault, operator, "Two", sender="ANBIETER", date=date(2026, 5, 5), content=b"second")
    third = add_document(vault, operator, "Three", sender="Anbieter", date=date(2026, 5, 5), content=b"third")
    names = [Path(path_of(d)).name for d in (first, second, third)]
    assert names == ["2026-05-05 Document.pdf", "2026-05-05 Document (2).pdf", "2026-05-05 Document (3).pdf"]
    assert [storage.safe_path(path_of(d)).read_bytes() for d in (first, second, third)] == [b"first", b"second", b"third"]


def test_a_move_never_overwrites_a_file_that_is_there(tmp_path: Path) -> None:
    source, target = tmp_path / "a.pdf", tmp_path / "b.pdf"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    with pytest.raises(storage.StorageError):
        storage.move_without_overwriting(source, target)
    assert target.read_bytes() == b"old" and source.read_bytes() == b"new"
    target.unlink()
    storage.move_without_overwriting(source, target)
    assert target.read_bytes() == b"new" and not source.exists()


def test_changing_the_fields_renames_the_file_in_the_background_and_empties_the_old_folders(
    client: TestClient, operator: Account,
) -> None:
    vault = own_vault(operator)
    doc = add_document(vault, operator, "Bill", sender="Old Sender", date=date(2025, 12, 31))
    old = path_of(doc)
    assert client.patch(f"/api/v1/documents/{doc}", json={"sender": "New Sender", "date": "2026-02-01"}).status_code == 200
    assert path_of(doc) == old, "the file moves in the background, not inside the request"
    assert jobs.run_pending() == 1
    new = path_of(doc)
    assert new.endswith("2026/New Sender/2026-02-01 Document.pdf")
    assert storage.safe_path(new).read_bytes() == PDF and not storage.safe_path(old).exists()
    assert not storage.safe_path(old).parent.exists(), "the folder it left is empty and gone"
    assert storage.safe_path(old).parents[1].exists() is False or list(storage.safe_path(old).parents[1].iterdir()) != []
    with SessionLocal() as db:
        version = db.scalar(select(Version).where(Version.document_id == doc))
        assert version is not None and version.sha256 == hashlib.sha256(PDF).hexdigest(), "the checksum stays"
        assert db.scalar(select(Job.state).where(Job.ref == doc)) == "done"
    assert jobs.run_pending() == 0


def test_a_kind_renamed_by_the_operator_renames_the_files_of_its_documents(client: TestClient, operator: Account) -> None:
    kind = next(k for k in client.get("/api/v1/kinds").json() if k["key"] == "contract")
    docs = [add_document(own_vault(operator), operator, f"C{i}", sender="S", date=date(2026, 1, i + 1), kind_id=kind["id"])
            for i in range(3)]
    assert Path(path_of(docs[0])).name == "2026-01-01 Vertrag.pdf"
    assert client.patch(f"/api/v1/kinds/{kind['id']}", json={"name": "Agreement"}).status_code == 200
    assert jobs.run_pending() == 3
    assert [Path(path_of(d)).name for d in docs] == [f"2026-01-0{i + 1} Agreement.pdf" for i in range(3)]


def test_a_rename_that_broke_off_after_the_move_is_finished_by_the_next_run(client: TestClient, operator: Account) -> None:
    doc = add_document(own_vault(operator), operator, "Interrupted", sender="Before", date=date(2026, 1, 1))
    old = path_of(doc)
    client.patch(f"/api/v1/documents/{doc}", json={"sender": "After"})
    # The move was made, the database does not know yet (the run was killed in between).
    with SessionLocal() as db:
        moves = storage.plan(db, db.get(__import__("app.models", fromlist=["Document"]).Document, doc))
        assert len(moves) == 1
        target = moves[0][2]
    storage.move_without_overwriting(storage.safe_path(old), storage.safe_path(target))
    assert path_of(doc) == old
    assert jobs.run_pending() == 1
    assert path_of(doc) == target and storage.safe_path(target).read_bytes() == PDF


def test_a_job_that_finds_the_file_missing_or_changed_fails_without_touching_anything(
    client: TestClient, operator: Account,
) -> None:
    doc = add_document(own_vault(operator), operator, "Lost", sender="A", date=date(2026, 1, 1))
    old = path_of(doc)
    storage.safe_path(old).unlink()
    client.patch(f"/api/v1/documents/{doc}", json={"sender": "B"})
    for _ in range(storage.__dict__.get("RETRIES", jobs.ATTEMPTS) + 1):
        jobs.run_pending()
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.ref == doc))
        assert job is not None and job.state == "failed" and job.attempts == jobs.ATTEMPTS and job.error == "StorageError"
    assert path_of(doc) == old


def test_a_stored_path_outside_the_folder_is_never_moved_or_deleted(client: TestClient, operator: Account, tmp_path: Path) -> None:
    victim = tmp_path / "victim.pdf"
    victim.write_bytes(b"keep me")
    doc = add_document(own_vault(operator), operator, "Tampered", sender="A", date=date(2026, 1, 1))
    with SessionLocal() as db:
        version = db.scalar(select(Version).where(Version.document_id == doc))
        assert version is not None
        version.original_path = "../../" + os.path.relpath(victim, get_settings().data_dir / "dokumente").replace("\\", "/")
        db.commit()
    client.patch(f"/api/v1/documents/{doc}", json={"sender": "B"})
    for _ in range(jobs.ATTEMPTS):
        jobs.run_pending()
    assert victim.read_bytes() == b"keep me"
    assert storage.remove_files([os.path.relpath(victim, get_settings().data_dir / "dokumente")]) == 0
    assert victim.exists()


def test_a_job_left_running_by_a_stopped_server_waits_again() -> None:
    with SessionLocal() as db:
        db.add(Job(kind=jobs.RENAME, ref=77, state="running", attempts=1))
        db.add(Job(kind=jobs.RENAME, ref=78, state="running", attempts=1))
        db.add(Job(kind=jobs.RENAME, ref=78, state="queued"))
        db.commit()
        jobs.recover(db)
        states = {(j.ref, j.state) for j in db.scalars(select(Job))}
    assert (77, "queued") in states and (78, "queued") in states and (78, "running") not in states


def test_only_one_job_of_a_kind_waits_for_a_document_at_a_time() -> None:
    with SessionLocal() as db:
        for _ in range(5):
            jobs.enqueue(db, jobs.RENAME, 5)
            db.commit()
        jobs.enqueue(db, jobs.RENAME, 6)
        jobs.enqueue(db, jobs.DELETE_FILES, 5, {"paths": []})
        db.commit()
        assert len(list(db.scalars(select(Job)))) == 3


def test_case_does_not_make_two_names(operator: Account) -> None:
    """A disk that ignores case (Windows, macOS, a NAS share) would merge ``Anbieter`` and ``ANBIETER`` folders."""
    vault = own_vault(operator)
    a = add_document(vault, operator, "a", sender="Anbieter", date=date(2026, 1, 1), content=b"1")
    b = add_document(vault, operator, "b", sender="anbieter", date=date(2026, 1, 1), content=b"2")
    assert path_of(a).lower() != path_of(b).lower()
    assert len({p.lower() for p in (path_of(a), path_of(b))}) == 2


def test_the_vault_folder_of_a_person_is_stable_when_the_name_changes(client: TestClient) -> None:
    person = make_account("jule")
    doc = add_document(own_vault(person), person, "Mine", sender="S", date=date(2026, 1, 1))
    before = path_of(doc)
    from app.services.vaults import update_vault

    with SessionLocal() as db:
        db.get(Account, person.id).display_name = "Julia"  # type: ignore[union-attr]
        db.commit()
    assert path_of(doc) == before and before.startswith("jule/")
    assert update_vault is not None


def test_the_background_loop_runs_the_waiting_jobs(client: TestClient, operator: Account) -> None:
    import asyncio

    doc = add_document(own_vault(operator), operator, "Loop", sender="Before", date=date(2026, 1, 1))
    client.patch(f"/api/v1/documents/{doc}", json={"sender": "After"})

    async def run() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(jobs.run_forever(stop))
        for _ in range(50):
            await asyncio.sleep(0.1)
            if "After" in path_of(doc):
                break
        stop.set()
        await asyncio.wait_for(task, 5)

    try:
        asyncio.run(run())
    finally:
        # The loop marks the server as stopping when it ends; a test after this one must not find it so.
        jobs.stopping.clear()
    assert "After" in path_of(doc)


def test_without_hard_links_a_move_still_never_overwrites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Some network shares have no hard links: the rename path checks that the target is free (mutation M31)."""

    def no_links(_source: object, _target: object) -> None:
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(storage.os, "link", no_links)
    source, target = tmp_path / "a.pdf", tmp_path / "b.pdf"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    with pytest.raises(storage.StorageError):
        storage.move_without_overwriting(source, target)
    assert target.read_bytes() == b"old" and source.read_bytes() == b"new"
    target.unlink()
    storage.move_without_overwriting(source, target)
    assert target.read_bytes() == b"new" and not source.exists()


def test_a_rename_that_broke_off_between_link_and_removal_leaves_no_second_copy(
    client: TestClient, operator: Account,
) -> None:
    doc = add_document(own_vault(operator), operator, "Twice", sender="Before", date=date(2026, 1, 1))
    old = path_of(doc)
    client.patch(f"/api/v1/documents/{doc}", json={"sender": "After"})
    with SessionLocal() as db:
        from app.models import Document

        target = storage.plan(db, db.get(Document, doc))[0][2]
    # The run linked the new name and died before the old name went: the file is there twice.
    storage.safe_path(target).parent.mkdir(parents=True, exist_ok=True)
    os.link(storage.safe_path(old), storage.safe_path(target))
    assert jobs.run_pending() == 1
    assert path_of(doc) == target and storage.safe_path(target).read_bytes() == PDF
    assert not storage.safe_path(old).exists()
    assert sorted(p.name for p in storage.root().rglob("*.pdf")) == [Path(target).name]


def test_the_same_file_of_another_document_is_never_taken_for_a_leftover(client: TestClient, operator: Account) -> None:
    """Two documents with the same content: the name one of them is going to is the other's file. It is not a leftover
    of the first: the first gets a counter, both files stay."""
    vault = own_vault(operator)
    first = add_document(vault, operator, "One", sender="Same", date=date(2026, 2, 2))
    second = add_document(vault, operator, "Two", sender="Other", date=date(2026, 2, 2))
    client.patch(f"/api/v1/documents/{second}", json={"sender": "Same"})
    assert jobs.run_pending() == 1
    assert path_of(first) != path_of(second) and path_of(second).endswith(" (2).pdf")
    assert storage.safe_path(path_of(first)).is_file() and storage.safe_path(path_of(second)).is_file()


def test_what_a_broken_off_write_left_goes_at_the_next_start(operator: Account) -> None:
    doc = add_document(own_vault(operator), operator, "Kept", sender="S", date=date(2026, 3, 3))
    folder = storage.safe_path(path_of(doc)).parent
    (folder / ".incoming-123-456-2026-03-03 Docum").write_bytes(b"half")
    (folder / ".incoming-9-9-x").write_bytes(b"")
    assert storage.sweep_incoming() == 2
    assert [p.name for p in folder.iterdir()] == [Path(path_of(doc)).name]
    assert storage.sweep_incoming() == 0
