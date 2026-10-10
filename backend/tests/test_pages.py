"""The files and pictures of a document: rights, addresses per version, the cache, the pages behind a link."""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import clock
from app.db import SessionLocal
from app.models import Document, Version
from app.services import documents, pages

from . import files
from .conftest import DATA_DIR, make_account, new_client
from .intake import process_all, sha, upload_and_read, upload_one
from .papers import shared_vault

# Pages that carry text of their own (30 letters and more): no recognition, no searchable copy.
PDF3 = files.make_pdf(["Seite eins\nmit Text, der lang genug ist", "Seite zwei mit Text, der lang genug ist",
                       "Seite drei mit Text, der lang genug ist"])


def base(document_id: int, number: int = 1) -> str:
    return f"/api/v1/documents/{document_id}/versions/{number}"


@pytest.fixture
def read(client: TestClient, operator: object) -> dict[str, Any]:
    """A document of three pages, read, and a link to it."""
    return upload_and_read(client, "Strom Oktober.pdf", PDF3)


def webp(data: bytes) -> bool:
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def test_the_preview_and_the_pages_are_webp_pictures_in_two_sizes_and_the_cache_keeps_them(
        client: TestClient, read: dict[str, Any]) -> None:
    document = read["id"]
    preview = client.get(f"{base(document)}/preview")
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/webp" and webp(preview.content)
    small = client.get(f"{base(document)}/pages/2")
    large = client.get(f"{base(document)}/pages/2?size=large")
    assert small.status_code == large.status_code == 200 and webp(small.content) and webp(large.content)
    import io

    from PIL import Image

    assert Image.open(io.BytesIO(preview.content)).width == 360
    assert Image.open(io.BytesIO(small.content)).width == 720
    assert Image.open(io.BytesIO(large.content)).width == 1600
    # They stand in the cache under the document and the version, not in the folder of documents.
    cache = pages.document_dir(document)
    # The worker drew the preview and the small pages of this short document when it read it; the large page is new.
    assert {p.name for p in cache.iterdir()} == {"v1-thumb.webp", "v1-p1-small.webp", "v1-p2-small.webp",
                                                 "v1-p3-small.webp", "v1-p2-large.webp"}
    assert not any(p.suffix == ".webp" for p in (Path(DATA_DIR) / "dokumente").rglob("*"))


def test_a_cache_that_was_emptied_is_made_again_from_the_files(client: TestClient, read: dict[str, Any]) -> None:
    document = read["id"]
    first = client.get(f"{base(document)}/pages/3").content
    import shutil

    shutil.rmtree(Path(DATA_DIR) / "cache")
    assert client.get(f"{base(document)}/pages/3").content == first
    assert client.get(f"{base(document)}/preview").status_code == 200
    assert (pages.thumb_path(document, 1)).is_file()


