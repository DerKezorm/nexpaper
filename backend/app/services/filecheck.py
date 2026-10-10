"""Checking the files: does every document still have its files, and are they the ones that were put there?

Each version of a document has a checksum of its original (``Version.sha256``, noted when the file came in and never
changed) and of its searchable copy (``Version.archive_sha256``, noted when the copy was put in place; for a copy that
has none yet, the first check notes it). Once a week, and on the operator's request, every file is read and compared.
A document whose file is gone gets ``files_state = "missing"``, one whose file does not match ``"changed"``; the
archive, the inbox and the document page show a sign, the history of the document gets a line, and the operators are
told once per run that found something new. A document that is whole again loses its sign at the next check.

**Gently.** The check runs in portions: at most ``PORTION_FILES`` files and ``PORTION_BYTES`` bytes, then it waits as
long as the portion took (at least ``PAUSE_MIN`` seconds), so the disk is busy for a third of the time at most while a
check runs, and the server answers all the while. Where the check stands is kept in the database (the setting
``files_check``): a stop in between is picked up at the same document. The portion itself is one function without
waiting (``run_portion``); the loop (``run_forever``) only calls it and sleeps.

**Safe against other work.** A document is looked at under the lock the page tools and the renaming of files take
(``storage.files_of``); one that is being worked on right now is skipped and counted as such, never read half moved.
Nothing outside ``dokumente/`` is read: a path in the database goes through ``storage.safe_path``, and a path that does
not pass counts as missing.

A document still being read, and a version that is being made, are not looked at (their files are not final).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import clock
from ..db import SessionLocal
from ..models import PROCESSING, Document, Version, VersionInfo
from . import changes, jobs, settings_service, storage, tell

logger = logging.getLogger("nexpaper.filecheck")

KEY = "files_check"
#: A document that lost a file, or whose file changed, and the line in its history that says so.
MISSING, CHANGED = "missing", "changed"
#: Only for ``look`` with a deadline: the time ran out while the file was read, nothing is known of it.
UNREAD = "unread"
EVENT_MISSING, EVENT_CHANGED, EVENT_WHOLE = "files_missing", "files_changed", "files_whole"
#: A portion: this many files or this many bytes, whichever comes first (the file that crosses the line is finished).
PORTION_FILES = 40
PORTION_BYTES = 192 * 1024 * 1024
#: After a portion the loop rests as long as it worked, but at least this long and at most ``PAUSE_MAX`` seconds.
PAUSE_MIN = 1.0
PAUSE_MAX = 20.0
#: How often a check is due, and how often an idle loop looks.
EVERY_DAYS = 7
TICK_SECONDS = 30
#: How long a check waits for a document that is being worked on, in seconds (none: it is skipped at once).
WAIT_FOR_DOCUMENT = 0.0
#: Where a tap leads: the settings, backups and storage (the cards of the check and of the storage are there).
PATH = "/einstellungen?tab=backups"
_CHUNK = 1024 * 1024

DEFAULT_STATE: dict[str, Any] = {
    "running": False, "started_at": None, "cursor": 0, "total": 0, "documents": 0, "files": 0, "bytes": 0,
    "problems": 0, "new_problems": 0, "skipped": 0, "finished_at": None, "last_files": 0, "last_documents": 0,
    "last_problems": 0, "last_skipped": 0,
}


def state(db: Session) -> dict[str, Any]:
    stored = settings_service.get(db, KEY)
    merged = dict(DEFAULT_STATE)
    if isinstance(stored, dict):
        merged.update({key: value for key, value in stored.items() if key in DEFAULT_STATE})
    return merged


def _save(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    merged = state(db)
    merged.update(values)
    settings_service.save(db, {KEY: merged})
    return merged


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=clock.now().tzinfo)


def status(db: Session) -> dict[str, Any]:
    """What the storage card shows: a check running (with how far it is), when the last one ended and what it found,
    and how many documents carry a sign now."""
    current = state(db)
    total = int(current["total"] or 0)
    done = int(current["documents"] or 0)
    finished = _parse(current["finished_at"])
    flagged = int(db.scalar(select(func.count()).select_from(Document).where(Document.files_state != "")) or 0)
    return {
        "running": bool(current["running"]),
        "documents_total": total if current["running"] else 0,
        "documents_done": min(done, total) if current["running"] else 0,
        "last_finished_at": finished.isoformat() if finished else None,
        "last_files": int(current["last_files"] or 0),
        "last_documents": int(current["last_documents"] or 0),
        "last_problems": int(current["last_problems"] or 0),
        "last_skipped": int(current["last_skipped"] or 0),
        "flagged_documents": flagged,
        "every_days": EVERY_DAYS,
    }


def start(db: Session, *, by_hand: bool = True) -> bool:
    """Begins a check (the operator's button, or the weekly time). False when one is running already."""
    current = state(db)
    if current["running"]:
        db.rollback()
        return False
    total = int(db.scalar(select(func.count()).select_from(Document)) or 0)
    _save(db, {
        "running": True, "started_at": clock.now().isoformat(), "cursor": 0, "total": total, "documents": 0,
        "files": 0, "bytes": 0, "problems": 0, "new_problems": 0, "skipped": 0,
    })
    logger.info("Check of the files begins documents=%s by_hand=%s", total, by_hand)
    return True


def due(db: Session, *, now: datetime | None = None) -> bool:
    """Whether the weekly check is due: never done, or the last one ended a week ago or more."""
    current = state(db)
    if current["running"]:
        return False
    last = _parse(current["finished_at"])
    if last is None:
        return True
    return (now or clock.now()) - last >= timedelta(days=EVERY_DAYS)


class _Seen:
    """What looking at the files of one document found."""

    def __init__(self) -> None:
        self.state = ""
        self.files = 0
        self.bytes = 0
        self.skipped = False
        #: The checksums of searchable copies noted for the first time: ``(version id, path, checksum)``.
        self.noted: list[tuple[int, str, str]] = []

    def worse(self, found: str) -> None:
        if found == MISSING or not self.state:
            self.state = found


class OutOfTime(Exception):
    """The time given for reading a file ran out before its end."""


def _hash(path: Path, deadline: float | None = None) -> tuple[str, int]:
    import hashlib

    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while block := handle.read(_CHUNK):
            size += len(block)
            digest.update(block)
            if deadline is not None and time.monotonic() > deadline:
                raise OutOfTime
    return digest.hexdigest(), size


def look(rel: str, expected: str, *, compare: bool = True, deadline: float | None = None) -> tuple[str, str, int]:
    """One file: ``("ok" | MISSING | CHANGED | UNREAD, checksum, bytes read)``. ``expected`` empty: nothing to compare
    to. ``compare`` false only looks whether the file is there and reads nothing (the trial run of a backup, when its
    time for reading ran out). ``deadline`` (a ``time.monotonic()`` value): a file still being read when it passes is
    given up, ``UNREAD``, however large it is."""
    try:
        path = storage.safe_path(rel)
    except storage.StorageError:
        return MISSING, "", 0
    try:
        if not path.is_file():
            return MISSING, "", 0
        if not compare:
            return "ok", "", 0
        digest, size = _hash(path, deadline)
    except OutOfTime:
        return UNREAD, "", 0
    except OSError:
        return MISSING, "", 0
    if expected and digest != expected:
        return CHANGED, digest, size
    return "ok", digest, size


def look_at(rows: list[Version]) -> _Seen:
    """The files of the versions of one document. Does not write: the caller holds the lock of the document."""
    seen = _Seen()
    for version in rows:
        found, _digest, size = look(version.original_path, version.sha256)
        seen.files += 1
        seen.bytes += size
        if found != "ok":
            seen.worse(found)
        if version.archive_path:
            found, digest, size = look(version.archive_path, version.archive_sha256)
            seen.files += 1
            seen.bytes += size
            if found != "ok":
                seen.worse(found)
            elif not version.archive_sha256:
                seen.noted.append((version.id, version.archive_path, digest))
    return seen


def _versions_of(db: Session, document_id: int) -> list[Version]:
    """The versions whose files are final: a version still being made is not looked at."""
    pending = select(VersionInfo.version_id).where(VersionInfo.document_id == document_id,
                                                   VersionInfo.state != "ready")
    return list(db.scalars(select(Version).where(Version.document_id == document_id, Version.id.not_in(pending))
                           .order_by(Version.n)))


def _note(db: Session, document_id: int, seen: _Seen) -> bool:
    """Writes what was found: the checksums noted for the first time, the sign of the document and a line in its
    history when the sign changed. Returns whether the document is newly flagged."""
    changes.write_lock(db)
    before = db.scalar(select(Document.files_state).where(Document.id == document_id))
    if before is None:
        db.rollback()
        return False  # deleted while it was looked at
    for version_id, path, digest in seen.noted:
        # Only if the copy is still the one that was read: a copy put in place meanwhile keeps its own checksum.
        db.execute(update(Version).where(Version.id == version_id, Version.archive_path == path,
                                         Version.archive_sha256 == "").values(archive_sha256=digest))
    flagged = False
    if seen.state != before:
        db.execute(update(Document).where(Document.id == document_id).values(files_state=seen.state))
        action = EVENT_WHOLE if not seen.state else (EVENT_MISSING if seen.state == MISSING else EVENT_CHANGED)
        changes.record(db, document_id, action, detail=None)
        flagged = bool(seen.state)
    db.commit()
    return flagged


def recheck_soon(db: Session, document: Document) -> None:
    """In the caller's transaction: a document that carries a sign is looked at again at once, by a job of its own (it
    waits for the files to be free), so that the sign goes when the cause did: a new version, a version put away, the
    document back from the trash. Nothing for a document in order: nothing a change can add is wrong, and the weekly
    check sees the rest."""
    if document.files_state:
        jobs.enqueue(db, jobs.FILES, document.id)


def recheck(document_id: int) -> str | None:
    """The files of this one document, now, and its sign afterwards (empty: in order). Raises ``storage.DocumentBusy``
    while a tool works on its files (the job tries again next round); ``None`` for a document that is gone. One still
    being read is not looked at (its files are not final)."""
    with SessionLocal() as db:
        found = db.execute(select(Document.status, Document.files_state).where(Document.id == document_id)).first()
        db.rollback()
        if found is None:
            return None
        if found[0] == PROCESSING:
            return str(found[1])
        with storage.files_of([document_id], WAIT_FOR_DOCUMENT):
            rows = _versions_of(db, document_id)
            db.rollback()
            seen = look_at(rows)
            _note(db, document_id, seen)
        return seen.state


def run_portion(db: Session, *, max_files: int = PORTION_FILES, max_bytes: int = PORTION_BYTES) -> bool:
    """The next portion of a running check. Returns True when the check is finished (or none was running)."""
    current = state(db)
    if not current["running"]:
        db.rollback()
        return True
    cursor = int(current["cursor"] or 0)
    files, read_bytes = int(current["files"]), int(current["bytes"])
    documents, problems = int(current["documents"]), int(current["problems"])
    new_problems, skipped = int(current["new_problems"]), int(current["skipped"])
    done_files = done_bytes = 0
    ids = list(db.execute(select(Document.id, Document.status).where(Document.id > cursor).order_by(Document.id)
                          .limit(max_files)))
    db.rollback()
    reached_end = True
    for document_id, status_of in ids:
        if done_files >= max_files or done_bytes >= max_bytes:
            reached_end = False
            break
        cursor = document_id
        documents += 1
        if status_of == PROCESSING:
            skipped += 1
            continue
        try:
            with storage.files_of([document_id], WAIT_FOR_DOCUMENT):
                rows = _versions_of(db, document_id)
                db.rollback()
                seen = look_at(rows)
                new = _note(db, document_id, seen)
        except storage.DocumentBusy:
            skipped += 1
            continue
        done_files += seen.files
        done_bytes += seen.bytes
        files += seen.files
        read_bytes += seen.bytes
        if seen.state:
            problems += 1
        if new:
            new_problems += 1
    finished = False
    if reached_end:
        # A full page may have more behind it.
        finished = len(ids) < max_files or db.scalar(select(Document.id).where(Document.id > cursor).limit(1)) is None
        db.rollback()
    values: dict[str, Any] = {"cursor": cursor, "documents": documents, "files": files, "bytes": read_bytes,
                              "problems": problems, "new_problems": new_problems, "skipped": skipped}
    if finished:
        values.update({
            "running": False, "finished_at": clock.now().isoformat(), "last_files": files, "last_documents": documents,
            "last_problems": problems, "last_skipped": skipped,
        })
    _save(db, values)
    if finished:
        logger.info("Check of the files done documents=%s files=%s problems=%s new=%s skipped=%s", documents, files,
                    problems, new_problems, skipped)
        if new_problems:
            _tell_operators(new_problems, problems)
    return finished


TEXTS = {
    "de": ("Dateien prüfen: Auffälligkeiten", "{count} Dokumente haben fehlende oder veränderte Dateien."),
    "en": ("Checking the files: problems found", "{count} documents have missing or changed files."),
}


def _tell_operators(new: int, total: int) -> None:
    count = max(new, total)
    tell.operator(tell.Notice(
        texts={lang: (title, body.format(count=count)) for lang, (title, body) in TEXTS.items()},
        url=PATH, tag="files-check",
        mail_subject="nexpaper: files are missing or changed",
        mail_body=(f"The check of the files found {count} documents with missing or changed files "
                   "(new since the last check: " + str(new) + ").\n\nSee the storage card in the settings: {where}\n"),
    ))


def run_once(*, max_files: int = PORTION_FILES, max_bytes: int = PORTION_BYTES) -> tuple[bool, float]:
    """One step of the loop: starts the weekly check when due, runs a portion when one is running. Returns whether a
    portion ran and how long it took."""
    started = time.monotonic()
    with SessionLocal() as db:
        if not state(db)["running"]:
            if not due(db):
                db.rollback()
                return False, 0.0
            if not start(db, by_hand=False):
                return False, 0.0
        run_portion(db, max_files=max_files, max_bytes=max_bytes)
    return True, time.monotonic() - started


def pause_after(seconds: float) -> float:
    return min(PAUSE_MAX, max(PAUSE_MIN, seconds))


async def run_forever(stop: asyncio.Event) -> None:
    """The loop beside the others. An idle server looks every ``TICK_SECONDS``; a running check goes on with the
    next portion after a rest as long as the last one took."""
    while not stop.is_set():
        wait = float(TICK_SECONDS)
        try:
            ran, took = await asyncio.to_thread(run_once)
            if ran:
                wait = pause_after(took)
        except Exception:
            logger.exception("Check of the files failed")
        try:
            await asyncio.wait_for(stop.wait(), wait)
            return
        except TimeoutError:
            continue
