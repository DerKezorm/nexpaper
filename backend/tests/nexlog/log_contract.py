"""What the contract tests ask of an app: the ``StandardAdapter`` the app's adapter extends, and small helpers.

The contract tests run the module inside the app: the app's own start (configure, setup, its store of the level), its
own middleware (request numbers, who acts), its own check of operators, its own routes mounted from
``nexlog.api``. They never change; the app fills in its adapter (``backend/tests/nexlog_adapter.py``).
"""

from __future__ import annotations

import importlib
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any


@dataclass
class LegacyLine:
    """A line exactly as the app wrote it before the module (copied from a real file of the app), and what the page
    must read from it."""

    raw: str
    level: str
    logger: str
    message: str
    request_id: str | None = None
    user: str | None = None
    #: The moment as ISO text with offset, as the line means it (the app's clock: local or UTC).
    at: str | None = None


@dataclass
class Secret:
    """A message the app might log, and the part of it that must never reach the file."""

    message: str
    hidden: str
    #: What must still stand in the line (the prefix of a key, the path), to show the line was written.
    kept: list[str] = field(default_factory=list)


class StandardAdapter:
    """Defaults; every method marked ``APP`` is the app's to write."""

    #: Where the vendored package lives in the app.
    package = "app.vendor.nexlog"
    #: Where the app mounts ``nexlog.api.router`` (nexpaper ``/api/v1/logs``).
    prefix = "/api/logs"
    #: The header that carries the request number in every answer (nexmail ``x-nexmail-vorgang``).
    request_id_header = "x-request-id"
    #: A route an operator may call that the middleware logs at ``detailed`` (not a quiet path like the health check).
    probe_path = "/api/about"

    def start(self) -> None:
        """APP: an empty app with a fresh database and data folder, started as in production: ``nexlog.configure``,
        ``nexlog.setup``, the store attached, ``apply_stored_mode``."""
        raise NotImplementedError("APP: start")

    def stop(self) -> None:
        """APP: close the database, ``nexlog.shutdown()``, remove temporary folders."""

    def client(self, role: str) -> Any:
        """APP: a ``TestClient`` of the app: ``"operator"`` signed in as an operator, ``"member"`` signed in as an
        account without that role, ``"anonymous"`` without a session."""
        raise NotImplementedError("APP: client")

    def operator_name(self) -> str:
        """APP: the username of the operator ``client("operator")`` signs in as (it stands in the lines as
        ``u:<name>``)."""
        raise NotImplementedError("APP: operator_name")

    def stored(self) -> tuple[Any, Any]:
        """APP: the level and its end as the app's store holds them now (its keys, raw)."""
        raise NotImplementedError("APP: stored")

    def store_legacy(self, deep: bool, minutes_from_now: int) -> None:
        """APP: write a level into the store the way the older version did (its keys, its names, its form of the end):
        a deep level (``detailed``, nexmail ``ausfuehrlich``) ending ``minutes_from_now`` from now (negative: in the
        past), or with ``deep=False`` the quiet level without an end."""
        raise NotImplementedError("APP: store_legacy")

    def environment(self, value: str) -> AbstractContextManager[None]:
        """APP: while open, the app's environment variable for the level (``NEXNOTES_LOG_LEVEL``) reads ``value``."""
        raise NotImplementedError("APP: environment")

    def legacy_lines(self) -> list[LegacyLine]:
        """APP: lines of the older version's file (at least one with a request number and, where the app wrote one,
        an account)."""
        raise NotImplementedError("APP: legacy_lines")

    def secrets(self) -> list[Secret]:
        """APP: messages with the app's keys and tokens in them (each prefix, each path with a token), and what of
        them must never reach the file."""
        raise NotImplementedError("APP: secrets")


def log_package(adapter: Any) -> ModuleType:
    package = importlib.import_module(adapter.package)
    importlib.import_module(f"{adapter.package}.api")
    return package
