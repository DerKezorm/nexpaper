"""What somebody without an account reaches: one document, by its link (``/l/<token>`` in the browser).

No sign-in: the token is the key. A person signed in who may see the document anyway (the one who made the link,
looking at how it looks) is not counted as an opening. A token that does not exist, has run out, was revoked, whose
document is in the trash or whose maker may no longer share it answers 404 exactly like a wrong one, and wrong ones
count against the sender on a brake of their own (``deps.link_guard``), apart from the sign-in. The page shows who
shared it, the title, the sender and the date; the file comes with the same token, and only when the link allows
downloading: a link without it shows the document and never hands out its file. The pages of the one document are
reachable as pictures (``/preview`` and ``/pages/<n>``) for as long as the link works, with or without downloading;
nothing else of the server is. Nothing else of the server is reachable this way.
"""

from __future__ import annotations

import logging
from datetime import date as Date
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import select

from ..db import SessionLocal
from ..deps import link_failed, link_guard, signed_in_viewer
from ..errors import error
from ..models import Account, Kind, Sender, Version
from ..services import pages, sharing, storage
from .files import disposition, picture

logger = logging.getLogger("nexpaper.sharing")

router = APIRouter(prefix="/api/v1", tags=["links"])

#: What a browser may show in place; everything else is offered as a download only.
INLINE = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".png": "image/png"}
DOWNLOAD_ONLY = {".heic": "image/heic", ".webp": "image/webp", ".avif": "image/avif",
                 ".xml": "application/octet-stream"}


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


def _not_found(request: Request) -> Exception:
    link_failed(request)
    return error("not_found", "Not found.", 404)


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
        version = db.scalar(select(Version).where(Version.document_id == document.id,
                                                  Version.n == document.current_version))
        has_file = version is not None
        inline = has_file and Path(version.original_path).suffix.lower() in INLINE  # type: ignore[union-attr]
        return PublicLink(
            shared_by=maker.display_name if maker else "", recipient=link.recipient, title=document.title,
            sender=sender.name if sender else None, kind=kind.name if kind else None, date=document.date,
            pages=document.pages, until=sharing.ends(link, sharing.rules(db).max_days),
            allow_download=link.allow_download, has_file=has_file, viewable=link.allow_download and inline,
            has_pages=has_file and version.pages > 0 and pages.source_pdf(version) is not None,  # type: ignore[union-attr]
        )


@router.get("/l/{token}/file", summary="The file of the document behind a link that allows downloading")
def file(token: str, request: Request) -> FileResponse:
    link_guard(request)
    with SessionLocal() as db:
        found = sharing.check_link(db, token)
        if found is None:
            raise _not_found(request)
        link, document = found
        if not link.allow_download:
            # The original and every other copy: a link without downloading shows the document, it never hands it out.
            raise error("download_not_allowed", "This link does not allow downloading.", 403)
        version = db.scalar(select(Version).where(Version.document_id == document.id,
                                                  Version.n == document.current_version))
        if version is None:
            raise error("not_found", "Not found.", 404)
        try:
            path = storage.safe_path(version.original_path)
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


def _picture(token: str, request: Request, page: int | None, size: str) -> Response:
    link_guard(request)
    with SessionLocal() as db:
        found = sharing.check_link(db, token)
        if found is None:
            raise _not_found(request)
        link, document = found
        version = db.scalar(select(Version).where(Version.document_id == document.id,
                                                  Version.n == document.current_version))
        if version is None:
            raise error("not_found", "Not found.", 404)
        return picture(request, document, version, db, page, size, f"l{link.id}")


@router.get("/l/{token}/preview", summary="The first page of the document behind a link, small, as a WebP picture")
def preview(token: str, request: Request) -> Response:
    return _picture(token, request, None, "thumb")


@router.get("/l/{token}/pages/{page}", summary="One page of the document behind a link as a WebP picture")
def page(
    token: str, page: Annotated[int, PathParam(ge=1, le=2**31 - 1)], request: Request,
    size: Literal["small", "large"] = "small",
) -> Response:
    return _picture(token, request, page, size)
