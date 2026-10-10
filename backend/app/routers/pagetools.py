"""The page tools: turning, deleting and ordering pages, joining documents, splitting one, the blank separator pages of
a batch scan, restoring a version and uploading a new one (``services/pagetools.py``).

Everything here changes a document: a signed-in browser or a device, never a program with an API key. A document the
caller may not see answers 404, one they see but may not change 403. Each change names the version it was made for
(``base_version``): when the document moved on in the meantime the answer is ``409 version_changed`` with the
``current_version``. The work on the PDF takes a moment (a worker process); while the server is doing as much of it as
it allows, the answer is ``503 busy`` with ``Retry-After``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Request
from fastapi import Path as PathParam
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from ..db import SessionLocal
from ..deps import Account as Caller
from ..deps import DbSession, Reader
from ..errors import error
from ..services import brakes, documents, limits, pagetools, receiving
from .files import VersionOut, version_out
from .schemas import DocumentOut, document_out

router = APIRouter(prefix="/api/v1/documents", tags=["page tools"])

DOCUMENT = Annotated[int, PathParam(ge=1, le=2**31 - 1)]
VERSION = Annotated[int, PathParam(ge=1, le=2**31 - 1, description="The number of the version")]
ID = Annotated[StrictInt, Field(ge=1, le=2**31 - 1)]
#: The most pages a request may name (the operator's limit of pages is checked as well).
MAX_SPECS = 20_000


class PageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The page in the current version, counted from 1.
    page: ID
    #: Degrees clockwise added to how the page stands.
    turn: Literal[0, 90, 180, 270] = 0


class PagesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The version the change was made for (the document's ``current_version``).
    base_version: ID
    #: The pages that stay, in their new order; a page left out is deleted (in the new version only).
    pages: list[PageIn] = Field(min_length=1, max_length=MAX_SPECS)


class MergeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: ID
    base_version: ID


class MergeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The version the document was seen at.
    base_version: ID
    #: The documents whose pages come after its own, in this order. They go to the trash; their notes and tags are
    #: added to the document, which keeps its fields.
    others: list[MergeItem] = Field(min_length=1, max_length=pagetools.MAX_MERGE - 1)


class PartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pages: list[PageIn] = Field(min_length=1, max_length=MAX_SPECS)
    #: The title of the new document; left out: the title of the document with the number of the part.
    title: str | None = Field(default=None, max_length=documents.TITLE_MAX * 2)


class SplitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_version: ID
    #: Each part becomes a document in the inbox. Pages named in no part (the blank separators) are left out.
    parts: list[PartIn] = Field(min_length=2, max_length=pagetools.MAX_PARTS)


class SplitOut(BaseModel):
    #: The new documents, in the order of the parts.
    items: list[DocumentOut]


class RestoreIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_version: ID


class SeparatorsOut(BaseModel):
    #: The version this is about (the current one).
    version: int
    #: The blank pages were looked for (the operator's switch was on when the document was read).
    checked: bool
    #: The blank pages, counted from 1.
    blank_pages: list[int]
    #: The documents a split at the blank pages would make (the pages of each); empty when that is fewer than two.
    parts: list[list[int]]
    #: Every second page is blank: a stack scanned on both sides (only a blank front cuts).
    duplex: bool
    #: Somebody chose "keep it as one document".
    dismissed: bool
    #: A split is proposed (in the inbox, two parts or more, not dismissed).
    suggested: bool


def _out(db: DbSession, uid: int, document_id: int) -> DocumentOut:
    return document_out(documents.one(db, uid, document_id)[1])


@router.post("/{document_id}/pages", response_model=DocumentOut,
             summary="Turn, delete and order the pages: a new version (the file as it came stays)")
def edit_pages(document_id: DOCUMENT, payload: PagesIn, account: Caller, db: DbSession) -> DocumentOut:
    brakes.take("pagetools", account.id)
    pagetools.edit_pages(db, account.id, document_id, payload.base_version,
                         [(item.page, item.turn) for item in payload.pages])
    return _out(db, account.id, document_id)


@router.post("/{document_id}/merge", response_model=DocumentOut,
             summary="Join other documents into this one (their pages after its own); they go to the trash")
def merge(document_id: DOCUMENT, payload: MergeIn, account: Caller, db: DbSession) -> DocumentOut:
    brakes.take("pagetools", account.id)
    items = [(document_id, payload.base_version), *((item.id, item.base_version) for item in payload.others)]
    pagetools.merge(db, account.id, items)
    return _out(db, account.id, document_id)


@router.post("/{document_id}/split", response_model=SplitOut, status_code=201,
             summary="Split a document into new ones in the inbox; it goes to the trash")
def split(document_id: DOCUMENT, payload: SplitIn, account: Caller, db: DbSession) -> SplitOut:
    brakes.take("pagetools", account.id)
    made = pagetools.split(db, account.id, document_id, payload.base_version,
                           [[(item.page, item.turn) for item in part.pages] for part in payload.parts],
                           [part.title for part in payload.parts])
    rows = documents.rows(db, account.id, made)
    return SplitOut(items=[document_out(row) for row in rows])


@router.get("/{document_id}/separators", response_model=SeparatorsOut,
            summary="The blank separator pages of the current version, and the split they propose")
def separators(document_id: DOCUMENT, account: Reader, db: DbSession) -> SeparatorsOut:
    found = pagetools.separators_of(db, account.id, document_id)
    return SeparatorsOut(**found.__dict__)


@router.delete("/{document_id}/separators", status_code=204,
               summary="Keep it as one document: no proposal to split this version again")
def keep_as_one(document_id: DOCUMENT, account: Caller, db: DbSession) -> None:
    pagetools.keep_as_one(db, account.id, document_id)


@router.post("/{document_id}/versions/{number}/restore", response_model=DocumentOut,
             summary="Make an older version the current one again (as a new version; nothing is deleted)")
def restore(document_id: DOCUMENT, number: VERSION, payload: RestoreIn, account: Caller, db: DbSession) -> DocumentOut:
    brakes.take("pagetools", account.id)
    pagetools.restore(db, account.id, document_id, number, payload.base_version)
    return _out(db, account.id, document_id)


@router.delete("/{document_id}/versions/{number}", status_code=204,
               summary="Put away an uploaded version that could not be read (a version that was read stays)")
def discard(document_id: DOCUMENT, number: VERSION, account: Caller, db: DbSession) -> None:
    brakes.take("pagetools", account.id)
    pagetools.discard(db, account.id, document_id, number)


_BODY = {
    "requestBody": {
        "required": True,
        "content": {"multipart/form-data": {"schema": {
            "type": "object", "required": ["file"],
            "properties": {"file": {"type": "string", "format": "binary",
                                    "description": "One file: PDF, JPEG, PNG, TIFF, HEIC, WebP, AVIF or XML"},
                           "note": {"type": "string", "maxLength": pagetools.NOTE_MAX,
                                    "description": "What is new about it, for the list of versions (optional)"}},
        }}},
    },
}


@router.post("/{document_id}/versions", response_model=VersionOut, status_code=202, openapi_extra=_BODY,
             summary="Upload a new version of a document (multipart/form-data, field 'file'); it is read, then current")
async def upload_version(document_id: DOCUMENT, request: Request, account: Caller, db: DbSession) -> VersionOut:
    """The right is checked before the first byte is read. ``note``: what is new about it, shown in the list. The
    version is listed as ``processing`` until the worker has read it, then it is the current one. A file the document
    has as its current version answers ``409 same_file``; a file larger than the server takes ``413``, one of a kind it
    does not take ``415``. A larger file goes in pieces: ``POST /uploads`` with ``document_id``."""
    brakes.take("pagetools", account.id)
    pagetools.ready_for_version(db, account.id, document_id)
    current = limits.current(db)
    db.rollback()
    form = await receiving.read_form(request.stream(), request.headers.get("content-type", ""), current.max_file, 1)
    try:
        if not form.files:
            raise error("invalid_input", "Send one file in the field \"file\".", 422)
        received = form.files[0]
        if received.problem is not None or received.path is None:
            status, code, message = received.problem or (500, "failed", "The file was not stored.")
            raise error(code, message, status)
        note = pagetools.clean_note(form.fields.get("note"))
        path, received.path = received.path, None
        with SessionLocal() as own:
            version = pagetools.accept_version(own, account.id, document_id, path=path, kind=received.kind,
                                               sha256=received.sha256, size=received.size, note=note)
            return version_out(own, version)
    finally:
        form.cleanup()
