"""Deadlines: the list of what is to be paid, cancelled or claimed, done and open again, and "later" for oneself.

The list is the deadlines of the documents the caller may change (``services/deadlines.py`` says why a reader gets
none): reading it is open to a signed-in browser, a device and a program with a key that reads. Marking one done, or
putting it off, changes something and needs a browser or a device with ``edit`` on the document; a document the caller
may not see answers 404, one they may only read 403. The number beside "Fristen" in the menu comes with the others from
``GET /api/v1/counts``.
"""

from __future__ import annotations

from datetime import date as Date
from typing import Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict

from ..deps import Account as Caller
from ..deps import DbSession, Reader
from ..services import deadlines, documents
from .schemas import DocumentOut, DoneOut, NoticeOut, document_out, person

router = APIRouter(prefix="/api/v1", tags=["deadlines"])

DeadlineKind = Literal["due", "contract_end", "warranty_end"]


class DeadlineOut(BaseModel):
    document_id: int
    title: str
    #: ``inbox`` or ``filed``: a deadline of a document waiting in the inbox is one too.
    status: Literal["inbox", "filed"]
    vault_id: int
    #: The caller sees the document through a share alone, in no vault of theirs.
    via_share: bool
    sender: str | None
    #: In cents.
    amount: int | None
    currency: str
    #: The kind of the date: ``due``, ``contract_end`` or ``warranty_end``.
    kind: DeadlineKind
    #: What is to be done: ``pay``, ``cancel`` (by the last day to cancel), ``ends`` (a contract ends; its last day to
    #: cancel passed, or it has none) or ``warranty``.
    what: Literal["pay", "cancel", "ends", "warranty"]
    #: The day to act by, and how many days from today (in the caller's time zone) it is; below 0: overdue.
    date: Date
    days: int
    #: The date itself (for a contract its end).
    end: Date
    notice: NoticeOut | None
    renew_months: int | None
    #: Where the end moves when nobody cancels; the last day to cancel, when it passed.
    renews_to: Date | None
    missed: Date | None
    done: DoneOut | None
    #: The caller's own "later", while it lasts.
    snoozed_until: Date | None


class SectionOut(BaseModel):
    #: How many there are; `items` holds the first `limit` of them, by the day to act.
    total: int
    items: list[DeadlineOut]


class DeadlinesOut(BaseModel):
    #: Today in the caller's time zone, the day the sections are counted from.
    today: Date
    #: How many days ahead count as soon (today included).
    soon_days: int
    overdue: SectionOut
    soon: SectionOut
    later: SectionOut
    #: Only with `done=true`.
    done: SectionOut | None
    #: Open deadlines per vault of the caller (vault id as text) under the other filters, and those seen through a
    #: share alone.
    counts: dict[str, int]
    shared: int


def _out(d: deadlines.Deadline) -> DeadlineOut:
    row, document, worked = d.row, d.document, d.worked
    return DeadlineOut(
        document_id=document.id, title=document.title, status=document.status,  # type: ignore[arg-type]
        vault_id=document.vault_id, via_share=d.via_share, sender=d.sender, amount=document.amount,
        currency=document.currency, kind=row.kind, what=worked.what, date=worked.date, days=d.days,  # type: ignore[arg-type]
        end=row.date,
        notice=NoticeOut(n=row.notice_n, unit=row.notice_unit) if row.notice_n and row.notice_unit else None,  # type: ignore[arg-type]
        renew_months=row.renew_months, renews_to=worked.renews_to, missed=worked.missed,
        done=DoneOut(at=row.done_at, by=person(d.done_by)) if row.done_at else None,
        snoozed_until=d.snoozed_until,
    )


def _section(section: deadlines.Section) -> SectionOut:
    return SectionOut(total=section.total, items=[_out(d) for d in section.items])


@router.get("/deadlines", response_model=DeadlinesOut,
            summary="What is to be paid, cancelled or claimed: overdue, the next 14 days, later, done")
def listing(
    account: Reader, db: DbSession,
    vault_id: int | None = Query(default=None, ge=1, le=2**31 - 1),
    shared: bool = Query(default=False, description="Only documents the caller reaches through a share alone"),
    what: Literal["pay", "cancel", "warranty"] | None = Query(
        default=None, description="`pay`: due dates; `cancel`: contracts; `warranty`: warranties"),
    done: bool = Query(default=False, description="Also what is done (paid, cancelled, claimed)"),
    limit: int = Query(default=200, ge=1, le=500, description="At most this many in each section"),
) -> DeadlinesOut:
    """The deadlines of the documents the caller may change (`edit` or `manage` in the vault, or a share with `edit`),
    in the inbox or filed. A vault the caller does not reach answers like an empty one."""
    today = deadlines.today_of(account)
    found = deadlines.listing(db, account.id, today, deadlines.Narrow(vault_id=vault_id, shared=shared, what=what),
                              with_done=done, limit=limit)
    return DeadlinesOut(
        today=today, soon_days=deadlines.SOON_DAYS, overdue=_section(found.overdue), soon=_section(found.soon),
        later=_section(found.later), done=_section(found.done) if found.done is not None else None,
        counts={str(v): n for v, n in found.counts.items()}, shared=found.shared,
    )


@router.post("/documents/{document_id}/dates/{kind}/done", response_model=DocumentOut,
             summary="Mark a deadline done (paid, cancelled, claimed), for everybody")
def mark_done(document_id: int, kind: DeadlineKind, account: Caller, db: DbSession) -> DocumentOut:
    """Nobody is reminded of it any more, and a cancelled contract no longer renews. Needs `edit`; 404 when the document
    has no such date."""
    deadlines.set_done(db, account.id, document_id, kind, True)
    return document_out(documents.one(db, account.id, document_id)[1])


@router.delete("/documents/{document_id}/dates/{kind}/done", response_model=DocumentOut,
               summary="Open a deadline that was marked done again")
def mark_open(document_id: int, kind: DeadlineKind, account: Caller, db: DbSession) -> DocumentOut:
    deadlines.set_done(db, account.id, document_id, kind, False)
    return document_out(documents.one(db, account.id, document_id)[1])


class SnoozeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: Literal[1, 3, 7]


class SnoozeOut(BaseModel):
    #: The caller is reminded again from this day on.
    until: Date


@router.put("/documents/{document_id}/dates/{kind}/snooze", response_model=SnoozeOut,
            summary="Later: no reminder of this deadline for the caller for 1, 3 or 7 days")
def put_off(document_id: int, kind: DeadlineKind, payload: SnoozeIn, account: Caller, db: DbSession) -> SnoozeOut:
    """Only for the caller: the others in the vault are reminded as before. Needs `edit` like the deadline itself; a
    deadline that is done answers `409 deadline_done`."""
    until = deadlines.snooze(db, account.id, document_id, kind, int(payload.days), deadlines.today_of(account))
    return SnoozeOut(until=until)


@router.delete("/documents/{document_id}/dates/{kind}/snooze", status_code=204,
               summary="End the caller's own later on a deadline")
def end_put_off(document_id: int, kind: DeadlineKind, account: Caller, db: DbSession) -> Response:
    deadlines.unsnooze(db, account.id, document_id, kind)
    return Response(status_code=204)
