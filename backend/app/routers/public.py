"""What somebody without an account reaches: one document, by its link (``/l/<token>`` in the browser).

No sign-in: the token is the key. A person signed in who may see the document anyway (the one who made the link,
looking at how it looks) is not counted as an opening. A token that does not exist, has run out, was revoked, whose
document is in the trash or whose maker may no longer share it answers 404 exactly like a wrong one, and wrong ones
count against the sender on a brake of their own (``deps.link_guard``), apart from the sign-in. The page shows who
shared it, the title, the sender and the date; the file comes with the same token, and only when the link allows
downloading: a link without it shows the document and never hands out its file. The pages of the one document are
reachable as pictures (``/preview`` and ``/pages/<n>``) for as long as the link works, with or without downloading;
nothing else of the server is. Nothing else of the server is reachable this way.

A link may show further documents that go with its own (N2, ``services/sharing.py``): the page lists them, and each
has the same paths under ``/l/<token>/also/<n>/`` (file, preview, pages, and the text in ``routers/search.py``). Every
one of them checks the token and that the document belongs to the link, in one query; a document that does not answers
exactly like a wrong token, and counts on the same brake. "Downloading allowed" holds for all of them; opening the link
counts once, not once per document.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date as Date
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..deps import link_failed, link_guard, signed_in_viewer
from ..errors import error
from ..models import Account, Document, Kind, Link, Sender, Version
from ..services import pages, sharing, storage
from .files import disposition, picture

logger = logging.getLogger("nexpaper.sharing")

router = APIRouter(prefix="/api/v1", tags=["links"])

#: What a browser may show in place; everything else is offered as a download only.
INLINE = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".png": "image/png"}
DOWNLOAD_ONLY = {".heic": "image/heic", ".webp": "image/webp", ".avif": "image/avif",
                 ".xml": "application/octet-stream"}


class PublicAlso(BaseModel):
    """A further document of a link: what the page lists under the document (N2). Never its sender or anything else."""

    #: The number of the document within the link, 1 to 10 in the order chosen (never a number of the server's: not
    #: the document's, not a row's).
    id: int
    title: str
    kind: str | None
    date: Date | None
    pages: int
    has_file: bool
    viewable: bool
    has_pages: bool


class PublicLink(BaseModel):
    #: The name the person who made the link shows to others; empty when they have none (never the sign-in name).
    shared_by: str
    recipient: str
    title: str
    sender: str | None
    kind: str | None
    date: Date | None
    pages: int
    until: datetime
    #: The file may be fetched (``/file``). Without it the link only shows the document.
    allow_download: bool
    #: Whether there is a file yet.
    has_file: bool
    #: The file can be fetched and a browser shows it in place (a PDF or a picture).
    viewable: bool
    #: The pages can be had as pictures (``/api/v1/l/<token>/pages/<n>``, ``/preview``).
    has_pages: bool
    #: Further documents the link shows ("Gehört dazu"), each under ``/api/v1/l/<token>/also/<id>/...``.
    also: list[PublicAlso] = []


def _not_found(request: Request) -> Exception:
    link_failed(request)
    return error("not_found", "Not found.", 404)


def _current(db: Session, document: Document) -> Version | None:
    return db.scalar(select(Version).where(Version.document_id == document.id, Version.n == document.current_version))


def _what_of(db: Session, document: Document, allow_download: bool) -> tuple[bool, bool, bool]:
    """``has_file``, ``viewable`` and ``has_pages`` of a document behind a link."""
    version = _current(db, document)
    if version is None:
        return False, False, False
    inline = Path(version.original_path).suffix.lower() in INLINE
    return True, allow_download and inline, version.pages > 0 and pages.source_pdf(version) is not None


@router.get("/l/{token}", response_model=PublicLink, summary="What a link shows (no sign-in; the token is the key)")
def open_link(token: str, request: Request) -> PublicLink:
    link_guard(request)
    viewer = signed_in_viewer(request)
    with SessionLocal() as db:
        found = sharing.open_link(db, token, viewer)
        if found is None:
            raise _not_found(request)
        link, document = found
        maker = db.get(Account, link.created_by) if link.created_by else None
        sender = db.get(Sender, document.sender_id) if document.sender_id else None
        kind = db.get(Kind, document.kind_id) if document.kind_id else None
        has_file, viewable, has_pages = _what_of(db, document, link.allow_download)
        also = []
        for shown in sharing.shown_also(db, link):
            other = shown.document
            other_kind = db.get(Kind, other.kind_id) if other.kind_id else None
            other_file, other_viewable, other_pages = _what_of(db, other, link.allow_download)
            also.append(PublicAlso(id=shown.item.number, title=other.title,
                                   kind=other_kind.name if other_kind else None, date=other.date, pages=other.pages,
                                   has_file=other_file, viewable=other_viewable, has_pages=other_pages))
        return PublicLink(
            shared_by=maker.display_name if maker else "", recipient=link.recipient, title=document.title,
            sender=sender.name if sender else None, kind=kind.name if kind else None, date=document.date,
            pages=document.pages, until=sharing.ends(link, sharing.rules(db).max_days),
            allow_download=link.allow_download, has_file=has_file, viewable=viewable, has_pages=has_pages, also=also,
        )


def _the(token: str, item: int | None) -> Callable[[Session], tuple[Link, Document] | None]:
    """How a path finds its link and document: the link's own (``item`` None) by the token alone, a further one by the
    token and its number within the link, in one query (``sharing.check_also``)."""
    def find(db: Session) -> tuple[Link, Document] | None:
        if item is None:
            return sharing.check_link(db, token)
        found = sharing.check_also(db, token, item)
        return None if found is None else (found[0], found[2])
    return find


def _file(find: Callable[[Session], tuple[Link, Document] | None], request: Request) -> FileResponse:
    link_guard(request)
    with SessionLocal() as db:
        found = find(db)
        if found is None:
            raise _not_found(request)
        link, document = found
        if not link.allow_download:
            # The original and every other copy: a link without downloading shows the document, it never hands it out.
            raise error("download_not_allowed", "This link does not allow downloading.", 403)
        version = _current(db, document)
        if version is None:
            raise error("not_found", "Not found.", 404)
        try:
            # A protected original (P1) is not what a link hands out: its copy without the password is.
            protected = bool(version.original_protected and version.archive_path)
            path = storage.safe_path(version.archive_path if protected else version.original_path)
        except storage.StorageError:
            logger.warning("A stored path was refused document_id=%s", document.id)
            raise error("not_found", "Not found.", 404) from None
        title = document.title
    extension = Path(path).suffix.lower()
    inline = extension in INLINE
    if not path.is_file():
        raise error("not_found", "Not found.", 404)
    media = INLINE.get(extension) or DOWNLOAD_ONLY.get(extension, "application/octet-stream")
    return FileResponse(path, media_type=media, headers={
        "Content-Disposition": disposition(title, extension, inline),
        "Cache-Control": "private, no-store", "X-Robots-Tag": "noindex",
    })


@router.get("/l/{token}/file", summary="The file of the document behind a link that allows downloading")
def file(token: str, request: Request) -> FileResponse:
    return _file(_the(token, None), request)


def _picture(find: Callable[[Session], tuple[Link, Document] | None], request: Request, page: int | None,
             size: str) -> Response:
    link_guard(request)
    with SessionLocal() as db:
        found = find(db)
        if found is None:
            raise _not_found(request)
        link, document = found
        version = _current(db, document)
        if version is None:
            raise error("not_found", "Not found.", 404)
        return picture(request, document, version, db, page, size, f"l{link.id}")


@router.get("/l/{token}/preview", summary="The first page of the document behind a link, small, as a WebP picture")
def preview(token: str, request: Request) -> Response:
    return _picture(_the(token, None), request, None, "thumb")


@router.get("/l/{token}/pages/{page}", summary="One page of the document behind a link as a WebP picture")
def page(
    token: str, page: Annotated[int, PathParam(ge=1, le=2**31 - 1)], request: Request,
    size: Literal["small", "large"] = "small",
) -> Response:
    return _picture(_the(token, None), request, page, size)


#: The number of a further document within its link.
ITEM = Annotated[int, PathParam(ge=1, le=2**31 - 1)]


@router.get("/l/{token}/also/{item}/file",
            summary="The file of a further document behind a link that allows downloading")
def also_file(token: str, item: ITEM, request: Request) -> FileResponse:
    """A document that does not belong to the link answers like a wrong token."""
    return _file(_the(token, item), request)


@router.get("/l/{token}/also/{item}/preview",
            summary="The first page of a further document behind a link, small, as a WebP picture")
def also_preview(token: str, item: ITEM, request: Request) -> Response:
    return _picture(_the(token, item), request, None, "thumb")


@router.get("/l/{token}/also/{item}/pages/{page}",
            summary="One page of a further document behind a link as a WebP picture")
def also_page(
    token: str, item: ITEM, page: Annotated[int, PathParam(ge=1, le=2**31 - 1)], request: Request,
    size: Literal["small", "large"] = "small",
) -> Response:
    return _picture(_the(token, item), request, page, size)
