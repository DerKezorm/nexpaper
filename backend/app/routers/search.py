"""The search, and the text of a document page by page.

``GET /api/v1/search`` finds what the caller may see (a signed-in browser, a device, a program with a read key): the
language of the archive's search field (``services/searchtext.py``) plus filters as parameters, newest first, with the
total and a cursor for the next page. Each hit carries the places to mark in its title and sender and an excerpt of
its text, as ranges, never as HTML. The archive's table asks for numbered pages (``page``) in an order of its choice
(``sort``) instead of the cursor; ``GET /api/v1/search/overview`` counts the same documents by sender, kind, year and
tag for the start of the archive.

``GET /api/v1/documents/{id}/versions/{n}/text`` is the text of every page of a version, with the rights of reading
the document; through a link (``/api/v1/l/{token}/text``) only when the link allows downloading: the text is the
document's content as much as its file is.
"""

from __future__ import annotations

import logging
import math
import secrets
import time
from collections.abc import Callable
from datetime import date as Date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from fastapi import Path as PathParam
from pydantic import BaseModel
from sqlalchemy import select

from ..db import SessionLocal
from ..deps import DbSession, Reader, link_guard
from ..errors import error
from ..models import Version, VersionText
from ..services import brakes, deadlines, ocr, rights, search, searchtext, sharing
from .public import _not_found
from .schemas import DocumentOut, KindOut, document_out, kind_out

logger = logging.getLogger("nexpaper.search")

router = APIRouter(prefix="/api/v1", tags=["search"])

ID = Annotated[int | None, Query(ge=1, le=2**31 - 1)]
DOCUMENT = Annotated[int, PathParam(ge=1, le=2**31 - 1)]
VERSION = Annotated[int, PathParam(ge=1, le=2**31 - 1, description="The number of the version")]

#: An answer to a search is sent at the next multiple of this many seconds after the search began: what is left of
#: the time a search takes (the index still looks up whether a word exists at all on the server, a few hundred
#: microseconds) disappears in the step. Measured in ``docs/search.md``.
TIME_STEP = 0.025
#: And then a random wait of up to this many seconds (from ``secrets``): a search that ends right at the edge of a step
#: cannot be used to tell one step from the next by sending it again and again.
JITTER = 0.025


def _jitter() -> float:
    return secrets.randbelow(int(JITTER * 1_000_000) + 1) / 1_000_000


#: The clock, the wait and the chance of the step, to be replaced in a test.
clock: Callable[[], float] = time.monotonic
sleep: Callable[[float], None] = time.sleep
jitter: Callable[[], float] = _jitter

#: Ranges are counted in UTF-16 code units, as JavaScript, Swift's NSString and Kotlin count a string.
RANGES = "Each range is [start, end) in UTF-16 code units of the text it belongs to."


class Excerpt(BaseModel):
    text: str
    #: Where the search was found in ``text``.
    marks: list[list[int]]
    #: Where the excerpt is from: the document's ``text`` or its ``notes``.
    source: Literal["text", "notes"]


class SearchHit(BaseModel):
    document: DocumentOut
    #: Where the search was found in the title and in the sender's name.
    title_marks: list[list[int]]
    sender_marks: list[list[int]]
    #: A piece of the text around the first place found; empty without words to look for.
    excerpt: Excerpt | None


class AmountOut(BaseModel):
    op: Literal["<", ">", "="]
    cents: int


class Understood(BaseModel):
    """The search as it was read: what counted as words, phrases and filters (folded, as the index compares)."""

    words: list[str]
    phrases: list[str]
    kinds: list[str]
    senders: list[str]
    tags: list[str]
    amounts: list[AmountOut]
    #: ``frist:`` / ``deadline:``: ``open``, ``overdue``, ``done``, or the number of days of ``<n``.
    deadlines: list[str | int] = []


class SearchOut(BaseModel):
    items: list[SearchHit]
    #: How many documents the search finds in all (that the caller may see).
    total: int
    #: Ask again with ``cursor=`` this for the next page; empty when there is no more.
    next: str | None
    understood: Understood


Order = Literal["-date", "date", "-title", "title", "-sender", "sender", "-amount", "amount"]


class NameCount(BaseModel):
    name: str
    count: int


