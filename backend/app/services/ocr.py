"""The settings of the text recognition (Settings, Storage, card "Text recognition") and what the server can do.

The image carries Tesseract with six languages (``LANGUAGES``) and nothing is loaded at run time: the operator picks
among them. Straightening (``--deskew --rotate-pages``) is a switch. The switch for blank separator pages is kept here
and shown, but only the page tools act on it.

On a machine without ocrmypdf or Tesseract (a development machine under Windows) every document is read as before and
only the text a PDF carries itself is found; ``available`` says so, and the card shows it.
"""

from __future__ import annotations

import importlib.util
import logging
import math
import shutil
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Document, Job
from . import settings_service

logger = logging.getLogger("nexpaper.ocr")

#: The languages in the image, in the order the card shows them.
LANGUAGES = ("deu", "eng", "fra", "nld", "pol", "tur")
DEFAULT_LANGUAGES = ["deu", "eng"]
#: How many pages ocrmypdf works on at once. One keeps a small server responsive.
JOBS_RANGE = (1, 4)
#: The operator's time limit counts per this many pages for the recognition when nothing was read yet (a scan of 40
#: pages takes four times as long as one of 10).
PAGES_PER_LIMIT = 10
#: Once pages were read, one page may take this many times the average of the last documents, within these bounds
#: (seconds): a document that is far slower than the others is stopped instead of holding up the queue for hours.
PACE_FACTOR = 10
PAGE_BUDGET = (10, 120)
#: However many pages: the recognition of one document never takes longer than the operator's ceiling (seconds; the
#: setting ``ocr_max_seconds``, one hour from the start).
MAX_SECONDS_RANGE = (60, 86400)
#: From this many pages the inbox says that the text will take a while.
LONG_DOCUMENT_PAGES = 300
#: Most seconds Tesseract may take for one page; a page that takes longer stays without text.
PAGE_SECONDS = 120
#: Most characters of text kept for one document.
MAX_CHARS = 2_000_000


@dataclass(frozen=True)
class OcrSettings:
    languages: list[str]
    straighten: bool
    blank_pages: bool
    jobs: int
    #: The ceiling for one document, in seconds.
    max_seconds: int


def current(db: Session) -> OcrSettings:
    """The settings, a value the database holds that is out of range pulled back into it."""
    raw = settings_service.get(db, "ocr_languages")
    languages = [code for code in LANGUAGES if isinstance(raw, list) and code in raw] or list(DEFAULT_LANGUAGES)
    try:
        jobs = int(settings_service.get(db, "ocr_jobs"))
    except (TypeError, ValueError):
        jobs = 1
    try:
        ceiling = int(settings_service.get(db, "ocr_max_seconds"))
    except (TypeError, ValueError):
        ceiling = int(settings_service.DEFAULTS["ocr_max_seconds"])
    return OcrSettings(
        languages=languages,
        straighten=bool(settings_service.get(db, "ocr_straighten")),
        blank_pages=bool(settings_service.get(db, "ocr_blank_pages")),
        jobs=min(max(jobs, JOBS_RANGE[0]), JOBS_RANGE[1]),
        max_seconds=min(max(ceiling, MAX_SECONDS_RANGE[0]), MAX_SECONDS_RANGE[1]),
    )


def time_limit(seconds: int, pages: int, ceiling: int = 3600, pace: float | None = None) -> int:
    """The time the recognition of a document of ``pages`` pages may take. Per page: ``PACE_FACTOR`` times the average
    of the last documents (``pace``, seconds per page), or the operator's limit per ``PAGES_PER_LIMIT`` pages while
    there is none, within ``PAGE_BUDGET``; at least the operator's limit for one document, at most ``ceiling``."""
    per_page = pace * PACE_FACTOR if pace else seconds / PAGES_PER_LIMIT
    per_page = min(max(per_page, PAGE_BUDGET[0]), PAGE_BUDGET[1])
    return int(min(ceiling, max(seconds, math.ceil(max(pages, 1) * per_page))))


def available() -> bool:
    """Whether this server can recognise text: ocrmypdf importable and Tesseract on the path."""
    return importlib.util.find_spec("ocrmypdf") is not None and shutil.which("tesseract") is not None


def seconds_per_page(db: Session, last: int = 20) -> float | None:
    """How long reading a document took per page, over the last documents read (the whole run: file, pictures, text).
    Nothing until something was read."""
    rows = db.execute(
        select(Job.started_at, Job.finished_at, Document.pages).join(Document, Document.id == Job.ref)
        .where(Job.kind == "process", Job.state == "done", Job.started_at.is_not(None), Job.finished_at.is_not(None),
               Document.pages > 0)
        .order_by(Job.id.desc()).limit(last)
    ).all()
    spans = [((finished - started).total_seconds(), pages) for started, finished, pages in rows if finished >= started]
    pages = sum(count for _seconds, count in spans)
    if not pages:
        return None
    return round(sum(seconds for seconds, _count in spans) / pages, 1)


__all__ = ["DEFAULT_LANGUAGES", "LANGUAGES", "MAX_CHARS", "PAGE_SECONDS", "OcrSettings", "available", "current",
           "seconds_per_page", "time_limit"]
