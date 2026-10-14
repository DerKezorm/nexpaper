"""The page tools: turning, deleting and ordering pages, joining documents, splitting one, the versions of a document.

**Nothing is overwritten.** Every tool makes a new version (``n + 1``) or new documents; the file as it came, and every
version before, stay as they are with their checksums. A document that is joined into another or split goes to the
trash (restorable for 30 days).

**The worker does the PDF work** (``app/worker.py`` ``assemble``, pikepdf, in a process of its own with the operator's
time and memory limits): the pages are taken from the PDF a version has (its searchable copy when there is one, so the
text the recognition put in goes along), turned as asked, written to new files, and their preview and small pages drawn.
No page is read again: the text of each page goes along from ``version_texts``.

**One moment for the check and the write.** The rights, the state of the document and the version it stands at are
checked when the request comes and again under the write lock, in the transaction that writes the new version. A
request names the version it was made for (``base_version``): when another change came first (a double click, a second
person), it answers ``409 version_changed`` and leaves nothing behind. While a new version that was uploaded is being
read, the tools wait (``409 version_pending``).

**Names on the disk.** A new version is put under a name of its own (``... (version n).pdf``) and the ``rename`` job
gives it the plain name of the current version, after the version before has moved to its own
(``storage.plan``).

**Rights.** ``edit`` on every document involved (through its vault or a share). Making documents (a split) and taking in
the pages of others (joining) needs ``edit`` in the vault itself, as moving a document does.
"""

from __future__ import annotations

import contextlib
import logging
import os
import secrets
import shutil
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import error
from ..models import (
    EDIT,
    FILED,
    INBOX,
    PROCESSING,
    TRASH,
    Document,
    DocumentTag,
    Job,
    Note,
    Tag,
    Version,
    VersionInfo,
    VersionText,
)
from . import catalog, changes, documents, filecheck, filetypes, jobs, limits, pages, rights, separators, storage

logger = logging.getLogger("nexpaper.pagetools")

TURNS = (0, 90, 180, 270)
#: The most a person may say about a version (``Version.note``).
NOTE_MAX = 200
#: The control characters a note may hold (they become blanks).
WHITE = "\t\r\n"
#: Documents joined in one go, and parts one document is split into.
MAX_MERGE = 20
MAX_PARTS = 100
# How a version came about (``VersionInfo.origin``, also ``Version.note``).
PAGES, MERGED, SPLIT, RESTORED, UPLOADED = "pages", "merged", "split", "restored", "uploaded"
# Whether it is read yet.
READY, PENDING, FAILED = "ready", "processing", "failed"
# What the history says.
PAGES_EDITED = "pages_edited"
MERGED_FROM, MERGED_INTO = "merged", "merged_into"
SPLIT_INTO = "split"
VERSION_RESTORED = "version_restored"
VERSION_UPLOADED, VERSION_ADDED, VERSION_FAILED = "version_uploaded", "version_added", "version_failed"
SPLIT_KEPT = "split_kept"
#: Runs of the worker for the page tools at the same moment (each person one at a time), and how long a request waits
#: for a place before the server says it is busy.
SLOTS = 2
WAIT_SECONDS = 2.0

#: How long a tool waits for the files of a document while the ``rename`` job moves them.
FILES_WAIT = 10.0

_gate = threading.BoundedSemaphore(SLOTS)
_busy: set[int] = set()
_busy_lock = threading.Lock()


def _busy_error(code: str = "busy", text: str = "The server is busy. Try again in a moment.") -> Exception:
    exc = error(code, text, 503)
    exc.headers = {"Retry-After": "5"}  # type: ignore[attr-defined]
    return exc


@contextlib.contextmanager
def _files(document_ids: list[int]) -> Iterator[None]:
    """The files of these documents to this tool alone, from reading their paths to writing the new version: the
    ``rename`` job waits meanwhile (``storage.files_of``), so no file moves away under a tool."""
    try:
        lock = storage.files_of(list(document_ids), FILES_WAIT)
        lock.__enter__()
    except storage.DocumentBusy:
        raise _busy_error() from None
    try:
        yield
    finally:
        lock.__exit__()


def _verify(path: Path, sha256: str) -> None:
    """The file is the one the version names (its checksum), else ``409 try_again`` and nothing is made."""
    if sha256 and storage.sha256_of(path) != sha256:
        logger.warning("A file did not have the checksum of its version")
        raise error("try_again", "The files of this document changed in the meantime. Try again.", 409)


@contextlib.contextmanager
def _slot(uid: int) -> Iterator[None]:
    """A place to run the worker: ``SLOTS`` for the server and one per person; else ``503 busy`` at once."""
    from .pictures import DecodersBusy

    with _busy_lock:
        if uid in _busy:
            raise DecodersBusy
        _busy.add(uid)
    try:
        if not _gate.acquire(timeout=WAIT_SECONDS):
            raise DecodersBusy
        try:
            yield
        finally:
            _gate.release()
    finally:
        with _busy_lock:
            _busy.discard(uid)


# --- Looking ----------------------------------------------------------------------------------------------------------


def current_version(db: Session, document: Document) -> Version:
    version = db.scalar(select(Version).where(Version.document_id == document.id,
                                              Version.n == document.current_version))
    if version is None:
        raise error("not_found", "Not found.", 404)
    return version


