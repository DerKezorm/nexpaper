"""Keeping documents: how long the papers of a kind are kept, and which may go now.

**The keeping time belongs to the kind** (``Kind.keep_years``; empty: none, and the kinds that come with nexpaper have
none). A document of such a kind gets the dated term ``keep_until``: the end of the year of its date plus that many
years (31.12.2036 for an invoice of 14.03.2026 kept 10 years), the way keeping times are usually counted. A document
without a date counts from the day it came in (``added_at``): there is no column for the day it was filed, and for a
document without a date the day it came is the closest there is to the day it was dated.

**Worked out, or set by hand.** A ``keep_until`` worked out from the kind is worked out again whenever what it rests on
changes: the document is filed or read, its kind, its date or its vault (another vault may give it another kind of the
same name) changes, or the kind gets another keeping time for the documents already there. One that a person set
(``DocumentDate.manual``) stays until the person takes it back ("Wieder aus der Art rechnen"); a kind without a
keeping time takes away only the worked-out ones.

**Who sets it.** For a kind of the whole server the operator, for a kind of a vault whoever manages the vault. Setting
it for the documents already there changes every document of the kind (it is a kind only the vault's documents, or
every vault's documents, may have), but the numbers the question shows count only what the person may see. Many
documents are done in the background (a job ``keep``), each with a new number for the feed and a line in its history.

**Nothing goes by itself, unless a kind says so.** "May go" (``expired``) lists the filed documents whose time is over
in the vaults where the person may change things; putting them in the trash is the person's doing, with the trash's 30
days. A kind can have the switch "expired documents into the trash by themselves" (``Kind.auto_trash``, off from the
start, only with a keeping time, set by whoever sets the time): then ``services/autotrash.py`` does it once a day.
Nothing is ever deleted for good by it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime

from sqlalchemy import ColumnElement, Integer, String, and_, cast, delete, exists, func, or_, select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import error
from ..models import EDIT, FILED, INBOX, MANAGE, TRASH, Account, Document, DocumentDate, Event, Job, Kind, VaultMember
from . import changes, jobs, rights, timezones

logger = logging.getLogger("nexpaper.keeping")

KEEP = "keep_until"
#: The years the interface offers; the interface takes any other number from 1 to ``YEARS_MAX`` too.
CHOICES = (1, 2, 3, 5, 6, 8, 10, 30)
YEARS_MAX = 30
#: The statuses a document has a worked-out keeping time in: not while it is being read (its kind is not settled).
WITH_TIME = (INBOX, FILED, TRASH)
#: Up to this many documents of a kind are changed at once, in the request; more go to the background.
AT_ONCE = 200
#: Documents changed in one transaction of the background job.
BATCH = 200


def until(years: int, day: Date | None, added_at: datetime | None) -> Date:
    """The end of the year of the document's date (else of the day it came in) plus ``years`` years."""
    base = day.year if day is not None else (added_at or clock.now()).year
    return Date(base + years, 12, 31)


def today_of(account: Account) -> Date:
    """Today in the person's time zone: a keeping time is over on the day after its date, wherever they are."""
    return clock.now().astimezone(timezones.zone_of(account)).date()


def check_years(years: int | None) -> int | None:
    if years is not None and not 1 <= years <= YEARS_MAX:
        raise error("invalid_keep_years", f"Keep documents 1 to {YEARS_MAX} years, or not set.", 422)
    return years


# --- Working it out ---------------------------------------------------------------------------------------------------


def _chunks(ids: list[int], size: int = 500) -> Iterable[list[int]]:
    for start in range(0, len(ids), size):
        yield ids[start:start + size]


def refresh(db: Session, document_ids: Iterable[int]) -> set[int]:
    """Works the ``keep_until`` of these documents out again from their kind, where no person set it. Returns the
    documents whose term changed (made, moved or taken away); the caller gives them their number and history line.
    The caller holds the write lock."""
    ids = sorted(set(document_ids))
    changed: set[int] = set()
    if not ids:
        return changed
    db.flush()
    for part in _chunks(ids):
        rows = db.execute(
            select(Document.id, Document.date, Document.added_at, Document.status, Kind.keep_years)
            .outerjoin(Kind, Kind.id == Document.kind_id).where(Document.id.in_(part))
        ).all()
        have = {row.document_id: row for row in db.scalars(select(DocumentDate).where(
            DocumentDate.document_id.in_(part), DocumentDate.kind == KEEP))}
        for document_id, day, added_at, status, years in rows:
            if status not in WITH_TIME:
                continue
            row = have.get(document_id)
            if row is not None and row.manual:
                continue
            wanted = until(years, day, added_at) if years else None
            if wanted is None:
                if row is not None:
                    db.delete(row)
                    changed.add(document_id)
            elif row is None:
                db.add(DocumentDate(document_id=document_id, kind=KEEP, date=wanted, manual=False))
                changed.add(document_id)
            elif row.date != wanted:
                row.date = wanted
                changed.add(document_id)
    if changed:
        db.flush()
    return changed


