"""nexpaper's side of the shared key module ``vendor/nexschluessel``: its ``AppConfig`` and the ``Store`` over
``api_keys``.

The module makes, lists, changes, revokes, locks and unlocks keys the same in every nex app and checks a presented
one; the rows stay in ``api_keys`` as nexpaper wrote them since 1.0.0 (prefix ``npk_``, SHA-256 hex of the whole key,
``scope`` ``read``/``upload``, ``expires_at``, ``blocked_at``), so every key made so far keeps working. Paired devices
(``npd_``) live in ``devices`` and are no keys of the module. Since mcp 1.1.0 there is a second kind, ``mcp``: MCP keys
made by hand (``npm_``) and the keys of programs that connected themselves, in a table of their own (``mcp_keys``,
``services/mcp_store.py``: an older nexpaper must never take one for an API key); their ids start at
``models_mcp.MCP_KEY_BASE``. Switches: ``api`` (``api_keys_allowed``) and ``mcp`` (``mcp_enabled``), both off from the
start. An account the operator takes AI from makes no MCP key, and its MCP keys and programs rest (MCP decision 10).

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
from ..models_mcp import MCP_KEY_BASE, McpKey, McpSpent, McpToolRight
from ..vendor.nexschluessel import ALL_AREAS, AppConfig, Area, Holder, Key, KeyChange, KeyKind, NewKey
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
        # mcp 1.1.0: MCP keys by hand and the keys of connected programs, limited to vaults where the account wants.
        KeyKind(
            id="mcp",
            prefix="npm_",
            rights=("read", "write"),
            areas=True,
            switch="mcp",
            programs_count=True,
        ),
    ),
    # geraete 0.1.0: the iPhone app and new devices (``services/geraete_store.py`` reads the same settings).
    switches=("api", "mcp", "app", "pairing"),
    programs=True,
    mcp_path="/api/mcp",
    # What a program heard before the module: ``key_invalid`` for a key that does not work, 401 while keys are off.
    error_codes=MappingProxyType({"token_invalid": "key_invalid"}),
    error_status=MappingProxyType({"api_off": 401}),
)

#: The module's switch and nexpaper's setting behind it.
SWITCH_SETTINGS = {"api": "api_keys_allowed", "mcp": "mcp_enabled", "app": "app_enabled",
                   "pairing": "app_pairing_allowed"}


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


def _mcp_key(row: McpKey) -> Key:
    return Key(
        id=row.id,
        account_id=row.account_id,
        kind="mcp",
        name=row.name,
        right=row.level if row.level in ("read", "write") else "read",
        prefix=row.prefix,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        blocked_at=row.blocked_at,
        areas=list(row.vault_ids) if row.vault_ids is not None else None,
        program=row.client_id is not None,
    )


def is_mcp(key_id: object) -> bool:
    """One number names one key of either table: MCP keys count from ``MCP_KEY_BASE``."""
    return isinstance(key_id, int) and key_id >= MCP_KEY_BASE


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

    def _mcp_rows(self, *where: object) -> list[Key]:
        rows = self.db.scalars(select(McpKey).where(*where).order_by(McpKey.id.desc())).all()
        return [_mcp_key(row) for row in rows]

    @staticmethod
    def _newest_first(found: list[Key]) -> list[Key]:
        return sorted(found, key=lambda key: (key.created_at is not None, key.created_at, key.id), reverse=True)

    def keys_of(self, account_id: object) -> list[Key]:
        return self._newest_first(self._rows(ApiKey.account_id == account_id)
                                  + self._mcp_rows(McpKey.account_id == account_id))

    def all_keys(self) -> list[Key]:
        return self._newest_first(self._rows() + self._mcp_rows())

    def key(self, key_id: object) -> Key | None:
        if is_mcp(key_id):
            found = self.db.get(McpKey, key_id)
            return _mcp_key(found) if found is not None else None
        row = self.db.get(ApiKey, key_id)
        return _key(row) if row is not None else None

    def key_by_hash(self, token_hash: str) -> Key | None:
        row = self.db.scalar(select(ApiKey).where(ApiKey.token_hash == token_hash))
        if row is not None:
            return _key(row)
        found = self.db.scalar(select(McpKey).where(McpKey.token_hash == token_hash))
        return _mcp_key(found) if found is not None else None

    def _new_mcp_id(self) -> int:
        """The next number of an MCP key; a number used before (its row gone) leaves nothing behind for the new one."""
        highest = self.db.scalar(select(McpKey.id).order_by(McpKey.id.desc()).limit(1))
        number = max(int(highest or 0), MCP_KEY_BASE - 1) + 1
        self.db.query(McpToolRight).filter(McpToolRight.key_id == number).delete()
        self.db.query(McpSpent).filter(McpSpent.key_id == number).delete()
        return number

    def add_key(self, new: NewKey) -> Key:
        if new.kind == "mcp":
            made = McpKey(id=self._new_mcp_id(), account_id=new.account_id, name=new.name, level=new.right,
                          token_hash=new.token_hash, prefix=new.prefix, created_at=new.created_at,
                          expires_at=new.expires_at, vault_ids=list(new.areas) if new.areas is not None else None,
                          extras=dict(new.options) or None)
            self.db.add(made)
            self.db.flush()
            return _mcp_key(made)
        row = ApiKey(account_id=new.account_id, name=new.name, scope=new.right, token_hash=new.token_hash,
                     prefix=new.prefix, created_at=new.created_at, expires_at=new.expires_at)
        self.db.add(row)
        self.db.flush()
        return _key(row)

    def change_key(self, key_id: object, change: KeyChange) -> Key:
        if is_mcp(key_id):
            found = self.db.get(McpKey, key_id)
            assert found is not None
            if change.name is not None:
                found.name = change.name
            if change.right is not None:
                found.level = change.right
            if change.areas is not None:
                found.vault_ids = None if change.areas == ALL_AREAS else list(change.areas)
            if change.options is not None:
                found.extras = {**(found.extras or {}), **change.options} or None
            self.db.flush()
            return _mcp_key(found)
        row = self.db.get(ApiKey, key_id)
        assert row is not None
        if change.name is not None:
            row.name = change.name
        if change.right is not None:
            row.scope = change.right
        self.db.flush()
        return _key(row)

    def remove_key(self, key_id: object) -> None:
        if is_mcp(key_id):
            self.db.query(McpSpent).filter(McpSpent.key_id == key_id).delete()
            self.db.query(McpToolRight).filter(McpToolRight.key_id == key_id).delete()
            self.db.query(McpKey).filter(McpKey.id == key_id).delete()
            self.db.flush()
            return
        row = self.db.get(ApiKey, key_id)
        if row is not None:
            self.db.delete(row)
            self.db.flush()

    def set_blocked(self, key_id: object, when: datetime | None) -> None:
        row = self.db.get(McpKey, key_id) if is_mcp(key_id) else self.db.get(ApiKey, key_id)
        if row is not None:
            row.blocked_at = when
            self.db.flush()

    def touch(self, key_id: object, when: datetime) -> None:
        row = self.db.get(McpKey, key_id) if is_mcp(key_id) else self.db.get(ApiKey, key_id)
        if row is not None:
            row.last_used_at = when
            self.db.flush()

    def holder(self, account_id: object) -> Holder | None:
        row = self.db.get(Account, account_id)
        if row is None:
            return None
        return Holder(id=row.id, name=row.name, display_name=row.display_name or "", out=out(row))

    def areas_of(self, account_id: object, kind: str) -> list[Area]:
        """An API key reaches what its account reaches; an MCP key may be limited to some of the account's vaults."""
        if kind != "mcp":
            return []
        from . import vaults

        return [Area(id=view.vault.id, name=view.name) for view in vaults.listing(self.db, int(str(account_id)))]

    def ai_allowed(self, account_id: object) -> bool:
        """"KI erlaubt" of the account (Server › Konten › Verwalten): without it the account makes no MCP key and its
        MCP keys and programs rest (MCP decision 10); API keys are not touched."""
        row = self.db.get(Account, account_id)
        return row is not None and bool(row.ai_allowed)

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
    """The dependency of the module's routes: one session per request, with MCP's part (``services/mcp_store.py``)."""
    from .mcp_store import McpStore

    with SessionLocal() as db:
        yield McpStore(db)


def address(request: Request) -> str:
    """The address programs use: the operator's public address, else the one this request came to."""
    with SessionLocal() as db:
        return settings_service.public_url(db) or str(request.base_url).rstrip("/")
