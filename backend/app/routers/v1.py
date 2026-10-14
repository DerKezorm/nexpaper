"""The routes for programs that hold an API key (``Authorization: Bearer npk_...``): a dashboard card, scripts.

**The promise.** What is under ``/api/v1`` stays as it is: new fields may come, nothing is renamed or taken away. A
change that would break a program goes to ``/api/v2`` beside it. ``docs/api.md`` describes the interface.

Walls, in this order: a request that carries an ``Origin`` is refused (browsers send one, programs do not; no web page
can use a key it found); API keys must be switched on by the operator; the key must be valid (a wrong one counts
against the sender like a wrong password); the key must stay under its rate. The session cookie counts for nothing
here. Devices that pair with a token of their own (``routers/devices.py``) use the account routes instead.

A key reads as its account and never more. What a key of scope ``read`` reads here is the dashboard card; the documents
themselves are read through ``routes/documents.py``.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from .. import __version__
from ..db import SessionLocal
from ..deps import address_failed, address_guard, bearer_scheme, bearer_token
from ..errors import error
from ..services import apikeys, dashboard, devices, logs, settings_service
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


class WaitingOut(BaseModel):
    id: int
    title: str
    added_at: str
    #: The page of the document in the web app.
    url: str


class DeadlineOut(BaseModel):
    id: int
    title: str
    #: The day, ``YYYY-MM-DD``.
    date: str
    #: ``due``, ``contract_end``, ``warranty_end`` or ``notice`` (a contract's last day to cancel).
    kind: str
    url: str


class DashboardOut(BaseModel):
    version: str
    inbox: int
    inbox_oldest: list[WaitingOut]
    inbox_oldest_at: str | None
    filed: int
    total: int
    added_week: int
    processing: int
    deadlines: list[DeadlineOut]


def _moment(value: Any) -> str:
    return str(value.replace(microsecond=0).isoformat())


@router.get("/dashboard", response_model=DashboardOut,
            summary="The numbers for a dashboard card: the inbox, the archive and what falls due soon")
def dashboard_card(request: Request, found: Reader) -> DashboardOut:
    """Counts and a few titles of what the key's account may read, nothing of the contents (no text, sender, amount or
    tag). A key of scope ``upload`` reads nothing here (``403 key_scope``).

    ``inbox`` is the inbox of the account as the menu shows it (the vaults where it may change things), ``filed``,
    ``total`` (everything not in the trash), ``added_week`` (the last seven days) and ``processing`` (text being read)
    are counted among all it may read. ``inbox_oldest`` names the five oldest of the inbox, the oldest first.
    ``deadlines`` are the dates of kind ``due``, ``contract_end`` and ``warranty_end`` from today to 14 days ahead, and
    the last day to cancel a contract as ``notice``, by day, at most 20; what is marked done is left out. ``url`` is
    the page of the document: the public address when the operator set one, else the address this request came to."""
    if found.scope != "read":
        raise error("key_scope", "This key is not for this.", 403)
    with SessionLocal() as db:
        base = settings_service.public_url(db) or str(request.base_url).rstrip("/")
        card = dashboard.numbers(db, found.account)

    def page(document_id: int, status: str) -> str:
        return f"{base}/dokument/{document_id}" if status == "filed" else f"{base}/eingang/{document_id}"

    return DashboardOut(
        version=__version__, inbox=card.inbox,
        inbox_oldest=[WaitingOut(id=d.id, title=d.title, added_at=_moment(d.added_at), url=page(d.id, d.status))
                      for d in card.inbox_oldest],
        inbox_oldest_at=_moment(card.inbox_oldest[0].added_at) if card.inbox_oldest else None,
        filed=card.filed, total=card.total, added_week=card.added_week, processing=card.processing,
        deadlines=[DeadlineOut(id=d.id, title=d.title, date=d.date.isoformat(), kind=d.kind, url=page(d.id, d.status))
                   for d in card.deadlines])