class KindCount(BaseModel):
    kind: KindOut
    count: int


class YearCount(BaseModel):
    year: int
    count: int


class OverviewOut(BaseModel):
    #: How many documents there are with these filters (that the caller may see).
    total: int
    #: Most first. A sender or tag of the same name in two vaults is counted as one.
    senders: list[NameCount]
    #: Most first; ``kind.id`` as the search's ``kind_id`` finds the kinds of the same name too.
    kinds: list[KindCount]
    #: By the document's date, the newest year first; a document without a date is in no year.
    years: list[YearCount]
    tags: list[NameCount]


@router.get("/search/overview", response_model=OverviewOut,
            summary="How the documents the caller may see spread over senders, kinds, years and tags")
def overview(
    account: Reader, db: DbSession,
    vault_id: ID = None,
    status: Literal["processing", "inbox", "filed"] | None = Query(
        default=None, description="Only this status; without it everything but the trash"),
    via_share: bool | None = Query(default=None, description="Only documents seen through a share alone (true), or "
                                   "only those of the caller's vaults (false)"),
    deadline: str | None = Query(default=None, pattern=r"^(open|overdue|done|[0-9]{1,4})$",
                                 description="Only documents with a deadline that is open, overdue, done, or open and "
                                             "due within this many days (overdue ones included)"),
) -> OverviewOut:
    brakes.take("search", account.id)
    found = search.overview(db, account.id, search.Filters(vault_id=vault_id, status=status, via_share=via_share,
                                                           deadline=_deadline(deadline),
                                                           today=deadlines.today_of(account)))
    return OverviewOut(
        total=found.total,
        senders=[NameCount(name=name, count=n) for name, n in found.senders],
        kinds=[KindCount(kind=kind_out(kind), count=n) for kind, n in found.kinds],  # type: ignore[arg-type]
        years=[YearCount(year=year, count=n) for year, n in found.years],
        tags=[NameCount(name=name, count=n) for name, n in found.tags],
    )


@router.get(
    "/search", response_model=SearchOut, summary="Find documents the caller may see",
    description="Words (each must be found, a part of a word is enough), \"a phrase\", art:/kind:, absender:/sender:, "
                "tag:, betrag:/amount: with >, < or = (comma or point), frist:/deadline: open, overdue, done or <n "
                "(days). Newest first, page by page with the cursor; or numbered pages in another order. " + RANGES,
)
def find(
    account: Reader, db: DbSession,
    q: str = Query(default="", max_length=searchtext.MAX_LENGTH, description="The search, as typed"),
    vault_id: ID = None, kind_id: ID = None, owner_id: ID = None,
    sender: str | None = Query(default=None, min_length=1, max_length=160, description="A sender's name, exactly"),
    tag: str | None = Query(default=None, min_length=1, max_length=40, description="A tag's name, exactly"),
    date_from: Date | None = Query(default=None, description="The document's date, from this day"),
    date_to: Date | None = Query(default=None, description="The document's date, up to this day"),
    status: Literal["processing", "inbox", "filed"] | None = Query(
        default=None, description="Only this status; without it everything but the trash"),
    trash: bool = Query(default=False, description="Search the trash instead (only the caller's own documents)"),
    via_share: bool | None = Query(default=None, description="Only documents seen through a share alone (true), or "
                                   "only those of the caller's vaults (false)"),
    cursor: str | None = Query(default=None, max_length=200, description="Only with the newest first and no page"),
    limit: int = Query(default=50, ge=1, le=search.MAX_LIMIT),
    sort: Order = Query(default="-date", description="date, title, sender or amount; a minus for the largest "
                        "(newest, Z) first. Empty senders and amounts come last."),
    page: int | None = Query(default=None, ge=1, le=search.MAX_PAGE, description="The numbered page, from 1"),
    deadline: str | None = Query(default=None, pattern=r"^(open|overdue|done|[0-9]{1,4})$",
                                 description="Only documents with a deadline that is open, overdue, done, or open and "
                                             "due within this many days (overdue ones included)"),
    keep: Literal["expired"] | None = Query(
        default=None, description="`expired`: only filed documents whose keeping time is over, in the vaults where the "
                                  "caller may change things (what `GET /api/v1/keeping` lists)"),
) -> SearchOut:
    brakes.take("search", account.id)
    filters = search.Filters(vault_id=vault_id, kind_id=kind_id, sender=sender, tag=tag, owner_id=owner_id,
                             date_from=date_from, date_to=date_to, status=status, trash=trash,
                             via_share=via_share, deadline=_deadline(deadline), keep=keep,
                             today=deadlines.today_of(account))
    began = clock()
    try:
        result = search.find(db, account.id, q, filters, cursor=cursor, limit=limit, order=sort, page=page)
    finally:
        _wait_for_the_step(began)
    items = []
    for hit in result.hits:
        excerpt = None
        if hit.snippet is not None:
            body, marks, source = hit.snippet
            excerpt = Excerpt(text=body, marks=searchtext.as_utf16(body, marks), source=source)  # type: ignore[arg-type]
        sender_name = hit.row.sender.name if hit.row.sender else ""
        items.append(SearchHit(
            document=document_out(hit.row), title_marks=searchtext.as_utf16(hit.row.document.title, hit.title_marks),
            sender_marks=searchtext.as_utf16(sender_name, hit.sender_marks), excerpt=excerpt,
        ))
    query = result.query
    return SearchOut(items=items, total=result.total, next=result.next, understood=Understood(
        words=query.words, phrases=[" ".join(parts) for parts, _prefix in query.phrases], kinds=query.kinds,
        senders=query.senders, tags=query.tags,
        amounts=[AmountOut(op=a.op, cents=a.cents) for a in query.amounts],  # type: ignore[arg-type]
        deadlines=query.deadlines,
    ))


