"""Backups of nexpaper, from the shared module ``sicherung`` (``app/vendor/nexsicherung``, bauplaene/sicherung 1.0.0).
What goes into an archive and how it comes back is nexpaper's own (``services/backup_hooks.py``: the database, the
settings in it and the server's secrets, **not the documents**); the module runs the rest: names, list, schedule (off,
every night, every week, every month at a time of day), keeping the newest automatic copies, upload, download, the
check before a restore, the copy of the current state before it, staging and the swap at the next start, and the
operators told once when a restore could not be put in place.

This file keeps the names the rest of nexpaper calls (``from app.services import backups``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..vendor.nexsicherung import AUTOMATIC_KINDS, EVERY, MANUAL, SCHEDULED, UPDATE, Entry, archives, plan, restore
from ..vendor.nexsicherung.errors import BackupError
from . import backup_hooks, settings_service
from .backup_hooks import (
    DATABASE_ENTRY,
    MANIFEST,
    MANIFEST_MAX,
    SECRET_ENTRY,
    ManifestInvalid,
    _manifest,
)

__all__ = [
    "AUTOMATIC_KINDS",
    "DATABASE_ENTRY",
    "MANIFEST",
    "MANIFEST_MAX",
    "MANUAL",
    "NAME",
    "SCHEDULED",
    "SECRET_ENTRY",
    "UPDATE",
    "BackupError",
    "Brief",
    "Entry",
    "ManifestInvalid",
    "_manifest",
    "apply_pending",
    "check",
    "configure",
    "create",
    "entries",
    "failed_folder",
    "folder",
    "keep",
    "path_of",
    "pending_folder",
    "prune",
    "receive",
    "remove",
    "report_failed_restore",
    "run_forever",
    "schedule",
    "stage_restore",
    "temporary_upload",
    "tidy_at_start",
]

#: The names of nexpaper's archives, as before the module (the module's ``name_pattern`` for ``nexpaper``).
NAME = re.compile(r"^nexpaper-\d{4}-\d{2}-\d{2}-\d{6}(-\d+)?(-upload)?\.zip$")

configure = backup_hooks.configure
create = archives.create
entries = archives.entries
folder = archives.folder
path_of = archives.path_of
prune = archives.prune
receive = archives.receive
remove = archives.remove
temporary_upload = archives.temporary_upload
tidy_at_start = archives.tidy_at_start
stage_restore = restore.stage_restore
apply_pending = restore.apply_pending
pending_folder = restore.pending_folder
failed_folder = restore.failed_folder
report_failed_restore = restore.report_failed_restore
run_forever = plan.run_forever


@dataclass
class Brief:
    """What a restore of an archive would do, in the shape nexpaper's callers knew before the module: what it holds,
    and whether it can be used. Made from the module's brief (its facts and the findings of ``backup_hooks``)."""

    name: str
    version: str
    created: str
    kind: str
    accounts: int
    database_ok: bool
    schema: int
    too_new: bool
    usable: bool
    documents: int = 0
    missing_documents: int = 0
    changed_documents: int = 0
    not_compared: int = 0
    newer_documents: int = 0
    rebuilds_index: bool = False
    revived_devices: int = 0
    revived_keys: int = 0
    revived_links: int = 0
    revived_link_documents: int = 0
    revived_pdf_passwords: int = 0
    revived_upload_requests: int = 0


def check(name: str, *, hash_seconds: float | None = None, viewer: Any = None) -> Brief:
    """The trial run of the archive ``name`` (``restore.check``), with the files on the disk read for at most
    ``hash_seconds`` (default ``backup_hooks.HASH_SECONDS``)."""
    if hash_seconds is None:
        found = restore.check(name, viewer=viewer)
    else:
        with backup_hooks.reading_files_for(hash_seconds):
            found = restore.check(name, viewer=viewer)
    details = found.details
    schema = int(details.get("schema") or 0)
    from .. import db

    counts = {key: details[key] for key in (
        "documents", "missing_documents", "changed_documents", "not_compared", "newer_documents", "rebuilds_index",
        "revived_devices", "revived_keys", "revived_links", "revived_link_documents", "revived_pdf_passwords",
        "revived_upload_requests",
    ) if key in details}
    return Brief(
        name=found.name, version=found.version, created=found.created, kind=found.kind,
        accounts=int(found.facts.get("accounts") or 0), database_ok=found.database_ok, schema=schema,
        too_new=found.too_new or schema > db.SCHEMA_VERSION, usable=found.usable, **counts,
    )


def schedule(db: Any) -> str:
    """off, daily, weekly or monthly, as the settings hold it (``backup_schedule``)."""
    value = settings_service.get(db, "backup_schedule")
    return value if value in EVERY else "off"


def keep(db: Any) -> int:
    value = settings_service.get(db, "backup_keep")
    return value if isinstance(value, int) and 1 <= value <= 365 else backup_hooks.DEFAULT_KEEP


configure()
