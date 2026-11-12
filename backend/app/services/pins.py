"""Pinned documents ("Angeheftet", K1): a short list of documents a person keeps at hand, for them alone.

**Rights.** Pinning needs no more than reading the document (through its vault or a share). The list shows only what
the person may see now and nothing in the trash: the right is part of the query (``rights.visible_clause``), nothing is
filtered afterwards. A pin whose document the person can no longer see stays in the table and is simply not shown; with
the right back (or out of the trash) it shows again. Gone with the person or the document.

**At most ``MAX``** that the person can see: a 21st is refused (``409 too_many_pins`` with ``max``). Counting and
writing are one moment under the write lock, so two pins at the same time never make 21.

**Not a change of the document**: no change number, no line in the history, nothing in the log about which document.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .. import clock
from ..errors import error
from ..models import TRASH, Document, Pin
from . import changes, rights

logger = logging.getLogger("nexpaper.pins")

#: The most pinned documents a person sees.
MAX = 20


def _shown(uid: int) -> list[object]:
    """The pins of ``uid`` whose document they may see, outside the trash (joined with ``Document``)."""
    return [Pin.user_id == uid, Document.status != TRASH, rights.visible_clause(uid)]


def count(db: Session, uid: int) -> int:
    return int(db.scalar(select(func.count()).select_from(Pin).join(Document, Document.id == Pin.document_id)
                         .where(*_shown(uid))) or 0)


def pin(db: Session, uid: int, document_id: int) -> bool:
    """Pins the document for the caller (404 for one they may not see, 409 ``in_trash``, 409 ``too_many_pins``). A pin
    that is there already is no error; True when it is new."""
    changes.write_lock(db)
    access = rights.require_document(db, uid, document_id)
    if access.document.status == TRASH:
        raise error("in_trash", "Restore the document first.", 409)
    if db.scalar(select(Pin.id).where(Pin.user_id == uid, Pin.document_id == document_id)) is not None:
        db.rollback()
        return False
    if count(db, uid) >= MAX:
        raise error("too_many_pins", f"At most {MAX} documents can be pinned. Take one off first.", 409, max=MAX)
    db.execute(sqlite_insert(Pin).values(user_id=uid, document_id=document_id, created_at=clock.now())
               .on_conflict_do_nothing())
    db.commit()
    return True


def unpin(db: Session, uid: int, document_id: int) -> bool:
    """Takes the caller's pin off a document they may see (404 else); True when there was one."""
    changes.write_lock(db)
    rights.require_document(db, uid, document_id)
    gone = db.execute(delete(Pin).where(Pin.user_id == uid, Pin.document_id == document_id)).rowcount
    db.commit()
    return bool(gone)


def listing(db: Session, uid: int, limit: int = MAX) -> list[Document]:
    """The pinned documents the caller may see now, the one pinned last first, none in the trash."""
    return list(db.scalars(
        select(Document).join(Pin, Pin.document_id == Document.id).where(*_shown(uid))
        .order_by(Pin.created_at.desc(), Pin.id.desc()).limit(max(1, limit))
    ))


def among(db: Session, uid: int, document_ids: list[int]) -> set[int]:
    """Which of these documents the caller pinned: one query by the unique index (person, document) for a whole page.
    The documents are the caller's to see already (the page is made of them)."""
    if not document_ids:
        return set()
    return set(db.scalars(select(Pin.document_id).where(Pin.user_id == uid, Pin.document_id.in_(document_ids))))


def search_clause(uid: int, wanted: bool) -> object:
    """``angeheftet:ja`` / ``pinned:yes`` (``wanted``) or ``angeheftet:nein`` / ``pinned:no``: the caller pinned the
    document. Only the caller's own pins; the search finds only what they may see anyway."""
    mine = Document.id.in_(select(Pin.document_id).where(Pin.user_id == uid))
    return mine if wanted else ~mine


__all__ = ["MAX", "among", "count", "listing", "pin", "search_clause", "unpin"]
