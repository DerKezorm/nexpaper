"""A document that has come in is read in a worker process: pages, preview, the PDF made from a picture, the errors that
leave the document in the inbox, the time limit, a restart."""

from __future__ import annotations

import io
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import worker
from app.db import SessionLocal
from app.models import Event, Job
from app.services import jobs, limits, pages, processing

from . import files
from .conftest import DATA_DIR, make_account, new_client
from .intake import limit, process_all, row_of, sha, upload_and_read, upload_one, version_of
from .papers import shared_vault


def archive_file(document_id: int) -> Path:
    path = version_of(document_id).archive_path
    assert path
    return Path(DATA_DIR) / "dokumente" / path


def events(document_id: int) -> list[tuple[str, Any]]:
    with SessionLocal() as db:
        return [(e.action, e.detail) for e in db.scalars(select(Event).where(Event.document_id == document_id).order_by(Event.id))]


def jobs_of(kind: str) -> list[tuple[int, str, int, str]]:
    with SessionLocal() as db:
        return [(j.ref, j.state, j.attempts, j.error) for j in db.scalars(select(Job).where(Job.kind == kind).order_by(Job.id))]


def pdf_pages(path: Path) -> list[tuple[float, float]]:
    import pypdfium2

    document = pypdfium2.PdfDocument(str(path))
    try:
        return [document[i].get_size() for i in range(len(document))]
    finally:
        document.close()


# --- What a good file comes to ---------------------------------------------------------------------------------------


def test_a_pdf_is_read_counted_and_gets_its_preview_and_waits_in_the_inbox(client: TestClient, operator: object) -> None:
    pdf = files.make_pdf(["Seite eins\nmit mehr Text\nund noch mehr", "Seite zwei mit genug Text, um als Text zu gelten"])
    made = upload_one(client, "Strom.pdf", pdf)
    # The process job, and the rename it asked for to settle the names.
    assert process_all() == 2
    document = client.get(f"/api/v1/documents/{made['id']}").json()
    assert document["status"] == "inbox" and document["pages"] == 2 and document["process_error"] == ""
    version = version_of(made["id"])
    assert version.pages == 2 and version.archive_path == ""
    # The original is not touched: same bytes, same checksum.
    assert (Path(DATA_DIR) / "dokumente" / version.original_path).read_bytes() == pdf and version.sha256 == sha(pdf)
    thumb = pages.thumb_path(made["id"], 1)
    assert thumb.is_file() and thumb.read_bytes()[:4] == b"RIFF" and thumb.read_bytes()[8:12] == b"WEBP"
    assert jobs_of(jobs.PROCESS) == [(made["id"], "done", 1, "")]
    assert [name for name, _ in events(made["id"])] == ["created", "processed"]
    assert events(made["id"])[1][1] == {"pages": 2, "text_pages": 2, "ocr_pages": 0}
    # The change feed shows the document at its new number.
    feed = client.get("/api/v1/changes?since=0").json()
    assert [item["document"]["status"] for item in feed["items"] if item.get("document")] == ["inbox"]


@pytest.mark.parametrize("kind, name, frames", [("png", "foto.png", 1), ("jpeg", "foto.jpg", 1), ("heic", "foto.heic", 1),
                                                ("webp", "foto.webp", 1), ("avif", "foto.avif", 1)])
def test_a_picture_becomes_a_pdf_beside_the_original_which_stays_as_it_came(
        client: TestClient, operator: object, kind: str, name: str, frames: int) -> None:
    data = files.make_image(kind, size=(600, 800), text="Quittung 14,90 EUR\nKaffee")
    document = upload_and_read(client, name, data)
    assert document["status"] == "inbox" and document["pages"] == frames and document["process_error"] == ""
    version = version_of(document["id"])
    original = Path(DATA_DIR) / "dokumente" / version.original_path
    assert original.read_bytes() == data and sha(data) == version.sha256
    archive = archive_file(document["id"])
    assert archive.read_bytes()[:5] == b"%PDF-" and archive.name.endswith(" (searchable).pdf")
    assert archive.parent == original.parent
    sizes = pdf_pages(archive)
    assert len(sizes) == frames and sizes[0][1] > sizes[0][0]  # upright, taller than wide, as the picture
    assert pages.thumb_path(document["id"], 1).is_file()


