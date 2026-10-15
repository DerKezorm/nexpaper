"""Expired documents into the trash by themselves: a switch per kind, off from the start.

**What it does.** Once a day, at night (``HOUR`` o'clock in the server's time), the filed documents of a kind with the
switch on whose ``keep_until`` has passed go to the trash, the same trash a person puts documents in, with its 30 days
to get them back. Nothing is ever deleted for good here; the trash empties itself as it always did.

**When.** The loop looks every ``TICK_SECONDS`` at most, but only does the work when the night's ``HOUR`` o'clock has
come and has not been done yet (``tick``): the number of the last night done is kept in the database (``counters``).
A start that finds a night missed (the server was off at ``HOUR`` o'clock) catches up at once; a start that finds
nothing recorded (the first one) only notes the night and waits for the next one, so installing the update or
switching a kind on never puts anything in the trash on the spot.

**Only once per document.** A document the task put in the trash carries the history line ``auto_trashed``; one with
that line is never taken again, so a person who restores it keeps it (until they put it away themselves). The same line
is the proof for the weekly mail ("N documents were put in the trash").

**Restart, clock and two runs at once.** Each batch is chosen and written under the write lock, so two runs at the same
time, a restart in the middle and a clock that jumps back never take a document twice (its status has changed by the
time the second one looks). What the clock says only decides which documents are over.

**The brake.** At most ``DAY_LIMIT`` documents per day; the rest waits for the next day. The count of the day is kept in
the database (``counters``), so a restart does not give a second day's worth. When the counted day lies after today (the
clock was ahead and has been set right), the run says so in the log as a warning and starts the count of today anew
instead of doing nothing until the clock catches up; each document is taken once anyway.

**Who.** Nobody: the history line has no person, so the interface names nexpaper itself.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import date as Date
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, and_, exists, func, select
from sqlalchemy.orm import Session

from .. import clock
from ..models import EDIT, FILED, INBOX, MANAGE, TRASH, Counter, Document, DocumentDate, Event, Kind, VaultMember
from . import changes, deadlines
from .keeping import KEEP

logger = logging.getLogger("nexpaper.autotrash")

#: The history line of a document the task put in the trash.
AUTO_TRASHED = "auto_trashed"
#: Documents put in the trash per day, at most.
DAY_LIMIT = 500
#: Documents written in one transaction.
BATCH = 100
#: The loop wakes at least this often, to see whether the night has come (and to notice a clock that was set).
TICK_SECONDS = 3600
#: The hour of the night (the server's time) the work is done in.
HOUR = 3
#: The counters of the day: its number (``Date.toordinal``) and how many were done on it.
DAY_COUNTER = "auto_trash_day"
DONE_COUNTER = "auto_trash_done"
#: The number (``Date.toordinal``) of the day whose ``HOUR`` o'clock was the last one done.
NIGHT_COUNTER = "auto_trash_night"


def over(today: Date, *, statuses: tuple[str, ...] = (FILED,), switch: bool = True) -> list[ColumnElement[bool]]:
    """The one condition for "the run will put this document in the trash": in one of ``statuses`` (the run takes the
    filed ones; a document in the inbox is asked with ``(FILED, INBOX)`` because it will be taken once it is filed), of
    a kind with a keeping time and (``switch``) the switch on, ``keep_until`` before ``today``, and not taken before (a
    document the task put in the trash once and a person restored stays). Every place that says "this one goes by
    itself" or counts what would go asks this, so none can say otherwise than the run does."""
    clauses = [
        Document.status.in_(statuses),
        Kind.id == Document.kind_id, Kind.keep_years.is_not(None),
        DocumentDate.document_id == Document.id, DocumentDate.kind == KEEP, DocumentDate.date < today,
        ~exists().where(Event.document_id == Document.id, Event.action == AUTO_TRASHED),
    ]
    if switch:
        clauses.append(Kind.auto_trash.is_(True))
    return clauses


def pending(db: Session, document_ids: Sequence[int], today: Date) -> set[int]:
    """Of these documents, the ones the run will put in the trash (or will, once filed): see ``over``."""
    ids = list(document_ids)
    if not ids:
        return set()
    return set(db.scalars(select(Document.id).where(Document.id.in_(ids), *over(today, statuses=(FILED, INBOX)))))


