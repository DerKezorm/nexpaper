"""The page tools: turning, deleting and ordering pages, joining, splitting, restoring a version and uploading a new one.
Every test runs the real worker (pikepdf and PDFium in a process of its own) on PDFs made here. The pages carry their
own text, so no text recognition is needed (Tesseract is not on every machine)."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import pypdfium2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import worker
from app.db import SessionLocal
from app.models import Document, Event, Note, Version, VersionInfo, VersionText
from app.services import pages, storage

from . import files
from .conftest import DATA_DIR, make_account, new_client
from .intake import device_token, limit, post_files, process_all, sha, upload_and_read, upload_key, upload_one
from .papers import own_vault, shared_vault
from .searching import titles

LINES = "mit genug Text, damit die Seite als Text gilt und nichts erkannt werden muss"


def pdf(*names: str) -> bytes:
    return files.make_pdf([f"{name} {LINES}" for name in names])


def made(client: TestClient, name: str = "Stapel.pdf", *pages_: str, vault_id: int | None = None) -> dict[str, Any]:
    return upload_and_read(client, name, pdf(*(pages_ or ("Eins", "Zwei", "Drei"))), vault_id)


def versions(document_id: int) -> list[Version]:
    with SessionLocal() as db:
        found = list(db.scalars(select(Version).where(Version.document_id == document_id).order_by(Version.n)))
        for row in found:
            db.expunge(row)
        return found


def file_of(rel: str) -> Path:
    return Path(DATA_DIR) / storage.FOLDER / rel


def text_of(document_id: int, n: int) -> list[str]:
    with SessionLocal() as db:
        version = db.scalar(select(Version).where(Version.document_id == document_id, Version.n == n))
        assert version is not None
        row = db.get(VersionText, version.id)
        assert row is not None
        return row.text.split("\f")


def pdf_texts(path: Path) -> list[str]:
    """The text of every page of a PDF, as PDFium reads it from the file."""
    document = pypdfium2.PdfDocument(str(path))
    try:
        return [document[i].get_textpage().get_text_bounded() for i in range(len(document))]
    finally:
        document.close()


def first_words(texts: list[str]) -> list[str]:
    return [text.split()[0] if text.split() else "" for text in texts]


def actions(document_id: int) -> list[str]:
    with SessionLocal() as db:
        return [e.action for e in db.scalars(select(Event).where(Event.document_id == document_id).order_by(Event.id))]


def turns(path: Path) -> list[int]:
    document = pypdfium2.PdfDocument(str(path))
    try:
        return [document[i].get_rotation() for i in range(len(document))]
    finally:
        document.close()


def leftovers() -> list[Path]:
    """What a run of the tools may never leave behind: temporary files beside the documents, pictures not put away."""
    base = Path(DATA_DIR)
    found = [p for p in (base / storage.FOLDER).rglob(".incoming-*")] if (base / storage.FOLDER).is_dir() else []
    cache = pages.cache_root()
    if cache.is_dir():
        found += [p for p in cache.iterdir() if p.name.startswith(".incoming-")]
    return found


def edit(client: TestClient, document_id: int, spec: list[tuple[int, int]], base: int = 1) -> Any:
    return client.post(f"/api/v1/documents/{document_id}/pages",
                       json={"base_version": base, "pages": [{"page": p, "turn": t} for p, t in spec]})


# --- Turning, deleting, ordering ---------------------------------------------------------------------------------------


def test_turning_deleting_and_ordering_makes_a_new_version_and_leaves_the_original_as_it_came(
        client: TestClient, operator: object) -> None:
    document = made(client)
    original = versions(document["id"])[0]
    before = file_of(original.original_path).read_bytes()
    since = client.get("/api/v1/changes?since=0").json()["next"]

    answer = edit(client, document["id"], [(3, 0), (1, 90)])
    assert answer.status_code == 200, answer.text
    shown = answer.json()
    assert shown["current_version"] == 2 and shown["pages"] == 2

    v1, v2 = versions(document["id"])
    assert file_of(v1.original_path).read_bytes() == before and sha(before) == v1.sha256 == original.sha256
    assert v2.pages == 2 and v2.sha256 == sha(file_of(v2.original_path).read_bytes())
    assert turns(file_of(v2.original_path)) == [0, 90]
    # The text of each page went along; nothing was read again.
    assert first_words(text_of(document["id"], 2)) == ["Drei", "Eins"]
    assert "Zwei" not in " ".join(text_of(document["id"], 2))
    # The pictures of the new version are there at once.
    assert pages.thumb_path(document["id"], 2).is_file()
    assert pages.page_path(document["id"], 2, 2, "small").is_file()
    assert actions(document["id"])[-1] == "pages_edited"
    # The change feed and the search know the new version.
    feed = client.get(f"/api/v1/changes?since={since}").json()
    assert [item["document"]["current_version"] for item in feed["items"] if item.get("document")] == [2]
    assert titles(client, "Zwei") == [] and titles(client, "Drei") == [shown["title"]]
    assert leftovers() == []
    listed = client.get(f"/api/v1/documents/{document['id']}/versions").json()
    assert [(v["n"], v["current"], v["origin"], v["from_n"], v["state"]) for v in listed] == [
        (2, True, "pages", 1, "ready"), (1, False, "", None, "ready")]


def test_the_new_version_takes_the_plain_name_and_the_old_one_moves_aside(client: TestClient, operator: object) -> None:
    document = made(client)
    plain = versions(document["id"])[0].original_path
    edit(client, document["id"], [(2, 0), (1, 0)])
    process_all()
    v1, v2 = versions(document["id"])
    assert v2.original_path == plain
    assert v1.original_path == plain[: -len(".pdf")] + " (version 1).pdf"
    assert file_of(v1.original_path).is_file() and file_of(v2.original_path).is_file()
    # And back: the restored version 1 takes the name again, version 2 moves aside.
    assert client.post(f"/api/v1/documents/{document['id']}/versions/1/restore", json={"base_version": 2}).status_code == 200
    process_all()
    v1, v2, v3 = versions(document["id"])
    assert v3.original_path == plain and v3.sha256 == v1.sha256
    assert {v1.original_path, v2.original_path} == {plain[:-4] + " (version 1).pdf", plain[:-4] + " (version 2).pdf"}
    assert sorted(p.name for p in file_of(plain).parent.iterdir()) == sorted(
        Path(v.original_path).name for v in (v1, v2, v3))


def test_a_searchable_copy_is_made_anew_beside_the_new_version(client: TestClient, operator: object) -> None:
    """A picture's version has its PDF beside it: the new version is made from that PDF (the picture cannot be cut)."""
    document = upload_and_read(client, "foto.png", files.make_image("png"))
    assert edit(client, document["id"], [(1, 180)]).status_code == 200
    v1, v2 = versions(document["id"])
    assert v1.original_path.endswith(".png") and v1.archive_path
    assert v2.original_path.endswith(".pdf") and v2.archive_path == "" and turns(file_of(v2.original_path)) == [180]


