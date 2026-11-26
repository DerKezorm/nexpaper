"""API keys through the interface: an account's own (My account, Devices and apps) and every key for the operator.

Only with a signed-in browser: a key or a device token never makes, lists or deletes keys (``BrowserAccount``).

Since the settings of 1.12 these are the old routes of the shared key module (``vendor/nexschluessel``, mounted under
``/api/v1/connections`` in ``main.py``): they answer in their old shapes and with their old codes, and do their work
through ``nexschluessel.keys`` over the same rows (``services/schluessel_store.py``). The iPhone shortcut's card and
nexpaper-ios keep using them. New beside them: ``POST /api/v1/admin/api-keys/{id}/unblock``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from ..deps import BrowserAccount, DbSession, OperatorAccount
from ..errors import error
from ..services import apikeys
from ..services.schluessel_store import CONFIG, SchluesselStore
from ..vendor.nexschluessel import KeyRefused, keys

logger = logging.getLogger("nexpaper.api")

router = APIRouter(prefix="/api/v1", tags=["api keys"])

#: The module's refusals as these routes answered before it (code, text, status).
OLD_ANSWERS: dict[str, tuple[str, str, int]] = {
    "right_invalid": ("invalid_input", "No such scope.", 422),
    "days_invalid": ("invalid_input", "A key runs out after 30, 90 or 365 days, or never.", 422),
    "name_missing": ("invalid_input", "The input is not valid.", 422),
    "name_too_long": ("invalid_input", "The input is not valid.", 422),
    "too_many_keys": ("too_many_keys", "An account holds at most 20 keys.", 409),
    "api_off": ("api_off", "The operator has not switched API keys on.", 403),
    "not_found": ("not_found", "Not found.", 404),
}


def _old(refusal: KeyRefused) -> HTTPException:
    code, text, status = OLD_ANSWERS.get(refusal.code, (refusal.public_code, refusal.message, refusal.status))
    return error(code, text, status)


class KeyOut(BaseModel):
    id: int
    name: str
    scope: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    #: The operator blocked it: it answers like none until the operator unblocks it.
    blocked: bool = False


class KeysOut(BaseModel):
    allowed: bool
    keys: list[KeyOut]


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    #: ``read`` (programs that read) or ``upload`` (a scanner or script that brings files in, and reads nothing).
    scope: str = Field(default="read", max_length=8)
    #: 30, 90 or 365; left out: never runs out.
    days: int | None = None


class MadeOut(BaseModel):
    key: KeyOut
    #: Shown once, never again.
    secret: str


def _out(entry: dict) -> KeyOut:
    return KeyOut(id=entry["id"], name=entry["name"] or "", scope=entry["right"], prefix=entry["prefix"],
                  created_at=entry["created_at"], last_used_at=entry["last_used_at"], expires_at=entry["expires_at"],
                  blocked=entry["blocked"])


@router.get("/api-keys", response_model=KeysOut, summary="The own API keys")
def own_keys(account: BrowserAccount, db: DbSession) -> KeysOut:
    listed = keys.listing(SchluesselStore(db), CONFIG, account.id)
    rows = sorted(listed["keys"], key=lambda entry: entry["id"])
    return KeysOut(allowed=bool(listed["api"]), keys=[_out(entry) for entry in rows])


@router.post("/api-keys", response_model=MadeOut, status_code=201, summary="Make an API key; shown once")
def make_key(body: KeyIn, account: BrowserAccount, db: DbSession) -> MadeOut:
    data = SchluesselStore(db)
    if not apikeys.allowed(db):
        raise error("api_off", "The operator has not switched API keys on.", 403)
    try:
        # Left out, ``days`` was never here (the old form); a name of spaces was "API".
        made = keys.make(data, CONFIG, account.id, kind="api", name=body.name.strip()[:100] or "API",
                         right=body.scope, days=body.days)
    except KeyRefused as refusal:
        data.rollback()
        raise _old(refusal) from None
    logger.info("API key made key_id=%s scope=%s days=%s", made.key.id, made.key.right, body.days or "never")
    return MadeOut(key=_out(keys.entry(made.key, CONFIG)), secret=made.secret)


@router.delete("/api-keys/{key_id}", status_code=204, summary="Delete an own API key")
def delete_key(key_id: Annotated[int, Path(ge=1)], account: BrowserAccount, db: DbSession) -> None:
    data = SchluesselStore(db)
    try:
        keys.revoke(data, CONFIG, account.id, key_id)
    except KeyRefused as refusal:
        data.rollback()
        raise _old(refusal) from None
    logger.info("API key deleted key_id=%s", key_id)


# --- The operator ----------------------------------------------------------------------------------------------------


class AnyKeyOut(BaseModel):
    id: int
    account: str
    name: str
    scope: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    blocked: bool = False


def _any(entry: dict) -> AnyKeyOut:
    return AnyKeyOut(id=entry["id"], account=entry["account"]["name"], name=entry["name"] or "",
                     scope=entry["right"], prefix=entry["prefix"], created_at=entry["created_at"],
                     last_used_at=entry["last_used_at"], expires_at=entry["expires_at"], blocked=entry["blocked"])


@router.get("/admin/api-keys", response_model=list[AnyKeyOut], summary="Every API key (operator)")
def every_key(_operator: OperatorAccount, db: DbSession) -> list[AnyKeyOut]:
    rows = keys.overview(SchluesselStore(db), CONFIG)
    return [_any(entry) for entry in sorted(rows, key=lambda entry: (entry["account"]["id"], entry["id"]))]


@router.post("/admin/api-keys/{key_id}/block", response_model=AnyKeyOut,
             summary="Block a key (operator); its account sees it blocked")
def block_key(key_id: Annotated[int, Path(ge=1)], _operator: OperatorAccount, db: DbSession) -> AnyKeyOut:
    data = SchluesselStore(db)
    before = data.key(key_id)
    try:
        entry = keys.block(data, CONFIG, key_id)
    except KeyRefused as refusal:
        data.rollback()
        raise _old(refusal) from None
    if before is not None and before.blocked_at is None:
        logger.info("API key blocked by the operator key_id=%s", key_id)
    return _any(entry)


@router.post("/admin/api-keys/{key_id}/unblock", response_model=AnyKeyOut,
             summary="Unblock a key (operator): it works again")
def unblock_key(key_id: Annotated[int, Path(ge=1)], _operator: OperatorAccount, db: DbSession) -> AnyKeyOut:
    data = SchluesselStore(db)
    before = data.key(key_id)
    try:
        entry = keys.unblock(data, CONFIG, key_id)
    except KeyRefused as refusal:
        data.rollback()
        raise _old(refusal) from None
    if before is not None and before.blocked_at is not None:
        logger.info("API key unblocked by the operator key_id=%s", key_id)
    return _any(entry)