def take(db: Session, document: Document, day: Date | None, manual: bool | None) -> bool:
    """The ``keep_until`` a person sent with the terms of a document (``PATCH``): ``day`` is its date, or None when the
    term was left out. ``manual`` says how it was meant: True set by hand, False worked out from the kind (the date
    sent is not looked at), None as it comes (left out, or the date it has now and was worked out: from the kind;
    another date: by hand). Left out or from the kind, it is worked out by ``refresh`` right after. True when the
    stored term changed."""
    row = db.scalar(select(DocumentDate).where(DocumentDate.document_id == document.id, DocumentDate.kind == KEEP))
    by_hand = bool(manual) if manual is not None else (
        day is not None and not (row is not None and not row.manual and row.date == day))
    if not by_hand:
        if row is not None and row.manual:
            # Back to the kind: the worked-out date follows from ``refresh``.
            db.delete(row)
            return True
        return False
    assert day is not None
    if row is None:
        db.add(DocumentDate(document_id=document.id, kind=KEEP, date=day, manual=True))
        return True
    if row.date == day and row.manual:
        return False
    row.date, row.manual = day, True
    return True


def freeze(db: Session, document_ids: Iterable[int]) -> set[int]:
    """The worked-out ``keep_until`` of these documents counts as set by hand from now on: the date stays where it is
    whatever the kind does (its keeping time taken away "for new ones only", the kind deleted or merged into one
    without a time). Returns the documents whose term was marked. The caller holds the write lock."""
    ids = sorted(set(document_ids))
    marked: set[int] = set()
    for part in _chunks(ids):
        for row in db.scalars(select(DocumentDate).where(
                DocumentDate.document_id.in_(part), DocumentDate.kind == KEEP, DocumentDate.manual.is_(False))):
            row.manual = True
            marked.add(row.document_id)
    if marked:
        db.flush()
    return marked


def stamp(db: Session, document_ids: Iterable[int], uid: int | None, *, by: str = "catalog") -> None:
    """New numbers for the feed and a line in the history of documents whose ``keep_until`` the kind changed."""
    ids = sorted(set(document_ids))
    changes.touch(db, ids)
    for document_id in ids:
        changes.record(db, document_id, changes.CHANGED, user_id=uid, detail={"fields": [KEEP], "by": by})


# --- The keeping time of a kind -------------------------------------------------------------------------------------


def _kind_to_set(db: Session, uid: int, kind_id: int) -> Kind:
    """The kind whose keeping time ``uid`` may set: a kind of a vault they manage (404 when they are not in it, 403 with
    less than ``manage``); a kind of the whole server is the operator's, which the router has checked."""
    kind = db.get(Kind, kind_id)
    if kind is None:
        raise error("not_found", "Not found.", 404)
    if kind.vault_id is not None:
        rights.require_vault(db, uid, kind.vault_id, MANAGE)
    return kind


def _base_year() -> ColumnElement[int]:
    """The year a keeping time counts from, in SQL: of the document's date, else of the day it came in."""
    return cast(func.substr(func.coalesce(cast(Document.date, String), cast(Document.added_at, String)), 1, 4), Integer)


@dataclass
class Preview:
    #: The documents of the kind the person may see (not in the trash, not being read).
    documents: int
    #: Of those, the ones with a keep_until a person set: they keep it.
    by_hand: int
    #: Of those, the ones whose time would be over at once.
    expired: int


def preview(db: Session, uid: int, kind_id: int, years: int | None, today: Date) -> Preview:
    """What the question before setting ``years`` (None: taking the time away) for the documents already there says.
    Only documents ``uid`` may see are counted."""
    check_years(years)
    kind = _kind_to_set(db, uid, kind_id)
    manual = select(DocumentDate.document_id).where(DocumentDate.kind == KEEP, DocumentDate.manual.is_(True))
    seen = and_(Document.kind_id == kind.id, Document.status.in_((INBOX, FILED)), rights.visible_clause(uid))
    documents = int(db.scalar(select(func.count()).select_from(Document).where(seen)) or 0)
    by_hand = int(db.scalar(select(func.count()).select_from(Document).where(seen, Document.id.in_(manual))) or 0)
    expired = 0 if years is None else int(db.scalar(select(func.count()).select_from(Document).where(
        seen, Document.id.not_in(manual), _base_year() + years < today.year)) or 0)
    db.rollback()
    return Preview(documents=documents, by_hand=by_hand, expired=expired)


@dataclass
class Setting:
    kind: Kind
    #: Documents the caller may see whose term changed now (the ones changed in the background are not counted).
    changed: int
    #: More documents the caller may see than are done at once: they are changed in the background.
    queued: bool


