"""The storage limit per account (konten 1.1.0, E24): what counts are the documents the account owns, every version of
their files as it came (``Version.size``), the trash included. The operator sets a limit per account (Server › Accounts,
"Manage"); none is set from the start. Nothing the account keeps is touched when it is reached.

The limit holds on every way in (Bauplan E47):

- an upload through the browser or ``/api/v1`` is refused with ``storage_limit_reached`` (507), as nexnotes does;
- a file of an upload request is refused with ``request_no_room`` (507); the stranger is told to try later;
- the automatic ways lose nothing: a file of the intake folder stays in the folder, a mail stays unread in the mailbox
  (``intake_mail``: kept under ``full`` and tried again once there is room), a document of Paperless is skipped with the
  reason ``storage_full`` and taken by a later run. Each says what waits (``waiting``); the account is told
  "Speicher voll, x Dokumente warten" (push and mail as nexpaper's other notices, ``tell``) and the log has a line.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import error
from ..models import Account, Document, Version

if TYPE_CHECKING:
    from .tell import Notice

logger = logging.getLogger("nexpaper.quota")

#: The ways that wait (``waiting``): the intake folder, the mailbox, the import from Paperless.
FOLDER, MAIL, PAPERLESS = "folder", "mail", "paperless"
#: The account hears again only after this long, and only when more documents wait than it was told of.
TELL_AGAIN_SECONDS = 3600.0
#: Where a tap leads: the archive, where the account can make room.
PATH = "/"
TAG = "storage-full"
TEXTS = {
    "de": ("Speicher voll", "{count} Dokumente warten, bis in deinem Konto wieder Platz ist.",
           "Ein Dokument wartet, bis in deinem Konto wieder Platz ist."),
    "en": ("Storage full", "{count} documents are waiting until there is room in your account again.",
           "A document is waiting until there is room in your account again."),
    "fr": ("Stockage plein", "{count} documents attendent qu'il y ait de nouveau de la place dans votre compte.",
           "Un document attend qu'il y ait de nouveau de la place dans votre compte."),
}


def used(db: Session, account_id: int) -> int:
    """The bytes of the documents the account owns."""
    return int(db.scalar(
        select(func.coalesce(func.sum(Version.size), 0))
        .join(Document, Document.id == Version.document_id)
        .where(Document.owner_id == account_id)
    ) or 0)


def used_per_account(db: Session) -> dict[int, int]:
    """The same for every account, in one query (the operator's list)."""
    rows = db.execute(
        select(Document.owner_id, func.coalesce(func.sum(Version.size), 0))
        .join(Version, Version.document_id == Document.id)
        .where(Document.owner_id.is_not(None))
        .group_by(Document.owner_id)
    )
    return {int(owner): int(total) for owner, total in rows}


def full(used_bytes: int, limit: int | None, size: int) -> bool:
    """``size`` more bytes would go past the limit (a file that fills it exactly still fits)."""
    return limit is not None and used_bytes + size > limit


def refused(used_bytes: int, limit: int | None) -> HTTPException:
    return error("storage_limit_reached", "The storage of the account is full.", 507, used=used_bytes, limit=limit)


def require_room(db: Session, account_id: int | None, size: int) -> None:
    """Refuse a file of ``size`` bytes for ``account_id`` when its documents would go past its limit."""
    if account_id is None:
        return
    account = db.get(Account, account_id)
    limit = account.storage_limit if account is not None else None
    if limit is None:
        return
    taken = used(db, account_id)
    if full(taken, limit, size):
        raise refused(taken, limit)


def room(db: Session, account_id: int | None, size: int) -> bool:
    """Whether ``size`` more bytes fit in the storage of ``account_id`` (always without a limit or an account)."""
    if account_id is None:
        return True
    account = db.get(Account, account_id)
    limit = account.storage_limit if account is not None else None
    return limit is None or not full(used(db, account_id), limit, size)


def some_room(db: Session, account_id: int | None) -> bool:
    """Whether the account has any room left: a way that waits tries again then (the exact size is asked when it
    does)."""
    return room(db, account_id, 1)


# --- What waits, and telling the account -----------------------------------------------------------------------------

_lock = threading.Lock()
#: The documents that wait now, by account and way.
_waiting: dict[int, dict[str, int]] = {}
#: How many documents each account was last told of, and when (``clock.monotonic``).
_told: dict[int, tuple[int, float]] = {}


def forget() -> None:
    """For the tests."""
    with _lock:
        _waiting.clear()
        _told.clear()


def waiting_now(account_id: int) -> int:
    with _lock:
        return sum(_waiting.get(account_id, {}).values())


def waiting(way: str, counts: dict[int, int]) -> None:
    """What waits on one way now, by account (it replaces what this way said before; an account it leaves out has
    nothing waiting there any more). An account that has more waiting than it was told of hears it, at most once in
    ``TELL_AGAIN_SECONDS``; one with nothing waiting is told again the next time it fills up."""
    now = clock.monotonic()
    due: list[tuple[int, int]] = []
    with _lock:
        for account_id in list(_waiting):
            _waiting[account_id].pop(way, None)
        for account_id, count in counts.items():
            if count > 0:
                _waiting.setdefault(account_id, {})[way] = count
        for account_id in set(_waiting) | set(_told):
            total = sum(_waiting.get(account_id, {}).values())
            if total == 0:
                _waiting.pop(account_id, None)
                _told.pop(account_id, None)
                continue
            before, at = _told.get(account_id, (0, 0.0))
            if total > before and (before == 0 or now - at >= TELL_AGAIN_SECONDS):
                _told[account_id] = (total, now)
                due.append((account_id, total))
    for account_id, total in due:
        logger.warning("Storage full: documents wait account_id=%s waiting=%s way=%s", account_id, total, way)
        tell_full(account_id, total)


def notice(count: int) -> Notice:
    """The notice "Speicher voll, x Dokumente warten" (push and mail, as nexpaper's other notices)."""
    from . import tell

    texts = {lang: (title, many.format(count=count) if count != 1 else one)
             for lang, (title, many, one) in TEXTS.items()}
    return tell.Notice(
        texts=texts, url=PATH, tag=TAG, mail_subject="nexpaper: storage full",
        mail_body=(f"The storage of your account is full: {count} documents are waiting until there is room again. "
                   "Nothing is lost; they come in by themselves once there is room.\n\nOpen nexpaper: {where}\n"),
        mails={
            "de": ("nexpaper: Speicher voll",
                   (f"Der Speicher deines Kontos ist voll: {count} Dokumente warten, bis wieder Platz ist. Nichts geht "
                    "verloren; sie kommen von selbst herein, sobald Platz ist.\n\nnexpaper öffnen: {where}\n")),
            "fr": ("nexpaper : stockage plein",
                   (f"Le stockage de votre compte est plein : {count} documents attendent qu'il y ait de nouveau de la "
                    "place. Rien n'est perdu ; ils arrivent d'eux-mêmes dès qu'il y a de la place.\n\n"
                    "Ouvrir nexpaper : {where}\n")),
        },
    )


def tell_full(account_id: int, count: int) -> None:
    from . import tell

    tell.person(account_id, notice(count))
