"""The search: what a person may see, found by words, phrases and filters, newest first, with an excerpt.

**Rights are in the query, twice.** The words are looked up in the index only among the entries in the caller's scope:
``{scope}: (v3v OR v12v OR u7u)`` (the vaults the caller is a member of, and their own token for documents shared with
them; ``services/search_index.py`` writes them), so the index never reads the entries of documents the caller cannot
see, and the time a search takes does not depend on them. The statement that finds and counts carries the rights
once more (``visible``), so the number, the order and the excerpts follow only what the caller may see. Nothing is
filtered or counted afterwards. Each person may search ``brakes.LIMITS["search"]`` times a minute
(typing with a pause between keystrokes stays well below it).

**How a word is found** (decided by the measurement in ``docs/search.md``): a word of ``searchtext.MIDDLE_MIN``
letters and more anywhere in a word, through the trigram index ``doc_tri`` (``werke`` finds ``Stadtwerke``, ``abschlag``
finds ``Stromabschlag``); a shorter word at the start of a word, through the word index ``doc_fts``; a phrase as its
words in a row, through the word index. Every term must be found, each in any of the fields.

**The trash** is searched only when asked for (``trash``), and then only the caller's own documents in it.

Order: by the document's date (the day it came in when it has none), newest first, then by id. ``next`` is a cursor for
the following page; it holds the place of the last document of this page, nothing else. The archive's table asks for a
numbered ``page`` instead and may sort by title, sender or amount too (``ORDERS``); a document without a sender or an
amount comes last either way, and equal ones keep the newest first.

``overview`` counts what the same rights and filters find, by sender, kind, year and tag: the start of the archive.
"""

from __future__ import annotations

import base64
import binascii
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import timedelta
from typing import Any

from sqlalchemy import ColumnElement, Integer, String, and_, bindparam, cast, column, exists, func, or_, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..errors import error
from ..models import (
    FTS_TABLE,
    TRASH,
    TRI_TABLE,
    Document,
    DocumentDate,
    DocumentTag,
    Kind,
    Sender,
    Share,
    Tag,
    Version,
    VersionText,
)
from ..names import name_key
from . import changes, deadlines, documents, rights, search_index, searchtext

logger = logging.getLogger("nexpaper.search")

MAX_LIMIT = 100
#: The orders a page may be asked in; a minus is the largest (the newest, Z) first.
ORDERS = ("-date", "date", "-title", "title", "-sender", "sender", "-amount", "amount")
#: Highest page number a search takes (with 100 a page, ten million documents).
MAX_PAGE = 100_000
#: Longest a search may take in the database.
MAX_SECONDS = 10.0
#: How many steps of the database engine run between two looks at the clock.
PROGRESS_STEPS = 10_000
#: Time for the excerpts of one answer (seconds). What is left after it gets the start of its text, unmarked: a page of
#: hits in very long texts must not keep the answer waiting.
EXCERPT_SECONDS = 1.0


@dataclass
class Filters:
    vault_id: int | None = None
    kind_id: int | None = None
    sender: str | None = None
    tag: str | None = None
    owner_id: int | None = None
    date_from: Date | None = None
    date_to: Date | None = None
    status: str | None = None
    trash: bool = False
    #: Only the documents the caller sees through a share alone (true), or only those of their vaults (false).
    via_share: bool | None = None
    #: Only documents with a deadline that is ``open``, ``overdue``, ``done``, or open within that many days.
    deadline: str | int | None = None
    #: Today for the deadlines (the caller's day); the server's when not given.
    today: Date | None = None


@dataclass
class Hit:
    row: documents.Row
    title_marks: list[tuple[int, int]] = field(default_factory=list)
    sender_marks: list[tuple[int, int]] = field(default_factory=list)
    #: (excerpt, its marks, where it is from: ``text`` or ``notes``) or nothing.
    snippet: tuple[str, list[tuple[int, int]], str] | None = None