def test_a_photo_turned_by_the_camera_comes_out_upright(client: TestClient, operator: object) -> None:
    from PIL import Image

    image = Image.new("RGB", (800, 400), "white")  # wide on the disk, "turned right" by the EXIF note
    exif = Image.Exif()
    exif[0x0112] = 6
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif)
    document = upload_and_read(client, "turned.jpg", buffer.getvalue())
    width, height = pdf_pages(archive_file(document["id"]))[0]
    assert height > width, (width, height)


def test_a_multi_page_tiff_becomes_one_pdf_with_all_pages(client: TestClient, operator: object) -> None:
    document = upload_and_read(client, "scan.tif", files.make_tiff(3))
    assert document["pages"] == 3 and len(pdf_pages(archive_file(document["id"]))) == 3


def test_a_picture_with_transparency_and_an_odd_colour_mode_still_makes_a_pdf(client: TestClient, operator: object) -> None:
    from PIL import Image

    transparent = io.BytesIO()
    Image.new("RGBA", (200, 300), (255, 0, 0, 80)).save(transparent, "PNG")
    palette = io.BytesIO()
    Image.new("P", (200, 300), 3).save(palette, "PNG")
    for name, data in (("alpha.png", transparent.getvalue()), ("palette.png", palette.getvalue())):
        document = upload_and_read(client, name, data)
        assert document["status"] == "inbox" and document["process_error"] == "" and document["pages"] == 1, name


def test_a_webp_animation_is_one_page_its_first_frame(client: TestClient, operator: object) -> None:
    limit(upload_max_pages=3)  # six frames against three pages: the frames are not pages
    data = files.make_animated_webp(frames=6)
    document = upload_and_read(client, "bewegt.webp", data)
    assert document["status"] == "inbox" and document["pages"] == 1 and document["process_error"] == ""
    assert (Path(DATA_DIR) / "dokumente" / version_of(document["id"]).original_path).read_bytes() == data
    assert len(pdf_pages(archive_file(document["id"]))) == 1


