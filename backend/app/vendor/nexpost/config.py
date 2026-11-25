"""What the module needs to know about the app: its name, its logo for HTML mails, its log, its own error codes, and
since 1.1.0 its round of the outbox (``outbox_runner``, for ``outbox.nudge``). Tests replace the mail server with
``use_smtp(factory)``; then nothing touches the network."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

_APP_NAME = re.compile(r"[a-z][a-z0-9-]{1,30}")
#: Since 1.1.0 the logo is checked: the first bytes of every PNG file.
PNG = b"\x89PNG\r\n\x1a\n"


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
    #: Since 1.1.0: the app's own round of the outbox (opens its own session and calls ``outbox.run_once``, then
    #: commits and closes; the function the app's minute loop calls). ``outbox.nudge`` runs it in a thread right after
    #: a mail was queued and committed. None: no nudging (the app's tests, an app without background work); the mail
    #: waits for the next round of the loop.
    outbox_runner: Callable[[], object] | None = None

    def __post_init__(self) -> None:
        if not _APP_NAME.fullmatch(self.app_name):
            raise ValueError(f"app_name {self.app_name!r} must be lower-case letters, digits and dashes")
        from .errors import CODES

        unknown = sorted(set(self.error_codes) - set(CODES))
        if unknown:
            raise ValueError(f"error_codes names codes the module does not have: {unknown}")
        if self.logo is not None and not self.logo.startswith(PNG):
            raise ValueError("logo must be the bytes of a PNG file (it goes out as image/png)")

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