@dataclass
class Result:
    hits: list[Hit]
    total: int
    next: str | None
    query: searchtext.Query


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _match(table: str, expression: str) -> ColumnElement[bool]:
    """``Document.id`` among the rows of a full-text table that match ``expression`` (built of quoted tokens only)."""
    lookup = text(f"SELECT rowid FROM {table} WHERE {table} MATCH :expr")  # noqa: S608 - table is a constant
    lookup = lookup.bindparams(bindparam("expr", value=expression, unique=True)).columns(column("rowid", Integer))
    return Document.id.in_(lookup)


#: The columns the words are looked for in (never ``scope``).
CONTENT = "{title sender text notes tags}"


def scope_of(db: Session, uid: int) -> list[str]:
    """The scope tokens of ``uid``: their vaults, and their own token for what is shared with them."""
    vaults = db.scalars(rights.member_vault_ids(uid))
    return [search_index.vault_token(v) for v in sorted(vaults)] + [search_index.person_token(uid)]


def scoped(scope: list[str], expression: str) -> str:
    """An FTS5 query limited to the entries of the scope: ``{scope}: (a OR b) AND {content}: (expression)``."""
    return "{scope} : (" + " OR ".join(f'"{token}"' for token in scope) + f") AND {CONTENT} : ({expression})"


def text_clauses(query: searchtext.Query, scope: list[str]) -> list[ColumnElement[bool]]:
    """The words and phrases, as at most two lookups (one in the trigram index, one in the word index), each only among
    the entries in ``scope``."""
    middle: list[str] = []
    start: list[str] = []
    for word in query.words:
        if len(word) >= searchtext.MIDDLE_MIN:
            middle.append(searchtext.fts_string([word], False))
        else:
            # A single letter as a whole word only: as a beginning it would be nearly every document.
            start.append(searchtext.fts_string([word], len(word) > 1))
    for parts, prefix in query.phrases:
        start.append(searchtext.fts_string(parts, prefix))
    clauses = []
    if middle:
        clauses.append(_match(TRI_TABLE, scoped(scope, " AND ".join(middle))))
    if start:
        clauses.append(_match(FTS_TABLE, scoped(scope, " AND ".join(start))))
    return clauses


def filter_clauses(query: searchtext.Query) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = []
    for value in query.kinds:
        pattern = _escape_like(name_key(value)) + "%"
        clauses.append(Document.kind_id.in_(select(Kind.id).where(or_(
            Kind.name_key.like(pattern, escape="\\"), Kind.key.like(pattern, escape="\\")))))
    for value in query.senders:
        pattern = "%" + _escape_like(name_key(value)) + "%"
        clauses.append(Document.sender_id.in_(select(Sender.id).where(Sender.key.like(pattern, escape="\\"))))
    for value in query.tags:
        pattern = _escape_like(name_key(value.lstrip("#"))) + "%"
        clauses.append(exists().where(DocumentTag.document_id == Document.id, DocumentTag.tag_id == Tag.id,
                                      Tag.key.like(pattern, escape="\\")))
    for amount in query.amounts:
        column = Document.amount
        clauses.append(column > amount.cents if amount.op == ">" else column < amount.cents if amount.op == "<"
                       else column == amount.cents)
    return clauses


def _sort_key() -> ColumnElement[Any]:
    # The document's date, else the day it came in: both as YYYY-MM-DD, which sorts as text.
    return func.coalesce(cast(Document.date, String), func.substr(cast(Document.added_at, String), 1, 10))


def _cursor(key: str, document_id: int) -> str:
    return base64.urlsafe_b64encode(f"{key}|{document_id}".encode()).decode().rstrip("=")


def _read_cursor(value: str) -> tuple[str, int]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("ascii")
        key, _, number = raw.partition("|")
        document_id = int(number)
        Date.fromisoformat(key)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise error("invalid_cursor", "This cursor is not one the search gave.", 422) from exc
    if not 0 < document_id < 2**31:
        raise error("invalid_cursor", "This cursor is not one the search gave.", 422)
    return key, document_id


