"""Blank separator pages: an empty sheet put between letters before a stack goes into the scanner marks where one letter
ends. Found while a document is read (a step of ``processing.STEPS``, only while the operator's switch "blank pages as
separators" is on), kept per version (``VersionInfo.blanks``), and offered in the inbox as a proposal to split
(``proposal``); a split drops them.

**How a page is judged** (``app/worker.py`` ``ink_ppm``, in the worker): the page drawn about 72 dots per inch wide, a
dot is ink when it is ``INK_STEP`` (60) grey levels darker than the paper, ink that reaches the edge of the picture in
one short run is the scanner (the wedges beside a slanted sheet, a black lid; a run longer than a tenth of the row or
column, a bar across the page or a ruled line, stays ink), a dot of ink counts only when two of its neighbours are ink
too (noise and dust do not), and the outer 1.5 % of each side is left out. The result is the ink in parts per million of
the area.

**The threshold** (``BLANK_PPM``), measured on the made-up scans of ``tests/scans.py`` (150 dpi, JPEG as scanners write
them): empty sheets with scanner noise up to a standard deviation of 14 levels, up to 40 specks of dust, a slant of 2.5
degrees with dark wedges, the other side shining through in grey 200 and above, tinted paper: **0** each. Nearly empty
sheets that are no separator: a back with only ``- 2 -`` in 9 point **27**, ``2`` in 10 point **42**, ``Seite 2 von 2``
in 8 point **242**, one short line **1129**, a page of text in grey 160 **6451** and in grey 170 **2564**, a faded
receipt in grey 160 **315**, a bar across the sheet **24742**, ruled paper **20819**; a letter about **50,000**. Specks
of dust larger than about 0.7 mm do count: such a sheet is taken for a page, which costs only a proposal not made (the
person cuts by hand), while a page taken for an empty one would lose a page. So the threshold sits low, at 12.

**Why 60 grey levels.** A series (ink of a page per step; text in grey 150/160/170/180, show-through
185/170): at 80 a page in grey 160 measured 0 (taken for empty), at 70 grey 170 still 0, at 60 grey 170 is found (835)
and the emptiest noisy sheet stays 0; at 50 noise begins to count (6), at 30 dust does. Still taken for empty: writing
paler than grey 180 and a yellow highlighter alone. Strong show-through (grey 185 and darker) counts as ink at 60: a
separator missed, which is the safe side.

**Duplex scans.** A stack scanned on both sides has the empty back of every one-sided letter as an empty page, and
always an even number of pages. When the number is even and every second page (2, 4, 6 ...) is empty, the empty backs
are taken for what they are: only an empty front (an odd page) cuts, and the empty pages all go when the stack is
split. A separator sheet scanned on both sides is two empty pages in a row: one cut. An odd number of pages is never
read as duplex: letters of one page with a separator between each (letter, separator, letter) split as they should.
Four pages with the second and fourth empty stay open to both readings (one letter of two sheets, or two letters):
nothing is proposed, the person cuts by hand.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Document, Version, VersionInfo
from . import filetypes, limits, ocr, storage

logger = logging.getLogger("nexpaper.separators")

#: A page with at most this much ink (parts per million of its area) is an empty sheet.
BLANK_PPM = 12


def blank_pages(ink: list[int]) -> list[int]:
    """The empty pages, counted from 1."""
    return [index + 1 for index, value in enumerate(ink) if int(value) <= BLANK_PPM]


@dataclass
class Proposal:
    #: The documents the stack would become, each a list of its pages (counted from 1).
    parts: list[list[int]] = field(default_factory=list)
    #: The empty pages that would go.
    separators: list[int] = field(default_factory=list)
    #: Every second page is empty: a stack scanned on both sides.
    duplex: bool = False


def proposal(pages: int, blanks: list[int]) -> Proposal:
    """How a stack of ``pages`` with these empty pages would be split. Fewer than two parts: no proposal (``parts``
    empty), though the empty pages are still named."""
    empty = {page for page in blanks if 1 <= page <= pages}
    if not empty or pages < 3:
        return Proposal(parts=[], separators=sorted(empty))
    evens = set(range(2, pages + 1, 2))
    duplex = pages >= 4 and pages % 2 == 0 and evens <= empty
    parts: list[list[int]] = []
    current: list[int] = []
    for page in range(1, pages + 1):
        if page in empty:
            # On both sides: the empty back of a page cuts nothing, an empty front (a separator sheet) does.
            if (not duplex or page % 2 == 1) and current:
                parts.append(current)
                current = []
            continue
        current.append(page)
    if current:
        parts.append(current)
    return Proposal(parts=parts if len(parts) >= 2 else [], separators=sorted(empty), duplex=duplex)


# --- The step while a document is read --------------------------------------------------------------------------------


def find_blanks(db: Session, document: Document, version: Version, run: Any) -> Any:
    """The step of ``processing.STEPS`` that measures the ink of every page, while the operator's switch is on and the
    document has more than one page. It never fails the document: when it does not work out, nothing is proposed."""
    from . import processing

    if not ocr.current(db).blank_pages:
        return processing.Outcome(True)
    count = int(run.data.get("pages") or 0)
    kind = filetypes.KIND_OF_EXTENSION.get(Path(version.original_path).suffix.lower())
    if count < 2 or kind in (None, filetypes.XML):
        return processing.Outcome(True)
    try:
        pdf = run.source or (run.work if run.data.get("derived") else storage.safe_path(version.original_path))
    except storage.StorageError:
        return processing.Outcome(True)
    current = limits.current(db)
    request = {"op": "blanks", "pdf": str(pdf), "max_pages": current.max_pages, "memory_mb": current.memory_mb,
               "render_pixels": limits.MAX_RENDER_PIXELS}
    db.rollback()
    outcome = processing.spawn(request, current.timeout_seconds)
    if not outcome.ok:
        logger.info("Blank pages not measured document_id=%s error=%s", document.id, outcome.error)
        return processing.Outcome(True)
    ink = outcome.data.get("ink")
    if not isinstance(ink, list) or len(ink) != count or not all(isinstance(value, int) for value in ink):
        return processing.Outcome(True)
    return processing.Outcome(True, data={"ink": ink})


def keep_blanks(db: Session, document: Document, version: Version, data: dict[str, Any]) -> None:
    """Called by ``processing._finish`` under the write lock: the empty pages the step found, on the version."""
    ink = data.get("ink")
    if not isinstance(ink, list):
        return
    info = info_of(db, version)
    info.blanks = blank_pages(ink)
    info.split_dismissed = False


def info_of(db: Session, version: Version) -> VersionInfo:
    """The row of a version, made when it has none (an ordinary ready version)."""
    info = db.get(VersionInfo, version.id)
    if info is None:
        info = VersionInfo(version_id=version.id, document_id=version.document_id, origin="", state="ready", error="",
                           split_dismissed=False)
        db.add(info)
    return info


# --- Documents read before (the job ``blanks``) ----------------------------------------------------------------------

#: The job that measures the blank pages of a document that was read without it (``services/jobs.py``).
JOB = "blanks"


def queue_missing(db: Session) -> int:
    """A job ``blanks`` for every document in the inbox of three pages or more whose current version was never looked
    at (read before this block, or while the switch was off). Only the inbox: a proposal to split is made there, and it
    holds few documents, so an upgrade does not read the whole archive again. Run at the start and when the operator
    turns the switch on. Returns how many."""
    from . import jobs

    if not ocr.current(db).blank_pages:
        db.rollback()
        return 0
    rows = db.execute(
        select(Document.id, VersionInfo.blanks)
        .join(Version, (Version.document_id == Document.id) & (Version.n == Document.current_version))
        .outerjoin(VersionInfo, VersionInfo.version_id == Version.id)
        .where(Document.status == "inbox", Document.pages >= 3)
    ).all()
    missing = [document_id for document_id, blanks in rows if not isinstance(blanks, list)]
    for document_id in missing:
        jobs.enqueue(db, JOB, document_id)
    db.commit()
    return len(missing)


def run_job(db: Session, document_id: int) -> None:
    """The job ``blanks``: the ink of every page of the current version, kept as with a document that is read. A
    document that left the inbox, changed version or was looked at meanwhile is left alone; a run that fails proposes
    nothing (it is not tried again)."""
    from . import changes, pagetools, processing

    document = db.get(Document, document_id)
    if document is None or document.status != "inbox" or not ocr.current(db).blank_pages:
        db.rollback()
        return
    version = pagetools.current_version(db, document)
    info = db.get(VersionInfo, version.id)
    if info is not None and isinstance(info.blanks, list):
        db.rollback()
        return
    try:
        pdf = pagetools.best_pdf(version)
    except Exception:  # noqa: BLE001 - no pages (an e-invoice as XML): nothing to look at
        db.rollback()
        return
    current = limits.current(db)
    version_id, count = version.id, version.pages
    request = {"op": "blanks", "pdf": str(pdf), "max_pages": current.max_pages, "memory_mb": current.memory_mb,
               "render_pixels": limits.MAX_RENDER_PIXELS}
    db.rollback()
    outcome = processing.spawn(request, current.timeout_seconds)
    ink = outcome.data.get("ink") if outcome.ok else None
    if not isinstance(ink, list) or len(ink) != count:
        logger.info("Blank pages not measured document_id=%s error=%s", document_id, outcome.error)
        return
    changes.write_lock(db)
    document = db.get(Document, document_id)
    version = db.get(Version, version_id)
    if document is None or version is None or document.current_version != version.n:
        db.rollback()
        return
    row = info_of(db, version)
    if isinstance(row.blanks, list):
        db.rollback()
        return
    row.blanks = blank_pages(ink)
    # The list shows whether a split is proposed: the document takes a new number for the change feed.
    document.change_seq = changes.next_seq(db)
    db.commit()


def suggested(db: Session, documents: list[Document]) -> set[int]:
    """The documents of the list (in the inbox) for which a split is proposed: their current version has empty pages
    that make two documents or more, and nobody said to keep it as one."""
    waiting = [d for d in documents if d.status == "inbox" and d.pages >= 3]
    if not waiting:
        return set()
    wanted = {(d.id, d.current_version): d for d in waiting}
    rows = db.execute(
        select(Version.document_id, Version.n, VersionInfo.blanks)
        .join(VersionInfo, VersionInfo.version_id == Version.id)
        .where(Version.document_id.in_([d.id for d in waiting]), VersionInfo.split_dismissed.is_(False))
    ).all()
    out = set()
    for document_id, n, blanks in rows:
        document = wanted.get((document_id, n))
        if document is not None and isinstance(blanks, list) and proposal(document.pages, blanks).parts:
            out.add(document_id)
    return out


__all__ = ["BLANK_PPM", "Proposal", "blank_pages", "find_blanks", "info_of", "keep_blanks", "proposal", "suggested"]
