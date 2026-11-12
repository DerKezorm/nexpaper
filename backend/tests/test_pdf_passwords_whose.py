"""Protected PDFs (P1), after the review: whose kept passwords are tried (only the person who brought the file, or the
person a delivered file came for into their personal vault; never by way of the owner of the document), a password
typed through a share is kept by the person who typed it, the brake per document counts per person and takes all or
nothing, a file that only claims to be encrypted is refused, the trial run of a backup counts kept passwords that would
come back, and the gaps the reviewer's mutations found. Every password is made at run time."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import clock
from app.db import SessionLocal
from app.models import Account, Event, PdfPassword, Version, VersionText
from app.services import backups, brakes, jobs, pdf_passwords, processing, receiving, storage

from . import files
from .conftest import make_account, new_client
from .intake import process_all, version_of
from .papers import own_vault, shared_vault
from .test_pdf_passwords import arrive, encrypted_bytes, protected, unlock, word


def keep_for(account: Account, password: str, name: str = "Gehalt") -> None:
    with SessionLocal() as db:
        assert pdf_passwords._keep(db, account.id, name, password) == "kept"
        db.commit()


def matched(account: Account) -> list[Any]:
    with SessionLocal() as db:
        return list(db.scalars(select(PdfPassword.last_matched_at).where(PdfPassword.user_id == account.id)))


def new_version(c: TestClient, document_id: int, data: bytes) -> None:
    answer = c.post(f"/api/v1/documents/{document_id}/versions", files={"file": ("neu.pdf", data, "application/pdf")})
    assert answer.status_code in (200, 201, 202), answer.text
    process_all()


def what_is_seen(c: TestClient, document_id: int) -> dict[str, Any]:
    """Everything a person with edit sees of the newest version: its state, its mark, a history line about it."""
    versions = c.get(f"/api/v1/documents/{document_id}/versions").json()
    newest = max(versions, key=lambda v: v["n"])
    events = c.get(f"/api/v1/documents/{document_id}/events").json()
    return {"state": newest["state"], "error": newest["error"], "protected": newest["original_protected"],
            "pages": newest["pages"], "opened_lines": sum(1 for e in events if e["action"] == "pdf_opened")}


@pytest.fixture
def jule(client: TestClient, operator: Account) -> Account:
    return make_account("jule")


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Every run of the worker, whether it carried passwords (True) or not."""
    seen: list[bool] = []
    real = processing._spawn

    def spawn(request: dict[str, Any], timeout: int, cwd: str) -> Any:
        seen.append(bool(request.get("passwords")))
        return real(request, timeout, cwd)

    monkeypatch.setattr(processing, "_spawn", spawn)
    return seen


# --- 1. Whose kept passwords are tried ---------------------------------------------------------------------------------


@pytest.mark.parametrize("way", ["vault_edit", "share_edit"])
def test_a_new_version_never_tries_the_owners_kept_passwords(
        client: TestClient, operator: Account, way: str, runs: list[bool]) -> None:
    """The reviewer's probe: Tom may change Jule's document and uploads versions he encrypted himself, once with a
    guess and once with the password Jule keeps. He learns nothing: both end alike, nothing is marked, no history line,
    no second run of the worker (the same time), and Jule's entry did not fit."""
    jule, tom = make_account("jule"), make_account("tom")
    secret = word()
    keep_for(jule, secret)
    with new_client(jule) as c:
        if way == "vault_edit":
            house = shared_vault("Haushalt", operator, (jule, "edit"), (tom, "edit"))
            document = arrive(c, files.make_pdf(["Stromrechnung Oktober"]), vault_id=house)
        else:
            document = arrive(c, files.make_pdf(["Stromrechnung Oktober"]))
            assert c.put(f"/api/v1/documents/{document['id']}/shares/{tom.id}",
                         json={"right": "edit"}).status_code in (200, 201, 204)
    with new_client(tom) as t:
        runs.clear()
        new_version(t, document["id"], protected(word()))
        wrong = what_is_seen(t, document["id"])
        new_version(t, document["id"], protected(secret))
        right = what_is_seen(t, document["id"])
    assert wrong == right == {"state": "failed", "error": "encrypted", "protected": "", "pages": 0, "opened_lines": 0}
    assert True not in runs, "a run with passwords happened"
    assert matched(jule) == [None]


