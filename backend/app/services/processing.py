"""Reading a document that has come in: the worker process, its time limit, and what is done with what it finds.

A document that has just been received stands as ``processing`` with a job ``process`` waiting for it. The loop in
``services/jobs.py`` takes the jobs one by one (one document at a time) and calls ``run``:

1. The steps are a list (``STEPS``), run one after the other (``app/worker.py``):
   *read the file*: pictures become a PDF beside the original, the pages are counted, the first page is drawn as the
   preview and fingerprinted; *read the text*: what the PDF carries, and where a page carries none, what Tesseract
   recognises (ocrmypdf), written as a searchable copy beside the original.
2. Each step runs **in a process of its own** (``spawn``): it gets the paths and the limits, no database and no secret.
   When it takes longer than the operator's limit (for the text: per ten pages) the process is killed with everything
   it started (Tesseract too); where the system has ``setrlimit`` the memory is limited too. A file that crashes the
   reader harms nothing else.
3. What the worker found is written in one short move under the write lock (``_finish``): the pages, the fingerprint,
   the searchable copy, the text, the document it looks like, the status ``inbox``, a line in the history (numbers
   only, never text) and a number for the change feed; the search index follows in the same transaction.

A file that cannot be read (a PDF with a password, a damaged one, one with too many pages) does not come back: the
document waits in the inbox with the reason (``process_error``), and a person may try again (``retry``). A file the
worker could not finish for another reason (the time limit, a crash, the disk) is tried ``ATTEMPTS`` times, then it
waits the same way. When only the text could not be read, the document keeps what the first step found and waits with
``ocr_timeout`` or ``ocr_failed``."""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import error
from ..models import EDIT, FILED, INBOX, PROCESSING, TRASH, Document, Job, Version, VersionText
from . import changes, filetypes, jobs, limits, ocr, pages, rights, search_index, separators, similar, sorting, storage

logger = logging.getLogger("nexpaper.processing")

ATTEMPTS = 3
WORKER = Path(__file__).resolve().parent.parent / "worker.py"
#: The environment the worker gets: enough to start, nothing the server knows (no secret key, no tokens).
KEEP_ENVIRONMENT = ("PATH", "SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL")
#: How long drawing one page may take, apart from the limit for a document.
RENDER_SECONDS = 60
# What the history says.
PROCESSED, PROCESS_FAILED, RETRIED = "processed", "process_failed", "retried"
#: Codes of a file that cannot be read, which no second try changes.
PERMANENT = ("encrypted", "broken", "too_many_pages", "too_large")


@dataclass
class Outcome:
    """What a run of the worker came to: ``data`` when it worked, else ``error`` (a code) and whether another try may
    help (``retry``)."""

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    retry: bool = False