def _live_job() -> Any:
    return select(Job.id).where(Job.kind == jobs.VERSION, Job.ref == VersionInfo.version_id,
                                Job.state.in_(("queued", "running"))).exists()


def pending(db: Session, document_id: int) -> bool:
    """A new version that was uploaded is being read: it waits for the worker or is in it. One whose job ended without
    marking it (it should not happen) does not hold the document."""
    return bool(db.scalar(select(func.count()).select_from(VersionInfo).where(
        VersionInfo.document_id == document_id, VersionInfo.state == PENDING, _live_job())))


def stalled(db: Session, version_ids: list[int]) -> set[int]:
    """Versions marked as being read whose job is gone: they count as failed."""
    if not version_ids:
        return set()
    return set(db.scalars(select(VersionInfo.version_id).where(
        VersionInfo.version_id.in_(version_ids), VersionInfo.state == PENDING, ~_live_job())))


def infos(db: Session, version_ids: list[int]) -> dict[int, VersionInfo]:
    if not version_ids:
        return {}
    rows = db.scalars(select(VersionInfo).where(VersionInfo.version_id.in_(version_ids)))
    return {row.version_id: row for row in rows}


def check(db: Session, uid: int, document_id: int, base_version: int | None, *, vault: bool = False) -> rights.Access:
    """The caller may change the document and it stands where the caller saw it: ``edit`` (``vault``: in the vault
    itself), not in the trash, read, at ``base_version``, with no new version being read."""
    access = rights.require_document(db, uid, document_id, EDIT)
    document = access.document
    if vault and not rights.at_least(access.vault, EDIT):
        # Seen through a share: the document may be changed, but nothing may be made in or taken into its vault.
        raise rights.forbidden()
    if document.status == TRASH:
        raise error("in_trash", "Restore the document first.", 409)
    if document.status == PROCESSING:
        raise error("not_ready", "The document is still being read.", 409)
    if base_version is not None and base_version != document.current_version:
        raise error("version_changed", "The document has changed in the meantime. Look at it again.", 409,
                    current_version=document.current_version)
    if pending(db, document.id):
        raise error("version_pending", "A new version of this document is still being read.", 409)
    return access


def _pdfs(version: Version) -> tuple[Path | None, Path | None]:
    """The original when it is a PDF, and the searchable copy (or the PDF made from a picture), when they are there."""
    found: list[Path | None] = []
    for rel, must_be_pdf in ((version.original_path, True), (version.archive_path, False)):
        path = None
        if rel and (not must_be_pdf or Path(rel).suffix.lower() == ".pdf"):
            try:
                candidate = storage.safe_path(rel)
            except storage.StorageError:
                candidate = None
            if candidate is not None and candidate.is_file():
                path = candidate
        found.append(path)
    return found[0], found[1]


def best_pdf(version: Version) -> Path:
    """The PDF whose pages the tools take: the searchable copy, else the original. An e-invoice as XML has its
    readable sheet as its searchable copy."""
    original, archive = _pdfs(version)
    found = archive or original
    if found is None or version.pages < 1:
        raise error("no_pages", "This document has no pages to work with.", 422)
    return found


def texts_of(db: Session, version: Version) -> VersionText | None:
    row = db.get(VersionText, version.id)
    if row is None or len(row.text.split("\f")) != version.pages:
        return None
    return row


def _pages_of(row: VersionText | None) -> list[str] | None:
    return None if row is None else row.text.split("\f")


def _validate(specs: list[tuple[int, int]], pages_count: int) -> None:
    if not specs:
        raise error("invalid_pages", "Keep at least one page.", 422)
    if len(specs) > pages_count:
        raise error("invalid_pages", "A page can be used only once.", 422)
    seen: set[int] = set()
    for page, turn in specs:
        if not 1 <= page <= pages_count:
            raise error("invalid_pages", "This document has no such page.", 422)
        if turn not in TURNS:
            raise error("invalid_pages", "A page turns by 0, 90, 180 or 270 degrees.", 422)
        if page in seen:
            raise error("invalid_pages", "A page can be used only once.", 422)
        seen.add(page)


# --- Making the files -------------------------------------------------------------------------------------------------


@dataclass
class Made:
    """What the worker made for one new version: the file, the searchable copy beside it (or none), the pictures in a
    folder of their own (moved to the cache once the version is written), and what it found."""

    file: Path
    archive: Path | None
    pictures: Path
    pages: int = 0
    phash: str = ""
    sha256: str = ""
    size: int = 0
    extension: str = ".pdf"
    placed: list[Path] = field(default_factory=list)

    def clean(self) -> None:
        for path in (self.file, self.archive, *self.placed):
            if path is not None:
                path.unlink(missing_ok=True)
        shutil.rmtree(self.pictures, ignore_errors=True)


SCRATCH = ".incoming-"
#: A folder of pictures older than this was left by a run that broke off (a run takes minutes at most).
SCRATCH_HOURS = 6


def _scratch_pictures() -> Path:
    folder = pages.cache_root() / f"{SCRATCH}{secrets.token_hex(8)}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def sweep_scratch() -> int:
    """The folders of pictures a run left behind when the server stopped in the middle, and the half-written pictures
    of a worker that was killed (``.incoming-part-…``), when they are older than ``SCRATCH_HOURS`` (now and then, with
    the housekeeping). Returns how many went."""
    root = pages.cache_root()
    if not root.is_dir():
        return 0
    cutoff = time.time() - SCRATCH_HOURS * 3600
    gone = 0
    for path in list(root.rglob(f"{SCRATCH}*")):
        with contextlib.suppress(OSError):
            if path.stat().st_mtime >= cutoff:
                continue
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink()
            gone += 1
    return gone


