"""Sharing a document: with a person of this server, or by a link with somebody who has no account.

Who may share: the managers of the vault and the person the document belongs to. The operator's switch ends every link
at once; the longest a link may last is the operator's choice. The address of a link can be copied again by the person
who made it and by the managers of the vault (``POST .../links/{id}/address``); the history says when.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, StrictBool, StrictInt

from ..deps import Account as Caller
from ..deps import DbSession, OperatorAccount, Reader
from ..models import Account, Document, Link
from ..services import settings_service, sharing
from .schemas import PersonRef, person

router = APIRouter(prefix="/api/v1", tags=["sharing"])


class ShareOut(BaseModel):
    user: PersonRef
    right: Literal["read", "edit"]
    created_at: datetime


class ShareIn(BaseModel):
    right: Literal["read", "edit"]


class LinkOut(BaseModel):
    id: int
    document_id: int
    recipient: str
    until: datetime
    allow_download: bool
    opened_count: int
    last_opened_at: datetime | None
    created_at: datetime
    created_by: PersonRef | None
    revoked_at: datetime | None
    #: ``active``; ``expired`` (its end, or the operator's limit, has passed); ``revoked``; ``off`` while the operator
    #: has links switched off; ``ended`` when the person who made it may no longer share the document.
    status: Literal["active", "expired", "revoked", "off", "ended"]
    #: The caller may copy the address again (the person who made it, the managers of the vault).
    can_copy: bool


class LinkCreated(LinkOut):
    #: The link's token.
    token: str
    #: The address to give out.
    url: str


class LinkAddress(BaseModel):
    url: str


class LinkIn(BaseModel):
    recipient: str = Field(max_length=sharing.RECIPIENT_MAX * 2)
    days: StrictInt = Field(ge=1, le=365)
    allow_download: StrictBool = True


class MyLink(LinkOut):
    document_title: str


class SharingRules(BaseModel):
    links_allowed: bool
    link_max_days: int


class SharingOverview(BaseModel):
    open_links: int
    people: int
    next_end: datetime | None


def _link(link: Link, db: DbSession, *, maker_ok: bool, can_copy: bool) -> LinkOut:
    author = db.get(Account, link.created_by) if link.created_by else None
    current = sharing.rules(db)
    return LinkOut(
        id=link.id, document_id=link.document_id, recipient=link.recipient, until=sharing.ends(link, current.max_days),
        allow_download=link.allow_download, opened_count=link.opened_count, last_opened_at=link.last_opened_at,
        created_at=link.created_at, created_by=person(author), revoked_at=link.revoked_at,
        status=sharing.status_of(link, current, maker_ok),  # type: ignore[arg-type]
        can_copy=can_copy,
    )


def _address(request: Request, db: DbSession, token: str) -> str:
    base = settings_service.public_url(db) or str(request.base_url).rstrip("/")
    return f"{base}/l/{token}"


@router.get("/sharing", response_model=SharingRules,
            summary="Whether links to the outside are on, and how long they last")
def rules(_account: Reader, db: DbSession) -> SharingRules:
    current = sharing.rules(db)
    return SharingRules(links_allowed=current.allowed, link_max_days=current.max_days)


@router.get("/sharing/overview", response_model=SharingOverview,
            summary="For the operator: how many links are open and whose (never what they point at)")
def overview(_operator: OperatorAccount, db: DbSession) -> SharingOverview:
    found = sharing.overview(db)
    return SharingOverview(open_links=found.open_links, people=found.people, next_end=found.next_end)  # type: ignore[arg-type]


@router.get("/links", response_model=list[MyLink], summary="The open links the caller made")
def my_links(account: Reader, db: DbSession) -> list[MyLink]:
    out = []
    for link, document in sharing.my_links(db, account.id):
        out.append(MyLink(**_link(link, db, maker_ok=True, can_copy=True).model_dump(), document_title=document.title))
    return out


@router.get("/documents/{document_id}/shares", response_model=list[ShareOut],
            summary="Who a document was shared with (who may share it: managers of the vault, its owner)")
def shares(document_id: int, account: Reader, db: DbSession) -> list[ShareOut]:
    return [ShareOut(user=person(a), right=s.right, created_at=s.created_at)  # type: ignore[arg-type]
            for s, a in sharing.shares_of(db, account.id, document_id)]


@router.put("/documents/{document_id}/shares/{user_id}", response_model=ShareOut,
            summary="Share a document with a person (or change the right)")
def set_share(document_id: int, user_id: int, payload: ShareIn, account: Caller, db: DbSession) -> ShareOut:
    share = sharing.set_share(db, account.id, document_id, user_id, payload.right)
    target = db.get(Account, user_id)
    return ShareOut(user=person(target), right=share.right, created_at=share.created_at)  # type: ignore[arg-type]


@router.delete("/documents/{document_id}/shares/{user_id}", status_code=204,
               summary="Stop sharing a document with a person (or give a shared document back)")
def remove_share(document_id: int, user_id: int, account: Caller, db: DbSession) -> None:
    sharing.remove_share(db, account.id, document_id, user_id)


@router.get("/documents/{document_id}/links", response_model=list[LinkOut], summary="The links of a document")
def links(document_id: int, account: Reader, db: DbSession) -> list[LinkOut]:
    return [_link(link, db, maker_ok=ok, can_copy=copy) for link, ok, copy in sharing.links_of(db, account.id,
                                                                                              document_id)]


@router.post("/documents/{document_id}/links", response_model=LinkCreated, status_code=201,
             summary="Make a link for somebody without an account")
def create_link(document_id: int, payload: LinkIn, request: Request, account: Caller, db: DbSession) -> LinkCreated:
    link, token = sharing.create_link(db, account.id, document_id, payload.recipient, payload.days,
                                      payload.allow_download)
    return LinkCreated(**_link(link, db, maker_ok=True, can_copy=True).model_dump(), token=token,
                       url=_address(request, db, token))


@router.post("/documents/{document_id}/links/{link_id}/address", response_model=LinkAddress,
             summary="The address of a link again, to copy (the person who made it, managers of the vault)")
def link_address(document_id: int, link_id: int, request: Request, account: Caller, db: DbSession) -> LinkAddress:
    """404 for everybody else, as for a link that does not exist. The history of the document says that the address
    was copied, never the address."""
    return LinkAddress(url=_address(request, db, sharing.address(db, account.id, document_id, link_id)))


@router.delete("/documents/{document_id}/links/{link_id}", status_code=204, summary="Revoke a link: it stops at once")
def revoke_link(document_id: int, link_id: int, account: Caller, db: DbSession) -> None:
    sharing.revoke_link(db, account.id, document_id, link_id)


__all__ = ["Document"]
