"""What the module needs to know about the app: its name, its logo for HTML mails, its log, its own error codes.
Tests replace the mail server with ``use_smtp(factory)``; then nothing touches the network."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

_APP_NAME = re.compile(r"[a-z][a-z0-9-]{1,30}")


@dataclass(frozen=True)
class AppConfig:
    #: ``nexnotes``: the default sender name and the name in every mail.
    app_name: str
    #: The name as people read it (``nexnotes``, ``nexmail``); default the app's name.
    display_name: str = ""
    #: The logo for HTML mails (PNG bytes), shown as ``cid:logo``; None: no logo.
    logo: bytes | None = None
    logger_name: str = ""
    #: Module code -> the app's code of an older version.
    error_codes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _APP_NAME.fullmatch(self.app_name):
            raise ValueError(f"app_name {self.app_name!r} must be lower-case letters, digits and dashes")
        from .errors import CODES

        unknown = sorted(set(self.error_codes) - set(CODES))
        if unknown:
            raise ValueError(f"error_codes names codes the module does not have: {unknown}")

    @property
    def log_name(self) -> str:
        return self.logger_name or f"{self.app_name}.mail"

    @property
    def shown_name(self) -> str:
        return self.display_name or self.app_name


_current: AppConfig | None = None
_smtp: Callable[..., Any] | None = None


def configure(config: AppConfig) -> None:
    global _current
    _current = config


def current() -> AppConfig:
    if _current is None:
        raise RuntimeError("nexpost is not configured: call nexpost.configure(AppConfig(...)) at start-up")
    return _current


def use_smtp(factory: Callable[..., Any] | None) -> None:
    """Tests: ``factory(settings, timeout, context)`` gives an object with ``send_message(message)`` and ``quit()``
    instead of a connection to a mail server. None goes back to the network."""
    global _smtp
    _smtp = factory


def smtp_factory() -> Callable[..., Any] | None:
    return _smtp
