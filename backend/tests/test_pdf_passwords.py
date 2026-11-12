"""Protected PDFs (P1): a PDF that needs a password waits in the inbox; a person who may change it opens it with the
password, the original stays as it came (its checksum, the check of the files), the PDF opened is what the view, the
search, links, exports and the page tools take. Passwords are kept only when asked, sealed, per person, at most 10;
they are tried on the protected PDFs that come into their owner's inbox and on nobody else's. Wrong tries count against a
brake. Every password here is made at run time."""

from __future__ import annotations

import io
import secrets
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from typing import Any

import pikepdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import clock
from app.db import SessionLocal
from app.models import Account, Event, Job, PdfPassword, Version
from app.services import backups, filecheck, pdf_passwords, processing

from . import files
from .conftest import DATA_DIR, PASSWORD, make_account, new_client
from .intake import process_all, sha, upload_key, upload_one, version_of
from .papers import own_vault, shared_vault

PATH = "/api/v1/pdf-passwords"
WORD = "lohnsteuerbescheinigung"


def word() -> str:
    """A password nobody wrote down: made now, with an umlaut, a space and signs in it."""
    return f"Pä ß!{secrets.token_urlsafe(10)}#€"


def protected(password: str = "", *, revision: int = 6, owner_only: bool = False, text: str = WORD) -> bytes:
    """A PDF of two pages, encrypted: with a password to open it (AES-256 is revision 6, AES-128 revision 4, RC4
    revision 3), or ``owner_only`` (it opens without one; printing and changing are locked)."""
    source = pikepdf.open(io.BytesIO(files.make_pdf([f"Gehaltsabrechnung Oktober {text}",
                                                       "Seite zwei mit genug Text Stadtwerke Lindenau"])))
    owner = secrets.token_urlsafe(16)
    if owner_only:
        encryption = pikepdf.Encryption(user="", owner=owner, allow=pikepdf.Permissions(
            print_lowres=False, print_highres=False, modify_other=False, modify_assembly=False))
    else:
        encryption = pikepdf.Encryption(user=password, owner=owner, R=revision, aes=revision >= 4,
                                        metadata=revision >= 4)
    out = io.BytesIO()
    source.save(out, encryption=encryption)
    return out.getvalue()


def encrypted(path: Path) -> bool:
    try:
        with pikepdf.open(path) as pdf:
            return bool(pdf.is_encrypted)
    except pikepdf.PasswordError:
        return True


def disk(rel: str) -> Path:
    return Path(DATA_DIR) / "dokumente" / rel


def history(document_id: int) -> list[tuple[str, Any, int | None]]:
    with SessionLocal() as db:
        return [(e.action, e.detail, e.user_id) for e in
                db.scalars(select(Event).where(Event.document_id == document_id).order_by(Event.id))]


def arrive(client: TestClient, data: bytes, name: str = "Gehalt.pdf", vault_id: int | None = None) -> dict[str, Any]:
    made = upload_one(client, name, data, vault_id)
    process_all()
    return client.get(f"/api/v1/documents/{made['id']}").json()  # type: ignore[no-any-return]


def unlock(client: TestClient, document_id: int, password: str, **extra: Any) -> Any:
    return client.post(f"/api/v1/documents/{document_id}/unlock", json={"password": password, **extra})


@pytest.fixture
def jule(client: TestClient, operator: Account) -> Account:
    return make_account("jule")


# --- Opening with a typed password -------------------------------------------------------------------------------------