def _kill(process: subprocess.Popen[bytes]) -> None:
    """The process and everything it started."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, check=False,
                           timeout=15)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        process.kill()
    except OSError:
        pass


def _reap(process: subprocess.Popen[bytes]) -> None:
    """Collects a killed process; one that does not go (it should not happen) is left, never waited for for good."""
    try:
        process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        logger.error("A worker process did not end after it was killed")


def spawn(request: dict[str, Any], timeout: int) -> Outcome:
    """One task in a worker process, at most ``timeout`` seconds. It runs in a folder of its own that is empty and goes
    afterwards: the data folder (the database, the secret key, the documents of everybody) is not where it stands."""
    if jobs.stopping.is_set():
        # The server is going down: no worker is started for a job that would be put back at once.
        raise jobs.Interrupted
    # A worker killed under load may hold its folder for a moment (Windows): that must not turn the end of a run into an
    # error of its own, the folder is empty anyway.
    with tempfile.TemporaryDirectory(prefix="nexpaper-worker-", ignore_cleanup_errors=True) as folder:
        return _spawn(request, timeout, folder)


def _spawn(request: dict[str, Any], timeout: int, cwd: str) -> Outcome:
    environment = {key: os.environ[key] for key in KEEP_ENVIRONMENT if key in os.environ}
    options: dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {}
    process = subprocess.Popen(
        [sys.executable, "-I", str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=environment, cwd=cwd, **options,
    )
    payload: bytes | None = json.dumps(request).encode("utf-8")
    deadline = time.monotonic() + timeout
    try:
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise subprocess.TimeoutExpired("worker", timeout)
            try:
                out, err = process.communicate(payload, timeout=min(1.0, left))
                break
            except subprocess.TimeoutExpired:
                payload = None
                if jobs.stopping.is_set():
                    # The server is going down: the worker goes with it, and the job waits for the next start.
                    _kill(process)
                    _reap(process)
                    raise jobs.Interrupted from None
    except subprocess.TimeoutExpired:
        _kill(process)
        _reap(process)
        logger.warning("The worker was stopped at the time limit seconds=%s", timeout)
        return Outcome(False, error="timeout", retry=True)
    except BaseException:
        _kill(process)
        raise
    lines = [line for line in out.decode("utf-8", "replace").splitlines() if line.strip()]
    try:
        answer = json.loads(lines[-1]) if lines else None
    except ValueError:
        answer = None
    if process.returncode != 0 or not isinstance(answer, dict):
        tail = err.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        logger.warning("The worker ended without an answer code=%s note=%s", process.returncode, tail[0][:120])
        return Outcome(False, error="failed", retry=True)
    if answer.get("ok"):
        return Outcome(True, data=answer)
    code = str(answer.get("error") or "failed")
    return Outcome(False, error=code, retry=bool(answer.get("retry")) and code not in PERMANENT)


def _kind_of(version: Version) -> str | None:
    return filetypes.KIND_OF_EXTENSION.get(Path(version.original_path).suffix.lower())


# --- The steps ---------------------------------------------------------------------------------------------------


@dataclass
class Run:
    """One run over a document: where its steps put what they make, and what they found so far."""

    #: The PDF made from a picture (step 1).
    work: Path
    #: The searchable copy the recognition wrote (step 2).
    searchable: Path
    #: The text of every page as JSON (step 2).
    text: Path
    data: dict[str, Any] = field(default_factory=dict)
    #: A later step that failed without spoiling what the first one found: the code the document waits with.
    soft_error: str = ""
    #: The PDF whose text is read, when it is not the original or ``work`` (a document read before, ``read_text``).
    source: Path | None = None

    def clean(self) -> None:
        for path in (self.work, self.searchable, self.text):
            path.unlink(missing_ok=True)


def read_file(db: Session, document: Document, version: Version, run: Run) -> Outcome:
    """The step that reads the file in the worker: pages, preview, fingerprint, and a PDF made from a picture
    (``run.work``)."""
    kind = _kind_of(version)
    if kind is None:
        return Outcome(False, error="broken")
    try:
        source = storage.safe_path(version.original_path)
    except storage.StorageError:
        return Outcome(False, error="failed", retry=True)
    if not source.is_file():
        return Outcome(False, error="failed", retry=True)
    current = limits.current(db)
    request: dict[str, Any] = {
        "op": "process", "kind": kind, "source": str(source), "max_pages": current.max_pages,
        "max_pixels": current.max_pixels, "memory_mb": current.memory_mb, "render_pixels": limits.MAX_RENDER_PIXELS,
        "thumb_out": str(pages.thumb_path(document.id, version.n)), "thumb_width": pages.WIDTHS["thumb"],
        # A short document has its small pages drawn here too (``{page}`` is filled in by the worker).
        "pages_pattern": str(pages.document_dir(document.id) / f"v{version.n}-p{{page}}-small.webp"),
        "pages_width": pages.WIDTHS["small"], "prerender_pages": pages.PRERENDER_PAGES,
    }
    if kind != filetypes.PDF:
        # A picture becomes a PDF there; an e-invoice that is XML only gets its readable copy there.
        request["archive_out"] = str(run.work)
    if kind == filetypes.XML:
        request["language"] = _language_of(db, document)
    db.rollback()  # the worker may take long: no read transaction stays open meanwhile
    return spawn(request, current.timeout_seconds)


_told_unavailable = False


def recognize_text(db: Session, document: Document, version: Version, run: Run) -> Outcome:
    """The step that reads the text (B3): what the PDF carries, and where a page carries none, what Tesseract
    recognises (``app/worker.py`` ``recognize``). The searchable copy goes to ``run.searchable``, the text of the pages
    to ``run.text``. Its time limit follows the pages and the pace of the last documents, with the operator's ceiling
    (``ocr.time_limit``)."""
    global _told_unavailable
    kind = _kind_of(version)
    if kind == filetypes.XML and not (run.data.get("derived") and run.work.is_file()):
        return Outcome(True)
    if version.note == "paperless":
        # Taken over from Paperless with the text it recognised and its searchable copy: nothing is read again.
        from . import paperless

        given = paperless.given_text(db, document, version, run)
        if given is not None:
            return given
    try:
        pdf = run.source or (run.work if run.data.get("derived") else storage.safe_path(version.original_path))
    except storage.StorageError:
        return Outcome(False, error="failed", retry=True)
    current = limits.current(db)
    settings = ocr.current(db)
    request: dict[str, Any] = {
        "op": "recognize", "pdf": str(pdf), "out": str(run.searchable), "text_out": str(run.text),
        "languages": settings.languages, "straighten": settings.straighten, "jobs": settings.jobs,
        "page_seconds": ocr.PAGE_SECONDS, "max_chars": ocr.MAX_CHARS, "max_pages": current.max_pages,
        "memory_mb": current.memory_mb,
    }
    limit = ocr.time_limit(current.timeout_seconds, int(run.data.get("pages") or 1), settings.max_seconds,
                           ocr.seconds_per_page(db))
    db.rollback()
    outcome = spawn(request, limit)
    if not outcome.ok:
        return outcome
    try:
        texts = _read_texts(run.text)
    except (OSError, ValueError):
        return Outcome(False, error="failed", retry=True)
    if outcome.data.get("ocr") == "unavailable" and not _told_unavailable:
        _told_unavailable = True
        logger.warning("Text recognition is not installed here: only text a PDF carries itself is found")
    return Outcome(True, data={"texts": texts, "ocr_pages": int(outcome.data.get("ocr_pages") or 0),
                               "languages": str(outcome.data.get("languages") or "")[:64],
                               "searchable": bool(outcome.data.get("archive"))})


def _language_of(db: Session, document: Document) -> str:
    """The language the readable copy of an e-invoice is set in: the owner's, German or English (German first)."""
    from ..models import Account

    owner = db.get(Account, document.owner_id) if document.owner_id else None
    language = (owner.language if owner is not None else "") or ""
    return "en" if language.lower().startswith("en") else "de"