def test_an_hdr_photo_from_an_iphone_is_one_page_the_photo_not_its_gain_map(client: TestClient, operator: object) -> None:
    from PIL import Image

    data = files.make_hdr_jpeg(size=(600, 800))
    assert Image.open(io.BytesIO(data)).format == "MPO" and Image.open(io.BytesIO(data)).n_frames == 2  # the premise
    limit(upload_max_pages=1)  # the gain map is no page, so one page is enough
    document = upload_and_read(client, "IMG_0042.jpg", data)
    assert document["status"] == "inbox" and document["pages"] == 1 and document["process_error"] == ""
    assert (Path(DATA_DIR) / "dokumente" / version_of(document["id"]).original_path).read_bytes() == data
    sizes = pdf_pages(archive_file(document["id"]))
    assert len(sizes) == 1 and sizes[0][1] > sizes[0][0]  # the photo (taller than wide), not the gain map
    first = pages.thumb_path(document["id"], 1)
    with Image.open(first) as thumb:
        red, green, blue = thumb.convert("RGB").getpixel((thumb.width // 2, thumb.height // 2))
    assert red > 150 and green < 100 and blue < 100, (red, green, blue)


@pytest.mark.parametrize("kind", ["webp", "avif"])
def test_a_webp_and_an_avif_with_transparency_are_drawn_on_white(client: TestClient, operator: object, kind: str) -> None:
    import pypdfium2
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (200, 300), (0, 0, 0, 0)).save(buffer, kind.upper())
    document = upload_and_read(client, f"klar.{kind}", buffer.getvalue())
    assert document["status"] == "inbox" and document["process_error"] == ""
    pdf = pypdfium2.PdfDocument(str(archive_file(document["id"])))
    try:
        shown = pdf[0].render(scale=0.2).to_pil().convert("RGB")
    finally:
        pdf.close()
    assert min(shown.get_flattened_data()) > (230, 230, 230)


@pytest.mark.parametrize("name, make", [
    ("cut.webp", lambda: files.make_image("webp", size=(400, 500))[:60]),
    ("cut.avif", lambda: files.make_image("avif", size=(400, 500))[:60]),
    ("empty.webp", lambda: b"RIFF\x04\x00\x00\x00WEBPVP8 "),
    ("noise.webp", lambda: b"RIFF\x20\x00\x00\x00WEBPVP8 " + bytes(range(40))),
    ("noise.avif", lambda: b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00avifmif1" + bytes(range(60))),
], ids=["cut webp", "cut avif", "empty webp", "noise webp", "noise avif"])
def test_a_broken_webp_or_avif_waits_in_the_inbox_with_the_reason_and_the_server_goes_on(
        client: TestClient, operator: object, name: str, make: Any) -> None:
    document = upload_and_read(client, name, make())
    assert document["status"] == "inbox" and document["process_error"] == "broken"
    assert upload_and_read(client, "gut.webp", files.make_image("webp"))["process_error"] == ""


def test_a_webp_with_too_many_pixels_is_turned_into_an_error_not_a_crash(client: TestClient, operator: object) -> None:
    limit(upload_max_megapixels=1)
    bomb = upload_and_read(client, "bomb.webp", files.bomb_webp(3000, 3000))  # 9 megapixels in a few hundred bytes
    assert bomb["process_error"] == "too_large" and bomb["status"] == "inbox"
    # Between the limit and twice the limit Pillow only warns; the worker still refuses it.
    assert upload_and_read(client, "over.webp", files.bomb_webp(1500, 1000))["process_error"] == "too_large"
    assert upload_and_read(client, "under.webp", files.bomb_webp(900, 1000))["process_error"] == ""


def test_an_e_invoice_in_xml_is_kept_and_gets_a_readable_page(client: TestClient, operator: object) -> None:
    # The XML stays the original; nexpaper sets a readable PDF from its data (``test_einvoices.py`` has more).
    document = upload_and_read(client, "rechnung.xml", files.invoice_xml())
    assert document["status"] == "inbox" and document["pages"] == 1 and document["process_error"] == ""
    assert version_of(document["id"]).archive_path.endswith(".pdf")
    assert client.get(f"/api/v1/documents/{document['id']}/versions/1/preview").status_code == 200


def test_the_pdf_made_from_a_picture_moves_with_the_fields_of_the_document(client: TestClient, operator: object) -> None:
    document = upload_and_read(client, "foto.png", files.make_image("png", size=(500, 700)))
    client.patch(f"/api/v1/documents/{document['id']}", json={"sender": "Stadtwerke Lindenau", "date": "2026-03-14"})
    jobs.run_pending()
    version = version_of(document["id"])
    assert "Stadtwerke Lindenau" in version.original_path and "Stadtwerke Lindenau" in version.archive_path
    assert version.archive_path.endswith("2026-03-14 Document (searchable).pdf")
    assert (Path(DATA_DIR) / "dokumente" / version.archive_path).is_file()


# --- Files that cannot be read -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("name, data, code", [
    ("password.pdf", files.encrypted_pdf("hunter2 correct horse"), "encrypted"),
    ("cut.pdf", files.broken_pdf(), "broken"),
    ("garbage.pdf", b"%PDF-1.4\n" + b"\x00\x01\x02garbage" * 50, "broken"),
    ("broken.png", files.make_image("png")[:60] + b"\x00" * 40, "broken"),
    ("broken.jpg", files.make_image("jpeg")[:80], "broken"),
], ids=["encrypted", "cut off", "garbage", "png", "jpeg"])
def test_a_file_that_cannot_be_read_waits_in_the_inbox_with_the_reason_and_the_server_goes_on(
        client: TestClient, operator: object, name: str, data: bytes, code: str) -> None:
    document = upload_and_read(client, name, data)
    assert document["status"] == "inbox" and document["process_error"] == code and document["pages"] == 0
    assert version_of(document["id"]).archive_path == "" and not pages.thumb_path(document["id"], 1).exists()
    # A mistake of the file is not tried again and does not count as a failure of the job.
    assert jobs_of(jobs.PROCESS) == [(document["id"], "done", 1, "")]
    assert events(document["id"])[-1] == ("process_failed", {"error": code})
    # Nothing of the failed run stays on the disk but the original.
    left = [p for p in (Path(DATA_DIR) / "dokumente").rglob("*") if p.is_file()]
    assert len(left) == 1
    # And the next document is read as if nothing happened.
    ok = upload_and_read(client, "fine.pdf", files.make_pdf(["gut"]))
    assert ok["status"] == "inbox" and ok["process_error"] == ""