def _worker_failed(code: str) -> Exception:
    if code == "timeout":
        return error("too_slow", "This took longer than the server allows. Try fewer pages.", 422)
    if code in ("encrypted", "broken", "too_many_pages", "too_large"):
        return error("pdf_" + code, "The PDF of this document cannot be worked on.", 422)
    # The worker ended without an answer (killed, the server stopping): another try may well work.
    return _busy_error("try_again", "The pages could not be made this time. Try again in a moment.")


def assemble(db: Session, uid: int, sources: list[Path], wanted: list[tuple[list[list[int]], list[list[int]] | None]]
             ) -> list[Made]:
    """New PDFs in the worker. ``wanted``: for each new version the pages of its file (``[source, page from 0, turn]``)
    and those of its searchable copy (or None). Raises the interface's error when the worker refuses."""
    from . import processing

    current = limits.current(db)
    made: list[Made] = []
    outputs: list[dict[str, Any]] = []
    for file_pages, archive_pages in wanted:
        item = Made(file=storage.incoming_path("tool-"),
                    archive=storage.incoming_path("tool-") if archive_pages else None, pictures=_scratch_pictures())
        made.append(item)
        drawn = {"thumb_out": str(item.pictures / "thumb.webp"), "thumb_width": pages.WIDTHS["thumb"],
                 "pages_pattern": str(item.pictures / "p{page}.webp"), "pages_width": pages.WIDTHS["small"],
                 "prerender_pages": pages.PRERENDER_PAGES}
        outputs.append({"out": str(item.file), "pages": file_pages, **({} if archive_pages else drawn)})
        if archive_pages:
            assert item.archive is not None
            outputs.append({"out": str(item.archive), "pages": archive_pages, **drawn})
    request = {"op": "assemble", "sources": [str(path) for path in sources], "outputs": outputs,
               "max_pages": current.max_pages, "memory_mb": current.memory_mb,
               "render_pixels": limits.MAX_RENDER_PIXELS}
    db.rollback()  # no transaction stays open while the worker runs
    try:
        with _slot(uid):
            outcome = processing.spawn(request, max(60, current.timeout_seconds))
        if not outcome.ok:
            logger.info("The page tools could not make a file error=%s", outcome.error)
            raise _worker_failed(outcome.error)
        results = outcome.data.get("outputs") or []
        index = 0
        for item, (_file_pages, archive_pages) in zip(made, wanted, strict=True):
            first = results[index]
            drawn_from = results[index + 1] if archive_pages else first
            index += 2 if archive_pages else 1
            item.pages = int(drawn_from.get("pages") or 0)
            item.phash = str(drawn_from.get("phash") or "")
            item.sha256 = storage.sha256_of(item.file)
            item.size = item.file.stat().st_size
            if item.pages < 1 or int(first.get("pages") or 0) != item.pages:
                raise _worker_failed("broken")
    except BaseException:
        for item in made:
            item.clean()
        raise
    return made


def _interim(db: Session, document: Document, n: int, extension: str, archive: bool = False) -> str:
    """A free name for a new file of version ``n`` beside the others; the ``rename`` job gives it its final one."""
    parts = storage.parts_for(db, document)
    tag = f"version {n}, searchable" if archive else f"version {n}"
    return "/".join((*parts.folders, storage.free_name(db, parts.folders, f"{parts.stem} ({tag}){extension}")))


def _next_n(db: Session, document_id: int) -> int:
    return int(db.scalar(select(func.max(Version.n)).where(Version.document_id == document_id)) or 0) + 1


def _add_version(db: Session, uid: int, document: Document, made: Made, origin: str, from_n: int | None,
                 detail: dict[str, Any], text: tuple[list[str], int, str] | None, blanks: list[int] | None,
                 dismissed: bool = False) -> Version:
    """Version ``n + 1`` of the document from what the worker made, as the current one (inside the caller's
    transaction, under the write lock). The files are put in place here; ``made.placed`` names them for a rollback."""
    from . import processing

    n = _next_n(db, document.id)
    rel = _interim(db, document, n, made.extension)
    made.placed.append(storage.adopt(made.file, rel))
    archive_rel, archive_sha256 = "", ""
    if made.archive is not None:
        archive_rel = _interim(db, document, n, ".pdf", archive=True)
        archive_sha256 = storage.sha256_of(made.archive)
        made.placed.append(storage.adopt(made.archive, archive_rel))
    version = Version(document_id=document.id, n=n, original_path=rel, archive_path=archive_rel, sha256=made.sha256,
                      size=made.size, pages=made.pages, created_by=uid, created_at=clock.now(), note="",
                      phash=made.phash, archive_sha256=archive_sha256)
    db.add(version)
    db.flush()
    db.add(VersionInfo(version_id=version.id, document_id=document.id, origin=origin, from_n=from_n, state=READY,
                       error="", detail=detail, blanks=blanks, split_dismissed=dismissed))
    if text is not None:
        processing._keep_text(db, version, text[0], text[1], text[2])
    document.current_version = n
    document.pages = made.pages
    # The small pages of a long version are drawn in the background, as after reading a document (B4).
    pages.queue_background(db, document.id, n, made.pages)
    return version