def test_nothing_to_change_makes_no_version(client: TestClient, operator: object) -> None:
    document = made(client)
    assert edit(client, document["id"], [(1, 0), (2, 0), (3, 0)]).json()["current_version"] == 1
    assert len(versions(document["id"])) == 1


@pytest.mark.parametrize("spec", [[(1, 0), (1, 0)], [(4, 0)], [(0, 0)]])
def test_pages_that_do_not_exist_or_twice_are_refused(client: TestClient, operator: object,
                                                      spec: list[tuple[int, int]]) -> None:
    document = made(client)
    answer = edit(client, document["id"], spec)
    assert answer.status_code == 422 and len(versions(document["id"])) == 1


def test_a_turn_other_than_a_quarter_and_no_pages_are_refused(client: TestClient, operator: object) -> None:
    document = made(client)
    assert edit(client, document["id"], [(1, 45)]).status_code == 422
    assert client.post(f"/api/v1/documents/{document['id']}/pages", json={"base_version": 1, "pages": []}
                       ).status_code == 422


def test_an_old_version_as_the_base_is_refused_and_says_the_current_one(client: TestClient, operator: object) -> None:
    document = made(client)
    assert edit(client, document["id"], [(2, 0), (1, 0)]).status_code == 200
    answer = edit(client, document["id"], [(1, 90)], base=1)
    assert answer.status_code == 409
    assert answer.json()["detail"]["code"] == "version_changed" and answer.json()["detail"]["current_version"] == 2
    assert len(versions(document["id"])) == 2


