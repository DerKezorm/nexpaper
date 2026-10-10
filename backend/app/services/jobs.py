"""Work for the background, kept in a table so that it survives a restart.

The kinds: ``rename`` (the files of a document follow its fields, ``services/storage.py``), ``delete_files``
(the files of a document that was deleted for good), ``process`` (a document that has just come in is read, in a
worker process: ``services/processing.py``), ``text`` (the text of a document read before there was text), ``pages``
(the small pictures of a long document, drawn after it was read, ``services/pages.py``) and ``index`` (the search index
of many documents at once, ``services/search_index.py``). A job is claimed in one statement (the database lets exactly
one claimer through), tried up to ``ATTEMPTS`` times (``process``: its own number), and a job left ``running`` by a
stopped server goes back to ``queued`` at the next start. At most one job of a kind waits for the same document (a
unique index), so a document renamed ten times in a row is renamed once.

Two loops run side by side: one for the quick jobs and one for ``process``, ``text`` and ``pages``, which may take
minutes and must not hold up a rename. Each loop does one job at a time, so one document is read at a time; ``pages``
runs only while no document waits to be read.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .. import clock
from ..db import SessionLocal
from ..models import Job
from . import storage

logger = logging.getLogger("nexpaper.jobs")

#: Set when the server stops, so that a worker process that is running is stopped with it.
stopping = threading.Event()

RENAME = "rename"
DELETE_FILES = "delete_files"
PROCESS = "process"
#: The search index of documents that changed in large numbers at once, or that have none yet
#: (``services/search_index.py``).
INDEX = "index"
#: One document looked at again by the check of the files, because what its sign was about may be gone
#: (``filecheck.recheck_soon``).
FILES = "files"
QUICK = (RENAME, DELETE_FILES, INDEX, FILES)
#: The text of a document read before there was text (``processing.read_text``): a worker run like ``process``.
TEXT = "text"
#: The small pictures of the pages of a long document, drawn after it was read (``pages.draw_in_background``). It runs
#: in the loop of the slow jobs, but only while no document waits to be read: new documents go first.
PAGES = "pages"
#: An uploaded version of a document, read like a new document (``pagetools.run_version``); ``ref`` is the
#: version's id.
VERSION = "version"
#: The blank separator pages of a document in the inbox that was read without looking for them
#: (``separators.run_job``).
BLANKS = "blanks"
READING = (PROCESS, TEXT, VERSION, BLANKS)
SLOW = (PROCESS, TEXT, VERSION, BLANKS, PAGES)
#: The Paperless import (``services/paperless.py``, one run at a time, ``ref`` 0) and the ZIPs of exports
#: (``services/exports.py``, ``ref`` the export): each in a loop of its own, as they may take hours and minutes.
IMPORT = "import"
EXPORT = "export"
#: The AI's proposals for a new document (``services/ai_proposals.py``): in a loop of its own, as a request may take
#: minutes and must hold up neither the reading of documents nor a rename. Tried once.
PROPOSE = "propose"
ATTEMPTS = 5
#: How often the loop looks for work, and how often it empties the trash and removes old change markers.
POLL_SECONDS = 2
TRASH_EVERY = 600


class Retry(Exception):
    """A job that failed for a reason another try may cure (the time limit, a crash): it waits to be run again until it
    has used its tries."""


class Interrupted(Exception):
    """The server is stopping: the job is put back as it was (no try used up) and runs at the next start."""


class GiveUp(Exception):
    """A job that failed on its last try for a reason it names: it stays failed."""


def enqueue(db: Session, kind: str, ref: int, payload: Any = None) -> None:
    """A job in the caller's transaction; a no-op while one of the same kind already waits for the same ``ref``."""
    db.execute(sqlite_insert(Job).values(kind=kind, ref=ref, payload=payload, state="queued", created_at=clock.now())
               .on_conflict_do_nothing())


def recover(db: Session) -> None:
    """At start: what a stopped server left ``running`` waits again (or is dropped when the same is already waiting)."""
    db.execute(text(
        "UPDATE jobs SET state = 'queued' WHERE state = 'running' AND NOT EXISTS ("
        "SELECT 1 FROM jobs q WHERE q.state = 'queued' AND q.kind = jobs.kind AND q.ref = jobs.ref)"
    ))
    db.execute(update(Job).where(Job.state == "running").values(state="done", finished_at=clock.now()))
    db.commit()
    from . import search_index

    # A document whose index entry lags behind its last change (a stop in between, a database from before the index).
    search_index.queue_if_stale(db)
    from . import separators

    # The documents in the inbox that were read without looking for blank separator pages (before block B5).
    separators.queue_missing(db)