def place_pictures(made: Made, document_id: int, n: int) -> None:
    """The pictures the worker drew go to the cache of the version (after it was written: a version that was not
    written has none)."""
    folder = pages.document_dir(document_id)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for path in made.pictures.glob("*.webp"):
            name = path.stem
            if name == "thumb":
                target = pages.thumb_path(document_id, n)
            elif name.startswith("p") and name[1:].split("-")[0].isdigit():
                number = int(name[1:].split("-")[0])
                size = "large" if name.endswith("-large") else "small"
                target = pages.page_path(document_id, n, number, size)
            else:
                continue
            os.replace(path, target)
    except OSError:
        logger.warning("Pictures of a new version not kept; they are drawn when asked for document_id=%s", document_id)
    finally:
        shutil.rmtree(made.pictures, ignore_errors=True)


def _write(db: Session, made: list[Made], body: Any) -> Any:
    """Runs ``body`` under the write lock and commits; on any failure the files of ``made`` go again."""
    try:
        changes.write_lock(db)
        result = body()
        db.commit()
    except BaseException:
        db.rollback()
        for item in made:
            item.clean()
        raise
    return result


# --- Turning, deleting, ordering --------------------------------------------------------------------------------------


def edit_pages(db: Session, uid: int, document_id: int, base_version: int, specs: list[tuple[int, int]]) -> Document:
    """See ``_edit_pages``; the files of the document are this tool's while it runs."""
    with _files([document_id]):
        return _edit_pages(db, uid, document_id, base_version, specs)


def _edit_pages(db: Session, uid: int, document_id: int, base_version: int, specs: list[tuple[int, int]]) -> Document:
    """The pages of the current version in a new order, turned, some left out: version ``n + 1``. ``specs``: for each
    page that stays, in its new place, its number in the current version and its turn (degrees clockwise)."""
    access = check(db, uid, document_id, base_version)
    document = access.document
    version = current_version(db, document)
    _validate(specs, version.pages)
    if specs == [(page, 0) for page in range(1, version.pages + 1)]:
        db.rollback()
        return document
    original, archive = _pdfs(version)
    if original is None and archive is None or version.pages < 1:
        raise error("no_pages", "This document has no pages to work with.", 422)
    if original is not None:
        _verify(original, version.sha256)
    text_row = texts_of(db, version)
    texts = _pages_of(text_row)
    old_info = db.get(VersionInfo, version.id)
    old_blanks = old_info.blanks if old_info is not None and isinstance(old_info.blanks, list) else None
    dismissed = bool(old_info is not None and old_info.split_dismissed)
    if original is not None and archive is not None:
        sources = [original, archive]
        wanted = ([[0, page - 1, turn] for page, turn in specs], [[1, page - 1, turn] for page, turn in specs])
    else:
        sources = [original or archive]  # type: ignore[list-item]
        wanted = ([[0, page - 1, turn] for page, turn in specs], None)
    made = assemble(db, uid, sources, [wanted])

    def write() -> Version:
        nonlocal document
        document = check(db, uid, document_id, base_version).document
        kept = [page for page, _turn in specs]
        detail = {"pages": len(specs), "turned": sum(1 for _page, turn in specs if turn),
                  "removed": version.pages - len(specs), "moved": kept != sorted(kept)}
        text = None
        if texts is not None and text_row is not None:
            text = ([texts[page - 1] for page in kept], min(text_row.ocr_pages, len(kept)), text_row.languages)
        blanks = [index for index, page in enumerate(kept, start=1) if page in old_blanks] if old_blanks else None
        new = _add_version(db, uid, document, made[0], PAGES, base_version, detail, text, blanks, dismissed)
        changes.record(db, document.id, PAGES_EDITED, user_id=uid, detail={"version": new.n, "from": base_version,
                                                                           **detail})
        _after(db, document, text is None)
        return new

    new = _write(db, made, write)
    place_pictures(made[0], document_id, new.n)
    return document


def _after(db: Session, document: Document, needs_text: bool) -> None:
    document.change_seq = changes.next_seq(db)
    jobs.enqueue(db, jobs.RENAME, document.id)
    filecheck.recheck_soon(db, document)
    if needs_text:
        # The version before had no text (a document read before there was text): it is read like one.
        jobs.enqueue(db, jobs.TEXT, document.id)


# --- Joining ---------------------------------------------------------------------------------------------------------


def merge(db: Session, uid: int, items: list[tuple[int, int]]) -> Document:
    """See ``_merge``; the files of all documents are this tool's while it runs."""
    if not 2 <= len(items) <= MAX_MERGE:
        raise error("invalid_merge", f"Join 2 to {MAX_MERGE} documents.", 422)
    with _files([document_id for document_id, _base in items]):
        return _merge(db, uid, items)