def test_two_people_at_the_same_moment_make_one_version_and_the_other_hears_409(
        client: TestClient, operator: object) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    vault = shared_vault("Haushalt", jule, (tom, "edit"))
    with new_client(jule) as first:
        document = made(first, "Stapel.pdf", vault_id=vault)
    results: list[int] = []
    barrier = threading.Barrier(2)

    def go(account: Any, spec: list[tuple[int, int]]) -> None:
        with new_client(account) as browser:
            barrier.wait()
            results.append(edit(browser, document["id"], spec).status_code)

    threads = [threading.Thread(target=go, args=(jule, [(3, 0)])), threading.Thread(target=go, args=(tom, [(1, 90)]))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert sorted(results) == [200, 409], results
    assert [v.n for v in versions(document["id"])] == [1, 2]
    assert leftovers() == []


def test_a_double_click_makes_one_version(client: TestClient, operator: object) -> None:
    """The same person twice at once: one runs, the other is told the server is busy or that it changed."""
    document = made(client)
    results: list[int] = []
    barrier = threading.Barrier(2)

    def go() -> None:
        with new_client(operator) as browser:  # type: ignore[arg-type]
            barrier.wait()
            results.append(edit(browser, document["id"], [(2, 0)]).status_code)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert min(results) == 200 and max(results) in (409, 503), results
    assert [v.n for v in versions(document["id"])] == [1, 2]
    assert leftovers() == []


def test_a_document_still_being_read_or_in_the_trash_is_refused(client: TestClient, operator: object) -> None:
    waiting = upload_one(client, "neu.pdf", pdf("Neu"))
    assert edit(client, waiting["id"], [(1, 90)]).json()["detail"]["code"] == "not_ready"
    process_all()
    client.delete(f"/api/v1/documents/{waiting['id']}")
    assert edit(client, waiting["id"], [(1, 90)]).json()["detail"]["code"] == "in_trash"


def test_an_e_invoice_as_xml_has_its_readable_sheet_to_work_on_and_keeps_its_data(
        client: TestClient, operator: object) -> None:
    """Sorting in sets a readable PDF for an XRechnung that came as XML: it has a page, so the tools work on that
    page and make a new version; the XML stays the original of version 1 and the data of the invoice stay with it."""
    invoice = upload_and_read(client, "rechnung.xml", files.invoice_xml())
    assert invoice["pages"] == 1 and invoice["einvoice"] == "UBL"
    answer = edit(client, invoice["id"], [(1, 90)])
    assert answer.status_code == 200 and answer.json()["current_version"] == 2
    assert client.get(f"/api/v1/documents/{invoice['id']}/versions/1/einvoice").status_code == 200
    assert client.get(f"/api/v1/documents/{invoice['id']}/einvoice").json()["number"]


# --- Hostile files ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("content, code", [(files.encrypted_pdf("geheim"), "pdf_encrypted"),
                                           (files.broken_pdf(), "pdf_broken")], ids=["encrypted", "broken"])
def test_a_hostile_pdf_is_refused_by_the_worker_and_nothing_changes(
        client: TestClient, operator: object, content: bytes, code: str) -> None:
    """A file the version names with its own checksum, which the worker refuses (it came past the reader somehow)."""
    document = made(client)
    path = file_of(versions(document["id"])[0].original_path)
    path.write_bytes(content)
    with SessionLocal() as db:
        version = db.scalar(select(Version).where(Version.document_id == document["id"]))
        assert version is not None
        version.sha256 = sha(content)
        db.commit()
    answer = edit(client, document["id"], [(1, 90)])
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == code
    assert len(versions(document["id"])) == 1 and leftovers() == []


