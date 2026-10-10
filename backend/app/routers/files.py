"""The files and pictures of a document: the original, the readable copy, the preview and the pages.

Every route is under the document and the number of its version, so that a new version has addresses of its own and a
browser never shows an old picture for a new version. The rights are those of reading the document (a member of its
vault or somebody it was shared with; a program with an API key may read too); a document the caller may not see
answers 404. The pictures are private to the caller and carry an ETag: a browser asks again each time (so a lost right
takes effect at once) and is told "unchanged" without the picture being sent."""

from __future__ import annotations

import hashlib
import hmac
import logging
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import select

from ..config import get_settings
from ..deps import DbSession, Reader
from ..errors import error
from ..models import Account, Document, Version, VersionInfo
from ..services import filetypes, pages, rights, storage
from .schemas import PersonRef, person

logger = logging.getLogger("nexpaper.files")

router = APIRouter(prefix="/api/v1/documents", tags=["files"])

DOCUMENT = Annotated[int, PathParam(ge=1, le=2**31 - 1)]
VERSION = Annotated[int, PathParam(ge=1, le=2**31 - 1, description="The number of the version")]
PAGE = Annotated[int, PathParam(ge=1, le=2**31 - 1, description="The page, counted from 1")]


class VersionOut(BaseModel):
    n: int
    #: The version the document stands at now.
    current: bool
    pages: int
    size: int
    sha256: str
    created_at: datetime
    created_by: PersonRef | None
    note: str
    #: The kind of the original: pdf, jpeg, png, tiff, heic, webp, avif or xml.
    kind: str
    #: There is a PDF made from the original (a picture) or a searchable copy: ``/archive`` serves it.
    has_archive: bool
    #: Pictures of the pages can be had (not for an e-invoice that is XML only).
    has_pages: bool
    #: How it came about (the page tools): ``pages`` (turned, deleted, ordered), ``merged``, ``split``, ``restored``
    #: (from ``from_n``), ``uploaded``; empty for the file the document came with.
    origin: str = ""
    #: The version it was made from.
    from_n: int | None = None
    #: ``ready``; ``processing`` while an uploaded version is read; ``failed`` (``error`` says why) when it could
    #: not be.
    state: Literal["ready", "processing", "failed"] = "ready"
    error: str = ""
    #: Where the original lies in the storage, from its folder for documents on: vault, year, sender, file
    #: (``Haushalt/2026/Stadtwerke Lindenau/2026-10-01 Rechnung.pdf``). Nothing above it, never the data folder.
    path: str


def conditional(request: Request, etag: str) -> Response | None:
    """304 when the browser already has this version of the answer."""
    sent = request.headers.get("if-none-match", "")
    if sent and (sent == "*" or etag in [part.strip() for part in sent.split(",")]):
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "private, no-cache"})
    return None


_UNSAFE_IN_NAME = {ord('"'): None, 92: None, ord("/"): None, ord(":"): None, ord("*"): None, ord("?"): None,
                   ord("<"): None, ord(">"): None, ord("|"): None}


def disposition(title: str, extension: str, inline: bool) -> str:
    """``Content-Disposition`` with a name made of the title that cannot break the header: ``filename`` in plain ASCII
    for old programs and ``filename*=UTF-8''...`` (RFC 5987) with the title as it is, umlauts, ``EUR`` sign and all."""
    clean = "".join(" " if unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") else c for c in title)
    clean = " ".join(clean.translate(_UNSAFE_IN_NAME).split())[:80].strip(" .") or "document"
    ascii_name = "".join(c if c.isascii() and (c.isalnum() or c in " ._-") else "_" for c in clean)
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_name}{extension}\"; filename*=UTF-8''{quote(clean + extension, safe='')}"


def etag_of(*parts: object) -> str:
    """The tag of an answer, made with the server's secret from what identifies it: a tag that stood in a link without
    downloading must not tell the checksum of the file."""
    key = get_settings().resolved_secret_key().encode("utf-8")
    return '"' + hmac.new(key, "|".join(str(p) for p in parts).encode("utf-8"), hashlib.sha256).hexdigest()[:32] + '"'


def kind_of(version: Version) -> str:
    return filetypes.KIND_OF_EXTENSION.get(Path(version.original_path).suffix.lower(), "pdf")


def _version(db: DbSession, uid: int, document_id: int, number: int) -> tuple[rights.Access, Version]:
    access = rights.require_document(db, uid, document_id)
    version = db.scalar(select(Version).where(Version.document_id == document_id, Version.n == number))
    if version is None:
        raise error("not_found", "Not found.", 404)
    return access, version


def _version_row(v: Version, current: int, author: Account | None, info: VersionInfo | None,
                 vault: bool = True) -> VersionOut:
    return VersionOut(
        n=v.n, current=v.n == current, pages=v.pages, size=v.size, sha256=v.sha256,
        created_at=v.created_at, created_by=person(author), note=v.note,
        kind=kind_of(v), has_archive=bool(v.archive_path), has_pages=pages.source_pdf(v) is not None,
        origin=info.origin if info is not None else "", from_n=info.from_n if info is not None else None,
        state=info.state if info is not None else "ready",  # type: ignore[arg-type]
        error=info.error if info is not None else "",
        path=shown_path(v.original_path, vault=vault),
    )


