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
from ..models import Account, Document, Vault
from ..services import changes, documents, processing, rights
from .schemas import DocumentOut, PersonRef, document_out, person

router = APIRouter(prefix="/api/v1", tags=["documents"])

ID = Annotated[int, Query(ge=1, le=2**31 - 1)]
#: The kinds of date a document may carry; `follow_up` (a day to look at it again, with a sentence) since K1.
DateKind = Literal["due", "contract_end", "warranty_end", "keep_until", "follow_up"]


class NoticeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: StrictInt = Field(ge=1, le=24)
    unit: Literal["weeks", "months"]


class DateIn(BaseModel):
    """A date of a document. A contract (``contract_end``) may carry its notice period and how many months it renews
    by; left out, they stay as they were, ``null`` takes them away."""

    model_config = ConfigDict(extra="forbid")
    kind: DateKind
    date: Date
    #: Only for `keep_until`: `true` set by hand (it stays when the kind, the date or the vault changes), `false` worked
    #: out from the kind's keeping time (the date sent is not used). Left out: the date it has now stays as it was
    #: made, another one counts as set by hand. A `keep_until` left out of `dates` is worked out from the kind again.
    manual: bool | None = None
    notice: NoticeIn | None = None
    renew_months: StrictInt | None = Field(default=None, ge=1, le=120)
    #: Only for `follow_up`: what to do on that day, one line of at most 200 characters (line breaks become blanks).
    #: Left out it stays as it was; `null` or empty takes it away. Never in a reminder.
    note: str | None = Field(default=None, max_length=400)


class DateSet(BaseModel):
    """One term in ``set_dates``: the kind it is, and only what is to change. A day left out keeps the day the term has
    (a new term needs one); ``notice`` and ``renew_months`` as in ``dates``."""

    model_config = ConfigDict(extra="forbid")
    kind: DateKind
    date: Date | None = None
    notice: NoticeIn | None = None
    renew_months: StrictInt | None = Field(default=None, ge=1, le=120)
    #: Only for `follow_up`, as in `dates`.
    note: str | None = Field(default=None, max_length=400)
    #: Only for `keep_until`, as in `dates`: `true` set by hand, `false` worked out from the kind's keeping time again
    #: (the term is dropped and worked out right away). With no day, `true` keeps the day it has as set by hand.
    manual: bool | None = None


class DocumentPatch(BaseModel):
    """Only the fields that are sent change. ``sender`` is a name (made if new), empty or null removes it; ``amount``
    is in cents; ``tags`` and ``dates`` replace the whole list. ``set_dates`` changes only the terms it names, and only
    what it sends of them; ``remove_dates`` takes terms away by kind (not together with ``dates``). A page that may be
    behind sends those, so it never sends back a day it did not see change (a contract that renewed meanwhile)."""

    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=documents.TITLE_MAX * 2)
    sender: str | None = Field(default=None, max_length=400)
    kind_id: StrictInt | None = Field(default=None, ge=1, le=2**31 - 1)
    date: Date | None = None
    amount: StrictInt | None = None
    status: Literal["inbox", "filed"] | None = None
    tags: list[str] | None = Field(default=None, max_length=60)
    dates: list[DateIn] | None = Field(default=None, max_length=12)
    set_dates: list[DateSet] | None = Field(default=None, max_length=5)
    remove_dates: list[DateKind] | None = Field(
        default=None, max_length=5)


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


#: The lines of the history about a link to the outside (``services/sharing.py``), and what of their detail only who may
#: share the document sees: how long a link lasts, how many further documents it shows, which link it was.
LINK_ACTIONS = ("link_created", "link_opened", "link_revoked", "link_copied", "link_also_shown", "link_also_left",
                "link_also_gone")
LINK_DETAILS = ("days", "until", "also", "link")


class EventOut(BaseModel):
    id: int
    at: datetime
    action: str
    #: Who did it; empty for somebody who used a link (then ``by_link`` says for whom the link was made).
    by: PersonRef | None
    #: For whom the link was made, only for a caller who may share the document (``can_share``); empty for everybody
    #: else, who reads ``via_link`` instead.
    by_link: str
    #: Field names and numbers, never contents. A vault the caller cannot see is left out.
    detail: dict[str, Any] | None
    #: Done by somebody through a link (also when ``by_link`` is left empty for the caller).
    via_link: bool = False


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
                                              "the n-th term of `dates` (`set_dates[n]` for single terms)."}})
def patch(document_id: int, payload: DocumentPatch, account: Caller, db: DbSession) -> DocumentOut:
    sent = payload.model_dump(exclude_unset=True)
    for required in ("title", "tags", "dates", "status", "set_dates", "remove_dates"):
        if required in sent and sent[required] is None:
            raise error("invalid_input", "This field cannot be empty.", 422, fields=[required])
    if "dates" in sent and ("set_dates" in sent or "remove_dates" in sent):
        raise error("invalid_input", "Send the whole list or single terms, not both.", 422,
                    fields=["dates", "set_dates", "remove_dates"])
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
    access = rights.require_document(db, account.id, document_id)
    visible = set(db.scalars(select(Vault.id).where(Vault.id.in_(rights.member_vault_ids(account.id)))))
    history = changes.history(db, document_id)
    authors = {e.user_id for e in history if e.user_id}
    people = {a.id: a for a in db.scalars(select(Account).where(Account.id.in_(authors)))}
    # Goes with (``services/related.py``): the other document is named only for a caller who may see it.
    from ..services import related as related_service
    from ..services import sharing as sharing_service

    # The further documents of a link (N2) name the other document the same way.
    naming = (related_service.SET, related_service.UNSET, sharing_service.ALSO_SHOWN, sharing_service.ALSO_LEFT,
              sharing_service.ALSO_GONE)
    # N2b: whoever may not share the document learns that a link was made, opened or ended, never for whom, for how
    # long, or how many documents it shows (the stored lines stay as they are; only the answer leaves it out).
    outside_only = not access.can_share
    partners = {e.detail.get("document") for e in history if e.action in naming
                and isinstance(e.detail, dict) and isinstance(e.detail.get("document"), int)}
    seen_titles: dict[int, str] = {int(i): t for i, t in db.execute(select(Document.id, Document.title).where(
        Document.id.in_(partners), rights.visible_clause(account.id))).all()} if partners else {}
    out = []
    for event in history:
        detail = dict(event.detail) if isinstance(event.detail, dict) else None
        if detail:
            # A vault the caller is not in stays a number they cannot use (and unnamed).
            for key in ("from", "to"):
                moved = event.action in (changes.MOVED, changes.TAKEN_OVER)
                if moved and key in detail and detail[key] not in visible:
                    detail[key] = None
            if event.action in naming:
                # A document the caller may not see is "another document": neither its number nor its title.
                partner = detail.get("document")
                if partner in seen_titles:
                    detail["title"] = seen_titles[partner]
                else:
                    detail["document"] = None
            if outside_only and event.action in LINK_ACTIONS:
                for key in LINK_DETAILS:
                    detail.pop(key, None)
        out.append(EventOut(id=event.id, at=event.at, action=event.action,
                            by=person(people.get(event.user_id)) if event.user_id else None,
                            by_link="" if outside_only else event.by_link, detail=detail,
                            via_link=bool(event.by_link)))
    return out
