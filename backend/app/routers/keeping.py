"""Keeping documents: the keeping time of a kind, the documents whose time is over, and many documents into the trash.

The keeping time of a kind of the whole server is the operator's (in a browser), the one of a vault's kind belongs to
whoever manages the vault, and so does the switch that puts the expired documents of the kind in the trash once a day
by themselves. The question before setting it counts only documents the caller may see. "May go" lists the filed
documents whose time is over in the vaults where the caller may change things; nothing is ever deleted for good by
itself.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from ..deps import Account as Caller
from ..deps import DbSession, Reader, require_browser_account, require_operator
from ..errors import error
from ..models import Account as AccountRow
from ..models import Kind
from ..services import documents, keeping
from .schemas import DocumentOut, KindOut, document_out, kind_out

router = APIRouter(prefix="/api/v1", tags=["keeping"])

ID = Annotated[int, Query(ge=1, le=2**31 - 1)]
#: Most documents put in the trash in one request.
MAX_TRASH = 500


def _who(request: Request, account: AccountRow, db: DbSession, kind_id: int) -> AccountRow:
    """The caller, who must be the operator in a browser when the kind is one of the whole server's."""
    row = db.get(Kind, kind_id)
    if row is not None and row.vault_id is None:
        return require_operator(request, require_browser_account(request))
    return account


class KeepPreview(BaseModel):
    #: The documents of the kind the caller may see (not in the trash, not being read): "Für alle N".
    documents: int
    #: Of those, the ones with a `keep_until` set by hand: they keep it.
    by_hand: int
    #: Of those, the ones whose time would be over at once (they would be listed under "may go").
    expired: int


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The years that would be set; null: the time taken away (`expired` is 0 then).
    years: StrictInt | None = Field(ge=1, le=keeping.YEARS_MAX)


@router.post("/kinds/{kind_id}/keeping/preview", response_model=KeepPreview,
             summary="What setting a keeping time for the documents of a kind already there would do; changes nothing "
                     "(manage in its vault; the operator for the server's)")
def preview(kind_id: int, payload: PreviewIn, request: Request, account: Caller, db: DbSession) -> KeepPreview:
    """Only documents the caller may see are counted; setting it changes every document of the kind."""
    who = _who(request, account, db, kind_id)
    found = keeping.preview(db, who.id, kind_id, payload.years, keeping.today_of(who))
    return KeepPreview(documents=found.documents, by_hand=found.by_hand, expired=found.expired)


class KeepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: Years to keep the documents of the kind, from the end of the year of their date; empty takes the time away.
    years: StrictInt | None = Field(ge=1, le=keeping.YEARS_MAX)
    #: Also for the documents already there: their `keep_until` is worked out again (taken away: a worked-out one
    #: goes); ones set by hand stay. Without it they are left alone (taken away: a worked-out one stays, as set by
    #: hand).
    existing: bool = False


class KeepOut(BaseModel):
    kind: KindOut
    #: Documents the caller may see whose `keep_until` changed now (every document of the kind is changed, only these
    #: are counted).
    changed: int
    #: More than 200 documents the caller may see: they are changed in the background, `changed` is 0.
    queued: bool


@router.put("/kinds/{kind_id}/keeping", response_model=KeepOut,
            summary="Set or take away the keeping time of a kind (manage in its vault; the operator for the server's)")
def set_keeping(kind_id: int, payload: KeepIn, request: Request, account: Caller, db: DbSession) -> KeepOut:
    who = _who(request, account, db, kind_id)
    done = keeping.set_kind(db, who.id, kind_id, payload.years, payload.existing)
    shown = kind_out(done.kind)
    assert shown is not None
    return KeepOut(kind=shown, changed=done.changed, queued=done.queued)


class AutoTrashIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


class AutoTrashOut(BaseModel):
    kind: KindOut
    #: Filed documents of the kind that the caller may see and whose keeping time is over now: what the switch would
    #: put in the trash at its next run (once a day).
    due: int