def _fair_choice(db: Session, skip: set[int], kinds: tuple[str, ...]) -> int | None:
    """Among the waiting jobs that read documents, the oldest one of the account that was served longest ago (an account
    that was never served first): the people of one server take turns, and a person who uploads a thousand files does
    not make everybody else wait for them all. A job ``version`` names a version, the others a document."""
    from ..models import Document, Version

    waiting = db.execute(select(Job.id, Job.kind, Job.ref).where(
        Job.state == "queued", Job.kind.in_(kinds), Job.id.not_in(skip)).order_by(Job.id).limit(1000)).all()
    if not waiting:
        return None
    version_refs = {ref for _id, kind, ref in waiting if kind == VERSION}
    of_version = dict(db.execute(select(Version.id, Version.document_id).where(Version.id.in_(version_refs))).all()) \
        if version_refs else {}

    def document_of(kind: str, ref: int) -> int | None:
        return of_version.get(ref) if kind == VERSION else ref

    refs = {document_of(kind, ref) for _id, kind, ref in waiting} - {None}
    owners = dict(db.execute(select(Document.id, Document.owner_id).where(Document.id.in_(refs))).all())
    served: dict[int, datetime] = {}
    plain = [kind for kind in kinds if kind != VERSION]
    queries = []
    if plain:
        queries.append(select(Document.owner_id, func.max(Job.started_at)).join(Document, Document.id == Job.ref)
                       .where(Job.kind.in_(plain), Job.started_at.is_not(None),
                              Document.owner_id.in_(set(owners.values()))).group_by(Document.owner_id))
    if VERSION in kinds:
        queries.append(select(Document.owner_id, func.max(Job.started_at)).join(Version, Version.id == Job.ref)
                       .join(Document, Document.id == Version.document_id)
                       .where(Job.kind == VERSION, Job.started_at.is_not(None),
                              Document.owner_id.in_(set(owners.values()))).group_by(Document.owner_id))
    for query in queries:
        for owner, started in db.execute(query).all():
            if owner is not None and (owner not in served or started > served[owner]):
                served[owner] = started
    oldest = datetime.min.replace(tzinfo=UTC)

    def rank(job: Any) -> tuple[datetime, int]:
        last = served.get(owners.get(document_of(job[1], job[2])))
        return (last.replace(tzinfo=last.tzinfo or UTC) if last else oldest, job[0])

    return min(waiting, key=rank)[0]


def _claim(db: Session, skip: set[int], kinds: tuple[str, ...]) -> Job | None:
    """The next waiting job of these kinds that was not tried in this round, marked running in the same statement: the
    oldest, but for the jobs that read documents the one whose account has waited longest (``_fair_choice``)."""
    if any(kind in kinds for kind in (*READING, PAGES)):
        before = tuple(kind for kind in kinds if kind != PAGES)
        chosen = _fair_choice(db, skip, before) if before else None
        if chosen is None and PAGES in kinds:
            # Pictures drawn ahead of time come last: only when no document of anybody waits to be read.
            chosen = db.scalar(select(Job.id).where(Job.state == "queued", Job.kind == PAGES, Job.id.not_in(skip))
                               .order_by(Job.id).limit(1))
        if chosen is None:
            return None
        row = db.execute(update(Job).where(Job.id == chosen, Job.state == "queued")
                         .values(state="running", started_at=clock.now(), attempts=Job.attempts + 1)
                         .returning(Job.id)).first()
        db.commit()
        return db.get(Job, row[0]) if row else None
    row = db.execute(
        update(Job).where(Job.id == select(Job.id).where(Job.state == "queued", Job.kind.in_(kinds),
                                                         Job.id.not_in(skip)).order_by(Job.id)
                          .limit(1).scalar_subquery())
        .values(state="running", started_at=clock.now(), attempts=Job.attempts + 1).returning(Job.id)
    ).first()
    db.commit()
    return db.get(Job, row[0]) if row else None


def _run(db: Session, job: Job) -> None:
    if job.kind == RENAME:
        storage.run_rename(db, job.ref)
    elif job.kind == DELETE_FILES:
        payload = job.payload or {}
        storage.remove_files(list(payload.get("paths", [])))
        if payload.get("cache_of"):
            from . import pages

            pages.remove(int(payload["cache_of"]))
    elif job.kind == PROCESS:
        from . import processing

        processing.run(db, job.id, job.ref, job.attempts)
    elif job.kind == TEXT:
        from . import processing

        processing.read_text(db, job.ref, job.attempts)
    elif job.kind == VERSION:
        from . import pagetools

        pagetools.run_version(db, job.ref, job.attempts)
    elif job.kind == BLANKS:
        from . import separators

        separators.run_job(db, job.ref)
    elif job.kind == PAGES:
        from . import pages

        pages.draw_in_background(db, job.ref, job.payload)
    elif job.kind == INDEX:
        from . import search_index

        search_index.run_job(db)
    elif job.kind == FILES:
        from . import filecheck

        filecheck.recheck(job.ref)
    elif job.kind == IMPORT:
        from . import paperless

        paperless.run_job(db, job.attempts)
    elif job.kind == EXPORT:
        from . import exports

        exports.run_job(db, job.ref)
    elif job.kind == PROPOSE:
        from . import ai_proposals

        ai_proposals.run_job(db, job.ref)
    else:
        raise storage.StorageError("unknown job")


