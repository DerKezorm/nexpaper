"""Senders, kinds and tags.

Senders and tags belong to a vault. The lists show the ones of the vaults the caller is in and of the documents shared
with them, the same name from several vaults as one entry (with the rows behind it). Renaming, merging and deleting act
on one row, that is on one vault, and need ``edit`` there. Kinds are of two sorts: the ones for the whole server are the
operator's to change, and every vault makes kinds of its own (``edit`` there), which the lists show to its members only.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field

from ..deps import Account as Caller
from ..deps import DbSession, Reader, require_browser_account, require_operator
from ..models import OPERATOR, Kind
from ..models import Account as AccountRow
from ..services import catalog
from .schemas import KindOut, NameRef, kind_out

router = APIRouter(prefix="/api/v1", tags=["catalog"])


class NameIn(BaseModel):
    name: str = Field(max_length=catalog.SENDER_MAX * 2)


class NameItem(BaseModel):
    id: int
    vault_id: int


class NameGroup(BaseModel):
    """One name, and the rows of that name in the vaults the caller reaches (one per vault)."""

    name: str
    items: list[NameItem]


def _groups(found: list[catalog.Group]) -> list[NameGroup]:
    return [NameGroup(name=g.name, items=[NameItem(id=i, vault_id=v) for i, v in g.items]) for g in found]


VaultFilter = Query(default=None, ge=1, le=2**31 - 1)


class MergeIn(BaseModel):
    #: The entry the documents go to. No lower bound here: the rights come first, whatever the number.
    into: int = Field(le=2**31 - 1)


class OrderEntry(BaseModel):
    """One sender, tag or kind with how many documents use it (``documents``: not in the trash; ``in_trash``: in it)."""

    id: int
    name: str
    #: The vault it belongs to; empty for a kind of the whole server.
    vault_id: int | None
    #: The caller's right in that vault; empty for a kind of the server.
    right: Literal["read", "edit", "manage"] | None
    documents: int
    in_trash: int
    #: Whether the caller may rename, merge and delete it here: `manage` in its vault, or the operator for a kind of the
    #: server.
    can_change: bool


class KindEntry(OrderEntry):
    key: str
    hue: int
    position: int


class OrderPage(BaseModel):
    items: list[OrderEntry]
    total: int


class KindOrderPage(BaseModel):
    items: list[KindEntry]
    total: int


Order = Query(default="name", pattern="^(name|documents)$", description="`name`, or `documents` (most used first)")


class KindIn(BaseModel):
    name: str = Field(max_length=catalog.KIND_MAX * 2)
    hue: int = Field(default=30, ge=0, le=360)
    #: A kind for this vault (``edit`` there); left out, a kind for the whole server (the operator).
    vault_id: int | None = Field(default=None, ge=1, le=2**31 - 1)


class KindPatch(BaseModel):
    name: str | None = Field(default=None, max_length=catalog.KIND_MAX * 2)
    hue: int | None = Field(default=None, ge=0, le=360)
    position: int | None = Field(default=None, ge=0, le=1000)


@router.get("/senders", response_model=list[NameGroup],
            summary="The senders of the caller's vaults and shared documents, gathered by name")
def senders(account: Reader, db: DbSession, vault_id: int | None = VaultFilter) -> list[NameGroup]:
    return _groups(catalog.visible_senders(db, account.id, vault_id))


@router.patch("/senders/{sender_id}", response_model=NameRef,
              summary="Rename a sender in its vault (onto a name the vault has merges them: manage, else 409); edit")
def rename_sender(sender_id: int, payload: NameIn, account: Caller, db: DbSession) -> NameRef:
    sender = catalog.rename_sender(db, account.id, sender_id, payload.name)
    return NameRef(id=sender.id, name=sender.name)


@router.delete("/senders/{sender_id}", status_code=204,
               summary="Delete a sender from its vault; its documents are left without one (managers, if any use it)")
def delete_sender(sender_id: int, account: Caller, db: DbSession,
                  force: bool = Query(default=False, description="Refused (403) for a caller who is not a manager "
                                                                 "while documents use the sender")) -> None:
    """While documents use the sender, only a manager of the vault deletes it. Anybody else with ``edit`` gets 409
    ``in_use`` with ``documents``, and 403 with ``force=true``, which is no way round the right."""
    catalog.delete_sender(db, account.id, sender_id, force)


@router.get("/tags", response_model=list[NameGroup],
            summary="The tags of the caller's vaults and shared documents, gathered by name")
def tags(account: Reader, db: DbSession, vault_id: int | None = VaultFilter) -> list[NameGroup]:
    return _groups(catalog.visible_tags(db, account.id, vault_id))


@router.patch("/tags/{tag_id}", response_model=NameRef,
              summary="Rename a tag in its vault (onto a name the vault has merges them: manage, else 409); edit")
def rename_tag(tag_id: int, payload: NameIn, account: Caller, db: DbSession) -> NameRef:
    tag = catalog.rename_tag(db, account.id, tag_id, payload.name)
    return NameRef(id=tag.id, name=tag.name)


@router.delete("/tags/{tag_id}", status_code=204,
               summary="Delete a tag from its vault, and take it off the documents there (edit in the vault)")
def delete_tag(tag_id: int, account: Caller, db: DbSession) -> None:
    catalog.delete_tag(db, account.id, tag_id)


def _operator(request: Request) -> AccountRow:
    """The operator in a signed-in browser (the kinds of the whole server are theirs to change)."""
    return require_operator(request, require_browser_account(request))


@router.get("/kinds", response_model=list[KindOut],
            summary="The kinds the caller can choose from: the server's and those of their vaults")
def kinds(account: Reader, db: DbSession, vault_id: int | None = VaultFilter) -> list[KindOut]:
    """With ``vault_id``, the choice for a document of that vault: the server's kinds and that vault's, one entry per
    name. Without it, the server's kinds and those of every vault the caller is in (a name may repeat across vaults)."""
    return [k for k in (kind_out(row) for row in catalog.kinds(db, account.id, vault_id)) if k is not None]


