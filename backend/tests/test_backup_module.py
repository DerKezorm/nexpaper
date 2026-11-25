"""Backups on the shared module sicherung: what was there before the module goes on (a restore staged by the version
before, the old ways and the new ones on the same list, the schedule of the settings page), and what the module adds
(a time of day, every month, the card "Speicher" with nexpaper's parts)."""

from __future__ import annotations

import json
import shutil
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import middleware
from app.db import SessionLocal
from app.models import Account
from app.services import backup_hooks, backups

from .conftest import make_account
from .papers import add_document, own_vault

PREFIX = "/api/v1/server/storage"


def accounts_now() -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(Account.id)).all())


def test_a_restore_staged_by_the_version_before_the_module_is_applied_at_the_start(operator: Account) -> None:
    """nexpaper 1.11 laid out ``restore-pending/`` with the database and the manifest (written last) and restarted; the
    first start of the new version puts it in place instead of throwing it away."""
    make_account("jule")
    path = backups.create(kind=backups.MANUAL)
    before = accounts_now()
    make_account("tom")
    pending = backups.pending_folder()
    shutil.rmtree(pending, ignore_errors=True)
    pending.mkdir(parents=True)
    with zipfile.ZipFile(path) as archive:
        (pending / "nexpaper.db").write_bytes(archive.read(backups.DATABASE_ENTRY))
        (pending / backups.MANIFEST).write_bytes(archive.read(backups.MANIFEST))
    assert backups.apply_pending() is True
    assert accounts_now() == before, "tom was made after the backup and is gone"
    assert not pending.exists() and not backups.failed_folder().exists()


def test_an_empty_archive_left_by_a_stopped_process_goes_at_the_start(operator: Account) -> None:
    folder = backups.folder()
    folder.mkdir(parents=True, exist_ok=True)
    empty = folder / "nexpaper-2020-01-01-000000.zip"
    empty.write_bytes(b"")
    unreadable = folder / "nexpaper-2020-01-02-000000.zip"
    unreadable.write_bytes(b"not an archive, but somebody's file")
    backups.apply_pending()
    assert not empty.exists()
    assert unreadable.exists(), "only an empty one goes; an unreadable one stays to be looked at"


def test_the_old_and_the_new_ways_show_the_same_backups(client: TestClient, operator: Account) -> None:
    old = client.post("/api/v1/backups", json={"note": "old way"}).json()["name"]
    new = client.post(f"{PREFIX}/backups", json={"note": "new way"}).json()["name"]
    listed_old = {entry["name"]: entry for entry in client.get("/api/v1/backups").json()}
    found = client.get(f"{PREFIX}/backups").json()
    listed_new = {entry["name"]: entry for entry in found["backups"]}
    assert {old, new} <= set(listed_old) and {old, new} <= set(listed_new)
    # The old list: the facts at the top as before (accounts, documents); the new one: under "facts".
    assert listed_old[new]["note"] == "new way" and listed_old[new]["accounts"] == 1
    assert listed_new[old]["facts"] == {"accounts": 1, "documents": 0}
    assert found["schedule"] == {"every": "daily", "time": "03:00", "keep": 7}
    brief = client.post(f"{PREFIX}/backups/{old}/check", json={}).json()
    assert brief["usable"] and brief["details"]["schema"] > 0 and brief["details"]["missing_documents"] == 0


def test_the_schedule_of_the_settings_page_and_of_the_module_are_one(client: TestClient, operator: Account) -> None:
    assert client.put("/api/v1/settings", json={"backup_schedule": "monthly", "backup_keep": 12}).status_code == 200
    assert client.get(f"{PREFIX}/backups").json()["schedule"] == {"every": "monthly", "time": "03:00", "keep": 12}
    saved = client.put(f"{PREFIX}/backups/schedule", json={"every": "weekly", "time": "22:15", "keep": 4})
    assert saved.status_code == 200
    settings = client.get("/api/v1/settings").json()
    assert (settings["backup_schedule"], settings["backup_keep"]) == ("weekly", 4)
    with SessionLocal() as db:
        assert backups.schedule(db) == "weekly" and backups.keep(db) == 4


def test_the_card_speicher_names_nexpapers_parts(client: TestClient, operator: Account) -> None:
    add_document(own_vault(operator), operator, "Rechnung")
    client.post(f"{PREFIX}/backups", json={})
    found = client.get(PREFIX).json()
    parts = {part["key"]: part for part in found["parts"]}
    assert {"documents", "originals", "database", "pages", "exports", "backups"} <= set(parts)
    assert parts["originals"]["within"] == "documents" and parts["documents"]["bytes"] > 0
    assert parts["backups"]["bytes"] > 0
    assert found["used"] == sum(part["bytes"] for part in found["parts"] if not part["within"])
    assert {"data", "database", "documents"} <= set(found["where"])
    # The old card of nexpaper stays its own route, in its own shape.
    old = client.get("/api/v1/storage").json()
    assert {"database", "documents", "backups", "files"} <= set(old)


def test_an_upload_on_the_new_way_may_be_as_large_as_on_the_old_one() -> None:
    assert middleware.LARGE_BODIES[f"{PREFIX}/backups/upload"] == middleware.LARGE_BODIES["/api/v1/backups/upload"]


def test_the_notice_of_a_failed_restore_opens_the_new_page() -> None:
    notice = backup_hooks.restore_failed_notice()
    assert notice.url == "/settings/storage" and notice.tag == "restore-failed"
    assert json.dumps(notice.texts, ensure_ascii=False).count("–") == 0