def _merge(db: Session, uid: int, items: list[tuple[int, int]]) -> Document:
    """Several documents become the first of them: its new version has the pages of all, in the order given. The first
    keeps its fields; the notes and tags of the others are added to it; the others go to the trash. ``items``: the
    documents with the version each was seen at."""
    ids = [document_id for document_id, _base in items]
    if not 2 <= len(items) <= MAX_MERGE:
        raise error("invalid_merge", f"Join 2 to {MAX_MERGE} documents.", 422)
    if len(set(ids)) != len(ids):
        raise error("invalid_merge", "A document can be joined only once.", 422)
    accesses = [check(db, uid, document_id, base, vault=index == 0) for index, (document_id, base) in enumerate(items)]
    versions = [current_version(db, access.document) for access in accesses]
    sources = [best_pdf(version) for version in versions]
    for version, path in zip(versions, sources, strict=True):
        if not version.archive_path:
            _verify(path, version.sha256)
    total = sum(version.pages for version in versions)
    if total > limits.current(db).max_pages:
        raise error("too_many_pages", "Together the documents have more pages than the server takes.", 422)
    rows = [texts_of(db, version) for version in versions]
    texts: list[str] | None = []
    for row in rows:
        if row is None or texts is None:
            texts = None
        else:
            texts.extend(row.text.split("\f"))
    file_pages = [[index, page, 0] for index, version in enumerate(versions) for page in range(version.pages)]
    made = assemble(db, uid, sources, [(file_pages, None)])

    def write() -> Version:
        found = [check(db, uid, document_id, base, vault=index == 0).document
                 for index, (document_id, base) in enumerate(items)]
        first, others = found[0], found[1:]
        text = None
        if texts is not None:
            text = (texts, sum(row.ocr_pages for row in rows if row is not None),
                    next((row.languages for row in rows if row is not None and row.languages), ""))
        detail = {"pages": total, "from": [other.id for other in others]}
        new = _add_version(db, uid, first, made[0], MERGED, items[0][1], detail, text, None)
        names: list[str] = []
        for other in others:
            for note in db.scalars(select(Note).where(Note.document_id == other.id).order_by(Note.id)):
                db.add(Note(document_id=first.id, user_id=note.user_id, text=note.text, created_at=note.created_at,
                            updated_at=note.updated_at))
            names.extend(db.scalars(select(Tag.name).join(DocumentTag, DocumentTag.tag_id == Tag.id)
                                    .where(DocumentTag.document_id == other.id)))
            _to_trash(db, uid, other)
            changes.record(db, other.id, MERGED_INTO, user_id=uid, detail={"into": first.id})
        have = set(db.scalars(select(DocumentTag.tag_id).where(DocumentTag.document_id == first.id)))
        for tag in catalog.tags_named(db, first.vault_id, uid, names):
            if tag.id not in have:
                db.add(DocumentTag(document_id=first.id, tag_id=tag.id))
                have.add(tag.id)
        changes.record(db, first.id, MERGED_FROM, user_id=uid, detail={"version": new.n, **detail})
        _after(db, first, text is None)
        return new

    new = _write(db, made, write)
    place_pictures(made[0], items[0][0], new.n)
    return documents.one(db, uid, items[0][0])[0].document


def _to_trash(db: Session, uid: int, document: Document) -> None:
    document.trashed_status = document.status if document.status in (INBOX, FILED) else FILED
    document.status = TRASH
    document.trashed_at = clock.now()
    document.change_seq = changes.next_seq(db)
    changes.record(db, document.id, changes.TRASHED, user_id=uid)


# --- Splitting ------------------------------------------------------------------------------------------------------


def split(db: Session, uid: int, document_id: int, base_version: int, parts: list[list[tuple[int, int]]],
          titles: list[str | None] | None = None) -> list[Document]:
    """See ``_split``; the files of the document are this tool's while it runs."""
    with _files([document_id]):
        return _split(db, uid, document_id, base_version, parts, titles)


def _split(db: Session, uid: int, document_id: int, base_version: int, parts: list[list[tuple[int, int]]],
           titles: list[str | None] | None = None) -> list[Document]:
    """The document becomes as many new documents as ``parts`` in the inbox, each with the pages named (in that order,
    turned as asked); pages named in no part (the blank separators) are left out. The new ones take the fields of the
    document (title with a number, sender, kind, date, tags), the document goes to the trash."""
    if not 2 <= len(parts) <= MAX_PARTS:
        raise error("invalid_split", f"Split into 2 to {MAX_PARTS} documents.", 422)
    if titles is not None and len(titles) != len(parts):
        raise error("invalid_split", "Give one title for each part, or none.", 422)
    access = check(db, uid, document_id, base_version, vault=True)
    document = access.document
    version = current_version(db, document)
    flat = [spec for part in parts for spec in part]
    if any(not part for part in parts):
        raise error("invalid_split", "Every part needs at least one page.", 422)
    _validate(flat, version.pages)
    names = [_title(document.title, index, (titles or [None] * len(parts))[index]) for index in range(len(parts))]
    source = best_pdf(version)
    if not version.archive_path:
        _verify(source, version.sha256)
    text_row = texts_of(db, version)
    texts = _pages_of(text_row)
    made = assemble(db, uid, [source], [([[0, page - 1, turn] for page, turn in part], None) for part in parts])

    def write() -> list[Document]:
        original = check(db, uid, document_id, base_version, vault=True).document
        tag_ids = list(db.scalars(select(DocumentTag.tag_id).where(DocumentTag.document_id == original.id)))
        made_documents: list[Document] = []
        for index, (part, item) in enumerate(zip(parts, made, strict=True)):
            new = Document(vault_id=original.vault_id, owner_id=original.owner_id, title=names[index],
                           sender_id=original.sender_id, kind_id=original.kind_id, date=original.date, status=INBOX,
                           source=original.source, added_at=clock.now(), pages=item.pages, current_version=1,
                           change_seq=changes.next_seq(db))
            db.add(new)
            db.flush()
            for tag_id in tag_ids:
                db.add(DocumentTag(document_id=new.id, tag_id=tag_id))
            changes.record(db, new.id, changes.CREATED, user_id=uid,
                           detail={"source": original.source, "split_from": original.id})
            parts_of = storage.parts_for(db, new)
            rel = "/".join((*parts_of.folders, storage.free_name(db, parts_of.folders, parts_of.stem + ".pdf")))
            item.placed.append(storage.adopt(item.file, rel))
            created = Version(document_id=new.id, n=1, original_path=rel, sha256=item.sha256, size=item.size,
                              pages=item.pages, created_by=uid, created_at=clock.now(), note="", phash=item.phash)
            db.add(created)
            db.flush()
            kept = [page for page, _turn in part]
            db.add(VersionInfo(version_id=created.id, document_id=new.id, origin=SPLIT, from_n=None, state=READY,
                               error="", detail={"from_document": original.id, "pages": kept}, blanks=[],
                               split_dismissed=False))
            if texts is not None and text_row is not None:
                from . import processing

                processing._keep_text(db, created, [texts[page - 1] for page in kept], 0, text_row.languages)
            else:
                jobs.enqueue(db, jobs.TEXT, new.id)
            pages.queue_background(db, new.id, 1, item.pages)
            made_documents.append(new)
        from . import keeping

        # The parts keep the kind and date of the whole: its keeping time too.
        keeping.refresh(db, [d.id for d in made_documents])
        _to_trash(db, uid, original)
        changes.record(db, original.id, SPLIT_INTO, user_id=uid,
                       detail={"into": [d.id for d in made_documents], "parts": len(parts),
                               "dropped": version.pages - len(flat)})
        return made_documents

    made_documents = _write(db, made, write)
    for new_document, item in zip(made_documents, made, strict=True):
        place_pictures(item, new_document.id, 1)
    return made_documents


