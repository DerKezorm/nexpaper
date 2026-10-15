"""Expired documents into the trash by themselves: a switch per kind, off from the start.

**What it does.** Once a day (the loop looks every ``TICK_SECONDS``) the filed documents of a kind with the switch on
whose ``keep_until`` has passed go to the trash, the same trash a person puts documents in, with its 30 days to get
them back. Nothing is ever deleted for good here; the trash empties itself as it always did.

**Only once per document.** A document the task put in the trash carries the history line ``auto_trashed``; one with
that line is never taken again, so a person who restores it keeps it (until they put it away themselves). The same line
is the proof for the weekly mail ("N documents were put in the trash").

**Restart, clock and two runs at once.** Each batch is chosen and written under the write lock, so two runs at the same
time, a restart in the middle and a clock that jumps back never take a document twice (its status has changed by the
time the second one looks). What the clock says only decides which documents are over.

**The brake.** At most ``DAY_LIMIT`` documents per day; the rest waits for the next day. The count of the day is kept in
the database (``counters``), so a restart does not give a second day's worth, and a clock that jumps back does not
either (a day that is not later than the one counted goes on with its count).

**Who.** Nobody: the history line has no person, so the interface names nexpaper itself.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import date as Date
from datetime import datetime

from sqlalchemy import ColumnElement, and_, exists, func, select
from sqlalchemy.orm import Session

from .. import clock
from ..models import EDIT, FILED, MANAGE, TRASH, Counter, Document, DocumentDate, Event, Kind, VaultMember
from . import changes, deadlines
from .keeping import KEEP

logger = logging.getLogger("nexpaper.autotrash")

#: The history line of a document the task put in the trash.
AUTO_TRASHED = "auto_trashed"
#: Documents put in the trash per day, at most.
DAY_LIMIT = 500
#: Documents written in one transaction.
BATCH = 100
TICK_SECONDS = 3600
#: The counters of the day: its number (``Date.toordinal``) and how many were done on it.
DAY_COUNTER = "auto_trash_day"
DONE_COUNTER = "auto_trash_done"


def _over(today: Date) -> list[ColumnElement[bool]]:
    """Filed, of a kind with the switch on and a keeping time, term over, not taken before."""
    return [
        Document.status == FILED,
        Kind.id == Document.kind_id, Kind.auto_trash.is_(True), Kind.keep_years.is_not(None),
        DocumentDate.document_id == Document.id, DocumentDate.kind == KEEP, DocumentDate.date < today,
        ~exists().where(Event.document_id == Document.id, Event.action == AUTO_TRASHED),
    ]


def _counter(db: Session, name: str) -> int | None:
    return db.scalar(select(Counter.value).where(Counter.name == name))


def _store(db: Session, name: str, value: int) -> None:
    row = db.get(Counter, name)
    if row is None:
        db.add(Counter(name=name, value=value))
    else:
        row.value = value


def due(db: Session, kind_id: int, today: Date, visible: ColumnElement[bool]) -> int:
    """How many filed documents of the kind are over their keeping time now (``visible``: the part of them the person
    may see), which is what the switch would put in the trash at its next run."""
    return int(db.scalar(select(func.count()).select_from(Document).join(
        DocumentDate, DocumentDate.document_id == Document.id).where(
        Document.kind_id == kind_id, Document.status == FILED, DocumentDate.kind == KEEP, DocumentDate.date < today,
        visible)) or 0)


def run(db: Session, today: Date | None = None, *, limit: int | None = None) -> int:
    """Puts the documents that are over into the trash, up to what is left of the day's ``limit``. Returns how many."""
    today = today or deadlines.server_today()
    limit = DAY_LIMIT if limit is None else limit
    total = 0
    while True:
        changes.write_lock(db)
        counted_day = _counter(db, DAY_COUNTER)
        done = _counter(db, DONE_COUNTER) or 0
        if counted_day is None or today.toordinal() > counted_day:
            counted_day, done = today.toordinal(), 0
        room = limit - done
        if room <= 0:
            db.rollback()
            break
        ids = list(db.scalars(select(Document.id).where(and_(*_over(today)))
                              .order_by(DocumentDate.date, Document.id).limit(min(room, BATCH))))
        if not ids:
            db.rollback()
            break
        first = changes.next_seqs(db, len(ids))
        rows = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_(ids)))}
        ended = dict(db.execute(select(DocumentDate.document_id, DocumentDate.date).where(
            DocumentDate.document_id.in_(ids), DocumentDate.kind == KEEP)).all())
        now = clock.now()
        for offset, document_id in enumerate(ids):
            document = rows[document_id]
            document.trashed_status = FILED
            document.status = TRASH
            document.trashed_at = now
            document.change_seq = first + offset
            changes.record(db, document_id, AUTO_TRASHED, detail={"keep_until": ended[document_id].isoformat()})
        _store(db, DAY_COUNTER, counted_day)
        _store(db, DONE_COUNTER, done + len(ids))
        db.commit()
        total += len(ids)
    if total:
        logger.info("Expired documents put in the trash by themselves count=%s", total)
    return total


def trashed_since(db: Session, uid: int, since: datetime, *, where: Sequence[ColumnElement[bool]] = ()) -> int:
    """How many documents the task put in the trash since ``since`` in the vaults where ``uid`` may change things (the
    weekly mail's line). ``where`` narrows the documents (the weekly mail leaves out the vaults a person muted)."""
    editable = select(VaultMember.vault_id).where(VaultMember.user_id == uid, VaultMember.right.in_((EDIT, MANAGE)))
    return int(db.scalar(select(func.count(func.distinct(Event.document_id))).select_from(Event).join(
        Document, Document.id == Event.document_id).where(
        Event.action == AUTO_TRASHED, Event.at >= since, Document.vault_id.in_(editable),
        *where)) or 0)


def run_once() -> int:
    from ..db import SessionLocal

    with SessionLocal() as db:
        return run(db)


async def run_forever(stop: asyncio.Event) -> None:
    """The loop beside the others: every ``TICK_SECONDS``."""
    while not stop.is_set():
        try:
            await asyncio.to_thread(run_once)
        except Exception:
            logger.exception("Putting expired documents in the trash failed")
        try:
            await asyncio.wait_for(stop.wait(), TICK_SECONDS)
            return
        except TimeoutError:
            continue


__all__ = ["AUTO_TRASHED", "BATCH", "DAY_LIMIT", "due", "run", "run_forever", "run_once", "trashed_since"]