def test_a_new_version_is_opened_with_the_kept_passwords_of_the_person_who_uploads_it(
        client: TestClient, operator: Account) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    house = shared_vault("Haushalt", operator, (jule, "edit"), (tom, "edit"))
    toms = word()
    keep_for(tom, toms)
    keep_for(jule, word())
    with new_client(jule) as c:
        document = arrive(c, files.make_pdf(["Vertrag Seite eins"]), vault_id=house)
    with new_client(tom) as t:
        new_version(t, document["id"], protected(toms))
        seen = what_is_seen(t, document["id"])
    assert seen["state"] == "ready" and seen["protected"] == "password" and seen["opened_lines"] == 1
    assert matched(tom) != [None] and matched(jule) == [None]


def deliver(account: Account, data: bytes, source: str, vault_id: int) -> int:
    """A file delivered for ``account`` the way the intake folder and the mailbox do it (``receiving.accept``)."""
    path = storage.incoming_path("test-")
    path.write_bytes(data)
    with SessionLocal() as db:
        document, _twin = receiving.accept(
            db, uid=account.id, vault_id=vault_id, filename="Gehalt.pdf", path=path, kind="pdf",
            sha256=hashlib.sha256(data).hexdigest(), size=len(data), source=source)
        document_id = document.id
    process_all()
    return document_id


@pytest.mark.parametrize("source", ["mail", "folder"])
def test_a_delivered_file_is_tried_only_in_the_personal_vault_of_the_person_it_came_for(
        client: TestClient, operator: Account, source: str, runs: list[bool]) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    house = shared_vault("Haushalt", operator, (jule, "edit"), (tom, "edit"))
    secret = word()
    keep_for(jule, secret)
    runs.clear()
    mine = deliver(jule, protected(secret), source, own_vault(jule))
    with new_client(jule) as c:
        opened = c.get(f"/api/v1/documents/{mine}").json()
    assert opened["process_error"] == "" and opened["original_protected"] == "password"
    assert True in runs
    runs.clear()
    shared = deliver(jule, protected(secret), source, house)
    with new_client(tom) as t:
        waiting = t.get(f"/api/v1/documents/{shared}").json()
        lines = [e["action"] for e in t.get(f"/api/v1/documents/{shared}/events").json()]
    assert waiting["process_error"] == "encrypted" and waiting["original_protected"] == ""
    assert "pdf_opened" not in lines and True not in runs


def test_an_imported_file_tries_nothing(client: TestClient, operator: Account, runs: list[bool]) -> None:
    jule = make_account("jule")
    secret = word()
    keep_for(jule, secret)
    runs.clear()
    imported = deliver(jule, protected(secret), "paperless", own_vault(jule))
    with new_client(jule) as c:
        assert c.get(f"/api/v1/documents/{imported}").json()["process_error"] == "encrypted"
    assert True not in runs


def test_whose_follows_the_file_not_the_owner(client: TestClient, operator: Account) -> None:
    """The one place that decides it, case by case; the owner of the document never comes into it."""
    jule, tom = make_account("jule"), make_account("tom")
    house = shared_vault("Haushalt", operator, (jule, "edit"), (tom, "edit"))
    with new_client(jule) as c:
        uploaded = arrive(c, files.make_pdf(["eins"]), vault_id=house)
    delivered = deliver(jule, files.make_pdf(["zwei"]), "mail", house)
    with SessionLocal() as db:
        from app.models import Document

        document = db.get(Document, uploaded["id"])
        version = db.scalar(select(Version).where(Version.document_id == document.id))
        assert pdf_passwords.whose(db, document, version) == jule.id
        # The owner changes (an account handed over): the file is still Jule's, whoever owns the document now.
        document.owner_id = tom.id
        assert pdf_passwords.whose(db, document, version) == jule.id
        version.created_by = None
        assert pdf_passwords.whose(db, document, version) is None
        other = db.get(Document, delivered)
        assert pdf_passwords.whose(db, other, db.scalar(select(Version).where(Version.document_id == delivered))) is None
        db.rollback()


# --- 2. Kept under the person who types it -----------------------------------------------------------------------------