@router.post("/kinds", response_model=KindOut, status_code=201,
             summary="Add a kind: for a vault (`vault_id`, edit there) or for the whole server (the operator)")
def create_kind(payload: KindIn, request: Request, response: Response, account: Caller, db: DbSession) -> KindOut:
    """A name the vault can already choose (its own kind, or one of the server's) answers ``200`` with that kind."""
    uid = account.id if payload.vault_id is not None else _operator(request).id
    kind, created = catalog.create_kind(db, uid, payload.name, payload.hue, payload.vault_id)
    if not created:
        response.status_code = 200
    return kind_out(kind)  # type: ignore[return-value]


def _may_change(request: Request, account: AccountRow, db: DbSession, kind_id: int) -> AccountRow:
    """The caller, who must be the operator (in a browser) when the kind is one of the whole server's."""
    row = db.get(Kind, kind_id)
    if row is not None and row.vault_id is None:
        return _operator(request)
    return account


@router.patch("/kinds/{kind_id}", response_model=KindOut,
              summary="Rename or recolor a kind (edit in its vault; the operator for the server's)")
def update_kind(kind_id: int, payload: KindPatch, request: Request, account: Caller, db: DbSession) -> KindOut:
    who = _may_change(request, account, db, kind_id)
    return kind_out(catalog.update_kind(db, who.id, kind_id, payload.name, payload.hue, payload.position))  # type: ignore[return-value]


@router.delete("/kinds/{kind_id}", status_code=204,
               summary="Delete a kind; its documents are left without one (managers of its vault, or `force`; the "
                       "operator for the server's)")
def delete_kind(kind_id: int, request: Request, account: Caller, db: DbSession,
                force: bool = Query(default=False, description="Take it off the documents that use it")) -> None:
    """While documents use a kind of a vault, a manager of the vault deletes it, anybody else with ``edit`` only with
    ``force=true``; otherwise 409 ``in_use`` with ``documents``, the number to ask about."""
    who = _may_change(request, account, db, kind_id)
    catalog.delete_kind(db, who.id, kind_id, force)


