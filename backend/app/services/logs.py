"""Logging, from the shared module ``log`` (``app/vendor/nexlog``, bauplaene/log 1.0.0).

nexpaper writes its log to ``data/logs/nexpaper.log``. The file rolls over at a size limit, three older files are kept,
and files older than 14 days are deleted. Four levels (``quiet``, ``normal``, ``detailed``, ``trace``); the two deep
ones switch themselves off; ``NEXPAPER_LOG_LEVEL`` overrides the stored level, the emergency exit for "the app does not
even start". All of it lives in the module now; this file only tells it what is nexpaper's own and keeps the names
every caller used (``from app.services import logs``).

Messages are English on purpose: log lines end up in bug reports and web searches. ``tests/test_log_language.py``
keeps that rule.

⚠️ What never goes into the log, at any level: anything stored in a document (its text, notes, titles, senders, tags),
search terms, passwords, tokens, keys, session identifiers. Sizes, counts, accounts and results do.
``tests/test_log_secrets.py`` scans the code for the obvious mistakes; the module's blacking out (tracebacks and stacks
included) is the net below that rule.
"""

from __future__ import annotations

from pathlib import Path

from .. import private
from ..config import get_settings
from ..vendor import nexlog

# The names of the module, as nexpaper's callers know them.
from ..vendor.nexlog import *
from ..vendor.nexlog import handlers as _handlers

#: A device token or an API key that ended up in a line (pasted into an address by mistake): devices ``npd_``, keys
#: ``npk_``, the links to a document ``lnk_``, to an export ``lnx_``, the upload requests ``upr_``; MCP keys and
#: programs ``npm_``, their refresh tokens ``npmr_`` and codes ``npmc_`` (mcp 1.1.0); connections with other nex apps
#: ``npv_``, ``npvr_``, ``npvc_`` (verbinden 0.1.1).
KEY_PREFIXES = ("npd_", "npk_", "lnk_", "lnx_", "upr_", "npm_", "npmr_", "npmc_", "npv_", "npvr_", "npvc_")
#: Tokens that stand in an address without a prefix of their own, on top of the module's (``invite``, ``reset`` …):
#: links that confirm a mail address (the page ``/mail/<token>`` and the route ``/api/v1/email/confirm/<token>``), the
#: links to a document (``/l/<token>``), the links that confirm a sender address (the page ``/absender/<token>`` and
#: the route ``/api/v1/mail-senders/confirm/<token>``), the links to an export (``/x/<token>``) and the upload requests
#: (``/u/<token>``). The same list nexpaper's own log had before the module.
TOKEN_PATHS = ("mail", "email/confirm", "l", "absender", "mail-senders/confirm", "x", "u")
#: Pillow writes every Exif value of a photo from DEBUG on (a description, a place, a device): never finer than WARNING.
SILENT = ("PIL",)

#: The filter that writes the request and the account into a line and blacks out, for a handler of nexpaper's own
#: (``reset_link`` appends to the server's file from another process).
_ContextFilter = _handlers._ContextFilter


def configure(log_dir: Path | None = None) -> None:
    """What the module needs of nexpaper: its name, folder, environment variable and rules. Done once on import, so
    every caller (the start, the tests) finds it configured. ``log_dir``: another folder (the contract tests)."""
    nexlog.configure(
        nexlog.AppConfig(
            app_name="nexpaper",
            log_dir=log_dir if log_dir is not None else (lambda: get_settings().data_dir / "logs"),
            env_level=lambda: get_settings().log_level or "",
            key_prefixes=KEY_PREFIXES,
            token_paths=TOKEN_PATHS,
            silent_loggers=SILENT,
            tighten=private.tighten,
        )
    )


configure()
