"""nexsprachen: the operator's own languages in every nex app, the same everywhere.

Vendored unchanged into ``backend/app/vendor/nexsprachen/``; a test in the app compares the files with the checksums
in ``MANIFEST.json``, so a change is made in the module's source, never in the copy.

- ``config``: the app's name, folder, built-in languages and template (``configure(AppConfig(...))``);
- ``errors``: the codes of the refusals and the reasons a file is not usable;
- ``store``: checking, listing, reading, saving and removing the files;
- ``api``: the routes for the card and the menus (needs FastAPI; imported only by
  ``from app.vendor.nexsprachen import api``).

The names of nexnotes' ``services/locales.py`` stand here unchanged, so that file may become
``from app.vendor.nexsprachen import *``.
"""

from __future__ import annotations

from . import errors, store
from .config import FALLBACK, AppConfig, configure, current
from .errors import CODES, REASONS, LocaleError, SaveError
from .store import (
    CODE_PATTERN,
    MAX_BYTES,
    MAX_DEPTH,
    MAX_FILES,
    MAX_KEY,
    MAX_NAME,
    META_KEY,
    RESERVED_KEYS,
    Language,
    Locale,
    Parsed,
    available,
    forget,
    known,
    languages,
    load,
    locales_dir,
    parse,
    remove,
    save,
    template,
    valid_code,
)

__version__ = "1.0.0"

__all__ = [
    "CODES",
    "CODE_PATTERN",
    "FALLBACK",
    "MAX_BYTES",
    "MAX_DEPTH",
    "MAX_FILES",
    "MAX_KEY",
    "MAX_NAME",
    "META_KEY",
    "REASONS",
    "RESERVED_KEYS",
    "AppConfig",
    "Language",
    "Locale",
    "LocaleError",
    "Parsed",
    "SaveError",
    "__version__",
    "available",
    "configure",
    "current",
    "errors",
    "forget",
    "known",
    "languages",
    "load",
    "locales_dir",
    "parse",
    "remove",
    "save",
    "store",
    "template",
    "valid_code",
]
