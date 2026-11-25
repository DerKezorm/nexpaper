"""nexlog contract tests: the app's adapter. Copied once by the module's ``tools/sync.py copy <app>`` to
``backend/tests/nexlog_adapter.py``; from then on it is the app's file.

Fill in every place marked ``APP:``. The contract tests in ``backend/tests/nexlog/`` (same in every app, never edit
them) call only what is here and in ``StandardAdapter``. Worked examples: the module's
``tests-fuer-apps/reference/nexlog_adapter.py`` (an app like nexnotes) and ``tests/mail_like_adapter.py`` (an app like
nexmail: German names of the levels, UTC, its own rules). Run them with ``pytest tests/nexlog``. Test values are made
at run time; no key is written into this file.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any

from log_contract import LegacyLine, Secret, StandardAdapter


class Adapter(StandardAdapter):
    # APP: where the vendored package lives, where the routes are mounted, the header of the request number, a route
    # the middleware logs at "detailed".
    package = "app.vendor.nexlog"
    prefix = "/api/logs"
    request_id_header = "x-request-id"
    probe_path = "/api/about"

    def start(self) -> None:
        # APP: an empty app (fresh database and data folder), started as in production.
        raise NotImplementedError("APP: start")

    def stop(self) -> None:
        # APP: close the database, nexlog.shutdown(), remove temporary folders.
        pass

    def client(self, role: str) -> Any:
        # APP: a TestClient as "operator", "member" or "anonymous".
        raise NotImplementedError("APP: client")

    def operator_name(self) -> str:
        # APP: the operator's username.
        raise NotImplementedError("APP: operator_name")

    def stored(self) -> tuple[Any, Any]:
        # APP: (level, end) as the app's settings hold them, raw.
        raise NotImplementedError("APP: stored")

    def store_legacy(self, deep: bool, minutes_from_now: int) -> None:
        # APP: write a level the way the older version did (its keys, names and form of the end).
        raise NotImplementedError("APP: store_legacy")

    def environment(self, value: str) -> AbstractContextManager[None]:
        # APP: the app's <APP>_LOG_LEVEL reads ``value`` while open.
        raise NotImplementedError("APP: environment")

    def legacy_lines(self) -> list[LegacyLine]:
        # APP: lines copied from a real file of the older version, with what they mean.
        raise NotImplementedError("APP: legacy_lines")

    def secrets(self) -> list[Secret]:
        # APP: one message for each of the app's key prefixes and token paths, with the value made at run time.
        raise NotImplementedError("APP: secrets")