def test_a_pdf_with_too_many_pages_and_a_picture_with_too_many_pixels_are_turned_into_an_error_not_a_crash(
        client: TestClient, operator: object) -> None:
    limit(upload_max_pages=3, upload_max_megapixels=1)
    many = upload_and_read(client, "many.pdf", files.make_pdf(["p"] * 5))
    assert many["process_error"] == "too_many_pages" and many["status"] == "inbox"
    bomb = upload_and_read(client, "bomb.png", files.bomb_png(3000, 3000))  # 9 megapixels in a few kilobytes
    assert bomb["process_error"] == "too_large" and bomb["status"] == "inbox"
    # Between the limit and twice the limit Pillow only warns; the worker still refuses it.
    over = upload_and_read(client, "over.png", files.bomb_png(1500, 1000))  # 1.5 megapixels against a limit of 1
    assert over["process_error"] == "too_large"
    assert upload_and_read(client, "under.png", files.bomb_png(900, 1000))["process_error"] == ""
    frames = upload_and_read(client, "frames.tif", files.make_tiff(5))
    assert frames["process_error"] == "too_many_pages"
    # Within the limits the same kinds of files pass.
    assert upload_and_read(client, "ok.pdf", files.make_pdf(["p"] * 3))["process_error"] == ""


def test_trying_again_reads_the_document_anew_and_only_a_document_that_failed(client: TestClient, operator: object) -> None:
    limit(upload_max_pages=2)
    document = upload_and_read(client, "many.pdf", files.make_pdf(["p"] * 4))
    assert document["process_error"] == "too_many_pages"
    limit(upload_max_pages=10)
    again = client.post(f"/api/v1/documents/{document['id']}/retry")
    assert again.status_code == 200
    assert again.json()["status"] == "processing" and again.json()["process_error"] == ""
    process_all()
    done = client.get(f"/api/v1/documents/{document['id']}").json()
    assert done["status"] == "inbox" and done["pages"] == 4 and done["process_error"] == ""
    names = [name for name, _ in events(document["id"])]
    assert names == ["created", "process_failed", "retried", "processed"]
    # A document that was read well has nothing to retry; nor has one still waiting.
    assert client.post(f"/api/v1/documents/{document['id']}/retry").status_code == 409
    waiting = upload_one(client, "w.pdf", files.make_pdf(["w"]))
    assert client.post(f"/api/v1/documents/{waiting['id']}/retry").status_code == 409


def test_only_somebody_who_may_change_the_document_may_ask_for_another_try(client: TestClient, operator: object) -> None:
    lea, tom, ann = make_account("lea"), make_account("tom"), make_account("ann")
    household = shared_vault("Household", make_account("boss"), (lea, "edit"), (tom, "read"))
    with new_client(lea) as browser:
        document = upload_and_read(browser, "cut.pdf", files.broken_pdf(), vault_id=household)
        assert document["process_error"] == "broken"
    with new_client(tom) as reader:
        assert reader.post(f"/api/v1/documents/{document['id']}/retry").status_code == 403
    with new_client(ann) as stranger:
        assert stranger.post(f"/api/v1/documents/{document['id']}/retry").status_code == 404
    assert row_of(document["id"]).process_error == "broken"