def _read_texts(path: Path) -> list[str]:
    """The page texts the worker wrote, at most ``ocr.MAX_CHARS`` characters (and the bytes they can take)."""
    with path.open("rb") as handle:
        raw = handle.read(ocr.MAX_CHARS * 6 + 65536)
    texts = json.loads(raw.decode("utf-8"))
    if not isinstance(texts, list) or not all(isinstance(item, str) for item in texts):
        raise ValueError("texts")
    return [item.replace("\f", "\n") for item in texts]


#: The steps of a run, in order: the first reads the file (it failing means the document cannot be read), the ones
#: after it add to what it found (them failing leaves the document readable, with the reason). The last one measures the
#: ink of the pages for the blank separator pages (``services/separators.py``, B5); it never fails.
STEPS: list[Callable[[Session, Document, Version, Run], Outcome]] = [read_file, recognize_text,
                                                                      separators.find_blanks]
#: Called in ``_finish`` under the write lock with what the steps found, before the document goes to the inbox: what
#: other blocks keep of a run (B5: the blank pages; B6: the e-invoice, and the proposals for the fields,
#: ``services/sorting.py``).
FINISHERS: list[Callable[[Session, Document, Version, dict[str, Any]], None]] = [separators.keep_blanks,
                                                                                 sorting.finish]