def _apply(db: Session, kind: Kind, ids: list[int]) -> set[int]:
    """The documents of the kind brought to what was decided last for the ones already there: worked out again (a
    time for all, or the time taken away for all), the worked-out dates kept as set by hand (taken away "for new ones
    only"), or nothing (a time set "for new ones only")."""
    if kind.keep_new_only:
        return set() if kind.keep_years else freeze(db, ids)
    return refresh(db, ids)


def set_kind(db: Session, uid: int, kind_id: int, years: int | None, existing: bool) -> Setting:
    """Sets the keeping time of a kind (None: none). With ``existing`` the documents already there are worked out
    again (taken away: their worked-out dates go); without it they are left alone (taken away: their worked-out dates
    stay, as set by hand). Few documents now, many in the background (one job ``keep``, which reads the decision when
    it runs). Every document of the kind is changed, but the answer counts only the ones ``uid`` may see."""
    check_years(years)
    changes.write_lock(db)
    kind = _kind_to_set(db, uid, kind_id)
    kind.keep_years = years
    kind.keep_new_only = not existing
    if years is None:
        # No keeping time, nothing to put in the trash when it is over.
        kind.auto_trash = False
    with_time = and_(Document.kind_id == kind.id, Document.status.in_(WITH_TIME))
    seen = set(db.scalars(select(Document.id).where(with_time, rights.visible_clause(uid)).limit(AT_ONCE + 1)))
    queued = len(seen) > AT_ONCE
    changed: set[int] = set()
    if existing or years is None:
        everything = list(db.scalars(select(Document.id).where(with_time).limit(AT_ONCE + 1)))
        if len(everything) > AT_ONCE:
            # The documents the caller sees first, when they are few: the answer is true at once.
            if not queued:
                changed = _apply(db, kind, list(seen))
            jobs.enqueue(db, jobs.KEEP, kind.id, {"by": uid})
        else:
            changed = _apply(db, kind, everything)
        stamp(db, changed, uid)
    else:
        # Nothing to do for the documents there: a job still waiting for this kind has nothing left to do either.
        db.execute(delete(Job).where(Job.kind == jobs.KEEP, Job.ref == kind.id, Job.state == "queued"))
    db.commit()
    shown = len(changed & seen)
    logger.info("Keeping time set kind_id=%s years=%s existing=%s changed=%s queued=%s", kind.id, years, existing,
                len(changed), queued)
    return Setting(kind=kind, changed=shown, queued=queued)


def run_job(db: Session, kind_id: int, payload: object) -> None:
    """The documents of a kind brought to the decision about them as it stands when the job runs (``_apply``), a batch
    per transaction. Running it twice, or after another decision, does no harm."""
    by = payload.get("by") if isinstance(payload, dict) else None
    # The person who set it, for the history; nobody when the account went meanwhile.
    uid = by if isinstance(by, int) and db.get(Account, by) is not None else None
    db.rollback()
    after = 0
    total = 0
    while True:
        if jobs.stopping.is_set():
            raise jobs.Interrupted
        changes.write_lock(db)
        kind = db.get(Kind, kind_id)
        if kind is None or (kind.keep_new_only and kind.keep_years):
            db.rollback()
            break
        ids = list(db.scalars(select(Document.id).where(
            Document.kind_id == kind_id, Document.status.in_(WITH_TIME), Document.id > after)
            .order_by(Document.id).limit(BATCH)))
        if not ids:
            db.rollback()
            break
        changed = _apply(db, kind, ids)
        stamp(db, changed, uid)
        db.commit()
        total += len(changed)
        after = ids[-1]
    logger.info("Keeping time worked out kind_id=%s changed=%s", kind_id, total)


# --- Into the trash by itself ---------------------------------------------------------------------------------------


def auto_trash_state(db: Session, uid: int, kind_id: int, today: Date) -> tuple[Kind, int]:
    """The kind and how many of its filed documents the caller may see are over their keeping time now: what the switch
    would put in the trash at its next run. Needs the right to set the keeping time."""
    kind = _kind_to_set(db, uid, kind_id)
    from . import autotrash  # here and not at the top: autotrash reads the dates this module names

    found = autotrash.due(db, kind.id, today, rights.visible_clause(uid))
    db.rollback()
    return kind, found


def set_auto_trash(db: Session, uid: int, kind_id: int, enabled: bool) -> Kind:
    """Switches "expired documents into the trash by themselves" for a kind. Only a kind with a keeping time can have it
    (409 ``no_keeping_time``); switching it off is always possible. The task looks at the kind's documents on its own
    at its next run, nothing happens here."""
    changes.write_lock(db)
    kind = _kind_to_set(db, uid, kind_id)
    if enabled and not kind.keep_years:
        raise error("no_keeping_time", "Set a keeping time for the kind first.", 409)
    if bool(kind.auto_trash) != enabled:
        kind.auto_trash = enabled
        db.commit()
        logger.info("Expired documents into the trash by themselves kind_id=%s enabled=%s", kind.id, enabled)
    else:
        db.rollback()
    return kind


