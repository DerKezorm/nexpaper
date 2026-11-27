"""nexwasneu: "What's new", the same in every nex app.

Vendored unchanged into ``backend/app/vendor/nexwasneu/``; a test in the app compares the files with the checksums in
``MANIFEST.json``, so a change is made in the module's source, never in the copy.

- ``config``: the app's name, running version, the folder of its texts and its built-in languages;
- ``texts``: the form of an entry, the language chain with English as the fallback, which entries an account reads
  (unread since its version, the one for "About", the history), the guard and the frozen texts of released versions;
- ``seen``: the account as the module needs it (``Viewer``), ``mark_seen`` and the value of a new account;
- ``api``: the routes (needs FastAPI; ``from app.vendor.nexwasneu import api``).
"""

from __future__ import annotations

from . import seen, texts
from .config import FALLBACK, FIRST, UNREAD_LIMIT, AppConfig, configure, current
from .seen import Viewer, mark_seen, seen_for_new_account
from .texts import (
    RELEASED,
    FreezeRefused,
    State,
    chain,
    collected,
    digest,
    entries,
    forget,
    freeze,
    is_entry,
    parse,
    problems,
    state,
)

__version__ = "0.1.0"

__all__ = [
    "FALLBACK",
    "FIRST",
    "RELEASED",
    "UNREAD_LIMIT",
    "AppConfig",
    "FreezeRefused",
    "State",
    "Viewer",
    "__version__",
    "chain",
    "collected",
    "configure",
    "current",
    "digest",
    "entries",
    "forget",
    "freeze",
    "is_entry",
    "mark_seen",
    "parse",
    "problems",
    "seen",
    "seen_for_new_account",
    "state",
    "texts",
]
