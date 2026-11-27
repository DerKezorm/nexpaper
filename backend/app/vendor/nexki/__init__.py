"""nexki: the AI services of the nex apps, the same in every app (module ``ki`` of bauplaene).

Copied unchanged into ``backend/app/vendor/nexki/`` by ``bauplaene/ki/tools/sync.py``; changed only there. The plan is
``Development/nexapps/Baupläne/Entwurf KI-Anbieter.md`` in nexlore with its decisions K1 onwards.

* ``config``: ``AppConfig``, ``Task``.
* ``model``: the ``Store`` the app gives over its own tables, ``OwnAccess``, ``Service``, ``Event``.
* ``chain``: the chain of switches (``usable``, ``reason``, ``state``) and ``for_programs`` for ``schluessel`` and
  ``mcp`` (MCP decision 10).
* ``settings``: the operator's service, the main switch, the way, the hosts, the brakes, an account's own service,
  ``adopt`` after an update.
* ``client``: ``ask`` (one task), ``list_models``, ``probe``, ``events``, ``frame`` for material.
* ``net``: where a request may go and how (rules of the network, one deadline, no redirect, no proxy).
* ``quirks``: the peculiarities of the models. ``brake``: the brakes. ``errors``: the refusals.
* ``api``: the routes (FastAPI).
"""

from __future__ import annotations

from . import brake, chain, client, config, errors, model, net, quirks, settings
from .client import Answer, ask, frame
from .config import APIS, MODES, AppConfig, Task
from .errors import CODES, AiRefused
from .model import Event, OwnAccess, Service, Store

__version__ = "0.1.3"

__all__ = [
    "APIS",
    "CODES",
    "MODES",
    "AiRefused",
    "Answer",
    "AppConfig",
    "Event",
    "OwnAccess",
    "Service",
    "Store",
    "Task",
    "ask",
    "brake",
    "chain",
    "client",
    "config",
    "errors",
    "frame",
    "model",
    "net",
    "quirks",
    "settings",
]
