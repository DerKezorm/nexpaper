"""Documents that go with each other ("Gehört zu", "Goes with"): the pairs, the proposals, and what other parts ask.

**One relation, no kind, both ways.** A pair is one row (``Related``), the smaller id first, at most once. No chains:
A with B and B with C does not show C at A. "Link" is the word of the links to the outside; here it is ``related``.

**Rights.** Setting, removing and turning a proposal down need ``edit`` on **both** documents (through the vault or a
share), also across vaults; the check and the write are one moment under the write lock, and setting a pair twice is no
error. The list shows only what the caller may see (``rights.visible_clause`` in the query) and names no number of
what is hidden; a document in the trash is not shown, and a document in the trash shows nothing (the pair stays and
comes back with it; deleted for good, it is gone with the row).

**Proposals, never by themselves.** Another document is proposed when it carries the same invoice, order or delivery
note number (same kind, same compare form, ``services/numbers.py``) and the caller may change both. Never the customer
number (it is on everything of a sender), never the IBAN. A number counts only with at least ``MIN_COMPARE``
characters and a digit, and not when more than ``MAX_CARRIERS`` documents the caller sees carry it (a framework order
on every monthly invoice). Two documents whose senders are both known and differ are not proposed: the measurement
(``tests/test_related_floor.py``) found small invoice numbers of different senders alike in up to 9 % of the proposals
without this rule, none with it. A pair turned down ("Passt nicht") or already set is not proposed again; at most
``MAX_SUGGESTIONS`` per document (``INBOX_SUGGESTIONS`` on a card of the inbox).

**The history** of both documents gets a line when a pair is set or removed (the detail is the number of the other
document, never its title), and both take a change number.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_, delete, exists, func, not_, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased

from .. import clock
from ..errors import error
from ..models import (
    EDIT,
    TRASH,
    Document,
    DocumentNumber,
    Kind,
    Related,
    RelatedDismissed,
    Sender,
    Share,
)
from . import changes, numbers, rights

logger = logging.getLogger("nexpaper.related")

#: The kinds of number a proposal goes by, the surest first (it names the reason).
SUGGEST_KINDS = (numbers.INVOICE, numbers.ORDER, numbers.DELIVERY)
MIN_COMPARE = 5
MAX_CARRIERS = 10
MAX_SUGGESTIONS = 5
INBOX_SUGGESTIONS = 3
#: "Link these together": two to this many documents, every pair among them.
MAX_TOGETHER = 10
# What the history says.
SET, UNSET = "related_set", "related_unset"


def pair_of(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _others(db: Session, document_ids: list[int]) -> dict[int, set[int]]:
    """For each of the documents, the other side of every pair it is in (seen or not)."""
    found: dict[int, set[int]] = {i: set() for i in document_ids}
    if not document_ids:
        return found
    for low, high in db.execute(select(Related.low_id, Related.high_id).where(
            or_(Related.low_id.in_(document_ids), Related.high_id.in_(document_ids)))):
        if low in found:
            found[low].add(high)
        if high in found:
            found[high].add(low)
    return found


# --- The list ------------------------------------------------------------------------------------------------------


@dataclass
class Entry:
    document: Document
    sender: Sender | None
    kind: Kind | None
    #: The caller may remove the pair (``edit`` on both).
    can_unlink: bool
    linked_at: datetime | None


def listing(db: Session, uid: int, document_id: int) -> list[Entry]:
    """What goes with a document the caller may see: only the documents they may see themselves, none in the trash,
    nothing at all while the document itself is in the trash. 404 for a document they may not see."""
    access = rights.require_document(db, uid, document_id)
    if access.document.status == TRASH:
        return []
    pairs = db.execute(select(Related.low_id, Related.high_id, Related.created_at).where(
        or_(Related.low_id == document_id, Related.high_id == document_id))).all()
    when = {(high if low == document_id else low): at for low, high, at in pairs}
    if not when:
        return []
    shown = list(db.scalars(select(Document).where(
        Document.id.in_(list(when)), rights.visible_clause(uid), Document.status != TRASH)
        .order_by(Document.date.desc().nulls_last(), Document.id.desc())))
    editable = set(db.scalars(select(Document.id).where(
        Document.id.in_([d.id for d in shown]), rights.editable_clause(uid)))) if access.can_edit else set()
    senders = {s.id: s for s in db.scalars(select(Sender).where(
        Sender.id.in_({d.sender_id for d in shown if d.sender_id})))}
    kinds = {k.id: k for k in db.scalars(select(Kind).where(Kind.id.in_({d.kind_id for d in shown if d.kind_id})))}
    return [Entry(document=d, sender=senders.get(d.sender_id) if d.sender_id else None,
                  kind=kinds.get(d.kind_id) if d.kind_id else None, can_unlink=d.id in editable,
                  linked_at=when.get(d.id)) for d in shown]


def having(db: Session, uid: int, document_ids: list[int]) -> set[int]:
    """Which of these documents have something the caller can see going with them (the documents themselves not in
    the trash, the others neither): two queries for a whole page."""
    if not document_ids:
        return set()
    other = aliased(Document)
    seen = _visible(uid, other)
    low = select(Related.low_id).join(other, other.id == Related.high_id).where(
        Related.low_id.in_(document_ids), other.status != TRASH, seen)
    high = select(Related.high_id).join(other, other.id == Related.low_id).where(
        Related.high_id.in_(document_ids), other.status != TRASH, seen)
    found = set(db.scalars(low)) | set(db.scalars(high))
    if not found:
        return found
    trashed = set(db.scalars(select(Document.id).where(Document.id.in_(found), Document.status == TRASH)))
    return found - trashed


def _visible(uid: int, document: type[Document] | object) -> ColumnElement[bool]:
    """``rights.visible_clause`` for an alias of ``Document``."""
    table = document
    return or_(
        table.vault_id.in_(rights.member_vault_ids(uid)),  # type: ignore[attr-defined]
        table.id.in_(select(Share.document_id).where(Share.user_id == uid)),  # type: ignore[attr-defined]
    )


def search_clause(uid: int, wanted: bool) -> ColumnElement[bool]:
    """``verknüpft:ja`` / ``linked:yes`` (``wanted``) or ``verknüpft:nein`` / ``linked:no``: the document has something
    going with it that the caller can see, outside the trash (as ``having``)."""
    other = aliased(Document)
    seen = _visible(uid, other)
    low = exists().where(Related.low_id == Document.id, other.id == Related.high_id, other.status != TRASH, seen)
    high = exists().where(Related.high_id == Document.id, other.id == Related.low_id, other.status != TRASH, seen)
    has = and_(Document.status != TRASH, or_(low, high))
    return has if wanted else not_(has)


# --- Setting and removing ------------------------------------------------------------------------------------------


def _both(db: Session, uid: int, a: int, b: int) -> tuple[Document, Document]:
    """Both documents, for a caller who may change both (404 for one they may not see, 403 for one they may only
    read). The caller holds the write lock."""
    if a == b:
        raise error("invalid_related", "A document cannot go with itself.", 422)
    first = rights.require_document(db, uid, a, EDIT).document
    second = rights.require_document(db, uid, b, EDIT).document
    return first, second


def _record(db: Session, uid: int | None, action: str, one: Document, other: Document,
            detail: dict[str, object] | None = None) -> None:
    for document, partner in ((one, other), (other, one)):
        document.change_seq = changes.next_seq(db)
        changes.record(db, document.id, action, user_id=uid, detail={"document": partner.id, **(detail or {})})


def _insert(db: Session, uid: int | None, low: int, high: int) -> bool:
    result = db.execute(sqlite_insert(Related).values(low_id=low, high_id=high, created_by=uid, created_at=clock.now())
                        .on_conflict_do_nothing())
    return bool(getattr(result, "rowcount", 0))


def link(db: Session, uid: int, a: int, b: int) -> bool:
    """Sets the pair; True when it is new (a pair that is there already is no error and changes nothing)."""
    changes.write_lock(db)
    one, other = _both(db, uid, a, b)
    if TRASH in (one.status, other.status):
        raise error("in_trash", "Restore the document first.", 409)
    made = _insert(db, uid, *pair_of(a, b))
    if made:
        _record(db, uid, SET, one, other)
    db.commit()
    return made


def unlink(db: Session, uid: int, a: int, b: int) -> bool:
    """Removes the pair; True when there was one. No question first: it can be set again any time, nothing is lost."""
    changes.write_lock(db)
    one, other = _both(db, uid, a, b)
    low, high = pair_of(a, b)
    result = db.execute(delete(Related).where(Related.low_id == low, Related.high_id == high))
    gone = bool(getattr(result, "rowcount", 0))
    if gone:
        _record(db, uid, UNSET, one, other)
    db.commit()
    return gone


def dismiss(db: Session, uid: int, a: int, b: int) -> None:
    """"Passt nicht": the pair is not proposed again (to anybody). Changes nothing at the documents."""
    changes.write_lock(db)
    _both(db, uid, a, b)
    low, high = pair_of(a, b)
    db.execute(sqlite_insert(RelatedDismissed).values(low_id=low, high_id=high, created_by=uid,
                                                      created_at=clock.now()).on_conflict_do_nothing())
    db.commit()


@dataclass
class Together:
    """What "link these together" did: pairs set now, pairs that were there, documents left out with the reason."""

    linked: int = 0
    already: int = 0
    refused: list[tuple[int, str]] = field(default_factory=list)


def link_all(db: Session, uid: int, ids: list[int]) -> Together:
    """Every pair among the documents (2 to ``MAX_TOGETHER``), in one transaction. A document the caller may not change
    (or see), or one in the trash, is left out and named with the reason (``not_found``, ``forbidden``, ``in_trash``);
    the others are linked among themselves. The bulk route of the archive calls this."""
    wanted = list(dict.fromkeys(ids))
    if not 2 <= len(wanted) <= MAX_TOGETHER:
        raise error("invalid_related", f"Link 2 to {MAX_TOGETHER} documents.", 422)
    result = Together()
    changes.write_lock(db)
    taken: list[Document] = []
    for document_id in wanted:
        try:
            document = rights.require_document(db, uid, document_id, EDIT).document
        except HTTPException as exc:
            code = exc.detail.get("code", "failed") if isinstance(exc.detail, dict) else "failed"
            result.refused.append((document_id, str(code)))
            continue
        if document.status == TRASH:
            result.refused.append((document_id, "in_trash"))
            continue
        taken.append(document)
    for index, one in enumerate(taken):
        for other in taken[index + 1:]:
            if _insert(db, uid, *pair_of(one.id, other.id)):
                _record(db, uid, SET, one, other)
                result.linked += 1
            else:
                result.already += 1
    db.commit()
    logger.info("Documents linked together by=%s linked=%s already=%s refused=%s", uid, result.linked, result.already,
                len(result.refused))
    return result


def inherit(db: Session, uid: int | None, into: Document, sources: list[Document]) -> int:
    """Joining pages (``pagetools.merge``): the document that stays takes over the pairs of the ones joined into it,
    never one with itself or among them. In the caller's transaction (under the write lock). Returns how many pairs are
    new."""
    source_ids = {d.id for d in sources}
    left_out = source_ids | {into.id}
    partners = set().union(*_others(db, sorted(source_ids)).values()) - left_out if source_ids else set()
    made = 0
    for partner_id in sorted(partners):
        partner = db.get(Document, partner_id)
        if partner is None:
            continue
        if _insert(db, uid, *pair_of(into.id, partner_id)):
            _record(db, uid, SET, into, partner, {"by": "merge"})
            made += 1
    return made


# --- Proposals -----------------------------------------------------------------------------------------------------


@dataclass
class Suggestion:
    document: Document
    sender: Sender | None
    kind: Kind | None
    #: The kind of number they share: ``invoice``, ``order`` or ``delivery``.
    via: str


def suggestions(db: Session, uid: int, document_ids: list[int],
                limit: int = MAX_SUGGESTIONS) -> dict[int, list[Suggestion]]:
    """Per document the caller may change (the others get none), the documents to propose, in a few queries for all of
    them. See the top of this file for the rule."""
    out: dict[int, list[Suggestion]] = {}
    if not document_ids:
        return out
    editable = set(db.scalars(select(Document.id).where(
        Document.id.in_(document_ids), rights.editable_clause(uid), Document.status != TRASH)))
    if not editable:
        return out
    mine = db.execute(select(DocumentNumber.document_id, DocumentNumber.kind, DocumentNumber.compare).where(
        DocumentNumber.document_id.in_(editable), DocumentNumber.kind.in_(SUGGEST_KINDS),
        func.length(DocumentNumber.compare) >= MIN_COMPARE)).all()
    keys = {(kind, compare) for _d, kind, compare in mine if any(char.isdigit() for char in compare)}
    if not keys:
        return out
    compares = sorted({compare for _kind, compare in keys})
    # How many documents the caller sees carry each number: one on more than ``MAX_CARRIERS`` says nothing.
    counted = db.execute(
        select(DocumentNumber.kind, DocumentNumber.compare, func.count(func.distinct(DocumentNumber.document_id)))
        .join(Document, Document.id == DocumentNumber.document_id)
        .where(DocumentNumber.compare.in_(compares), DocumentNumber.kind.in_(SUGGEST_KINDS),
               rights.visible_clause(uid), Document.status != TRASH)
        .group_by(DocumentNumber.kind, DocumentNumber.compare)).all()
    usable = {(kind, compare) for kind, compare, count in counted if (kind, compare) in keys and count <= MAX_CARRIERS}
    if not usable:
        return out
    carriers: dict[tuple[str, str], set[int]] = {}
    for document_id, kind, compare in db.execute(
            select(DocumentNumber.document_id, DocumentNumber.kind, DocumentNumber.compare)
            .join(Document, Document.id == DocumentNumber.document_id)
            .where(DocumentNumber.compare.in_(sorted({c for _k, c in usable})),
                   DocumentNumber.kind.in_(SUGGEST_KINDS), rights.editable_clause(uid), Document.status != TRASH)):
        if (kind, compare) in usable:
            carriers.setdefault((kind, compare), set()).add(document_id)
    candidates: dict[int, dict[int, set[str]]] = {}
    for document_id, kind, compare in mine:
        for other in carriers.get((kind, compare), ()):
            if other != document_id:
                candidates.setdefault(document_id, {}).setdefault(other, set()).add(kind)
    if not candidates:
        return out
    every = set(candidates) | {o for found in candidates.values() for o in found}
    closed = _closed_pairs(db, sorted(set(candidates)))
    documents = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_(every)))}
    sender_keys = dict(db.execute(select(Document.id, Sender.key).join(Sender, Sender.id == Document.sender_id)
                                  .where(Document.id.in_(every))).all())
    senders = {s.id: s for s in db.scalars(select(Sender).where(
        Sender.id.in_({d.sender_id for d in documents.values() if d.sender_id})))}
    kinds = {k.id: k for k in db.scalars(select(Kind).where(
        Kind.id.in_({d.kind_id for d in documents.values() if d.kind_id})))}
    for document_id, found in candidates.items():
        own_sender = sender_keys.get(document_id)
        ranked = []
        for other_id, via in found.items():
            if pair_of(document_id, other_id) in closed:
                continue
            if _senders_differ(own_sender, sender_keys.get(other_id)):
                continue
            other = documents.get(other_id)
            if other is None:
                continue
            reason = next(kind for kind in SUGGEST_KINDS if kind in via)
            ranked.append((-len(via), SUGGEST_KINDS.index(reason), -(other.id), other, reason))
        ranked.sort(key=lambda item: item[:3])
        if ranked:
            out[document_id] = [Suggestion(document=other, sender=senders.get(other.sender_id) if other.sender_id
                                           else None, kind=kinds.get(other.kind_id) if other.kind_id else None,
                                           via=reason) for *_rank, other, reason in ranked[:limit]]
    return out


def _senders_differ(one: str | None, other: str | None) -> bool:
    """Both documents have a sender and they are not the same (by the name's key): not proposed."""
    return one is not None and other is not None and one != other


def _closed_pairs(db: Session, document_ids: list[int]) -> set[tuple[int, int]]:
    """The pairs of these documents that are set already or were turned down."""
    found: set[tuple[int, int]] = set()
    for table in (Related, RelatedDismissed):
        for low, high in db.execute(select(table.low_id, table.high_id).where(
                or_(table.low_id.in_(document_ids), table.high_id.in_(document_ids)))):
            found.add((low, high))
    return found


def suggestions_for(db: Session, uid: int, document_id: int) -> list[Suggestion]:
    """The proposals for one document the caller may see (404 else); none when they may not change it."""
    rights.require_document(db, uid, document_id)
    return suggestions(db, uid, [document_id]).get(document_id, [])


__all__ = ["INBOX_SUGGESTIONS", "MAX_SUGGESTIONS", "MAX_TOGETHER", "SET", "UNSET", "Entry", "Suggestion", "Together",
           "dismiss", "having", "inherit", "link", "link_all", "listing", "pair_of", "search_clause", "suggestions",
           "suggestions_for", "unlink"]