def test_a_document_in_the_trash_is_still_read_and_goes_back_where_it_was_asked_to(client: TestClient,
                                                                                    operator: object) -> None:
    made = upload_one(client, "gone.pdf", files.make_pdf(["gone"]))
    client.delete(f"/api/v1/documents/{made['id']}")
    process_all()
    in_trash = client.get(f"/api/v1/documents/{made['id']}").json()
    assert in_trash["status"] == "trash" and in_trash["pages"] == 1
    restored = client.post(f"/api/v1/documents/{made['id']}/restore").json()
    assert restored["status"] == "inbox"


def test_a_document_deleted_while_it_waited_leaves_no_file_of_the_run(client: TestClient, operator: object) -> None:
    from app.models import Document
    from app.services import documents

    made = upload_one(client, "gone.png", files.make_image("png"))
    with SessionLocal() as db:
        found = db.get(Document, made["id"])
        assert found is not None
        documents.delete_for_good(db, found)
        db.commit()
    process_all()
    assert not pages.document_dir(made["id"]).exists()
    assert [p for p in (Path(DATA_DIR) / "dokumente").rglob("*") if p.is_file()] == []


# --- The worker process: limits, kill, restart ---------------------------------------------------------------------------


def script(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "worker_stub.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8", newline="\n")
    return path


def fast_limits(monkeypatch: pytest.MonkeyPatch, seconds: int = 1) -> None:
    monkeypatch.setitem(limits.RANGES, "process_timeout_seconds", (1, 86400))
    limit(process_timeout_seconds=seconds)