@pytest.mark.parametrize("revision", [6, 4, 3], ids=["aes256", "aes128", "rc4"])
def test_a_protected_pdf_waits_and_the_right_password_opens_it_while_the_original_stays(
        jule: Account, revision: int) -> None:
    password = word() if revision != 3 else f"äöü{secrets.token_hex(4)}"
    data = protected(password, revision=revision)
    with new_client(jule) as c:
        document = arrive(c, data)
        assert document["status"] == "inbox" and document["process_error"] == "encrypted"
        assert document["original_protected"] == ""
        # A wrong one: a friendly answer, and the document is as it was.
        wrong = unlock(c, document["id"], password + "x")
        assert wrong.status_code == 422 and wrong.json()["detail"]["code"] == "wrong_pdf_password"
        again = c.get(f"/api/v1/documents/{document['id']}").json()
        assert (again["status"], again["process_error"], again["change_seq"]) == (
            "inbox", "encrypted", document["change_seq"])
        assert version_of(document["id"]).archive_path == ""
        right = unlock(c, document["id"], password)
        assert right.status_code == 200, right.text
        assert right.json()["kept"] == "" and right.json()["document"]["status"] == "processing"
        process_all()
        opened = c.get(f"/api/v1/documents/{document['id']}").json()
        assert opened["status"] == "inbox" and opened["process_error"] == "" and opened["pages"] == 2
        assert opened["original_protected"] == "password"
        version = version_of(document["id"])
        # The original as it came, with its checksum; the searchable copy without the encryption.
        assert disk(version.original_path).read_bytes() == data and version.sha256 == sha(data)
        assert encrypted(disk(version.original_path)) and not encrypted(disk(version.archive_path))
        assert version.archive_sha256 == sha(disk(version.archive_path).read_bytes())
        assert filecheck.recheck(document["id"]) in (None, "")
        assert c.get(f"/api/v1/documents/{document['id']}").json()["files_state"] == ""
        # What is served: the original as it came, the copy opened; the pages draw; the search finds the text.
        assert c.get(f"/api/v1/documents/{document['id']}/versions/1/file").content == data
        assert c.get(f"/api/v1/documents/{document['id']}/versions/1/archive").content[:5] == b"%PDF-"
        assert c.get(f"/api/v1/documents/{document['id']}/versions/1/pages/1").status_code == 200
        listed = c.get(f"/api/v1/documents/{document['id']}/versions").json()
        assert listed[0]["original_protected"] == "password" and listed[0]["has_archive"] is True
        found = c.get(f"/api/v1/search?q={WORD}").json()["items"]
        assert [item["document"]["id"] for item in found] == [document["id"]]
    actions = [(action, detail, user) for action, detail, user in history(document["id"])]
    assert ("pdf_opened", {"by": "typed"}, jule.id) in actions
    assert actions[-1][0] == "processed"


def test_a_pdf_that_only_locks_printing_and_changing_goes_through_without_a_question_and_the_page_tools_work(
        jule: Account) -> None:
    data = protected(owner_only=True)
    with new_client(jule) as c:
        document = arrive(c, data)
        assert document["status"] == "inbox" and document["process_error"] == "" and document["pages"] == 2
        assert document["original_protected"] == "restricted"
        version = version_of(document["id"])
        assert disk(version.original_path).read_bytes() == data and not encrypted(disk(version.archive_path))
        # The text was read (the original would not have been rewritten by the recognition).
        assert [i["document"]["id"] for i in c.get(f"/api/v1/search?q={WORD}").json()["items"]] == [document["id"]]
        turned = c.post(f"/api/v1/documents/{document['id']}/pages", json={
            "base_version": 1, "pages": [{"page": 2, "turn": 90}, {"page": 1, "turn": 0}]})
        assert turned.status_code == 200, turned.text
        assert c.get(f"/api/v1/documents/{document['id']}").json()["original_protected"] == ""
        assert unlock(c, document["id"], "anything").json()["detail"]["code"] == "not_protected"


def test_the_page_tools_work_on_the_pdf_opened_and_a_version_brought_back_stays_protected(jule: Account) -> None:
    password = word()
    with new_client(jule) as c:
        document = arrive(c, protected(password))
        assert unlock(c, document["id"], password).status_code == 200
        process_all()
        turned = c.post(f"/api/v1/documents/{document['id']}/pages", json={
            "base_version": 1, "pages": [{"page": 1, "turn": 180}]})
        assert turned.status_code == 200, turned.text
        process_all()
        now = c.get(f"/api/v1/documents/{document['id']}").json()
        assert now["current_version"] == 2 and now["pages"] == 1 and now["original_protected"] == ""
        assert not encrypted(disk(version_of(document["id"], 2).original_path))
        back = c.post(f"/api/v1/documents/{document['id']}/versions/1/restore", json={"base_version": 2})
        assert back.status_code == 200, back.text
        restored = c.get(f"/api/v1/documents/{document['id']}").json()
        assert restored["current_version"] == 3 and restored["original_protected"] == "password"
        assert c.get(f"/api/v1/documents/{document['id']}/versions/3/pages/2").status_code == 200


