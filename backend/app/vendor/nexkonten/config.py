"""What the module needs to know about the app it runs in.

The module imports nothing from an app. The app hands over its name once at start-up with
``configure(AppConfig(...))``; everything else (accounts, invitations, links, sessions) comes in through the
``Store`` protocol (``model.py``) when it is needed.

Tests replace the network with ``use_transport(httpx.MockTransport(...))``; the module then never touches it.
"""

from __future__ import annotations

import os
import re
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import httpx

#: An app name as it appears in log names and in ``<APP>_SETUP_TOKEN``.
_APP_NAME = re.compile(r"[a-z][a-z0-9-]{1,30}")
#: Values of an environment variable that switch something on.
_ON = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class AppConfig:
    """The app's side of the contract. Only ``app_name`` is required.

    ``setup_token`` returns the setup code the operator fixed (``""`` for none); by default the environment variable
    ``<APP>_SETUP_TOKEN`` (``NEXMAIL_SETUP_TOKEN``). An app that reads its settings elsewhere hands over a function.
    """

    app_name: str
    setup_token: Callable[[], str] | None = None
    #: The logger the module writes to. Default ``<app>.accounts``.
    logger_name: str = ""
    #: A TLS context of the app's own for fetching a provider's picture; None: httpx's defaults.
    ssl_context: ssl.SSLContext | None = None
    #: The app's own error codes for clients of an older version: module code -> app code (``{"username_taken":
    #: "name_taken"}``). ``AccountError.public_code`` and ``as_dict()`` answer with them.
    error_codes: Mapping[str, str] = field(default_factory=dict)
    #: Since 0.3.3, the emergency hammer: True switches the second factor off for everybody (an older variable of the
    #: app, ``NEXMAIL_ZWEI_FAKTOR_AUS``). ``<APP>_SECOND_FACTOR_OFF`` counts always, with or without this.
    second_factor_off: Callable[[], bool] | None = None

    def __post_init__(self) -> None:
        if not _APP_NAME.fullmatch(self.app_name):
            raise ValueError(f"app_name {self.app_name!r} must be lower-case letters, digits and dashes")
        from .errors import CODES

        unknown = sorted(set(self.error_codes) - set(CODES))
        if unknown:
            raise ValueError(f"error_codes names codes the module does not have: {unknown}")

    @property
    def log_name(self) -> str:
        return self.logger_name or f"{self.app_name}.accounts"

    @property
    def setup_token_env(self) -> str:
        """``NEXMAIL_SETUP_TOKEN`` for ``nexmail``."""
        return self.app_name.upper().replace("-", "_") + "_SETUP_TOKEN"

    @property
    def second_factor_off_env(self) -> str:
        """``NEXMAIL_SECOND_FACTOR_OFF`` for ``nexmail``."""
        return self.app_name.upper().replace("-", "_") + "_SECOND_FACTOR_OFF"

    def second_factor_is_off(self) -> bool:
        """The emergency hammer: ``<APP>_SECOND_FACTOR_OFF`` set to 1, true, yes or on, or the app's own hook."""
        if os.environ.get(self.second_factor_off_env, "").strip().lower() in _ON:
            return True
        return bool(self.second_factor_off is not None and self.second_factor_off())

    def given_setup_token(self) -> str:
        if self.setup_token is not None:
            return (self.setup_token() or "").strip()
        return os.environ.get(self.setup_token_env, "").strip()


_current: AppConfig | None = None
_transport: httpx.BaseTransport | None = None


def configure(config: AppConfig) -> None:
    """Called once at start-up (and by tests)."""
    global _current
    _current = config


def current() -> AppConfig:
    if _current is None:
        raise RuntimeError("nexkonten is not configured: call nexkonten.configure(AppConfig(...)) at start-up")
    return _current


def use_transport(transport: httpx.BaseTransport | None) -> None:
    """Tests: every fetch goes through this transport instead of the network. None goes back to the network."""
    global _transport
    _transport = transport


def transport() -> httpx.BaseTransport | None:
    return _transport
