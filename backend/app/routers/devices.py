"""Paired devices: a phone, a later native app or a script that speaks for an account with a token of its own.

Making, listing and revoking want a signed-in browser (``BrowserAccount``): a device cannot pair another one, and a lost
phone cannot make itself a new token. The token is shown once. Pairing by a QR code and by OAuth with PKCE is in
``routers/pairing.py``; this is the token itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field

from ..deps import BrowserAccount, DbSession
from ..errors import error
from ..models import Device
from ..services import devices

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])

DeviceUid = Annotated[str, Path(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")]


class DeviceOut(BaseModel):
    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    #: How it was paired: ``token`` (made in the browser), ``qr`` (a pairing code), ``app:<client>`` (an app, OAuth).
    via: str = "token"


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=devices.NAME_MAX)


class PairedOut(BaseModel):
    device: DeviceOut
    #: The token of the device, shown once and never again.
    token: str


def _out(row: Device) -> DeviceOut:
    return DeviceOut(id=row.uid, name=row.name, prefix=row.prefix, created_at=row.created_at,
                     last_used_at=row.last_used_at, via=row.via or "token")


@router.get("", response_model=list[DeviceOut], summary="The devices paired with the own account")
def listing(account: BrowserAccount, db: DbSession) -> list[DeviceOut]:
    return [_out(row) for row in devices.listing(db, account.id)]


@router.post("", response_model=PairedOut, status_code=201, summary="Pair a device; its token is shown once")
def pair(body: DeviceIn, account: BrowserAccount, db: DbSession) -> PairedOut:
    row, token = devices.make(db, account, body.name)
    return PairedOut(device=_out(row), token=token)


@router.delete("/{uid}", status_code=204, summary="Revoke a device: its token stops working at once")
def revoke(uid: DeviceUid, account: BrowserAccount, db: DbSession) -> None:
    if not devices.revoke(db, account.id, uid):
        raise error("not_found", "Not found.", 404)
