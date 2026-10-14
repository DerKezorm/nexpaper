"""The numbers of the dashboard card (``GET /api/v1/dashboard``): what waits, what is filed, what falls due soon.

**Who sees what.** Everything is counted among the documents the key's account may read (``rights.visible_clause``),
the trash left out, and it is counted in the query, not afterwards. The one exception is the inbox, which is the
account's own inbox as the menu shows it: the documents in the vaults where the account may *change* things
(``inbox.waiting``), so the card never shows a number the web app does not.

**Deadlines.** A date of a document (``document_dates``) is a deadline when somebody has to act before it:

- ``due``: a bill to pay, a payment that falls due,
- ``contract_end``: a contract that ends or renews, the day to cancel it,
- ``warranty_end``: the last day to claim under a warranty.

``keep_until`` (keep the paper until) is not one: nothing is to be done by that day, so it is left out. A contract with
a notice period comes once more as ``notice``, on its last day to cancel (``services/deadlines.py``). A deadline marked
done (paid, cancelled, claimed) is left out altogether.

**What leaves.** Counts, a title, a date and a link: no text of a document, no sender, no amount, no tag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..models import FILED, INBOX, PROCESSING, TRASH, Account, Document, DocumentDate
from . import inbox, rights, timezones

#: The kinds of date that are a deadline (see the top).
DEADLINE_KINDS = ("due", "contract_end", "warranty_end")
#: The kind a contract's last day to cancel is named by.
NOTICE = "notice"
#: How many of the oldest documents of the inbox are named.
OLDEST = 5
#: How far ahead, in days from today (today included), a deadline is shown, and how many at most.
HORIZON_DAYS = 14
MAX_DEADLINES = 20
#: ``added_week`` looks back this far.
WEEK = timedelta(days=7)


@dataclass
class Waiting:
    id: int
    title: str
    added_at: datetime
    status: str


@dataclass
class Deadline:
    id: int
    title: str
    date: Date
    kind: str
    status: str


@dataclass
class Numbers:
    inbox: int = 0
    inbox_oldest: list[Waiting] = field(default_factory=list)
    filed: int = 0
    total: int = 0
    added_week: int = 0
    processing: int = 0
    deadlines: list[Deadline] = field(default_factory=list)


def today_of(account: Account) -> Date:
    """Today on the clock of the account's time zone (the server's own until the browser told one)."""
    return clock.now().astimezone(timezones.zone_of(account)).date()


def numbers(db: Session, account: Account) -> Numbers:
    uid = account.id
    seen = rights.visible_clause(uid)
    out = Numbers()
    per_status = dict(db.execute(
        select(Document.status, func.count()).where(seen, Document.status != TRASH).group_by(Document.status)).all())
    out.filed = int(per_status.get(FILED, 0))
    out.processing = int(per_status.get(PROCESSING, 0))
    out.total = sum(int(n) for n in per_status.values())
    out.added_week = int(db.scalar(select(func.count()).select_from(Document).where(
        seen, Document.status != TRASH, Document.added_at >= clock.now() - WEEK)) or 0)

    waiting = (Document.status == INBOX, inbox.waiting(uid))
    out.inbox = int(db.scalar(select(func.count()).select_from(Document).where(*waiting)) or 0)
    out.inbox_oldest = [Waiting(id=i, title=t, added_at=a, status=s) for i, t, a, s in db.execute(
        select(Document.id, Document.title, Document.added_at, Document.status).where(*waiting)
        .order_by(Document.added_at.asc(), Document.id.asc()).limit(OLDEST)).all()]

    today = today_of(account)
    last = today + timedelta(days=HORIZON_DAYS)
    found: list[Deadline] = []
    for day_column, kinds, named in ((DocumentDate.date, DEADLINE_KINDS, None),
                                     (DocumentDate.notice_date, ("contract_end",), NOTICE)):
        found += [Deadline(id=i, title=t, date=d, kind=named or k, status=s) for i, t, d, k, s in db.execute(
            select(Document.id, Document.title, day_column, DocumentDate.kind, Document.status)
            .join(DocumentDate, DocumentDate.document_id == Document.id)
            .where(seen, Document.status != TRASH, DocumentDate.kind.in_(kinds), DocumentDate.done_at.is_(None),
                   day_column.is_not(None), day_column >= today, day_column <= last)
            .order_by(day_column.asc(), Document.id.asc(), DocumentDate.kind.asc())
            .limit(MAX_DEADLINES)).all()]
    out.deadlines = sorted(found, key=lambda d: (d.date, d.id, d.kind))[:MAX_DEADLINES]
    return out