def test_a_file_that_is_not_the_one_its_version_names_stops_every_tool(client: TestClient, operator: object) -> None:
    """The checksum of the version is checked before the pages are taken: a file swapped on the disk makes nothing."""
    document = made(client)
    other = made(client, "b.pdf", "Andere")
    path = file_of(versions(document["id"])[0].original_path)
    path.write_bytes(pdf("Vertauscht", "Zwei", "Drei"))
    for answer in (edit(client, document["id"], [(1, 90)]),
                   client.post(f"/api/v1/documents/{document['id']}/split", json={
                       "base_version": 1, "parts": [{"pages": [{"page": 1}]}, {"pages": [{"page": 2}]}]}),
                   client.post(f"/api/v1/documents/{other['id']}/merge", json={
                       "base_version": 1, "others": [{"id": document["id"], "base_version": 1}]})):
        assert answer.status_code == 409 and answer.json()["detail"]["code"] == "try_again"
    assert len(versions(document["id"])) == 1 and len(versions(other["id"])) == 1 and leftovers() == []


def test_the_worker_refuses_a_pdf_with_more_pages_than_allowed_and_a_turn_it_does_not_know(tmp_path: Path) -> None:
    source = tmp_path / "a.pdf"
    source.write_bytes(pdf("Eins", "Zwei", "Drei"))
    with pytest.raises(worker.Refused) as caught:
        worker.assemble({"sources": [str(source)], "max_pages": 2,
                         "outputs": [{"out": str(tmp_path / "b.pdf"), "pages": [[0, 0, 0]]}]})
    assert caught.value.code == "too_many_pages"
    with pytest.raises(worker.Refused):
        worker.assemble({"sources": [str(source)], "outputs": [{"out": str(tmp_path / "c.pdf"), "pages": [[0, 0, 45]]}]})
    with pytest.raises(worker.Refused):
        worker.assemble({"sources": [str(source)], "outputs": [{"out": str(tmp_path / "d.pdf"), "pages": [[0, 7, 0]]}]})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf"]


def test_joining_more_pages_than_the_operator_allows_is_refused(client: TestClient, operator: object) -> None:
    first, second = made(client, "a.pdf"), made(client, "b.pdf")
    limit(upload_max_pages=5)
    answer = client.post(f"/api/v1/documents/{first['id']}/merge",
                         json={"base_version": 1, "others": [{"id": second["id"], "base_version": 1}]})
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "too_many_pages"


# --- Joining ---------------------------------------------------------------------------------------------------------


def test_joining_puts_the_pages_after_each_other_and_the_others_in_the_trash(client: TestClient, operator: object) -> None:
    first = made(client, "a.pdf", "Alpha", "Beta")
    second = made(client, "b.pdf", "Gamma")
    third = made(client, "c.pdf", "Delta")
    client.patch(f"/api/v1/documents/{second['id']}", json={"tags": ["strom"]})
    client.post(f"/api/v1/documents/{second['id']}/notes", json={"text": "Zaehlerstand notiert"})
    answer = client.post(f"/api/v1/documents/{first['id']}/merge", json={
        "base_version": 1, "others": [{"id": third["id"], "base_version": 1}, {"id": second["id"], "base_version": 1}]})
    assert answer.status_code == 200, answer.text
    joined = answer.json()
    assert joined["pages"] == 4 and joined["current_version"] == 2 and joined["title"] == first["title"]
    assert first_words(text_of(first["id"], 2)) == ["Alpha", "Beta", "Delta", "Gamma"]
    # The file itself has its pages in that order, not only the text kept beside it.
    assert first_words(pdf_texts(file_of(versions(first["id"])[1].original_path))) == ["Alpha", "Beta", "Delta", "Gamma"]
    assert joined["tags"] == ["strom"] and joined["notes"] == 1
    for other in (second, third):
        shown = client.get(f"/api/v1/documents/{other['id']}").json()
        assert shown["status"] == "trash"
        assert actions(other["id"])[-2:] == ["trashed", "merged_into"]
    assert actions(first["id"])[-1] == "merged"
    # The note stays on the document in the trash too, and it can come back.
    assert len(client.get(f"/api/v1/documents/{second['id']}/notes").json()) == 1
    assert client.post(f"/api/v1/documents/{second['id']}/restore").json()["status"] == "inbox"
    assert sorted(titles(client, "Gamma")) == sorted([first["title"], second["title"]])
    assert leftovers() == []


