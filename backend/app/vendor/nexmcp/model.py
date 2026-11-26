"""What the module and the app hand each other: who calls (``Caller``), a program that registered (``Client``), a code
of a consent (``Code``), a program's key (``Program``), a request that waits for the account (``Request``), and the
``Store``: the app's tables behind a few calls. Like ``schluessel``, the module knows no database; every app keeps its
tables and the form of its rows (nexnotes ``api_tokens`` with ``client_id`` and ``oauth_*``, nexlore ``mcp_keys`` and
``mcp_requests``, nextime a new ``mcp_keys``). Only SHA-256 hex of codes and tokens is ever stored."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

AccountId = int | str
KeyId = int | str


@dataclass
class Caller:
    """The account behind a key, as it stands at this request. The app builds it from its own check of the key
    (``nexschluessel.authenticate`` or its older check), never from what the program says."""

    key_id: KeyId
    #: The key's name ("Notebook on the laptop"; a program: its name).
    key_name: str
    account_id: AccountId
    #: The account's name, for logs and "approved by".
    account_name: str
    #: The key's level as stored (the operator's highest level caps it, ``rights.level_of``).
    level: str
    #: The areas the key is limited to; ``None``: all the account may reach. The app's tools check them.
    areas: list[Any] | None = None
    #: The key's extras that are on (``{"mailtext": True}``).
    options: dict[str, bool] = field(default_factory=dict)
    #: The key's own right per tool, only where it differs from the group's default.
    rights: dict[str, str] = field(default_factory=dict)
    #: Issued to a program by OAuth.
    program: bool = False
    #: The account is an operator (tools ``admin_only``).
    admin: bool = False
    #: The operator lets the account use AI (decision 10; apps without "KI erlaubt": always).
    ai_allowed: bool = True
    #: The app's own object for its tools (its account row, detached); the module never reads it.
    account: Any = None


@dataclass(frozen=True)
class Client:
    """A program that registered itself (RFC 7591): public, with PKCE, its name and return addresses."""

    id: str
    name: str
    redirect_uris: tuple[str, ...]
    created_at: datetime
    last_used_at: datetime | None = None
    #: Whether a key of an account came from it (one in use is never pushed out to make room).
    in_use: bool = False


@dataclass(frozen=True)
class Code:
    """A code an account gave a program on the consent page: traded once, within ``code_minutes``."""

    code_hash: str
    client_id: str
    account_id: AccountId
    redirect_uri: str
    challenge: str
    level: str
    areas: list[Any] | None
    options: dict[str, bool]
    expires_at: datetime
    resource: str = ""


@dataclass(frozen=True)
class Grant:
    """What a program gets at a trade or a refresh, for the store to write on its key: the hashes of the new access
    and refresh tokens, the access token's visible start and end."""

    access_hash: str
    access_prefix: str
    access_expires: datetime
    refresh_hash: str


@dataclass(frozen=True)
class Program:
    """A program's key as the token endpoint needs it."""

    key_id: KeyId
    account_id: AccountId
    client_id: str
    #: The last consent (a program signs in again ``refresh_days`` after it).
    signed_in_at: datetime
    #: The last refresh (or the consent): ``idle_days`` after it the program signs in again.
    refreshed_at: datetime


@dataclass(frozen=True)
class Request:
    """A call of a tool set to "ask": its arguments fixed as canonical JSON (and their SHA-256), waiting for the
    account's answer until ``expires_at``."""

    id: int | str
    account_id: AccountId
    key_id: KeyId
    key_name: str
    tool: str
    arguments: str
    digest: str
    #: ``waiting``, ``running``, ``done``, ``failed``, ``declined``, ``expired``.
    status: str
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None = None
    decided_by: str = ""
    #: The tool's answer (``done``) or why it failed, as JSON text.
    result: str | None = None
    #: The tool's one line for the bell (``Tool.describe``), fixed at asking.
    summary: str = ""
    dangerous: bool = False


#: The states of a request.
WAITING, RUNNING, DONE, FAILED, DECLINED, EXPIRED = "waiting", "running", "done", "failed", "declined", "expired"
STATES = (WAITING, RUNNING, DONE, FAILED, DECLINED, EXPIRED)


