"""What the module and the app hand each other: a key as the module sees it (never its secret, never its hash), the
account that holds it, the areas a key may be limited to, a new key for the app to store, and the ``Store``: the
app's tables behind a few calls. Every app keeps its own tables and the form of its rows (nexnotes ``api_tokens`` with
a column ``kind``, nextime ``api_keys``, nexmail ``api_schluessel``, nexdiary with the name sealed); the store
translates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

AccountId = int | str
KeyId = int | str
AreaId = int | str


@dataclass(frozen=True)
class Area:
    """A folder, a space, a calendar, a mailbox the account may give a key."""

    id: AreaId
    name: str


@dataclass
class Key:
    """One key as the app holds it, without its secret or its hash."""

    id: KeyId
    account_id: AccountId
    #: ``api`` or ``mcp`` (the module's kinds).
    kind: str
    #: The name the account gave it; ``None`` where the operator may not read it (nexdiary seals names with the
    #: owner's key).
    name: str | None
    #: The right as the app names it (``read``, ``write``, ``upload``, ``count``, ``draft`` …).
    right: str
    #: The visible start: prefix plus a few characters (``ntk_AbCd``).
    prefix: str
    created_at: datetime | None = None
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    #: Locked by the operator: the key is refused until unlocked.
    blocked_at: datetime | None = None
    #: The areas the key is limited to; ``None``: all the account may reach, later ones too.
    areas: list[AreaId] | None = None
    #: The extras that are on (``{"mcp": True}``; nexmail ``tasks``, ``tags``).
    options: dict[str, bool] = field(default_factory=dict)
    #: A form of key no longer made, still valid (nexnotes ``card``: only the nexdeck card); ``None`` for today's.
    legacy: str | None = None
    #: Issued to a program that connected itself by OAuth with the account's consent (an AI tool).
    program: bool = False


@dataclass(frozen=True)
class Holder:
    """The account behind a key, for the operator's overview and the check of a key."""

    id: AccountId
    #: The username.
    name: str
    #: The name others see; empty: the username.
    display_name: str = ""
    #: Blocked or deleted: none of its keys works.
    out: bool = False


@dataclass(frozen=True)
class NewKey:
    """A key the module made, for the app to store. ``token_hash`` is the SHA-256 of the whole key (prefix included)
    in hex, the form every app stores; the secret itself never reaches the store."""

    account_id: AccountId
    kind: str
    name: str
    right: str
    token_hash: str
    prefix: str
    created_at: datetime
    expires_at: datetime | None
    areas: list[AreaId] | None
    options: dict[str, bool]
    #: The form's reference against a double click (nextime ``client_ref``), or ``None``.
    client_ref: str | None = None


@dataclass(frozen=True)
class KeyChange:
    """What an account changes on a key of its own (name, right, areas, extras); ``None`` leaves a part as it is."""

    name: str | None = None
    right: str | None = None
    #: ``ALL_AREAS`` for "all, later ones too"; a list for some.
    areas: list[AreaId] | str | None = None
    options: dict[str, bool] | None = None


#: In a ``KeyChange``: the key reaches every area of the account, later ones too.
ALL_AREAS = "all"


@runtime_checkable
class Store(Protocol):
    """The app's tables. One transaction per request: the module calls ``commit()`` once a result stands. Rows of
    paired devices are never keys of the module (nexnotes keeps them in the same table: the store leaves them out)."""

    def keys_of(self, account_id: AccountId) -> list[Key]:
        """Every key of the account, of every kind, programs (OAuth) included, newest first."""
        ...

    def all_keys(self) -> list[Key]:
        """Every key of every account, for the operator."""
        ...

    def key(self, key_id: KeyId) -> Key | None: ...

    def key_by_hash(self, token_hash: str) -> Key | None:
        """The key whose stored hash is ``token_hash`` (SHA-256 hex of the presented key)."""
        ...

    def add_key(self, new: NewKey) -> Key:
        """Store a new key as the app stores keys (its table, its columns, a sealed name where the app seals)."""
        ...

    def change_key(self, key_id: KeyId, change: KeyChange) -> Key: ...

    def remove_key(self, key_id: KeyId) -> None:
        """Revoke: the key is gone (every app deletes the row; nexlore's programs with it)."""
        ...

    def set_blocked(self, key_id: KeyId, when: datetime | None) -> None:
        """The operator locks (``when``) or unlocks (``None``) a key."""
        ...

    def touch(self, key_id: KeyId, when: datetime) -> None:
        """Note ``last used``."""
        ...

    def holder(self, account_id: AccountId) -> Holder | None: ...

    def areas_of(self, account_id: AccountId, kind: str) -> list[Area]:
        """The areas the account may give a key of ``kind`` (what it may read itself), in the app's order."""
        ...

    def keys_wait(self, account_id: AccountId) -> bool:
        """Whether the account's keys rest until it sets up a second factor of its own (the operator requires one,
        the account signs in with a password and has none; a provider's check of the session does not count for a
        key). The app's own rule (``totp.setup_required`` without the session)."""
        ...

    def switch(self, name: str) -> bool:
        """The operator's switch ``api``, ``mcp`` (and ``app``, ``pairing`` where the app has them), from the app's
        settings under its own name and default (nexnotes ``api_enabled``, nextasks ``api_tokens_allowed`` …)."""
        ...

    def set_switch(self, name: str, on: bool) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class ClientRefStore(Protocol):
    """Optional: a store that finds a key by the form's reference (nextime), so a double click makes one key."""

    def key_by_client_ref(self, account_id: AccountId, client_ref: str) -> Key | None: ...


class RightsStore(Protocol):
    """Optional: a store that narrows the rights a new key may get (nexlore: the operator's "highest level of a key"
    for MCP keys). Returns a part of the kind's rights."""

    def rights_allowed(self, account_id: AccountId, kind: str) -> tuple[str, ...]: ...
