"""What the module takes from the module ``mcp`` next to it (decision V4: one OAuth core, not two): the core
(``oauthcore``: digest, PKCE, return addresses, new tokens) and the brake in memory. In an app both packages lie under
``app.vendor`` (``app.vendor.nexmcp``), in the modules' own tests at the top (``nexmcp``); the sibling is found either
way. ``tools/sync.py`` refuses to copy into an app without ``nexmcp`` 1.1.0 or later."""

from __future__ import annotations

import importlib
from types import ModuleType

#: The version of ``nexmcp`` that brings ``oauthcore``.
NEEDS_MCP = (1, 1, 0)


def _sibling(name: str) -> ModuleType:
    parent = (__package__ or "").rpartition(".")[0]
    return importlib.import_module(f"{parent}.{name}" if parent else name)


_mcp = _sibling("nexmcp")
if tuple(int(part) for part in str(_mcp.__version__).split(".")) < NEEDS_MCP:
    raise ImportError("the module verbinden needs nexmcp 1.1.0 or later next to it")

oauthcore: ModuleType = _sibling("nexmcp.oauthcore")
brake: ModuleType = _sibling("nexmcp.brake")
BRAKE = brake.BRAKE