def test_an_empty_a_very_long_and_an_overlong_password(jule: Account) -> None:
    longest = "L" + secrets.token_hex(63)  # 127 characters, what the newest encryption reads at most
    with new_client(jule) as c:
        document = arrive(c, protected(longest))
        empty = unlock(c, document["id"], "")
        assert empty.status_code == 422 and empty.json()["detail"]["code"] == "invalid_pdf_password"
        too_long = unlock(c, document["id"], "x" * (pdf_passwords.PASSWORD_MAX + 1))
        assert too_long.status_code == 422 and too_long.json()["detail"] == {
            "code": "invalid_input", "message": "The input is not valid.", "fields": ["password"]}
        long_wrong = unlock(c, document["id"], "y" * pdf_passwords.PASSWORD_MAX)
        assert long_wrong.json()["detail"]["code"] == "wrong_pdf_password"
        assert unlock(c, document["id"], longest).status_code == 200
        process_all()
        assert c.get(f"/api/v1/documents/{document['id']}").json()["process_error"] == ""


def test_a_document_that_does_not_wait_for_a_password_is_refused_before_anything_runs(
        jule: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[object] = []
    real = processing.spawn
    monkeypatch.setattr(processing, "spawn", lambda request, timeout: ran.append(request.get("op")) or real(
        request, timeout))
    with new_client(jule) as c:
        plain = arrive(c, files.make_pdf(["Nichts geschuetzt"]))
        ran.clear()
        answer = unlock(c, plain["id"], "whatever")
        assert answer.status_code == 409 and answer.json()["detail"]["code"] == "not_protected"
        assert ran == []


# --- The brake ---------------------------------------------------------------------------------------------------------


def test_five_tries_per_document_and_hour_then_the_brake_even_for_the_right_password(
        jule: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    password = word()
    moment = [1000.0]
    monkeypatch.setattr(clock, "monotonic", lambda: moment[0])
    with new_client(jule) as c:
        document = arrive(c, protected(password))
        for _ in range(pdf_passwords.TRIES_PER_DOCUMENT):
            assert unlock(c, document["id"], password + "?").status_code == 422
        stopped = unlock(c, document["id"], password)
        assert stopped.status_code == 429 and stopped.json()["detail"]["code"] == "pdf_password_too_often"
        assert int(stopped.headers["Retry-After"]) > 3000
        assert c.get(f"/api/v1/documents/{document['id']}").json()["process_error"] == "encrypted"
        moment[0] += 3601
        assert unlock(c, document["id"], password).status_code == 200


def test_the_brake_per_person_holds_across_documents_and_others_are_not_stopped(
        client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_passwords, "TRIES_PER_PERSON", 3)
    jule, tom = make_account("jule"), make_account("tom")
    house = shared_vault("Haushalt", operator, (jule, "edit"), (tom, "edit"))
    password = word()
    with new_client(jule) as c:
        first = arrive(c, protected(password), vault_id=house)
        second = arrive(c, protected(password), name="Zwei.pdf", vault_id=house)
        assert unlock(c, first["id"], "a").status_code == 422
        assert unlock(c, first["id"], "b").status_code == 422
        assert unlock(c, second["id"], "c").status_code == 422
        assert unlock(c, second["id"], password).status_code == 429
    with new_client(tom) as t:
        assert unlock(t, second["id"], password).status_code == 200


def test_a_stranger_and_a_reader_do_not_use_the_brake_of_the_document(
        client: TestClient, operator: Account) -> None:
    jule, lea, out = make_account("jule"), make_account("lea"), make_account("outsider")
    house = shared_vault("Haushalt", operator, (jule, "edit"), (lea, "read"))
    password = word()
    with new_client(jule) as c:
        document = arrive(c, protected(password), vault_id=house)
    for who, status in ((lea, 403), (out, 404)):
        with new_client(who) as other:
            for _ in range(pdf_passwords.TRIES_PER_DOCUMENT + 1):
                assert unlock(other, document["id"], password).status_code == status
    with new_client(jule) as c:
        assert unlock(c, document["id"], password).status_code == 200


# --- Rights ------------------------------------------------------------------------------------------------------------


def test_who_may_open_through_a_share_a_device_a_key_and_a_link(client: TestClient, operator: Account) -> None:
    jule, tom, lea = make_account("jule"), make_account("tom"), make_account("lea")
    password = word()
    with new_client(jule) as c:
        documents = [arrive(c, protected(password), name=f"D{n}.pdf") for n in range(3)]
        assert c.put(f"/api/v1/documents/{documents[0]['id']}/shares/{tom.id}", json={"right": "read"}).status_code \
            in (200, 201, 204)
        assert c.put(f"/api/v1/documents/{documents[1]['id']}/shares/{lea.id}", json={"right": "edit"}).status_code \
            in (200, 201, 204)
        link = c.post(f"/api/v1/documents/{documents[2]['id']}/links", json={"recipient": "x", "days": 1}).json()
        device = c.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with new_client(tom) as t:
        assert unlock(t, documents[0]["id"], password).status_code == 403
    with new_client(lea) as le:
        assert unlock(le, documents[1]["id"], password).status_code == 200
    reader, uploader = upload_key(jule, "read"), upload_key(jule, "upload")
    with TestClient(client.app, base_url="http://testserver") as program:
        for secret in (reader, uploader):
            answer = program.post(f"/api/v1/documents/{documents[2]['id']}/unlock", json={"password": password},
                                  headers={"Authorization": f"Bearer {secret}"})
            assert answer.status_code in (401, 403), answer.status_code
        # A link reaches its document's pages and file, never this route; without a session there is none.
        assert program.post(f"/api/v1/documents/{documents[2]['id']}/unlock",
                            json={"password": password}).status_code in (400, 401, 403)
        assert program.get(f"/api/v1/l/{link['token']}").status_code == 200
        by_device = program.post(f"/api/v1/documents/{documents[2]['id']}/unlock", json={"password": password},
                                 headers={"Authorization": f"Bearer {device}"})
        assert by_device.status_code == 200, by_device.text
    process_all()
    with TestClient(client.app, base_url="http://testserver") as program:
        shown = program.get(f"/api/v1/l/{link['token']}/file")
        # The link hands out the PDF opened, never the protected original.
        assert shown.status_code in (200, 403)
        if shown.status_code == 200:
            assert not encrypted_bytes(shown.content)


def encrypted_bytes(data: bytes) -> bool:
    try:
        with pikepdf.open(io.BytesIO(data)) as pdf:
            return bool(pdf.is_encrypted)
    except pikepdf.PasswordError:
        return True


def test_a_link_that_allows_downloading_hands_out_the_pdf_opened(jule: Account) -> None:
    password = word()
    with new_client(jule) as c:
        document = arrive(c, protected(password))
        assert unlock(c, document["id"], password).status_code == 200
        process_all()
        link = c.post(f"/api/v1/documents/{document['id']}/links",
                      json={"recipient": "x", "days": 1, "allow_download": True}).json()
    with TestClient(c.app, base_url="http://testserver") as guest:
        shown = guest.get(f"/api/v1/l/{link['token']}/file")
        assert shown.status_code == 200 and shown.content[:5] == b"%PDF-" and not encrypted_bytes(shown.content)


# --- Kept passwords ----------------------------------------------------------------------------------------------------


def test_a_password_is_kept_only_when_asked_and_opens_the_next_pdf_by_itself(jule: Account) -> None:
    password = word()
    with new_client(jule) as c:
        first = arrive(c, protected(password))
        assert unlock(c, first["id"], password).json()["kept"] == ""
        assert c.get(PATH).json() == []
        second = arrive(c, protected(password), name="November.pdf")
        assert second["process_error"] == "encrypted", "nothing was kept, so nothing was tried"
        no_name = unlock(c, second["id"], password, remember=True)
        assert no_name.status_code == 422 and no_name.json()["detail"]["code"] == "invalid_pdf_password_name"
        kept = unlock(c, second["id"], password, remember=True, name="  Gehaltsabrechnung  ")
        assert kept.status_code == 200 and kept.json()["kept"] == "kept"
        process_all()
        entries = c.get(PATH).json()
        assert [(e["name"], e["readable"], e["last_matched_at"]) for e in entries] == [
            ("Gehaltsabrechnung", True, None)]
        assert set(entries[0]) == {"id", "name", "created_at", "last_matched_at", "readable"}
        third = arrive(c, protected(password), name="Dezember.pdf")
        assert third["status"] == "inbox" and third["process_error"] == "" and third["pages"] == 2
        assert third["original_protected"] == "password"
        assert c.get(PATH).json()[0]["last_matched_at"] is not None
        # The history says a kept password opened it, never which one, and no person did it.
        assert ("pdf_opened", {"by": "kept"}, None) in history(third["id"])
        shown = c.get(f"/api/v1/documents/{third['id']}/events").text
        assert "Gehaltsabrechnung" not in shown


def test_the_kept_passwords_are_tried_in_turn_and_the_one_that_fits_is_noted(jule: Account) -> None:
    first, second = word(), word()
    with new_client(jule) as c:
        for password, name in ((first, "Gehalt"), (second, "Versicherung")):
            document = arrive(c, protected(password), name=f"{name}.pdf")
            assert unlock(c, document["id"], password, remember=True, name=name).json()["kept"] == "kept"
            process_all()
        came = arrive(c, protected(second), name="Police.pdf")
        assert came["process_error"] == "" and came["original_protected"] == "password"
        matched = {e["name"]: e["last_matched_at"] for e in c.get(PATH).json()}
        assert matched["Versicherung"] is not None and matched["Gehalt"] is None
        # The same password again is known, not kept twice.
        other = arrive(c, protected(first), name="Gehalt2.pdf")
        assert other["process_error"] == ""


def test_the_same_password_is_known_and_at_most_ten_are_kept(jule: Account) -> None:
    with SessionLocal() as db:
        for n in range(pdf_passwords.MAX - 1):
            assert pdf_passwords._keep(db, jule.id, f"Eintrag {n}", word()) == "kept"
        db.commit()
    password = word()
    with new_client(jule) as c:
        document = arrive(c, protected(password))
        assert unlock(c, document["id"], password, remember=True, name="Zehn").json()["kept"] == "kept"
        process_all()
        assert len(c.get(PATH).json()) == pdf_passwords.MAX
        again = arrive(c, protected(word()), name="Elf.pdf")
        full = unlock(c, again["id"], "egal", remember=True, name="Elf")
        assert full.status_code == 409 and full.json()["detail"]["code"] == "too_many_pdf_passwords"
    with SessionLocal() as db:
        assert pdf_passwords._keep(db, jule.id, "Doppelt", password) == "known"
        db.rollback()


def test_a_kept_password_of_another_person_is_never_tried(client: TestClient, operator: Account) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    house = shared_vault("Haushalt", operator, (jule, "edit"), (tom, "edit"))
    password = word()
    with new_client(tom) as t:
        document = arrive(t, protected(password), vault_id=house)
        assert unlock(t, document["id"], password, remember=True, name="Toms").json()["kept"] == "kept"
        process_all()
    with new_client(jule) as c:
        # Jule's document in the vault they share: tom's kept password is not hers, so it waits.
        mine = arrive(c, protected(password), vault_id=house)
        assert mine["process_error"] == "encrypted"
        assert c.get(PATH).json() == []
    with SessionLocal() as db:
        assert db.scalar(select(PdfPassword.last_matched_at).where(PdfPassword.user_id == tom.id)) is None


def test_the_list_is_only_the_own_one_for_everybody_the_operator_too(
        client: TestClient, operator: Account) -> None:
    jule = make_account("jule")
    with SessionLocal() as db:
        pdf_passwords._keep(db, jule.id, "Gehalt", word())
        db.commit()
        entry = db.scalar(select(PdfPassword.id))
    assert client.get(PATH).json() == []
    assert client.patch(f"{PATH}/{entry}", json={"name": "Mine"}).status_code == 404
    assert client.delete(f"{PATH}/{entry}").status_code == 404
    with new_client(jule) as c:
        assert [e["name"] for e in c.get(PATH).json()] == ["Gehalt"]
        renamed = c.patch(f"{PATH}/{entry}", json={"name": "Lohn"})
        assert renamed.status_code == 200 and renamed.json()["name"] == "Lohn"
        assert c.patch(f"{PATH}/{entry}", json={"name": "\x07"}).status_code == 422
        device = c.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    key = upload_key(jule, "read")
    with TestClient(client.app, base_url="http://testserver") as program:
        assert program.get(PATH, headers={"Authorization": f"Bearer {device}"}).status_code == 200
        for secret in (key, upload_key(jule, "upload")):
            assert program.get(PATH, headers={"Authorization": f"Bearer {secret}"}).status_code in (401, 403)
            assert program.delete(f"{PATH}/{entry}",
                                  headers={"Authorization": f"Bearer {secret}"}).status_code in (401, 403)
        assert program.get(PATH).status_code == 401
    with new_client(jule) as c:
        assert c.delete(f"{PATH}/{entry}").status_code == 204
        assert c.get(PATH).json() == []


def test_a_new_secret_key_makes_the_kept_passwords_unreadable_and_nothing_breaks(
        jule: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    password = word()
    with SessionLocal() as db:
        pdf_passwords._keep(db, jule.id, "Gehalt", password)
        db.commit()
    from app import security

    monkeypatch.setattr(security, "server_key", lambda: secrets.token_bytes(32))
    with new_client(jule) as c:
        assert [(e["name"], e["readable"]) for e in c.get(PATH).json()] == [("Gehalt", False)]
        document = arrive(c, protected(password))
        assert document["process_error"] == "encrypted"


def test_the_kept_passwords_go_with_the_account(client: TestClient, operator: Account) -> None:
    tom = make_account("tom")
    with SessionLocal() as db:
        pdf_passwords._keep(db, tom.id, "Gehalt", word())
        db.commit()
    answer = client.request("DELETE", f"/api/v1/accounts/{tom.id}",
                            json={"current_password": PASSWORD, "confirm_name": "tom", "documents": "delete_documents"})
    assert answer.status_code == 204, answer.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(PdfPassword)) == 0


def test_a_new_version_is_opened_with_a_kept_password_and_one_without_a_password_is_plain(jule: Account) -> None:
    password = word()
    with new_client(jule) as c:
        document = arrive(c, files.make_pdf(["Version eins ohne Passwort"]))
        first = arrive(c, protected(password), name="Erst.pdf")
        assert unlock(c, first["id"], password, remember=True, name="Gehalt").status_code == 200
        process_all()
        upload = c.post(f"/api/v1/documents/{document['id']}/versions",
                        files={"file": ("neu.pdf", protected(password), "application/pdf")})
        assert upload.status_code in (200, 201, 202), upload.text
        process_all()
        now = c.get(f"/api/v1/documents/{document['id']}").json()
        assert now["current_version"] == 2 and now["original_protected"] == "password" and now["pages"] == 2
        versions = {v["n"]: v["original_protected"] for v in c.get(f"/api/v1/documents/{document['id']}/versions").json()}
        assert versions == {1: "", 2: "password"}


def test_the_trash_and_deleting_for_good_take_the_pdf_opened_along(jule: Account) -> None:
    password = word()
    with new_client(jule) as c:
        document = arrive(c, protected(password))
        assert unlock(c, document["id"], password).status_code == 200
        process_all()
        version = version_of(document["id"])
        opened, original = disk(version.archive_path), disk(version.original_path)
        assert opened.is_file() and original.is_file()
        assert c.delete(f"/api/v1/documents/{document['id']}").status_code in (200, 204)
        assert c.post(f"/api/v1/documents/{document['id']}/purge").status_code == 204
        process_all()
    assert not opened.exists() and not original.exists()


def test_an_export_takes_the_pdf_opened_as_searchable_and_the_protected_original_as_original(jule: Account) -> None:
    from app.services import exports

    password = word()
    with new_client(jule) as c:
        document = arrive(c, protected(password))
        assert unlock(c, document["id"], password).status_code == 200
        process_all()
    with SessionLocal() as db:
        version = db.scalar(select(Version).where(Version.document_id == document["id"]))
        content = exports.Content(pdf=True, original=True, csv=True, xml=False)
        chosen = {which: rel for which, rel, _ext in exports.files_of(version, content)}
    assert chosen["original"] == version.original_path and chosen["pdf"] == version.archive_path


# --- Nothing tells a password ------------------------------------------------------------------------------------------


def test_the_worker_gets_the_password_on_its_standard_input_only_and_answers_without_it(
        jule: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    password = word()
    seen: list[tuple[list[str], dict[str, str]]] = []
    answers: list[dict[str, Any]] = []
    real_popen = processing.subprocess.Popen
    real_spawn = processing._spawn

    def popen(args: list[str], **kwargs: Any) -> Any:
        seen.append((list(args), dict(kwargs.get("env") or {})))
        return real_popen(args, **kwargs)

    def spawn(request: dict[str, Any], timeout: int, cwd: str) -> Any:
        outcome = real_spawn(request, timeout, cwd)
        answers.append(dict(outcome.data))
        return outcome

    monkeypatch.setattr(processing.subprocess, "Popen", popen)
    monkeypatch.setattr(processing, "_spawn", spawn)
    with new_client(jule) as c:
        document = arrive(c, protected(password))
        assert unlock(c, document["id"], password, remember=True, name="Gehalt").status_code == 200
        process_all()
        arrive(c, protected(password), name="Zwei.pdf")
    assert seen
    for args, environment in seen:
        assert not any(password in part for part in args)
        assert not any(password in value for value in environment.values())
    assert {"unlocked": 1, "ok": True} in [{k: v for k, v in a.items() if k in ("ok", "unlocked")} for a in answers]
    assert all(password not in repr(answer) for answer in answers)


def test_after_a_whole_round_the_password_is_nowhere_but_sealed(
        jule: Account, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    """Wrong, right and kept, with the log at its finest level: the password stands in no log line, no row of the
    database (only sealed), no answer, no name of a file and no file of the data folder, a backup included."""
    import logging

    from app.services import logs

    password = f"Unik{secrets.token_hex(12)}Wert"
    caplog.set_level(logging.DEBUG)
    logs.setup()
    logs.apply_mode("trace")
    said: list[str] = []
    try:
        with new_client(jule) as c:
            def keep(answer: Any) -> Any:
                said.append(answer.text + repr(dict(answer.headers)))
                return answer

            document = arrive(c, protected(password))
            keep(unlock(c, document["id"], password[::-1]))
            keep(unlock(c, document["id"], password, remember=True, name="Gehalt"))
            process_all()
            second = arrive(c, protected(password), name="Zwei.pdf")
            assert second["process_error"] == ""
            for path in (f"/api/v1/documents/{document['id']}", f"/api/v1/documents/{document['id']}/events",
                         PATH, "/api/v1/changes?since=0", f"/api/v1/documents/{second['id']}/events",
                         f"/api/v1/documents/{document['id']}/versions"):
                keep(c.get(path))
        backup = backups.create(kind=backups.MANUAL)
    finally:
        logs.apply_mode("normal")
    for text in said:
        assert password not in text
    for record in caplog.records:
        assert password not in record.getMessage() and password not in repr(record.args)
    spellings = {password.encode(codec) for codec in ("utf-8", "utf-16-le", "latin-1")}

    def clean(data: bytes, where: str) -> None:
        assert not any(spelling in data for spelling in spellings), where

    for path in Path(DATA_DIR).rglob("*"):
        assert password not in path.name
        if not path.is_file():
            continue
        data = path.read_bytes()
        clean(data, str(path))
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    clean(archive.read(name), f"{path}:{name}")
    assert backup.is_file()
    # Every row of every table: the sealed value only.
    copy = tmp_path / "rows.db"
    with zipfile.ZipFile(backup) as archive:
        copy.write_bytes(archive.read(backups.DATABASE_ENTRY))
    with closing(sqlite3.connect(copy)) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        for table in tables:
            for row in connection.execute(f'SELECT * FROM "{table}"'):  # noqa: S608 - the names come from SQLite
                assert password not in repr(row), table
        sealed = connection.execute("SELECT sealed FROM pdf_passwords").fetchall()
        assert len(sealed) == 1 and sealed[0][0]
    with SessionLocal() as db:
        for job in db.scalars(select(Job)):
            assert password not in repr(job.payload) and password not in (job.error or "")
    backup.unlink(missing_ok=True)


def test_the_backup_holds_the_sealed_passwords_and_its_trial_passes(jule: Account, tmp_path: Path) -> None:
    password = word()
    with SessionLocal() as db:
        pdf_passwords._keep(db, jule.id, "Gehalt", password)
        db.commit()
    path = backups.create(kind=backups.MANUAL)
    try:
        with zipfile.ZipFile(path) as archive:
            copy = tmp_path / "copy.db"
            copy.write_bytes(archive.read(backups.DATABASE_ENTRY))
        with closing(sqlite3.connect(copy)) as connection:
            rows = connection.execute("SELECT user_id, name, sealed FROM pdf_passwords").fetchall()
            assert [(u, n) for u, n, _s in rows] == [(jule.id, "Gehalt")] and password not in rows[0][2]
            assert connection.execute("SELECT count(*) FROM pragma_table_info('versions') "
                                      "WHERE name = 'original_protected'").fetchone()[0] == 1
        brief = backups.check(path.name)
        assert brief.usable
    finally:
        path.unlink(missing_ok=True)


def test_the_own_vault_is_where_an_upload_lands_for_these_tests(jule: Account) -> None:
    """The documents above are the uploader's: the owner whose kept passwords are tried."""
    with new_client(jule) as c:
        document = arrive(c, files.make_pdf(["eigen"]))
    assert document["vault_id"] == own_vault(jule) and document["owner"]["id"] == jule.id
