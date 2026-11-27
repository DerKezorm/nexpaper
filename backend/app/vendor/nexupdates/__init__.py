"""nexupdates: whether a newer version of the app is out, the same in every nex app.

Vendored unchanged into ``backend/app/vendor/nexupdates/``; a test in the app compares the files with the checksums
in ``MANIFEST.json``, so a change is made in the module's source, never in the copy.

- ``config``: name, version, repository, project page, address, the hooks to the app's switch, memory and bell;
- ``check``: the question (one address, a size limit, a deadline, no proxy from the environment), the daily rhythm,
  the switch, the setup answer (U1), the background look with one notice per new version (U3);
- ``words``: the bell's words in German, English and French;
- ``api``: the routes of the page "Über" (needs FastAPI; ``from app.vendor.nexupdates import api``).

The names of nexnotes' ``services/updates.py`` stand here (``parse``, ``is_newer``, ``state``, ``forget``, ``State``,
``INTERVAL``, ``RETRY``, ``MAX_ANSWER``), so that file may become ``from app.vendor.nexupdates import *``.
"""

from __future__ import annotations

from . import check, words
from .check import (
    HEADERS,
    INTERVAL,
    MAX_ANSWER,
    RETRY,
    TIMEOUT,
    USER_AGENT,
    State,
    ask,
    at_setup,
    forget,
    is_newer,
    look_once,
    parse,
    run_forever,
    set_switch,
    state,
    switch_on,
)
from .config import DEFAULT_ON, AppConfig, configure, current
from .words import notice

__version__ = "0.1.4"

__all__ = [
    "DEFAULT_ON",
    "HEADERS",
    "INTERVAL",
    "MAX_ANSWER",
    "RETRY",
    "TIMEOUT",
    "USER_AGENT",
    "AppConfig",
    "State",
    "__version__",
    "ask",
    "at_setup",
    "check",
    "configure",
    "current",
    "forget",
    "is_newer",
    "look_once",
    "notice",
    "parse",
    "run_forever",
    "set_switch",
    "state",
    "switch_on",
    "words",
]
