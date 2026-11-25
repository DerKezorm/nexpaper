"""Helpers for the module and for the app's hooks: files only the owner may read, names nobody else takes, the
database through SQLite's backup API, the check of a database, hashes, members of an archive within limits.

All of them were written several times in the apps (nexnotes, nexpaper, nexdiary, nextime …); an app's ``pack`` and
``check`` should use these instead of its own copies, so that a fix reaches every app.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import time
import zipfile
import zlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import BackupError

FILE_MODE = 0o600
FOLDER_MODE = 0o700
SQLITE_HEADER = b"SQLite format 3\x00"
CHUNK = 1024 * 1024
#: What zipfile raises for a member it cannot read (a flipped byte, a cut-off file, an unknown method). A flipped
#: byte in a deflated member often reaches zlib before the CRC check: zipfile hands on ``zlib.error`` as it is.
DAMAGE = (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, NotImplementedError, RuntimeError, ValueError,
          zlib.error)


# --- Files only the owner may read ----------------------------------------------------------------------------------


def tighten(path: Path) -> None:
    """Only the owner, for a file or a folder; quietly nothing where the system does not allow it (Windows)."""
    try:
        os.chmod(path, FOLDER_MODE if path.is_dir() else FILE_MODE)
    except OSError:
        pass


def private_folder(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    tighten(path)
    return path


def new_file(path: Path) -> None:
    """An empty file only the owner may read, before a byte is in it."""
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, FILE_MODE)
    os.close(descriptor)
    tighten(path)


def reserve(folder: Path, stem: str, end: str) -> Path:
    """A new empty file ``<stem><end>``, or ``<stem>-2<end>``, ``-3`` …: created with ``O_EXCL``, so two processes in
    the same second never take the same name."""
    number = 1
    while True:
        name = f"{stem}{end}" if number == 1 else f"{stem}-{number}{end}"
        try:
            descriptor = os.open(folder / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, FILE_MODE)
        except FileExistsError:
            number += 1
            continue
        os.close(descriptor)
        tighten(folder / name)
        return folder / name


def settle(work: Path, folder: Path, stem: str, end: str) -> Path:
    """Move the whole file ``work`` to the first free name ``<stem><end>``, ``<stem>-2<end>`` … in ``folder`` and
    return it. No name is taken before the file is whole, and none is ever overwritten: a hard link, which fails on a
    name that is taken (then ``work`` goes), on Windows a rename, which refuses one. Where the file system has no hard
    links (some shares, FAT), a rename onto a name that is free."""
    number = 1
    while True:
        final = folder / (f"{stem}{end}" if number == 1 else f"{stem}-{number}{end}")
        try:
            if os.name == "nt":
                os.rename(work, final)
                return final
            try:
                os.link(work, final)
            except FileExistsError:
                raise
            except OSError:
                if final.exists():
                    raise FileExistsError(final) from None
                os.replace(work, final)
                return final
            work.unlink()
            return final
        except FileExistsError:
            number += 1


def stamp(moment: datetime) -> str:
    """``2026-11-25-031500`` in UTC, the stamp in every archive's name."""
    return moment.astimezone(UTC).strftime("%Y-%m-%d-%H%M%S")


def remove_tree(folder: Path, *, tries: int = 5) -> bool:
    """A folder and everything in it, read-only files too (Windows refuses those to ``rmtree``); a few tries, because a
    virus scanner may hold a file for a moment. Returns whether it is gone."""

    def writable_then_again(function: Callable[[str], Any], path: str, _error: BaseException) -> None:
        try:
            os.chmod(path, 0o700)
            function(path)
        except OSError:
            pass

    for attempt in range(tries):
        if not folder.exists():
            return True
        shutil.rmtree(folder, onexc=writable_then_again)
        if not folder.exists():
            return True
        time.sleep(0.2 * (attempt + 1))
    return not folder.exists()


# --- The database ---------------------------------------------------------------------------------------------------


def copy_database(source: Path, target: Path) -> None:
    """The database through SQLite's backup API, never as a file: in WAL mode a file copy misses what still sits in the
    ``-wal`` side file. The copy is in journal mode DELETE, one file. Never opens the running database in a way that
    blocks the app (the backup API reads page by page)."""
    origin = sqlite3.connect(source)
    copy = sqlite3.connect(target)
    try:
        origin.backup(copy)
        copy.execute("PRAGMA journal_mode=DELETE")
        copy.commit()
    finally:
        copy.close()
        origin.close()