def _title(base: str, index: int, given: str | None) -> str:
    if given is not None and given.strip():
        return documents.clean_title(given)
    suffix = f" ({index + 1})"
    return documents.clean_title(base[: documents.TITLE_MAX - len(suffix)].rstrip() + suffix)


# --- Versions -----------------------------------------------------------------------------------------------------


def _link_or_copy(source: Path, label: str) -> Path:
    """A copy of a file beside the documents: a second name of the same file where the disk can, else a copy."""
    target = storage.incoming_path(label)
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)
    return target


def restore(db: Session, uid: int, document_id: int, number: int, base_version: int) -> Document:
    """See ``_restore``; the files of the document are this tool's while it runs."""
    with _files([document_id]):
        return _restore(db, uid, document_id, number, base_version)


def _restore(db: Session, uid: int, document_id: int, number: int, base_version: int) -> Document:
    """Version ``number`` again as the current one: a new version ``n + 1`` with its file, its searchable copy, its text
    and its pictures. Nothing is deleted; the version that was current stays in the list."""
    access = check(db, uid, document_id, base_version)
    document = access.document
    if number == document.current_version:
        raise error("already_current", "This version is the current one.", 409)
    old = db.scalar(select(Version).where(Version.document_id == document.id, Version.n == number))
    if old is None:
        raise error("not_found", "Not found.", 404)
    old_info = db.get(VersionInfo, old.id)
    if old_info is not None and old_info.state != READY:
        raise error("version_not_ready", "This version was not read.", 409)
    try:
        source = storage.safe_path(old.original_path)
        archive = storage.safe_path(old.archive_path) if old.archive_path else None
    except storage.StorageError:
        raise error("not_found", "Not found.", 404) from None
    if not source.is_file() or (archive is not None and not archive.is_file()):
        raise error("file_missing", "The file of this version is missing on the disk.", 409)
    text_row = db.get(VersionText, old.id)
    text = (text_row.text.split("\f"), text_row.ocr_pages, text_row.languages) if text_row is not None else None
    blanks = old_info.blanks if old_info is not None and isinstance(old_info.blanks, list) else None
    dismissed = bool(old_info is not None and old_info.split_dismissed)
    pictures = _scratch_pictures()
    made = Made(file=_link_or_copy(source, "restore-"), archive=None, pictures=pictures, pages=old.pages,
                phash=old.phash, sha256=old.sha256, size=old.size, extension=Path(old.original_path).suffix.lower())
    try:
        # The very file of that version, or nothing (it should not happen under the lock).
        _verify(made.file, old.sha256)
        if archive is not None:
            made.archive = _link_or_copy(archive, "restore-")
        for path in pages.document_dir(document.id).glob(f"v{number}-*.webp"):
            rest = path.name[len(f"v{number}-"):]
            shutil.copyfile(path, pictures / (rest.replace("-small", "") if rest.endswith("-small.webp") else rest))
    except BaseException:
        made.clean()
        raise
    db.rollback()

    def write() -> Version:
        nonlocal document
        document = check(db, uid, document_id, base_version).document
        new = _add_version(db, uid, document, made, RESTORED, number, {"pages": old.pages}, text, blanks,
                           dismissed)
        changes.record(db, document.id, VERSION_RESTORED, user_id=uid, detail={"version": new.n, "from": number})
        _after(db, document, text is None)
        return new

    new = _write(db, [made], write)
    place_pictures(made, document_id, new.n)
    return document


