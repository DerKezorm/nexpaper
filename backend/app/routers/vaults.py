"""Vaults: the places documents are kept, who is in them with which right.

Listing and reading is open to a signed-in browser, a device and a program with a key. Making, renaming, deleting a
vault and changing who is in it want a signed-in browser (``BrowserAccount``): the rights of other people are never
changed with a device token. A vault is made by the operator only; its managers hand out the rights.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import BrowserAccount, DbSession, OperatorAccount, Reader
from ..models import Account
from ..services import vaults
from .schemas import PersonRef

router = APIRouter(prefix="/api/v1", tags=["vaults"])


class MemberOut(BaseModel):
    user_id: int
    name: str
    display_name: str
    right: Literal["read", "edit", "manage"]


class VaultOut(BaseModel):
    id: int
    name: str
    icon: str
    #: Whose own vault this is; empty for a shared one.
    personal_of: int | None
    my_right: Literal["read", "edit", "manage"]
    #: Documents in it (the trash not counted) and the bytes of their files.
    documents: int
    size: int
    members: list[MemberOut]


class VaultIn(BaseModel):
    name: str = Field(min_length=1, max_length=vaults.NAME_MAX)
    icon: str = Field(default="folder", max_length=16)


class VaultPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=vaults.NAME_MAX)
    icon: str | None = Field(default=None, max_length=16)


class MemberIn(BaseModel):
    right: Literal["read", "edit", "manage"]


class MemberRow(BaseModel):
    user_id: int = Field(ge=1, le=2**31 - 1)
    right: Literal["read", "edit", "manage"]


class MembersIn(BaseModel):
    """Everybody who is to be in the vault, with their right; who is left out leaves."""

    members: list[MemberRow] = Field(max_length=vaults.MAX_MEMBERS)


class MoveToIn(BaseModel):
    move_to: int | None = Field(default=None, ge=1, le=2**31 - 1)


def _out(item: vaults.VaultView) -> VaultOut:
    return VaultOut(
        id=item.vault.id, name=item.name, icon=item.vault.icon, personal_of=item.vault.personal_of,
        my_right=item.right,  # type: ignore[arg-type]
        documents=item.documents, size=item.size,
        members=[MemberOut(user_id=m.user_id, name=a.name, display_name=a.display_name,
                           right=m.right) for m, a in item.members],  # type: ignore[arg-type]
    )


@router.get("/vaults", response_model=list[VaultOut], summary="The vaults the caller is a member of")
def listing(account: Reader, db: DbSession) -> list[VaultOut]:
    return [_out(item) for item in vaults.listing(db, account.id)]


@router.get("/vaults/{vault_id}", response_model=VaultOut, summary="One vault, with its members")
def read(vault_id: int, account: Reader, db: DbSession) -> VaultOut:
    return _out(vaults.view(db, account.id, vault_id))


@router.post("/vaults", response_model=VaultOut, status_code=201, summary="Make a shared vault (the operator)")
def create(payload: VaultIn, operator: OperatorAccount, db: DbSession) -> VaultOut:
    vault = vaults.create_shared(db, operator, payload.name, payload.icon)
    return _out(vaults.view(db, operator.id, vault.id))


@router.patch("/vaults/{vault_id}", response_model=VaultOut,
              summary="Rename a shared vault or change its icon (managers)")
def patch(vault_id: int, payload: VaultPatch, account: BrowserAccount, db: DbSession) -> VaultOut:
    vaults.update_vault(db, account.id, vault_id, payload.name, payload.icon)
    return _out(vaults.view(db, account.id, vault_id))


@router.delete("/vaults/{vault_id}", status_code=204,
               summary="Delete a shared vault (managers); documents in it go to `move_to`")
def delete(vault_id: int, account: BrowserAccount, db: DbSession,
           move_to: Annotated[int | None, Query(ge=1, le=2**31 - 1)] = None) -> None:
    vaults.delete_vault(db, account.id, vault_id, move_to)


@router.put("/vaults/{vault_id}/members", response_model=VaultOut,
            summary="Set who is in the vault with which right, all at once (managers); a refusal changes nothing")
def set_members(vault_id: int, payload: MembersIn, account: BrowserAccount, db: DbSession) -> VaultOut:
    vaults.set_members(db, account.id, vault_id, [(m.user_id, m.right) for m in payload.members])
    return _out(vaults.view(db, account.id, vault_id))


@router.put("/vaults/{vault_id}/members/{user_id}", response_model=VaultOut,
            summary="Give a person a right in the vault, or change it (managers)")
def set_member(vault_id: int, user_id: int, payload: MemberIn, account: BrowserAccount, db: DbSession) -> VaultOut:
    vaults.set_member(db, account.id, vault_id, user_id, payload.right)
    return _out(vaults.view(db, account.id, vault_id))


@router.delete("/vaults/{vault_id}/members/{user_id}", status_code=204,
               summary="Take a person out of the vault (managers)")
def remove_member(vault_id: int, user_id: int, account: BrowserAccount, db: DbSession) -> None:
    vaults.remove_member(db, account.id, vault_id, user_id)


@router.post("/vaults/{vault_id}/leave", status_code=204, summary="Leave a shared vault")
def leave(vault_id: int, account: BrowserAccount, db: DbSession) -> None:
    vaults.leave(db, account.id, vault_id)


@router.get("/people", response_model=list[PersonRef], summary="The people of this server, to share with")
def people(_account: Reader, db: DbSession) -> list[PersonRef]:
    """Names only (no mail addresses, no roles), without blocked accounts: enough to pick somebody to share with."""
    rows = db.scalars(select(Account).where(Account.blocked_at.is_(None)).order_by(Account.name))
    return [PersonRef(id=a.id, name=a.name, display_name=a.display_name) for a in rows]