def merge_effect(db: Session, uid: int, kind_id: int, into_id: int, today: Date) -> tuple[Kind, int]:
    """What merging a kind into another does to the nightly task, for the question before it: the target kind and how
    many filed documents of the kind that the caller may see would be over their keeping time under the target (a
    date a person set stays as it is, the others are worked out again from the target's years) and would therefore
    be put in the trash by the task, when the target has the switch on. 0 when it has not. Changes nothing."""
    from . import autotrash, catalog  # here and not at the top: catalog reads this module

    _source, target = catalog.merge_pair(db, uid, kind_id, into_id)
    found = 0
    if target.auto_trash and target.keep_years:
        manual = select(DocumentDate.document_id).where(
            DocumentDate.kind == KEEP, DocumentDate.manual.is_(True), DocumentDate.date < today)
        manual_any = select(DocumentDate.document_id).where(DocumentDate.kind == KEEP, DocumentDate.manual.is_(True))
        worked_out = and_(Document.id.not_in(manual_any), _base_year() + target.keep_years < today.year)
        found = int(db.scalar(select(func.count()).select_from(Document).where(
            Document.kind_id == kind_id, Document.status == FILED, rights.visible_clause(uid),
            ~exists().where(Event.document_id == Document.id, Event.action == autotrash.AUTO_TRASHED),
            or_(Document.id.in_(manual), worked_out))) or 0)
    db.rollback()
    return target, found


# --- May go ---------------------------------------------------------------------------------------------------------


def _may_change_vaults(uid: int) -> object:
    """The vaults where ``uid`` may change things: a share of one document is no place to clear out."""
    return select(VaultMember.vault_id).where(VaultMember.user_id == uid, VaultMember.right.in_((EDIT, MANAGE)))


def _over(uid: int, today: Date, vault_id: int | None = None) -> list[ColumnElement[bool]]:
    clauses = [Document.status == FILED, Document.vault_id.in_(_may_change_vaults(uid)),
               DocumentDate.document_id == Document.id, DocumentDate.kind == KEEP, DocumentDate.date < today]
    if vault_id is not None:
        clauses.append(Document.vault_id == vault_id)
    return clauses


def expired_clauses(uid: int, today: Date) -> list[ColumnElement[bool]]:
    """The conditions of "may go" for a query over documents (the archive's filter): filed, in a vault where ``uid`` may
    change things, ``keep_until`` before ``today``."""
    return [Document.status == FILED, Document.vault_id.in_(_may_change_vaults(uid)),
            exists().where(DocumentDate.document_id == Document.id, DocumentDate.kind == KEEP,
                           DocumentDate.date < today)]


def expired(db: Session, uid: int, today: Date, *, vault_id: int | None = None, limit: int = 100,
            offset: int = 0) -> tuple[list[Document], int]:
    """The filed documents whose keeping time is over, in the vaults where ``uid`` may change things: the ones over
    longest first. A vault they cannot change things in is simply empty."""
    clauses = _over(uid, today, vault_id)
    total = int(db.scalar(select(func.count()).select_from(Document).join(
        DocumentDate, DocumentDate.document_id == Document.id).where(*clauses)) or 0)
    found = list(db.scalars(select(Document).join(DocumentDate, DocumentDate.document_id == Document.id)
                            .where(*clauses).order_by(DocumentDate.date, Document.date, Document.id)
                            .limit(limit).offset(offset)))
    return found, total


def may_go_count(db: Session, uid: int, today: Date | None = None, *,
                 where: Sequence[ColumnElement[bool]] = ()) -> int:
    """How many documents ``uid`` may put in the trash because their keeping time is over (the weekly mail's line
    "N documents may go"). ``today`` defaults to today in the person's time zone; ``where`` adds conditions on the
    documents (the weekly mail leaves out the vaults a person muted)."""
    if today is None:
        account = db.get(Account, uid)
        if account is None:
            return 0
        today = today_of(account)
    return int(db.scalar(select(func.count()).select_from(Document).join(
        DocumentDate, DocumentDate.document_id == Document.id).where(*_over(uid, today), *where)) or 0)


__all__ = ["AT_ONCE", "CHOICES", "KEEP", "YEARS_MAX", "Preview", "Setting", "auto_trash_state", "expired",
           "expired_clauses", "may_go_count", "merge_effect", "preview", "refresh", "run_job", "set_auto_trash",
           "set_kind", "stamp", "take", "today_of", "until"]
