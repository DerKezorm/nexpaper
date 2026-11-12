"""What somebody without an account reaches through an upload request (``/u/<token>`` in the browser): who asks, and a
way to send files. Nothing to read: never what came already, no file, no name of one, nothing of the server.

* ``GET /api/v1/u/<token>``: the display name of the person who asks (empty when they have none, never the sign-in
  name), whom the request is for, until when it works, how many files it still takes and the largest a file may be.
  "How many still" tells only how much of this one address was used (by whoever holds it): nothing of the person's
  documents, and a sender needs it to know what is left.
* ``POST /api/v1/u/<token>/files``: one file (``multipart/form-data``, field ``file``) per request. In this order,
  before a byte of the body is read: the brake of wrong tokens, the declared length (it must be there, and at most one
  file and its envelope; ``middleware.body_limit`` has already turned a larger one away), the token, the tries per
  request and per sender and hour, a place of the request (``upload_requests.hold``: room for the file, two at once,
  the request's bytes of the day, the server's day as read so far). Then the file is read as every upload is (kind from
  the content, size counted while it arrives, ``services/receiving.py``), only as long as it keeps coming (``Paced``),
  and becomes a document in the inbox of the person who asked, in their personal vault
  (``services/upload_requests.take_file``). What it cost is counted after: the bytes read, the file only when taken.
  The answer says "arrived" or the reason in one code; a file that is the same as one the person has answers exactly
  like any other.

An unknown token, one that ran out, was revoked or took all its files, and the operator's switch off answer the same
404, and count on the brake (``deps.request_failed``). No session is read or set here: the routes speak for the token
alone, and the one that changes something is the only path without the tab header (``middleware._stranger_upload``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

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
                             max_mb=min(limits.current(db).max_file, upload_requests.REQUEST_DAY_BYTES) // limits.MB)


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


class BodyTooSlow(Exception):
    """The body of a file stopped coming, or came slower than ``upload_requests.BODY_MIN_RATE``."""


class Paced:
    """The body of the request, piece by piece, as long as it keeps coming: a pause longer than ``BODY_IDLE_SECONDS``
    or the whole of it past its time (``BODY_BASE_SECONDS`` plus the announced length at ``BODY_MIN_RATE``) breaks it
    off. Counts the bytes it handed on (``read``): what a refused or broken-off file cost."""

    def __init__(self, stream: AsyncIterator[bytes], announced: int) -> None:
        self._stream = stream.__aiter__()
        loop = asyncio.get_running_loop()
        self._loop = loop
        self.deadline = loop.time() + upload_requests.BODY_BASE_SECONDS + announced / upload_requests.BODY_MIN_RATE
        self.read = 0

    def __aiter__(self) -> Paced:
        return self

    async def __anext__(self) -> bytes:
        left = self.deadline - self._loop.time()
        if left <= 0:
            raise BodyTooSlow
        try:
            chunk = await asyncio.wait_for(self._stream.__anext__(),
                                           timeout=min(upload_requests.BODY_IDLE_SECONDS, left))
        except TimeoutError:
            raise BodyTooSlow from None
        self.read += len(chunk)
        return chunk


def _before(token: str, request: Request, length: int) -> tuple[upload_requests.Hold, int]:
    """Everything before a byte of the body is read, in one database session (run in the thread pool, not in the event
    loop: a write lock held elsewhere makes it wait, never the other requests)."""
    with SessionLocal() as db:
        found = upload_requests.check(db, token)
        if found is None:
            raise _unknown(request)
        request_id = found[0].id
        max_file = min(limits.current(db).max_file, upload_requests.REQUEST_DAY_BYTES)
        if length > max_file + ENVELOPE:
            raise error("too_large", f"The file is larger than the limit of {max_file // limits.MB} MB.", 413,
                        max_mb=max_file // limits.MB)
        if not upload_requests.hour_room(request_id, client_ip(request)):
            raise _busy("request_busy", "Too many files at once. Wait a while.", 600)
        held = upload_requests.hold(db, request_id, length)
        if held.refused == "gone":
            raise _unknown(request)
        if held.refused == "busy":
            raise _busy("request_busy", "Two files of this request are on their way. Send the next one after them.", 30)
        if held.refused:
            raise _busy("request_day_full", "No more files are taken today. Try again tomorrow.", 3600)
        return held, max_file


def _take(request_id: int, received: Any) -> bool:
    """The file that arrived becomes a document, if the request still takes it (not revoked, the switch on, room left);
    run in the thread pool."""
    with SessionLocal() as db:
        live = upload_requests.still_open(db, request_id)
        if live is None:
            return False
        upload_requests.take_file(db, live, filename=received.filename, path=received.path, kind=received.kind,
                                  sha256=received.sha256, size=received.size)
        return True


def _after(request_id: int, read: int, taken: bool) -> int:
    """What the file cost is counted (read bytes, the file only when taken), the person is told when due; returns how
    many files the request still takes."""
    with SessionLocal() as db:
        upload_requests.charge(db, request_id, read, taken=taken)
        if not taken:
            return 0
        upload_requests.tell_if_due(db, request_id)
        row_now = upload_requests.still_open(db, request_id)
        return max(0, row_now.max_files - row_now.received) if row_now is not None else 0


@router.post("/u/{token}/files", response_model=Arrived, status_code=201, openapi_extra=_BODY,
             summary="Send one file through an upload request (no sign-in; the token is the key)")
async def send(token: str, request: Request) -> Arrived:
    # The route is ``async`` because it reads the body as it arrives; every step with the database runs in the thread
    # pool (``run_in_threadpool``), so that a busy database never stops the event loop for everybody else. (A comment,
    # not a docstring: the description of the interface stays the same.)
    request_guard(request)
    declared = request.headers.get("content-length", "")
    if not declared.isdigit():
        raise error("length_required", "Send the file with its length.", 411)
    length = int(declared)
    held, max_file = await run_in_threadpool(_before, token, request, length)
    body = Paced(request.stream(), length)
    taken = False
    try:
        try:
            form = await receiving.read_form(body, request.headers.get("content-type", ""), max_file, 1)
        except BodyTooSlow:
            raise error("too_slow", "The file came too slowly. Try again on a better connection.", 408) from None
        try:
            if len(form.files) != 1:
                raise error("invalid_input", "Send one file in the field \"file\".", 422)
            received = form.files[0]
            if received.problem is not None or received.path is None:
                status, code, message = received.problem or (500, "failed", "The file was not stored.")
                extra = {"max_mb": max_file // limits.MB} if code == "too_large" else {}
                raise error(code, message, status, **extra)
            try:
                taken = await run_in_threadpool(_take, held.request_id, received)
            finally:
                if received.path is not None:
                    received.path.unlink(missing_ok=True)
                    received.path = None
            if not taken:
                # Revoked, all files there, or the switch went off while the file arrived: nothing is kept.
                raise _unknown(request)
        finally:
            form.cleanup()
    finally:
        upload_requests.release(held)
        remaining = await run_in_threadpool(_after, held.request_id, body.read, taken)
    return Arrived(status="arrived", remaining=remaining)
