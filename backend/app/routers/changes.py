"""The feed of changes: what happened to the documents a caller may see since a number they already have.

For a program that keeps its own copy (a native app working offline). Ask with ``since=0`` the first time, then with
the ``next`` of the last answer until ``more`` is false. Nothing is missed: a number appears in the feed only after
every smaller one, whatever else writes at the same time, and a page is read in one read transaction. A document that
is no longer visible comes as a small ``gone`` marker without contents; a vault whose rights changed as ``vault_lost``
(drop its documents; the ones still visible otherwise follow with a newer number) or ``vault_refresh`` (fetch them
anew). ``since=0`` brings no markers. Markers are kept 90 days: an older number answers ``410 sync_from_start``.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..deps import DbSession, Reader
from ..services import changes, documents
from .schemas import DocumentOut, document_out

router = APIRouter(prefix="/api/v1", tags=["changes"])


class ChangeOut(BaseModel):
    seq: int
    type: Literal["document", "gone", "vault_lost", "vault_refresh"]
    document: DocumentOut | None = None
    document_id: int | None = None
    vault_id: int | None = None


class ChangesOut(BaseModel):
    items: list[ChangeOut]
    #: Ask for this number next.
    next: int
    more: bool


@router.get("/changes", response_model=ChangesOut, summary="Changes to the caller's documents after a number",
            responses={410: {"description": "The number is older than the changes kept: sync again from 0"}})
def feed(account: Reader, db: DbSession, since: int = Query(default=0, ge=0, le=2**62),
         limit: int = Query(default=100, ge=1, le=500)) -> ChangesOut:
    with changes.snapshot(db):
        page = changes.feed(db, account.id, since, limit)
        by_id = {r.document.id: r
                 for r in documents.rows(db, account.id, [i.document for i in page.items if i.document])}
        items = []
        for item in page.items:
            if item.document is not None:
                items.append(ChangeOut(seq=item.seq, type="document", document=document_out(by_id[item.document.id])))
            else:
                items.append(ChangeOut(seq=item.seq, type=item.type,  # type: ignore[arg-type]
                                       document_id=item.document_id, vault_id=item.vault_id))
        return ChangesOut(items=items, next=page.next, more=page.more)