def version_out(db: DbSession, version: Version) -> VersionOut:
    """One version as the list shows it."""
    document = db.get(Document, version.document_id)
    author = db.get(Account, version.created_by) if version.created_by else None
    # Only the person who uploaded it reads this answer, and they may change the document: through its vault or a share.
    vault = bool(document) and rights.vault_right(db, version.created_by or 0, document.vault_id) is not None
    return _version_row(version, document.current_version if document else 0, author, db.get(VersionInfo, version.id),
                        vault)


@router.get("/{document_id}/versions", response_model=list[VersionOut],
            summary="The versions of a document, newest first")
def versions(document_id: DOCUMENT, account: Reader, db: DbSession) -> list[VersionOut]:
    access = rights.require_document(db, account.id, document_id)
    found = list(db.scalars(select(Version).where(Version.document_id == document_id).order_by(Version.n.desc())))
    maker_ids = {v.created_by for v in found if v.created_by}
    authors = {a.id: a for a in db.scalars(select(Account).where(Account.id.in_(maker_ids)))}
    info = {row.version_id: row for row in db.scalars(select(VersionInfo).where(
        VersionInfo.version_id.in_([v.id for v in found])))}
    rows = [_version_row(v, access.document.current_version, authors.get(v.created_by) if v.created_by else None,
                         info.get(v.id), access.vault is not None) for v in found]
    from ..services import pagetools

    stuck = pagetools.stalled(db, [v.id for v in found if v.id in info])
    if stuck:
        # Being read, but its job is gone: it will not be read any more.
        numbers = {v.n for v in found if v.id in stuck}
        rows = [r.model_copy(update={"state": "failed", "error": "failed"}) if r.n in numbers else r for r in rows]
    return rows


def shown_path(stored: str, vault: bool = True) -> str:
    """A stored path as the person may read it: relative, inside the storage, with forward slashes; empty for anything
    else (an absolute path, a step upwards), which the storage never holds. Without ``vault`` (the caller sees the
    document through a share, not as a member) the name of the vault is left out: they see it nowhere else."""
    parts = stored.replace("\\", "/").split("/")
    if not stored or stored.startswith(("/", "\\")) or ":" in parts[0] or any(p in ("", ".", "..") for p in parts):
        return ""
    return "/".join(parts if vault else parts[1:])


def _send(path: Path, media: str, request: Request, etag: str, title: str, extension: str, inline: bool) -> Response:
    cached = conditional(request, etag)
    if cached is not None:
        return cached
    if not path.is_file():
        raise error("not_found", "Not found.", 404)
    return FileResponse(path, media_type=media, headers={
        "Content-Disposition": disposition(title, extension, inline), "ETag": etag,
        "Cache-Control": "private, no-cache"})


@router.get("/{document_id}/versions/{number}/file", summary="The file as it came (the original, never changed)")
def original(document_id: DOCUMENT, number: VERSION, request: Request, account: Reader, db: DbSession) -> Response:
    access, version = _version(db, account.id, document_id, number)
    try:
        path = storage.safe_path(version.original_path)
    except storage.StorageError:
        logger.warning("A stored path was refused document_id=%s", document_id)
        raise error("not_found", "Not found.", 404) from None
    kind = kind_of(version)
    return _send(path, filetypes.MEDIA_TYPE[kind], request, etag_of("file", document_id, version.n, version.sha256),
                 access.document.title,
                 filetypes.EXTENSION[kind], kind in filetypes.INLINE)


@router.get("/{document_id}/versions/{number}/archive",
            summary="The PDF made from a picture, or the searchable copy (404 while there is none)")
def archive(document_id: DOCUMENT, number: VERSION, request: Request, account: Reader, db: DbSession) -> Response:
    access, version = _version(db, account.id, document_id, number)
    if not version.archive_path:
        raise error("not_found", "Not found.", 404)
    try:
        path = storage.safe_path(version.archive_path)
    except storage.StorageError:
        raise error("not_found", "Not found.", 404) from None
    return _send(path, "application/pdf", request, etag_of("archive", document_id, version.n, version.sha256),
                 access.document.title, ".pdf", True)


def picture(request: Request, document: Document, version: Version, db: DbSession, page: int | None, size: str,
            principal: str) -> Response:
    """A picture of a page (or the preview) as a WebP, drawn if the cache does not have it yet."""
    etag = etag_of("picture", document.id, version.n, version.sha256, "t" if page is None else f"p{page}", size)
    cached = conditional(request, etag)
    if cached is not None:
        return cached
    path = pages.ensure(db, document, version, page, size, principal)
    return FileResponse(path, media_type="image/webp", headers={"ETag": etag, "Cache-Control": "private, no-cache"})


@router.get("/{document_id}/versions/{number}/preview", summary="The first page, small, as a WebP picture")
def preview(document_id: DOCUMENT, number: VERSION, request: Request, account: Reader, db: DbSession) -> Response:
    access, version = _version(db, account.id, document_id, number)
    return picture(request, access.document, version, db, None, "thumb", f"u{account.id}")


@router.get("/{document_id}/versions/{number}/pages/{page}", summary="One page as a WebP picture")
def page(
    document_id: DOCUMENT, number: VERSION, page: PAGE, request: Request, account: Reader, db: DbSession,
    size: Literal["small", "large"] = "small",
) -> Response:
    access, version = _version(db, account.id, document_id, number)
    return picture(request, access.document, version, db, page, size, f"u{account.id}")