def test_the_pictures_carry_an_etag_and_are_private_and_a_repeated_question_is_answered_without_the_picture(
        client: TestClient, read: dict[str, Any]) -> None:
    url = f"{base(read['id'])}/pages/1?size=large"
    first = client.get(url)
    etag = first.headers["etag"]
    assert etag and first.headers["cache-control"] == "private, no-cache"
    again = client.get(url, headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b"" and again.headers["etag"] == etag
    other = client.get(url, headers={"If-None-Match": '"something-else"'})
    assert other.status_code == 200 and other.content == first.content
    # Each size and each page has an address and a tag of its own.
    tags = {client.get(f"{base(read['id'])}/pages/{p}?size={s}").headers["etag"] for p in (1, 2) for s in ("small", "large")}
    assert len(tags) == 4


def test_every_picture_and_file_checks_the_right_to_read_the_document(client: TestClient, read: dict[str, Any]) -> None:
    urls = [f"{base(read['id'])}/{tail}" for tail in ("preview", "pages/1", "pages/1?size=large", "file", "archive")]
    urls.append(f"/api/v1/documents/{read['id']}/versions")
    with new_client(make_account("tom")) as stranger:
        assert [stranger.get(url).status_code for url in urls] == [404] * len(urls)
        # A stranger asking for pictures of a document that does not exist gets the same answer.
        assert stranger.get("/api/v1/documents/99999/versions/1/preview").status_code == 404
    with TestClient(client.app, base_url="http://testserver") as nobody:
        assert [nobody.get(url).status_code for url in urls] == [401] * len(urls)
    # A share gives the right to read, and with it the pictures.
    reader = make_account("lea")
    client.put(f"/api/v1/documents/{read['id']}/shares/{reader.id}", json={"right": "read"})
    with new_client(reader) as shared:
        assert shared.get(f"{base(read['id'])}/preview").status_code == 200
        assert shared.get(f"{base(read['id'])}/file").status_code == 200
    # The share ends: so do the pictures.
    client.delete(f"/api/v1/documents/{read['id']}/shares/{reader.id}")
    with new_client(reader) as shared:
        assert shared.get(f"{base(read['id'])}/preview").status_code == 404


def test_a_member_of_the_vault_reads_a_document_in_the_trash_and_a_key_for_reading_reads_too(
        client: TestClient, operator: object) -> None:
    lea, tom = make_account("lea"), make_account("tom")
    household = shared_vault("Household", make_account("boss"), (lea, "edit"), (tom, "read"))
    with new_client(lea) as editor:
        document = upload_and_read(editor, "a.pdf", PDF3, vault_id=household)
        editor.delete(f"/api/v1/documents/{document['id']}")
    with new_client(tom) as reader:
        assert reader.get(f"{base(document['id'])}/preview").status_code == 200
    from app.services import settings_service

    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": True})
    with new_client(tom) as reader:
        secret = reader.post("/api/v1/api-keys", json={"name": "k", "scope": "read"}).json()["secret"]
    with TestClient(client.app, base_url="http://testserver") as program:
        answer = program.get(f"{base(document['id'])}/pages/2", headers={"Authorization": f"Bearer {secret}"})
        assert answer.status_code == 200 and webp(answer.content)


def test_the_original_comes_as_it_came_in_place_for_a_pdf_and_as_a_download_for_the_rest(client: TestClient,
                                                                                         operator: object) -> None:
    pdf = upload_and_read(client, "Rechnung Strom.pdf", PDF3)
    served = client.get(f"{base(pdf['id'])}/file")
    assert served.status_code == 200 and served.content == PDF3 and served.headers["content-type"] == "application/pdf"
    assert served.headers["content-disposition"] == "inline; filename=\"Rechnung Strom.pdf\"; filename*=UTF-8''Rechnung%20Strom.pdf"
    # The tag is made with the server's secret: it does not carry the checksum of the file, not even a part of it.
    assert served.headers["etag"] != f'"{sha(PDF3)}"' and sha(PDF3)[:16] not in served.headers["etag"]
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["cache-control"] == "private, no-cache"
    assert client.get(f"{base(pdf['id'])}/file", headers={"If-None-Match": served.headers["etag"]}).status_code == 304
    heic = files.make_image("heic")
    photo = upload_and_read(client, "Foto.heic", heic)
    sent = client.get(f"{base(photo['id'])}/file")
    assert sent.content == heic and sent.headers["content-type"] == "image/heic"
    assert sent.headers["content-disposition"].startswith("attachment")
    for kind in ("webp", "avif"):
        picture = files.make_image(kind)
        other = upload_and_read(client, f"Foto.{kind}", picture)
        got = client.get(f"{base(other['id'])}/file")
        assert got.content == picture and got.headers["content-type"] == f"image/{kind}", kind
        assert got.headers["content-disposition"].startswith("attachment"), kind
    xml = upload_and_read(client, "rechnung.xml", files.invoice_xml())
    served_xml = client.get(f"{base(xml['id'])}/file")
    assert served_xml.headers["content-disposition"].startswith("attachment") and served_xml.content == files.invoice_xml()
    # A title cannot break out of the header.
    tricky = upload_and_read(client, 'x";\r\nSet-Cookie: a=b.pdf', files.make_pdf(["t"]))
    header = client.get(f"{base(tricky['id'])}/file").headers["content-disposition"]
    assert "\r" not in header and "\n" not in header and header.count('"') == 2


def test_the_pdf_made_from_a_picture_is_the_archive_copy(client: TestClient, operator: object) -> None:
    photo = upload_and_read(client, "foto.png", files.make_image("png", size=(500, 700)))
    archive = client.get(f"{base(photo['id'])}/archive")
    assert archive.status_code == 200 and archive.content[:5] == b"%PDF-" and archive.headers["content-type"] == "application/pdf"
    original = client.get(f"{base(photo['id'])}/file")
    assert original.headers["content-type"] == "image/png"
    # A PDF has no copy of its own yet; the page pictures of a photo come from the PDF made of it.
    pdf = upload_and_read(client, "scan.pdf", PDF3)
    assert client.get(f"{base(pdf['id'])}/archive").status_code == 404
    assert client.get(f"{base(photo['id'])}/pages/1").status_code == 200


def test_pages_that_the_document_does_not_have_and_versions_that_do_not_exist_are_404(client: TestClient,
                                                                                      read: dict[str, Any]) -> None:
    url = base(read["id"])
    assert client.get(f"{url}/pages/4").status_code == 404
    assert client.get(f"{url}/pages/0").status_code == 422
    assert client.get(f"{url}/pages/-1").status_code == 422
    assert client.get(f"{url}/pages/99999999999999999999").status_code == 422
    assert client.get(f"{url}/pages/1?size=huge").status_code == 422
    assert client.get(f"{base(read['id'], 2)}/preview").status_code == 404
    assert client.get(f"{base(read['id'], 0)}/preview").status_code == 422
    assert client.get(f"{base(read['id'], 2)}/file").status_code == 404
    # Nothing was written to the cache for a page that is not there.
    assert {p.name for p in pages.document_dir(read["id"]).iterdir()} == {
        "v1-thumb.webp", "v1-p1-small.webp", "v1-p2-small.webp", "v1-p3-small.webp"}


def test_a_document_still_being_read_has_a_file_but_no_pictures_yet(client: TestClient, operator: object) -> None:
    made = upload_one(client, "wait.pdf", PDF3)
    assert client.get(f"{base(made['id'])}/preview").status_code == 409
    assert client.get(f"{base(made['id'])}/pages/1").json()["detail"]["code"] == "not_ready"
    assert client.get(f"{base(made['id'])}/file").content == PDF3


def test_a_new_version_has_pictures_and_addresses_of_its_own(client: TestClient, read: dict[str, Any]) -> None:
    document = read["id"]
    old = client.get(f"{base(document)}/pages/1").content
    second = files.make_pdf(["Ganz anderer Inhalt\nmit anderem Text\nund mehr davon"])
    from app.services import storage

    with SessionLocal() as db:
        first = db.query(Version).filter_by(document_id=document, n=1).one()
        relative = first.original_path.rsplit("/", 1)[0] + "/neu.pdf"
        storage.write_new(relative, second)
        db.add(Version(document_id=document, n=2, original_path=relative, sha256=sha(second), size=len(second), pages=1,
                       created_by=None, created_at=clock.now(), note="test"))
        db.get(Document, document).current_version = 2  # type: ignore[union-attr]
        db.commit()
    listed = client.get(f"/api/v1/documents/{document}/versions").json()
    assert [(v["n"], v["current"]) for v in listed] == [(2, True), (1, False)]
    new = client.get(f"{base(document, 2)}/pages/1")
    assert new.status_code == 200 and new.content != old
    assert new.headers["etag"] != client.get(f"{base(document)}/pages/1").headers["etag"]
    # The old version still answers with its old picture; a page of the new one is not a page of the old.
    assert client.get(f"{base(document)}/pages/1").content == old
    assert client.get(f"{base(document, 2)}/pages/2").status_code == 404
    assert {p.name for p in pages.document_dir(document).iterdir()} >= {"v1-p1-small.webp", "v2-p1-small.webp"}


def test_four_requests_for_a_page_at_once_are_answered_within_the_limit_of_one_person(client: TestClient, read: dict[str, Any]) -> None:
    results: list[tuple[int, int]] = []
    gate = threading.Barrier(4, timeout=30)

    def ask() -> None:
        with TestClient(client.app, base_url="http://testserver", cookies=client.cookies) as same:
            gate.wait()
            answer = same.get(f"{base(read['id'])}/pages/3?size=large")
            results.append((answer.status_code, len(answer.content)))

    threads = [threading.Thread(target=ask) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # One person has two pages in the making at a time: of four requests at once some are asked to come back (503), none
    # fails otherwise, and what was drawn is the same picture for all.
    assert {code for code, _ in results} <= {200, 503} and any(code == 200 for code, _ in results)
    assert len({size for code, size in results if code == 200}) == 1
    assert client.get(f"{base(read['id'])}/pages/3?size=large").status_code == 200


def test_the_server_says_it_is_busy_when_it_is_drawing_as_many_pages_as_it_may(client: TestClient, read: dict[str, Any],
                                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    gate = pages._semaphore()
    gate.acquire()
    monkeypatch.setattr(pages, "WAIT_SECONDS", 0.2)
    try:
        started = time.monotonic()
        busy = client.get(f"{base(read['id'])}/pages/2?size=large")
        assert busy.status_code == 503 and busy.headers["retry-after"]
        assert time.monotonic() - started < 3, "a request is not kept waiting for a place"
        # What the cache has is served without a place.
        assert client.get(f"{base(read['id'])}/preview").status_code == 200
    finally:
        gate.release()
    assert client.get(f"{base(read['id'])}/pages/2?size=large").status_code == 200


def test_the_server_does_not_keep_a_request_waiting_for_a_place_for_long_by_default() -> None:
    assert pages.WAIT_SECONDS <= 2


def test_one_person_and_one_link_have_only_a_few_pages_in_the_making_at_a_time(client: TestClient,
                                                                              read: dict[str, Any]) -> None:
    me = client.get("/api/v1/auth/me").json()["id"]
    token = make_link(client, read["id"])
    with SessionLocal() as db:
        from app.models import Link

        link_id = db.query(Link).one().id
    url = f"{base(read['id'])}/pages/3?size=large"
    link_url = f"/api/v1/l/{token}/pages/3?size=large"
    pages._active[f"u{me}"] = pages.PER_PRINCIPAL
    pages._active[f"l{link_id}"] = pages.PER_PRINCIPAL
    try:
        assert client.get(url).status_code == 503
        with TestClient(client.app, base_url="http://testserver") as outside:
            assert outside.get(link_url).status_code == 503
            # A page that is in the cache needs no place, so it is not counted.
            assert client.get(f"{base(read['id'])}/pages/1").status_code == 200
            assert outside.get(f"/api/v1/l/{token}/pages/1").status_code == 200
        # Somebody else is not held up by it.
        with new_client(make_account("probe")) as other:
            share = client.put(f"/api/v1/documents/{read['id']}/shares/{other.get('/api/v1/auth/me').json()['id']}",
                               json={"right": "read"})
            assert share.status_code == 200
            assert other.get(url).status_code == 200
    finally:
        pages._active.clear()
    assert client.get(url).status_code == 200
    assert not pages._active


def test_the_cache_is_trimmed_to_its_size_and_clears_what_was_used_longest_ago(client: TestClient,
                                                                              read: dict[str, Any]) -> None:
    import os

    folder = pages.document_dir(read["id"])
    files_ = sorted(folder.glob("*.webp"))
    assert len(files_) == 4
    now = time.time()
    for index, path in enumerate(files_):
        path.write_bytes(b"x" * 1000)
        os.utime(path, (now - 1000 + index * 10, now - 1000 + index * 10))
    # Using the oldest one moves it to the front of the line.
    oldest = files_[0]
    assert client.get(f"{base(read['id'])}/{'preview' if oldest.name.endswith('thumb.webp') else 'pages/' + oldest.name.split('-p')[1][0]}"
                      ).status_code == 200
    assert pages.trim(10**9) == 0  # large enough: nothing goes
    removed = pages.trim(2500)
    assert removed >= 2 and sum(p.stat().st_size for p in folder.glob("*.webp")) <= 2500 * 0.9
    assert oldest.exists() or oldest.name != files_[0].name
    assert pages.trim(0) == 0  # 0 or less is no limit that trims


def test_the_cache_size_is_a_setting_with_a_floor_and_the_housekeeping_trims_to_it(client: TestClient,
                                                                                  read: dict[str, Any]) -> None:
    from app.services import jobs

    assert client.put("/api/v1/settings", json={"cache_max_mb": 63}).status_code == 422
    assert client.put("/api/v1/settings", json={"cache_max_mb": 64}).status_code == 200
    assert client.get("/api/v1/settings").json()["cache_max_mb"] == 64
    big = pages.document_dir(read["id"]) / "v1-p9-small.webp"
    big.write_bytes(b"x" * (70 * 1024 * 1024))
    jobs.housekeeping()
    assert not big.exists()


def test_the_cache_goes_with_a_document_that_is_deleted_for_good(client: TestClient, read: dict[str, Any]) -> None:
    client.get(f"{base(read['id'])}/pages/2")
    assert pages.document_dir(read["id"]).is_dir()
    client.delete(f"/api/v1/documents/{read['id']}")
    with SessionLocal() as db:
        db.get(Document, read["id"]).trashed_at = clock.now() - timedelta(days=31)  # type: ignore[union-attr]
        db.commit()
        assert documents.purge_expired(db) == 1
    process_all()
    assert not pages.document_dir(read["id"]).exists()
    assert [p for p in (Path(DATA_DIR) / "dokumente").rglob("*") if p.is_file()] == []


def test_the_paths_of_the_pictures_come_from_numbers_only() -> None:
    assert pages.page_path(7, 2, 3, "small") == pages.document_dir(7) / "v2-p3-small.webp"
    with pytest.raises(ValueError):
        pages.page_path(7, 2, 3, "../../etc")
    assert str(pages.document_dir(5)).endswith("5")
    assert pages.thumb_path(int("12"), int("3")).name == "v3-thumb.webp"


# --- Behind a link ------------------------------------------------------------------------------------------------------


def make_link(client: TestClient, document: int, **body: Any) -> str:
    made = client.post(f"/api/v1/documents/{document}/links", json={"recipient": "Tax office", "days": 7, **body})
    assert made.status_code == 201, made.text
    return made.json()["url"].rsplit("/", 1)[-1]  # type: ignore[no-any-return]


def test_a_link_shows_the_pages_of_its_one_document_and_nothing_else(client: TestClient, read: dict[str, Any]) -> None:
    other = upload_and_read(client, "other.pdf", files.make_pdf(["Anderes Dokument"]))
    token = make_link(client, read["id"])
    with TestClient(client.app, base_url="http://testserver") as outside:
        shown = outside.get(f"/api/v1/l/{token}").json()
        assert shown["has_pages"] is True and shown["pages"] == 3
        preview = outside.get(f"/api/v1/l/{token}/preview")
        assert preview.status_code == 200 and webp(preview.content) and preview.headers["cache-control"] == "private, no-cache"
        pages_seen = [outside.get(f"/api/v1/l/{token}/pages/{n}") for n in (1, 2, 3)]
        assert [p.status_code for p in pages_seen] == [200] * 3 and len({p.content for p in pages_seen}) == 3
        assert outside.get(f"/api/v1/l/{token}/pages/3?size=large").status_code == 200
        assert outside.get(f"/api/v1/l/{token}/pages/4").status_code == 404
        # The same picture as the document's own, nothing of the other document, and no way to name another one.
        own = client.get(f"{base(read['id'])}/pages/2").content
        assert pages_seen[1].content == own
        assert outside.get(f"/api/v1/l/{token}/pages/1").content != client.get(f"{base(other['id'])}/pages/1").content
        for path in (f"/api/v1/l/{token}/versions/1/pages/1", f"/api/v1/l/{token}/../documents/{other['id']}",
                     f"/api/v1/documents/{read['id']}/versions/1/pages/1"):
            assert outside.get(path, headers={"Authorization": f"Bearer {token}"}).status_code in (401, 404, 405)


def test_a_link_without_download_still_shows_the_pages_but_never_hands_out_a_file(client: TestClient,
                                                                                   read: dict[str, Any]) -> None:
    token = make_link(client, read["id"], allow_download=False)
    with TestClient(client.app, base_url="http://testserver") as outside:
        assert outside.get(f"/api/v1/l/{token}/file").status_code == 403
        assert outside.get(f"/api/v1/l/{token}/pages/1?size=large").status_code == 200
        assert outside.get(f"/api/v1/l/{token}/preview").status_code == 200
        assert outside.get(f"/api/v1/l/{token}").json()["has_pages"] is True


def test_the_pictures_behind_a_link_stop_when_the_link_stops(client: TestClient, read: dict[str, Any],
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    token = make_link(client, read["id"])
    other = make_link(client, read["id"], recipient="Bank")
    paths = [f"/api/v1/l/{token}/preview", f"/api/v1/l/{token}/pages/1", f"/api/v1/l/{token}/pages/2?size=large"]
    with TestClient(client.app, base_url="http://testserver") as outside:
        assert [outside.get(path).status_code for path in paths] == [200] * 3
        # Revoked.
        links = client.get(f"/api/v1/documents/{read['id']}/links").json()
        mine = next(link for link in links if link["recipient"] == "Tax office")
        client.delete(f"/api/v1/documents/{read['id']}/links/{mine['id']}")
        assert [outside.get(path).status_code for path in paths] == [404] * 3
    # A link that was not revoked: the document in the trash stops it, the end of its days stops it.
    with TestClient(client.app, base_url="http://testserver") as outside:
        live = [f"/api/v1/l/{other}/preview", f"/api/v1/l/{other}/pages/1"]
        assert [outside.get(path).status_code for path in live] == [200, 200]
        client.delete(f"/api/v1/documents/{read['id']}")
        assert [outside.get(path).status_code for path in live] == [404, 404]
        client.post(f"/api/v1/documents/{read['id']}/restore")
        assert [outside.get(path).status_code for path in live] == [200, 200]
        now = clock.now()
        monkeypatch.setattr(clock, "now", lambda: now + timedelta(days=8))
        assert [outside.get(path).status_code for path in live] == [404, 404]


def test_the_switch_of_the_operator_stops_the_pictures_behind_links_too(client: TestClient, read: dict[str, Any]) -> None:
    token = make_link(client, read["id"])
    with TestClient(client.app, base_url="http://testserver") as outside:
        assert outside.get(f"/api/v1/l/{token}/pages/1").status_code == 200
        assert client.put("/api/v1/settings", json={"links_allowed": False}).status_code == 200
        assert outside.get(f"/api/v1/l/{token}/pages/1").status_code == 404
        assert outside.get(f"/api/v1/l/{token}/preview").status_code == 404


def test_wrong_tokens_count_against_the_sender_on_the_pictures_too(client: TestClient, read: dict[str, Any]) -> None:
    with TestClient(client.app, base_url="http://testserver") as outside:
        codes = [outside.get(f"/api/v1/l/lnk_{'x' * 40}/pages/1").status_code for _ in range(60)]
    assert codes[0] == 404 and 429 in codes


def test_the_rights_of_the_maker_decide_what_a_link_shows(client: TestClient, operator: object) -> None:
    lea = make_account("lea")
    household = shared_vault("Household", make_account("boss"), (lea, "manage"))
    with new_client(lea) as maker:
        document = upload_and_read(maker, "a.pdf", PDF3, vault_id=household)
        token = make_link(maker, document["id"])
        with TestClient(client.app, base_url="http://testserver") as outside:
            assert outside.get(f"/api/v1/l/{token}/pages/1").status_code == 200
            from app.models import VaultMember

            with SessionLocal() as db:
                db.query(VaultMember).filter_by(vault_id=household, user_id=lea.id).delete()
                db.commit()
            assert outside.get(f"/api/v1/l/{token}/pages/1").status_code == 404



def test_the_name_in_the_download_keeps_what_a_name_may_have_in_the_extended_form_and_is_plain_in_the_other(
        client: TestClient, operator: object) -> None:
    unicode_title = "Rechnung M\u00e4rz \u20ac"
    made = upload_and_read(client, unicode_title + ".pdf", PDF3)
    header = client.get(f"{base(made['id'])}/file").headers["content-disposition"]
    assert header == ("inline; filename=\"Rechnung M_rz _.pdf\"; "
                      "filename*=UTF-8''Rechnung%20M%C3%A4rz%20%E2%82%AC.pdf")
    header.encode("ascii")  # every byte of the header is ASCII, as the standard wants it
    # The same through a link, and a title that tries to leave the header or the folder.
    token = make_link(client, made["id"])
    with TestClient(client.app, base_url="http://testserver") as outside:
        assert outside.get(f"/api/v1/l/{token}/file").headers["content-disposition"] == header
    nasty = upload_and_read(client, "a" + chr(34) + "; filename=evil" + chr(92) + ".." + chr(92) + "x" + chr(0x202E) + ".pdf", files.make_pdf(["n"]))
    value = client.get(f"{base(nasty['id'])}/file").headers["content-disposition"]
    assert value.count(chr(34)) == 2 and chr(92) not in value and chr(13) not in value and chr(10) not in value
    assert value.startswith("inline; filename=\"") and "; filename*=UTF-8''" in value
    value.encode("ascii")


def test_the_cache_headers_of_every_answer_with_a_file_or_a_picture_say_private_and_ask_again(
        client: TestClient, operator: object) -> None:
    photo = upload_and_read(client, "foto.png", files.make_image("png", size=(500, 700)))
    for tail in ("file", "archive", "preview", "pages/1", "pages/1?size=large"):
        answer = client.get(f"{base(photo['id'])}/{tail}")
        assert answer.status_code == 200, tail
        assert answer.headers["cache-control"] == "private, no-cache", tail
        assert answer.headers["etag"].startswith('"') and sha(files.make_image("png", size=(500, 700)))[:8] not in answer.headers["etag"]


def test_a_page_that_takes_too_long_to_draw_ends_with_an_answer_and_does_not_hang(
        client: TestClient, read: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The limit on drawing is tested by a test that turns red when the limit is missing, not one that hangs with it: the
    request runs in a thread and the test waits for it a while."""
    from app.services import processing

    stub = tmp_path / "slow_worker.py"
    stub.write_text("import time\ntime.sleep(40)\n", encoding="utf-8", newline=chr(10))
    monkeypatch.setattr(processing, "WORKER", stub)
    monkeypatch.setattr(processing, "RENDER_SECONDS", 1)
    answer: list[int] = []

    def ask() -> None:
        with TestClient(client.app, base_url="http://testserver", cookies=client.cookies) as same:
            answer.append(same.get(f"{base(read['id'])}/pages/2?size=large").status_code)

    thread = threading.Thread(target=ask, daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(20)
    assert not thread.is_alive(), "the request hangs: the time limit of drawing is not applied"
    assert answer == [422] and time.monotonic() - started < 15


def test_drawing_a_page_is_given_a_short_time_limit_of_its_own(client: TestClient, read: dict[str, Any],
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """The test above shows that a limit is applied; this one that the limit a page gets is short, whatever the limit
    for reading a whole document is."""
    from app.services import processing

    given: list[int] = []
    real = processing.spawn

    def spy(request: dict[str, Any], timeout: int) -> Any:
        given.append(timeout)
        return real(request, timeout)

    monkeypatch.setattr(processing, "spawn", spy)
    assert client.get(f"{base(read['id'])}/pages/3?size=large").status_code == 200
    assert given == [processing.RENDER_SECONDS] and 5 <= processing.RENDER_SECONDS <= 120
