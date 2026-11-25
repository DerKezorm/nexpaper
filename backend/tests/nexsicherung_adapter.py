"""nexsicherung contract tests: the app's adapter. Copied once by the module's ``tools/sync.py copy <app>`` to
``backend/tests/nexsicherung_adapter.py``; from then on it is the app's file.

Fill in every place marked ``APP:``. The contract tests in ``backend/tests/nexsicherung/`` (same in every app, never
edit them) call only what is here and in ``StandardAdapter``. A worked example is the module's
``tests-fuer-apps/reference/nexsicherung_adapter.py`` with ``refapp.py``. Run them with ``pytest tests/nexsicherung``.
Test values are made at run time; no password is written into this file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sicherung_contract import StandardAdapter


class Adapter(StandardAdapter):
    # APP: where the vendored package lives, where the app mounts the module's routes, its old routes and header.
    package = "app.vendor.nexsicherung"
    prefix = "/api/server/storage"
    legacy_prefix = "/api/backups"
    legacy_header = "x-APP-password"

    def start(self) -> None:
        # APP: a fresh data folder, the app started as in production, an operator with a password and a member.
        raise NotImplementedError("APP: start")

    def stop(self) -> None:
        # APP: close the database, remove the temporary folder.
        pass

    @property
    def password(self) -> str:
        # APP: the operator's password.
        raise NotImplementedError("APP: password")

    def operator(self) -> Any:
        # APP: a TestClient signed in as the operator (a new sign-in after a restore).
        raise NotImplementedError("APP: operator")

    def member(self) -> Any:
        # APP: a TestClient signed in as a member.
        raise NotImplementedError("APP: member")

    def restart(self) -> None:
        # APP: close the database, then the app's start (apply_pending before the database opens).
        raise NotImplementedError("APP: restart")

    def add_content(self, label: str) -> None:
        # APP: something the app keeps, with a file where it keeps files.
        raise NotImplementedError("APP: add_content")

    def content(self) -> Any:
        # APP: what the app keeps, comparable with ==.
        raise NotImplementedError("APP: content")

    def legacy_archive(self) -> tuple[Path, Any]:
        # APP: a backup made by the app's code before the module, in the backups folder, and the content it holds.
        raise NotImplementedError("APP: legacy_archive")

    def settings_schedule(self) -> tuple[str, int]:
        # APP: backup_schedule and backup_keep as the app's settings route reads them, in the module's words.
        raise NotImplementedError("APP: settings_schedule")
