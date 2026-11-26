"""nexsicherung contract tests: nexpaper's adapter (copied once from the module's template, now nexpaper's file).

The contract tests in ``backend/tests/nexsicherung/`` run the module against nexpaper's real hooks
(``app/services/backup_hooks.py``), its routes (``/api/v1/server/storage`` and the old ``/api/v1/backups``) and its
data. The database and data folder are the ones of the test session (``tests/conftest.py`` empties the database, the
documents and the backups before every test). A backup of nexpaper holds the database and the key, never the
documents: what a restore brings back is the documents' entries (their titles and the checksums noted for their files).
"""

from __future__ import annotations

import json
import os
import secrets
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sicherung_contract import StandardAdapter

from app.vendor.nexsicherung.routes import former_names


class Adapter(StandardAdapter):
    package = "app.vendor.nexsicherung"
    prefix = "/api/v1/server/storage"
    legacy_prefix = "/api/v1/backups"
    legacy_header = "x-nexpaper-password"
    # E53: the names nexpaper gives the routers for the description, exactly as given (routers/backups.py).
    _names = former_names(legacy_prefix)
    operation_ids: dict[str, str] = _names["operation_ids"]
    summaries: dict[str, str] = _names["summaries"]
    schema_names: dict[str, str] = _names["schema_names"]
    # E53, step 9: the old routes check {name} with nexpaper's pattern and length again (former_names gives it).
    name_pattern = bool(_names.get("name_pattern"))
    openapi_path = "/api/v1/openapi.json"

    def start(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app
        from app.models import MEMBER, OPERATOR
        from tests.conftest import TAB, make_account

        self._password = secrets.token_urlsafe(12)
        self._operator = make_account("olli", OPERATOR, password=self._password)
        self._member = make_account("mika", MEMBER, password=secrets.token_urlsafe(12))
        self._clients: list[Any] = []
        self._main = TestClient(app, base_url="http://testserver", headers=TAB)
        self._main.__enter__()

    def stop(self) -> None:
        for client in self._clients:
            client.close()
        self._main.__exit__(None, None, None)

    @property
    def password(self) -> str:
        return self._password

    def _client(self, account: Any) -> Any:
        from tests.conftest import new_client

        client = new_client(account)
        self._clients.append(client)
        return client

    def operator(self) -> Any:
        return self._client(self._operator)

    def member(self) -> Any:
        return self._client(self._member)

    def restart(self) -> None:
        """The next start: the database closed, the staged restore swapped in, the database opened and checked."""
        from app.db import engine, init_db
        from app.services import backups

        engine.dispose()
        backups.configure()
        backups.tidy_at_start()
        backups.apply_pending()
        init_db()

    def start_again(self) -> None:
        """nexpaper's start on the same data folder: the same steps as ``restart`` (``main.lifespan``)."""
        self.restart()

    def add_content(self, label: str) -> None:
        """A document of the operator with its file (as an upload leaves it: the file in the document folder)."""
        from tests.papers import PDF, add_document, own_vault

        add_document(own_vault(self._operator), self._operator, label, content=PDF + label.encode() * 50)

    def content(self) -> Any:
        from app.db import SessionLocal
        from app.models import Document, Version

        with SessionLocal() as db:
            rows = db.query(Document.title, Version.sha256).join(Version, Version.document_id == Document.id)
            return sorted((title, sha) for title, sha in rows)

    def legacy_archive(self) -> tuple[Path, Any]:
        """A backup as nexpaper 1.11.0 made it (``services/backups.create`` before the module): the same members and
        manifest, version 1.11.0, the old name."""
        self.add_content("from the old version")
        held = self.content()
        from app.services import backup_hooks, backups

        folder = backups.folder()
        folder.mkdir(parents=True, exist_ok=True)
        moment = datetime(2026, 10, 1, 3, 0, 0, tzinfo=UTC)
        target = folder / f"nexpaper-{moment.strftime('%Y-%m-%d-%H%M%S')}.zip"
        target.touch()
        backup_hooks.write_archive(target, kind="scheduled", note="", created=moment.isoformat(timespec="seconds"),
                                   version="1.11.0")
        # 1.11.0 wrote the manifest as its dataclass: every field, in this order.
        with zipfile.ZipFile(target) as archive:
            manifest = json.loads(archive.read(backup_hooks.MANIFEST))
            members = [(info, archive.read(info)) for info in archive.infolist() if info.filename != backup_hooks.MANIFEST]
        fields = ("version", "created", "kind", "note", "accounts", "bytes", "sha256", "documents", "with_index")
        old = {key: manifest[key] for key in fields}
        os.remove(target)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for info, data in members:
                archive.writestr(info, data)
            archive.writestr(backup_hooks.MANIFEST, json.dumps(old, ensure_ascii=False))
        return target, held

    def settings_schedule(self) -> tuple[str, int]:
        found = self.operator().get("/api/v1/settings").json()
        return found["backup_schedule"], found["backup_keep"]
