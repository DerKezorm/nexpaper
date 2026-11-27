"""nexgeraete: pairing iPhone, iPad and Mac with the server of a nex app, the devices of an account, notifications.

Vendored unchanged into ``backend/app/vendor/nexgeraete/``; a test in the app compares the files with the checksums in
``MANIFEST.json``, so a change is made in the module's source, never in the copy.

The module manages; the rows stay in the app's tables and keep their form, so every device paired so far works on
unchanged (its prefix, its hash, its push ticket):

- ``config``: the app's name, scheme, prefix, old form, limits, relay and kinds of notification;
- ``model``: a device as the module sees it, the account behind it, pairings, the ``Store`` over the app's tables;
- ``tokens``: keys, codes, hashes, comparison in fixed time, PKCE;
- ``pairing``: QR code, code to type, sign-in in the browser, another own device;
- ``devices``: knowing a device by its key (``authenticate``), the list, renaming, disconnecting, the daily sweep;
- ``push``: signing up for notifications, kinds per device, sealing and sending through the relay;
- ``notices``: "Neue Version" for operators and "Neues Gerät verbunden";
- ``forms``: the answers in the forms ``nex``, ``tasks``, ``mail``; ``errors``: the refusals;
- ``seal`` (needs ``cryptography``), ``qr`` (needs ``segno``), ``api`` (needs FastAPI): imported where they are used.
"""

from __future__ import annotations

from . import devices, errors, forms, notices, pairing, push, tokens
from .config import (
    ALPHABET,
    CLIENT_HEADER,
    DEVICE_KINDS,
    FORM_MAIL,
    FORM_NEX,
    FORM_TASKS,
    FORMS,
    KIND_SECURITY,
    KIND_UPDATE,
    SWITCH_APP,
    SWITCH_PAIRING,
    SWITCHES,
    VIA_BROWSER,
    VIA_CODE,
    VIA_ICLOUD,
    VIA_QR,
    VIAS,
    AppConfig,
    PushKind,
)
from .devices import Caller, Client, authenticate, client_of, describe
from .errors import CODES, DeviceRefused
from .model import (
    AccountId,
    ConnectCode,
    Device,
    DeviceChange,
    DeviceId,
    GoneStore,
    Holder,
    NewDevice,
    NewPairing,
    Pairing,
    PushState,
    Store,
)
from .pairing import Paired, Started

__version__ = "0.1.5"

__all__ = [
    "ALPHABET",
    "CLIENT_HEADER",
    "CODES",
    "DEVICE_KINDS",
    "FORMS",
    "FORM_MAIL",
    "FORM_NEX",
    "FORM_TASKS",
    "KIND_SECURITY",
    "KIND_UPDATE",
    "SWITCHES",
    "SWITCH_APP",
    "SWITCH_PAIRING",
    "VIAS",
    "VIA_BROWSER",
    "VIA_CODE",
    "VIA_ICLOUD",
    "VIA_QR",
    "AccountId",
    "AppConfig",
    "Caller",
    "Client",
    "ConnectCode",
    "Device",
    "DeviceChange",
    "DeviceId",
    "DeviceRefused",
    "GoneStore",
    "Holder",
    "NewDevice",
    "NewPairing",
    "Paired",
    "Pairing",
    "PushKind",
    "PushState",
    "Started",
    "Store",
    "__version__",
    "authenticate",
    "client_of",
    "describe",
    "devices",
    "errors",
    "forms",
    "notices",
    "pairing",
    "push",
    "tokens",
]