def test_joining_needs_edit_on_every_document_and_in_the_vault_of_the_first(client: TestClient, operator: object) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    reading = shared_vault("Nur lesen", jule, (tom, "read"))
    with new_client(jule) as owner:
        theirs = made(owner, "fremd.pdf", vault_id=reading)
    with new_client(tom) as browser:
        mine = made(browser, "mein.pdf")
        answer = browser.post(f"/api/v1/documents/{mine['id']}/merge",
                              json={"base_version": 1, "others": [{"id": theirs["id"], "base_version": 1}]})
        assert answer.status_code == 403
        answer = browser.post(f"/api/v1/documents/{theirs['id']}/merge",
                              json={"base_version": 1, "others": [{"id": mine["id"], "base_version": 1}]})
        assert answer.status_code == 403
        assert browser.get(f"/api/v1/documents/{mine['id']}").json()["status"] == "inbox"
    stranger = make_account("lea")
    with new_client(stranger) as browser:
        own = made(browser, "lea.pdf")
        answer = browser.post(f"/api/v1/documents/{own['id']}/merge",
                              json={"base_version": 1, "others": [{"id": theirs["id"], "base_version": 1}]})
        assert answer.status_code == 404
    assert len(versions(theirs["id"])) == 1


def test_joining_a_document_twice_or_with_itself_is_refused(client: TestClient, operator: object) -> None:
    first, second = made(client, "a.pdf"), made(client, "b.pdf")
    twice = {"base_version": 1, "others": [{"id": second["id"], "base_version": 1}] * 2}
    assert client.post(f"/api/v1/documents/{first['id']}/merge", json=twice).status_code == 422
    itself = {"base_version": 1, "others": [{"id": first["id"], "base_version": 1}]}
    assert client.post(f"/api/v1/documents/{first['id']}/merge", json=itself).status_code == 422


# --- Splitting -------------------------------------------------------------------------------------------------------


def test_splitting_makes_new_documents_in_the_inbox_and_drops_the_pages_named_in_no_part(
        client: TestClient, operator: object) -> None:
    document = made(client, "stapel.pdf", "Alpha", "Leer", "Gamma", "Delta")
    client.patch(f"/api/v1/documents/{document['id']}",
                 json={"sender": "Stadtwerke Lindenau", "tags": ["haus"], "status": "filed"})
    answer = client.post(f"/api/v1/documents/{document['id']}/split", json={
        "base_version": 1, "parts": [{"pages": [{"page": 1}]}, {"pages": [{"page": 3}, {"page": 4, "turn": 90}],
                                                                  "title": "Werkstatt"}]})
    assert answer.status_code == 201, answer.text
    parts = answer.json()["items"]
    assert [p["pages"] for p in parts] == [1, 2] and [p["status"] for p in parts] == ["inbox", "inbox"]
    assert parts[0]["title"] == document["title"] + " (1)" and parts[1]["title"] == "Werkstatt"
    assert all(p["sender"]["name"] == "Stadtwerke Lindenau" and p["tags"] == ["haus"] for p in parts)
    assert first_words(text_of(parts[1]["id"], 1)) == ["Gamma", "Delta"]
    assert turns(file_of(versions(parts[1]["id"])[0].original_path)) == [0, 90]
    assert client.get(f"/api/v1/documents/{document['id']}").json()["status"] == "trash"
    assert actions(document["id"])[-2:] == ["trashed", "split"]
    assert titles(client, "Leer") == []
    assert pages.thumb_path(parts[0]["id"], 1).is_file()
    with SessionLocal() as db:
        info = db.get(VersionInfo, versions(parts[0]["id"])[0].id)
        assert info is not None and info.origin == "split" and info.detail["from_document"] == document["id"]
    assert leftovers() == []


