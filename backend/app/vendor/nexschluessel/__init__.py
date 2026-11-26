"""nexschluessel: the API keys and AI tools (MCP) of every nex app, the same everywhere.

Vendored unchanged into ``backend/app/vendor/nexschluessel/``; a test in the app compares the files with the checksums
in ``MANIFEST.json``, so a change is made in the module's source, never in the copy.

The module manages; the rows stay in the app's tables and keep their form, so every key made so far works on
unchanged (its prefix, its hash, its rights and areas):

- ``config``: the app's kinds of key (prefix, older prefixes, rights, extras, areas, lifetimes, limits), its switches;
- ``model``: a key as the module sees it and the ``Store`` the app writes over its tables;
- ``tokens``: making a secret, its hash (SHA-256 hex of the whole key), the visible start, ``Authorization: Bearer``;
- ``keys``: make, change, revoke, the account's list, the operator's overview, lock and unlock, ``authenticate``;
- ``switches``: the operator's card "Interfaces";
- ``errors``: the refusals (``KeyRefused``), with the app's own codes where its answers had others;
- ``api``: the routes of the cards (needs FastAPI; imported only by ``from app.vendor.nexschluessel import api``).
"""

from __future__ import annotations

from . import keys, switches, tokens
from .config import (
    DEFAULT_EXPIRY_DAYS,
    KIND_API,
    KIND_MCP,
    KINDS,
    OPTION_MCP,
    RIGHT_READ,
    RIGHT_UPLOAD,
    RIGHT_WRITE,
    SWITCH_API,
    SWITCH_APP,
    SWITCH_MCP,
    SWITCH_PAIRING,
    SWITCHES,
    AppConfig,
    KeyKind,
)
from .errors import CODES, KeyRefused
from .keys import Caller, Made, authenticate, block, change, entry, listing, make, overview, revoke, unblock
from .model import (
    ALL_AREAS,
    AccountId,
    AiStore,
    Area,
    AreaId,
    ClientRefStore,
    Holder,
    Key,
    KeyChange,
    KeyId,
    NewKey,
    Store,
)
from .tokens import bearer, digest, make_secret, plausible, shown_prefix

__version__ = "1.1.2"

__all__ = [
    "ALL_AREAS",
    "CODES",
    "DEFAULT_EXPIRY_DAYS",
    "KINDS",
    "KIND_API",
    "KIND_MCP",
    "OPTION_MCP",
    "RIGHT_READ",
    "RIGHT_UPLOAD",
    "RIGHT_WRITE",
    "SWITCHES",
    "SWITCH_API",
    "SWITCH_APP",
    "SWITCH_MCP",
    "SWITCH_PAIRING",
    "AccountId",
    "AiStore",
    "AppConfig",
    "Area",
    "AreaId",
    "Caller",
    "ClientRefStore",
    "Holder",
    "Key",
    "KeyChange",
    "KeyId",
    "KeyKind",
    "KeyRefused",
    "Made",
    "NewKey",
    "Store",
    "__version__",
    "authenticate",
    "bearer",
    "block",
    "change",
    "digest",
    "entry",
    "keys",
    "listing",
    "make",
    "make_secret",
    "overview",
    "plausible",
    "revoke",
    "shown_prefix",
    "switches",
    "tokens",
    "unblock",
]
