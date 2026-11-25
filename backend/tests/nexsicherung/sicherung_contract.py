"""What the contract tests ask of an app: the ``StandardAdapter`` the app's adapter extends, and small helpers.

The contract tests run the module against the app's real hooks, real routes and real data: a backup made, changed,
checked, restored at the (simulated) next start, downloaded and brought in again, a backup of the app's older version
restored, the old routes in their old shapes. They never change; the app fills in its adapter
(``backend/tests/nexsicherung_adapter.py``).
"""

from __future__ import annotations

import base64
import importlib
from pathlib import Path
from types import ModuleType
from typing import Any


class StandardAdapter:
    """Defaults; every method marked ``APP`` is the app's to write."""

    #: Where the vendored package lives in the app.
    package = "app.vendor.nexsicherung"
    #: The module's routes as the app mounts them (``routes.router(prefix=...)``).
    prefix = "/api/server/storage"
    #: The app's old routes (``routes.legacy_router``) and their password header; empty: the app had none.
    legacy_prefix = "/api/backups"
    legacy_header = ""

    def start(self) -> None:
        """APP: an empty app in a fresh data folder, started as in production (``configure``, ``apply_pending``, the
        database), with an operator who has a password (``password``) and a member."""
        raise NotImplementedError("APP: start")

    def stop(self) -> None:
        """APP: close the database, remove temporary folders."""

    @property
    def password(self) -> str:
        """APP: the operator's password."""
        raise NotImplementedError("APP: password")

    def operator(self) -> Any:
        """APP: a test client (``fastapi.testclient.TestClient``) signed in as the operator; after a restore a new
        sign-in (the restore ended every session)."""
        raise NotImplementedError("APP: operator")

    def member(self) -> Any:
        """APP: a test client signed in as an account that is not the operator."""
        raise NotImplementedError("APP: member")

    def restart(self) -> None:
        """APP: what the next start does after a staged restore (``restore = "restart"``): close the database, then
        the app's start (``apply_pending`` before the database opens). For ``restore = "now"`` nothing."""
        raise NotImplementedError("APP: restart")

    def add_content(self, label: str) -> None:
        """APP: add something the app keeps, with a file where the app keeps files (a note with an attachment, an
        event, a document), named by ``label``."""
        raise NotImplementedError("APP: add_content")

    def content(self) -> Any:
        """APP: what the app keeps, comparable with ``==`` (titles and the hashes of the files)."""
        raise NotImplementedError("APP: content")

    def legacy_archive(self) -> tuple[Path, Any]:
        """APP: a backup made by the app's code **before the module** (its old ``create``, or a file kept from it),
        lying in the backups folder under its old name, and the ``content()`` a restore of it brings back. The app's
        content is changed after it, so that a restore shows."""
        raise NotImplementedError("APP: legacy_archive")

    def settings_schedule(self) -> tuple[str, int]:
        """APP: the schedule and the number kept as the app's own settings route reads them (``GET /api/settings``
        ``backup_schedule``, ``backup_keep``; nexmail ``sicherung_takt``…), mapped to the module's words."""
        raise NotImplementedError("APP: settings_schedule")


def package_of(adapter: Any) -> ModuleType:
    package = importlib.import_module(adapter.package)
    for name in ("archives", "restore", "plan", "space", "routes"):
        importlib.import_module(f"{adapter.package}.{name}")
    return package


def header(password: str) -> str:
    return base64.b64encode(password.encode("utf-8")).decode("ascii")


def code_of(response: Any) -> str:
    """The error code of a refusal: ``{"detail": {"code"}}``, or the app's own shape with a ``code`` somewhere."""
    try:
        body = response.json()
    except ValueError:
        return ""
    detail = body.get("detail", body) if isinstance(body, dict) else {}
    if isinstance(detail, dict):
        return str(detail.get("code") or detail.get("fehler") or "")
    return ""
