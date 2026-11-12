"""Goes with ("Gehört zu"): the documents that go with a document, setting and removing a pair, the proposals, turning
one down. ``related``, because ``/documents/{id}/links`` are the links to the outside.

Reading is open to a signed-in browser, a device and a program with a key of scope ``read``; everything that changes
needs a browser or a device. Setting, removing and turning down need ``edit`` on both documents. A document the caller
may not see answers 404, like one that does not exist; one they see but may not change answers 403.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Path
from pydantic import BaseModel

from ..deps import Account as Caller
from ..deps import DbSession, Reader
from ..services import related
from .schemas import KindOut, NameRef, kind_out

router = APIRouter(prefix="/api/v1", tags=["related"])

OtherId = Annotated[int, Path(ge=1, le=2**31 - 1)]


class RelatedOut(BaseModel):
    """A document that goes with the one asked about, as far as the caller may see it."""

    id: int
    title: str
    kind: KindOut | None
    sender: NameRef | None
    date: Date | None
    status: Literal["processing", "inbox", "filed", "trash"]
    #: The caller may remove the pair (`edit` on both documents).
    can_unlink: bool
    linked_at: datetime | None
    #: The caller may share it by a link of its own, so it may also be shown with a link of the document asked about.
    can_share: bool = False


class SuggestionOut(BaseModel):
    """A document proposed to go with the one asked about: it carries the same number of the kind `via`."""

    id: int
    title: str
    kind: KindOut | None
    sender: NameRef | None
    date: Date | None
    status: Literal["processing", "inbox", "filed", "trash"]
    #: The kind of number both carry: `invoice`, `order` (also a purchase order or an order confirmation) or
    #: `delivery` (a delivery note).
    via: Literal["invoice", "order", "delivery"]


def related_out(entry: related.Entry) -> RelatedOut:
    document = entry.document
    return RelatedOut(id=document.id, title=document.title, kind=kind_out(entry.kind),
                      sender=NameRef(id=entry.sender.id, name=entry.sender.name) if entry.sender else None,
                      date=document.date, status=document.status,  # type: ignore[arg-type]
                      can_unlink=entry.can_unlink, linked_at=entry.linked_at, can_share=entry.can_share)


def suggestion_out(found: related.Suggestion) -> SuggestionOut:
    document = found.document
    return SuggestionOut(id=document.id, title=document.title, kind=kind_out(found.kind),
                         sender=NameRef(id=found.sender.id, name=found.sender.name) if found.sender else None,
                         date=document.date, status=document.status,  # type: ignore[arg-type]
                         via=found.via)  # type: ignore[arg-type]


@router.get("/documents/{document_id}/related", response_model=list[RelatedOut],
            summary="The documents that go with a document (only those the caller may see)")
def listing(document_id: int, account: Reader, db: DbSession) -> list[RelatedOut]:
    """Nothing in the trash is shown, and a document in the trash shows nothing; what the caller may not see is left
    out without a trace (no number of hidden ones)."""
    return [related_out(e) for e in related.listing(db, account.id, document_id)]


@router.put("/documents/{document_id}/related/{other_id}", response_model=list[RelatedOut],
            summary="Set that two documents go with each other (edit on both)")
def link(document_id: int, other_id: OtherId, account: Caller, db: DbSession) -> list[RelatedOut]:
    """Setting a pair that is there already is no error. Both documents get a line in their history and a new change
    number. Answers what goes with `document_id` now."""
    related.link(db, account.id, document_id, other_id)
    return [related_out(e) for e in related.listing(db, account.id, document_id)]


@router.delete("/documents/{document_id}/related/{other_id}", response_model=list[RelatedOut],
               summary="Remove that two documents go with each other (edit on both)")
def unlink(document_id: int, other_id: OtherId, account: Caller, db: DbSession) -> list[RelatedOut]:
    """Nothing is deleted: the pair can be set again. A pair that is not there is no error."""
    related.unlink(db, account.id, document_id, other_id)
    return [related_out(e) for e in related.listing(db, account.id, document_id)]


@router.get("/documents/{document_id}/related/suggestions", response_model=list[SuggestionOut],
            summary="Documents proposed to go with a document (only for a caller who may change both)")
def suggestions(document_id: int, account: Reader, db: DbSession) -> list[SuggestionOut]:
    """Other documents with the same invoice, order or delivery note number, at most five, the ones that share the
    most numbers first. Empty for a caller who may only read the document; proposals turned down or already set are
    not repeated."""
    return [suggestion_out(s) for s in related.suggestions_for(db, account.id, document_id)]


@router.post("/documents/{document_id}/related/{other_id}/dismiss", response_model=list[SuggestionOut],
             summary="Turn a proposal down: the pair is not proposed again (edit on both)")
def dismiss(document_id: int, other_id: OtherId, account: Caller, db: DbSession) -> list[SuggestionOut]:
    related.dismiss(db, account.id, document_id, other_id)
    return [suggestion_out(s) for s in related.suggestions_for(db, account.id, document_id)]