@runtime_checkable
class Store(Protocol):
    """The app's tables for one request (the app gives one per request; ``commit`` once a result stands)."""

    # --- keys (the app's own check) ------------------------------------------------------------------------------

    def caller(self, token: str) -> Caller | None:
        """The caller behind a presented key or program's access token, by the app's own check (prefix, hash,
        locked, expired, account blocked or deleted, second factor owed, the switch of programs); ``None`` for none.
        A key whose account may not use AI comes back with ``ai_allowed=False`` (the module answers it as resting)."""
        ...

    def caller_of_key(self, key_id: KeyId) -> Caller | None:
        """The caller behind a key as it stands now (for a request its account answers; for the key's rights page),
        with the same checks as ``caller`` but without the token; ``None`` when the key is gone or may not work."""
        ...

    def count_keys(self, account_id: AccountId) -> int:
        """The account's keys and programs as its limit counts them."""
        ...

    def account_may(self, account_id: AccountId) -> bool:
        """Whether the account may sign in now (not blocked, not deleted, no second factor owed)."""
        ...

    def ai_allowed(self, account_id: AccountId) -> bool:
        """Whether the operator lets the account use AI (apps without "KI erlaubt": always ``True``)."""
        ...

    def key_areas(self, account_id: AccountId) -> list[dict[str, Any]]:
        """``[{"id", "name"}]``: what the account may give a key (empty where the app has no areas). Named apart from
        ``schluessel``'s ``areas_of``, so one class may serve both stores."""
        ...

    # --- settings ------------------------------------------------------------------------------------------------

    def mcp_on(self) -> bool:
        """The operator's switch "MCP access" under the app's name and default (schluessel's ``switch("mcp")``)."""
        ...

    def setting(self, name: str) -> Any:
        """The module's settings under the app's names: ``programs`` (bool), ``max_level`` (str),
        ``blocked_tools`` (list of names); ``None`` while never set (the module's default then)."""
        ...

    def set_setting(self, name: str, value: Any) -> None: ...

    def key_rights(self, key_id: KeyId) -> dict[str, str]: ...

    def set_key_rights(self, key_id: KeyId, rights: dict[str, str]) -> None:
        """Only the rights that differ from the group's default (the module passes them so)."""
        ...

    # --- OAuth ---------------------------------------------------------------------------------------------------

    def add_client(self, client: Client) -> None: ...

    def client(self, client_id: str) -> Client | None: ...

    def clients(self) -> list[Client]:
        """Every registered program (for making room: the module removes the ones used longest ago)."""
        ...

    def remove_client(self, client_id: str) -> None: ...

    def touch_client(self, client_id: str, when: datetime) -> None: ...

    def add_code(self, code: Code) -> None: ...

    def take_code(self, code_hash: str) -> Code | None:
        """The code, removed in the same step: two requests bringing it at once get it once."""
        ...

    def program_signed_in(
        self,
        account_id: AccountId,
        client: Client,
        *,
        level: str,
        areas: list[Any] | None,
        options: dict[str, bool],
        grant: Grant,
        now: datetime,
    ) -> KeyId:
        """The account agreed: the program's key (kind ``mcp``, a program) with this level, areas and extras and
        the new tokens. An existing key of the same program and account is updated and keeps its rights per tool;
        ``signed_in_at`` and ``refreshed_at`` become ``now``."""
        ...

    def has_program(self, account_id: AccountId, client_id: str) -> bool:
        """Whether the account has a key of this program already (signing in again replaces it, so it adds none)."""
        ...

    def program_by_refresh(self, refresh_hash: str) -> Program | None: ...

    def program_of_token(self, token_hash: str) -> Program | None:
        """The program whose current access or refresh token has this hash (for revoking it, RFC 7009)."""
        ...

    def program_refreshed(self, key_id: KeyId, grant: Grant, now: datetime) -> None: ...

    def spend(self, key_id: KeyId, token_hash: str, keep: int) -> None:
        """Remember a traded code or refresh token of the program (the last ``keep`` of it)."""
        ...

    def spent_by(self, token_hash: str) -> KeyId | None:
        """The program whose spent code or refresh token this was."""
        ...

    def end_program(self, key_id: KeyId) -> None:
        """The program's key is gone (with what it spent); what it wrote stays."""
        ...

    # --- requests ------------------------------------------------------------------------------------------------

    def add_request(self, request: Request) -> Request:
        """Store it and return it with its id."""
        ...

    def request(self, request_id: int | str) -> Request | None: ...

    def requests_of(self, account_id: AccountId) -> list[Request]:
        """The account's requests, newest first."""
        ...

    def count_waiting(self, account_id: AccountId, key_id: KeyId | None = None) -> int: ...

    def claim(self, request_id: int | str, status: str, *, now: datetime, by: str = "") -> bool:
        """``waiting`` becomes ``status`` in one step; ``False`` when it was not ``waiting`` any more."""
        ...

    def finish(self, request_id: int | str, status: str, result: str | None, now: datetime) -> None: ...

    def expire(self, now: datetime) -> int:
        """Waiting requests past their time become ``expired``; returns how many."""
        ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