def visible(uid: int) -> ColumnElement[bool]:
    """``rights.visible_clause`` as the search needs it: the vault is compared on every row (``vault_id + 0`` keeps
    SQLite from fetching the documents vault by vault through the index, which for a person in many vaults took
    seconds with 200,000 documents; a pass over the table takes a tenth of that, and the word index narrows it first
    when there are words)."""
    return or_(
        (Document.vault_id + 0).in_(rights.member_vault_ids(uid)),
        Document.id.in_(select(Share.document_id).where(Share.user_id == uid)),
    )


def where(uid: int, query: searchtext.Query, filters: Filters, scope: list[str]) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = [visible(uid)]
    if filters.trash:
        # Only the caller's own documents in the trash.
        clauses += [Document.status == TRASH, Document.owner_id == uid]
    elif filters.status is not None:
        clauses.append(Document.status == filters.status)
    else:
        clauses.append(Document.status != TRASH)
    if filters.vault_id is not None:
        clauses.append(Document.vault_id == filters.vault_id)
    if filters.kind_id is not None:
        # The kind, and the kinds of the same name in the vaults the caller is in (every vault has kinds of its own, and
        # the archive filters by the name). A kind of a vault the caller is not in has no namesakes for them.
        name = select(Kind.name_key).where(Kind.id == filters.kind_id, or_(
            Kind.vault_id.is_(None), Kind.vault_id.in_(rights.member_vault_ids(uid)))).scalar_subquery()
        clauses.append(or_(Document.kind_id == filters.kind_id,
                           Document.kind_id.in_(select(Kind.id).where(Kind.name_key == name))))
    if filters.owner_id is not None:
        clauses.append(Document.owner_id == filters.owner_id)
    if filters.sender is not None:
        clauses.append(Document.sender_id.in_(select(Sender.id).where(Sender.key == name_key(filters.sender.strip()))))
    if filters.tag is not None:
        clauses.append(exists().where(DocumentTag.document_id == Document.id, DocumentTag.tag_id == Tag.id,
                                      Tag.key == name_key(filters.tag.strip())))
    if filters.date_from is not None:
        clauses.append(Document.date >= filters.date_from)
    if filters.date_to is not None:
        clauses.append(Document.date <= filters.date_to)
    if filters.via_share is not None:
        in_vault = (Document.vault_id + 0).in_(rights.member_vault_ids(uid))
        clauses.append(~in_vault if filters.via_share else in_vault)
    today = filters.today or deadlines.server_today()
    for wanted in ([filters.deadline] if filters.deadline is not None else []) + list(query.deadlines):
        clauses.append(deadline_clause(wanted, today))
    return clauses + filter_clauses(query) + text_clauses(query, scope)


def deadline_clause(wanted: str | int, today: Date) -> ColumnElement[bool]:
    """The document has a deadline (``services/deadlines.py``) that is ``open``, ``overdue`` or ``done``, or one that
    is open and due within ``wanted`` days (overdue ones included)."""
    rows = [DocumentDate.document_id == Document.id, *deadlines.deadline_rows()]
    if wanted == "done":
        rows.append(DocumentDate.done_at.is_not(None))
    else:
        rows.append(deadlines.is_open())
        if wanted == "overdue":
            rows.append(deadlines.act_by(today) < today)
        elif isinstance(wanted, int):
            rows.append(deadlines.act_by(today) <= today + timedelta(days=wanted))
    return exists().where(*rows)


@contextmanager
def _bounded(db: Session) -> Iterator[None]:
    """A search that runs longer than ``MAX_SECONDS`` is stopped by SQLite itself (a progress handler), and answers
    503: no search holds a connection and a processor for long, however it is put together."""
    raw = db.connection().connection.driver_connection
    deadline = time.monotonic() + MAX_SECONDS
    raw.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, PROGRESS_STEPS)
    try:
        yield
    except OperationalError:
        # Stopped by the handler: the message is SQLite's ("interrupted", or what the step it stopped in says).
        if time.monotonic() <= deadline:
            raise
        logger.warning("A search was stopped at the time limit seconds=%s", MAX_SECONDS)
        raise error("search_too_slow", "This search takes too long. Narrow it down with more words or filters.",
                    503) from None
    finally:
        raw.set_progress_handler(None, 0)


