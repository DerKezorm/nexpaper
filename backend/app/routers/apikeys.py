"""API keys through the interface: an account's own (My account, Devices and apps) and every key for the operator.

Only with a signed-in browser: a key or a device token never makes, lists or deletes keys (``BrowserAccount``).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import BrowserAccount, DbSession, OperatorAccount
from ..errors import error
from ..models import Account as AccountRow
from ..models import ApiKey, utcnow
from ..services import apikeys
from ..services.apikeys import KeyProblem

logger = logging.getLogger("nexpaper.api")

router = APIRouter(prefix="/api/v1", tags=["api keys"])


class KeyOut(BaseModel):
    id: int
    name: str
    scope: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    #: The operator blocked it: it answers like none, for good.
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


def _out(row: ApiKey) -> KeyOut:
    return KeyOut(id=row.id, name=row.name, scope=row.scope, prefix=row.prefix, created_at=row.created_at,
                  last_used_at=row.last_used_at, expires_at=row.expires_at, blocked=row.blocked_at is not None)


@router.get("/api-keys", response_model=KeysOut, summary="The own API keys")
def own_keys(account: BrowserAccount, db: DbSession) -> KeysOut:
    rows = db.scalars(select(ApiKey).where(ApiKey.account_id == account.id).order_by(ApiKey.id)).all()
    return KeysOut(allowed=apikeys.allowed(db), keys=[_out(row) for row in rows])


@router.post("/api-keys", response_model=MadeOut, status_code=201, summary="Make an API key; shown once")
def make_key(body: KeyIn, account: BrowserAccount, db: DbSession) -> MadeOut:
    if not apikeys.allowed(db):
        raise error("api_off", "The operator has not switched API keys on.", 403)
    try:
        row, secret = apikeys.make(db, account, body.name, body.scope, body.days)
    except KeyProblem as exc:
        raise error(exc.code, exc.text, exc.status) from exc
    return MadeOut(key=_out(row), secret=secret)


@router.delete("/api-keys/{key_id}", status_code=204, summary="Delete an own API key")
def delete_key(key_id: Annotated[int, Path(ge=1)], account: BrowserAccount, db: DbSession) -> None:
    row = db.get(ApiKey, key_id)
    if row is None or row.account_id != account.id:
        raise error("not_found", "Not found.", 404)
    db.delete(row)
    db.commit()
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


def _any(row: ApiKey, owner: str) -> AnyKeyOut:
    return AnyKeyOut(id=row.id, account=owner, name=row.name, scope=row.scope, prefix=row.prefix,
                     created_at=row.created_at, last_used_at=row.last_used_at, expires_at=row.expires_at,
                     blocked=row.blocked_at is not None)


@router.get("/admin/api-keys", response_model=list[AnyKeyOut], summary="Every API key (operator)")
def every_key(_operator: OperatorAccount, db: DbSession) -> list[AnyKeyOut]:
    names = dict(db.execute(select(AccountRow.id, AccountRow.name)).all())
    rows = db.scalars(select(ApiKey).order_by(ApiKey.account_id, ApiKey.id)).all()
    return [_any(row, names.get(row.account_id, "")) for row in rows]


@router.post("/admin/api-keys/{key_id}/block", response_model=AnyKeyOut,
             summary="Block a key for good (operator); its account sees it blocked")
def block_key(key_id: Annotated[int, Path(ge=1)], _operator: OperatorAccount, db: DbSession) -> AnyKeyOut:
    row = db.get(ApiKey, key_id)
    if row is None:
        raise error("not_found", "Not found.", 404)
    if row.blocked_at is None:
        row.blocked_at = utcnow()
        db.commit()
        logger.info("API key blocked by the operator key_id=%s", key_id)
    owner = db.get(AccountRow, row.account_id)
    return _any(row, owner.name if owner else "")
