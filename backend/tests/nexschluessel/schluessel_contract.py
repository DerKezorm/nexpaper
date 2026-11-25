"""What the contract tests ask of an app: the ``StandardAdapter`` the app's adapter extends, and small helpers.

The contract tests run the module inside the app: the app's own start, its own sessions and operators, its own
``Store`` over its own tables, its own routes that take a key (``/api/v1``, ``/api/mcp``), the module's routes mounted
from ``nexschluessel.api``. Above all they prove that **every key made before the module still works**: the adapter
writes keys the way the older version did (its table, its prefix, its hash) and the tests present them to the app's
real routes. They never change; the app fills in its adapter (``backend/tests/nexschluessel_adapter.py``).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType
from typing import Any


@dataclass(frozen=True)
class LegacyKey:
    """A form of key the app made before the module (each prefix, each kind, each legacy form)."""

    #: For the test's name and messages ("API token", "nexdeck card key", "OAuth connector").
    label: str
    #: The module's kind: ``api`` or ``mcp``.
    kind: str
    #: Its prefix (``ntk_``, ``nn_deck_``).
    prefix: str
    #: The right it was made with, as the app names it.
    right: str
    #: The legacy form the store reports (``card``), or ``None``.
    legacy: str | None = None
    #: Issued to a program by OAuth (an AI tool's connector).
    program: bool = False


class StandardAdapter:
    """Defaults; every method marked ``APP`` is the app's to write."""

    #: Where the vendored package lives in the app.
    package = "app.vendor.nexschluessel"
    #: Where the app mounts ``nexschluessel.api.router``.
    prefix = "/api/connections"

    def start(self) -> None:
        """APP: an empty app (fresh database), started as in production, with three accounts: ``owner`` and
        ``other`` (members, passwords, no second factor) and ``operator``."""
        raise NotImplementedError("APP: start")

    def stop(self) -> None:
        """APP: close the database, remove temporary folders."""

    def config(self) -> Any:
        """APP: the app's ``nexschluessel.AppConfig`` (the one its routes use)."""
        raise NotImplementedError("APP: config")

    def client(self, role: str) -> Any:
        """APP: a ``TestClient`` signed in as ``"owner"``, ``"other"``, ``"operator"`` (a browser session), or
        ``"anonymous"`` without one."""
        raise NotImplementedError("APP: client")

    def legacy_keys(self) -> list[LegacyKey]:
        """APP: every form of key the older version made (each kind, each prefix, the connectors of AI tools)."""
        raise NotImplementedError("APP: legacy_keys")

    def make_legacy(self, spec: LegacyKey, *, account: str = "owner", expired: bool = False) -> str:
        """APP: write a key of ``spec`` for ``account`` exactly the way the older version did (its service function or
        the row as it wrote it: prefix, SHA-256 hex, its columns) and return the secret. ``expired``: its end lies
        an hour in the past (apps without an end of keys: ``pytest.skip``)."""
        raise NotImplementedError("APP: make_legacy")

    def probe(self, kind: str, secret: str) -> int:
        """APP: present ``secret`` to a real route of the app that takes keys of ``kind`` (``api``: ``GET
        /api/v1/me`` or what the app has; ``mcp``: ``POST /api/mcp`` with ``initialize``) and return the status."""
        raise NotImplementedError("APP: probe")

    def owe_factor(self) -> None:
        """APP: from now on the owner's keys rest: the operator requires a second factor, the owner signs in with a
        password and has none."""
        raise NotImplementedError("APP: owe_factor")

    def defaults(self, kind: Any) -> dict:
        """What a new key of ``kind`` needs beyond a name in this app (nexmail: its mailboxes, ``{"areas": [...]}``);
        the contract tests send it with every key they make."""
        return {}

    def refusal(self, answer: Any) -> dict:
        """The body of a refusal of the module's routes as a dict with ``code`` (default: FastAPI's ``detail``, the
        module's form; an app with its own form of errors reads it here)."""
        return answer.json()["detail"]

    def foreign_area(self) -> Any:
        """APP: the id of an area of ``other`` that ``owner`` cannot reach (where the app limits keys to areas)."""
        raise NotImplementedError("APP: foreign_area")


def package(adapter: Any) -> ModuleType:
    found = importlib.import_module(adapter.package)
    importlib.import_module(f"{adapter.package}.api")
    return found


def ok(status: int) -> bool:
    return 200 <= status < 300


def kinds_made_by_hand(config: Any) -> list[Any]:
    return [kind for kind in config.kinds if kind.creatable]
