"""What only nexpaper's own user may read: the key, the database, the backups, the log.

A backup holds ``secret.key`` and the database (password hashes, sealed secrets, the filing). Written with the
container's default umask they were readable for every user of the machine (0644 in 0755 folders): on a NAS share or
a host with other users, anybody could copy them.

On Windows ``chmod`` knows only read-only; there everything here does nothing.
"""

from __future__ import annotations

import os
from pathlib import Path

from .config import get_settings

FILE_MODE = 0o600
FOLDER_MODE = 0o700


def tighten(path: Path) -> None:
    """Only the owner, for a file or a folder; quietly nothing where the system does not allow it."""
    try:
        os.chmod(path, FOLDER_MODE if path.is_dir() else FILE_MODE)
    except OSError:
        pass


def new_file(path: Path) -> None:
    """Creates an empty file only the owner may read, before anything is written into it."""
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, FILE_MODE)
    os.close(descriptor)
    tighten(path)


def tighten_all() -> None:
    """At start: the keys, the database with its journal, the backups and the log."""
    data = get_settings().data_dir
    for name in ("secret.key", "nexpaper.db", "nexpaper.db-wal", "nexpaper.db-shm"):
        if (data / name).exists():
            tighten(data / name)
    for folder in (data / "backups", data / "logs", data / "keys"):
        if not folder.is_dir():
            continue
        tighten(folder)
        for inner in folder.rglob("*"):
            tighten(inner)