def _order(order: str) -> list[ColumnElement[Any]]:
    """The ``ORDER BY`` of ``order``: the column, empty ones last, then the newest first and the id."""
    key = _sort_key()
    newest = [key.desc(), Document.id.desc()]
    down = order.startswith("-")
    name = order.lstrip("-")
    if name == "date":
        return newest if down else [key.asc(), Document.id.asc()]
    column: ColumnElement[Any]
    if name == "title":
        column = Document.title.collate("NOCASE")
    elif name == "sender":
        column = select(Sender.key).where(Sender.id == Document.sender_id).scalar_subquery()
    else:
        column = Document.amount
    return [column.is_(None), column.desc() if down else column.asc(), *newest]


def find(db: Session, uid: int, raw: str, filters: Filters, *, cursor: str | None = None, limit: int = 50,
         order: str = "-date", page: int | None = None) -> Result:
    """One page of what ``uid`` may see that the search ``raw`` finds, with the total: after ``cursor`` (newest first
    only), or the numbered ``page`` in ``order``."""
    if order not in ORDERS:
        raise error("invalid_order", "Sort by one of: " + ", ".join(ORDERS) + ".", 422)
    if cursor and (page is not None or order != "-date"):
        raise error("cursor_and_page", "A cursor goes with the newest first and no page number.", 422)
    if page is not None and not 1 <= page <= MAX_PAGE:
        raise error("invalid_page", f"Ask for a page from 1 to {MAX_PAGE}.", 422, max=MAX_PAGE)
    query = _parse(raw)
    limit = max(1, min(limit, MAX_LIMIT))
    clauses = where(uid, query, filters, scope_of(db, uid) if query.has_text else [])
    key = _sort_key()
    with changes.snapshot(db), _bounded(db):
        total = int(db.scalar(select(func.count()).select_from(Document).where(and_(*clauses))) or 0)
        statement = select(Document, key.label("sort_key")).where(and_(*clauses))
        if cursor:
            after_key, after_id = _read_cursor(cursor)
            statement = statement.where(or_(key < after_key, and_(key == after_key, Document.id < after_id)))
        statement = statement.order_by(*_order(order))
        if page is not None:
            statement = statement.offset((page - 1) * limit)
        found = db.execute(statement.limit(limit + 1)).all()
        more = len(found) > limit
        found = found[:limit]
        rows = documents.rows(db, uid, [row[0] for row in found])
        hits = _hits(db, query, rows)
    # A numbered page has no cursor: the next one is the next number.
    paged = page is not None or order != "-date"
    next_cursor = _cursor(found[-1][1], found[-1][0].id) if more and found and not paged else None
    return Result(hits=hits, total=total, next=next_cursor, query=query)


def _parse(raw: str) -> searchtext.Query:
    try:
        return searchtext.parse(raw)
    except searchtext.SearchError as exc:
        message = {"query_too_long": f"Use at most {searchtext.MAX_LENGTH} characters.",
                   "too_many_terms": f"Use at most {searchtext.MAX_TERMS} words and filters.",
                   "invalid_amount": "Write an amount like betrag:>100 or amount:<12,50.",
                   "invalid_deadline": "Write frist:offen, frist:überfällig, frist:erledigt or frist:<30 "
                                       "(deadline:open, overdue, done, <30)."}[exc.code]
        limit_of = {"query_too_long": searchtext.MAX_LENGTH, "too_many_terms": searchtext.MAX_TERMS}
        values = {"max": limit_of[exc.code]} if exc.code in limit_of else {}
        raise error(exc.code, message, 422, **values) from exc


@dataclass
class Overview:
    total: int
    #: (name, number of documents), most first; senders and tags of the same name in two vaults are one.
    senders: list[tuple[str, int]]
    #: (a kind of that name, number), most first; the search counts the kinds of the same name in when one is asked for.
    kinds: list[tuple[Kind, int]]
    #: (year of the document's date, number), the newest year first; a document without a date is in no year.
    years: list[tuple[int, int]]
    tags: list[tuple[str, int]]