def test_a_split_into_one_part_or_with_an_empty_part_is_refused(client: TestClient, operator: object) -> None:
    document = made(client)
    one = {"base_version": 1, "parts": [{"pages": [{"page": 1}]}]}
    assert client.post(f"/api/v1/documents/{document['id']}/split", json=one).status_code == 422
    empty = {"base_version": 1, "parts": [{"pages": [{"page": 1}]}, {"pages": []}]}
    assert client.post(f"/api/v1/documents/{document['id']}/split", json=empty).status_code == 422


def test_splitting_needs_edit_in_the_vault_itself_not_only_a_share(client: TestClient, operator: object) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    with new_client(jule) as owner:
        document = made(owner, "jule.pdf")
        owner.put(f"/api/v1/documents/{document['id']}/shares/{tom.id}", json={"right": "edit"})
    with new_client(tom) as browser:
        body = {"base_version": 1, "parts": [{"pages": [{"page": 1}]}, {"pages": [{"page": 2}]}]}
        assert browser.post(f"/api/v1/documents/{document['id']}/split", json=body).status_code == 403
        # Turning pages of a document shared for editing is fine: it stays where it is.
        assert edit(browser, document["id"], [(1, 90)]).status_code == 200


# --- Versions --------------------------------------------------------------------------------------------------------


def test_restoring_a_version_makes_it_current_again_as_a_new_one_and_deletes_nothing(
        client: TestClient, operator: object) -> None:
    document = made(client)
    edit(client, document["id"], [(1, 0)])
    answer = client.post(f"/api/v1/documents/{document['id']}/versions/1/restore", json={"base_version": 2})
    assert answer.status_code == 200 and answer.json()["current_version"] == 3 and answer.json()["pages"] == 3
    v1, v2, v3 = versions(document["id"])
    assert v3.sha256 == v1.sha256 and file_of(v3.original_path).read_bytes() == file_of(v1.original_path).read_bytes()
    assert file_of(v2.original_path).is_file()
    assert text_of(document["id"], 3) == text_of(document["id"], 1)
    assert pages.thumb_path(document["id"], 3).is_file()
    assert actions(document["id"])[-1] == "version_restored"
    again = client.post(f"/api/v1/documents/{document['id']}/versions/3/restore", json={"base_version": 3})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_current"
    stale = client.post(f"/api/v1/documents/{document['id']}/versions/2/restore", json={"base_version": 2})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "version_changed"
    assert client.post(f"/api/v1/documents/{document['id']}/versions/9/restore",
                       json={"base_version": 3}).status_code == 404


def upload_version(client: TestClient, document_id: int, name: str, content: bytes, **kwargs: Any) -> Any:
    return client.post(f"/api/v1/documents/{document_id}/versions",
                       files=[("file", (name, content, "application/octet-stream"))], **kwargs)


def test_an_uploaded_version_is_read_and_then_becomes_the_current_one(client: TestClient, operator: object) -> None:
    document = made(client)
    answer = upload_version(client, document["id"], "neu.pdf", pdf("Neu", "Neuer"))
    assert answer.status_code == 202, answer.text
    assert answer.json()["n"] == 2 and answer.json()["state"] == "processing" and not answer.json()["current"]
    # While it is read, the document shows the version before and the tools wait.
    assert client.get(f"/api/v1/documents/{document['id']}").json()["current_version"] == 1
    assert edit(client, document["id"], [(1, 90)]).json()["detail"]["code"] == "version_pending"
    assert upload_version(client, document["id"], "noch.pdf", pdf("Noch")).status_code == 409
    process_all()
    shown = client.get(f"/api/v1/documents/{document['id']}").json()
    assert shown["current_version"] == 2 and shown["pages"] == 2
    assert first_words(text_of(document["id"], 2)) == ["Neu", "Neuer"]
    assert titles(client, "Neuer") == [shown["title"]] and titles(client, "Drei") == []
    listed = client.get(f"/api/v1/documents/{document['id']}/versions").json()
    assert [(v["n"], v["state"], v["origin"], v["current"]) for v in listed] == [
        (2, "ready", "uploaded", True), (1, "ready", "", False)]
    assert actions(document["id"])[-2:] == ["version_uploaded", "version_added"]
    v1, v2 = versions(document["id"])
    assert v2.original_path == v1.original_path[:-len(" (version 1).pdf")] + ".pdf"
    assert shown["status"] == "inbox"