def test_a_password_typed_through_a_share_is_kept_by_the_person_who_typed_it(
        client: TestClient, operator: Account) -> None:
    jule, lea = make_account("jule"), make_account("lea")
    password = word()
    with new_client(jule) as c:
        document = arrive(c, protected(password))
        assert c.put(f"/api/v1/documents/{document['id']}/shares/{lea.id}",
                     json={"right": "edit"}).status_code in (200, 201, 204)
    with new_client(lea) as le:
        answer = unlock(le, document["id"], password, remember=True, name="Von Jule")
        assert answer.status_code == 200 and answer.json()["kept"] == "kept"
        assert [e["name"] for e in le.get("/api/v1/pdf-passwords").json()] == ["Von Jule"]
    with new_client(jule) as c:
        assert c.get("/api/v1/pdf-passwords").json() == []
    with SessionLocal() as db:
        assert [row.user_id for row in db.scalars(select(PdfPassword))] == [lea.id]


# --- 3. The brake ------------------------------------------------------------------------------------------------------


def test_somebody_elses_tries_never_lock_the_owner_out(client: TestClient, operator: Account) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    house = shared_vault("Haushalt", operator, (jule, "edit"), (tom, "edit"))
    password = word()
    with new_client(jule) as c:
        document = arrive(c, protected(password), vault_id=house)
    with new_client(tom) as t:
        for _ in range(pdf_passwords.TRIES_PER_DOCUMENT):
            assert unlock(t, document["id"], "falsch").status_code == 422
        assert unlock(t, document["id"], password).status_code == 429
    with new_client(jule) as c:
        assert unlock(c, document["id"], password).status_code == 200


