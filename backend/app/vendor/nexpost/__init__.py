"""nexpost: the system mail of every nex app, the same everywhere.

Vendored unchanged into ``backend/app/vendor/nexpost/``; a test in the app compares the files with the checksums in
``MANIFEST.json``, so a change is made in the module's source, never in the copy.

- ``config``: the app's name, logo and error codes (``configure(AppConfig(...))``);
- ``model``: settings, letters, the outbox, the ``Store`` the app implements;
- ``settings``: what the operator types, checked, older values understood, the warning without encryption;
- ``letters``: the texts in German, English and French, text and HTML with the logo, headers in one line;
- ``send``: one letter through the mail server, the refusals as fixed codes;
- ``outbox``: queue, send again after 1, 5, 15, 60, 180 minutes, the test mail.

Only the standard library is needed.
"""

from __future__ import annotations

from . import common, letters, outbox, send, settings
from .config import AppConfig, configure, current, use_smtp
from .errors import CODES, MailError
from .model import (
    NONE,
    SECURITY,
    STARTTLS,
    TLS,
    Letter,
    MailSettings,
    MailStatus,
    OutboxItem,
    Store,
)

__version__ = "1.0.0"

__all__ = [
    "CODES",
    "NONE",
    "SECURITY",
    "STARTTLS",
    "TLS",
    "AppConfig",
    "Letter",
    "MailError",
    "MailSettings",
    "MailStatus",
    "OutboxItem",
    "Store",
    "__version__",
    "common",
    "configure",
    "current",
    "letters",
    "outbox",
    "send",
    "settings",
    "use_smtp",
]
