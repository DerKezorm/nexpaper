"""The storage limit per account (konten 1.1.0, E24): what counts are the documents the account owns, every version of
their files as it came (``Version.size``), the trash included. The operator sets a limit per account (Server, Accounts,
"Manage"); none is set from the start. When the documents reach it, an upload through the browser or ``/api/v1`` is
refused with ``storage_limit_reached`` (507), as nexnotes does; nothing the account keeps is touched.

The intake folder, the mail intake, the Paperless import and upload requests are not held to it yet (``einst-fragen``
B2.3): a file that comes in there is taken as before.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import error
from ..models import Account, Document, Version


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
