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

#: Since 1.1.0: what the operator's account functions offer beyond what every app has (several operators, block,
#: delete with 30 days to bring back), by feature, the apps that have it (plan "Einstellungen", decided 25.11.2026):
#: a storage limit per account only where accounts keep files, "AI allowed" where the app has AI built in, "Immich
#: allowed" where Immich is connected. Changed only here, after the owner of the apps decided; the contract tests hold
#: every app to its row.
FEATURE_STORAGE_LIMIT = "storage_limit"
FEATURE_AI = "ai"
FEATURE_IMMICH = "immich"
FEATURES: Mapping[str, frozenset[str]] = {
    FEATURE_STORAGE_LIMIT: frozenset({"nexnotes", "nexpaper", "nexdiary", "nexlore"}),
    FEATURE_AI: frozenset({"nexmail", "nexpaper", "nexdiary", "nexlore"}),
    FEATURE_IMMICH: frozenset({"nexdiary"}),
}
#: The features that are rights of an account (a box to tick in the dialog "Manage"), in their order.
RIGHTS = (FEATURE_AI, FEATURE_IMMICH)


def features_of(app_name: str) -> frozenset[str]:
    """The features the table gives an app by its name."""
    return frozenset(feature for feature, apps in FEATURES.items() if app_name in apps)


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
    #: Since 1.1.0: the features of ``FEATURES`` this app has; None (the default) takes the app's row of the table.
    #: Only the module's own tests name them by hand (an app called ``nexapp`` has none).
    features: frozenset[str] | None = None
    #: Since E45: what the app showed an account that never chose light or dark before 1.1.0 (nexmail, nexlore
    #: ``dark``; every other app ``system``). An account of before without a choice and without a value its browser
    #: kept takes it once (``profiles.adopt_theme``), so that nothing changes at the update. New accounts always start
    #: with ``system``.
    theme_default_before: str = "system"

    def __post_init__(self) -> None:
        if not _APP_NAME.fullmatch(self.app_name):
            raise ValueError(f"app_name {self.app_name!r} must be lower-case letters, digits and dashes")
        from .errors import CODES

        unknown = sorted(set(self.error_codes) - set(CODES))
        if unknown:
            raise ValueError(f"error_codes names codes the module does not have: {unknown}")
        strange = sorted(set(self.features or ()) - set(FEATURES))
        if strange:
            raise ValueError(f"features names features the module does not have: {strange}")
        if self.theme_default_before not in ("light", "dark", "system"):
            raise ValueError(f"theme_default_before {self.theme_default_before!r} must be light, dark or system")

    @property
    def feature_set(self) -> frozenset[str]:
        """The features this app has (``FEATURES``)."""
        return features_of(self.app_name) if self.features is None else frozenset(self.features)

    def has(self, feature: str) -> bool:
        return feature in self.feature_set

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