def overview(db: Session, uid: int, filters: Filters) -> Overview:
    """How many documents ``uid`` may see with ``filters``, and how they spread over senders, kinds, years and tags:
    the same rights and filters as ``find``, so nothing is counted that the caller could not open."""
    clauses = where(uid, searchtext.parse(""), filters, [])
    seen = select(Document.id).where(and_(*clauses))
    most = func.count().desc()
    year = func.substr(cast(Document.date, String), 1, 4)
    with changes.snapshot(db), _bounded(db):
        total = int(db.scalar(select(func.count()).select_from(Document).where(and_(*clauses))) or 0)
        senders = db.execute(
            select(func.min(Sender.name), func.count()).join(Document, Document.sender_id == Sender.id)
            .where(Document.id.in_(seen)).group_by(Sender.key).order_by(most, func.min(Sender.name))
        ).all()
        kind_rows = db.execute(
            select(func.min(Kind.id), func.count()).join(Document, Document.kind_id == Kind.id)
            .where(Document.id.in_(seen)).group_by(Kind.name_key).order_by(most, func.min(Kind.name))
        ).all()
        kinds = {kind.id: kind for kind in db.scalars(select(Kind).where(Kind.id.in_([row[0] for row in kind_rows])))}
        years = db.execute(
            select(year, func.count()).where(Document.id.in_(seen), Document.date.is_not(None))
            .group_by(year).order_by(year.desc())
        ).all()
        tags = db.execute(
            select(func.min(Tag.name), func.count()).join(DocumentTag, DocumentTag.tag_id == Tag.id)
            .where(DocumentTag.document_id.in_(seen)).group_by(Tag.key).order_by(most, func.min(Tag.name))
        ).all()
    return Overview(
        total=total,
        senders=[(name, int(n)) for name, n in senders],
        kinds=[(kinds[kind_id], int(n)) for kind_id, n in kind_rows if kind_id in kinds],
        years=[(int(y), int(n)) for y, n in years if y and y.isdigit()],
        tags=[(name, int(n)) for name, n in tags],
    )


def _hits(db: Session, query: searchtext.Query, rows: list[documents.Row]) -> list[Hit]:
    terms = query.patterns()
    if not terms:
        return [Hit(row=row) for row in rows]
    ids = [row.document.id for row in rows]
    texts = dict(db.execute(
        select(Document.id, VersionText.text)
        .join(Version, (Version.document_id == Document.id) & (Version.n == Document.current_version))
        .join(VersionText, VersionText.version_id == Version.id).where(Document.id.in_(ids))
    ).all()) if ids else {}
    hits = []
    deadline = time.monotonic() + EXCERPT_SECONDS
    for row in rows:
        hit = Hit(row=row, title_marks=searchtext.find_marks(row.document.title, terms),
                  sender_marks=searchtext.find_marks(row.sender.name, terms) if row.sender else [])
        body = texts.get(row.document.id) or ""
        if time.monotonic() > deadline:
            start = " ".join(body[: searchtext.SNIPPET_SIDE * 2].split())
            hit.snippet = (start, [], "text") if start else None
            hits.append(hit)
            continue
        excerpt, marks = searchtext.snippet(body, terms)
        if marks:
            hit.snippet = (excerpt, marks, "text")
        else:
            notes = _notes_snippet(db, row.document.id, terms)
            hit.snippet = notes if notes else ((excerpt, [], "text") if excerpt else None)
        hits.append(hit)
    return hits


def _notes_snippet(db: Session, document_id: int, terms: list[str]) -> tuple[str, list[tuple[int, int]], str] | None:
    from ..models import Note

    for body in db.scalars(select(Note.text).where(Note.document_id == document_id).order_by(Note.id)):
        excerpt, marks = searchtext.snippet(body, terms)
        if marks:
            return excerpt, marks, "notes"
    return None


__all__ = [
    "MAX_LIMIT", "MAX_PAGE", "ORDERS", "Filters", "Hit", "Overview", "Result", "find", "overview", "text_clauses",
    "where",
]
