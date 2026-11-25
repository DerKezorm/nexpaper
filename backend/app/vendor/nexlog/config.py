"""What the module needs to know about the app: its name, where its log lives, the value of its environment variable,
which clock its lines are written in, what to black out on top of the common rules, and which loggers of its own and of
its libraries to tame. Everything else (the level stored in the database, who is an operator) comes in later through
``attach_store`` and the router."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_APP_NAME = re.compile(r"[a-z][a-z0-9-]{1,30}")


@dataclass(frozen=True)
class AppConfig:
    #: ``nexnotes``: the logger of the app (``nexnotes``, ``nexnotes.api`` …), the file (``nexnotes.log``) and the
    #: name of a download (``nexnotes-log-2026-11-25.txt``).
    app_name: str
    #: The folder of the files (``<data>/logs``), or a function that names it (read at every use: tests move it).
    log_dir: Path | Callable[[], Path]
    #: The value of the app's environment variable (``NEXNOTES_LOG_LEVEL``), or a function that reads it. A mode or an
    #: alias fixes the level; empty leaves it to the operator.
    env_level: str | Callable[[], str] = ""
    #: The name of that variable, for the refusal of a change (default ``<APP>_LOG_LEVEL``; nexmail
    #: ``NEXMAIL_LOG_STUFE``).
    env_name: str = ""
    #: The clock of the lines: False the server's local clock (nexnotes and most apps), True UTC (nexmail). Lines
    #: already written keep their meaning only when this stays what the app had.
    utc: bool = False
    #: Prefixes of the app's keys and tokens (``ntk_``, ``nxa_``): what follows them never reaches the log.
    key_prefixes: tuple[str, ...] = ()
    #: Path segments followed by a token (``invite``, ``abo``, ``mail-senders/confirm``), on top of the common ones.
    token_paths: tuple[str, ...] = ()
    #: Query parameters that carry a token, on top of the common ones (``invite``).
    query_keys: tuple[str, ...] = ()
    #: More rules as (pattern, replacement), applied after the common ones (nexmail keeps its own exactly so).
    redactions: tuple[tuple[str, str], ...] = ()
    #: Libraries that follow the level of the libraries (``imapclient``), on top of the common noisy ones.
    noisy_loggers: tuple[str, ...] = ()
    #: Loggers held at WARNING whatever the level (``caldav``, ``PIL``), on top of the common silent ones.
    silent_loggers: tuple[str, ...] = ()
    #: Called with the folder of the files once it exists (nexnotes makes it private); None: nothing.
    tighten: Callable[[Path], None] | None = None

    def __post_init__(self) -> None:
        if not _APP_NAME.fullmatch(self.app_name):
            raise ValueError(f"app_name {self.app_name!r} must be lower-case letters, digits and dashes")
        for pattern, _replacement in self.redactions:
            re.compile(pattern)

    @property
    def variable(self) -> str:
        return self.env_name or f"{self.app_name.upper().replace('-', '_')}_LOG_LEVEL"

    def folder(self) -> Path:
        return Path(self.log_dir() if callable(self.log_dir) else self.log_dir)

    def environment(self) -> str:
        value = self.env_level() if callable(self.env_level) else self.env_level
        return (value or "").strip()


_current: AppConfig | None = None


def configure(config: AppConfig) -> None:
    """At start-up, before ``setup()``. Configuring again (tests) builds the rules of blacking out anew."""
    global _current
    _current = config
    from . import masking

    masking.rebuild(config)


def current() -> AppConfig:
    if _current is None:
        raise RuntimeError("nexlog is not configured: call nexlog.configure(AppConfig(...)) at start-up")
    return _current
