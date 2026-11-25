"""nexschluessel contract tests: the app's adapter. Copied once by the module's ``tools/sync.py copy <app>`` to
``backend/tests/nexschluessel_adapter.py``; from then on it is the app's file.

Fill in every place marked ``APP:``. The contract tests in ``backend/tests/nexschluessel/`` (same in every app, never
edit them) call only what is here and in ``StandardAdapter``. Worked examples: the module's
``tests-fuer-apps/reference/nexschluessel_adapter.py`` (an app like nexnotes) and ``tests/mail_like_adapter.py`` (an
app like nexmail). Run them with ``pytest tests/nexschluessel``. Keys are made at run time; none is written into this
file.

The heart of it is ``legacy_keys`` and ``make_legacy``: every form of key the app made before the module (each kind,
each prefix, the old forms that still work, the connectors of AI tools), written exactly the way the older version
wrote it. The tests present each to the app's real routes before and after the module touched it.
"""

from __future__ import annotations

from typing import Any

from schluessel_contract import LegacyKey, StandardAdapter


class Adapter(StandardAdapter):
    # APP: where the vendored package lives and where the module's routes are mounted.
    package = "app.vendor.nexschluessel"
    prefix = "/api/connections"

    def start(self) -> None:
        # APP: an empty app (fresh database), started as in production; accounts "owner", "other" (members with a
        # password, no second factor, each with at least one area where keys are limited to areas) and "operator".
        raise NotImplementedError("APP: start")

    def stop(self) -> None:
        # APP: close the database, remove temporary folders.
        pass

    def config(self) -> Any:
        # APP: the app's nexschluessel.AppConfig.
        raise NotImplementedError("APP: config")

    def client(self, role: str) -> Any:
        # APP: a TestClient as "owner", "other", "operator" (browser sessions) or "anonymous".
        raise NotImplementedError("APP: client")

    def legacy_keys(self) -> list[LegacyKey]:
        # APP: every form of key the older version made, e.g. LegacyKey("API token", "api", "ntk_", "read").
        raise NotImplementedError("APP: legacy_keys")

    def make_legacy(self, spec: LegacyKey, *, account: str = "owner", expired: bool = False) -> str:
        # APP: write it the old way (the old service function, or the row as it was written) and return the secret.
        raise NotImplementedError("APP: make_legacy")

    def probe(self, kind: str, secret: str) -> int:
        # APP: the status of a real route of the app that takes keys of this kind (GET /api/v1/me, POST /api/mcp).
        raise NotImplementedError("APP: probe")

    def owe_factor(self) -> None:
        # APP: the operator requires a second factor; the owner has none.
        raise NotImplementedError("APP: owe_factor")

    def foreign_area(self) -> Any:
        # APP: an area of "other" the owner cannot reach (only where keys are limited to areas).
        raise NotImplementedError("APP: foreign_area")