def run_pending(limit: int = 1000, kinds: tuple[str, ...] = QUICK + SLOW + (IMPORT, EXPORT, PROPOSE)) -> int:
    """Runs the waiting jobs of these kinds, oldest first, until none is left or ``limit`` ran. Returns how many ran."""
    ran = 0
    tried: set[int] = set()
    while ran < limit:
        with SessionLocal() as db:
            job = _claim(db, tried, kinds)
            if job is None:
                return ran
            tried.add(job.id)
            ran += 1
            try:
                _run(db, job)
            except Interrupted:
                db.rollback()
                db.execute(update(Job).where(Job.id == job.id).values(state="queued", attempts=Job.attempts - 1))
                db.commit()
                return ran
            except storage.DocumentBusy:
                # A page tool works on the files of the document: the job waits for the next round, no try used up
                # (or goes, when the tool queued the same job meanwhile).
                db.rollback()
                db.execute(text(
                    "UPDATE jobs SET state = CASE WHEN EXISTS (SELECT 1 FROM jobs q WHERE q.state = 'queued' "
                    "AND q.kind = jobs.kind AND q.ref = jobs.ref) THEN 'done' ELSE 'queued' END, "
                    "attempts = attempts - 1 WHERE id = :id"), {"id": job.id})
                db.commit()
            except Exception as exc:  # noqa: BLE001 - a job that fails must not stop the others
                db.rollback()
                # A job that is not given up on waits for the next round.
                failed = isinstance(exc, GiveUp) or job.attempts >= ATTEMPTS
                name = str(exc)[:60] if isinstance(exc, Retry | GiveUp) and str(exc) else type(exc).__name__
                logger.warning("Job failed kind=%s ref=%s attempt=%s error=%s", job.kind, job.ref, job.attempts, name)
                db.execute(update(Job).where(Job.id == job.id).values(
                    state="failed" if failed else "queued", error=name, finished_at=clock.now()))
                db.commit()
            else:
                db.execute(update(Job).where(Job.id == job.id).values(state="done", finished_at=clock.now(), error=""))
                db.commit()
    return ran


def waiting(db: Session) -> int:
    return len(db.scalars(select(Job.id).where(Job.state.in_(("queued", "running")))).all())


async def _loop(stop: asyncio.Event, kinds: tuple[str, ...], every: float, extra: bool = False) -> None:
    last_trash = 0.0
    while not stop.is_set():
        try:
            await asyncio.to_thread(run_pending, 50, kinds)
            if extra and clock.monotonic() - last_trash > TRASH_EVERY:
                last_trash = clock.monotonic()
                await asyncio.to_thread(housekeeping)
        except Exception:
            logger.exception("Background run failed")
        try:
            await asyncio.wait_for(stop.wait(), every)
        except TimeoutError:
            continue


def housekeeping() -> None:
    """Now and then: the trash, old change markers, uploads that ran out."""
    from . import changes, documents, uploads

    with SessionLocal() as db:
        documents.purge_expired(db)
    with SessionLocal() as db:
        changes.prune_markers(db)
    with SessionLocal() as db:
        uploads.sweep(db)
    with SessionLocal() as db:
        from . import limits, pages

        pages.trim(limits.current(db).cache_bytes)
    with SessionLocal() as db:
        from . import exports, paperless

        exports.sweep(db)
        paperless.sweep_staged(db)
    from . import pagetools

    pagetools.sweep_scratch()


async def run_forever(stop: asyncio.Event) -> None:
    stopping.clear()
    with SessionLocal() as db:
        recover(db)
    try:
        await asyncio.gather(_loop(stop, QUICK, POLL_SECONDS, extra=True), _loop(stop, SLOW, POLL_SECONDS),
                             _loop(stop, (IMPORT,), POLL_SECONDS), _loop(stop, (EXPORT,), POLL_SECONDS),
                             _loop(stop, (PROPOSE,), POLL_SECONDS))
    finally:
        stopping.set()
