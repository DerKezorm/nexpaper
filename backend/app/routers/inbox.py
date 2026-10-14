"""The inbox as a list: what waits to be filed, found and sorted, a page at a time; filing many documents at once; the
numbers the menu shows.

The inbox of a person is what is not filed yet in the vaults where they may change things (see ``services/inbox.py``).
Reading needs a browser, a device or a program with a key; filing changes documents and needs a browser or a device.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from ..deps import Account as Caller
from ..deps import DbSession, Reader
from ..services import deadlines, documents, inbox
from .schemas import DocumentOut, document_out

router = APIRouter(prefix="/api/v1", tags=["inbox"])

ID = Annotated[int, Query(ge=1, le=2**31 - 1)]
Source = Literal["upload", "camera", "mail", "folder", "share", "paperless", "api"]


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
    return InboxPage(items=[document_out(r) for r in documents.rows(db, account.id, page.documents)],
                     total=page.total, counts={str(v): n for v, n in page.counts.items()},
                     shared=page.shared, all=sum(page.counts.values()) + page.shared, reading=page.reading)


class MenuCounts(BaseModel):
    #: Waiting in the inbox (not counting what is being read).
    inbox: int
    #: Being read.
    reading: int
    #: In the trash, in the vaults the caller sees.
    trash: int
    #: Beside "Fristen": open deadlines that are overdue or come in the next 14 days, and how many of them are overdue
    #: (``GET /api/v1/deadlines`` has them).
    deadlines: int = 0
    deadlines_overdue: int = 0


@router.get("/counts", response_model=MenuCounts, summary="The numbers beside Inbox, Deadlines and Trash in the menu")
def counts(account: Reader, db: DbSession) -> MenuCounts:
    found = inbox.menu_counts(db, account.id)
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
