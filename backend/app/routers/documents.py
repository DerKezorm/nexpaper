"""Documents: reading, changing fields, moving, the trash, notes, the history.

Reading is open to a signed-in browser, a device and a program with a key. Everything that changes needs a browser or a
device (a key only reads). A document the caller may not see answers 404, like one that does not exist; one they see but
may not change answers 403. A file is made by the upload block, not here.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import select

from ..deps import Account as Caller
from ..deps import BrowserAccount, DbSession, Reader
from ..errors import error
from ..models import Account, Vault
from ..services import changes, documents, processing, rights
from .schemas import DocumentOut, PersonRef, document_out, person

router = APIRouter(prefix="/api/v1", tags=["documents"])

ID = Annotated[int, Query(ge=1, le=2**31 - 1)]


class DateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["due", "contract_end", "warranty_end", "keep_until"]
    date: Date


class DocumentPatch(BaseModel):
    """Only the fields that are sent change. ``sender`` is a name (made if new), empty or null removes it; ``amount``
    is in cents; ``tags`` and ``dates`` replace the whole list."""

    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=documents.TITLE_MAX * 2)
    sender: str | None = Field(default=None, max_length=400)
    kind_id: StrictInt | None = Field(default=None, ge=1, le=2**31 - 1)
    date: Date | None = None
    amount: StrictInt | None = None
    status: Literal["inbox", "filed"] | None = None
    tags: list[str] | None = Field(default=None, max_length=60)
    dates: list[DateIn] | None = Field(default=None, max_length=12)


class MoveIn(BaseModel):
    vault_id: StrictInt = Field(ge=1, le=2**31 - 1)


class NoteIn(BaseModel):
    text: str = Field(max_length=documents.NOTE_MAX * 2)


class NoteOut(BaseModel):
    id: int
    author: PersonRef | None
    text: str
    created_at: datetime
    updated_at: datetime | None
    #: The caller may change or delete it (their own; managers may delete any).
    mine: bool


class EventOut(BaseModel):
    id: int
    at: datetime
    action: str
    #: Who did it; empty for somebody who used a link (then ``by_link`` says for whom the link was made).
    by: PersonRef | None
    by_link: str
    #: Field names and numbers, never contents. A vault the caller cannot see is left out.
    detail: dict[str, Any] | None


class DocumentPage(BaseModel):
    items: list[DocumentOut]
    #: Ask again with ``after=`` this number; empty when there is no more.
    next: int | None


def _one(db: DbSession, account: Account, document_id: int) -> DocumentOut:
    return document_out(documents.one(db, account.id, document_id)[1])


@router.get("/documents", response_model=DocumentPage, summary="Documents the caller may see, by id")
def listing(
    account: Reader, db: DbSession, vault_id: int | None = Query(default=None, ge=1, le=2**31 - 1),
    status: Literal["processing", "inbox", "filed", "trash"] | None = None,
    after: int = Query(default=0, ge=0, le=2**31 - 1), limit: int = Query(default=100, ge=1, le=500),
    via_share: bool | None = Query(default=None, description="Only documents seen through a share alone (true), or "
                                   "only those of the caller's vaults (false)"),
    sender: str | None = Query(default=None, min_length=1, max_length=160, description="A sender's name"),
    tag: str | None = Query(default=None, min_length=1, max_length=40, description="A tag's name"),
) -> DocumentPage:
    found = documents.listing(db, account.id, vault_id=vault_id, status=status, after=after, limit=limit + 1,
                              via_share=via_share, sender=sender, tag=tag)
    more = len(found) > limit
    found = found[:limit]
    return DocumentPage(items=[document_out(r) for r in documents.rows(db, account.id, found)],
                        next=found[-1].id if more and found else None)


@router.get("/documents/{document_id}", response_model=DocumentOut, summary="One document")
def read(document_id: int, account: Reader, db: DbSession) -> DocumentOut:
    return _one(db, account, document_id)


@router.patch("/documents/{document_id}", response_model=DocumentOut, summary="Change fields of a document",
              responses={422: {"description": "A field is wrong. A date that is out of range (1900 to 2200) or no "
                                              "date answers `invalid_date` with `field`: `date`, or `dates[n]` for "
                                              "the n-th term of `dates`."}})
def patch(document_id: int, payload: DocumentPatch, account: Caller, db: DbSession) -> DocumentOut:
    sent = payload.model_dump(exclude_unset=True)
    for required in ("title", "tags", "dates", "status"):
        if required in sent and sent[required] is None:
            raise error("invalid_input", "This field cannot be empty.", 422, fields=[required])
    if "sender" in sent and sent["sender"] is not None:
        sent["sender"] = sent["sender"].strip() or None
    documents.update_fields(db, account.id, document_id, sent)
    return _one(db, account, document_id)


@router.post("/documents/{document_id}/move", response_model=DocumentOut,
             summary="Move a document to another vault (edit in both)")
def move(document_id: int, payload: MoveIn, account: Caller, db: DbSession) -> DocumentOut:
    documents.move(db, account.id, document_id, payload.vault_id)
    return _one(db, account, document_id)


@router.delete("/documents/{document_id}", response_model=DocumentOut,
               summary="Put a document in the trash for 30 days")
def trash(document_id: int, account: Caller, db: DbSession) -> DocumentOut:
    documents.trash(db, account.id, document_id)
    return _one(db, account, document_id)


@router.post("/documents/{document_id}/restore", response_model=DocumentOut, summary="Take a document out of the trash")
def restore(document_id: int, account: Caller, db: DbSession) -> DocumentOut:
    documents.restore(db, account.id, document_id)
    return _one(db, account, document_id)


@router.post("/documents/{document_id}/purge", status_code=204,
             summary="Delete a document in the trash for good (managers of the vault, or its owner with edit; "
                     "browser only)")
def purge(document_id: int, account: BrowserAccount, db: DbSession) -> None:
    """It cannot be undone: only from a signed-in browser, like the operator's routes (a lost phone deletes
    nothing)."""
    documents.purge(db, account.id, document_id)


@router.post("/documents/{document_id}/retry", response_model=DocumentOut,
             summary="Try again to read a document that could not be read")
def retry(document_id: int, account: Caller, db: DbSession) -> DocumentOut:
    processing.retry(db, account.id, document_id)
    return _one(db, account, document_id)


# --- Notes ------------------------------------------------------------------------------------------------------------


def _note(note: Any, author: Account | None, uid: int, manager: bool) -> NoteOut:
    return NoteOut(id=note.id, author=person(author), text=note.text, created_at=note.created_at,
                   updated_at=note.updated_at, mine=note.user_id == uid or manager)


@router.get("/documents/{document_id}/notes", response_model=list[NoteOut],
            summary="The notes on a document (everybody who sees it sees them)")
def notes(document_id: int, account: Reader, db: DbSession) -> list[NoteOut]:
    manager = rights.access_to(db, account.id, document_id)
    manager_right = manager is not None and manager.vault == rights.MANAGE
    return [_note(n, a, account.id, manager_right) for n, a in documents.notes_of(db, account.id, document_id)]


@router.post("/documents/{document_id}/notes", response_model=NoteOut, status_code=201,
             summary="Write a note on a document (anybody who sees it)")
def add_note(document_id: int, payload: NoteIn, account: Caller, db: DbSession) -> NoteOut:
    note = documents.add_note(db, account.id, document_id, payload.text)
    return _note(note, db.get(Account, account.id), account.id, False)


@router.put("/documents/{document_id}/notes/{note_id}", response_model=NoteOut, summary="Change an own note")
def edit_note(document_id: int, note_id: int, payload: NoteIn, account: Caller, db: DbSession) -> NoteOut:
    note = documents.edit_note(db, account.id, document_id, note_id, payload.text)
    return _note(note, db.get(Account, account.id), account.id, False)


@router.delete("/documents/{document_id}/notes/{note_id}", status_code=204,
               summary="Delete an own note, or any note as a manager of the vault")
def delete_note(document_id: int, note_id: int, account: Caller, db: DbSession) -> None:
    documents.delete_note(db, account.id, document_id, note_id)


# --- History ----------------------------------------------------------------------------------------------------------


@router.get("/documents/{document_id}/events", response_model=list[EventOut],
            summary="Who did what to a document and when (for everybody who sees it)")
def events(document_id: int, account: Reader, db: DbSession) -> list[EventOut]:
    rights.require_document(db, account.id, document_id)
    visible = set(db.scalars(select(Vault.id).where(Vault.id.in_(rights.member_vault_ids(account.id)))))
    history = changes.history(db, document_id)
    authors = {e.user_id for e in history if e.user_id}
    people = {a.id: a for a in db.scalars(select(Account).where(Account.id.in_(authors)))}
    out = []
    for event in history:
        detail = dict(event.detail) if isinstance(event.detail, dict) else None
        if detail:
            # A vault the caller is not in stays a number they cannot use (and unnamed).
            for key in ("from", "to"):
                moved = event.action in (changes.MOVED, changes.TAKEN_OVER)
                if moved and key in detail and detail[key] not in visible:
                    detail[key] = None
        out.append(EventOut(id=event.id, at=event.at, action=event.action,
                            by=person(people.get(event.user_id)) if event.user_id else None, by_link=event.by_link,
                            detail=detail))
    return out
