"""What the module keeps, and the ``Store`` through which the app keeps it in its own tables (a template of the tables
is the reference app's ``SCHEMA``). The module never touches the app's older tables of its connections: it reads them
through ``Store.legacy`` and shows them as they are."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

AccountId = Any
#: An area as the app names it to an account (a space, a calendar, a vault): ``{"id": …, "name": …}``.
Area = dict[str, Any]


@dataclass
class Connection:
    """One connection of one account with one partner app, kept the same way on both sides (``id`` is shared).

    ``uses``: what this app may do at the partner; ``grants``: what the partner may do here. ``held`` is the partner's
    access and refresh token for this app, sealed by the app; ``issued_*`` the hashes of the tokens this app gave the
    partner."""

    id: str
    account_id: AccountId
    partner: str
    partner_base: str
    partner_account: str
    uses: tuple[str, ...]
    grants: tuple[str, ...]
    #: Areas here the partner may reach (``None``: all, also later ones).
    areas_granted: list[Any] | None
    #: The areas the partner let this app reach, as it named them (for the card).
    areas_used: list[Area] | None
    held: str
    issued_access_hash: str
    issued_refresh_hash: str
    issued_access_expires: datetime
    created_at: datetime
    #: When the partner last used or refreshed what it holds (here), and when this app last reached the partner.
    used_at: datetime | None = None
    ok_at: datetime | None = None
    state: str = "connected"
    stale_since: datetime | None = None
    #: The last refusal of the partner as one of the module's codes.
    problem: str | None = None
    partner_version: str = ""


@dataclass(frozen=True)
class Pending:
    """A connection this app started: the account went to the partner's consent page and comes back with a code."""

    state_hash: str
    account_id: AccountId
    partner: str
    partner_base: str
    #: The PKCE verifier, sealed by the app.
    verifier: str
    areas_granted: list[Any] | None
    created_at: datetime


@dataclass(frozen=True)
class Code:
    """A code this app gave on its consent page, for the app that asked."""

    code_hash: str
    account_id: AccountId
    partner: str
    partner_base: str
    redirect_uri: str
    challenge: str
    areas_granted: list[Any] | None
    expires_at: datetime


@dataclass(frozen=True)
class Legacy:
    """A connection the app made before the module, with a key typed in by hand: shown, never changed (alte
    Verbindungen merken nichts). ``shown``: the start of the key (``ntk_AbCd``); ``problem``: one of the module's
    codes (``unreachable``, ``refused``) when the app knows the key is turned down."""

    partner: str
    partner_base: str
    shown: str = ""
    expires_at: datetime | None = None
    ok_at: datetime | None = None
    problem: str | None = None


@dataclass(frozen=True)
class Waiting:
    """A revocation the partner has not heard yet."""

    id: Any
    partner_base: str
    #: The token to bring, sealed by the app.
    token: str
    since: datetime


@dataclass(frozen=True)
class Caller:
    """Who calls the app with a token of a connection: the account it acts as and what the connection allows."""

    account_id: AccountId
    connection_id: str
    partner: str
    purposes: tuple[str, ...]
    areas: list[Any] | None
    #: The highest right among the purposes (``read``, ``write``), ``None`` when the connection grants nothing here.
    level: str | None

    def may(self, purpose: str) -> bool:
        return purpose in self.purposes


class Store(Protocol):
    """The app's tables behind the module. Every method says what the app writes; ``commit`` ends a change."""

    # --- connections ---------------------------------------------------------------------------------------------
    def connections(self, account_id: AccountId) -> list[Connection]: ...
    def connection(self, account_id: AccountId, partner: str) -> Connection | None: ...
    def by_issued_access(self, token_hash: str) -> Connection | None: ...
    def by_issued_refresh(self, token_hash: str) -> Connection | None: ...
    def save(self, connection: Connection) -> None: ...
    def remove(self, connection_id: str) -> None: ...

    # --- started connections and codes (each good once) ----------------------------------------------------------
    def add_pending(self, pending: Pending) -> None: ...
    def take_pending(self, state_hash: str) -> Pending | None: ...
    def add_code(self, code: Code) -> None: ...
    def take_code(self, code_hash: str) -> Code | None: ...

    # --- spent codes and refresh tokens, per connection ----------------------------------------------------------
    def spend(self, connection_id: str, token_hash: str, keep: int) -> None: ...
    def spent_by(self, token_hash: str) -> str | None: ...

    # --- revocations that wait for the partner -------------------------------------------------------------------
    def revoke_later(self, account_id: AccountId, partner_base: str, sealed_token: str, now: datetime) -> None: ...
    def waiting(self) -> list[Waiting]: ...
    def done_waiting(self, waiting_id: Any) -> None: ...

    # --- the account and the app --------------------------------------------------------------------------------
    def account_may(self, account_id: AccountId) -> bool:
        """False while the account is blocked or deleted (its connections rest, E41)."""
        ...

    def account_name(self, account_id: AccountId) -> str: ...
    def areas(self, account_id: AccountId) -> list[Area]: ...
    def legacy(self, account_id: AccountId) -> list[Legacy]: ...
    def retire_key(self, token: str) -> bool:
        """An API key of the app (an older connection's) ends itself; True when there was one."""
        ...

    def setting(self, name: str) -> Any:
        """``connections`` (bool, ``None`` = never set = on), ``addresses`` (partner -> address)."""
        ...

    def set_setting(self, name: str, value: Any) -> None: ...
    def local_allowed(self) -> bool:
        """The operator's switch for connections into the own network (``connections_local_network``)."""
        ...

    def seal(self, text: str) -> str: ...
    def unseal(self, sealed: str) -> str: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
