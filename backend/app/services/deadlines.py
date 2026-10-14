"""Deadlines: what has to be paid, cancelled or claimed under a warranty, worked out from the dates of the documents.

**What a deadline is.** A date of a document (``document_dates``) of the kinds ``due`` (pay by), ``contract_end`` (a
contract ends or renews) and ``warranty_end`` (claim by). ``keep_until`` is none: nothing is to be done by that day. A
contract with a notice period is due on its **last day to cancel**: the end minus the period, to the day of the calendar
(31.12. minus 3 months is 30.09.; 31.05. minus 3 months is the last day of February; the last day of a month stays the
last day of the other one). Once that day has passed, the end of the contract is the deadline, with the date it renews
to when nobody cancels. The last day to cancel is kept with the row (``notice_date``), so that the search and this page
compare it in SQL; ``store_terms`` keeps it in step whenever the end or the period changes.

**Done** (paid, cancelled, claimed) ends a deadline for everybody: it leaves the list (unless asked for) and nobody is
reminded of it any more. Done can be taken back. A cancelled contract does not renew. **Later** (1, 3 or 7 days) is for
the one person who asks: the others in the vault are reminded as before.

**Who sees which.** The deadlines of the documents the person may change: ``edit`` or ``manage`` in the vault, or a
share with ``edit`` (``rights.editable_clause``), in the inbox or filed. Somebody who may only read gets no deadlines
and is never reminded (the mock: "aus allen Tresoren, in denen du bearbeiten darfst"), the same as the inbox. The right
is in the query; nothing is filtered or counted afterwards.

**Today** is the person's (``timezones.zone_of``); the clock is ``app.clock``, so a test sets it. The renewal runs on
the server's day; once a day would do, every ``TICK_SECONDS`` is cheap.

**Renewing by itself.** A contract with a renewal that nobody cancelled moves its end on once the end has passed
(``renew_due``): to the first end that is today or later, however many terms it is behind (a contract imported from
long ago does not step year by year), counted in whole terms from the end a person last set (``renew_anchor``), so the
day does not drift to the end of the month after a February. A page that still shows the old end and sends it back does
not undo a renewal (``documents._set_dates``). The write is a compare-and-set on the end it read, under the write lock,
and never from an end it renewed from before (``renewed_from``): two runs at once, a restart or a clock that jumps back
move it once. Each renewal takes a number for the feed and writes ``renewed`` in the history.

``open_for`` is what the reminders take (the block after this one): every open deadline of a person with the day to act.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date as Date
from datetime import timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, case, delete, func, or_, select, true, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .. import clock
from ..errors import error
from ..models import EDIT, FILED, INBOX, TRASH, Account, DeadlineSnooze, Document, DocumentDate, Sender
from . import changes, rights, timezones

logger = logging.getLogger("nexpaper.deadlines")

#: The kinds of date that are a deadline.
DEADLINE_KINDS = ("due", "contract_end", "warranty_end")
#: What a deadline asks for, by the kind of its date; a contract whose last day to cancel passed only ``ends``.
WHAT = {"due": "pay", "contract_end": "cancel", "warranty_end": "warranty"}
WHATS = ("pay", "cancel", "ends", "warranty")
#: How far ahead the page and the menu count as "soon" (today and the 14 days after it).
SOON_DAYS = 14
#: Units of a notice period, and its most; how many months a contract renews by at most.
UNITS = ("weeks", "months")
NOTICE_MAX = 24
RENEW_MAX = 120
#: "Later": by how many days.
SNOOZE_DAYS = (1, 3, 7)
#: The history.
DONE, REOPENED, RENEWED = "deadline_done", "deadline_reopened", "renewed"
#: How often the loop looks for contracts to renew.
TICK_SECONDS = 1800
#: Renewals written in one transaction.
BATCH = 200
#: The latest day a contract renews to (``documents.DATE_MAX``).
LAST_DAY = Date(2200, 12, 31)


# --- The calendar -----------------------------------------------------------------------------------------------------


def add_months(day: Date, n: int) -> Date:
    """``n`` months later (earlier when negative): the same day where the month has it, else its last day, and the last
    day of a month stays the last day of the other one (31.12. minus 3 months is 30.09.)."""
    index = day.year * 12 + (day.month - 1) + n
    year, month = divmod(index, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    was_last = day.day == calendar.monthrange(day.year, day.month)[1]
    return Date(year, month, last if was_last else min(day.day, last))


def last_to_cancel(end: Date, n: int, unit: str) -> Date:
    """The last day to cancel a contract that ends on ``end`` with a notice period of ``n`` ``unit``."""
    return end - timedelta(days=7 * n) if unit == "weeks" else add_months(end, -n)


def today_of(account: Account) -> Date:
    """Today on the clock of the person's time zone (the server's own until the browser told one)."""
    return clock.now().astimezone(timezones.zone_of(account)).date()


def server_today() -> Date:
    return clock.now().astimezone().date()


# --- The terms of a contract ------------------------------------------------------------------------------------------


def check_terms(kind: str, notice: dict[str, Any] | None, renew: int | None, field: str) -> None:
    """A notice period and a renewal belong to a contract only, and stay in their bounds (``invalid_terms`` naming the
    ``field``)."""
    if (notice is not None or renew is not None) and kind != "contract_end":
        raise error("invalid_terms", "Only a contract has a notice period and a renewal.", 422, field=field)
    if notice is not None and (notice.get("unit") not in UNITS or not isinstance(notice.get("n"), int)
                               or not 1 <= notice["n"] <= NOTICE_MAX):
        raise error("invalid_terms", f"A notice period is 1 to {NOTICE_MAX} weeks or months.", 422, field=field)
    if renew is not None and not 1 <= renew <= RENEW_MAX:
        raise error("invalid_terms", f"A contract renews by 1 to {RENEW_MAX} months.", 422, field=field)


def store_terms(row: DocumentDate) -> None:
    """Works the last day to cancel out again from the end and the notice period of the row."""
    if row.kind == "contract_end" and row.notice_n and row.notice_unit in UNITS and row.date is not None:
        try:
            row.notice_date = last_to_cancel(row.date, row.notice_n, row.notice_unit)
        except (ValueError, OverflowError):
            row.notice_date = None
    else:
        row.notice_date = None


# --- What a deadline is today -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Worked:
    #: ``pay``, ``cancel``, ``ends`` or ``warranty``.
    what: str
    #: The day to act by.
    date: Date
    #: The last day to cancel, when it has passed (then the end is the deadline).
    missed: Date | None = None
    #: Where the end moves when nobody cancels.
    renews_to: Date | None = None


def work_out(kind: str, day: Date, *, notice_date: Date | None, renew_months: int | None, done: bool,
             today: Date) -> Worked:
    """The deadline of one date (the mock's ``deadlines``)."""
    if kind != "contract_end":
        return Worked(what=WHAT[kind], date=day)
    renews_to = None
    if renew_months:
        try:
            renews_to = add_months(day, renew_months)
        except ValueError:
            renews_to = None
    if notice_date is not None:
        if notice_date >= today or done:
            return Worked(what="cancel", date=notice_date, renews_to=renews_to)
        return Worked(what="ends", date=day, missed=notice_date, renews_to=renews_to)
    return Worked(what="ends", date=day, renews_to=renews_to)


def act_by(today: Date) -> ColumnElement[Any]:
    """``work_out(...).date`` in SQL: the last day to cancel while it has not passed (or the contract is done), else the
    date itself."""
    return case(
        (and_(DocumentDate.kind == "contract_end", DocumentDate.notice_date.is_not(None),
              or_(DocumentDate.notice_date >= today, DocumentDate.done_at.is_not(None))), DocumentDate.notice_date),
        else_=DocumentDate.date,
    )


def is_open() -> ColumnElement[bool]:
    return DocumentDate.done_at.is_(None)


def deadline_rows() -> list[ColumnElement[bool]]:
    """Dates that are deadlines, of documents in the inbox or filed (being read: not yet; the trash: no more)."""
    return [DocumentDate.kind.in_(DEADLINE_KINDS), Document.status.in_((INBOX, FILED))]


# --- The list ---------------------------------------------------------------------------------------------------------


@dataclass
class Deadline:
    row: DocumentDate
    document: Document
    sender: str | None
    worked: Worked
    days: int
    #: "Later" of the asking person, while it lasts.
    snoozed_until: Date | None
    #: The person sees the document through a share alone, in no vault of theirs.
    via_share: bool
    done_by: Account | None


@dataclass
class Section:
    total: int
    items: list[Deadline]


@dataclass
class Listing:
    today: Date
    overdue: Section
    soon: Section
    later: Section
    done: Section | None
    #: Open deadlines per vault of the person (the vault's number), and those seen through a share alone.
    counts: dict[int, int]
    shared: int


@dataclass
class Narrow:
    vault_id: int | None = None
    #: Only what the person reaches through a share of the document alone.
    shared: bool = False
    #: ``pay``, ``cancel`` (contracts, also those that only end) or ``warranty``.
    what: str | None = None


def _mine(uid: int, narrow: Narrow | None = None) -> list[ColumnElement[bool]]:
    clauses = [*deadline_rows(), rights.editable_clause(uid)]
    if narrow is None:
        return clauses
    if narrow.vault_id is not None:
        clauses.append(Document.vault_id == narrow.vault_id)
    if narrow.shared:
        clauses.append(Document.vault_id.not_in(rights.member_vault_ids(uid)))
    if narrow.what is not None:
        kind = {"pay": "due", "cancel": "contract_end", "warranty": "warranty_end"}[narrow.what]
        clauses.append(DocumentDate.kind == kind)
    return clauses


def listing(db: Session, uid: int, today: Date, narrow: Narrow, *, with_done: bool = False,
            limit: int = 200) -> Listing:
    """The deadlines page: overdue, the next ``SOON_DAYS`` days, later, and (when asked) what is done; each the first
    ``limit`` by the day to act, with how many there are."""
    when = act_by(today)
    soon_end = today + timedelta(days=SOON_DAYS)
    base = _mine(uid, narrow)
    parts = {
        "overdue": [is_open(), when < today],
        "soon": [is_open(), when >= today, when <= soon_end],
        "later": [is_open(), when > soon_end],
        "done": [DocumentDate.done_at.is_not(None)],
    }
    members = set(db.scalars(rights.member_vault_ids(uid)))
    with changes.snapshot(db):
        sections: dict[str, Section] = {}
        for name, extra in parts.items():
            if name == "done" and not with_done:
                continue
            where = and_(*base, *extra)
            total = int(db.scalar(select(func.count()).select_from(DocumentDate)
                                  .join(Document, Document.id == DocumentDate.document_id).where(where)) or 0)
            found = db.execute(
                select(DocumentDate, Document, Sender.name)
                .join(Document, Document.id == DocumentDate.document_id)
                .outerjoin(Sender, Sender.id == Document.sender_id)
                .where(where).order_by(when.asc(), Document.id.asc(), DocumentDate.kind.asc()).limit(limit)
            ).all()
            sections[name] = Section(total=total, items=_deadlines(db, uid, today, found, members))
        # The vault chips: open deadlines under the other filters, apart from the vault.
        apart = Narrow(what=narrow.what)
        per_vault = dict(db.execute(
            select(Document.vault_id, func.count()).select_from(DocumentDate)
            .join(Document, Document.id == DocumentDate.document_id)
            .where(*_mine(uid, apart), is_open()).group_by(Document.vault_id)
        ).all())
    counts = {int(v): int(n) for v, n in per_vault.items() if v in members}
    shared = sum(int(n) for v, n in per_vault.items() if v not in members)
    return Listing(today=today, overdue=sections["overdue"], soon=sections["soon"], later=sections["later"],
                   done=sections.get("done"), counts=counts, shared=shared)


def _deadlines(db: Session, uid: int, today: Date, found: Any, members: set[int]) -> list[Deadline]:
    if not found:
        return []
    ids = [row.id for row, _document, _sender in found]
    snoozes = dict(db.execute(select(DeadlineSnooze.date_id, DeadlineSnooze.until).where(
        DeadlineSnooze.user_id == uid, DeadlineSnooze.date_id.in_(ids), DeadlineSnooze.until > today)).all())
    who = {a.id: a for a in db.scalars(select(Account).where(
        Account.id.in_({row.done_by for row, _d, _s in found if row.done_by})))}
    out = []
    for row, document, sender in found:
        worked = work_out(row.kind, row.date, notice_date=row.notice_date, renew_months=row.renew_months,
                          done=row.done_at is not None, today=today)
        out.append(Deadline(row=row, document=document, sender=sender, worked=worked,
                            days=(worked.date - today).days, snoozed_until=snoozes.get(row.id),
                            via_share=document.vault_id not in members,
                            done_by=who.get(row.done_by) if row.done_by else None))
    return out


@dataclass
class Count:
    #: Open deadlines that are overdue or come within ``SOON_DAYS`` days.
    soon: int
    overdue: int


def menu_count(db: Session, uid: int, today: Date) -> Count:
    """The number beside "Fristen" in the menu: what is overdue and what comes in the next ``SOON_DAYS`` days, open."""
    when = act_by(today)
    soon, overdue = db.execute(
        select(func.count(), func.coalesce(func.sum(case((when < today, 1), else_=0)), 0)).select_from(DocumentDate)
        .join(Document, Document.id == DocumentDate.document_id)
        .where(*_mine(uid), is_open(), when <= today + timedelta(days=SOON_DAYS))
    ).one()
    return Count(soon=int(soon or 0), overdue=int(overdue or 0))


def open_for(db: Session, uid: int, today: Date, *, until: Date | None = None,
             where: Sequence[ColumnElement[bool]] = ()) -> list[Deadline]:
    """Every open deadline of the person's documents (the ones they may change), with the day to act; up to ``until``
    when given, and narrowed by ``where`` (the reminders leave out muted vaults and what is long overdue in SQL). What
    the reminders take."""
    when = act_by(today)
    clauses = [*_mine(uid), is_open(), *where]
    if until is not None:
        clauses.append(when <= until)
    found = db.execute(
        select(DocumentDate, Document, Sender.name).join(Document, Document.id == DocumentDate.document_id)
        .outerjoin(Sender, Sender.id == Document.sender_id).where(*clauses)
        .order_by(when.asc(), Document.id.asc(), DocumentDate.kind.asc())
    ).all()
    return _deadlines(db, uid, today, found, set(db.scalars(rights.member_vault_ids(uid))))


# --- Done, later ------------------------------------------------------------------------------------------------------


def _date_row(db: Session, uid: int, document_id: int, kind: str) -> tuple[Document, DocumentDate]:
    access = rights.require_document(db, uid, document_id, EDIT)
    document = access.document
    if document.status == TRASH:
        raise error("in_trash", "Restore the document first.", 409)
    row = db.scalar(select(DocumentDate).where(DocumentDate.document_id == document_id, DocumentDate.kind == kind))
    if row is None or kind not in DEADLINE_KINDS:
        raise error("no_such_date", "The document has no such date.", 404)
    return document, row


def set_done(db: Session, uid: int, document_id: int, kind: str, done: bool) -> Document:
    """Paid, cancelled or claimed (``done``), or open again. Needs ``edit``; for everybody, with who and when."""
    changes.write_lock(db)
    document, row = _date_row(db, uid, document_id, kind)
    if (row.done_at is not None) == done:
        db.rollback()
        return document
    row.done_at = clock.now() if done else None
    row.done_by = uid if done else None
    if done:
        # Nothing left to remind of: "later" of anybody goes with it.
        db.execute(delete(DeadlineSnooze).where(DeadlineSnooze.date_id == row.id))
    document.change_seq = changes.next_seq(db)
    changes.record(db, document.id, DONE if done else REOPENED, user_id=uid, detail={"kind": kind})
    db.commit()
    return document


def snooze(db: Session, uid: int, document_id: int, kind: str, days: int, today: Date) -> Date:
    """"Later": the person is not reminded of this deadline until ``today + days``. Only for themselves; needs ``edit``
    like every deadline (a reader has none). Not a change of the document: no number, no history."""
    if days not in SNOOZE_DAYS:
        raise error("invalid_input", "Choose 1, 3 or 7 days.", 422)
    changes.write_lock(db)
    _document, row = _date_row(db, uid, document_id, kind)
    if row.done_at is not None:
        raise error("deadline_done", "This deadline is done.", 409)
    until = today + timedelta(days=days)
    db.execute(sqlite_insert(DeadlineSnooze).values(date_id=row.id, user_id=uid, until=until, created_at=clock.now())
               .on_conflict_do_update(index_elements=["date_id", "user_id"], set_={"until": until}))
    db.commit()
    return until


def unsnooze(db: Session, uid: int, document_id: int, kind: str) -> None:
    """"Jetzt wieder": the person's "later" on this deadline ends."""
    changes.write_lock(db)
    _document, row = _date_row(db, uid, document_id, kind)
    db.execute(delete(DeadlineSnooze).where(DeadlineSnooze.date_id == row.id, DeadlineSnooze.user_id == uid))
    db.commit()


def snoozes_of(db: Session, uid: int, date_ids: list[int], today: Date) -> dict[int, Date]:
    if not date_ids:
        return {}
    return {int(k): v for k, v in db.execute(select(DeadlineSnooze.date_id, DeadlineSnooze.until).where(
        DeadlineSnooze.user_id == uid, DeadlineSnooze.date_id.in_(date_ids), DeadlineSnooze.until > today)).all()}


# --- Renewing by itself -----------------------------------------------------------------------------------------------


def next_end(anchor: Date, months: int, today: Date, after: Date | None = None) -> Date | None:
    """The first end of the contract that is today or later (and after ``after``, the end it has now), counted from
    ``anchor`` in whole terms of ``months`` (each from the anchor itself: a contract to the 30th stays at the 30th after
    a February, a 31st stays the last day of the month); nothing beyond ``LAST_DAY``."""
    step = 1
    while True:
        try:
            moved = add_months(anchor, months * step)
        except ValueError:
            return None
        if moved > LAST_DAY:
            return None
        if moved >= today and (after is None or moved > after):
            return moved
        step += 1


def renew_due(db: Session, today: Date | None = None) -> int:
    """Moves on every contract whose end has passed, that renews and that nobody cancelled. Returns how many."""
    today = today or server_today()
    moved = 0
    seen: set[int] = set()
    while True:
        changes.write_lock(db)
        rows = db.execute(
            select(DocumentDate.id, DocumentDate.document_id, DocumentDate.date, DocumentDate.renew_months,
                   DocumentDate.renew_anchor)
            .join(Document, Document.id == DocumentDate.document_id)
            .where(DocumentDate.kind == "contract_end", DocumentDate.renew_months.is_not(None),
                   DocumentDate.renew_months > 0, is_open(), DocumentDate.date < today,
                   or_(DocumentDate.renewed_from.is_(None), DocumentDate.renewed_from != DocumentDate.date),
                   Document.status.in_((INBOX, FILED)), DocumentDate.id.not_in(seen) if seen else true())
            .order_by(DocumentDate.id).limit(BATCH)
        ).all()
        if not rows:
            db.rollback()
            return moved
        for date_id, document_id, end, months, anchor in rows:
            seen.add(date_id)
            target = next_end(anchor or end, months, today, after=end)
            if target is None:
                continue
            # Compare and set: only from the end that was read, and never twice from the same end.
            changed = db.execute(
                update(DocumentDate).where(
                    DocumentDate.id == date_id, DocumentDate.date == end, DocumentDate.done_at.is_(None),
                    or_(DocumentDate.renewed_from.is_(None), DocumentDate.renewed_from != end))
                .values(date=target, renewed_from=end)
                .execution_options(synchronize_session=False)
            ).rowcount
            if not changed:
                continue
            row = db.get(DocumentDate, date_id)
            if row is not None:
                db.refresh(row)
                store_terms(row)
            db.execute(delete(DeadlineSnooze).where(DeadlineSnooze.date_id == date_id))
            db.execute(update(Document).where(Document.id == document_id).values(change_seq=changes.next_seq(db))
                       .execution_options(synchronize_session=False))
            changes.record(db, document_id, RENEWED, detail={"kind": "contract_end", "from": end.isoformat(),
                                                             "to": target.isoformat()})
            moved += 1
        db.commit()
        logger.info("Contracts renewed by themselves count=%s", moved)


def run_once() -> int:
    from ..db import SessionLocal

    with SessionLocal() as db:
        return renew_due(db)


async def run_forever(stop: asyncio.Event) -> None:
    """The loop beside the others: renews what is due, then waits ``TICK_SECONDS``."""
    while not stop.is_set():
        try:
            await asyncio.to_thread(run_once)
        except Exception:
            logger.exception("Renewing contracts failed")
        try:
            await asyncio.wait_for(stop.wait(), TICK_SECONDS)
            return
        except TimeoutError:
            continue


__all__ = [
    "DEADLINE_KINDS", "SNOOZE_DAYS", "SOON_DAYS", "Count", "Deadline", "Listing", "Narrow", "Worked", "act_by",
    "add_months", "last_to_cancel", "listing", "menu_count", "open_for", "renew_due", "run_forever", "set_done",
    "snooze", "snoozes_of", "store_terms", "today_of", "unsnooze", "work_out",
]
