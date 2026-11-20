"""Sorting again: the proposals of documents waiting in the inbox worked out once more, after a rule was made or
changed (issue #11). First a look at what would change, then the change for the documents the person ticked.

**What is asked.** The same as when the document arrived (``sorting.propose``): the e-invoice, the rules, as last time,
the text, and what the AI answered then (kept in ``Document.suggest``). The text is the one read when it arrived: no
new reading, no new question to the AI. A field a person set stays theirs (``person``).

**A look first.** Proposals are written as they are made, and a rule may move a document into another vault at once,
with its sender and tags following it there; a rule too wide (a word that is also in the advertising) would move many
documents nobody can bring back with one click. So ``preview`` works every document out as ``apply`` would, in a
transaction of its own that is rolled back, and says per document what would change, before and after. There is no
second way of working the proposals out that could say something else than what then happens.

**One document at a time.** Each document is its own transaction (the write lock for a moment, then let go), so the
worker and the people go on while hundreds are looked at. At most ``MAX`` documents in one go.

**Who.** Only documents in the inbox the caller may change (``rights.editable_clause``), never one being read, filed or
in the trash. The rules that apply are those of the vault the document arrived in, as on arrival: the caller's rights do
not widen or narrow them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from ..errors import error
from ..models import INBOX, Document, Version, VersionText
from . import changes, einvoices, rights, sorting

logger = logging.getLogger("nexpaper.sort_again")

#: Documents named in one call.
MAX = 1000
#: Documents looked at in one call of ``preview``; the next call goes on after the last (``after``).
STEP = 100


def _waiting(uid: int, ids: list[int] | None) -> Select[tuple[int]]:
    query = select(Document.id).where(Document.status == INBOX, rights.editable_clause(uid))
    if ids is not None:
        if len(ids) > MAX:
            raise error("too_many", f"At most {MAX} documents at once.", 422)
        query = query.where(Document.id.in_(set(ids)))
    return query


def candidates(db: Session, uid: int, ids: list[int] | None, *, after: int = 0,
               limit: int = MAX) -> tuple[list[int], int]:
    """The documents to look at: of ``ids`` (or the whole inbox) those waiting in the inbox the caller may change, in
    the order they were numbered, after ``after``, at most ``limit``. Also how many there are in all."""
    query = _waiting(uid, ids)
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    found = list(db.scalars(query.where(Document.id > after).order_by(Document.id).limit(limit)))
    return found, total


def _text(db: Session, document: Document) -> str:
    version = db.scalar(select(Version).where(Version.document_id == document.id,
                                              Version.n == document.current_version))
    row = db.get(VersionText, version.id) if version is not None else None
    return (row.text if row is not None else "").replace("\f", "\n")


def _still_waiting(db: Session, uid: int, document_id: int) -> Document | None:
    """The document, when it still waits in the inbox and the caller may change it (looked at under the write lock)."""
    document = db.scalar(select(Document).where(Document.id == document_id, Document.status == INBOX,
                                                rights.editable_clause(uid)))
    return document


def _propose(db: Session, document: Document) -> list[str]:
    return sorting.propose(db, document, _text(db, document), invoice=einvoices.latest(db, document.id))


@dataclass
class Look[Shown]:
    """One document whose proposals would change."""

    document_id: int
    #: The fields that would change.
    fields: list[str]
    #: Per changed field where the new value comes from (``rule``, ``last_time``, ``text``, ``ai``, ``einvoice``).
    origins: dict[str, str]
    before: Shown
    #: ``None`` when the caller could no longer see the document afterwards (a rule moves it where they are not).
    after: Shown | None


@dataclass
class Preview[Shown]:
    items: list[Look[Shown]] = field(default_factory=list)
    #: How many documents this call looked at, and how many there are in all.
    looked_at: int = 0
    total: int = 0
    #: Where the next call goes on (``after``); ``None`` when every document was looked at.
    next: int | None = None


def preview[Shown](db: Session, uid: int, ids: list[int] | None, shown: Callable[[Session, Document], Shown], *,
                   after: int = 0) -> Preview[Shown]:
    """What sorting again would change, worked out the way ``apply`` does it and rolled back, for the next ``STEP``
    documents after ``after``. ``shown`` turns a document into what the caller sees of it (called before and after,
    inside the transaction)."""
    found, total = candidates(db, uid, ids, after=after, limit=STEP + 1)
    db.rollback()
    more = len(found) > STEP
    found = found[:STEP]
    out: Preview[Shown] = Preview(looked_at=len(found), total=total, next=found[-1] if more else None)
    for document_id in found:
        changes.write_lock(db)
        try:
            document = _still_waiting(db, uid, document_id)
            if document is None:
                continue
            before = shown(db, document)
            changed = _propose(db, document)
            if not changed:
                continue
            db.flush()
            suggest = document.suggest if isinstance(document.suggest, dict) else {}
            after = shown(db, document) if rights.access_to(db, uid, document_id) is not None else None
            out.items.append(Look(document_id=document_id, fields=sorted(changed),
                                  origins={k: str(suggest[k]) for k in changed if isinstance(suggest.get(k), str)},
                                  before=before, after=after))
        except Exception as exc:  # noqa: BLE001 - one document that cannot be worked out leaves the others
            logger.warning("Sorting again failed in the look document_id=%s error=%s", document_id,
                           type(exc).__name__)
        finally:
            db.rollback()
    return out


@dataclass
class Done:
    #: The documents whose proposals changed, and of those how many moved to another vault.
    changed: list[int] = field(default_factory=list)
    moved: int = 0
    #: Worked out again with nothing new.
    unchanged: int = 0
    #: No longer in the inbox, or no longer the caller's to change.
    skipped: int = 0
    failed: int = 0


def apply(db: Session, uid: int, ids: list[int]) -> Done:
    """Sorts the documents again and keeps what changed, each document in a transaction of its own."""
    if not ids:
        raise error("invalid", "Name the documents.", 422)
    wanted = list(dict.fromkeys(ids))
    found, _ = candidates(db, uid, wanted)
    db.rollback()
    done = Done(skipped=len(wanted) - len(found))
    for document_id in found:
        changes.write_lock(db)
        try:
            document = _still_waiting(db, uid, document_id)
            if document is None:
                done.skipped += 1
                db.rollback()
                continue
            changed = _propose(db, document)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - one document that cannot be worked out leaves the others
            db.rollback()
            done.failed += 1
            logger.warning("Sorting again failed document_id=%s error=%s", document_id, type(exc).__name__)
            continue
        if changed:
            done.changed.append(document_id)
            done.moved += "vault" in changed
        else:
            done.unchanged += 1
    logger.info("Inbox sorted again by=%s changed=%s moved=%s unchanged=%s skipped=%s failed=%s", uid,
                len(done.changed), done.moved, done.unchanged, done.skipped, done.failed)
    return done


__all__ = ["MAX", "Done", "Look", "Preview", "apply", "candidates", "preview"]