def clean_note(value: str | None) -> str:
    """What the person says about a new version ("a better scan, page 2 was blurred"): one line (line breaks and tabs
    become blanks), no other control characters, at most ``NOTE_MAX`` characters."""
    raw = value or ""
    if any((ord(char) < 32 and char not in WHITE) or ord(char) == 127 for char in raw):
        raise error("invalid_note", "A note cannot hold control characters.", 422)
    text = " ".join(raw.split())
    if len(text) > NOTE_MAX:
        raise error("invalid_note", f"Use at most {NOTE_MAX} characters.", 422)
    return text


def accept_version(db: Session, uid: int, document_id: int, *, path: Path, kind: str, sha256: str,
                   size: int, note: str = "") -> Version:
    """See ``_accept_version``; the files of the document are this tool's while the file is put in place."""
    try:
        with _files([document_id]):
            return _accept_version(db, uid, document_id, path=path, kind=kind, sha256=sha256, size=size, note=note)
    finally:
        path.unlink(missing_ok=True)


def _accept_version(db: Session, uid: int, document_id: int, *, path: Path, kind: str, sha256: str,
                    size: int, note: str = "") -> Version:
    """A file that was uploaded becomes the next version of a document. It is read by the worker like a new document
    (job ``version``); until then the document shows the version before, and the new one is listed as being read.
    ``path`` is moved (gone afterwards). ``note``: what the person says about it (``clean_note``)."""
    extension = filetypes.EXTENSION[kind]
    try:
        changes.write_lock(db)
        document = check(db, uid, document_id, None).document
        current = current_version(db, document)
        if current.sha256 == sha256:
            raise error("same_file", "This file is the current version already.", 409)
        n = _next_n(db, document.id)
        rel = _interim(db, document, n, extension)
        placed = storage.adopt(path, rel)
    except BaseException:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    try:
        version = Version(document_id=document.id, n=n, original_path=rel, sha256=sha256, size=size, pages=0,
                          created_by=uid, created_at=clock.now(), note=note[:NOTE_MAX])
        db.add(version)
        db.flush()
        db.add(VersionInfo(version_id=version.id, document_id=document.id, origin=UPLOADED, from_n=current.n,
                           state=PENDING, error="", detail=None, blanks=None, split_dismissed=False))
        changes.record(db, document.id, VERSION_UPLOADED, user_id=uid, detail={"version": n})
        document.change_seq = changes.next_seq(db)
        jobs.enqueue(db, jobs.VERSION, version.id)
        db.commit()
    except BaseException:
        db.rollback()
        placed.unlink(missing_ok=True)
        raise
    return version


def ready_for_version(db: Session, uid: int, document_id: int) -> Document:
    """Before a new version is received: the caller may add one now (the body is read only then)."""
    access = check(db, uid, document_id, None)
    db.rollback()
    return access.document


def run_version(db: Session, version_id: int, attempt: int) -> None:
    """The job ``version``: an uploaded version is read like a new document (the steps of ``processing.STEPS``), then
    it becomes the current one. A file that cannot be read stays in the list, marked so; the document keeps the version
    it had."""
    version = db.get(Version, version_id)
    info = db.get(VersionInfo, version_id)
    if version is None or info is None or info.state != PENDING:
        db.rollback()
        return
    document = db.get(Document, version.document_id)
    if document is None:
        db.rollback()
        return
    document_id, n = document.id, version.n
    try:
        _read_version(db, version_id, attempt, document, version, document_id, n)
    except (jobs.Retry, jobs.GiveUp, jobs.Interrupted, storage.DocumentBusy):
        raise
    except Exception:
        # Something the steps do not expect (a full disk, a locked database): on the last try the version is marked
        # as failed, so that it does not hold the document for ever.
        if attempt >= jobs.ATTEMPTS:
            db.rollback()
            _version_failed(db, version_id, "failed")
        raise


def _read_version(db: Session, version_id: int, attempt: int, document: Document, version: Version, document_id: int,
                  n: int) -> None:
    from . import processing

    work = processing.Run(work=storage.incoming_path("proc-"), searchable=storage.incoming_path("text-"),
                          text=storage.incoming_path("pages-"))
    outcome = processing.Outcome(False, error="failed", retry=True)
    try:
        for index, step in enumerate(processing.STEPS):
            outcome = step(db, document, version, work)
            if outcome.ok:
                work.data.update(outcome.data)
                continue
            if index == 0 or (outcome.retry and attempt < processing.ATTEMPTS):
                break
            work.soft_error = processing.SOFT_ERRORS.get(outcome.error, "ocr_failed")
            outcome = processing.Outcome(True)
            break
        if outcome.ok:
            _finish_version(db, version_id, work)
            return
    except Exception:
        work.clean()
        raise
    work.clean()
    pages.remove_version(document_id, n)
    if outcome.retry and attempt < processing.ATTEMPTS:
        raise jobs.Retry(outcome.error)
    _version_failed(db, version_id, outcome.error or "failed")
    if outcome.retry:
        raise jobs.GiveUp(outcome.error or "failed")


def _finish_version(db: Session, version_id: int, work: Any) -> None:
    version = db.get(Version, version_id)
    if version is None:
        db.rollback()
        work.clean()
        return
    document_id = version.document_id
    db.rollback()
    with storage.files_of([document_id], 60):
        _finish_version_locked(db, version_id, work)


