"""The archive's table beyond the search (A1): many documents changed at once, and the person's saved searches.

``POST /api/v1/documents/bulk`` changes up to 500 documents in one call (a tag added or taken away, a kind, another
vault, the trash), each through the function a single change uses, with its right, its history and its number. It needs
a browser or a device (a key only reads). The answer counts what changed and why the rest did not
(``services/bulk.py``); a document the caller may not see is ``forbidden`` like one they may only read.

``/api/v1/saved-searches`` lists, makes, renames, moves and deletes the caller's saved searches; the list carries the
number of hits of each (``services/saved.py``), counted by the search with its brake and its step in time. Reading
is open to a browser, a device and a program with a read key; changing needs a browser or a device.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Path
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from ..deps import Account as Caller
from ..deps import DbSession, Reader
from ..models import Account, SavedSearch
from ..services import brakes, bulk, saved
from . import search as search_router

router = APIRouter(prefix="/api/v1", tags=["archive"])

SAVED_ID = Annotated[int, Path(ge=1, le=2**31 - 1)]


# --- Many documents at once -------------------------------------------------------------------------------------------


class BulkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[StrictInt] = Field(min_length=1, max_length=bulk.MAX_BULK)
    #: `link` sets every pair among 2 to 10 documents to go with each other (`/documents/{id}/related`).
    action: Literal["add_tag", "remove_tag", "kind", "move", "trash", "link"]
    #: For `add_tag` and `remove_tag`: the tag's name (tags are the vault's own; the name finds them in every vault).
    tag: str | None = Field(default=None, max_length=200)
    #: For `kind`: one of the server's kinds (for every document), or a vault's (only for the documents of that vault).
    kind_id: StrictInt | None = Field(default=None, ge=1, le=2**31 - 1)
    #: For `move`: the vault (`edit` there); sender, kind and tags go along by their names, as in a single move.
    vault_id: StrictInt | None = Field(default=None, ge=1, le=2**31 - 1)


class Skipped(BaseModel):
    id: int
    #: `forbidden` (no right to change it, or no such document: the two are not told apart), `in_trash`,
    #: `kind_elsewhere` (the kind is another vault's), `unchanged` (it was so already), or the code a single change
    #: gave.
    reason: str


class BulkOut(BaseModel):
    changed: list[int]
    skipped: list[Skipped]
    #: How many were skipped for each reason.
    reasons: dict[str, int]


@router.post("/documents/bulk", response_model=BulkOut,
             summary="Change many documents at once: a tag added or taken away, a kind, another vault, the trash, or "
                     "set them to go with each other")
def change_many(payload: BulkIn, account: Caller, db: DbSession) -> BulkOut:
    """Every document is checked and changed on its own, as a single change would be, with a line in its history and a
    new change number. Duplicates count once."""
    done = bulk.change(db, account.id, payload.ids, payload.action, tag=payload.tag, kind_id=payload.kind_id,
                       vault_id=payload.vault_id)
    reasons: dict[str, int] = {}
    for _id, reason in done.skipped:
        reasons[reason] = reasons.get(reason, 0) + 1
    return BulkOut(changed=done.changed, skipped=[Skipped(id=i, reason=r) for i, r in done.skipped], reasons=reasons)


# --- Saved searches ---------------------------------------------------------------------------------------------------


class SavedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=saved.NAME_MAX * 4)
    #: The archive's address (`q=strom&kind=3&sort=-amount`); parts the archive does not know are dropped.
    query: str = Field(max_length=4000)


class SavedRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=saved.NAME_MAX * 4)


class SavedOut(BaseModel):
    id: int
    name: str
    #: The known parts of the archive's address, sorted (what the archive opens with `/?` before it).
    query: str
    position: int
    #: How many documents it finds now; empty when `state` is not `ok`.
    count: int | None
    #: `ok`; `no_access` (the vault of its filter is not one the caller sees, whether it still exists or not);
    #: `failed` (the search could not answer, e.g. it took too long).
    state: Literal["ok", "no_access", "failed"]
    #: It has the filter "Frist", which the caller switched off: counted, like the archive shows it, without it.
    deadlines_off: bool


def _out(row: SavedSearch, counted: saved.Counted | None) -> SavedOut:
    return SavedOut(id=row.id, name=row.name, query=row.query, position=row.position,
                    count=counted.count if counted else None, state=counted.state if counted else "ok",  # type: ignore[arg-type]
                    deadlines_off=counted.deadlines_off if counted else False)


def _listed(db: DbSession, account: Account) -> list[SavedOut]:
    rows = saved.entries(db, account.id)
    if not rows:
        return []
    if saved.needs_search(db, account, rows):
        # Counting is searching: the search's brake, and its step in time for the answer.
        brakes.take("search", account.id)
        began = search_router.clock()
        try:
            found = saved.counts(db, account, rows)
        finally:
            search_router._wait_for_the_step(began)
    else:
        found = saved.counts(db, account, rows)
    return [_out(row, found.get(row.id)) for row in rows]


@router.get("/saved-searches", response_model=list[SavedOut],
            summary="The caller's saved searches, in their order, each with its number of hits")
def list_saved(account: Reader, db: DbSession) -> list[SavedOut]:
    return _listed(db, account)


@router.post("/saved-searches", response_model=SavedOut, status_code=201,
             summary="Keep a search of the archive under a name (at most 30)")
def create_saved(payload: SavedIn, account: Caller, db: DbSession) -> SavedOut:
    row = saved.create(db, account.id, payload.name, payload.query)
    return _out(row, None)


@router.patch("/saved-searches/{saved_id}", response_model=SavedOut, summary="Rename a saved search")
def rename_saved(saved_id: SAVED_ID, payload: SavedRename, account: Caller, db: DbSession) -> SavedOut:
    row = saved.rename(db, account.id, saved_id, payload.name)
    return _out(row, None)


@router.post("/saved-searches/{saved_id}/up", response_model=list[SavedOut],
             summary="Move a saved search one place up; answers the whole list")
def up_saved(saved_id: SAVED_ID, account: Caller, db: DbSession) -> list[SavedOut]:
    saved.move(db, account.id, saved_id, -1)
    return _listed(db, account)


@router.post("/saved-searches/{saved_id}/down", response_model=list[SavedOut],
             summary="Move a saved search one place down; answers the whole list")
def down_saved(saved_id: SAVED_ID, account: Caller, db: DbSession) -> list[SavedOut]:
    saved.move(db, account.id, saved_id, 1)
    return _listed(db, account)


@router.delete("/saved-searches/{saved_id}", status_code=204,
               summary="Delete a saved search (the documents stay as they are)")
def delete_saved(saved_id: SAVED_ID, account: Caller, db: DbSession) -> None:
    saved.delete(db, account.id, saved_id)
