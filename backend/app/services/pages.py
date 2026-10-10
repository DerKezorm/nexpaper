"""The pictures of a document: the preview and the pages, kept in the cache.

    <data>/cache/pages/<document id>/v<version>-thumb.webp
    <data>/cache/pages/<document id>/v<version>-p<page>-<size>.webp

The cache holds nothing that cannot be made again from the files, so it can be emptied at any time (a backup need not
carry it). The preview of a new document is made by the worker as part of reading it; every other picture is made when
somebody asks for it first, by a worker process too (a PDF is never drawn inside the server), and kept. The path is
built from numbers the server holds, never from anything a request says. Each version of a document has pictures of
its own and so an address of its own: a new version never shows an old picture from a cache.

Two sizes of a page: ``small`` (720 pixels wide, for the strip of pages and the page of a link) and ``large`` (1600, for
reading). The preview is the first page at 360 pixels.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import threading
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import error
from ..models import Document, Version
from . import filetypes, limits, storage

logger = logging.getLogger("nexpaper.pages")

WIDTHS = {"thumb": 360, "small": 720, "large": 1600}
SIZES = ("small", "large")
_drawing = threading.Lock()
_slots: threading.BoundedSemaphore | None = None
#: How long a request waits for a free place to draw a page before the server says it is busy.
WAIT_SECONDS = 1.5
#: Pages one person, or one link, may have in the making at the same moment.
PER_PRINCIPAL = 2
#: A document of up to this many pages has its preview and its small pages drawn by the worker that reads it.
PRERENDER_PAGES = 30
#: A longer one has its small pages drawn in the background afterwards (job ``pages``), this many in one run of the
#: worker; between two runs a document that waits to be read goes first.
BACKGROUND_BATCH = 20
_active: dict[str, int] = {}


def cache_root() -> Path:
    return get_settings().data_dir / "cache" / "pages"


def document_dir(document_id: int) -> Path:
    return cache_root() / str(int(document_id))


def thumb_path(document_id: int, version: int) -> Path:
    return document_dir(document_id) / f"v{int(version)}-thumb.webp"


def page_path(document_id: int, version: int, page: int, size: str) -> Path:
    if size not in SIZES:
        raise ValueError("size")
    return document_dir(document_id) / f"v{int(version)}-p{int(page)}-{size}.webp"


def remove(document_id: int) -> None:
    """All pictures of a document."""
    shutil.rmtree(document_dir(document_id), ignore_errors=True)


def trim(max_bytes: int) -> int:
    """Keeps the cache within ``max_bytes``: when it is larger, the pictures used longest ago go until it is at nine
    tenths of it. They are made again when somebody asks. Returns how many files went."""
    root = cache_root()
    if not root.is_dir() or max_bytes <= 0:
        return 0
    entries: list[tuple[float, int, Path]] = []
    total = 0
    for path in root.rglob("*.webp"):
        try:
            info = path.stat()
        except OSError:
            continue
        entries.append((info.st_mtime, info.st_size, path))
        total += info.st_size
    if total <= max_bytes:
        return 0
    entries.sort(key=lambda entry: entry[0])
    removed = 0
    for _moment, size, path in entries:
        if total <= max_bytes * 0.9:
            break
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        removed += 1
    logger.info("Page cache trimmed files=%s", removed)
    return removed


def remove_version(document_id: int, version: int) -> None:
    folder = document_dir(document_id)
    if not folder.is_dir():
        return
    for path in folder.glob(f"v{int(version)}-*"):
        path.unlink(missing_ok=True)


def source_pdf(version: Version) -> Path | None:
    """The PDF the pictures are drawn from: the file itself when it is a PDF, else the PDF made from the picture. None
    for a file without pages (an e-invoice as XML) or when it is gone from the disk."""
    for rel in (version.archive_path, version.original_path):
        if not rel or Path(rel).suffix.lower() != ".pdf":
            continue
        try:
            path = storage.safe_path(rel)
        except storage.StorageError:
            continue
        if path.is_file():
            return path
    return None


def _semaphore() -> threading.BoundedSemaphore:
    global _slots
    with _drawing:
        if _slots is None:
            _slots = threading.BoundedSemaphore(max(1, min(int(get_settings().decode_slots), 16)))
        return _slots


def current_version(db: Session, document: Document, number: int | None = None) -> Version:
    n = document.current_version if number is None else number
    version = db.scalar(select(Version).where(Version.document_id == document.id, Version.n == n))
    if version is None:
        raise error("not_found", "Not found.", 404)
    return version


def _enter(principal: str) -> None:
    """One person (or one link) draws at most ``PER_PRINCIPAL`` pages at a time: a flood of requests for pages that are
    not in the cache yet, from an account or from anybody who has an address, cannot take every place."""
    from .pictures import DecodersBusy

    with _drawing:
        if _active.get(principal, 0) >= PER_PRINCIPAL:
            raise DecodersBusy
        _active[principal] = _active.get(principal, 0) + 1


def _leave(principal: str) -> None:
    with _drawing:
        left = _active.get(principal, 1) - 1
        if left <= 0:
            _active.pop(principal, None)
        else:
            _active[principal] = left


def ensure(db: Session, document: Document, version: Version, page: int | None, size: str,
           principal: str = "-") -> Path:
    """The picture file of a page (``page`` 1-based; ``None``: the preview), drawn now if the cache does not have it.
    The errors are the interface's own: 404 for a page the document does not have or a file that has none, 409 while the
    document is still being read, 503 with ``Retry-After`` when the server is drawing as many pages as it is allowed to
    (it does not make a request wait for long: a thread of the pool is not kept for a queue) or the same person or link
    already has ``PER_PRINCIPAL`` of them going."""
    from . import processing

    if document.status == "processing":
        raise error("not_ready", "The document is still being read.", 409)
    kind = filetypes.KIND_OF_EXTENSION.get(Path(version.original_path).suffix.lower())
    # An e-invoice that is XML only has pages once nexpaper set its readable copy (B6).
    if version.pages < 1 or (kind == filetypes.XML and not version.archive_path):
        raise error("not_found", "Not found.", 404)
    if page is not None and not 1 <= page <= version.pages:
        raise error("not_found", "Not found.", 404)
    target = thumb_path(document.id, version.n) if page is None else page_path(document.id, version.n, page, size)
    if target.is_file():
        with contextlib.suppress(OSError):
            os.utime(target)  # used just now: the cache clears what was used longest ago
        return target
    source = source_pdf(version)
    if source is None:
        raise error("not_found", "Not found.", 404)
    width = WIDTHS["thumb"] if page is None else WIDTHS[size]
    current = limits.current(db)
    db.rollback()  # no transaction stays open while a page is drawn
    _enter(principal)
    gate = _semaphore()
    if not gate.acquire(timeout=WAIT_SECONDS):
        _leave(principal)
        from .pictures import DecodersBusy

        raise DecodersBusy
    try:
        if target.is_file():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        outcome = processing.spawn({
            "op": "render", "pdf": str(source), "page": (page or 1) - 1, "width": width, "out": str(target),
            "memory_mb": current.memory_mb, "render_pixels": limits.MAX_RENDER_PIXELS,
        }, processing.RENDER_SECONDS)
    finally:
        gate.release()
        _leave(principal)
    if not outcome.ok or not target.is_file():
        logger.info("A page could not be drawn document_id=%s error=%s", document.id, outcome.error)
        raise error("render_failed", "This page could not be drawn.", 422)
    return target


def queue_background(db: Session, document_id: int, version: int, count: int) -> None:
    """After a document was read (in the caller's transaction): its small pages are drawn in the background when the
    worker did not draw them (more than ``PRERENDER_PAGES``). How many is the operator's limit, read when the job
    runs."""
    from . import jobs

    if count > PRERENDER_PAGES:
        jobs.enqueue(db, jobs.PAGES, document_id, {"version": int(version), "next": 1})


def draw_in_background(db: Session, document_id: int, payload: object) -> None:
    """The job ``pages``: the next ``BACKGROUND_BATCH`` small pictures of the current version of a document, up to the
    operator's limit (``prerender_max_pages``), in a worker process at a low priority; a job for the rest follows. The
    loop that runs it takes it only when no document waits to be read (``jobs._claim``). Pages that are in the cache
    already are left alone; one that does not draw is drawn (or refused) when somebody asks for it."""
    from . import jobs, processing

    document = db.get(Document, document_id)
    if document is None or document.status in ("processing", "trash"):
        db.rollback()
        return
    version = db.scalar(select(Version).where(Version.document_id == document.id,
                                              Version.n == document.current_version))
    kind = filetypes.KIND_OF_EXTENSION.get(Path(version.original_path).suffix.lower()) if version else None
    if version is None or (kind == filetypes.XML and not version.archive_path):
        db.rollback()
        return
    data = payload if isinstance(payload, dict) else {}
    # A job queued for an earlier version starts the current one from its first page.
    first = max(1, int(data.get("next") or 1)) if data.get("version") == version.n else 1
    current = limits.current(db)
    last = min(version.pages, current.prerender_pages, first + BACKGROUND_BATCH - 1)
    source = source_pdf(version)
    if first > last or source is None:
        db.rollback()
        return
    number, cap = version.n, min(version.pages, current.prerender_pages)
    db.rollback()  # no transaction stays open while the worker draws
    outcome = processing.spawn({
        "op": "render_pages", "pdf": str(source), "first": first, "last": last,
        "pattern": str(document_dir(document_id) / f"v{number}-p{{page}}-small.webp"), "width": WIDTHS["small"],
        "memory_mb": current.memory_mb, "render_pixels": limits.MAX_RENDER_PIXELS,
    }, current.timeout_seconds)
    if not outcome.ok:
        logger.info("Pages were not drawn in the background document_id=%s error=%s", document_id, outcome.error)
        return
    if last < cap:
        jobs.enqueue(db, jobs.PAGES, document_id, {"version": number, "next": last + 1})
        db.commit()