def _finish_version_locked(db: Session, version_id: int, work: Any) -> None:
    from . import processing

    data = work.data
    try:
        changes.write_lock(db)
        version = db.get(Version, version_id)
        info = db.get(VersionInfo, version_id)
        document = db.get(Document, version.document_id) if version is not None else None
        if version is None or info is None or document is None or info.state != PENDING:
            db.rollback()
            work.clean()
            return
        count = int(data.get("pages") or 0)
        document.current_version = max(document.current_version, version.n)
        made = work.searchable if data.get("searchable") and work.searchable.is_file() else (
            work.work if data.get("derived") and work.work.is_file() else None)
        if made is not None:
            target = _interim(db, document, version.n, ".pdf", archive=True)
            version.archive_sha256 = storage.sha256_of(made)
            storage.adopt(made, target)
            version.archive_path = target
        version.pages = count
        version.phash = str(data.get("phash") or "")
        texts = data.get("texts")
        if isinstance(texts, list):
            processing._keep_text(db, version, texts, int(data.get("ocr_pages") or 0), str(data.get("languages") or ""))
        info.state = READY
        info.error = work.soft_error
        ink = data.get("ink")
        info.blanks = separators.blank_pages(ink) if isinstance(ink, list) else None
        if document.current_version == version.n:
            document.pages = count
            pages.queue_background(db, document.id, version.n, count)
        added: dict[str, Any] = {"version": version.n, "pages": count}
        if work.soft_error:
            added["error"] = work.soft_error
        changes.record(db, document.id, VERSION_ADDED, detail=added)
        document.change_seq = changes.next_seq(db)
        jobs.enqueue(db, jobs.RENAME, document.id)
        filecheck.recheck_soon(db, document)
        db.commit()
    except Exception:
        db.rollback()
        work.clean()
        raise
    work.clean()


def _version_failed(db: Session, version_id: int, code: str) -> None:
    changes.write_lock(db)
    info = db.get(VersionInfo, version_id)
    version = db.get(Version, version_id)
    if info is None or version is None:
        db.rollback()
        return
    info.state = FAILED
    info.error = code[:24]
    changes.record(db, version.document_id, VERSION_FAILED, detail={"version": version.n, "error": code[:24]})
    document = db.get(Document, version.document_id)
    if document is not None:
        document.change_seq = changes.next_seq(db)
    db.commit()
    logger.info("An uploaded version could not be read document_id=%s error=%s", version.document_id, code)


VERSION_DISCARDED = "version_discarded"


def discard(db: Session, uid: int, document_id: int, number: int) -> None:
    """An uploaded version that could not be read goes again, file and all (``edit``). A version that was read is
    never deleted (``409 not_failed``)."""
    with _files([document_id]):
        changes.write_lock(db)
        access = rights.require_document(db, uid, document_id, EDIT)
        document = access.document
        if document.status == TRASH:
            raise error("in_trash", "Restore the document first.", 409)
        version = db.scalar(select(Version).where(Version.document_id == document_id, Version.n == number))
        if version is None:
            raise error("not_found", "Not found.", 404)
        info = db.get(VersionInfo, version.id)
        stuck = info is not None and info.state == PENDING and bool(stalled(db, [version.id]))
        failed = info is not None and (info.state == FAILED or stuck)
        if not failed or number == document.current_version:
            raise error("not_failed", "Only a version that could not be read can be put away.", 409)
        paths = [rel for rel in (version.original_path, version.archive_path) if rel]
        db.delete(version)
        document.change_seq = changes.next_seq(db)
        changes.record(db, document.id, VERSION_DISCARDED, user_id=uid, detail={"version": number})
        filecheck.recheck_soon(db, document)
        db.commit()
        storage.remove_files(paths)
        pages.remove_version(document_id, number)


# --- The blank separator pages of a document --------------------------------------------------------------------------


@dataclass
class Separators:
    version: int
    checked: bool
    blank_pages: list[int]
    parts: list[list[int]]
    duplex: bool
    dismissed: bool
    #: A split is proposed: in the inbox, two parts or more, not dismissed.
    suggested: bool


def separators_of(db: Session, uid: int, document_id: int) -> Separators:
    access = rights.require_document(db, uid, document_id)
    document = access.document
    version = current_version(db, document)
    info = db.get(VersionInfo, version.id)
    blanks = info.blanks if info is not None and isinstance(info.blanks, list) else None
    found = separators.proposal(version.pages, blanks or [])
    dismissed = bool(info is not None and info.split_dismissed)
    return Separators(version=version.n, checked=blanks is not None, blank_pages=found.separators, parts=found.parts,
                      duplex=found.duplex, dismissed=dismissed,
                      suggested=document.status == INBOX and bool(found.parts) and not dismissed)


def keep_as_one(db: Session, uid: int, document_id: int) -> None:
    """"Keep as one document": the proposal to split is not made again for this version."""
    changes.write_lock(db)
    access = rights.require_document(db, uid, document_id, EDIT)
    document = access.document
    version = current_version(db, document)
    info = separators.info_of(db, version)
    if info.split_dismissed:
        db.rollback()
        return
    info.split_dismissed = True
    document.change_seq = changes.next_seq(db)
    changes.record(db, document.id, SPLIT_KEPT, user_id=uid, detail={"version": version.n})
    db.commit()


__all__ = ["MAX_MERGE", "MAX_PARTS", "TURNS", "accept_version", "check", "edit_pages", "infos", "keep_as_one",
           "merge", "pending", "ready_for_version", "restore", "run_version", "separators_of", "split"]
