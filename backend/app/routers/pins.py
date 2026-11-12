"""Pinned documents ("Angeheftet", K1): the caller's own short list of documents to keep at hand.

Pinning needs no more than reading the document, but it is the caller's own list: a signed-in browser or a device, never
a key (a key changes nothing). The list is read by a key of scope ``read`` as well. A document the caller may not see
answers 404, like one that does not exist. Not a change of the document: no change number, no history.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from ..deps import Account as Caller
from ..deps import DbSession, Reader
from ..services import documents, pins
from .schemas import DocumentOut, document_out

router = APIRouter(prefix="/api/v1", tags=["pins"])


class PinsOut(BaseModel):
    #: The pinned documents the caller may see now, the one pinned last first; none in the trash.
    items: list[DocumentOut]
    #: How many the caller may pin at most.
    max: int


class PinOut(BaseModel):
    pinned: bool
    #: How many pinned documents the caller sees now.
    count: int
    max: int


@router.get("/pins", response_model=PinsOut, summary="The caller's pinned documents (only what they may see now)")
def listing(account: Reader, db: DbSession,
            limit: int = Query(default=pins.MAX, ge=1, le=pins.MAX,
                               description="At most this many (the start of the phone shows six)")) -> PinsOut:
    found = pins.listing(db, account.id, limit)
    return PinsOut(items=[document_out(r) for r in documents.rows(db, account.id, found)], max=pins.MAX)


@router.put("/documents/{document_id}/pin", response_model=PinOut,
            summary="Pin a document for oneself (reading it is enough; at most 20)")
def pin(document_id: int, account: Caller, db: DbSession) -> PinOut:
    """Pinning one that is pinned already is no error. A document in the trash answers `409 in_trash`; a 21st answers
    `409 too_many_pins` with `max`."""
    pins.pin(db, account.id, document_id)
    return PinOut(pinned=True, count=pins.count(db, account.id), max=pins.MAX)


@router.delete("/documents/{document_id}/pin", status_code=204, summary="Take one's pin off a document")
def unpin(document_id: int, account: Caller, db: DbSession) -> Response:
    """Taking off a pin that is not there is no error."""
    pins.unpin(db, account.id, document_id)
    return Response(status_code=204)
