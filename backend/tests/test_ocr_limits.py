"""The settings and limits of the text recognition, and the worker's text step where no recognition is needed or none is
installed (these run everywhere; the recognition itself is in ``test_ocr.py``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import worker
from app.db import SessionLocal
from app.services import ocr, settings_service

from .files import make_pdf
from .invoices import scan_pdf, sheet


def test_the_time_limit_follows_the_pages_the_pace_and_the_ceiling() -> None:
    # Nothing read yet: the operator's limit per ten pages, at least the limit for one document.
    assert ocr.time_limit(300, 0) == 300
    assert ocr.time_limit(300, 1) == 300
    assert ocr.time_limit(300, 10) == 300
    assert ocr.time_limit(300, 11) == 330
    # Within the bounds per page (10 to 120 seconds).
    assert ocr.time_limit(60, 95) == 950
    assert ocr.time_limit(6000, 95, ceiling=86400) == 11400
    # Once pages were read: ten times their average, so a document far slower than the others is stopped.
    assert ocr.time_limit(300, 100, pace=2.5) == 2500
    assert ocr.time_limit(300, 10, pace=2.5) == 300
    # Never past the ceiling, however many pages: 2000 pages do not hold the queue for 16 hours.
    assert ocr.time_limit(300, 2000) == 3600
    assert ocr.time_limit(300, 2000, ceiling=7200, pace=50) == 7200


def test_settings_out_of_range_in_the_database_are_pulled_back() -> None:
    with SessionLocal() as db:
        assert ocr.current(db).max_seconds == 3600
        settings_service.save(db, {"ocr_languages": ["xx", "tur", "deu"], "ocr_jobs": 99, "ocr_straighten": False,
                                   "ocr_max_seconds": 10})
        current = ocr.current(db)
        assert current.languages == ["deu", "tur"] and current.jobs == 4 and current.straighten is False
        assert current.max_seconds == 60
        settings_service.save(db, {"ocr_languages": "deu", "ocr_jobs": "x", "ocr_max_seconds": "y"})
        current = ocr.current(db)
        assert current.languages == ["deu", "eng"] and current.jobs == 1 and current.max_seconds == 3600


def _recognize(tmp_path: Path, pdf: bytes, **extra: object) -> tuple[dict, list[str]]:
    source = tmp_path / "in.pdf"
    source.write_bytes(pdf)
    request = {"op": "recognize", "pdf": str(source), "out": str(tmp_path / "out.pdf"),
               "text_out": str(tmp_path / "text.json"), "languages": ["deu"], **extra}
    answer = worker.recognize(request)
    return answer, json.loads((tmp_path / "text.json").read_text(encoding="utf-8"))


def test_a_pdf_with_text_on_every_page_needs_no_recognition(tmp_path: Path) -> None:
    answer, texts = _recognize(tmp_path, make_pdf(["Seite eins\nmit Text, der lang genug ist", ("Seite zwei mit "
                                                   "Text, der auch lang genug ist")]))
    assert answer == {"ok": True, "pages": 2, "ocr_pages": 0, "archive": False, "languages": "", "ocr": "not_needed"}
    assert texts[0].startswith("Seite eins") and "mit Text" in texts[0] and texts[1].startswith("Seite zwei")
    assert not (tmp_path / "out.pdf").exists()


def test_the_text_is_cut_at_the_limit_of_characters(tmp_path: Path) -> None:
    _answer, texts = _recognize(tmp_path, make_pdf(["a" * 40, "b" * 40, "c" * 40]), max_chars=60)
    assert [text.strip() for text in texts] == ["a" * 40, "b" * 20, ""]


def test_too_many_pages_are_refused(tmp_path: Path) -> None:
    with pytest.raises(worker.Refused) as refused:
        _recognize(tmp_path, make_pdf(["eins", "zwei", "drei"]), max_pages=2)
    assert refused.value.code == "too_many_pages"


def test_a_page_with_only_a_trace_of_text_counts_as_a_scan(tmp_path: Path) -> None:
    """A scanner that writes "3" or "Seite 1 von 3" as text onto its picture: under ``MIN_PAGE_CHARACTERS`` letters
    and digits the page is read like a scan (here without the recognition: it is asked for, not skipped)."""
    import io

    from .invoices import joined_pdf

    traced = joined_pdf(scan_pdf(sheet(["Ein Blatt ohne Textschicht"])), make_pdf(["3"]))
    import pikepdf

    with pikepdf.open(io.BytesIO(traced)) as pdf:
        # The "3" laid over the picture of the scan, as one page.
        pdf.pages[0].add_overlay(pdf.pages[1])
        del pdf.pages[1]
        out = io.BytesIO()
        pdf.save(out)
    answer, texts = _recognize(tmp_path, out.getvalue())
    # Read like a scan: with the recognition the words of the picture come in, without it the "3" stays all there is.
    assert ("Blatt" in texts[0]) if ocr.available() else texts[0].strip() == "3"
    assert answer["ocr"] != "not_needed"
    assert worker.MIN_PAGE_CHARACTERS == 30
    _answer, texts = _recognize(tmp_path, make_pdf(["Seite 1 von 3"]))
    assert _answer["ocr"] != "not_needed"


@pytest.mark.skipif(ocr.available(), reason="describes a machine without the recognition")
def test_without_the_recognition_a_scan_keeps_its_pages_without_text(tmp_path: Path) -> None:
    answer, texts = _recognize(tmp_path, scan_pdf(sheet(["Ein Blatt ohne Textschicht"])))
    assert answer["ocr"] == "unavailable" and answer["archive"] is False and texts == [""]
