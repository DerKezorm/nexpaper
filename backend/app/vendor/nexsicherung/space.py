"""The card "Speicher": what the app takes on the disk, by part, how full the disk is, and whether the data lies on a
network share.

* ``footprint`` measures the data folder at most once a minute (``forget`` after a copy is made or deleted), never
  following links, and stops counting after ``COUNT_SECONDS`` (the part says ``complete`` False).
* ``locate`` tells where a folder lies: on Linux from the mount table (``/proc/mounts``, the longest mount point that
  holds the path), on Windows from the drive type (``DRIVE_REMOTE``) and UNC paths; anything else is "unknown", no
  warning is made up and none withheld by a guess. SQLite keeps its data safe with the file system's locks, which NFS
  and SMB do not keep reliably: a database on a share can break without a word.
"""

from __future__ import annotations

import errno
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .config import current
from .model import Part, Where

FOOTPRINT_SECONDS = 60.0
COUNT_SECONDS = 15.0
#: Above this share of the disk in use the page warns (nexnotes, nextime, nexpaper: 90 %).
NEARLY_FULL = 0.9
FULL_CODES = frozenset({errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)})

_footprint: tuple[float, list[Part]] | None = None
_footprint_lock = threading.Lock()


def disk_full(error: BaseException) -> bool:
    """A full disk or quota, however deep in the chain of causes; SQLite says "database or disk is full"."""
    seen: BaseException | None = error
    depth = 0
    while seen is not None and depth < 20:
        if isinstance(seen, OSError) and seen.errno in FULL_CODES:
            return True
        if isinstance(seen, sqlite3.OperationalError) and "full" in str(seen):
            return True
        seen = getattr(seen, "orig", None) or seen.__cause__ or seen.__context__
        depth += 1
    return False


def _size_of(path: str, deadline: float) -> tuple[int, bool]:
    """The bytes of a file, or of everything below a folder; links are not followed, what vanishes meanwhile counts as
    nothing. Returns the size and whether it was counted to the end before ``deadline``."""
    total = 0
    stack = [path]
    while stack:
        if time.monotonic() > deadline:
            return total, False
        current_path = stack.pop()
        try:
            with os.scandir(current_path) as found:
                for entry in found:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except NotADirectoryError:
            try:
                total += os.stat(current_path, follow_symlinks=False).st_size
            except OSError:
                pass
        except OSError:
            continue
    return total, True


def measure(data_dir: Path, parts: dict[str, tuple[str, ...]], database_names: tuple[str, ...],
            backups: Path | None = None) -> list[Part]:
    """The top of ``data_dir`` by part: the database files, each part's names, the backups folder, the rest as
    ``other``. Parts without bytes are left out, except the database."""
    deadline = time.monotonic() + COUNT_SECONDS
    sizes: dict[str, int] = {"database": 0}
    complete: dict[str, bool] = {}
    owner: dict[str, str] = {name: "database" for name in database_names}
    for key, names in parts.items():
        for name in names:
            owner[name] = key
    if backups is not None and backups.parent == data_dir:
        owner.setdefault(backups.name, "backups")
    try:
        with os.scandir(data_dir) as found:
            top = [(entry.name, entry.path) for entry in found if not entry.is_symlink()]
    except OSError:
        top = []
    for name, full in top:
        key = owner.get(name, "other")
        size, whole = _size_of(full, deadline)
        sizes[key] = sizes.get(key, 0) + size
        complete[key] = complete.get(key, True) and whole
    if backups is not None and backups.parent != data_dir and backups.is_dir():
        size, whole = _size_of(str(backups), deadline)
        sizes["backups"] = sizes.get("backups", 0) + size
        complete["backups"] = whole
    order = ["database", *parts.keys(), "backups", "other"]
    seen: list[str] = []
    for key in order:
        if key not in seen:
            seen.append(key)
    return [Part(key, sizes.get(key, 0), "", complete.get(key, True)) for key in seen
            if key == "database" or sizes.get(key, 0) > 0]


def footprint() -> list[Part]:
    """What the app takes, by part: the app's ``parts`` hook, or the data folder measured by ``AppConfig.parts``; at
    most once a minute."""
    global _footprint
    with _footprint_lock:
        if _footprint is not None and time.monotonic() - _footprint[0] < FOOTPRINT_SECONDS:
            return _footprint[1]
        config = current()
        given = config.hooks.parts()
        found = list(given) if given is not None else measure(config.data_dir, config.parts,
                                                              config.database_names(), config.backups)
        _footprint = (time.monotonic(), found)
        return found


