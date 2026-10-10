"""What the data folder holds and how much room is left: the numbers of the storage card in the settings.

* the database (with its write-ahead file) and, of it, the search index;
* the documents (``dokumente/``), the cache of page pictures, the exports and the backups;
* the free room on the disk the data folder lies on;
* where the database and the documents lie (a local disk or a network share, ``services/mounts.py``).

Counting the files of a large archive takes a moment, so a folder is counted at most once in ``REMEMBER_SECONDS`` and
never for longer than ``COUNT_SECONDS``; a count that did not finish says so (``complete`` false) and shows what it
had. The index is measured in the database itself, through the blocks of its tables, which costs a look at the table
and not at the data.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ..config import get_settings
from . import backups, exports, mounts, pages, storage

logger = logging.getLogger("nexpaper.space")

#: How long a count of a folder is believed, and how long a count may take.
REMEMBER_SECONDS = 300.0
COUNT_SECONDS = 15.0
#: The tables of the search index: the two indexes with the tables SQLite keeps beside them, and the list of what is in.
INDEX_TABLES = ("doc_fts", "doc_tri")
_lock = threading.Lock()
_remembered: dict[str, tuple[float, int, int, bool]] = {}


def forget() -> None:
    with _lock:
        _remembered.clear()


def count_folder(path: Path, *, limit_seconds: float = COUNT_SECONDS) -> tuple[int, int, bool]:
    """``(bytes, files, complete)`` of everything under ``path``; links are not followed. ``complete`` is false when the
    time ran out."""
    deadline = time.monotonic() + limit_seconds
    total = files = 0
    pending = [str(path)]
    while pending:
        if time.monotonic() > deadline:
            return total, files, False
        folder = pending.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, files, True


def folder_size(path: Path, *, now: float | None = None, limit_seconds: float = COUNT_SECONDS) -> dict[str, Any]:
    """A folder's size, counted at most every ``REMEMBER_SECONDS``."""
    moment = time.monotonic() if now is None else now
    key = str(path)
    with _lock:
        known = _remembered.get(key)
    if known is not None and moment - known[0] < REMEMBER_SECONDS:
        return {"bytes": known[1], "files": known[2], "complete": known[3]}
    size, files, complete = count_folder(path, limit_seconds=limit_seconds)
    with _lock:
        _remembered[key] = (moment, size, files, complete)
    return {"bytes": size, "files": files, "complete": complete}


def database_bytes() -> int:
    database = get_settings().database_path
    total = 0
    for suffix in ("", "-wal", "-shm"):
        try:
            total += database.with_name(database.name + suffix).stat().st_size
        except OSError:
            continue
    return total


def index_bytes() -> int | None:
    """The size of the search index, or None when it cannot be told (no index tables yet)."""
    connection = sqlite3.connect(f"file:{get_settings().database_path.as_posix()}?mode=ro", uri=True, timeout=5)
    try:
        total = 0
        found = False
        for table in INDEX_TABLES:
            for part in ("data", "docsize"):
                name = f"{table}_{part}"
                exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,))
                if exists.fetchone() is None:
                    continue
                found = True
                column = "block" if part == "data" else "sz"
                row = connection.execute(f'SELECT coalesce(sum(length({column})), 0) FROM "{name}"').fetchone()  # noqa: S608
                total += int(row[0] or 0)
        return total if found else None
    except sqlite3.DatabaseError:
        return None
    finally:
        connection.close()


def originals_bytes() -> int:
    """What the originals add up to, by the sizes noted when they came in (no file is read)."""
    from sqlalchemy import func, select

    from ..db import SessionLocal
    from ..models import Version

    with SessionLocal() as db:
        return int(db.scalar(select(func.coalesce(func.sum(Version.size), 0))) or 0)


def where(path: Path) -> dict[str, Any]:
    found = mounts.locate(path)
    return {"kind": found.kind, "fstype": found.fstype, "network": found.network}


def free_bytes(path: Path) -> tuple[int, int]:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return 0, 0
    return usage.free, usage.total


def overview() -> dict[str, Any]:
    """Everything the card shows."""
    settings = get_settings()
    data = settings.data_dir
    documents = folder_size(storage.root())
    cache = folder_size(pages.cache_root())
    exported = folder_size(exports.folder())
    saved = folder_size(backups.folder())
    free, total = free_bytes(data)
    return {
        "database": {"bytes": database_bytes(), "index_bytes": index_bytes(),
                     "where": where(settings.database_path.parent)},
        "documents": {**documents, "originals_bytes": originals_bytes(),
                      "where": where(storage.root() if storage.root().exists() else data)},
        "cache": cache,
        "exports": exported,
        "backups": saved,
        "free_bytes": free,
        "total_bytes": total,
        "data": {"where": where(data)},
    }
