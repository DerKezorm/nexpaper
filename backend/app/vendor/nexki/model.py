"""What the module reads and writes, and the ``Store`` the app gives it over its own tables. The module has no database:
the app maps every name below to where its value lives today (nexmail ``einstellung`` and ``Benutzer.ki_*``, nexpaper
and nexdiary ``settings`` ``ai_*``, nexlore ``ai_shared_*`` and ``Account.ai_*``), so that no field wanders and every
stored key, model and switch keeps working (plan: "Alte Einstellungen gelten weiter")."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

AccountId = Any

#: The operator's settings, by the names ``Store.setting`` is asked with. ``None`` from the store means "never stored"
#: (what ``settings.adopt`` looks for after an update).
SETTINGS = (
    "enabled",  # bool: the main switch "KI auf diesem Server erlaubt" (K3)
    "mode",  # "shared" | "own" (K2)
    "api",  # "openai" | "messages": the operator's service
    "url",  # its base address, with a slash at the end
    "model",
    "key",  # sealed with AppConfig.operator_key_context; "" when there is none
    "hosts",  # list[str]: hosts in the own network accounts may use for their own service (K4)
    "per_minute",  # int: brakes the operator set (None: the app's default)
    "per_day",
    "server_day",
    "day",  # {"day": "YYYY-MM-DD", "count": n}: today's requests on the server
    "hosts_adopted",  # bool: the hosts of older own accesses were taken onto the list once (K4)
)


@dataclass(frozen=True)
class OwnAccess:
    """An account's own service (mode "own"): the same fields as the operator's. ``key`` is sealed with
    ``AppConfig.account_key_context``."""

    api: str
    url: str
    model: str
    key: str = ""


@dataclass(frozen=True)
class Service:
    """What a request goes out with: the operator's service or an account's own, the key unsealed."""

    api: str
    url: str
    model: str
    key: str
    operator: bool

    @property
    def complete(self) -> bool:
        return bool(self.api and self.url and self.model)


@dataclass(frozen=True)
class Event:
    """One line of "what went out" (K5). ``sent`` is the sealed text of a manual task, "" for an automatic one."""

    account_id: AccountId
    at: datetime
    task: str
    to: str
    model: str
    manual: bool
    chars: int
    outcome: str
    sent: str = ""
    id: Any = None


class Store(Protocol):
    """The app's tables. One object may be this and the ``Store`` of ``schluessel`` and ``mcp`` at once."""

    def setting(self, name: str) -> Any:
        """The operator's setting ``name`` (see ``SETTINGS``), ``None`` when never stored."""
        ...

    def set_setting(self, name: str, value: Any) -> None: ...

    def account_allowed(self, account_id: AccountId) -> bool:
        """"KI erlaubt" of the account (module konten: the right ``ai``; the app's column ``ai_allowed``,
        ``ki_erlaubt``)."""
        ...

    def account_out(self, account_id: AccountId) -> bool:
        """The account is blocked or deleted (module konten): nothing goes out for it."""
        ...

    def person_on(self, account_id: AccountId) -> bool:
        """The person's own switch "KI für mich" (nexpaper, nexdiary profile ``ai``; nexmail ``ki_aktiv``; nexlore
        ``ai_active``)."""
        ...

    def set_person_on(self, account_id: AccountId, on: bool) -> None: ...

    def own_access(self, account_id: AccountId) -> OwnAccess | None:
        """The account's own service, ``None`` when it never set one up."""
        ...

    def set_own_access(self, account_id: AccountId, access: OwnAccess | None) -> None: ...

    def own_access_urls(self) -> list[str]:
        """The addresses of every own access there is (``settings.adopt`` lists their hosts once, K4)."""
        ...

    def seal(self, text: str, context: str) -> str: ...

    def unseal(self, sealed: str, context: str) -> str:
        """The text, or "" when it cannot be unsealed (another secret of the server)."""
        ...

    def add_event(self, event: Event) -> None: ...

    def events(self, account_id: AccountId) -> list[Event]:
        """The account's events, newest first."""
        ...

    def clear_events(self, account_id: AccountId) -> int: ...

    def drop_events(self, before: datetime, *, keep: int) -> int:
        """Events older than ``before``, and of each account all but its newest ``keep``."""
        ...

    def commit(self) -> None: ...
