"""The inbox as a list: what waits to be filed, found and sorted, a page at a time; filing many documents at once;
sorting again after a rule changed (first a look, then the change); the numbers the menu shows.

The inbox of a person is what is not filed yet in the vaults where they may change things (see ``services/inbox.py``).
Reading needs a browser, a device or a program with a key; filing changes documents and needs a browser or a device.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy.orm import Session

from ..deps import Account as Caller
from ..deps import DbSession, Reader
from ..models import Document
from ..services import deadlines, documents, inbox, related, sort_again
from .related import SuggestionOut, suggestion_out
from .schemas import DocumentOut, document_out

router = APIRouter(prefix="/api/v1", tags=["inbox"])

ID = Annotated[int, Query(ge=1, le=2**31 - 1)]
Source = Literal["upload", "camera", "mail", "folder", "share", "paperless", "api", "request"]


class InboxPage(BaseModel):
    items: list[DocumentOut]
    #: How many documents the filters (the vault included) find.
    total: int
    #: How many each vault would show under the same filters apart from the vault: vault id (as text) to number.
    #: Only vaults the caller is a member of with `edit` or `manage`.
    counts: dict[str, int]
    #: How many are in no such vault but reachable through a share of the document alone (no vault number).
    shared: int
    #: The sum of `counts` and `shared`.
    all: int
    #: How many of the `total` are still being read.
    reading: int
    #: Per document of `items` (its id as text) the documents proposed to go with it, at most three; only documents
    #: with a proposal are named (`GET /documents/{id}/related/suggestions` has up to five).
    related: dict[str, list[SuggestionOut]] = {}


@router.get("/inbox", response_model=InboxPage,
            summary="What waits in the inbox, in the vaults where the caller may change things")
def listing(
    account: Reader, db: DbSession, vault_id: int | None = Query(default=None, ge=1, le=2**31 - 1),
    q: str = Query(default="", max_length=200, description="Part of the title or of the sender's name"),
    sender: str | None = Query(default=None, min_length=1, max_length=160, description="A sender's name"),
    kind_id: int | None = Query(default=None, ge=1, le=2**31 - 1), source: Source | None = None,
    owner_id: int | None = Query(default=None, ge=1, le=2**31 - 1, description="Who brought it in"),
    shared: bool = Query(default=False, description="Only what the caller reaches through a share of the document "
                                                     "alone, in no vault of theirs"),
    sort: Literal["new", "old", "date"] = Query(default="new", description="`new`/`old`: by arrival; `date`: by the "
                                                "date on the document"),
    limit: int = Query(default=50, ge=1, le=inbox.MAX_PAGE), offset: int = Query(default=0, ge=0, le=10**7),
) -> InboxPage:
    """Documents being read come first. A vault in which the caller may only read has no inbox for them: nothing of it
    is listed or counted, and a `vault_id` they do not reach answers like an empty one."""
    page = inbox.listing(db, account.id, inbox.Filters(q=q, sender=sender, kind_id=kind_id, source=source,
                                                      owner_id=owner_id, vault_id=vault_id, shared=shared),
                         sort=sort, limit=limit, offset=offset)
    proposals = related.suggestions(db, account.id, [d.id for d in page.documents], related.INBOX_SUGGESTIONS)
    return InboxPage(items=[document_out(r) for r in documents.rows(db, account.id, page.documents)],
                     total=page.total, counts={str(v): n for v, n in page.counts.items()},
                     shared=page.shared, all=sum(page.counts.values()) + page.shared, reading=page.reading,
                     related={str(k): [suggestion_out(s) for s in found] for k, found in proposals.items()})


class MenuCounts(BaseModel):
    #: Waiting in the inbox (not counting what is being read).
    inbox: int
    #: Being read.
    reading: int
    #: In the trash, in the vaults the caller sees.
    trash: int
    #: Beside "Fristen": open deadlines that are overdue or come in the next 14 days, and how many of them are overdue
    #: (``GET /api/v1/deadlines`` has them). 0 for someone who switched deadlines off (`profile.deadlines`).
    deadlines: int = 0
    deadlines_overdue: int = 0


@router.get("/counts", response_model=MenuCounts, summary="The numbers beside Inbox, Deadlines and Trash in the menu")
def counts(account: Reader, db: DbSession) -> MenuCounts:
    found = inbox.menu_counts(db, account.id)
    if not deadlines.wanted(account):
        # Someone who switched deadlines off (My account › Notifications) has no number beside a menu item they do not
        # have.
        return MenuCounts(inbox=found.inbox, reading=found.reading, trash=found.trash)
    soon = deadlines.menu_count(db, account.id, deadlines.today_of(account))
    return MenuCounts(inbox=found.inbox, reading=found.reading, trash=found.trash, deadlines=soon.soon,
                      deadlines_overdue=soon.overdue)


class FileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[StrictInt] = Field(min_length=1, max_length=inbox.MAX_BULK)
    #: Move them all to this vault first (`edit` in both); left out, they stay where they are.
    vault_id: StrictInt | None = Field(default=None, ge=1, le=2**31 - 1)
    #: Give them all this kind (one of the server's, or of the vault they end up in).
    kind_id: StrictInt | None = Field(default=None, ge=1, le=2**31 - 1)
    #: Tags to add to what they carry.
    add_tags: list[str] = Field(default_factory=list, max_length=10)


class Refused(BaseModel):
    id: int
    #: Why: the code a single change would have given (`not_found`, `forbidden`, `still_processing` ...).
    code: str


class FileOut(BaseModel):
    filed: list[int]
    failed: list[Refused]


@router.post("/inbox/file", response_model=FileOut,
             summary="File many documents at once, with a vault, a kind and tags for all of them")
def file_documents(payload: FileIn, account: Caller, db: DbSession) -> FileOut:
    """Every document is checked on its own, as a single change would be (the right in its vault, the state it is in,
    the kind it may have). The proposals stay as they are: filing takes them over. A document that fails is named with
    the reason and the others go on; a kind or a tag the target does not accept is found before anything is changed, so
    the document stays untouched in its old vault."""
    done = inbox.file_many(db, account.id, payload.ids, vault_id=payload.vault_id, kind_id=payload.kind_id,
                           add_tags=payload.add_tags)
    return FileOut(filed=done.filed, failed=[Refused(id=i, code=c) for i, c in done.failed])


class SortAgainIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The documents to look at; left out, every document in the caller's inbox.
    ids: list[StrictInt] | None = Field(default=None, min_length=1, max_length=sort_again.MAX)
    #: Go on after this document: the `next` of the answer before.
    after: StrictInt = Field(default=0, ge=0, le=2**31 - 1)


class SortAgainItem(BaseModel):
    #: The fields that would change: `title`, `sender`, `kind`, `date`, `amount`, `dates`, `tags`, `vault`,
    #: `reference`.
    fields: list[str]
    #: Per changed field where the new value comes from: `rule`, `last_time`, `text`, `ai`, `einvoice`.
    origins: dict[str, str]
    before: DocumentOut
    #: The document afterwards; `null` when a rule would move it where the caller does not reach.
    after: DocumentOut | None


class SortAgainPreview(BaseModel):
    #: Only the documents whose proposals would change.
    items: list[SortAgainItem]
    #: How many documents this answer looked at (at most 100).
    looked_at: int
    #: How many documents there are to look at in all (the inbox, or of the ids named).
    total: int
    #: Ask again with `after` set to this to look at the next ones; `null` when all were looked at.
    next: int | None


def _shown(account_id: int) -> Callable[[Session, Document], DocumentOut]:
    def shown(db: Session, document: Document) -> DocumentOut:
        return document_out(documents.rows(db, account_id, [document])[0])

    return shown


@router.post("/inbox/sort-again/preview", response_model=SortAgainPreview,
             summary="What working the proposals out again would change, without changing anything")
def sort_again_preview(payload: SortAgainIn, account: Caller, db: DbSession) -> SortAgainPreview:
    """At most 100 documents in one answer, in the order of their numbers; `next` says where to go on. Every document
    is worked out exactly as `POST /inbox/sort-again` would, in a transaction that is rolled back:
    the rules of the vault it arrived in, as last time, the text, and what the AI answered when it arrived (no new
    reading, no new question). A field a person set stays as it is. Only documents waiting in the inbox the caller may
    change; one being read, filed or in the trash is left out."""
    found = sort_again.preview(db, account.id, payload.ids, _shown(account.id), after=payload.after)
    return SortAgainPreview(items=[SortAgainItem(fields=i.fields, origins=i.origins, before=i.before, after=i.after)
                                   for i in found.items], looked_at=found.looked_at, total=found.total,
                            next=found.next)


class SortAgainApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The documents to sort again (the ones the person ticked in the look).
    ids: list[StrictInt] = Field(min_length=1, max_length=sort_again.MAX)


class SortAgainOut(BaseModel):
    #: The documents whose proposals changed.
    changed: list[int]
    #: How many of them a rule moved to another vault.
    moved: int
    #: Worked out again, nothing new.
    unchanged: int
    #: No longer waiting in the inbox, or no longer the caller's to change.
    skipped: int
    failed: int


@router.post("/inbox/sort-again", response_model=SortAgainOut,
             summary="Work the proposals of documents in the inbox out again, after a rule was made or changed")
def sort_again_apply(payload: SortAgainApplyIn, account: Caller, db: DbSession) -> SortAgainOut:
    """Worked out anew when asked, not taken from the look: what changed since is part of it. Each document on its
    own; the documents stay in the inbox until a person files them. A rule may move a document to another vault, as
    when it arrived."""
    done = sort_again.apply(db, account.id, payload.ids)
    return SortAgainOut(changed=done.changed, moved=done.moved, unchanged=done.unchanged, skipped=done.skipped,
                        failed=done.failed)