def put_by_itself(db: Session, document_ids: Sequence[int]) -> set[int]:
    """Of these documents, the ones in the trash that the task put there (the last line of the history about the trash
    is ``auto_trashed``, not a person's ``trashed``): the trash page says so."""
    ids = list(document_ids)
    if not ids:
        return set()
    last: dict[int, str] = {}
    for document_id, action in db.execute(select(Event.document_id, Event.action).where(
            Event.document_id.in_(ids), Event.action.in_((AUTO_TRASHED, "trashed"))).order_by(Event.id)):
        last[document_id] = action
    return {i for i, action in last.items() if action == AUTO_TRASHED}


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
    may see) and would be taken (``over`` without the switch: the kind is asked before it is switched on); documents
    the task put in the trash once and a person restored are not counted, the run never takes them again."""
    return int(db.scalar(select(func.count(Document.id)).where(
        Document.kind_id == kind_id, *over(today, switch=False), visible)) or 0)


def run(db: Session, today: Date | None = None, *, limit: int | None = None) -> int:
    """Puts the documents that are over into the trash, up to what is left of the day's ``limit``. Returns how many."""
    today = today or deadlines.server_today()
    limit = DAY_LIMIT if limit is None else limit
    total = 0
    while True:
        changes.write_lock(db)
        counted_day = _counter(db, DAY_COUNTER)
        done = _counter(db, DONE_COUNTER) or 0
        if counted_day is not None and counted_day > today.toordinal():
            # The clock was ahead and has been set right: the count of a day that has not come yet would block the run
            # until the clock caught up. Start today's count anew (each document is taken once in any case).
            logger.warning("The clock is behind the last day the task counted; counting today anew "
                           "(counted_day=%s today=%s)", Date.fromordinal(counted_day).isoformat(), today.isoformat())
            counted_day, done = today.toordinal(), 0
        elif counted_day is None or today.toordinal() > counted_day:
            counted_day, done = today.toordinal(), 0
        room = limit - done
        if room <= 0:
            db.rollback()
            break
        ids = list(db.scalars(select(Document.id).where(and_(*over(today)))
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


def trashed_since(db: Session, uid: int, since: datetime, *, where: Sequence[ColumnElement[bool]] = (),
                  still_in_trash: bool = False) -> int:
    """How many documents the task put in the trash since ``since`` in the vaults where ``uid`` may change things (the
    weekly mail's line). ``where`` narrows the documents (the weekly mail leaves out the vaults a person muted);
    ``still_in_trash`` leaves out the ones that were restored or are gone (the archive's note, which leads to the trash
    page, counts what is there to find)."""
    editable = select(VaultMember.vault_id).where(VaultMember.user_id == uid, VaultMember.right.in_((EDIT, MANAGE)))
    return int(db.scalar(select(func.count(func.distinct(Event.document_id))).select_from(Event).join(
        Document, Document.id == Event.document_id).where(
        Event.action == AUTO_TRASHED, Event.at >= since, Document.vault_id.in_(editable),
        *([Document.status == TRASH] if still_in_trash else []), *where)) or 0)


def night_of(moment: datetime) -> int:
    """The number of the night ``moment`` belongs to: the day whose ``HOUR`` o'clock (the server's time) was the last
    one before it. At two in the morning that is yesterday's night."""
    local = moment.astimezone()
    return local.date().toordinal() if local.hour >= HOUR else local.date().toordinal() - 1


def tick(db: Session, moment: datetime | None = None) -> int:
    """One look: does the work when a night has come that has not been done, otherwise nothing. Returns how many
    documents were put in the trash.

    * Nothing recorded (the first look ever): the night is noted, nothing is done, so the update itself and a switch
      that was just turned on never put anything in the trash at once.
    * An earlier night recorded (the server was off at ``HOUR`` o'clock, or this is the next night): the work is done
      now, and then the night is recorded.
    * A later night recorded (the clock was ahead and is right again): said in the log, the night of now is recorded.
    """
    moment = moment or clock.now()
    night = night_of(moment)
    changes.write_lock(db)
    seen = _counter(db, NIGHT_COUNTER)
    if seen is not None and seen > night:
        logger.warning("The clock is behind the last night the task worked in; waiting for the next one "
                       "(recorded_night=%s now_night=%s)", Date.fromordinal(seen).isoformat(),
                       Date.fromordinal(night).isoformat())
    if seen is None or seen > night:
        _store(db, NIGHT_COUNTER, night)
        db.commit()
        return 0
    if seen == night:
        db.rollback()
        return 0
    db.rollback()
    taken = run(db, moment.astimezone().date())
    changes.write_lock(db)
    _store(db, NIGHT_COUNTER, night)
    db.commit()
    return taken


def seconds_to_wait(moment: datetime | None = None) -> float:
    """How long the loop sleeps: until the next ``HOUR`` o'clock, but not longer than ``TICK_SECONDS`` (a clock that is
    set meanwhile is noticed within the hour)."""
    local = (moment or clock.now()).astimezone()
    next_night = local.replace(hour=HOUR, minute=0, second=1, microsecond=0)
    if next_night <= local:
        next_night += timedelta(days=1)
    return max(1.0, min(float(TICK_SECONDS), (next_night - local).total_seconds()))


def run_once() -> int:
    from ..db import SessionLocal

    with SessionLocal() as db:
        return tick(db)


async def run_forever(stop: asyncio.Event) -> None:
    """The loop beside the others: looks at start (catching up a night that was missed), then at ``HOUR`` o'clock."""
    while not stop.is_set():
        try:
            await asyncio.to_thread(run_once)
        except Exception:
            logger.exception("Putting expired documents in the trash failed")
        try:
            await asyncio.wait_for(stop.wait(), seconds_to_wait())
            return
        except TimeoutError:
            continue


__all__ = ["AUTO_TRASHED", "BATCH", "DAY_LIMIT", "HOUR", "due", "night_of", "over", "pending", "put_by_itself", "run",
           "run_forever", "run_once", "seconds_to_wait", "tick", "trashed_since"]
