"""What an app tells the module about itself (``AppConfig``), and the places that are the same in every app.

The places are fixed (one form for all apps, so that an app finds every other without asking): the description of
the app at ``/.well-known/nex-app``, the module's routes under ``/api/connect``, the consent page at ``/connect/app``
and the page the browser comes back to at ``/connect/return``. An app's older routes for its connections stay where
they are; these are new."""

from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import CATALOG, Catalog

WELL_KNOWN = "/.well-known/nex-app"
PREFIX = "/api/connect"
CONSENT_PAGE = "/connect/app"
RETURN_PAGE = "/connect/return"
#: The form of the description and of the exchange; an app without the description is "too old".
PROTOCOL = 1

#: The states of a connection as the card shows them.
STATES = ("connected", "unreachable", "refused", "resting", "off")


@dataclass(frozen=True)
class AppConfig:
    #: The app's name, one of ``catalog.APPS`` (``nextasks``).
    app_name: str
    #: The app's version, named in its description (``1.4.0``).
    version: str
    #: The start of the tokens this app gives its partners: access, refresh and code (``ntc_``, ``ntcr_``,
    #: ``ntcc_``). The app's own and never one of its API keys', so that its log blackens them and a key check never
    #: mistakes one for a key.
    access_prefix: str
    refresh_prefix: str
    code_prefix: str
    catalog: Catalog = CATALOG
    #: How long an access token lasts; the holder refreshes it on its own.
    access_hours: int = 1
    #: Decision V1 (2a): a connection holds until it is ended, and rests after this many days without any use.
    idle_days: int = 180
    #: A code and a started connection hold this long, and are good once.
    code_minutes: int = 10
    #: Every request to a partner ends after this (the description of a partner: ``describe_seconds``).
    seconds: float = 10.0
    describe_seconds: float = 3.0
    connect_seconds: float = 3.0
    #: The largest answer of a partner read.
    max_answer: int = 2_000_000
    #: Decision V1 (4a): an older connection by API key shows "läuft ab" this many days before its key ends.
    expiring_days: int = 7
    #: Connections started and checks by hand, per account and minute.
    starts_per_minute: int = 5
    #: How many spent refresh tokens per connection are recognised when brought again.
    spent_kept: int = 20
    #: A revocation that did not reach the partner is tried again for this long.
    revoke_days: int = 30
    #: The words the app sends as ``User-Agent``.
    agent: str = field(default="")

    def __post_init__(self) -> None:
        if self.app_name not in self.catalog.purposes:
            raise ValueError(f"{self.app_name} is not in the catalog of nex apps")
        prefixes = {self.access_prefix, self.refresh_prefix, self.code_prefix}
        if len(prefixes) != 3 or not all(prefix.endswith("_") and len(prefix) >= 3 for prefix in prefixes):
            raise ValueError("access, refresh and code need three different prefixes ending in _")

    @property
    def partners(self) -> list[str]:
        return self.catalog.partners(self.app_name)

    @property
    def user_agent(self) -> str:
        return self.agent or f"{self.app_name}/{self.version}"