#: The code a later step leaves on the document when it fails for good (else ``ocr_failed``).
SOFT_ERRORS = {"timeout": "ocr_timeout"}


# --- A run -------------------------------------------------------------------------------------------------------


def run(db: Session, job_id: int, document_id: int, attempt: int) -> None:
    """Reads one document. Returns when it is done (also when it could not be read for good); raises ``jobs.Retry`` for
    a try that may be repeated and ``jobs.GiveUp`` when the last try failed too."""
    document = db.get(Document, document_id)
    if document is None or document.status not in (PROCESSING, TRASH):
        return
    version = db.scalar(select(Version).where(Version.document_id == document.id,
                                              Version.n == document.current_version))
    if version is None:
        _fail(db, document_id, "broken")
        return
    version_n = version.n
    work = Run(work=storage.incoming_path("proc-"), searchable=storage.incoming_path("text-"),
               text=storage.incoming_path("pages-"))
    outcome = Outcome(False, error="failed", retry=True)
    try:
        for index, step in enumerate(STEPS):
            outcome = step(db, document, version, work)
            if outcome.ok:
                work.data.update(outcome.data)
                continue
            if index == 0 or (outcome.retry and attempt < ATTEMPTS):
                break
            # A later step failed for good: the document is kept with what the steps before it found.
            work.soft_error = SOFT_ERRORS.get(outcome.error, "ocr_failed")
            logger.warning("The text of a document could not be read document_id=%s error=%s", document_id,
                           outcome.error)
            outcome = Outcome(True)
            break
        if outcome.ok:
            _finish(db, document_id, version_n, work)
            return
    except Exception:
        work.clean()
        raise
    work.clean()
    pages.remove_version(document_id, version_n)
    if outcome.retry and attempt < ATTEMPTS:
        raise jobs.Retry(outcome.error)
    _fail(db, document_id, outcome.error or "failed")
    if outcome.retry:
        raise jobs.GiveUp(outcome.error or "failed")


