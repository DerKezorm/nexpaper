"""Paired devices: a phone, a later native app or a script that speaks for an account with a token of its own.

Making, listing and revoking want a signed-in browser (``BrowserAccount``): a lost phone cannot make itself a new token.
One exception: a device brings in another device of its account (``POST /sibling``), for the owner's iPad that takes the
iPhone's connection from iCloud; the new device has a token and a place in the list of its own. The token is shown once.
Pairing by a QR code and by OAuth with PKCE is in ``routers/pairing.py``; this is the token itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, Field

from ..deps import Account, BrowserAccount, DbSession
from ..errors import error
from ..models import Device
from ..services import devices, geraete_store
from ..services.konten_store import oldest_name
from ..vendor import nexgeraete

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])

DeviceUid = Annotated[str, Path(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")]


class DeviceOut(BaseModel):
    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    #: How it was paired: ``token`` (made in the browser), ``qr`` (a pairing code), ``app:<client>`` (an app, OAuth),
    #: ``device`` (brought in by another device of the account).
    via: str = "token"


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=devices.NAME_MAX)


class PairedOut(BaseModel):
    device: DeviceOut
    #: The token of the device, shown once and never again.
    token: str
    #: The account the device now speaks for: its first username, the same across renames (an app up to
    #: nexpaper-ios 1.3 keeps the connection by it). The current name is in ``GET /api/v1/auth/me``.
    account: str
    #: The id of the account (a JSON number): what an app keeps a connection by from now on.
    account_id: int


def _out(row: Device) -> DeviceOut:
    # The names of before (geraete 0.1.0 writes ``icloud`` and ``code`` for these two ways).
    return DeviceOut(id=row.uid, name=row.name, prefix=row.prefix, created_at=row.created_at,
                     last_used_at=row.last_used_at, via=geraete_store.old_via(row.via))


@router.get("", response_model=list[DeviceOut], summary="The devices paired with the own account")
def listing(account: BrowserAccount, db: DbSession) -> list[DeviceOut]:
    return [_out(row) for row in devices.listing(db, account.id)]


@router.post("", response_model=PairedOut, status_code=201, summary="Pair a device; its token is shown once")
def pair(body: DeviceIn, account: BrowserAccount, db: DbSession) -> PairedOut:
    row, token = devices.make(db, account, body.name)
    return PairedOut(device=_out(row), token=token, account=oldest_name(db, account), account_id=account.id)


class BroughtOut(BaseModel):
    """The answer of ``POST /devices/pair``: the new device, its token (shown once) and the account."""
    device: DeviceOut
    token: str
    #: The account the device now speaks for: its first username, the same across renames (an app up to
    #: nexpaper-ios 1.3 keeps the connection by it). The current name is in ``GET /api/v1/auth/me``.
    account: str
    #: The id of the account (a JSON number): what an app keeps a connection by from now on.
    account_id: int


@router.post("/sibling", response_model=BroughtOut, status_code=201,
             summary="A device brings in another device of its account; the new token is shown once")
def bring_in(body: DeviceIn, request: Request, account: Account, db: DbSession) -> BroughtOut:
    parent = getattr(request.state, "device", None)
    if parent is None:
        # A browser pairs with ``POST /devices`` or a code; this way is for a device that hands its connection on.
        raise error("device_only", "This needs a device token.", 403)
    row, token = devices.sibling(db, account, parent, body.name,
                                 nexgeraete.client_of(request.headers.get(nexgeraete.CLIENT_HEADER)))
    return BroughtOut(device=_out(row), token=token, account=oldest_name(db, account), account_id=account.id)


@router.delete("/{uid}", status_code=204, summary="Revoke a device: its token stops working at once")
def revoke(uid: DeviceUid, account: BrowserAccount, db: DbSession) -> None:
    if not devices.revoke(db, account.id, uid):
        raise error("not_found", "Not found.", 404)
