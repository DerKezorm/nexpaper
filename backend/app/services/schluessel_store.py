"""nexpaper's side of the shared key module ``vendor/nexschluessel``: its ``AppConfig`` and the ``Store`` over
``api_keys``.

The module makes, lists, changes, revokes, locks and unlocks keys the same in every nex app and checks a presented
one; the rows stay in ``api_keys`` as nexpaper wrote them since 1.0.0 (prefix ``npk_``, SHA-256 hex of the whole key,
``scope`` ``read``/``upload``, ``expires_at``, ``blocked_at``), so every key made so far keeps working. Paired devices
(``npd_``) live in ``devices`` and are no keys of the module. nexpaper has no MCP and no switch of its own for the
iPhone app: the only switch is ``api`` (``api_keys_allowed``, off from the start).

What stays nexpaper's own: the walls of ``/api/v1`` (no ``Origin``, the brake per sender, ``PER_MINUTE``, the upload
limit per hour, ``key_scope``; ``services/apikeys.py``, ``deps.py``, ``routers/v1.py``) and the old routes under
``/api/v1/api-keys`` and ``/api/v1/admin/api-keys`` in their old shapes (``routers/apikeys.py``).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from types import MappingProxyType

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Account, ApiKey, utcnow
from ..vendor.nexschluessel import AppConfig, Area, Holder, Key, KeyChange, KeyKind, NewKey
from . import settings_service, totp

#: nexpaper's keys: ``npk_``, ``read`` (a dashboard card, a script) or ``upload`` (the iPhone shortcut, a scanner),
#: 30, 90 or 365 days or never; the form starts with a year for reading and never for uploading (a shortcut that stops
#: after a year is a worse surprise than a key that can only put documents into its owner's inbox).
CONFIG = AppConfig(
    app_name="nexpaper",
    kinds=(
        KeyKind(
            id="api",
            prefix="npk_",
            rights=("read", "upload"),
            default_days=365,
            default_days_by_right=MappingProxyType({"upload": None}),
        ),
    ),
    switches=("api",),
    # What a program heard before the module: ``key_invalid`` for a key that does not work, 401 while keys are off.
    error_codes=MappingProxyType({"token_invalid": "key_invalid"}),
    error_status=MappingProxyType({"api_off": 401}),
)

#: The module's switch and nexpaper's setting behind it.
SWITCH_SETTINGS = {"api": "api_keys_allowed"}


def _key(row: ApiKey) -> Key:
    return Key(
        id=row.id,
        account_id=row.account_id,
        kind="api",
        name=row.name,
        # A scope nexpaper does not know (none was ever written) reads, as ``apikeys.authenticate`` always took it.
        right=row.scope if row.scope in ("read", "upload") else "read",
        prefix=row.prefix,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        blocked_at=row.blocked_at,
    )


def out(row: Account | None, now: datetime | None = None) -> bool:
    """None of the account's keys works: it is blocked, locked for a while, or deleted (waiting to be purged)."""
    if row is None:
        return True
    moment = now or utcnow()
    return (
        row.blocked_at is not None
        or (row.locked_until is not None and row.locked_until > moment)
        or getattr(row, "deleted_at", None) is not None
    )


class SchluesselStore:
    """The module's ``Store`` inside one SQLAlchemy session (one request)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _rows(self, *where: object) -> list[Key]:
        rows = self.db.scalars(select(ApiKey).where(*where).order_by(ApiKey.id.desc())).all()
        return [_key(row) for row in rows]

    def keys_of(self, account_id: object) -> list[Key]:
        return self._rows(ApiKey.account_id == account_id)

    def all_keys(self) -> list[Key]:
        return self._rows()

    def key(self, key_id: object) -> Key | None:
        row = self.db.get(ApiKey, key_id)
        return _key(row) if row is not None else None

    def key_by_hash(self, token_hash: str) -> Key | None:
        row = self.db.scalar(select(ApiKey).where(ApiKey.token_hash == token_hash))
        return _key(row) if row is not None else None

    def add_key(self, new: NewKey) -> Key:
        row = ApiKey(account_id=new.account_id, name=new.name, scope=new.right, token_hash=new.token_hash,
                     prefix=new.prefix, created_at=new.created_at, expires_at=new.expires_at)
        self.db.add(row)
        self.db.flush()
        return _key(row)

    def change_key(self, key_id: object, change: KeyChange) -> Key:
        row = self.db.get(ApiKey, key_id)
        assert row is not None
        if change.name is not None:
            row.name = change.name
        if change.right is not None:
            row.scope = change.right
        self.db.flush()
        return _key(row)

    def remove_key(self, key_id: object) -> None:
        row = self.db.get(ApiKey, key_id)
        if row is not None:
            self.db.delete(row)
            self.db.flush()

    def set_blocked(self, key_id: object, when: datetime | None) -> None:
        row = self.db.get(ApiKey, key_id)
        if row is not None:
            row.blocked_at = when
            self.db.flush()

    def touch(self, key_id: object, when: datetime) -> None:
        row = self.db.get(ApiKey, key_id)
        if row is not None:
            row.last_used_at = when
            self.db.flush()

    def holder(self, account_id: object) -> Holder | None:
        row = self.db.get(Account, account_id)
        if row is None:
            return None
        return Holder(id=row.id, name=row.name, display_name=row.display_name or "", out=out(row))

    def areas_of(self, account_id: object, kind: str) -> list[Area]:
        # A key of nexpaper reaches what its account reaches; it is never limited to some vaults.
        return []

    def keys_wait(self, account_id: object) -> bool:
        row = self.db.get(Account, account_id)
        return row is not None and totp.keys_wait(self.db, row)

    def switch(self, name: str) -> bool:
        return bool(settings_service.get(self.db, SWITCH_SETTINGS[name]))

    def set_switch(self, name: str, on: bool) -> None:
        settings_service.save(self.db, {SWITCH_SETTINGS[name]: bool(on)}, commit=False)

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()


def store() -> Iterator[SchluesselStore]:
    """The dependency of the module's routes: one session per request."""
    with SessionLocal() as db:
        yield SchluesselStore(db)


def address(request: Request) -> str:
    """The address programs use: the operator's public address, else the one this request came to."""
    with SessionLocal() as db:
        return settings_service.public_url(db) or str(request.base_url).rstrip("/")