def test_the_same_file_again_is_no_new_version(client: TestClient, operator: object) -> None:
    content = pdf("Eins", "Zwei")
    document = upload_and_read(client, "a.pdf", content)
    answer = upload_version(client, document["id"], "a.pdf", content)
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "same_file"
    assert len(versions(document["id"])) == 1 and leftovers() == []


def test_an_uploaded_version_that_cannot_be_read_stays_listed_and_the_document_keeps_its_version(
        client: TestClient, operator: object) -> None:
    document = made(client)
    assert upload_version(client, document["id"], "kaputt.pdf", files.encrypted_pdf("x")).status_code == 202
    process_all()
    shown = client.get(f"/api/v1/documents/{document['id']}").json()
    assert shown["current_version"] == 1 and shown["pages"] == 3
    listed = client.get(f"/api/v1/documents/{document['id']}/versions").json()
    assert (listed[0]["n"], listed[0]["state"], listed[0]["error"]) == (2, "failed", "encrypted")
    assert actions(document["id"])[-1] == "version_failed"
    # The tools work again, and the next version gets the next number.
    assert edit(client, document["id"], [(1, 90)]).json()["current_version"] == 3


def test_a_new_version_in_pieces_names_its_document(client: TestClient, operator: object) -> None:
    document = made(client)
    content = pdf("Stueck")
    start = client.post("/api/v1/uploads", json={"filename": "v.pdf", "size": len(content), "sha256": sha(content),
                                                 "document_id": document["id"]})
    assert start.status_code == 201, start.text
    upload = start.json()["upload"]
    assert upload["target_document_id"] == document["id"]
    assert client.put(f"/api/v1/uploads/{upload['id']}?offset=0", content=content,
                      headers={"Content-Type": "application/octet-stream"}).status_code == 200
    finished = client.post(f"/api/v1/uploads/{upload['id']}/finish")
    assert finished.status_code == 200 and finished.json()["document"]["id"] == document["id"]
    process_all()
    assert client.get(f"/api/v1/documents/{document['id']}").json()["current_version"] == 2
    # The same file as the current version is not even sent.
    again = client.post("/api/v1/uploads", json={"filename": "v.pdf", "size": len(content), "sha256": sha(content),
                                                 "document_id": document["id"]})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "same_file"


def test_a_key_for_uploading_cannot_add_a_version_and_a_reader_cannot_either(client: TestClient, operator: Any) -> None:
    document = made(client)
    key = upload_key(operator)
    content = pdf("Schluessel")
    with TestClient(client.app, base_url="http://testserver") as program:
        answer = program.post("/api/v1/uploads", headers={"Authorization": f"Bearer {key}"}, json={
            "filename": "v.pdf", "size": len(content), "sha256": sha(content), "document_id": document["id"]})
        assert answer.status_code == 403
        answer = upload_version(program, document["id"], "v.pdf", content, headers={"Authorization": f"Bearer {key}"})
        assert answer.status_code == 401  # a key is no way in to the routes that change documents
    tom = make_account("tom")
    with new_client(tom) as browser:
        assert upload_version(browser, document["id"], "v.pdf", content).status_code == 404
    assert len(versions(document["id"])) == 1


def test_a_device_may_use_the_tools(client: TestClient, operator: object) -> None:
    document = made(client)
    token = device_token(client)
    with TestClient(client.app, base_url="http://testserver") as device:
        answer = device.post(f"/api/v1/documents/{document['id']}/pages", headers={"Authorization": f"Bearer {token}"},
                             json={"base_version": 1, "pages": [{"page": 2}]})
        assert answer.status_code == 200 and answer.json()["pages"] == 1


