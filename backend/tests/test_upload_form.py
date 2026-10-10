"""The browser's upload: ``POST /api/v1/documents`` (multipart, one or more files, each its own document)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Document, Event, Job, Vault, VaultMember, Version
from app.services import jobs, storage

from . import files
from .conftest import DATA_DIR, TAB, make_account, new_client
from .intake import device_token, disk_files, limit, post_files, row_of, sha, upload_key, upload_one, version_of
from .papers import PDF, own_vault, shared_vault


def count(model: type) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)


def test_a_pdf_becomes_a_document_in_the_vault_of_the_person_that_waits_to_be_read(client: TestClient) -> None:
    owner = make_account("lea")
    pdf = files.make_pdf(["Rechnung 2026-1001"])
    with new_client(owner) as lea:
        answer = post_files(lea, ("Strom Oktober.pdf", pdf))
        assert answer.status_code == 201
        item = answer.json()["items"][0]
        document = item["document"]
        assert item["status"] == "accepted" and item["error"] is None and item["duplicate"] is None
        assert document["title"] == "Strom Oktober" and document["status"] == "processing"
        assert document["source"] == "upload" and document["owner"]["name"] == "lea" and document["pages"] == 0
        assert document["vault_id"] == own_vault(owner) and document["my_right"] == "manage"
        # The file stands on the disk under a readable name, the way it came, with its checksum.
        version = version_of(document["id"])
        assert version.sha256 == sha(pdf) and version.size == len(pdf) and version.note == "upload"
        assert version.original_path.endswith(".pdf") and (Path(DATA_DIR) / storage.FOLDER / version.original_path).read_bytes() == pdf
        # A job to read it waits, and the history says where it came from.
        with SessionLocal() as db:
            waiting = db.scalars(select(Job).where(Job.kind == jobs.PROCESS)).all()
            assert [(j.ref, j.state) for j in waiting] == [(document["id"], "queued")]
            assert [(e.action, e.detail) for e in db.scalars(select(Event).where(Event.document_id == document["id"]))] == [
                ("created", {"source": "upload"})]
        # Nobody but the maker sees it.
        with new_client(make_account("tom")) as tom:
            assert tom.get(f"/api/v1/documents/{document['id']}").status_code == 404


@pytest.mark.parametrize("name, content, kind", [
    ("scan.pdf", files.make_pdf(), ".pdf"),
    ("foto.JPG", files.make_image("jpeg"), ".jpg"),
    ("foto.png", files.make_image("png"), ".png"),
    ("scan.tiff", files.make_tiff(2), ".tif"),
    ("IMG_0001.HEIC", files.make_image("heic"), ".heic"),
    ("download.WEBP", files.make_image("webp"), ".webp"),
    ("photo.avif", files.make_image("avif"), ".avif"),
    ("rechnung.xml", files.invoice_xml(), ".xml"),
    ("zugferd.xml", files.cii_xml(), ".xml"),
    # The ending of the name is not believed: a PDF called .jpg is stored as what it is.
    ("liegt-falsch.jpg", files.make_pdf(), ".pdf"),
    ("kein-ende", files.make_image("png"), ".png"),
], ids=["pdf", "jpeg", "png", "tiff", "heic", "webp", "avif", "ubl", "cii", "pdf as jpg", "no ending"])
def test_every_kind_is_taken_and_stored_by_what_it_is(client: TestClient, operator: object, name: str, content: bytes,
                                                      kind: str) -> None:
    document = upload_one(client, name, content)
    assert version_of(document["id"]).original_path.endswith(kind)


@pytest.mark.parametrize("name, content", [
    ("tool.pdf", files.EXE),
    ("page.png", files.HTML),
    ("drawing.svg", files.SVG),
    ("drawing.png", files.SVG),
    ("note.xml", b'<?xml version="1.0"?><note>hello</note>'),
    ("xxe.xml", b'<?xml version="1.0"?><!DOCTYPE Invoice [<!ENTITY x SYSTEM "file:///etc/passwd">]><Invoice>&x;</Invoice>'),
    ("anim.gif", b"GIF89a" + b"\x00" * 100),
    ("text.pdf", b"this is not a pdf at all"),
    ("zip.pdf", b"PK\x03\x04" + b"\x00" * 100),
    ("sound.webp", b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 100),
    ("clip.avif", b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 100),
], ids=["exe as pdf", "html as png", "svg", "svg as png", "other xml", "xml with entity", "gif", "text as pdf", "zip",
        "wave as webp", "video as avif"])
def test_a_file_of_the_wrong_kind_is_415_and_leaves_nothing_behind(client: TestClient, operator: object, name: str,
                                                                    content: bytes) -> None:
    answer = post_files(client, (name, content))
    assert answer.status_code == 415, answer.text
    detail = answer.json()["detail"]
    assert detail["code"] in ("unsupported_type", "xml_not_invoice", "xml_doctype") and detail["message"]
    assert detail["items"][0]["status"] == "rejected"
    assert count(Document) == 0 and count(Version) == 0 and count(Job) == 0
    assert disk_files() == []


def test_a_file_that_is_too_large_is_413_and_not_stored_and_the_others_in_the_request_are_taken(
        client: TestClient, operator: object) -> None:
    limit(upload_max_mb=1)
    big = files.make_pdf(["x"]) + b"\n%" + b"0" * (1024 * 1024 + 10)
    answer = post_files(client, ("big.pdf", big), ("small.pdf", PDF))
    assert answer.status_code == 201
    first, second = answer.json()["items"]
    assert (first["status"], first["http_status"], first["error"]["code"]) == ("rejected", 413, "too_large")
    assert second["status"] == "accepted"
    assert count(Document) == 1 and len(disk_files()) == 1
    # Only the big one: the answer of the request is 413.
    refused = post_files(client, ("big.pdf", big))
    assert refused.status_code == 413 and refused.json()["detail"]["code"] == "too_large"
    assert count(Document) == 1 and len(disk_files()) == 1


def test_a_body_larger_than_the_request_may_be_is_refused_before_it_is_read(client: TestClient, operator: object) -> None:
    limit(upload_max_mb=1)  # a request may carry ten files of that size, and a little more
    huge = files.make_pdf(["x"]) + b"\n%" + b"0" * (12 * 1024 * 1024)
    answer = post_files(client, ("huge.pdf", huge))
    assert answer.status_code == 413
    assert count(Document) == 0 and disk_files() == []
    # Padding in a field that is no file does not get past either: the request as a whole has a limit (each file has one
    # of its own, a field has none but this one).
    padded = client.post("/api/v1/documents", data={"note": "x" * (12 * 1024 * 1024)},
                         files=[("file", ("a.pdf", PDF, "application/pdf"))])
    assert padded.status_code == 413 and padded.json()["detail"]["code"] == "too_large"
    assert count(Document) == 0 and disk_files() == []


def test_more_files_than_a_request_may_carry_turn_the_whole_request_away_at_once(
        client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import limits

    monkeypatch.setattr(limits, "FILES_PER_REQUEST", 2)
    answer = post_files(client, *[(f"{i}.pdf", files.make_pdf([f"Seite {i}"])) for i in range(3)])
    assert answer.status_code == 413 and answer.json()["detail"]["code"] == "too_many_files"
    # Nothing of the request was kept, and no result is made for the parts past the limit.
    assert count(Document) == 0 and disk_files() == []
    assert "items" not in answer.json()["detail"]


def test_a_flood_of_tiny_parts_is_stopped_at_the_limit_and_not_read_to_the_end(client: TestClient, operator: object) -> None:
    crlf = bytes([13, 10])
    boundary = b"floodboundary"
    part = (b"--" + boundary + crlf + b'Content-Disposition: form-data; name="file"; filename="a.pdf"' + crlf + crlf + b"x" + crlf)
    body = part * 20000 + b"--" + boundary + b"--" + crlf
    started = time.monotonic()
    answer = client.post("/api/v1/documents", content=body, headers={"Content-Type": "multipart/form-data; boundary=floodboundary"})
    assert answer.status_code == 413 and answer.json()["detail"]["code"] == "too_many_files"
    assert time.monotonic() - started < 3 and len(answer.content) < 500
    assert count(Document) == 0 and disk_files() == []
    # Many parts that are no files: 400 as well, after a few tens.
    fields = b"".join(b"--" + boundary + crlf + b'Content-Disposition: form-data; name="f' + str(i).encode() + b'"' + crlf + crlf + b"v" + crlf
                      for i in range(200)) + b"--" + boundary + b"--" + crlf
    many = client.post("/api/v1/documents", content=fields, headers={"Content-Type": "multipart/form-data; boundary=floodboundary"})
    assert many.status_code == 400 and many.json()["detail"]["code"] == "too_many_parts"


def multipart(*parts: tuple[bytes, bytes], closed: bool = True) -> tuple[bytes, dict[str, str]]:
    """A multipart body from ``(header value, content)`` pairs, the headers as raw bytes, and its content type."""
    crlf = bytes([13, 10])
    boundary = b"namesboundary"
    body = b"".join(b"--" + boundary + crlf + b"Content-Disposition: " + head + crlf + b"Content-Type: application/octet-stream" + crlf
                    + crlf + content + crlf for head, content in parts)
    if closed:
        body += b"--" + boundary + b"--" + crlf
    return body, {"Content-Type": "multipart/form-data; boundary=namesboundary"}


@pytest.mark.parametrize("name, title", [
    ("Rechnung März €.pdf", "Rechnung März €"),
    ("Screenshot 10.15 AM.pdf", "Screenshot 10.15 AM"),  # the narrow space reads, and the title takes a plain one
    ("Quittung 🧾 Kaffee.pdf", "Quittung 🧾 Kaffee"),
    ("請求書 2026.pdf", "請求書 2026"),
    ("„Abschlag“ Strom ‑ Oktober.pdf", "„Abschlag“ Strom ‑ Oktober"),
], ids=["euro", "narrow space", "emoji", "cjk", "quotes and hyphen"])
def test_a_name_beyond_latin_1_is_a_good_title_and_does_not_spoil_the_other_files_of_the_request(
        client: TestClient, operator: object, name: str, title: str) -> None:
    answer = post_files(client, (name, files.make_pdf(["a"])), ("gut.pdf", files.make_pdf(["b"])))
    assert answer.status_code == 201, answer.text
    first, second = answer.json()["items"]
    assert (first["status"], second["status"]) == ("accepted", "accepted")
    assert first["document"]["title"] == title and "�" not in first["document"]["title"]
    assert second["document"]["title"] == "gut"


def test_the_extended_filename_of_rfc_5987_is_read_and_wins(client: TestClient, operator: object) -> None:
    body, headers = multipart(
        (b"form-data; name=\"file\"; filename=\"fallback.pdf\"; filename*=UTF-8''Rechnung%20M%C3%A4rz%20%E2%82%AC.pdf",
         files.make_pdf(["a"])),
        ('form-data; name="file"; filename="März".pdf'.encode(), files.make_pdf(["b"])),
        (b'form-data; name="file"; filename="M' + bytes([0xE4]) + b'rz Latin1.pdf"', files.make_pdf(["c"])))
    answer = client.post("/api/v1/documents", content=body, headers=headers)
    assert answer.status_code == 201, answer.text
    titles = [item["document"]["title"] for item in answer.json()["items"]]
    assert titles[0] == "Rechnung März €"
    assert "�" not in " ".join(titles) and titles[2] == "März Latin1"


def test_a_header_that_cannot_be_taken_apart_spoils_its_own_part_only(client: TestClient, operator: object) -> None:
    body, headers = multipart((b"form-data; name=\"file\"; filename*=one'quote.pdf", files.make_pdf(["a"])),
                              (b'form-data; name="file"; filename="gut.pdf"', files.make_pdf(["b"])))
    answer = client.post("/api/v1/documents", content=body, headers=headers)
    assert answer.status_code == 201
    first, second = answer.json()["items"]
    assert first["status"] == "rejected" and first["http_status"] == 400 and first["error"]["code"] == "invalid_input"
    assert second["status"] == "accepted" and count(Document) == 1


def test_a_body_that_stops_before_the_closing_boundary_is_400_not_500_and_leaves_nothing(client: TestClient,
                                                                                         operator: object) -> None:
    body, headers = multipart((b'form-data; name="file"; filename="a.pdf"', files.make_pdf(["a"])), closed=False)
    answer = client.post("/api/v1/documents", content=body, headers=headers)
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "invalid_input"
    assert count(Document) == 0 and disk_files() == []


def test_an_empty_file_and_a_request_without_files_are_422_and_a_body_that_is_no_form_is_400(
        client: TestClient, operator: object) -> None:
    assert post_files(client, ("empty.pdf", b"")).status_code == 422
    assert client.post("/api/v1/documents", data={"note": "hello"}, files={}).status_code in (400, 422)
    assert client.post("/api/v1/documents", files=[("note", ("note.txt", b"hello", "text/plain"))]).status_code == 415
    assert client.post("/api/v1/documents", json={"file": "x"}).status_code == 400
    broken = client.post("/api/v1/documents", content=b"--nope\r\nContent-Disposition: form-data; name=\"file\"; "
                         b"filename=\"a.pdf\"\r\n\r\n" + PDF, headers={"Content-Type": "multipart/form-data; boundary=zzz"})
    assert broken.status_code in (400, 422)
    assert count(Document) == 0 and disk_files() == []


def test_a_name_with_path_parts_stays_a_title_and_the_file_stays_inside_the_document_folder(
        client: TestClient, operator: object) -> None:
    names = ["../../../etc/cron.d/evil.pdf", "..\\..\\windows\\system32\\x.pdf", "/abs/path/file.pdf", "C:\\temp\\f.pdf",
             "con.pdf", "a\x00b.pdf", "x" * 300 + ".pdf"]
    for name in names:
        document = upload_one(client, name, files.make_pdf([name[:20]]))
        assert "/" not in document["title"] and "\\" not in document["title"] and "\x00" not in document["title"]
    base = (Path(DATA_DIR) / storage.FOLDER).resolve()
    stored = disk_files()
    assert len(stored) == len(names)
    assert all(base in path.resolve().parents for path in stored)
    assert not any(path.name.startswith(storage.INCOMING) for path in stored)


def test_the_vault_is_the_one_named_else_the_one_chosen_else_the_own(client: TestClient, operator: object) -> None:
    lea, tom = make_account("lea"), make_account("tom")
    household = shared_vault("Household", make_account("boss"), (lea, "edit"), (tom, "read"))
    with new_client(lea) as lea_browser:
        assert upload_one(lea_browser, "own.pdf", files.make_pdf(["a"]))["vault_id"] == own_vault(lea)
        assert upload_one(lea_browser, "shared.pdf", files.make_pdf(["b"]), vault_id=household)["vault_id"] == household
        # The vault she chose for her uploads.
        assert lea_browser.put("/api/v1/me/preferences", json={"default_vault": household}).status_code == 200
        assert upload_one(lea_browser, "chosen.pdf", files.make_pdf(["c"]))["vault_id"] == household
        # She loses the right to add there: her uploads go to her own vault again, without an error.
        with SessionLocal() as db:
            db.query(VaultMember).filter_by(vault_id=household, user_id=lea.id).update({"right": "read"})
            db.commit()
        assert upload_one(lea_browser, "after.pdf", files.make_pdf(["d"]))["vault_id"] == own_vault(lea)
    with new_client(tom) as tom_browser:
        # Read only: he sees the vault and may not add to it.
        denied = post_files(tom_browser, ("x.pdf", PDF), vault_id=household)
        assert denied.status_code == 403
        # Nobody else's vault, and none that is not there, is told apart.
        assert post_files(tom_browser, ("x.pdf", PDF), vault_id=own_vault(lea)).status_code == 404
        assert post_files(tom_browser, ("x.pdf", PDF), vault_id=99999).status_code == 404
    assert count(Document) == 4 and len(disk_files()) == 4


def test_the_same_file_twice_is_taken_both_times_and_the_second_says_so(client: TestClient, operator: object) -> None:
    pdf = files.make_pdf(["Einmal"])
    first = upload_one(client, "a.pdf", pdf)
    again = post_files(client, ("b.pdf", pdf)).json()["items"][0]
    assert again["status"] == "accepted"
    assert again["duplicate"] == {"document_id": first["id"], "title": "a", "kind": "same"}
    assert again["document"]["duplicate"] == {"document_id": first["id"], "title": "a", "kind": "same"}
    assert row_of(again["document"]["id"]).duplicate_of == first["id"]
    # Both stand on the disk, under names that do not clash.
    assert len({version_of(first["id"]).original_path, version_of(again["document"]["id"]).original_path}) == 2


def test_a_file_somebody_else_keeps_out_of_sight_is_not_mentioned(client: TestClient, operator: object) -> None:
    pdf = files.make_pdf(["Privat"])
    with new_client(make_account("lea")) as lea:
        mine = upload_one(lea, "private.pdf", pdf)
    with new_client(make_account("tom")) as tom:
        theirs = post_files(tom, ("same.pdf", pdf)).json()["items"][0]
    # The answer has the shape of a file that is new: nothing in it, in the document or in the rows.
    assert theirs["duplicate"] is None and theirs["document"]["duplicate"] is None
    assert row_of(theirs["document"]["id"]).duplicate_of is None
    assert mine["id"] != theirs["document"]["id"]


def test_two_uploads_at_the_same_moment_make_two_documents_with_two_files(client: TestClient, operator: object) -> None:
    lea = make_account("lea")
    results: list[int] = []
    gate = threading.Barrier(4, timeout=20)

    def send(number: int) -> None:
        with new_client(lea) as browser:
            gate.wait()
            answer = post_files(browser, ("same name.pdf", files.make_pdf([f"Blatt {number}"])))
            results.append(answer.status_code)

    threads = [threading.Thread(target=send, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [201] * 4
    assert count(Document) == 4 and len({v.original_path.lower() for v in _versions()}) == 4
    assert len(disk_files()) == 4


def _versions() -> list[Version]:
    with SessionLocal() as db:
        return list(db.scalars(select(Version)))


def test_who_may_upload_a_browser_a_device_and_a_key_for_uploading_but_not_a_key_for_reading_nor_a_stranger(
        client: TestClient, operator: object) -> None:
    lea = make_account("lea")
    with new_client(lea) as browser:
        token = device_token(browser)
    # No sign-in.
    with TestClient(client.app, base_url="http://testserver", headers=TAB) as nobody:
        assert nobody.post("/api/v1/documents", files=[("file", ("a.pdf", PDF))]).status_code == 401
    with TestClient(client.app, base_url="http://testserver") as program:
        # A device token needs no tab header.
        device = program.post("/api/v1/documents", files=[("file", ("d.pdf", files.make_pdf(["Gerät"])))],
                              headers={"Authorization": f"Bearer {token}"})
        assert device.status_code == 201 and device.json()["items"][0]["document"]["source"] == "api"
        # A key for uploading uploads; one for reading does not (and the other way round).
        key = upload_key(lea)
        sent = program.post("/api/v1/documents", files=[("file", ("k.pdf", files.make_pdf(["Schlüssel"])))],
                            headers={"Authorization": f"Bearer {key}"})
        assert sent.status_code == 201 and sent.json()["items"][0]["document"]["source"] == "api"
        assert program.get("/api/v1/documents", headers={"Authorization": f"Bearer {key}"}).status_code == 403
        read_key = upload_key(lea, "read")
        refused = program.post("/api/v1/documents", files=[("file", ("r.pdf", PDF))],
                               headers={"Authorization": f"Bearer {read_key}"})
        assert refused.status_code == 403 and refused.json()["detail"]["code"] == "key_scope"
        assert program.get("/api/v1/documents", headers={"Authorization": f"Bearer {read_key}"}).status_code == 200
        # A key does not come from a web page.
        assert program.post("/api/v1/documents", files=[("file", ("o.pdf", PDF))],
                            headers={"Authorization": f"Bearer {key}", "Origin": "https://evil.example.com"}).status_code == 403
    assert count(Document) == 2


def test_a_browser_without_the_tab_header_cannot_upload(client: TestClient, operator: object) -> None:
    with TestClient(client.app, base_url="http://testserver", cookies=client.cookies) as plain:
        assert plain.post("/api/v1/documents", files=[("file", ("a.pdf", PDF))]).status_code == 400
    assert count(Document) == 0


def test_the_tokens_of_a_person_never_reach_the_log_or_the_disk_by_an_upload(client: TestClient, operator: object) -> None:
    document = upload_one(client, "secret name.pdf", files.make_pdf(["x"]))
    assert document["title"] == "secret name"
    names = " ".join(str(path) for path in disk_files())
    assert "npd_" not in names and "npk_" not in names


def test_the_vault_row_is_untouched_by_uploads(client: TestClient, operator: object) -> None:
    with SessionLocal() as db:
        before = [(v.id, v.name, v.folder) for v in db.scalars(select(Vault))]
    upload_one(client, "a.pdf", PDF)
    with SessionLocal() as db:
        assert [(v.id, v.name, v.folder) for v in db.scalars(select(Vault))] == before


def chunks(name: str, content: bytes, piece: int = 16 * 1024):
    """A multipart body as an async stream of small pieces, the way a real connection delivers it (the test client hands
    the whole body over in one piece, which hides what happens between the first bytes and the last), and its type."""
    boundary = "nexpaperboundary0123456789"
    crlf = bytes([13, 10])
    head = (b"--" + boundary.encode() + crlf + b'Content-Disposition: form-data; name="file"; filename="' + name.encode() + b'"' + crlf
            + b"Content-Type: application/octet-stream" + crlf + crlf)
    tail = crlf + b"--" + boundary.encode() + b"--" + crlf
    body = head + content + tail

    async def stream():
        for at in range(0, len(body), piece):
            yield body[at:at + piece]

    return stream(), f"multipart/form-data; boundary={boundary}"


def read(name: str, content: bytes, max_file: int):
    import asyncio

    from app.services import receiving

    stream, content_type = chunks(name, content)
    return asyncio.run(receiving.read_form(stream, content_type, max_file, 10))


def test_a_file_that_grows_past_the_limit_while_it_arrives_leaves_no_partial_file_behind(operator: object) -> None:
    form = read("big.pdf", files.make_pdf(["x"]) + b"\n%" + b"0" * (300 * 1024), max_file=100 * 1024)
    try:
        (received,) = form.files
        assert received.problem is not None and received.problem[:2] == (413, "too_large")
        assert received.path is None
        # It was being written when the limit was reached: the part that was written is gone.
        assert disk_files() == []
    finally:
        form.cleanup()


def test_a_file_of_the_wrong_kind_is_not_written_at_all_however_long_it_is_and_a_good_one_arrives_whole(
        operator: object) -> None:
    refused = read("tool.pdf", files.EXE + b"0" * (200 * 1024), max_file=10**9)
    try:
        assert refused.files[0].problem is not None and refused.files[0].problem[0] == 415
        assert disk_files() == []
    finally:
        refused.cleanup()
    good_bytes = files.make_pdf(["fine"]) + b"\n%" + b"0" * (200 * 1024)
    good = read("fine.pdf", good_bytes, max_file=10**9)
    try:
        (received,) = good.files
        assert received.problem is None and received.path is not None and received.size == len(good_bytes)
        assert received.path.read_bytes() == good_bytes and received.sha256 == sha(good_bytes)
    finally:
        good.cleanup()
    assert disk_files() == []


def test_a_body_without_a_length_is_counted_while_it_arrives_and_stopped_at_the_limit(client: TestClient,
                                                                                       operator: object) -> None:
    limit(upload_max_mb=1)  # a request may carry 11 MB then
    crlf = bytes([13, 10])
    head = (b"--lengthless" + crlf + b'Content-Disposition: form-data; name="file"; filename="a.pdf"' + crlf + crlf)

    def body():
        yield head
        for _ in range(24):
            yield b"%" * (512 * 1024)

    answer = client.post("/api/v1/documents", content=body(), headers={"Content-Type": "multipart/form-data; boundary=lengthless"})
    assert answer.status_code == 413
    assert count(Document) == 0 and disk_files() == []
