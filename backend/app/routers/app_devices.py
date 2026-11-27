"""The shared module geraete 0.1.4 in nexpaper (``services/geraete_store.py``): the parts that are nexpaper's own.

``GET /api/app/1/hello`` and ``GET /api/app/1/me``: the two routes of the app's own on ``/api/app/1``, where the iPhone
apps built on NexKonto speak (``me`` with the key, through the module's ``api.device``). The rest of ``/api/app/1`` and
the browser's routes under ``/api/v1`` (``app-pairing``, ``app-connect``, ``app-devices``,
``server/accounts/{id}/devices``) are the module's (``main.py``). The pairing window's QR code is the module's too:
with ``link_form="pair"`` (G58) its link is ``nexpaper://pair?server=…&code=…``, which nexpaper-ios up to 1.3 scans and
trades at ``POST /api/v1/devices/pair``, then ``address``, ``pairing`` and ``secret`` for an app built on NexKonto.

The old routes of before (``/api/v1/devices``, ``/api/v1/devices/pairing``, ``/pair``, ``/sibling``, OAuth) stay in
``routers/devices.py`` and ``routers/pairing.py`` with their shapes.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from .. import __version__
from ..services import geraete_store
from ..vendor import nexgeraete
from ..vendor.nexgeraete import api

router = APIRouter(include_in_schema=False)

CONFIG = geraete_store.CONFIG
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