def forget() -> None:
    """The next ``footprint`` measures again (a copy was made or deleted)."""
    global _footprint
    with _footprint_lock:
        _footprint = None


# --- Where a folder lies -------------------------------------------------------------------------------------------

NETWORK_TYPES = frozenset({
    "nfs", "nfs3", "nfs4", "cifs", "smb", "smb2", "smb3", "smbfs", "afs", "ncpfs", "coda", "fuse.sshfs", "fuse.rclone",
    "glusterfs", "fuse.glusterfs", "lustre", "ceph", "fuse.ceph",
})
DRIVE_REMOTE = 4
MOUNT_TABLE = Path("/proc/mounts")
UNKNOWN = Where("unknown")


def _unescape(field: str) -> str:
    """``/proc/mounts`` writes a space, a tab, a newline and a backslash in a mount point as octal (``\\040``)."""
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), field)


def in_table(path: str, table: str) -> Where:
    """The mount that holds ``path``: the longest mount point that contains it; a later line of the same mount point
    wins (a mount laid over another one)."""
    best: tuple[int, str] | None = None
    for line in table.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        mount, fstype = _unescape(fields[1]), fields[2]
        inside = mount == "/" or path == mount or path.startswith(mount.rstrip("/") + "/")
        if inside and (best is None or len(mount) >= best[0]):
            best = (len(mount), fstype)
    if best is None:
        return UNKNOWN
    return Where("network" if best[1].lower() in NETWORK_TYPES else "local", best[1])


def on_windows(path: str, drive_type: int | None) -> Where:
    """A UNC path is a share; a drive letter is one when Windows says ``DRIVE_REMOTE``."""
    if (path.startswith("\\\\") and not path.startswith("\\\\?\\")) or path.startswith("\\\\?\\UNC\\"):
        return Where("network", "smb")
    if drive_type is None:
        return UNKNOWN
    return Where("network", "smb") if drive_type == DRIVE_REMOTE else Where("local")


def _drive_type(path: str) -> int | None:  # pragma: no cover - needs Windows
    try:
        import ctypes

        drive = os.path.splitdrive(path)[0]
        if not drive:
            return None
        return int(ctypes.windll.kernel32.GetDriveTypeW(drive + "\\"))  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError):
        return None


def locate(path: Path, *, table: str | None = None, drive_type: int | None = None,
           windows: bool | None = None) -> Where:
    """Where ``path`` lies. The arguments stand in for the machine in a test; left out, the machine is asked."""
    is_windows = os.name == "nt" if windows is None else windows
    try:
        resolved = os.path.realpath(path)
    except (OSError, ValueError):
        resolved = str(path)
    if is_windows:
        return on_windows(resolved, drive_type if drive_type is not None else _drive_type(resolved))
    if table is None:
        try:
            table = MOUNT_TABLE.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return UNKNOWN
    return in_table(resolved, table)


def places() -> dict[str, Path]:
    config = current()
    found = dict(config.hooks.places())
    found.setdefault("data", config.data_dir)
    if config.database_path is not None:
        found.setdefault("database", config.database_path.parent)
    return found


def warn_at_start() -> dict[str, Where]:
    """At the start: one line in the log per place on a network share. Returns where each lies."""
    logger = logging.getLogger(current().logger.name)
    found = {}
    for key, path in places().items():
        where = locate(path)
        found[key] = where
        if where.network:
            logger.warning("The %s folder lies on a network share (%s). SQLite can lose data there; keep it on a "
                           "local disk.", key, where.fstype or "network")
    return found


def overview() -> dict[str, Any]:
    """The card "Speicher": what the app takes (sum and parts), the disk under the data folder, and the places on a
    network share."""
    config = current()
    parts = footprint()
    used = sum(part.bytes for part in parts if not part.within)
    try:
        disk = shutil.disk_usage(config.data_dir)
        total, disk_used, free = disk.total, disk.used, disk.free
    except OSError:
        total = disk_used = free = 0
    where = {key: locate(path) for key, path in places().items()}
    return {
        "app": config.app_name,
        "used": used,
        "parts": [part.__dict__ for part in parts],
        "complete": all(part.complete for part in parts),
        "total": total,
        "disk_used": disk_used,
        "free": free,
        "nearly_full": bool(total) and disk_used / total > NEARLY_FULL,
        "where": {key: {"kind": value.kind, "fstype": value.fstype} for key, value in where.items()},
        "network": sorted(key for key, value in where.items() if value.network),
    }
