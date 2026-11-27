"""The shared module geraete 0.1.0 in nexpaper (``services/geraete_store.py``): the parts that are nexpaper's own.

- ``GET /api/app/1/hello`` and ``GET /api/app/1/me``: the two routes of the app's own on ``/api/app/1``, where the
  iPhone apps built on NexKonto speak (``me`` with the key, through the module's ``api.device``). The rest of
  ``/api/app/1`` and the browser's routes under ``/api/v1`` (``app-pairing``, ``app-connect``, ``app-devices``,
  ``server/accounts/{id}/devices``) are the module's (``main.py``).
- ``POST /api/v1/devices/app-pairing``: the module's pairing (``POST /api/v1/app-pairing``), with a QR code the
  published iPhone app reads too; the page's pairing window asks here (``frontend/src/api/devices.ts``).
  nexpaper-ios up to 1.3 scans ``nexpaper://pair?server=…&code=…`` and trades the code at ``POST
  /api/v1/devices/pair``; the module's link ``nexpaper://connect?…`` means nothing to it. This link carries both:
  ``server`` and ``code`` for the published app, ``address``, ``pairing`` and ``secret`` (G6) for an app built on
  NexKonto. A new code ends the one before, as nexpaper's codes always did; everything else answers as the module's
  route does, and the window asks the module's routes for the rest.

The old routes of before (``/api/v1/devices``, ``/api/v1/devices/pairing``, ``/pair``, ``/sibling``, OAuth) stay in
``routers/devices.py`` and ``routers/pairing.py`` with their shapes.
"""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import quote, urlsplit, urlunsplit

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..deps import BrowserAccount
from ..services import geraete_store, settings_service
from ..vendor import nexgeraete
from ..vendor.nexgeraete import api, forms, qr

router = APIRouter(include_in_schema=False)

CONFIG = geraete_store.CONFIG
Data = Annotated[geraete_store.GeraeteStore, Depends(geraete_store.store)]
Found = Annotated[nexgeraete.Caller, Depends(api.device(config=CONFIG, store=geraete_store.store,
                                                       clock=geraete_store.now))]


@router.get("/api/app/1/hello")
def hello() -> dict[str, Any]:
    """Who answers here, before any key: the app, the version of ``/api/app/1``, the ways a device may come in."""
    return {"app": CONFIG.app, "api": 1, "min_api": 1, "version": __version__, **api.hello_fields(CONFIG)}


@router.get("/api/app/1/me")
def me(found: Found) -> dict[str, Any]:
    """The account, this device, whether notifications can go out."""
    return api.me_fields(CONFIG, found)


class AddressIn(BaseModel):
    #: Where the browser sees nexpaper now; counts only when the operator set no public address.
    address: str = Field(default="", max_length=600)


def _origin(raw: str) -> str:
    """An address the browser gave, with its path (a nexpaper under a sub-path, G47), without query; empty when it is
    none."""
    parts = urlsplit(raw.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def pair_link(address: str, code: str, pairing_id: str, secret: str) -> str:
    """What the QR code holds: ``nexpaper://pair?server=…&code=…`` as the published app reads it, then ``address``,
    ``pairing`` and ``secret`` of the module (G6)."""
    where = quote(address, safe="")
    return (f"{CONFIG.scheme}://pair?server={where}&code={quote(code, safe='')}&address={where}"
            f"&pairing={quote(pairing_id, safe='')}&secret={quote(secret, safe='')}")


@router.post("/api/v1/devices/app-pairing", status_code=201)
def start_pairing(request: Request, account: BrowserAccount, data: Data,
                  body: Annotated[AddressIn | None, Body()] = None) -> Any:
    """A QR code and a code for the app (five minutes, one device; a new one ends the one before)."""
    public = settings_service.public_url(data.db)
    address = public or _origin(body.address if body else "") or _origin(str(request.base_url))
    try:
        started = nexgeraete.pairing.start(data, CONFIG, account.id, address=address, replace=True,
                                           now=geraete_store.now())
    except nexgeraete.DeviceRefused as refusal:
        data.rollback()
        status, content, headers = forms.refusal(nexgeraete.FORM_NEX, refusal)
        return JSONResponse(status_code=status, content=content, headers=headers)
    link = pair_link(started.address, started.code, started.pairing.id, started.secret)
    return JSONResponse(
        status_code=201,
        content={
            "id": started.pairing.id,
            "secret": started.secret,
            "code": started.code,
            "link": link,
            "address": started.address,
            "expires_at": nexgeraete.devices.iso(started.pairing.expires_at),
            "qr_svg": qr.svg(link),
            "app_store_url": CONFIG.app_store_url,
        },
        headers={"Cache-Control": "no-store"},
    )