def _finish(db: Session, document_id: int, version_n: int, work: Run) -> None:
    """The worker's result in one move: under the write lock, what was found is written (pages, fingerprint, the
    searchable copy, the text) and the document goes to the inbox. The search index follows in the same transaction
    (``services/search_index.py``)."""
    data = work.data
    # The document it looks like is looked for before the write lock: it reads the fingerprints of every document the
    # owner may see, which nobody else has to wait for.
    twin = _twin(db, document_id, data)
    try:
        changes.write_lock(db)
        document = db.get(Document, document_id)
        version = db.scalar(select(Version).where(Version.document_id == document_id, Version.n == version_n))
        if document is None or version is None:
            db.rollback()
            work.clean()
            pages.remove(document_id)
            return
        count = int(data.get("pages") or 0)
        never_read = document.pages == 0 and not version.phash
        # The searchable copy: the one the recognition wrote, else the PDF made from a picture.
        made = work.searchable if data.get("searchable") and work.searchable.is_file() else (
            work.work if data.get("derived") and work.work.is_file() else None)
        if made is not None:
            old = version.archive_path
            target = storage.archive_target(db, document, version)
            version.archive_sha256 = storage.sha256_of(made)
            storage.adopt(made, target)
            version.archive_path = target
            if old and old != target:
                storage.remove_files([old])
        document.pages = count
        version.pages = count
        version.phash = str(data.get("phash") or "")
        texts = data.get("texts")
        detail: dict[str, Any] = {"pages": count}
        if isinstance(texts, list):
            _keep_text(db, version, texts, int(data.get("ocr_pages") or 0), str(data.get("languages") or ""))
            detail["text_pages"] = sum(1 for page in texts if page.strip())
            detail["ocr_pages"] = int(data.get("ocr_pages") or 0)
        if work.soft_error:
            detail["error"] = work.soft_error
        document.process_error = work.soft_error
        for finisher in FINISHERS:
            finisher(db, document, version, data)
        if document.duplicate_kind != similar.SAME and isinstance(texts, list):
            alike = db.get(Document, twin) if twin is not None else None
            alike = alike if alike is not None and alike.status != TRASH else None
            document.duplicate_of = alike.id if alike is not None else None
            document.duplicate_kind = similar.SIMILAR if alike is not None else ""
        if document.status == PROCESSING:
            # A document taken over from Paperless is filed as it was there, unless it carried an inbox tag.
            document.status = FILED if data.get("file_as") == FILED else INBOX
        elif document.status == TRASH and never_read:
            # Put in the trash while it waited to be read: restored, it goes to the inbox like any new document.
            document.trashed_status = INBOX
        document.change_seq = changes.next_seq(db)
        # The history is shown to everybody who sees the document: it never says that the person who made it keeps the
        # same file elsewhere (that is on the document and filtered per reader), and it holds no text, only numbers.
        changes.record(db, document.id, PROCESSED, detail=detail)
        sorting.recorded(db, document.id)
        # The files follow the fields, which may have changed while the worker read: one cheap job settles it.
        jobs.enqueue(db, jobs.RENAME, document.id)
        # A long document gets its small pages drawn in the background, behind the documents that wait to be read.
        pages.queue_background(db, document.id, version.n, count)
        db.commit()
    except Exception:
        db.rollback()
        work.clean()
        raise
    work.clean()


def _twin(db: Session, document_id: int, data: dict[str, Any]) -> int | None:
    """The id of the document this one is the same sheet as (``similar.similar_document``), or nothing."""
    texts = data.get("texts")
    document = db.get(Document, document_id)
    found = None
    if document is not None and isinstance(texts, list) and document.duplicate_kind != similar.SAME:
        twin = similar.similar_document(db, document, str(data.get("phash") or ""), "\n".join(texts))
        found = twin.id if twin is not None else None
    db.rollback()
    return found


def _keep_text(db: Session, version: Version, texts: list[str], ocr_pages: int, languages: str) -> None:
    """The text of a version, its pages separated by a form feed; replaces what an earlier run found."""
    body = "\f".join(texts)
    row = db.get(VersionText, version.id)
    if row is None:
        row = VersionText(version_id=version.id, document_id=version.document_id)
        db.add(row)
    row.text = body
    row.pages = len(texts)
    row.ocr_pages = ocr_pages
    row.languages = languages
    row.digest = search_index.text_digest(body)
    row.created_at = clock.now()


TEXT_READ = "text_read"