# --- Order: what the senders, tags and kinds are used for ------------------------------------------------------------


def _page(account: AccountRow, db: DbSession, what: str, vault_id: int | None, q: str, order: str, limit: int,
          offset: int) -> tuple[list[dict[str, object]], int]:
    items, total = catalog.entries(db, account.id, what, vault_id=vault_id, q=q, order=order, limit=limit,
                                   offset=offset)
    for item in items:
        if item["vault_id"] is None:
            item["can_change"] = account.role == OPERATOR
    return items, total


@router.get("/order/senders", response_model=OrderPage,
            summary="The senders of the caller's vaults with the number of documents that use each")
def order_senders(account: Reader, db: DbSession, vault_id: int | None = VaultFilter,
                  q: str = Query(default="", max_length=200, description="Part of the name"), order: str = Order,
                  limit: int = Query(default=200, ge=1, le=catalog.ORDER_MAX),
                  offset: int = Query(default=0, ge=0, le=10**7)) -> OrderPage:
    """Only the vaults the caller is in are looked at; a `vault_id` they are not in answers like an empty one."""
    items, total = _page(account, db, "senders", vault_id, q, order, limit, offset)
    return OrderPage.model_validate({"items": items, "total": total})


@router.get("/order/tags", response_model=OrderPage,
            summary="The tags of the caller's vaults with the number of documents that carry each")
def order_tags(account: Reader, db: DbSession, vault_id: int | None = VaultFilter,
               q: str = Query(default="", max_length=200, description="Part of the name"), order: str = Order,
               limit: int = Query(default=200, ge=1, le=catalog.ORDER_MAX),
               offset: int = Query(default=0, ge=0, le=10**7)) -> OrderPage:
    items, total = _page(account, db, "tags", vault_id, q, order, limit, offset)
    return OrderPage.model_validate({"items": items, "total": total})


@router.get("/order/kinds", response_model=KindOrderPage,
            summary="The kinds of the server and of the caller's vaults with the number of documents that have each")
def order_kinds(account: Reader, db: DbSession, vault_id: int | None = VaultFilter,
                q: str = Query(default="", max_length=200, description="Part of the name"), order: str = Order,
                limit: int = Query(default=200, ge=1, le=catalog.ORDER_MAX),
                offset: int = Query(default=0, ge=0, le=10**7)) -> KindOrderPage:
    """A kind of the server is counted over the documents of the caller's vaults only."""
    items, total = _page(account, db, "kinds", vault_id, q, order, limit, offset)
    return KindOrderPage.model_validate({"items": items, "total": total})


@router.post("/senders/{sender_id}/merge", response_model=NameRef,
             summary="Move all documents of a sender to another sender of the same vault, and delete it (manage)")
def merge_sender(sender_id: int, payload: MergeIn, account: Caller, db: DbSession) -> NameRef:
    target = catalog.merge_sender(db, account.id, sender_id, payload.into)
    return NameRef(id=target.id, name=target.name)


@router.post("/tags/{tag_id}/merge", response_model=NameRef,
             summary="Move all documents of a tag to another tag of the same vault, and delete it (manage)")
def merge_tag(tag_id: int, payload: MergeIn, account: Caller, db: DbSession) -> NameRef:
    target = catalog.merge_tag(db, account.id, tag_id, payload.into)
    return NameRef(id=target.id, name=target.name)


@router.post("/kinds/{kind_id}/merge", response_model=KindOut,
             summary="Move all documents of a kind to another kind they may have, and delete it (manage in its vault; "
                     "the operator for the server's)")
def merge_kind(kind_id: int, payload: MergeIn, request: Request, account: Caller, db: DbSession) -> KindOut:
    who = _may_change(request, account, db, kind_id)
    return kind_out(catalog.merge_kind(db, who.id, kind_id, payload.into))  # type: ignore[return-value]