def database_whole(path: Path, *, ignore: re.Pattern[str] | None = None) -> bool:
    """Whether the file is an SQLite database that passes ``PRAGMA integrity_check``. ``ignore``: lines of the check
    that do not count (a search index the restore builds anew, e.g. ``search_index_v\\d+``). Raises
    ``sqlite3.OperationalError`` and ``OSError`` for a file the system does not let it read (``read_database``
    tries again)."""
    with open(path, "rb") as handle:
        if handle.read(16) != SQLITE_HEADER:
            return False
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        found = [str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()]
    except sqlite3.OperationalError:
        raise
    except sqlite3.DatabaseError:
        return False
    finally:
        connection.close()
    if found == ["ok"]:
        return True
    return ignore is not None and all(ignore.search(line) for line in found)


def read_database(archive: zipfile.ZipFile, member: str, scratch: Path, *, limit: int,
                  ignore: re.Pattern[str] | None = None, tries: int = 3, pause: float = 0.25) -> bool:
    """Unpack the database ``member`` to ``scratch`` (within ``limit`` bytes) and check it with ``database_whole``.
    A file the system does not let SQLite read for a moment (a virus scanner holding the fresh copy: ``disk I/O
    error``, ``database is locked``) is read again from a new copy, up to ``tries`` times (nexnotes, nextime). The
    scratch file is the caller's to remove; it stays for the caller to read further (the counts of a restore)."""
    for attempt in range(tries):
        if attempt:
            time.sleep(pause * attempt)
        try:
            extract(archive, member, scratch, limit=limit)
            return database_whole(scratch, ignore=ignore)
        except (sqlite3.OperationalError, OSError):
            # Not damage, a file held for a moment: a new copy, after a pause.
            try:
                scratch.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        except DAMAGE:
            return False
    return False


# --- Hashes and members ---------------------------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_member(archive: zipfile.ZipFile, member: str | zipfile.ZipInfo, *, limit: int) -> tuple[int, str]:
    """Size and sha256 of a member as it unpacks, stopping past ``limit`` bytes (``backup_too_large``): the size in the
    archive's directory may lie (a zip bomb)."""
    digest = hashlib.sha256()
    size = 0
    with archive.open(member) as handle:
        while chunk := handle.read(CHUNK):
            size += len(chunk)
            if size > limit:
                raise BackupError("backup_too_large", "a member of the archive is larger than allowed")
            digest.update(chunk)
    return size, digest.hexdigest()


def extract(archive: zipfile.ZipFile, member: str | zipfile.ZipInfo, target: Path, *, limit: int) -> int:
    """One member into ``target`` (a file only the owner may read), stopping past ``limit`` bytes. Returns the size."""
    new_file(target)
    size = 0
    try:
        with archive.open(member) as source, open(target, "wb") as sink:
            while chunk := source.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise BackupError("backup_too_large", "a member of the archive is larger than allowed")
                sink.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return size


#: A member name that could leave the folder it is unpacked into, or is not portable: never unpacked.
_UNSAFE = re.compile(r"(^|/)\.\.(/|$)|\\|^/|^[A-Za-z]:|[\x00-\x1f]")


def safe_member(name: str, prefix: str, pattern: re.Pattern[str] | None = None) -> str | None:
    """The part of ``name`` after ``prefix`` when it is a plain relative path that stays inside (no ``..``, no
    backslash, no drive, no control character) and, with ``pattern``, matches it; else None."""
    if not name.startswith(prefix):
        return None
    rest = name[len(prefix):]
    if not rest or _UNSAFE.search(rest) or rest.endswith("/"):
        return None
    if pattern is not None and not pattern.fullmatch(rest):
        return None
    return rest


def read_small(archive: zipfile.ZipFile, member: str, *, limit: int = 64 * 1024) -> bytes:
    """A small member (a manifest, a key) read whole, never more than ``limit`` bytes."""
    with archive.open(member) as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise BackupError("backup_invalid", f"{member} is larger than {limit} bytes")
    return data


# --- Versions -------------------------------------------------------------------------------------------------------


def version_tuple(text: str) -> tuple[int, ...]:
    """``1.2.10`` as (1, 2, 10); anything that is not a number counts as 0."""
    parts = [int(part) if part.isdigit() else 0 for part in re.split(r"[.+-]", text or "")[:3]]
    return tuple(parts + [0] * (3 - len(parts)))


def newer(version: str, running: str) -> bool:
    """Whether an archive of ``version`` comes from a newer version than ``running``."""
    return version_tuple(version) > version_tuple(running)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