@router.post("/kinds/{kind_id}/auto-trash/preview", response_model=AutoTrashOut,
             summary="Whether expired documents of a kind go to the trash by themselves, and how many would go now; "
                     "changes nothing (manage in its vault; the operator for the server's)")
def preview_auto_trash(kind_id: int, request: Request, account: Caller, db: DbSession) -> AutoTrashOut:
    """Counts only documents the caller may see."""
    who = _who(request, account, db, kind_id)
    kind, due = keeping.auto_trash_state(db, who.id, kind_id, keeping.today_of(who))
    shown = kind_out(kind)
    assert shown is not None
    return AutoTrashOut(kind=shown, due=due)


@router.put("/kinds/{kind_id}/auto-trash", response_model=AutoTrashOut,
            summary="Switch expired documents of a kind into the trash by themselves on or off (manage in its vault; "
                    "the operator for the server's)")
def set_auto_trash(kind_id: int, payload: AutoTrashIn, request: Request, account: Caller,
                   db: DbSession) -> AutoTrashOut:
    """Off from the start, and only for a kind with a keeping time (`409 no_keeping_time`). Once a day the filed
    documents of the kind whose `keep_until` has passed go to the trash (30 days to get them back), each once, at most
    500 a day. Nothing is deleted for good. Switching it on changes nothing now; the next run does the work."""
    who = _who(request, account, db, kind_id)
    kind = keeping.set_auto_trash(db, who.id, kind_id, payload.enabled)
    _kind, due = keeping.auto_trash_state(db, who.id, kind_id, keeping.today_of(who))
    shown = kind_out(kind)
    assert shown is not None
    return AutoTrashOut(kind=shown, due=due)


class MayGoPage(BaseModel):
    #: The documents, the ones whose time is over longest first. Their `dates` hold the `keep_until`.
    items: list[DocumentOut]
    total: int


@router.get("/keeping", response_model=MayGoPage,
            summary="Filed documents whose keeping time is over, in the vaults where the caller may change things")
def may_go(account: Reader, db: DbSession, vault_id: int | None = Query(default=None, ge=1, le=2**31 - 1),
           limit: int = Query(default=100, ge=1, le=MAX_TRASH),
           offset: int = Query(default=0, ge=0, le=10**7)) -> MayGoPage:
    """Nothing goes by itself: the person picks and puts them in the trash (`POST /documents/trash`). A vault where
    the caller may only read, and documents only shared with them, are not looked at."""
    found, total = keeping.expired(db, account.id, keeping.today_of(account), vault_id=vault_id, limit=limit,
                                   offset=offset)
    return MayGoPage(items=[document_out(r) for r in documents.rows(db, account.id, found)], total=total)


class TrashIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[StrictInt] = Field(min_length=1, max_length=MAX_TRASH)


class Refused(BaseModel):
    id: int
    #: The code a single `DELETE /documents/{id}` would have given (`not_found`, `forbidden` ...).
    code: str


class TrashOut(BaseModel):
    trashed: list[int]
    failed: list[Refused]


@router.post("/documents/trash", response_model=TrashOut, tags=["documents"],
             summary="Put many documents in the trash for 30 days, each checked on its own")
def trash_many(payload: TrashIn, account: Caller, db: DbSession) -> TrashOut:
    """Like `DELETE /documents/{id}` for each: `edit` on the document. One the caller may not see fails as
    `not_found`, exactly as one that does not exist; the others go on."""
    trashed: list[int] = []
    failed: list[Refused] = []
    for document_id in dict.fromkeys(payload.ids):
        try:
            if not 1 <= document_id < 2**31:
                raise error("not_found", "Not found.", 404)
            documents.trash(db, account.id, document_id)
            trashed.append(document_id)
        except HTTPException as exc:
            # One refusal does not stop the others.
            db.rollback()
            code = exc.detail.get("code", "failed") if isinstance(exc.detail, dict) else "failed"
            failed.append(Refused(id=document_id, code=str(code)))
    return TrashOut(trashed=trashed, failed=failed)
