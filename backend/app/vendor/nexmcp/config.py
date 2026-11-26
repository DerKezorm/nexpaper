"""What the module needs to know about the app's MCP: its name and version for ``initialize``, the sentence it gives AI
programs (``instructions``), its tools, its levels, the answers its walls gave so far, its OAuth paths and token
prefixes, and the limits. The keys and their rows stay with the app (module ``schluessel``); the module reaches them
through the ``Store`` (``model.py``)."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

#: The groups of tools: they order the list "Rights per tool" and give the hints of ``tools/list``. ``admin`` only for
#: accounts that are operators (nexdeck's ``diagnosis``).
GROUP_READ = "read"
GROUP_DRAFT = "draft"
GROUP_CHANGE = "change"
GROUP_RISKY = "risky"
GROUP_ADMIN = "admin"
GROUPS = (GROUP_READ, GROUP_DRAFT, GROUP_CHANGE, GROUP_RISKY, GROUP_ADMIN)
#: Groups that only look: their tools are allowed or denied, never asked for.
LOOKING = (GROUP_READ, GROUP_ADMIN)

ALLOW = "allow"
ASK = "ask"
DENY = "deny"
RIGHTS = (ALLOW, ASK, DENY)

#: Decision 3: a new key or program may use every tool of its level at once; "ask" and "deny" are set per tool.
DEFAULT_RIGHTS: Mapping[str, str] = MappingProxyType(dict.fromkeys(GROUPS, ALLOW))

#: The MCP protocol versions every app speaks, newest first.
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_APP = re.compile(r"[a-z][a-z0-9-]{1,30}")
_PREFIX = re.compile(r"[a-z][a-z0-9_]{1,14}")
_PATH = re.compile(r"/[A-Za-z0-9/_.-]*")

Run = Callable[[Any, dict[str, Any]], Any | Awaitable[Any]]


@dataclass(frozen=True)
class Tool:
    """One tool of the app. ``run(ctx, args)`` goes through the app's services with ``ctx.caller``'s account and
    returns JSON-able data (or raises ``ToolError`` with the text for the program); it may be ``async``."""

    name: str
    #: ``read``, ``draft``, ``change``, ``risky`` or ``admin`` (``GROUPS``).
    group: str
    #: The level a key needs, one of ``AppConfig.levels``.
    level: str
    #: English, for the program.
    description: str
    #: JSON Schema of the arguments (``type: object``); checked before anything runs (``arguments.check``).
    input_schema: Mapping[str, Any]
    run: Run
    #: The extra of the key the tool needs (nexmail ``mailtext``, nexdiary ``entries``); without it the tool is not
    #: there for the key.
    needs: str | None = None
    #: Calls per minute and key on top of the key's rate, for an expensive tool (nexdiary ``search_entries``).
    per_minute: int | None = None
    #: Only for accounts that are operators (nexdeck ``diagnosis``).
    admin_only: bool = False
    #: ``(ctx, args) -> bool``: this call is dangerous (nexdeck: a button that stops something); then it always waits
    #: for the account's yes, which takes a second click.
    dangerous: Callable[[Any, dict[str, Any]], bool] | None = None
    #: ``(args) -> str``: one line for the bell and the request page ("Delete the event 'Dentist'"); default: none.
    describe: Callable[[dict[str, Any]], str] | None = None
    #: Never denied and never blocked (``request_status``, which the module brings itself).
    always: bool = False

    def __post_init__(self) -> None:
        if not _NAME.fullmatch(self.name):
            raise ValueError(f"tool name {self.name!r}: lower-case letters, digits, underscores")
        if self.group not in GROUPS:
            raise ValueError(f"{self.name}: group {self.group!r} must be one of {GROUPS}")
        if self.input_schema.get("type") != "object":
            raise ValueError(f"{self.name}: the input schema must be an object")
        if self.per_minute is not None and not 1 <= self.per_minute <= 10_000:
            raise ValueError(f"{self.name}: per_minute out of range")

    @property
    def looks_only(self) -> bool:
        return self.group in LOOKING


@dataclass(frozen=True)
class AppConfig:
    """The app's MCP. The defaults are the ones decided for all apps; an app sets what it answered otherwise so far
    (``off_status`` 403 in nexnotes and nextime, ``invalid_code`` ``token_invalid`` in nextime, ``max_body`` 4 MB in
    nexnotes), so that no program notices the move."""

    app_name: str
    #: The app's version (``initialize`` names it).
    version: str
    #: English, one paragraph, ending with the rule that texts of people are data, never instructions.
    instructions: str
    tools: tuple[Tool, ...]
    #: The levels of a key, lowest first (nexnotes ``read``/``write``, nexlore ``read``/``draft``/``write``).
    levels: tuple[str, ...] = ("read", "write")
    #: The highest level a key may have until the operator says otherwise (``None``: the highest of ``levels``).
    max_level: str | None = None
    #: The right per group a new key starts with (decision 3: allow everything of its level).
    default_rights: Mapping[str, str] = DEFAULT_RIGHTS
    #: Tools blocked for every account until the operator says otherwise (nexlore ``delete_space``, ``empty_trash``).
    blocked_by_default: tuple[str, ...] = ()
    #: The extras a key may carry that tools need (``Tool.needs``); offered on the consent page, off from the start.
    extras: tuple[str, ...] = ()

    # --- the endpoint -------------------------------------------------------------------------------------------
    mcp_path: str = "/api/mcp"
    #: Status and code while the operator has MCP switched off (nexnotes, nextime: 403 ``mcp_off``).
    off_status: int = 404
    off_code: str = "not_found"
    #: The code of 401 for a key that is no key (nextime ``token_invalid``).
    invalid_code: str = "key_invalid"
    #: The largest message (nexnotes 4 MB: a note at its limit).
    max_body: int = 1024 * 1024
    #: Requests per minute and key.
    per_minute: int = 240
    #: Wrong keys one sender may bring before it waits.
    free_wrong_keys: int = 20

    # --- OAuth for programs (nexnotes, nexlore ``/api/oauth``; nexdeck ``/api/mcp/oauth``) -----------------------
    #: Whether programs connect themselves (always, decision 6; ``False`` only for a test of the module).
    oauth: bool = True
    oauth_prefix: str = "/api/oauth"
    #: The page of the app where the account agrees (nexnotes, nexlore ``/oauth/authorize``).
    consent_path: str = "/oauth/authorize"
    #: The prefix of a program's access token: the prefix of the app's MCP keys (nexnotes ``nn_mcp_``, nexlore
    #: ``nxl_``, nextime ``nt_mcp_``), so the app's check of keys knows it.
    access_prefix: str = "mcp_"
    #: The prefix of its refresh token (``nnr_``, ``nxr_``, ``ntr_``) and of a code.
    refresh_prefix: str = "mcpr_"
    code_prefix: str = "mcpc_"
    access_hours: int = 1
    #: Decision 7: a program signs in again after 90 days, and after 30 days without a refresh.
    refresh_days: int = 90
    idle_days: int = 30
    code_minutes: int = 10
    #: Spent codes and refresh tokens remembered per program, to know a copy when it is brought again.
    spent_kept: int = 20
    max_clients: int = 500
    register_per_minute: int = 30
    register_per_sender: int = 10
    #: Keys and programs an account may hold (a new program counts; the module ``schluessel`` counts the same).
    max_keys: int = 20

    # --- requests (the right "ask") ------------------------------------------------------------------------------
    #: Decision 4: a request waits 24 hours (nexdeck keeps 10 minutes).
    request_minutes: int = 24 * 60
    max_waiting: int = 20
    max_waiting_per_key: int = 10
    max_request_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if not _APP.fullmatch(self.app_name):
            raise ValueError(f"app_name {self.app_name!r}: lower-case letters, digits and dashes")
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("every tool once")
        if "request_status" in names:
            raise ValueError("request_status is the module's own tool")
        if not self.levels or len(self.levels) != len(set(self.levels)):
            raise ValueError("levels: at least one, each once")
        for name in self.levels:
            if not _NAME.fullmatch(name):
                raise ValueError(f"level {name!r}")
        if self.max_level is not None and self.max_level not in self.levels:
            raise ValueError(f"max_level {self.max_level!r} must be one of {self.levels}")
        for tool in self.tools:
            if tool.level not in self.levels:
                raise ValueError(f"{tool.name}: level {tool.level!r} must be one of {self.levels}")
            if tool.needs is not None and tool.needs not in self.extras:
                raise ValueError(f"{tool.name}: needs {tool.needs!r}, not among the extras {self.extras}")
        for group, right in self.default_rights.items():
            if group not in GROUPS or right not in RIGHTS:
                raise ValueError(f"default right {group!r}: {right!r}")
        for name in self.blocked_by_default:
            if name not in names:
                raise ValueError(f"blocked_by_default names {name!r}, no tool of the app")
        for name in self.extras:
            if not _NAME.fullmatch(name):
                raise ValueError(f"extra {name!r}")
        for prefix in (self.access_prefix, self.refresh_prefix, self.code_prefix):
            if not _PREFIX.fullmatch(prefix):
                raise ValueError(f"prefix {prefix!r}")
        if len({self.access_prefix, self.refresh_prefix, self.code_prefix}) != 3:
            raise ValueError("access, refresh and code prefixes must differ")
        for path in (self.mcp_path, self.oauth_prefix, self.consent_path):
            if not _PATH.fullmatch(path) or path.endswith("/"):
                raise ValueError(f"path {path!r}")
        if self.off_status not in (403, 404):
            raise ValueError("off_status: 403 or 404")
        if not 1024 <= self.max_body <= 64 * 1024 * 1024 or not 1 <= self.per_minute <= 100_000:
            raise ValueError("limits out of range")
        if not 1 <= self.request_minutes <= 7 * 24 * 60 or not 1 <= self.max_waiting_per_key <= self.max_waiting:
            raise ValueError("request limits out of range")
        if not 1 <= self.idle_days <= self.refresh_days <= 3650 or not 1 <= self.access_hours <= 24:
            raise ValueError("token lifetimes out of range")

    @property
    def highest(self) -> str:
        return self.max_level or self.levels[-1]

    def tool(self, name: object) -> Tool | None:
        return next((tool for tool in all_tools(self) if tool.name == name), None)

    def at_least(self, level: str, need: str) -> bool:
        """Whether ``level`` reaches ``need`` on the app's ladder (an unknown level reaches nothing)."""
        if level not in self.levels or need not in self.levels:
            return False
        return self.levels.index(level) >= self.levels.index(need)


def all_tools(config: AppConfig) -> tuple[Tool, ...]:
    """The app's tools and the module's ``request_status``."""
    from .requests import STATUS_TOOL  # noqa: PLC0415 (requests imports this module)

    return (*config.tools, STATUS_TOOL(config))
