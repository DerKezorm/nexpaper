"""The check of the files: portions, signs on the documents, the history, the notice to the operators, and what it must
not do (read outside the folder, read half-moved files, run over itself)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, Document, Event, Version
from app.services import filecheck, settings_service, storage, tell

from .conftest import make_account, new_client
from .papers import PDF, add_document, own_vault


@pytest.fixture
def told(monkeypatch: pytest.MonkeyPatch) -> list[tell.Notice]:
    """The notices to the operators, caught instead of sent."""
    caught: list[tell.Notice] = []
    monkeypatch.setattr(tell, "operator", caught.append)
    return caught


def documents(count: int) -> list[int]:
    jule = make_account("jule")
    return [add_document(own_vault(jule), jule, f"Rechnung {number}", content=PDF + str(number).encode())
            for number in range(count)]


def path_of(document_id: int, n: int = 1) -> Path:
    with SessionLocal() as db:
        return storage.safe_path(db.scalar(select(Version.original_path).where(Version.document_id == document_id,
                                                                               Version.n == n)))


def run_all(**limits: int) -> int:
    """A whole check, portion by portion. Returns how many portions it took."""
    with SessionLocal() as db:
        assert filecheck.start(db)
    portions = 0
    while True:
        portions += 1
        with SessionLocal() as db:
            if filecheck.run_portion(db, **limits):
                return portions
        assert portions < 500


def state_of(document_id: int) -> str:
    with SessionLocal() as db:
        return str(db.scalar(select(Document.files_state).where(Document.id == document_id)))


def actions(document_id: int) -> list[str]:
    with SessionLocal() as db:
        return list(db.scalars(select(Event.action).where(Event.document_id == document_id).order_by(Event.id)))


def test_whole_files_leave_no_sign(operator: Account, told: list[tell.Notice]) -> None:
    ids = documents(3)
    run_all()
    assert [state_of(i) for i in ids] == ["", "", ""]
    with SessionLocal() as db:
        status = filecheck.status(db)
    assert status["running"] is False and status["last_documents"] == 3 and status["last_files"] == 3
    assert status["last_problems"] == 0 and status["flagged_documents"] == 0 and status["last_finished_at"]
    assert told == []
    assert not any(a.startswith("files_") for i in ids for a in actions(i))


def test_a_missing_and_a_changed_file_get_a_sign_a_line_in_the_history_and_one_notice(
    operator: Account, told: list[tell.Notice]
) -> None:
    gone, altered, fine = documents(3)
    path_of(gone).unlink()
    path_of(altered).write_bytes(PDF + b"someone wrote here")
    run_all()
    assert (state_of(gone), state_of(altered), state_of(fine)) == ("missing", "changed", "")
    assert "files_missing" in actions(gone) and "files_changed" in actions(altered)
    assert len(told) == 1, "one notice for the whole run, not one per document"
    assert told[0].url == filecheck.PATH and "2" in told[0].texts["en"][1]
    with SessionLocal() as db:
        status = filecheck.status(db)
    assert status["last_problems"] == 2 and status["flagged_documents"] == 2
    # The same problem found again is not new: no second line, no second notice.
    run_all()
    assert actions(gone).count("files_missing") == 1 and len(told) == 1


def test_a_document_whole_again_loses_its_sign_and_says_so(operator: Account, told: list[tell.Notice]) -> None:
    (one,) = documents(1)
    path = path_of(one)
    original = path.read_bytes()
    path.write_bytes(b"damaged")
    run_all()
    assert state_of(one) == "changed"
    path.write_bytes(original)
    run_all()
    assert state_of(one) == ""
    assert actions(one)[-2:] == ["files_changed", "files_whole"]
    assert len(told) == 1


def test_missing_wins_over_changed_in_one_document(operator: Account) -> None:
    (one,) = documents(1)
    with SessionLocal() as db:
        first = db.scalar(select(Version).where(Version.document_id == one))
        db.add(Version(document_id=one, n=2, original_path=first.original_path.replace(".pdf", " (2).pdf"),
                       sha256="0" * 64, size=1, pages=1, created_at=first.created_at))
        db.commit()
    path_of(one).write_bytes(b"damaged")
    run_all()
    assert state_of(one) == "missing", "version 2 has no file; version 1 is changed; the worse one counts"


def test_the_searchable_copy_is_noted_the_first_time_and_compared_after(operator: Account) -> None:
    (one,) = documents(1)
    with SessionLocal() as db:
        version = db.scalar(select(Version).where(Version.document_id == one))
        archive = version.original_path.replace(".pdf", " (searchable).pdf")
        storage.safe_path(archive).write_bytes(PDF + b"searchable")
        version.archive_path = archive
        db.commit()
    run_all()
    assert state_of(one) == ""
    with SessionLocal() as db:
        noted = db.scalar(select(Version.archive_sha256).where(Version.document_id == one))
    assert noted == storage.sha256_of(storage.safe_path(archive))
    storage.safe_path(archive).write_bytes(PDF + b"searchable, but changed")
    run_all()
    assert state_of(one) == "changed"
    storage.safe_path(archive).unlink()
    run_all()
    assert state_of(one) == "missing"


def test_a_path_that_leaves_the_folder_is_missing_and_reads_nothing(operator: Account, tmp_path: Path) -> None:
    (one,) = documents(1)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(PDF)
    with SessionLocal() as db:
        db.execute(Version.__table__.update().where(Version.document_id == one).values(original_path=str(outside)))
        db.commit()
    run_all()
    assert state_of(one) == "missing"


def test_the_work_goes_in_portions_and_a_stop_in_between_is_picked_up(operator: Account) -> None:
    ids = documents(7)
    path_of(ids[5]).unlink()
    with SessionLocal() as db:
        filecheck.start(db)
    seen = []
    while True:
        with SessionLocal() as db:
            done = filecheck.run_portion(db, max_files=2)
            current = filecheck.state(db)
        seen.append((current["cursor"], current["documents"]))
        if done:
            break
    assert len(seen) == 4, seen
    assert [documents_done for _cursor, documents_done in seen] == [2, 4, 6, 7]
    assert state_of(ids[5]) == "missing"
    assert state_of(ids[0]) == ""


def test_the_bytes_of_a_portion_are_bounded_too(operator: Account) -> None:
    ids = documents(4)
    with SessionLocal() as db:
        filecheck.start(db)
        # Each file is some 70 bytes; 100 bytes allow two of them (the one that crosses the line is finished).
        assert filecheck.run_portion(db, max_files=40, max_bytes=100) is False
        assert filecheck.state(db)["documents"] == 2
        assert filecheck.run_portion(db, max_files=40, max_bytes=100) is True
    assert filecheck.state(SessionLocal())["documents"] == len(ids)


def test_a_check_that_runs_is_not_started_again_and_a_portion_without_one_does_nothing(operator: Account) -> None:
    documents(2)
    with SessionLocal() as db:
        assert filecheck.start(db) is True
        assert filecheck.start(db) is False
        assert filecheck.status(db)["running"] is True
    with SessionLocal() as db:
        assert filecheck.run_portion(db) is True
        assert filecheck.run_portion(db) is True, "nothing running: nothing to do"
        assert filecheck.status(db)["running"] is False


def test_the_weekly_check_is_due_after_a_week_and_never_while_one_runs(operator: Account) -> None:
    documents(1)
    now = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    with SessionLocal() as db:
        assert filecheck.due(db, now=now), "never checked"
    run_all()
    with SessionLocal() as db:
        finished = filecheck._parse(filecheck.state(db)["finished_at"])
        assert finished is not None
        assert not filecheck.due(db, now=finished + timedelta(days=6, hours=23))
        assert filecheck.due(db, now=finished + timedelta(days=7))
        filecheck.start(db)
        assert not filecheck.due(db, now=finished + timedelta(days=30))


def test_the_loop_starts_the_weekly_check_and_goes_on_with_portions(operator: Account) -> None:
    documents(3)
    ran, _took = filecheck.run_once(max_files=2)
    assert ran is True
    with SessionLocal() as db:
        assert filecheck.status(db)["running"] is True
    ran, _took = filecheck.run_once(max_files=2)
    with SessionLocal() as db:
        assert filecheck.status(db)["running"] is False
    # Just checked: nothing to do until next week.
    assert filecheck.run_once() == (False, 0.0)


def test_the_pause_after_a_portion_is_as_long_as_the_portion_within_bounds() -> None:
    assert filecheck.pause_after(0.0) == filecheck.PAUSE_MIN
    assert filecheck.pause_after(5.0) == 5.0
    assert filecheck.pause_after(500.0) == filecheck.PAUSE_MAX


def test_a_document_being_worked_on_is_skipped_not_read_half_moved(operator: Account) -> None:
    busy, other = documents(2)
    with storage.files_of([busy], 0):
        # The lock is the one of a stripe: another document of the same stripe would wait too, which costs nothing.
        run_all()
    with SessionLocal() as db:
        state = filecheck.state(db)
    assert state["last_skipped"] >= 1 and state["last_documents"] == 2
    assert state_of(other) == "" and state_of(busy) == ""


def test_a_document_still_being_read_is_not_looked_at(operator: Account) -> None:
    (one,) = documents(1)
    path_of(one).unlink()
    with SessionLocal() as db:
        db.get(Document, one).status = "processing"
        db.commit()
    run_all()
    assert state_of(one) == ""


def test_a_document_deleted_while_it_was_looked_at_leaves_nothing_behind(
    operator: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    (one,) = documents(1)
    path_of(one).unlink()
    real = filecheck.look_at

    def deleting(rows: Any) -> Any:
        seen = real(rows)
        with SessionLocal() as db:
            db.delete(db.get(Document, one))
            db.commit()
        return seen

    monkeypatch.setattr(filecheck, "look_at", deleting)
    run_all()
    with SessionLocal() as db:
        assert db.get(Document, one) is None
        assert db.scalar(select(Event).where(Event.action == "files_missing")) is None


def test_the_state_of_a_check_is_a_setting_that_survives_the_server(operator: Account) -> None:
    documents(2)
    with SessionLocal() as db:
        filecheck.start(db)
        filecheck.run_portion(db, max_files=1)
    with SessionLocal() as db:
        stored = settings_service.get(db, filecheck.KEY)
    assert stored["running"] is True and stored["cursor"] > 0 and stored["documents"] == 1


# --- Over HTTP -------------------------------------------------------------------------------------------------------


def test_the_sign_is_on_the_document_for_everybody_who_sees_it(client: TestClient, operator: Account) -> None:
    jule = make_account("jule")
    (one,) = [add_document(own_vault(jule), jule, "Rechnung", content=PDF + b"x")]
    path_of(one).unlink()
    run_all()
    with new_client(jule) as browser:
        assert browser.get(f"/api/v1/documents/{one}").json()["files_state"] == "missing"
        listed = browser.get("/api/v1/documents").json()
        rows = listed["items"] if isinstance(listed, dict) else listed
        assert [row["files_state"] for row in rows] == ["missing"]
        history = browser.get(f"/api/v1/documents/{one}/events").json()
        assert "files_missing" in [event["action"] for event in history]


def test_only_the_operator_in_a_browser_asks_and_starts(client: TestClient, operator: Account) -> None:
    documents(2)
    started = client.post("/api/v1/storage/files/check")
    assert started.status_code == 202 and started.json()["started"] is True and started.json()["running"] is True
    again = client.post("/api/v1/storage/files/check")
    assert again.status_code == 202 and again.json()["started"] is False
    card = client.get("/api/v1/storage").json()
    assert card["files"]["running"] is True and card["files"]["every_days"] == 7
    member = make_account("tom")
    with new_client(member) as browser:
        assert browser.get("/api/v1/storage").status_code == 403
        assert browser.post("/api/v1/storage/files/check").status_code == 403
    with new_client() as stranger:
        assert stranger.get("/api/v1/storage").status_code == 401
        assert stranger.post("/api/v1/storage/files/check").status_code == 401


# --- A sign goes when its cause goes (not a week later) ----------------------------------------------------------------


def flagged_document() -> tuple[int, bytes]:
    """A document whose file is gone and has been seen to be: the sign is on. Returns it and what the file held."""
    (one,) = documents(1)
    path = path_of(one)
    content = path.read_bytes()
    path.unlink()
    run_all()
    assert state_of(one) == "missing"
    return one, content


def jule_in_a_browser() -> TestClient:
    """The browser of the person the document belongs to (the operator does not see a personal vault)."""
    with SessionLocal() as db:
        account = db.scalar(select(Account).where(Account.name == "jule"))
        assert account is not None
        db.expunge(account)
    return new_client(account)


def jobs_done() -> None:
    from .intake import process_all

    process_all()


def test_a_document_back_from_the_trash_is_looked_at_again_at_once() -> None:
    one, content = flagged_document()
    with jule_in_a_browser() as jule:
        assert jule.delete(f"/api/v1/documents/{one}").status_code == 200
        path_of(one).write_bytes(content)
        jobs_done()
        assert state_of(one) == "missing", "in the trash nothing is looked at again: the file may still be on its way"
        assert jule.post(f"/api/v1/documents/{one}/restore").status_code == 200
    jobs_done()
    assert state_of(one) == ""
    assert "files_whole" in actions(one)


def test_a_document_that_is_in_order_is_not_looked_at_again_for_nothing() -> None:
    (one,) = documents(1)
    with jule_in_a_browser() as jule:
        assert jule.delete(f"/api/v1/documents/{one}").status_code == 200
        assert jule.post(f"/api/v1/documents/{one}/restore").status_code == 200
    with SessionLocal() as db:
        from app.models import Job

        assert db.scalars(select(Job.id).where(Job.kind == "files")).all() == []


def test_a_new_version_and_a_version_put_away_look_at_the_document_again_at_once(
    client: TestClient, operator: Account
) -> None:
    from .files import encrypted_pdf
    from .test_pagetools import made, pdf, upload_version, versions

    document = made(client)["id"]
    path = path_of(document)
    content = path.read_bytes()
    path.unlink()
    run_all()
    assert state_of(document) == "missing"
    # The file is put back; nothing looks, so the sign stays ... until a new version has been read.
    path.write_bytes(content)
    assert state_of(document) == "missing"
    assert upload_version(client, document, "neu.pdf", pdf("Neu", "Neuer")).status_code == 202
    jobs_done()
    assert state_of(document) == ""
    # The same for a version that could not be read and is put away. (The new version took the name; the first one was
    # renamed to "(version 1)", so the path is asked again.)
    path_of(document, 1).unlink()
    run_all()
    assert state_of(document) == "missing"
    path_of(document, 1).write_bytes(content)
    assert upload_version(client, document, "kaputt.pdf", encrypted_pdf("x")).status_code == 202
    jobs_done()
    failed = [row.n for row in versions(document) if row.n > 2]
    assert failed, "the unreadable version is there"
    assert state_of(document) == "missing", "a version that failed is no reason to look again"
    assert client.delete(f"/api/v1/documents/{document}/versions/{failed[0]}").status_code in (200, 204)
    jobs_done()
    assert state_of(document) == ""


def test_the_operator_asks_for_one_document_and_the_sign_goes_when_the_file_is_back(
    client: TestClient, operator: Account
) -> None:
    one, content = flagged_document()
    path_of(one).write_bytes(content)
    assert state_of(one) == "missing", "nothing looked again yet"
    answer = client.post(f"/api/v1/storage/files/documents/{one}/check")
    assert answer.status_code == 200 and answer.json() == {"files_state": ""}
    assert state_of(one) == ""
    path_of(one).write_bytes(content + b"changed")
    assert client.post(f"/api/v1/storage/files/documents/{one}/check").json() == {"files_state": "changed"}
    assert state_of(one) == "changed"


def test_asking_for_one_document_needs_the_operator_in_a_browser_and_a_document_that_exists(
    client: TestClient, operator: Account
) -> None:
    one, _content = flagged_document()
    assert client.post("/api/v1/storage/files/documents/99999/check").status_code == 404
    member = make_account("tom")
    with new_client(member) as browser:
        assert browser.post(f"/api/v1/storage/files/documents/{one}/check").status_code == 403
    with new_client() as stranger:
        assert stranger.post(f"/api/v1/storage/files/documents/{one}/check").status_code == 401
    token = client.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with TestClient(client.app, base_url="http://testserver") as device:
        refused = device.post(f"/api/v1/storage/files/documents/{one}/check", headers={"Authorization": f"Bearer {token}"})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "browser_only"
    assert state_of(one) == "missing"


def test_asking_while_a_tool_works_on_the_files_answers_try_again(client: TestClient, operator: Account) -> None:
    one, content = flagged_document()
    path_of(one).write_bytes(content)
    with storage.files_of([one], 1):
        busy = client.post(f"/api/v1/storage/files/documents/{one}/check")
    assert busy.status_code == 409 and busy.json()["detail"]["code"] == "try_again"
    assert state_of(one) == "missing"
