"""The text recognition in the worker, with ocrmypdf and Tesseract as the image carries them.

These tests need both programs and run where they are (the image; ``tools/test_in_image.sh``); elsewhere they are
skipped with that reason, and a skipped test is not a passed one."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.models import Account
from app.services import limits, ocr

from .conftest import DATA_DIR
from .files import make_pdf
from .intake import limit, process_all, sha, upload_one, version_of
from .invoices import joined_pdf, monthly_invoice, picture_bytes, scan_pdf, sheet

pytestmark = pytest.mark.skipif(not ocr.available(), reason="needs ocrmypdf and Tesseract (they are in the image; run "
                                                           "tools/test_in_image.sh)")

LINES = ["Kfz Versicherung Beitragsrechnung 2026", "Versicherungsnummer HV 778 120 33", "Jahresbeitrag 412,50 EUR",
         "Bitte ueberweisen Sie den Betrag bis zum 15.01.2026", "Hansa Versicherung, Lindenau"]


def text_of(client: TestClient, document_id: int) -> dict:
    return client.get(f"/api/v1/documents/{document_id}/versions/1/text").json()


def words_of(answer: dict) -> str:
    return " ".join(answer["pages"]).lower()


def test_a_skewed_noisy_scan_is_read_kept_searchable_and_the_original_stays(client: TestClient,
                                                                             operator: Account) -> None:
    scan = scan_pdf(sheet(LINES, angle=1.8, noise=6000, seed=4))
    made = upload_one(client, "Scan.pdf", scan)
    process_all()
    document = client.get(f"/api/v1/documents/{made['id']}").json()
    assert document["status"] == "inbox" and document["process_error"] == "" and document["pages"] == 1
    answer = text_of(client, made["id"])
    assert answer["state"] == "done" and answer["ocr_pages"] == 1 and answer["languages"] == "deu+eng"
    for word in ("versicherung", "beitragsrechnung", "jahresbeitrag", "412,50", "lindenau"):
        assert word in words_of(answer), word
    version = version_of(made["id"])
    # The original as it came; the searchable copy beside it.
    assert (Path(DATA_DIR) / "dokumente" / version.original_path).read_bytes() == scan and version.sha256 == sha(scan)
    assert version.archive_path.endswith("(searchable).pdf")
    archive = client.get(f"/api/v1/documents/{made['id']}/versions/1/archive")
    assert archive.status_code == 200 and archive.content.startswith(b"%PDF")
    hits = client.get("/api/v1/search", params={"q": "jahresbeitrag versicherung"}).json()
    assert hits["total"] == 1 and "Jahresbeitrag" in hits["items"][0]["excerpt"]["text"]
    events = client.get(f"/api/v1/documents/{made['id']}/events").json()
    processed = next(e for e in events if e["action"] == "processed")
    assert processed["detail"] == {"pages": 1, "text_pages": 1, "ocr_pages": 1}


def test_a_scan_with_a_trace_of_text_is_read_like_a_scan(client: TestClient, operator: Account) -> None:
    """A scanner that writes a page number ("3") as text onto its picture: the page is read all the same."""
    import io

    import pikepdf

    with pikepdf.open(io.BytesIO(joined_pdf(scan_pdf(sheet(LINES, angle=0.8, seed=7)), make_pdf(["3"])))) as pdf:
        pdf.pages[0].add_overlay(pdf.pages[1])
        del pdf.pages[1]
        out = io.BytesIO()
        pdf.save(out)
    made = upload_one(client, "Mit Seitenzahl.pdf", out.getvalue())
    process_all()
    answer = text_of(client, made["id"])
    assert answer["ocr_pages"] == 1 and "beitragsrechnung" in words_of(answer)
    assert version_of(made["id"]).archive_path.endswith("(searchable).pdf")


def test_a_pdf_with_text_is_not_recognised_again(client: TestClient, operator: Account) -> None:
    made = upload_one(client, "Brief.pdf", make_pdf(["Liebe Jule, der Zaehlerstand ist 4711. Viele Gruesse."]))
    process_all()
    answer = text_of(client, made["id"])
    assert answer["ocr_pages"] == 0 and "zaehlerstand ist 4711" in words_of(answer)
    assert version_of(made["id"]).archive_path == ""


def test_a_photo_becomes_a_searchable_pdf(client: TestClient, operator: Account) -> None:
    photo = picture_bytes(sheet(LINES, angle=-1.2, noise=4000, brightness=232, seed=5), "jpeg", 75)
    made = upload_one(client, "Foto.jpg", photo)
    process_all()
    answer = text_of(client, made["id"])
    assert answer["ocr_pages"] == 1 and "beitragsrechnung" in words_of(answer)
    archive = client.get(f"/api/v1/documents/{made['id']}/versions/1/archive").content
    import io

    import pypdfium2

    pdf = pypdfium2.PdfDocument(io.BytesIO(archive))
    assert "Beitragsrechnung" in pdf[0].get_textpage().get_text_bounded()


def test_a_mixed_pdf_keeps_its_text_and_has_the_scanned_page_read(client: TestClient, operator: Account) -> None:
    mixed = joined_pdf(make_pdf(["Seite eins mit eigenem Text Wasserzaehler"]), scan_pdf(sheet(LINES, angle=0.6)))
    made = upload_one(client, "Gemischt.pdf", mixed)
    process_all()
    answer = text_of(client, made["id"])
    assert answer["ocr_pages"] == 1 and len(answer["pages"]) == 2
    assert "wasserzaehler" in answer["pages"][0].lower() and "jahresbeitrag" in answer["pages"][1].lower()


def test_a_page_upside_down_is_turned_and_read(client: TestClient, operator: Account) -> None:
    made = upload_one(client, "Kopf.pdf", scan_pdf(sheet(LINES * 3, angle=180, seed=6)))
    process_all()
    assert "beitragsrechnung" in words_of(text_of(client, made["id"]))


def test_the_languages_of_the_settings_are_used(client: TestClient, operator: Account) -> None:
    assert client.put("/api/v1/settings/ocr", json={"languages": ["fra", "nld"]}).status_code == 200
    made = upload_one(client, "Facture.pdf", scan_pdf(sheet(["Facture numero 2026-17", "Montant total 99,00 EUR"])))
    process_all()
    answer = text_of(client, made["id"])
    assert answer["languages"] == "fra+nld" and "facture" in words_of(answer)


def tesseracts() -> int:
    """How many Tesseract processes run on this machine (read from /proc)."""
    count = 0
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                count += (entry / "comm").read_text(encoding="utf-8").strip() == "tesseract"
            except OSError:
                continue
    return count


def test_a_recognition_past_the_time_limit_is_stopped_with_tesseract_and_the_document_keeps_its_pages(
        client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    if not Path("/proc/self/comm").is_file():
        pytest.skip("counts processes in /proc (Linux)")
    monkeypatch.setitem(limits.RANGES, "process_timeout_seconds", (1, 86400))
    # One second for the whole document (not the ten seconds a page gets at least).
    monkeypatch.setattr(ocr, "PAGE_BUDGET", (0, 120))
    long_scan = scan_pdf(*[sheet(monthly_invoice(month), angle=0.5, noise=2000, seed=month) for month in range(1, 9)])
    made = upload_one(client, "Lang.pdf", long_scan)
    # Reading the file is quick; recognising eight pages is not done in one second.
    limit(process_timeout_seconds=1)
    began = time.monotonic()
    runner = threading.Thread(target=process_all, daemon=True)
    runner.start()
    runner.join(120)
    assert not runner.is_alive(), "the time limit was not applied"
    assert time.monotonic() - began < 120
    document = client.get(f"/api/v1/documents/{made['id']}").json()
    assert document["status"] == "inbox" and document["process_error"] == "ocr_timeout" and document["pages"] == 8
    assert client.get(f"/api/v1/documents/{made['id']}/versions/1/preview").status_code == 200
    time.sleep(1)
    assert tesseracts() == 0, "a Tesseract outlived the worker"
    # Nothing runs any more; trying again with time enough reads it.
    assert client.get("/api/v1/settings/ocr").json()["running"] == 0
    limit(process_timeout_seconds=600)
    assert client.post(f"/api/v1/documents/{made['id']}/retry").status_code == 200
    process_all()
    document = client.get(f"/api/v1/documents/{made['id']}").json()
    assert document["process_error"] == "" and text_of(client, made["id"])["ocr_pages"] == 8