def test_a_try_the_brake_refuses_takes_nothing_from_the_other_brake(
        client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    """All or nothing: a try stopped by the brake of the document does not count against the person."""
    monkeypatch.setattr(pdf_passwords, "TRIES_PER_PERSON", pdf_passwords.TRIES_PER_DOCUMENT + 1)
    jule = make_account("jule")
    password = word()
    with new_client(jule) as c:
        first = arrive(c, protected(password))
        second = arrive(c, protected(password), name="Zwei.pdf")
        for _ in range(pdf_passwords.TRIES_PER_DOCUMENT):
            assert unlock(c, first["id"], "falsch").status_code == 422
        for _ in range(3):
            assert unlock(c, first["id"], "falsch").status_code == 429
        assert unlock(c, second["id"], password).status_code == 200


def test_the_brake_takes_all_or_none_directly() -> None:
    brakes.forget()
    brakes.take_hourly(("pdf_password_document", (1, 1), 1))
    with pytest.raises(HTTPException):
        brakes.take_hourly(("pdf_password_person", 1, 5), ("pdf_password_document", (1, 1), 1))
    for _ in range(5):
        brakes.take_hourly(("pdf_password_person", 1, 5))
    brakes.forget()


# --- 4. A file that only claims to be encrypted ------------------------------------------------------------------------

GARBAGE = (b"%PDF-1.7\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R/Encrypt<</Filter/Standard/V 5/R 6>>>>\n"
           b"%%EOF")


def test_a_file_that_only_claims_to_be_encrypted_is_refused_and_nothing_is_written(client: TestClient,
                                                                                  operator: Account) -> None:
    jule = make_account("jule")
    with new_client(jule) as c:
        document = arrive(c, GARBAGE, name="kaputt.pdf")
        assert document["process_error"] == "encrypted"
        for _ in range(2):
            answer = unlock(c, document["id"], word())
            assert answer.status_code == 422 and answer.json()["detail"]["code"] == "pdf_broken"
        after = c.get(f"/api/v1/documents/{document['id']}").json()
    assert (after["status"], after["process_error"], after["change_seq"]) == ("inbox", "encrypted",
                                                                              document["change_seq"])
    with SessionLocal() as db:
        assert db.scalar(select(Event.id).where(Event.document_id == document["id"],
                                                Event.action == "pdf_opened")) is None
        assert jobs.run_pending() == 0


# --- 5. The trial run of a backup --------------------------------------------------------------------------------------


def test_the_trial_run_counts_kept_passwords_a_restore_would_bring_back(client: TestClient,
                                                                        operator: Account) -> None:
    jule = make_account("jule")
    keep_for(jule, word(), "Gehalt")
    keep_for(jule, word(), "Versicherung")
    path = backups.create(kind=backups.MANUAL)
    try:
        assert backups.check(path.name).revived_pdf_passwords == 0
        with SessionLocal() as db:
            db.execute(delete(PdfPassword).where(PdfPassword.name == "Gehalt"))
            db.commit()
        brief = backups.check(path.name)
        assert brief.revived_pdf_passwords == 1
        answer = client.post(f"/api/v1/backups/{path.name}/check").json()
        assert answer["revived_pdf_passwords"] == 1 and "Gehalt" not in str(answer)
    finally:
        path.unlink(missing_ok=True)


# --- 8. The reviewer's mutations that lived ----------------------------------------------------------------------------


def opened_document(c: TestClient, password: str) -> dict[str, Any]:
    document = arrive(c, protected(password))
    assert unlock(c, document["id"], password).status_code == 200
    process_all()
    return c.get(f"/api/v1/documents/{document['id']}").json()  # type: ignore[no-any-return]


def test_reading_the_text_again_takes_the_pdf_opened_never_the_protected_original(jule: Account) -> None:
    """P2: the job ``text`` of a protected document reads its copy without the encryption."""
    with new_client(jule) as c:
        document = opened_document(c, word())
    with SessionLocal() as db:
        db.execute(delete(VersionText).where(VersionText.document_id == document["id"]))
        db.commit()
    with SessionLocal() as db:
        processing.read_text(db, document["id"], 1)
    with SessionLocal() as db:
        row = db.scalar(select(VersionText).where(VersionText.document_id == document["id"]))
        assert row is not None and "lohnsteuerbescheinigung" in row.text.lower()


def test_the_tag_of_the_pdf_opened_changes_with_its_checksum(jule: Account) -> None:
    """P6: the copy is replaced (the recognition, another opening) while the original stays: its tag must change."""
    with new_client(jule) as c:
        document = opened_document(c, word())
        path = f"/api/v1/documents/{document['id']}/versions/1/archive"
        before = c.get(path).headers["ETag"]
        with SessionLocal() as db:
            version = db.scalar(select(Version).where(Version.document_id == document["id"]))
            version.archive_sha256 = "0" * 64
            db.commit()
        after = c.get(path).headers["ETag"]
    assert before != after


def test_a_link_hands_out_the_pdf_opened_also_when_it_was_only_locked(jule: Account) -> None:
    """P7: an original that only locks printing and changing is not what a link hands out either."""
    with new_client(jule) as c:
        document = arrive(c, protected(owner_only=True))
        assert document["original_protected"] == "restricted"
        link = c.post(f"/api/v1/documents/{document['id']}/links",
                      json={"recipient": "x", "days": 1, "allow_download": True}).json()
    with TestClient(c.app, base_url="http://testserver") as guest:
        shown = guest.get(f"/api/v1/l/{link['token']}/file")
    assert shown.status_code == 200 and not encrypted_bytes(shown.content)
    assert shown.content != version_bytes(document["id"])


def version_bytes(document_id: int) -> bytes:
    return (Path(storage.root()) / version_of(document_id).original_path).read_bytes()


def test_opening_in_the_trash_is_refused_before_anything_runs(jule: Account, runs: list[bool]) -> None:
    """P8."""
    password = word()
    with new_client(jule) as c:
        document = arrive(c, protected(password))
        assert c.delete(f"/api/v1/documents/{document['id']}").status_code in (200, 204)
        runs.clear()
        answer = unlock(c, document["id"], password)
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "not_protected"
    assert runs == []


def test_kept_passwords_are_unsealed_only_when_the_first_run_says_encrypted(
        jule: Account, monkeypatch: pytest.MonkeyPatch, runs: list[bool]) -> None:
    """P11: a PDF without a password never brings the kept ones out of the seal."""
    keep_for(jule, word())
    asked: list[object] = []
    real = pdf_passwords.for_person
    monkeypatch.setattr(pdf_passwords, "for_person", lambda db, person: asked.append(person) or real(db, person))
    with new_client(jule) as c:
        arrive(c, files.make_pdf(["Ganz normal"]))
        arrive(c, protected(owner_only=True), name="Gesperrt.pdf")
        assert asked == [] and True not in runs
        arrive(c, protected(word()), name="Fremd.pdf")
    assert asked == [jule.id]


def test_the_clock_of_the_brake_is_the_apps(monkeypatch: pytest.MonkeyPatch) -> None:
    """The hourly brake reads ``clock.monotonic`` (the tests above move it)."""
    moment = [10.0]
    monkeypatch.setattr(clock, "monotonic", lambda: moment[0])
    brakes.forget()
    brakes.take_hourly(("pdf_password_person", 7, 1))
    moment[0] += 3601
    brakes.take_hourly(("pdf_password_person", 7, 1))
    brakes.forget()

