"""The routes for programs that hold an API key (``Authorization: Bearer npk_...``): a dashboard card, scripts.

**The promise.** What is under ``/api/v1`` stays as it is: new fields may come, nothing is renamed or taken away. A
change that would break a program goes to ``/api/v2`` beside it. ``docs/api.md`` describes the interface.

Walls, in this order: a request that carries an ``Origin`` is refused (browsers send one, programs do not; no web page
can use a key it found); API keys must be switched on by the operator; the key must be valid (a wrong one counts
against the sender like a wrong password); the key must stay under its rate. The session cookie counts for nothing
here. Devices that pair with a token of their own (``routers/devices.py``) use the account routes instead.

A key reads as its account and never more. The routes for documents join with the blocks that make documents.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials

from .. import __version__
from ..db import SessionLocal
from ..deps import address_failed, address_guard, bearer_scheme, bearer_token
from ..errors import error
from ..services import apikeys, devices, logs
from ..services.apikeys import Caller

logger = logging.getLogger("nexpaper.api")

router = APIRouter(prefix="/api/v1", tags=["api keys"])


def caller(
    request: Request, _scheme: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None
) -> Caller:
    if request.headers.get("origin"):
        raise error("origin_refused", "The API is for programs, not web pages.", 403)
    token = bearer_token(request)
    if token is not None and token.startswith(devices.TOKEN_PREFIX):
        raise error("token_wrong_kind", "This is a device token; this route wants an API key.", 401)
    with SessionLocal() as db:
        if not apikeys.allowed(db):
            raise error("api_off", "The operator has not switched API keys on.", 401)
        address_guard(request)
        found = apikeys.authenticate(db, bearer_token(request))
    if found is None:
        address_failed(request)
        raise error("key_invalid", "No valid API key.", 401)
    if not apikeys.brake(found.key_id):
        exc = error("slow_down", "Too many requests with this key. Wait a minute.", 429)
        exc.headers = {"Retry-After": "60"}
        raise exc
    logs.set_actor(found.account.name)
    return found


Reader = Annotated[Caller, Depends(caller)]


@router.get("/me", summary="Who the API key speaks for, and what it may")
def me(found: Reader) -> dict[str, Any]:
    return {
        "name": found.account.name,
        "display_name": found.account.display_name,
        "scope": found.scope,
        "version": __version__,
    }