def read_text(db: Session, document_id: int, attempt: int) -> None:
    """The job ``text``: the text of a document that was read before there was text (a database from before schema 6).
    Only the step of the text runs, on the PDF the document has (the copy made from a picture, else the original); the
    document keeps its status, its pages and its pictures. The searchable copy replaces the PDF made from a picture."""
    document = db.get(Document, document_id)
    if document is None or document.status == PROCESSING:
        return  # gone, or being read anyway
    version = db.scalar(select(Version).where(Version.document_id == document.id,
                                              Version.n == document.current_version))
    kind = _kind_of(version) if version is not None else None
    if version is None or kind in (None, filetypes.XML) or db.get(VersionText, version.id) is not None:
        db.rollback()
        return
    try:
        source = storage.safe_path(version.archive_path if kind != filetypes.PDF else version.original_path)
    except storage.StorageError:
        db.rollback()
        return
    if not source.is_file():
        db.rollback()
        return
    version_id, version_n, pages_before = version.id, version.n, document.pages
    work = Run(work=storage.incoming_path("proc-"), searchable=storage.incoming_path("text-"),
               text=storage.incoming_path("pages-"), source=source, data={"pages": pages_before})
    try:
        outcome = recognize_text(db, document, version, work)
        if not outcome.ok:
            if outcome.retry and attempt < ATTEMPTS:
                raise jobs.Retry(outcome.error)
            raise jobs.GiveUp(outcome.error or "failed")
        data = outcome.data
        changes.write_lock(db)
        document = db.get(Document, document_id)
        version = db.get(Version, version_id)
        if document is None or version is None or version.n != version_n or db.get(VersionText, version_id):
            db.rollback()
            return
        if data.get("searchable") and work.searchable.is_file():
            old = version.archive_path
            target = storage.archive_target(db, document, version)
            version.archive_sha256 = storage.sha256_of(work.searchable)
            storage.adopt(work.searchable, target)
            version.archive_path = target
            if old and old != target:
                storage.remove_files([old])
        texts = list(data.get("texts") or [])
        _keep_text(db, version, texts, int(data.get("ocr_pages") or 0), str(data.get("languages") or ""))
        document.change_seq = changes.next_seq(db)
        changes.record(db, document.id, TEXT_READ, detail={
            "text_pages": sum(1 for page in texts if page.strip()), "ocr_pages": int(data.get("ocr_pages") or 0)})
        jobs.enqueue(db, jobs.RENAME, document.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        work.clean()


def queue_text_reading(db: Session) -> int:
    """A job ``text`` for every document that was read but has no text (the step of schema 6 does the same in SQL)."""
    missing = list(db.scalars(
        select(Document.id).join(Version, (Version.document_id == Document.id)
                                 & (Version.n == Document.current_version))
        .outerjoin(VersionText, VersionText.version_id == Version.id)
        .where(VersionText.version_id.is_(None), Document.status != PROCESSING,
               ~Version.original_path.ilike("%.xml"))
    ))
    for document_id in missing:
        jobs.enqueue(db, jobs.TEXT, document_id)
    db.commit()
    return len(missing)


def _fail(db: Session, document_id: int, code: str) -> None:
    """The document waits in the inbox with the reason; nothing of the failed run stays."""
    changes.write_lock(db)
    document = db.get(Document, document_id)
    if document is None:
        db.rollback()
        return
    document.process_error = code
    if document.status == PROCESSING:
        document.status = INBOX
    elif document.status == TRASH:
        document.trashed_status = INBOX
    document.change_seq = changes.next_seq(db)
    changes.record(db, document.id, PROCESS_FAILED, detail={"error": code})
    db.commit()
    logger.info("A document could not be read document_id=%s error=%s", document_id, code)


def retry(db: Session, uid: int, document_id: int) -> Document:
    """A person asks for another try at a document that could not be read."""
    changes.write_lock(db)
    access = rights.require_document(db, uid, document_id, EDIT)
    document = access.document
    if document.status != INBOX or not document.process_error:
        raise error("nothing_to_retry", "This document was read without a problem.", 409)
    document.status = PROCESSING
    document.process_error = ""
    document.change_seq = changes.next_seq(db)
    changes.record(db, document.id, RETRIED, user_id=uid)
    jobs.enqueue(db, jobs.PROCESS, document.id)
    db.commit()
    return document


def waiting(db: Session) -> tuple[int, int]:
    """(being read, waiting) for the settings page."""
    running = len(db.scalars(select(Job.id).where(Job.kind == jobs.PROCESS, Job.state == "running")).all())
    queued = len(db.scalars(select(Job.id).where(Job.kind == jobs.PROCESS, Job.state == "queued")).all())
    return running, queued


__all__ = ["ATTEMPTS", "Outcome", "retry", "run", "spawn", "waiting"]