def _deadline(value: str | None) -> str | int | None:
    if value is None:
        return None
    return int(value) if value.isdigit() else value


def _wait_for_the_step(began: float) -> None:
    """Until the next multiple of ``TIME_STEP`` since ``began``, and a random bit of ``JITTER`` more (an answer that
    failed too)."""
    elapsed = clock() - began
    sleep(max(0.0, TIME_STEP * max(1, math.ceil(elapsed / TIME_STEP)) - elapsed) + jitter())


class TextOut(BaseModel):
    version: int
    #: ``done``: read (``pages`` holds what was found, an empty page had no text); ``pending``: not read yet;
    #: ``none``: there is no text to read (an e-invoice that is XML only).
    state: Literal["done", "pending", "none"]
    #: The text of each page, the first page first.
    pages: list[str]
    #: Pages whose text came from the recognition, and the languages it used.
    ocr_pages: int
    languages: str
    #: From this many pages the text of a document takes a while (the inbox says so while it is ``pending``).
    long_document_pages: int = ocr.LONG_DOCUMENT_PAGES


def _text_of(db: DbSession, version: Version) -> TextOut:
    row = db.get(VersionText, version.id)
    if row is not None:
        return TextOut(version=version.n, state="done", pages=row.text.split("\f") if row.text else [""] * row.pages,
                       ocr_pages=row.ocr_pages, languages=row.languages)
    state: Literal["pending", "none"] = "none" if version.original_path.lower().endswith(".xml") else "pending"
    return TextOut(version=version.n, state=state, pages=[], ocr_pages=0, languages="")


@router.get("/documents/{document_id}/versions/{number}/text", response_model=TextOut,
            summary="The text of every page of a version (what the file carries and what was recognised)")
def version_text(document_id: DOCUMENT, number: VERSION, account: Reader, db: DbSession) -> TextOut:
    rights.require_document(db, account.id, document_id)
    version = db.scalar(select(Version).where(Version.document_id == document_id, Version.n == number))
    if version is None:
        raise error("not_found", "Not found.", 404)
    return _text_of(db, version)


@router.get("/l/{token}/text", response_model=TextOut,
            summary="The text of the document behind a link that allows downloading")
def link_text(token: str, request: Request) -> TextOut:
    link_guard(request)
    with SessionLocal() as db:
        found = sharing.check_link(db, token)
        if found is None:
            raise _not_found(request)
        link, document = found
        if not link.allow_download:
            raise error("download_not_allowed", "This link does not allow downloading.", 403)
        version = db.scalar(select(Version).where(Version.document_id == document.id,
                                                  Version.n == document.current_version))
        if version is None:
            raise error("not_found", "Not found.", 404)
        return _text_of(db, version)
