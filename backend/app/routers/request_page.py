"""What somebody without an account reaches through an upload request (``/u/<token>`` in the browser): who asks, and a
way to send files. Nothing to read: never what came already, no file, no name of one, nothing of the server.

* ``GET /api/v1/u/<token>``: the display name of the person who asks (empty when they have none, never the sign-in
  name), whom the request is for, until when it works, how many files it still takes and the largest a file may be.
  "How many still" tells only how much of this one address was used (by whoever holds it): nothing of the person's
  documents, and a sender needs it to know what is left.
* ``POST /api/v1/u/<token>/files``: one file (``multipart/form-data``, field ``file``) per request. In this order,
  before a byte of the body is read: the brake of wrong tokens, the declared length (it must be there, and at most one
  file and its envelope; ``middleware.body_limit`` has already turned a larger one away), the token, the tries per
  request and per sender and hour, the day of the whole server, a slot of the request (atomic). Then the file is read
  as every upload is (kind from the content, size counted while it arrives, ``services/receiving.py``) and becomes a
  document in the inbox of the person who asked, in their personal vault (``services/upload_requests.take_file``).
  The answer says "arrived" or the reason in one code; a file that is the same as one the person has answers exactly
  like any other.

An unknown token, one that ran out, was revoked or took all its files, and the operator's switch off answer the same
404, and count on the brake (``deps.request_failed``). No session is read or set here: the routes speak for the token
alone, and the one that changes something is the only path without the tab header (``middleware._stranger_upload``).
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..db import SessionLocal
from ..deps import client_ip, request_failed, request_guard
from ..errors import error
from ..services import limits, receiving, upload_requests

logger = logging.getLogger("nexpaper.requests")

router = APIRouter(prefix="/api/v1", tags=["upload requests"])

#: Room for the envelope of the form around the one file.
ENVELOPE = limits.MB


class PublicRequest(BaseModel):
    #: The name the person who asks shows to others; empty when they have none.
    requested_by: str
    #: Whom the request is meant for (as the person wrote it).
    name: str
    until: datetime
    #: Files the request still takes.
    remaining: int
    #: The largest file, in MB.
    max_mb: int


class Arrived(BaseModel):
    #: Always ``arrived``: the file is in the person's inbox.
    status: str
    remaining: int


def _unknown(request: Request) -> Exception:
    request_failed(request)
    return error("not_found", "Not found.", 404)


@router.get("/u/{token}", response_model=PublicRequest,
            summary="What an upload request shows (no sign-in; the token is the key)")
def show(token: str, request: Request) -> PublicRequest:
    request_guard(request)
    with SessionLocal() as db:
        found = upload_requests.check(db, token)
        if found is None:
            raise _unknown(request)
        row, person = found
        current = upload_requests.rules(db)
        return PublicRequest(requested_by=person.display_name or "", name=row.name,
                             until=upload_requests.ends(row, current.max_days),
                             remaining=max(0, row.max_files - row.received),
                             max_mb=limits.current(db).max_file // limits.MB)


_BODY = {
    "requestBody": {
        "required": True,
        "content": {"multipart/form-data": {"schema": {
            "type": "object", "required": ["file"],
            "properties": {"file": {"type": "string", "format": "binary",
                                    "description": "One file: PDF, JPEG, PNG, TIFF, HEIC, WebP, AVIF, or an e-invoice "
                                                   "as XML"}},
        }}},
    },
}


def _busy(code: str, text: str, wait: int) -> Exception:
    exc = error(code, text, 429)
    exc.headers = {"Retry-After": str(wait)}  # type: ignore[attr-defined]
    return exc


@router.post("/u/{token}/files", response_model=Arrived, status_code=201, openapi_extra=_BODY,
             summary="Send one file through an upload request (no sign-in; the token is the key)")
async def send(token: str, request: Request) -> Arrived:
    request_guard(request)
    declared = request.headers.get("content-length", "")
    if not declared.isdigit():
        raise error("length_required", "Send the file with its length.", 411)
    length = int(declared)
    with SessionLocal() as db:
        found = upload_requests.check(db, token)
        if found is None:
            raise _unknown(request)
        request_id = found[0].id
        max_file = limits.current(db).max_file
        if length > max_file + ENVELOPE:
            raise error("too_large", f"The file is larger than the limit of {max_file // limits.MB} MB.", 413,
                        max_mb=max_file // limits.MB)
        if not upload_requests.hour_room(request_id, client_ip(request)):
            raise _busy("request_busy", "Too many files at once. Wait a while.", 600)
        if not upload_requests.day_reserve(db, length):
            raise _busy("request_day_full", "The server takes no more files today. Try again tomorrow.", 3600)
        if not upload_requests.hold(db, request_id):
            upload_requests.day_settle(db, length, 0, taken=False)
            raise _unknown(request)
    taken = False
    used = 0
    try:
        form = await receiving.read_form(request.stream(), request.headers.get("content-type", ""), max_file, 1)
        try:
            if len(form.files) != 1:
                raise error("invalid_input", "Send one file in the field \"file\".", 422)
            received = form.files[0]
            used = received.size
            if received.problem is not None or received.path is None:
                status, code, message = received.problem or (500, "failed", "The file was not stored.")
                extra = {"max_mb": max_file // limits.MB} if code == "too_large" else {}
                raise error(code, message, status, **extra)
            path, received.path = received.path, None
            try:
                with SessionLocal() as db:
                    live = upload_requests.still_open(db, request_id)
                    if live is None:
                        # Revoked, or the switch went off, while the file arrived: nothing is kept.
                        raise _unknown(request)
                    upload_requests.take_file(db, live, filename=received.filename, path=path, kind=received.kind,
                                              sha256=received.sha256, size=received.size)
                    taken = True
            finally:
                if not taken:
                    path.unlink(missing_ok=True)
        finally:
            form.cleanup()
    finally:
        with SessionLocal() as db:
            if not taken:
                upload_requests.give_back(db, request_id)
            upload_requests.day_settle(db, length, used, taken=taken)
    with SessionLocal() as db:
        upload_requests.tell_if_due(db, request_id)
        current = upload_requests.rules(db)
        row_now = upload_requests.still_open(db, request_id)
        remaining = max(0, row_now.max_files - row_now.received) if row_now is not None and current.allowed else 0
    return Arrived(status="arrived", remaining=remaining)