def test_a_worker_that_takes_too_long_is_killed_with_everything_it_started_and_the_document_ends_in_the_inbox(
        client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    beat = tmp_path / "beat.txt"
    child_beat = tmp_path / "child-beat.txt"
    child = tmp_path / "child_stub.py"
    child.write_text(textwrap.dedent(f"""
        import time
        while True:
            open('{child_beat.as_posix()}', 'a').write('c')
            time.sleep(0.1)
    """), encoding="utf-8", newline=chr(10))
    monkeypatch.setattr(processing, "WORKER", script(tmp_path, f"""
        import subprocess, sys, time
        # A child of its own: the kill must reach it too.
        subprocess.Popen([sys.executable, '{child.as_posix()}'])
        while True:
            open('{beat.as_posix()}', 'a').write('x')
            time.sleep(0.1)
    """))
    fast_limits(monkeypatch)
    made = upload_one(client, "slow.pdf", files.make_pdf(["slow"]))
    started = time.monotonic()
    # In a thread with a deadline of its own: a time limit that is not applied must turn this red, not hang the run.
    runner = threading.Thread(target=process_all, daemon=True)
    runner.start()
    runner.join(40)
    # Three tries, one second each, then it stays failed.
    assert not runner.is_alive(), "the time limit was not applied"
    assert time.monotonic() - started < 40
    assert jobs_of(jobs.PROCESS) == [(made["id"], "failed", 3, "timeout")]
    document = client.get(f"/api/v1/documents/{made['id']}").json()
    assert document["status"] == "inbox" and document["process_error"] == "timeout"
    # Both the worker and its child are dead: what they write does not grow any more.
    for path in (beat, child_beat):
        assert path.exists()
        size = path.stat().st_size
        time.sleep(1.0)
        assert path.stat().st_size == size, f"{path.name} still grows"
    # With a good worker again, trying again reads it.
    monkeypatch.undo()
    assert client.post(f"/api/v1/documents/{made['id']}/retry").status_code == 200
    process_all()
    assert client.get(f"/api/v1/documents/{made['id']}").json()["process_error"] == ""


def test_a_worker_that_crashes_or_answers_with_nonsense_is_tried_three_times_and_then_the_document_waits(
        client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for number, body in enumerate(("import sys\nsys.exit(139)\n", "print('not json at all')\n", "")):
        monkeypatch.setattr(processing, "WORKER", script(tmp_path, body))
        made = upload_one(client, f"crash{number}.pdf", files.make_pdf([f"crash {number}"]))
        process_all()
        assert jobs_of(jobs.PROCESS)[-1] == (made["id"], "failed", 3, "failed"), number
        document = client.get(f"/api/v1/documents/{made['id']}").json()
        assert document["status"] == "inbox" and document["process_error"] == "failed"
        assert events(made["id"])[-1] == ("process_failed", {"error": "failed"})


def test_a_worker_that_fails_once_and_then_works_reads_the_document(
        client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    marker = tmp_path / "first-try"
    real = processing.WORKER
    stub = script(tmp_path, f"""
        import os, runpy, sys
        marker = '{marker.as_posix()}'
        if not os.path.exists(marker):
            open(marker, 'w').write('x')
            sys.exit(1)
        runpy.run_path('{real.as_posix()}', run_name='__main__')
    """)
    monkeypatch.setattr(processing, "WORKER", stub)
    made = upload_one(client, "twice.pdf", files.make_pdf(["twice"]))
    process_all()
    assert jobs_of(jobs.PROCESS) == [(made["id"], "done", 2, "")]
    assert client.get(f"/api/v1/documents/{made['id']}").json()["status"] == "inbox"


def test_the_worker_gets_no_secret_and_no_database(client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch,
                                                   tmp_path: Path) -> None:
    seen = tmp_path / "environment.txt"
    monkeypatch.setattr(processing, "WORKER", script(tmp_path, f"""
        import json, os, sys
        request = json.loads(sys.stdin.read())
        if request['op'] == 'recognize':
            # The step that reads the text: the same stand-in, which sees the same.
            open(request['text_out'], 'w').write('[""]')
        open('{seen.as_posix()}', 'a').write(json.dumps({{'env': sorted(os.environ), 'cwd': os.getcwd(),
                                                'argv': sys.argv, 'flags': sys.flags.isolated,
                                                'listing': os.listdir('.')}}) + chr(10))
        print(json.dumps({{'ok': True, 'pages': 1, 'phash': '', 'derived': False}}))
    """))
    made = upload_one(client, "env.pdf", files.make_pdf(["env"]))
    jobs.run_pending()
    reports = [__import__("json").loads(line) for line in seen.read_text(encoding="utf-8").splitlines()]
    # Both steps (the file, the text), each in a process of its own.
    assert len(reports) == 2
    for report in reports:
        assert not [key for key in report["env"] if key.upper().startswith("NEXPAPER") or "SECRET" in key.upper()
                    or "TOKEN" in key.upper() or "PASSWORD" in key.upper()]
        # A folder of its own, empty, and not the data folder where the database and the secret key are.
        assert report["listing"] == [] and Path(report["cwd"]).resolve() != Path(DATA_DIR).resolve()
        assert Path(DATA_DIR).resolve() not in Path(report["cwd"]).resolve().parents
        assert not Path(report["cwd"]).exists()  # and it went with the run
        assert report["flags"] == 1  # isolated mode: no user site, no working directory on the path
    assert client.get(f"/api/v1/documents/{made['id']}").json()["pages"] == 1


#: How long a wait of the stop test lasts at the most (seconds): far longer than a loaded machine needs.
STOP_WAIT = 60.0


def test_a_job_that_was_running_when_the_server_stopped_runs_again_after_the_start(client: TestClient,
                                                                                    operator: object) -> None:
    made = upload_one(client, "restart.pdf", files.make_pdf(["restart"]))
    with SessionLocal() as db:
        job = db.scalars(select(Job).where(Job.kind == jobs.PROCESS)).one()
        job.state, job.attempts = "running", 1
        db.commit()
    assert process_all() == 0  # nothing waits: the job looks taken
    with SessionLocal() as db:
        jobs.recover(db)
    assert process_all() == 2  # the reading, and the rename it asks for
    assert client.get(f"/api/v1/documents/{made['id']}").json()["status"] == "inbox"
    assert jobs_of(jobs.PROCESS) == [(made["id"], "done", 2, "")]


def test_stopping_the_server_stops_the_worker_and_leaves_the_job_waiting_without_using_a_try(
        client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    beat = tmp_path / "beat.txt"
    monkeypatch.setattr(processing, "WORKER", script(tmp_path, f"""
        import time
        while True:
            open('{beat.as_posix()}', 'a').write('x')
            time.sleep(0.1)
    """))
    monkeypatch.setitem(limits.RANGES, "process_timeout_seconds", (1, 86400))
    limit(process_timeout_seconds=600)
    made = upload_one(client, "stop.pdf", files.make_pdf(["stop"]))
    # The run happens in a thread of its own, and every wait of this test has an end: the stop is asked for when the
    # worker has shown that it runs (not after a fixed time, which a loaded machine overtakes), and a run that does not
    # end is reported as that instead of keeping the whole test run waiting.
    run = threading.Thread(target=jobs.run_pending, daemon=True)
    run.start()
    try:
        started = time.monotonic()
        while not beat.exists() and run.is_alive() and time.monotonic() - started < STOP_WAIT:
            time.sleep(0.05)
        assert beat.exists(), f"the worker did not start within {STOP_WAIT} s"
        jobs.stopping.set()
        run.join(timeout=STOP_WAIT)
        assert not run.is_alive(), f"the run did not end {STOP_WAIT} s after the server was asked to stop"
    finally:
        jobs.stopping.set()
        run.join(timeout=STOP_WAIT)
        jobs.stopping.clear()
    assert jobs_of(jobs.PROCESS) == [(made["id"], "queued", 0, "")]
    assert client.get(f"/api/v1/documents/{made['id']}").json()["status"] == "processing"
    size = beat.stat().st_size
    time.sleep(0.8)
    assert beat.stat().st_size == size


def test_no_worker_is_started_once_the_server_is_stopping(client: TestClient, operator: object,
                                                          monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    started = tmp_path / "started.txt"
    monkeypatch.setattr(processing, "WORKER", script(tmp_path, f"""
        open('{started.as_posix()}', 'a').write('x')
    """))
    made = upload_one(client, "late.pdf", files.make_pdf(["late"]))
    jobs.stopping.set()
    try:
        jobs.run_pending()
    finally:
        jobs.stopping.clear()
    assert not started.exists()
    assert jobs_of(jobs.PROCESS) == [(made["id"], "queued", 0, "")]


def test_one_document_is_read_at_a_time_in_the_order_they_came(client: TestClient, operator: object) -> None:
    ids = [upload_one(client, f"{n}.pdf", files.make_pdf([f"Nummer {n}"]))["id"] for n in range(3)]
    assert jobs.run_pending(limit=1, kinds=jobs.SLOW) == 1
    states = {i: client.get(f"/api/v1/documents/{i}").json()["status"] for i in ids}
    assert [states[i] for i in ids] == ["inbox", "processing", "processing"]
    assert process_all() >= 2
    assert {client.get(f"/api/v1/documents/{i}").json()["status"] for i in ids} == {"inbox"}


def test_a_rename_waits_for_nobody_a_process_job_takes(client: TestClient, operator: object) -> None:
    made = upload_one(client, "a.pdf", files.make_pdf(["a"]))
    client.patch(f"/api/v1/documents/{made['id']}", json={"sender": "Stadtwerke Lindenau"})
    # The quick jobs (the rename) run without touching the reading job.
    assert jobs.run_pending(kinds=jobs.QUICK) == 1
    assert jobs_of(jobs.PROCESS) == [(made["id"], "queued", 0, "")]
    assert "Stadtwerke Lindenau" in version_of(made["id"]).original_path
    process_all()
    assert client.get(f"/api/v1/documents/{made['id']}").json()["status"] == "inbox"


# --- The worker itself --------------------------------------------------------------------------------------------------


def test_the_memory_limit_is_set_where_the_system_has_one(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple[int, int]]] = []

    class FakeResource:
        RLIMIT_AS = "as"
        RLIMIT_DATA = "data"

        @staticmethod
        def setrlimit(which: str, values: tuple[int, int]) -> None:
            calls.append((which, values))

    monkeypatch.setitem(sys.modules, "resource", FakeResource)
    worker._limit_memory(0)
    assert calls == []
    worker._limit_memory(512)
    assert calls == [("as", (512 * 1024 * 1024, 512 * 1024 * 1024))]


def test_the_worker_without_resource_module_runs_without_a_memory_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "resource", None)  # an import of it fails, as on Windows
    worker._limit_memory(512)


def test_a_page_is_never_drawn_larger_than_the_pixel_limit() -> None:
    import pypdfium2

    huge = files.make_pdf(["wide"], size=(14400, 14400))
    document = pypdfium2.PdfDocument(huge)
    try:
        image = worker._drawn(document[0], 6000, 4_000_000)
    finally:
        document.close()
    assert image.width * image.height <= 4_000_000 * 1.02


@pytest.mark.skipif(sys.platform == "win32", reason="the memory limit of a process is a Linux feature (setrlimit)")
def test_a_page_that_needs_more_memory_than_the_limit_ends_that_one_run_and_without_a_limit_it_is_drawn(
        tmp_path: Path) -> None:
    """The real thing, on a system that has it: the same page at 9000 pixels wide is drawn without a limit and is refused
    (`too_large`, no retry, no file) under 512 MB. Skipped on Windows, where the other test only checks the call."""
    source = tmp_path / "a.pdf"
    source.write_bytes(files.make_pdf(["Hallo"]))
    request = {"op": "render", "pdf": str(source), "page": 0, "width": 9000, "render_pixels": 10**9}
    free = processing.spawn({**request, "out": str(tmp_path / "free.webp"), "memory_mb": 0}, 120)
    assert free.ok and (tmp_path / "free.webp").is_file()
    held = processing.spawn({**request, "out": str(tmp_path / "held.webp"), "memory_mb": 512}, 120)
    assert not held.ok and held.error == "too_large" and not held.retry
    assert not (tmp_path / "held.webp").exists()


def test_a_page_of_absurd_size_is_refused_as_too_large_whatever_the_system_can_limit(
        client: TestClient, operator: object) -> None:
    """Once the scale was held at a minimum, which lifted the cap on pixels again: a page of a million points a side was drawn
    with a hundred million. No limit on memory is needed to refuse it (Windows has none)."""
    for size in (10**6, 30_000):
        document = upload_and_read(client, f"huge{size}.pdf", files.make_pdf(["x"], size=(size, size)))
        assert document["process_error"] == "too_large", size
        assert not pages.thumb_path(document["id"], 1).exists()
    # A large but real sheet (the standard's own limit, two metres) is read and drawn small.
    sheet = upload_and_read(client, "plan.pdf", files.make_pdf(["Bauplan des Hauses am Weiher, Erdgeschoss"], size=(14400, 5000)))
    assert sheet["process_error"] == "" and pages.thumb_path(sheet["id"], 1).is_file()
    assert client.get(f"/api/v1/documents/{sheet['id']}/versions/1/pages/1?size=large").status_code == 200


def test_the_people_of_a_server_take_turns_for_the_worker_and_one_who_uploads_a_lot_does_not_hold_the_others_up(
        client: TestClient, operator: object) -> None:
    lea, tom = make_account("lea"), make_account("tom")
    with new_client(lea) as lea_browser, new_client(tom) as tom_browser:
        first = [upload_one(lea_browser, f"lea{n}.pdf", files.make_pdf([f"Lea {n}"]))["id"] for n in range(4)]
        theirs = upload_one(tom_browser, "tom.pdf", files.make_pdf(["Tom"]))["id"]
    order: list[int] = []
    for _ in range(5):
        assert jobs.run_pending(limit=1, kinds=jobs.SLOW) == 1
        with SessionLocal() as db:
            started = db.scalars(select(Job).where(Job.kind == jobs.PROCESS, Job.state == "done").order_by(Job.started_at, Job.id))
            order = [j.ref for j in started]
    # Lea's first, then Tom's although it came last, then Lea's again in the order they came.
    assert order == [first[0], theirs, first[1], first[2], first[3]]
