"""nexverbinden: the connections of the nex apps with each other, the same in every app (module ``verbinden``).

Vendored unchanged into ``backend/app/vendor/nexverbinden/``; a test in the app compares the files with the checksums
in ``MANIFEST.json``, so a change is made in the module's source, never in the copy. Needs ``nexmcp`` 1.1.0 or later
next to it (the shared OAuth core and the brake).

The module brings the way two apps connect (one click, the other app asks once, both directions in one connection),
the tokens between them, the state of a connection and the card; the app brings its tables behind the ``Store``, the
check of a token at its own routes (``authenticate``, ``require``) and what it does with a partner (``call``):

- ``catalog``: which app connects with which, and the purposes each grants (the 14 pairs);
- ``config``: the app's settings (``AppConfig``) and the places that are the same everywhere;
- ``model``: the connection, a started one, a code, an older connection, the caller, and the ``Store``;
- ``connect``: start, consent, token, refresh, revoke, call, check, end, the card's view;
- ``reach`` and ``outbound``: asking a partner with the rules of the apps (own network only with the switch);
- ``errors``: the refusals;
- ``api``: the routes (needs FastAPI; imported only by ``from app.vendor.nexverbinden import api``).
"""

from __future__ import annotations

from . import catalog, connect, reach
from .catalog import APPS, CATALOG, PAIRS, PURPOSES, Catalog, Pair, Purpose
from .config import CONSENT_PAGE, PREFIX, PROTOCOL, RETURN_PAGE, STATES, WELL_KNOWN, AppConfig
from .connect import authenticate, call, check, disconnect, end_all, require, retry_waiting, views
from .errors import CODES, GrantError, Refused
from .model import Caller, Code, Connection, Legacy, Pending, Store, Waiting

__version__ = "0.1.1"

__all__ = [
    "APPS",
    "CATALOG",
    "CODES",
    "CONSENT_PAGE",
    "PAIRS",
    "PREFIX",
    "PROTOCOL",
    "PURPOSES",
    "RETURN_PAGE",
    "STATES",
    "WELL_KNOWN",
    "AppConfig",
    "Caller",
    "Catalog",
    "Code",
    "Connection",
    "GrantError",
    "Legacy",
    "Pair",
    "Pending",
    "Purpose",
    "Refused",
    "Store",
    "Waiting",
    "__version__",
    "authenticate",
    "call",
    "catalog",
    "check",
    "connect",
    "disconnect",
    "end_all",
    "reach",
    "require",
    "retry_waiting",
    "views",
]
