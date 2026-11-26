"""What the module needs to know about the app's keys: which kinds it has (API keys, MCP keys), the prefix of new ones
and the prefixes that stay valid, the rights and the extras the app offers, whether a key is limited to some of the
account's areas (folders, spaces, calendars, mailboxes), the lifetimes the app knows, its limits, and which switches of
the operator it has. The rows themselves stay in the app's tables; the module reaches them through the ``Store``
(``model.py``)."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from types import MappingProxyType
from typing import Any

#: The kinds of the module: keys for the programming interface, keys for AI tools (MCP).
KIND_API = "api"
KIND_MCP = "mcp"
KINDS = (KIND_API, KIND_MCP)

#: The operator's switches of the card "Interfaces". ``app`` and ``pairing`` are places the app fills (its iPhone app).
SWITCH_API = "api"
SWITCH_MCP = "mcp"
SWITCH_APP = "app"
SWITCH_PAIRING = "pairing"
SWITCHES = (SWITCH_API, SWITCH_MCP, SWITCH_APP, SWITCH_PAIRING)

#: Rights the module has words for; an app may name others (nexmail ``count``/``headers``, nexlore ``draft``) and
#: brings their words to the card.
RIGHT_READ = "read"
RIGHT_WRITE = "write"
RIGHT_UPLOAD = "upload"

#: The extra every app with MCP may offer on an API key: the key also opens ``/api/mcp`` (nexnotes, nextime).
OPTION_MCP = "mcp"

#: The lifetimes of nexnotes, nextasks, nextime, nexpaper, nexdiary, nexlore (``None``: never runs out).
DEFAULT_EXPIRY_DAYS: tuple[int | None, ...] = (30, 90, 365, None)

_PREFIX = re.compile(r"[a-z][a-z0-9_]{1,14}")
_APP_NAME = re.compile(r"[a-z][a-z0-9-]{1,30}")
_ID = re.compile(r"[a-z][a-z0-9_]{0,31}")


@dataclass(frozen=True)
class KeyKind:
    """One kind of key of the app, with its rules. The prefix is the app's (``ntk_``); a key made before keeps working
    under every prefix in ``accepted``."""

    #: ``api`` or ``mcp`` (``KINDS``).
    id: str
    #: The prefix of a new key (``ntk_``, ``nn_api_``, ``nxm_``). Never changed: every key made so far starts with it.
    prefix: str
    #: More prefixes keys of this kind may have from older versions (nexnotes ``nn_deck_`` for the nexdeck card).
    accepted: tuple[str, ...] = ()
    #: The rights the app offers, in the order of the form (``read``, ``write``; nexpaper ``read``, ``upload``; nexmail
    #: ``count``, ``headers``; nexdiary ``read`` alone).
    rights: tuple[str, ...] = (RIGHT_READ, RIGHT_WRITE)
    #: The right the form starts with.
    default_right: str = RIGHT_READ
    #: Extras to tick (``mcp``; nexmail ``tasks``, ``tags``), each on or off.
    options: tuple[str, ...] = ()
    #: Whether a key is limited to some of the account's areas (folders, spaces, calendars, mailboxes).
    areas: bool = False
    #: Only with ``areas``: a key must name its areas, "all" is not offered (nexmail's mailboxes).
    areas_required: bool = False
    #: The lifetimes in days the form offers (``None`` in it: never); ``None`` instead of a tuple: the app knows no end
    #: of a key (nexmail) and the form asks nothing.
    expiry_days: tuple[int | None, ...] | None = DEFAULT_EXPIRY_DAYS
    #: The lifetime the form starts with.
    default_days: int | None = 90
    #: A lifetime per right, where the app starts differently (nexpaper: ``read`` 365, ``upload`` never).
    default_days_by_right: Mapping[str, int | None] = field(default_factory=lambda: MappingProxyType({}))
    #: Keys an account may hold of this kind (with the kinds in ``counted_with``).
    max_keys: int = 20
    #: Other kinds that count toward ``max_keys`` (nexnotes counts its old card keys with the API keys).
    counted_with: tuple[str, ...] = ()
    #: Whether keys a program got by OAuth (connected AI tools) count toward ``max_keys`` (nexlore: yes).
    programs_count: bool = False
    #: The longest name.
    name_max: int = 100
    #: How many characters after the prefix the list shows (nexmail 6, all others 4).
    shown_extra: int = 4
    #: Random bytes of a new key (``secrets.token_urlsafe``): 32 everywhere.
    secret_bytes: int = 32
    #: A presented key longer than this is refused before any lookup.
    max_length: int = 200
    #: Whether a member may make new keys of this kind here (nexnotes makes no MCP keys by hand any more: it has the
    #: extra ``mcp`` on an API key and the connected programs).
    creatable: bool = True
    #: Whether name, right, areas and extras can be changed afterwards.
    editable: bool = True
    #: The operator's switch that opens and closes this kind (``api``, ``mcp``).
    switch: str = SWITCH_API

    def __post_init__(self) -> None:
        if self.id not in KINDS:
            raise ValueError(f"kind {self.id!r} must be one of {KINDS}")
        for prefix in (self.prefix, *self.accepted):
            if not _PREFIX.fullmatch(prefix):
                raise ValueError(f"prefix {prefix!r} must be lower-case letters, digits and underscores")
        if not self.rights or self.default_right not in self.rights:
            raise ValueError(f"{self.id}: default_right {self.default_right!r} must be one of {self.rights}")
        for name in (*self.rights, *self.options):
            if not _ID.fullmatch(name):
                raise ValueError(f"{self.id}: {name!r} is no name for a right or an extra")
        if self.areas_required and not self.areas:
            raise ValueError(f"{self.id}: areas_required needs areas")
        if self.expiry_days is not None:
            if not self.expiry_days or self.default_days not in self.expiry_days:
                raise ValueError(f"{self.id}: default_days {self.default_days!r} must be one of {self.expiry_days}")
            for right, days in self.default_days_by_right.items():
                if right not in self.rights or days not in self.expiry_days:
                    raise ValueError(f"{self.id}: default_days_by_right {right!r}: {days!r}")
        if self.switch not in (SWITCH_API, SWITCH_MCP):
            raise ValueError(f"{self.id}: switch {self.switch!r} must be api or mcp")
        if not 1 <= self.max_keys <= 1000 or not 1 <= self.name_max <= 400 or not 0 <= self.shown_extra <= 12:
            raise ValueError(f"{self.id}: limits out of range")
        if not 16 <= self.secret_bytes <= 64:
            raise ValueError(f"{self.id}: secret_bytes out of range")

    @property
    def prefixes(self) -> tuple[str, ...]:
        """Every prefix a key of this kind may have: the one of new keys first."""
        return (self.prefix, *self.accepted)

    def days_for(self, right: str) -> int | None:
        """The lifetime the form starts with for ``right``."""
        if self.expiry_days is None:
            return None
        return self.default_days_by_right.get(right, self.default_days)


@dataclass(frozen=True)
class AppConfig:
    """The app's keys. ``kinds`` holds its API keys and, where it has MCP, its MCP keys."""

    #: ``nexnotes``: named on the cards ("… mit nexnotes").
    app_name: str
    kinds: tuple[KeyKind, ...]
    #: The operator's switches the app has (``api``; with MCP ``mcp``; with an iPhone app ``app``, ``pairing``).
    switches: tuple[str, ...] = (SWITCH_API,)
    #: Whether AI tools connect by OAuth with the account's consent (nexnotes, nexlore): the card lists them.
    programs: bool = False
    #: Where programs reach the interface and AI tools reach MCP, after the public address (``/api/v1``, ``/api/mcp``;
    #: ``None``: the app has no MCP endpoint).
    api_path: str = "/api/v1"
    mcp_path: str | None = None
    #: How often ``last used`` is written at most.
    used_every: timedelta = timedelta(minutes=1)
    #: How many days before its end a key is marked.
    warn_days: int = 7
    #: The type of a key's id in the app (nexmail: ``str``).
    key_id: type = int
    #: The app's own codes for the module's refusals, where its answers had others (nextime ``keys_too_many``).
    error_codes: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    #: The app's own status for a refusal, where it answered otherwise (nextasks ``api_off`` on use: 401).
    error_status: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    #: Since E36: the values of the app's own columns in "API-Schlüssel aller Konten" (nexnotes: the number of folders
    #: a key reaches), ``(store, key) -> {column: value}``; they go into each row of the operator's list as ``extra``,
    #: the card shows them through its ``extra`` columns. ``None``: no columns of the app.
    admin_extra: Callable[[Any, Any], Mapping[str, Any]] | None = None

    def __post_init__(self) -> None:
        if not _APP_NAME.fullmatch(self.app_name):
            raise ValueError(f"app_name {self.app_name!r} must be lower-case letters, digits and dashes")
        ids = [kind.id for kind in self.kinds]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("kinds must name each kind once")
        prefixes = [prefix for kind in self.kinds for prefix in kind.prefixes]
        if len(prefixes) != len(set(prefixes)):
            raise ValueError("a prefix may belong to one kind only")
        for one in prefixes:
            for other in prefixes:
                if one != other and other.startswith(one):
                    raise ValueError(f"prefix {other!r} starts with {one!r}: a key could not tell its kind")
        for switch in self.switches:
            if switch not in SWITCHES:
                raise ValueError(f"switch {switch!r} must be one of {SWITCHES}")
        if SWITCH_API not in self.switches:
            raise ValueError("every app has the switch api")
        for kind in self.kinds:
            if kind.switch not in self.switches:
                raise ValueError(f"{kind.id}: its switch {kind.switch!r} is not among the app's switches")
            if OPTION_MCP in kind.options and SWITCH_MCP not in self.switches:
                raise ValueError(f"{kind.id}: the extra mcp needs the switch mcp")
            for other in kind.counted_with:
                if other not in ids:
                    raise ValueError(f"{kind.id}: counted_with names {other!r}, no kind of the app")
        if (KIND_MCP in ids or self.programs) and SWITCH_MCP not in self.switches:
            raise ValueError("MCP keys and connected programs need the switch mcp")
        if self.key_id not in (int, str):
            raise ValueError("key_id must be int or str")

    def kind(self, kind_id: str) -> KeyKind | None:
        return next((kind for kind in self.kinds if kind.id == kind_id), None)

    def kind_of(self, token: str) -> KeyKind | None:
        """The kind a presented key belongs to by its prefix."""
        return next((kind for kind in self.kinds if any(token.startswith(prefix) for prefix in kind.prefixes)), None)

    @property
    def has_mcp(self) -> bool:
        return SWITCH_MCP in self.switches

    def public_code(self, code: str) -> str:
        return self.error_codes.get(code, code)
