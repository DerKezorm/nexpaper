"""The inbox as a list for people: what waits there, found by words and filters, a page at a time, and filed in bulk.

**Who sees what.** The inbox of a person is every document that is not filed yet in a vault where they may *change*
things (``edit`` or ``manage``), and every document shared with them with ``edit``. A member with ``read`` only does not
see the inbox of that vault: they cannot file anything there, so a list of things they may only look at would be noise
(and a number in the menu they cannot bring down). The rights are in the query, so no count includes what the caller
may not see.

**A page at a time.** The list holds thousands after an import; a page is at most ``MAX_PAGE`` documents, in the order
chosen (``new``, ``old``, ``date``), what is still being read first. ``total`` follows the filters, ``counts`` says how
many each vault would show under the same filters apart from the vault itself (the chips above the list). A document the
caller may change only through a share of its own is in no vault of theirs: it is counted in ``shared``, a group
without a vault number, and ``shared=true`` lists just those.

**Words.** ``q`` is looked for in the title and in the sender's name, case and accents aside (``names.search_key``, as
an SQL function: ``db.py``), or in the text, notes and tags through the search index of the archive (``search``): its
words, parts of words included, only among the entries of the caller's vaults and shares (the scope tokens), under the
same time limit. Filters written in the words (``art:``, ``betrag:``) are not read here; the inbox has its own.

**Filing many.** ``file_many`` takes at most ``MAX_BULK`` documents and treats every one on its own, with the same
checks as the single change: the right in its vault, the state it is in, the kind it may have. One that fails is named
with the reason, the others go on. What is shared for all of them: a vault (they move there first), a kind, tags to add.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_, case, func, or_, select
from sqlalchemy.orm import Session

from ..errors import error
from ..models import EDIT, FILED, INBOX, MANAGE, PROCESSING, TRASH, Document, DocumentTag, Sender, Tag, VaultMember
from ..names import name_key, search_key
from . import catalog, documents, rights, search, searchtext

logger = logging.getLogger("nexpaper.inbox")

MAX_PAGE = 200
MAX_BULK = 200
SORTS = ("new", "old", "date")


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def waiting(uid: int) -> ColumnElement[bool]:
    """The documents of the inbox the caller may work on: being read or waiting, and theirs to change."""
    return and_(Document.status.in_((PROCESSING, INBOX)), rights.editable_clause(uid))


@dataclass
class Filters:
    q: str = ""
    sender: str | None = None
    kind_id: int | None = None
    source: str | None = None
    owner_id: int | None = None
    vault_id: int | None = None
    #: Only the documents the caller reaches through a share alone.
    shared: bool = False


def _own_vaults(uid: int) -> ColumnElement[bool]:
    """The document lies in a vault where the caller may change things."""
    return Document.vault_id.in_(select(VaultMember.vault_id).where(VaultMember.user_id == uid,
                                                                  VaultMember.right.in_((EDIT, MANAGE))))


def _in_text(db: Session, uid: int, words: str) -> ColumnElement[bool] | None:
    """The documents whose text, notes or tags hold ``words``, among those ``uid`` reaches (the index's scope)."""
    try:
        query = searchtext.parse(words)
    except searchtext.SearchError:
        return None
    if not query.has_text:
        return None
    clauses = search.text_clauses(query, search.scope_of(db, uid))
    return and_(*clauses) if clauses else None


def _conditions(f: Filters, *, with_vault: bool,
                in_text: ColumnElement[bool] | None = None) -> list[ColumnElement[bool]]:
    out: list[ColumnElement[bool]] = []
    if f.q.strip():
        pattern = _like(search_key(f.q.strip())[:200])
        out.append(or_(
            func.search_key(Document.title).like(pattern, escape="\\"),
            Document.sender_id.in_(select(Sender.id).where(func.search_key(Sender.name).like(pattern, escape="\\"))),
            *([in_text] if in_text is not None else []),
        ))
    if f.sender is not None:
        out.append(Document.sender_id.in_(select(Sender.id).where(Sender.key == name_key(f.sender.strip()))))
    if f.kind_id is not None:
        out.append(Document.kind_id == f.kind_id)
    if f.source is not None:
        out.append(Document.source == f.source)
    if f.owner_id is not None:
        out.append(Document.owner_id == f.owner_id)
    if with_vault and f.vault_id is not None:
        out.append(Document.vault_id == f.vault_id)
    return out


@dataclass
class Page:
    documents: list[Document]
    total: int
    #: Per vault of the caller (where they may change things).
    counts: dict[int, int]
    #: The documents reached through a share alone, in no vault of the caller's.
    shared: int
    reading: int


def listing(db: Session, uid: int, f: Filters, *, sort: str = "new", limit: int = 50, offset: int = 0) -> Page:
    limit = max(1, min(limit, MAX_PAGE))
    with search._bounded(db):
        return _listing(db, uid, f, sort=sort, limit=limit, offset=offset)


def _listing(db: Session, uid: int, f: Filters, *, sort: str, limit: int, offset: int) -> Page:
    in_text = _in_text(db, uid, f.q.strip()[:searchtext.MAX_LENGTH]) if f.q.strip() else None
    base = [waiting(uid), *_conditions(f, with_vault=False, in_text=in_text)]
    own = _own_vaults(uid)
    # A vault number only for vaults the caller is in; whatever else they may change comes through a share.
    grouped = case((own, Document.vault_id), else_=0)
    counts = {int(vault): int(n) for vault, n in db.execute(
        select(grouped, func.count()).where(*base).group_by(grouped)).all()}
    shared = counts.pop(0, 0)
    scoped = [*base, *([Document.vault_id == f.vault_id] if f.vault_id is not None else []),
              *([~own] if f.shared else [])]
    total = int(db.scalar(select(func.count()).select_from(Document).where(*scoped)) or 0)
    reading = int(db.scalar(select(func.count()).select_from(Document).where(
        *scoped, Document.status == PROCESSING)) or 0)
    if sort == "old":
        order = [Document.added_at.asc(), Document.id.asc()]
    elif sort == "date":
        # The day on the document, else the day it came in.
        order = [func.coalesce(Document.date, func.substr(Document.added_at, 1, 10)).desc(), Document.id.desc()]
    else:
        order = [Document.added_at.desc(), Document.id.desc()]
    first_reading = case((Document.status == PROCESSING, 0), else_=1)
    found = list(db.scalars(select(Document).where(*scoped).order_by(first_reading, *order).limit(limit)
                            .offset(max(0, offset))))
    return Page(documents=found, total=total, counts=counts, shared=shared, reading=reading)


@dataclass
class Counts:
    inbox: int
    reading: int
    trash: int


def menu_counts(db: Session, uid: int) -> Counts:
    """What the menu shows beside "Eingang" and "Papierkorb"."""
    per_status = dict(db.execute(
        select(Document.status, func.count()).where(waiting(uid)).group_by(Document.status)).all())
    trash = int(db.scalar(select(func.count()).select_from(Document).where(
        rights.visible_clause(uid), Document.status == TRASH)) or 0)
    return Counts(inbox=int(per_status.get(INBOX, 0)), reading=int(per_status.get(PROCESSING, 0)), trash=trash)


@dataclass
class Result:
    filed: list[int] = field(default_factory=list)
    failed: list[tuple[int, str]] = field(default_factory=list)


def file_many(db: Session, uid: int, ids: list[int], *, vault_id: int | None, kind_id: int | None,
              add_tags: list[str]) -> Result:
    """Files the documents, each on its own. Returns which were filed and which not, with the reason (the code of the
    error a single change would have given). A document the caller may not see fails as ``not_found``, exactly as one
    that does not exist."""
    if len(ids) > MAX_BULK:
        raise error("too_many", f"At most {MAX_BULK} documents at once.", 422)
    result = Result()
    for document_id in dict.fromkeys(ids):
        try:
            _file_one(db, uid, document_id, vault_id, kind_id, add_tags)
            result.filed.append(document_id)
        except HTTPException as exc:
            db.rollback()
            code = exc.detail.get("code", "failed") if isinstance(exc.detail, dict) else "failed"
            result.failed.append((document_id, str(code)))
    logger.info("Documents filed in bulk by=%s filed=%s failed=%s", uid, len(result.filed), len(result.failed))
    return result


def _tags_after(db: Session, document_id: int, add_tags: list[str]) -> list[str]:
    """The tags the document has, plus the new ones it has not got yet."""
    have = list(db.scalars(select(Tag.name).join(DocumentTag, DocumentTag.tag_id == Tag.id)
                           .where(DocumentTag.document_id == document_id)))
    known = {name_key(name) for name in have}
    return have + [name for name in add_tags if name_key(name) not in known]


def _file_one(db: Session, uid: int, document_id: int, vault_id: int | None, kind_id: int | None,
              add_tags: list[str]) -> None:
    access = rights.require_document(db, uid, document_id, rights.EDIT)
    document = access.document
    if document.status == PROCESSING:
        raise error("still_processing", "The document is still being read.", 409)
    if document.status == TRASH:
        raise error("in_trash", "Restore the document first.", 409)
    if document.status != INBOX:
        raise error("not_in_inbox", "The document is filed already.", 409)
    # Everything that could refuse the change is looked at before the document moves: a kind or a tag the target does
    # not accept must leave it where it was, in its old vault, unchanged.
    target = vault_id if vault_id is not None else document.vault_id
    if vault_id is not None and vault_id != document.vault_id:
        rights.require_vault(db, uid, vault_id, rights.EDIT)
    if kind_id is not None:
        catalog.kind_in_scope(db, kind_id, target)
    tags = _tags_after(db, document_id, add_tags) if add_tags else None
    if tags is not None:
        catalog.check_tags(tags)
    # The checks above only read; the changes below begin with the write lock, so the read ends here.
    db.rollback()
    if vault_id is not None and vault_id != document.vault_id:
        documents.move(db, uid, document_id, vault_id)
    patch: dict[str, Any] = {"status": FILED}
    if kind_id is not None:
        patch["kind_id"] = kind_id
    if tags is not None:
        patch["tags"] = tags
    documents.update_fields(db, uid, document_id, patch)


__all__ = ["MAX_BULK", "MAX_PAGE", "SORTS", "Counts", "Filters", "Page", "Result", "file_many", "listing",
           "menu_counts", "waiting"]
