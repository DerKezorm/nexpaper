"""Bringing files in: the browser's upload and the upload in pieces with resumption.

Both end in the same place: a document in ``processing`` that the worker reads (``services/processing.py``) and that
then waits in the inbox. A signed-in browser, a device and a program with an API key of scope ``upload`` may upload; a
key that only reads may not. The vault is named by ``vault_id`` (one the caller may add to), else it is the one they
chose for their uploads, else their own."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from ..db import SessionLocal
from ..deps import DbSession, Uploader, bearer_token
from ..errors import error
from ..models import Document
from ..services import apikeys, filetypes, limits, receiving, uploads
from .schemas import DocumentOut, DuplicateOut, document_out

router = APIRouter(prefix="/api/v1", tags=["uploads"])

UPLOAD_ID = Annotated[str, Path(max_length=64, description="The id that starting the upload returned")]
VAULT = Annotated[int | None, Query(ge=1, le=2**31 - 1,
                                    description="The vault the files go to; one the caller may add to")]


#: Where a file comes from, when the caller says so: the camera of the app, or the share menu of the phone.
SOURCE = Annotated[Literal["camera", "share"] | None, Query(
    description="camera: photographed in the app; share: sent from another app. Left out: upload or api")]


def _source(request: Request, said: str | None = None) -> str:
    """What the caller said (camera, share); else ``api`` for a device or a program and ``upload`` for a browser."""
    if said is not None:
        return said
    return "api" if bearer_token(request) is not None else "upload"


def _key_of(request: Request) -> int | None:
    """The API key that asks (``deps._key_account``), or None for a browser or a device."""
    return getattr(request.state, "api_key_id", None)


def _keys_own(db: DbSession, request: Request, upload_id: str) -> None:
    """A key reaches only the uploads it started; any other answers like none (404)."""
    key_id = _key_of(request)
    if key_id is None:
        return
    from ..models import Upload

    row = db.get(Upload, upload_id) if len(upload_id) == 32 else None
    if row is None or row.api_key_id != key_id:
        raise error("not_found", "Not found.", 404)


def _plain(out: DocumentOut) -> DocumentOut:
    """What a key for uploading hears of its document: no hint at another document of the account (a key reads
    nothing)."""
    return out.model_copy(update={"duplicate": None})


def _hour_full() -> Exception:
    exc = error("upload_limit", f"This key has brought in {apikeys.UPLOADS_PER_HOUR} files this hour. Wait a while.",
                429, per_hour=apikeys.UPLOADS_PER_HOUR)
    exc.headers = {"Retry-After": "600"}  # type: ignore[attr-defined]
    return exc


# --- One request, several files ---------------------------------------------------------------------------------


class FileResult(BaseModel):
    filename: str
    status: str
    #: The document, when the file was taken (it stands as ``processing`` until the worker has read it).
    document: DocumentOut | None = None
    #: Why a file was not taken: ``code`` and ``message``; ``status`` is the one the whole request would carry alone.
    error: dict[str, Any] | None = None
    http_status: int | None = None
    #: A document the caller already has with this very file.
    duplicate: DuplicateOut | None = None


class UploadResults(BaseModel):
    items: list[FileResult]


_BODY = {
    "requestBody": {
        "required": True,
        "content": {"multipart/form-data": {"schema": {
            "type": "object", "required": ["file"],
            "properties": {"file": {
                "type": "array", "items": {"type": "string", "format": "binary"},
                "description": "One or more files: PDF, JPEG, PNG, TIFF, HEIC, WebP, AVIF, or an e-invoice as XML"}},
        }}},
    },
}


@router.post("/documents", response_model=UploadResults, status_code=201, openapi_extra=_BODY,
             summary="Upload one or more files (multipart/form-data, field 'file'); each becomes a document")
async def upload(request: Request, account: Uploader, db: DbSession, vault_id: VAULT = None,
                 source: SOURCE = None) -> UploadResults:
    """The files are written to the disk while they arrive. Each file has its own result. When none was taken, the
    answer is the error of the first (415 for a kind of file that is not taken, 413 for one that is too large) with all
    results in ``items``. The vault is checked before the first byte is read. An API key brings in at most
    ``UPLOADS_PER_HOUR`` files an hour; a file past that has the result ``upload_limit`` (429)."""
    key_id = _key_of(request)
    if key_id is not None and apikeys.upload_room(key_id) == 0:
        raise _hour_full()
    target = receiving.resolve_vault(db, account.id, vault_id)
    current = limits.current(db)
    db.rollback()
    form = await receiving.read_form(request.stream(), request.headers.get("content-type", ""), current.max_file,
                                     limits.FILES_PER_REQUEST)
    results: list[FileResult] = []
    try:
        if not form.files:
            raise error("invalid_input", "Send at least one file in the field \"file\".", 422)
        source = _source(request, source)
        for received in form.files:
            if received.problem is not None or received.path is None:
                status, code, message = received.problem or (500, "failed", "The file was not stored.")
                info: dict[str, Any] = {"code": code, "message": message}
                if code == "too_large":
                    info["max_mb"] = current.max_file // limits.MB
                results.append(FileResult(filename=received.filename, status="rejected", http_status=status,
                                          error=info))
                continue
            if key_id is not None and not apikeys.take_upload(key_id):
                results.append(FileResult(filename=received.filename, status="rejected", http_status=429, error={
                    "code": "upload_limit", "message": "This key has brought in all the files it may this hour.",
                    "per_hour": apikeys.UPLOADS_PER_HOUR}))
                continue
            path, received.path = received.path, None
            try:
                with SessionLocal() as own:
                    document, twin = receiving.accept(
                        own, uid=account.id, vault_id=target, filename=received.filename, path=path, kind=received.kind,
                        sha256=received.sha256, size=received.size, source=source)
                    results.append(_accepted(own, account.id, received.filename, document, twin, key_id is not None))
            except Exception:
                path.unlink(missing_ok=True)
                raise
    finally:
        form.cleanup()
    if not any(result.status == "accepted" for result in results):
        first = results[0]
        assert first.error is not None
        extra = {key: value for key, value in first.error.items() if key not in ("code", "message")}
        raise error(first.error["code"], first.error["message"], first.http_status or 400,
                    items=[r.model_dump(mode="json") for r in results], **extra)
    return UploadResults(items=results)


def _accepted(db: Any, uid: int, filename: str, document: Document, twin: Document | None, key: bool = False
              ) -> FileResult:
    from ..services import documents

    row = documents.rows(db, uid, [document])[0]
    if key:
        return FileResult(filename=filename, status="accepted", document=_plain(document_out(row)), duplicate=None)
    duplicate = DuplicateOut(document_id=twin.id, title=twin.title, kind="same") if twin is not None else None
    return FileResult(filename=filename, status="accepted", document=document_out(row), duplicate=duplicate)


# --- In pieces --------------------------------------------------------------------------------------------------


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=255, description="The name the file has; a proposal for the title")
    size: StrictInt = Field(ge=1, le=2**53, description="The size in bytes")
    sha256: str = Field(min_length=64, max_length=64, description="The SHA-256 of the file, 64 hexadecimal digits")
    vault_id: StrictInt | None = Field(default=None, ge=1, le=2**31 - 1)
    #: camera: photographed in the app; share: sent from another app. Left out: upload or api.
    source: Literal["camera", "share"] | None = None
    #: The file becomes a new version of this document (the right to change it is needed), not a document of its own.
    #: ``vault_id`` is then left out.
    document_id: StrictInt | None = Field(default=None, ge=1, le=2**31 - 1)


class UploadOut(BaseModel):
    id: str
    state: str
    filename: str
    vault_id: int
    size: int
    #: How many bytes the server has, in order from the start: the next piece starts here.
    received: int
    #: The size of a piece the server proposes; a piece may be any size up to ``max_piece``.
    chunk_size: int
    max_piece: int
    expires_at: datetime
    #: The document, once the upload is finished.
    document_id: int | None
    #: The document this upload becomes a new version of.
    target_document_id: int | None = None


class ExistingOut(BaseModel):
    id: int
    title: str
    status: str


class StartOut(BaseModel):
    #: True: the caller already has a document with this very file. ``document`` says which (empty for an API key, which
    #: reads nothing), ``upload`` is empty, and nothing is to be sent.
    exists: bool
    upload: UploadOut | None
    document: ExistingOut | None


class FinishOut(BaseModel):
    document: DocumentOut
    #: A document the caller already has with this very file.
    duplicate: DuplicateOut | None
    #: False: this was a repeated request for an upload that was finished already; the document is the same.
    created: bool


def _out(upload: Any) -> UploadOut:
    return UploadOut(id=upload.id, state=upload.state, filename=upload.filename, vault_id=upload.vault_id,
                     size=upload.size, received=upload.received,
                     chunk_size=limits.PIECE, max_piece=limits.MAX_PIECE, expires_at=upload.expires_at,
                     document_id=upload.document_id, target_document_id=upload.target_document_id)


@router.post("/uploads", response_model=StartOut, status_code=201,
             summary="Announce a file to upload in pieces (size and SHA-256 first; a file the caller has is not sent)")
def start(payload: StartIn, request: Request, account: Uploader, db: DbSession) -> Any:
    key_id = _key_of(request)
    found = uploads.start(db, account.id, vault_id=payload.vault_id, filename=payload.filename, size=payload.size,
                          sha256=payload.sha256, source=_source(request, payload.source), key_id=key_id,
                          document_id=payload.document_id)
    # A key counts each new file once, when it begins; going on with an open upload and a file the server has cost
    # nothing. Counting is one step (of many starts at once only the room passes); a start past it is dropped again.
    if key_id is not None and found.existing is None and not found.resumed and not apikeys.take_upload(key_id):
        assert found.upload is not None
        uploads.abort(db, account.id, found.upload.id)
        raise _hour_full()
    if found.existing is not None:
        existing = None if key_id is not None else ExistingOut(
            id=found.existing.id, title=found.existing.title, status=found.existing.status)
        body = StartOut(exists=True, upload=None, document=existing)
        return JSONResponse(status_code=200, content=body.model_dump(mode="json"))
    assert found.upload is not None
    body = StartOut(exists=False, upload=_out(found.upload), document=None)
    if found.resumed:
        # An upload of this file that was open already: it goes on where it stands (200, not 201).
        return JSONResponse(status_code=200, content=body.model_dump(mode="json"))
    return body


@router.get("/uploads", response_model=list[UploadOut],
            summary="The own uploads that wait for more pieces, newest first")
def open_uploads(request: Request, account: Uploader, db: DbSession) -> list[UploadOut]:
    key_id = _key_of(request)
    return [_out(row) for row in uploads.open_ones(db, account.id) if key_id is None or row.api_key_id == key_id]


@router.get("/uploads/{upload_id}", response_model=UploadOut,
            summary="How far an upload has come (to go on after a break)")
def state(upload_id: UPLOAD_ID, request: Request, account: Uploader, db: DbSession) -> UploadOut:
    _keys_own(db, request, upload_id)
    return _out(uploads.status(db, account.id, upload_id))


@router.put("/uploads/{upload_id}", response_model=UploadOut,
            summary="Send the next piece (raw bytes) at the offset where the last one ended",
            openapi_extra={"requestBody": {"required": True, "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}})
async def piece(
    upload_id: UPLOAD_ID, request: Request, account: Uploader, db: DbSession,
    offset: Annotated[int, Query(ge=0, le=2**53, description="Where this piece starts; must be the bytes received")],
) -> UploadOut:
    """A piece at any other offset answers 409 ``offset_mismatch`` with ``received``: the offset to go on from."""
    _keys_own(db, request, upload_id)
    return _out(await uploads.append(db, account.id, upload_id, offset, request.stream()))


@router.post("/uploads/{upload_id}/finish", response_model=FinishOut,
             summary="Check the file against its SHA-256 and make the document (twice makes one)")
def finish(upload_id: UPLOAD_ID, request: Request, account: Uploader, db: DbSession) -> FinishOut:
    from ..services import documents

    _keys_own(db, request, upload_id)
    document, twin, created = uploads.finish(db, account.id, upload_id)
    row = documents.rows(db, account.id, [document])[0]
    if _key_of(request) is not None:
        return FinishOut(document=_plain(document_out(row)), duplicate=None, created=created)
    duplicate = DuplicateOut(document_id=twin.id, title=twin.title, kind="same") if twin is not None else None
    return FinishOut(document=document_out(row), duplicate=duplicate, created=created)


@router.delete("/uploads/{upload_id}", status_code=204, summary="Cancel an upload and drop what arrived")
def cancel(upload_id: UPLOAD_ID, request: Request, account: Uploader, db: DbSession) -> None:
    _keys_own(db, request, upload_id)
    uploads.abort(db, account.id, upload_id)


_ = filetypes