def test_deleting_a_document_for_good_takes_every_version_with_it(client: TestClient, operator: object) -> None:
    document = made(client)
    edit(client, document["id"], [(1, 90)])
    paths = [file_of(v.original_path) for v in versions(document["id"])]
    from app.services import documents as documents_service

    with SessionLocal() as db:
        row = db.get(Document, document["id"])
        assert row is not None
        documents_service.delete_for_good(db, row)
        db.commit()
    process_all()
    assert not any(path.exists() for path in paths)
    with SessionLocal() as db:
        assert db.scalars(select(VersionInfo)).all() == [] and db.scalars(select(Note)).all() == []


def test_post_files_still_makes_documents_not_versions(client: TestClient, operator: Any) -> None:
    answer = post_files(client, ("a.pdf", pdf("A")), vault_id=own_vault(operator))
    assert answer.status_code == 201 and answer.json()["items"][0]["document"]["current_version"] == 1
    assert os.environ.get("NEXPAPER_DATA_DIR") == DATA_DIR


def test_a_note_says_what_is_new_about_an_uploaded_version(client: TestClient, operator: object) -> None:
    document = made(client)
    note = "  besserer Scan,\n Seite 2 war unscharf "
    too_long = upload_version(client, document["id"], "lang.pdf", pdf("Lang"), data={"note": "x" * 201})
    assert too_long.status_code == 422 and too_long.json()["detail"]["code"] == "invalid_note"
    answer = upload_version(client, document["id"], "neu.pdf", pdf("Besser"), data={"note": note})
    assert answer.status_code == 202 and answer.json()["note"] == "besserer Scan, Seite 2 war unscharf"
    assert len(versions(document["id"])) == 2 and leftovers() == []


def test_pictures_a_broken_off_run_left_behind_go_with_the_housekeeping(client: TestClient, operator: object) -> None:
    from app.services import pagetools

    old = pages.cache_root() / ".incoming-old"
    new = pages.cache_root() / ".incoming-new"
    for folder in (old, new):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "thumb.webp").write_bytes(b"RIFF")
    part = pages.cache_root() / "7" / ".incoming-part-123-v1-thumb.webp"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"RIFF")
    long_ago = 1_700_000_000
    for path in (old, part):
        os.utime(path, (long_ago, long_ago))
    assert pagetools.sweep_scratch() == 2
    assert not old.exists() and new.exists() and not part.exists()


def test_a_pdf_with_a_searchable_copy_gets_both_made_anew_and_neither_old_one_changes(
        client: TestClient, operator: object) -> None:
    """A scan that was recognised has the original and the searchable copy beside it: the new version has both, made
    from each, and the pictures and the text come from the searchable one."""
    document = made(client, "scan.pdf", "Eins", "Zwei")
    copy = pdf("Erkannt-Eins", "Erkannt-Zwei")
    with SessionLocal() as db:
        version = db.scalar(select(Version).where(Version.document_id == document["id"]))
        assert version is not None
        rel = version.original_path[: -len(".pdf")] + " (searchable).pdf"
        file_of(rel).write_bytes(copy)
        version.archive_path = rel
        db.commit()
    before = file_of(versions(document["id"])[0].original_path).read_bytes()
    assert edit(client, document["id"], [(2, 90), (1, 0)]).status_code == 200
    v1, v2 = versions(document["id"])
    assert file_of(v1.original_path).read_bytes() == before and file_of(v1.archive_path).read_bytes() == copy
    assert v2.archive_path and turns(file_of(v2.original_path)) == [90, 0] and turns(file_of(v2.archive_path)) == [90, 0]
    texts = pypdfium2.PdfDocument(str(file_of(v2.archive_path)))
    try:
        assert texts[0].get_textpage().get_text_bounded().startswith("Erkannt-Zwei")
    finally:
        texts.close()
    assert client.get(f"/api/v1/documents/{document['id']}/versions").json()[0]["has_archive"]
    process_all()
    v1, v2 = versions(document["id"])
    assert "(version 1, searchable)" in v1.archive_path and v2.archive_path.endswith(" (searchable).pdf")
