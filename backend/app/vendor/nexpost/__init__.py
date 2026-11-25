"""nexpost: the system mail of every nex app, the same everywhere.

Vendored unchanged into ``backend/app/vendor/nexpost/``; a test in the app compares the files with the checksums in
``MANIFEST.json``, so a change is made in the module's source, never in the copy.

- ``config``: the app's name, logo and error codes, since 1.1.0 its round of the outbox (``configure(AppConfig(...))``);
- ``model``: settings, letters, the outbox, the ``Store`` the app implements;
- ``settings``: what the operator types, checked, older values understood, the warning without encryption;
- ``letters``: the texts in German, English and French, text and HTML with the logo, headers in one line;
- ``app_letters`` (since 1.1.0): the app's own letters (reports, notifications, reminders, deadlines) in the same frame;
- ``send``: one letter through the mail server, the refusals as fixed codes;
- ``outbox``: queue (nudged at once since 1.1.0), send again after 1, 5, 15, 60, 180 minutes, the test mail;
- ``api`` (since 1.1.0, not loaded here: it needs FastAPI): the routes of the page Server › Mail.

Only the standard library is needed (``api`` aside).
"""

from __future__ import annotations

from . import app_letters, common, letters, outbox, send, settings
from .config import AppConfig, configure, current, use_smtp
from .errors import CODES, MailError
from .model import (
    EXTRA_HEADERS,
    NONE,
    SECURITY,
    STARTTLS,
    TLS,
    Letter,
    MailSettings,
    MailStatus,
    OutboxItem,
    Recipient,
    Store,
    letter_data,
    letter_from,
)

__version__ = "1.1.0"

__all__ = [
    "CODES",
    "EXTRA_HEADERS",
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
    "Recipient",
    "Store",
    "__version__",
    "app_letters",
    "common",
    "configure",
    "current",
    "letter_data",
    "letter_from",
    "letters",
    "outbox",
    "send",
    "settings",
    "use_smtp",
]
