"""What the contract tests ask of an app: the ``StandardAdapter`` the app's adapter extends, and small helpers.

The contract tests run the module inside the app: the app's own start (``configure`` with its folder, its built-in
languages, its template), its own check of operators and readers, its own form of a refusal, the routes mounted from
``nexsprachen.api``. They never change; the app fills in its adapter (``backend/tests/nexsprachen_adapter.py``).
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any


class StandardAdapter:
    """Defaults; every method marked ``APP`` is the app's to write."""

    #: Where the vendored package lives in the app.
    package = "app.vendor.nexsprachen"
    #: Where the app mounts ``nexsprachen.api.router`` (nexnotes ``/api/locales``).
    prefix = "/api/locales"
    #: Further prefixes the same routes are mounted under (an app's older way, or a newer one beside it).
    also: tuple[str, ...] = ()
    #: The languages the app ships: code -> name in itself, in the app's order (``AppConfig.built_in``).
    built_in: dict[str, str] = {"de": "Deutsch", "en": "English"}
    #: Whether anybody may read the list, the texts and the template (``reader=None``), or only who is signed in.
    public_read = True
    #: Whether the server hands out the template (``AppConfig.template``); False when the app's page makes it.
    has_template = True
    #: Where the app describes its interface (nexpaper ``/api/v1/openapi.json``).
    openapi_path = "/openapi.json"
    #: The names the app gave ``api.router`` for ``prefix`` so that its description stays as it was (the same dicts:
    #: ``operation_ids``, ``summaries`` by route, ``schema_names`` by schema); empty: FastAPI's names of the module.
    operation_ids: dict[str, str] = {}
    summaries: dict[str, str] = {}
    schema_names: dict[str, str] = {}

    def start(self) -> None:
        """APP: an empty app with a fresh data folder, started as in production (``nexsprachen.configure``, the
        routes mounted)."""
        raise NotImplementedError("APP: start")

    def stop(self) -> None:
        """APP: close the database, remove temporary folders."""

    def client(self, role: str) -> Any:
        """APP: a ``TestClient`` of the app: ``"operator"`` signed in as an operator, ``"member"`` signed in as an
        account without that role, ``"anonymous"`` without a session."""
        raise NotImplementedError("APP: client")

    def folder(self) -> Path:
        """The app's folder of own languages (``AppConfig.folder``); by default what the module says."""
        return contract_package(self).locales_dir()

    def refusal(self, response: Any) -> tuple[str, dict[str, Any]]:
        """The code of a refusal and its values, from the app's form (default nexnotes':
        ``{"detail": {"code", "message", …values}}``)."""
        detail = response.json().get("detail")
        assert isinstance(detail, dict), response.text
        values = {key: value for key, value in detail.items() if key not in ("code", "message")}
        return str(detail.get("code")), values


def contract_package(adapter: Any) -> ModuleType:
    package = importlib.import_module(adapter.package)
    importlib.import_module(f"{adapter.package}.api")
    return package


def upload(client: Any, prefix: str, code: str, body: bytes) -> Any:
    return client.put(f"{prefix}/{code}", content=body, headers={"content-type": "application/json"})


def files_in(folder: Path) -> list[str]:
    """Every name in the folder, passing files of an upload included."""
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []
