"""Where a folder lies: on a disk of this machine or on a network share.

SQLite keeps its data safe with the locks of the file system. NFS and SMB/CIFS do not keep every promise a local disk
does, and a database on a share can lose data or break without a word. So nexpaper looks at where the data folder
(and with it the database) lies and says so, in the log at the start and on the storage card in the settings. The
documents themselves are plain files and may lie on a NAS.

* **Linux:** the mount table, ``/proc/mounts``. The mount that holds the path is the one with the longest mount point
  that is a parent of it; its file system type tells (``nfs``, ``nfs4``, ``cifs``, ``smb3`` ...).
* **Windows:** the type of the drive (``GetDriveTypeW``: ``DRIVE_REMOTE``), and paths that begin with ``\\\\``.
* Anything else (macOS, an unreadable table) is "unknown": no warning is made up, none is withheld by a guess.

The functions take the mount table or the drive type as arguments, so a test can say what the machine would say.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("nexpaper.mounts")

#: File system types that are network shares. ``fuse.sshfs`` and ``fuse.rclone`` are shares in a different coat.
NETWORK_TYPES = frozenset({
    "nfs", "nfs3", "nfs4", "cifs", "smb", "smb2", "smb3", "smbfs", "afs", "ncpfs", "coda", "fuse.sshfs", "fuse.rclone",
    "glusterfs", "fuse.glusterfs", "lustre", "ceph", "fuse.ceph",
})
DRIVE_REMOTE = 4
MOUNT_TABLE = Path("/proc/mounts")


@dataclass(frozen=True)
class Where:
    #: ``network``, ``local`` or ``unknown``.
    kind: str
    #: The file system type as the system calls it (``nfs4``), or empty.
    fstype: str = ""

    @property
    def network(self) -> bool:
        return self.kind == "network"


UNKNOWN = Where("unknown")


def _unescape(field: str) -> str:
    """``/proc/mounts`` writes a space, a tab, a newline and a backslash in a mount point as octal (``\\040``)."""
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), field)


def parse_table(text: str) -> list[tuple[str, str]]:
    """``(mount point, type)`` of every line of a mount table; a line that is not one is skipped."""
    found = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            found.append((_unescape(parts[1]), parts[2]))
    return found


def _is_inside(path: str, mount: str) -> bool:
    return mount == "/" or path == mount or path.startswith(mount.rstrip("/") + "/")


def in_table(path: str, table: str) -> Where:
    """The mount that holds ``path``, from the text of a mount table: the longest mount point that contains it. A later
    line of the same mount point wins (a mount laid over another one)."""
    best: tuple[int, str] | None = None
    for mount, fstype in parse_table(table):
        if _is_inside(path, mount) and (best is None or len(mount) >= best[0]):
            best = (len(mount), fstype)
    if best is None:
        return UNKNOWN
    return Where("network" if best[1].lower() in NETWORK_TYPES else "local", best[1])


def on_windows(path: str, drive_type: int | None) -> Where:
    """A UNC path is a share; a drive letter is one when Windows says ``DRIVE_REMOTE``."""
    if path.startswith("\\\\") and not path.startswith("\\\\?\\"):
        return Where("network", "smb")
    if path.startswith("\\\\?\\UNC\\"):
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


def _resolve(path: Path) -> str:
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return str(path)


def locate(path: Path, *, table: str | None = None, drive_type: int | None = None,
           windows: bool | None = None) -> Where:
    """Where ``path`` lies. The arguments stand in for the machine in a test; left out, the machine is asked."""
    is_windows = os.name == "nt" if windows is None else windows
    resolved = _resolve(path)
    if is_windows:
        return on_windows(resolved, drive_type if drive_type is not None else _drive_type(resolved))
    if table is None:
        try:
            table = MOUNT_TABLE.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return UNKNOWN
    return in_table(resolved, table)


def warn_at_start(data_dir: Path, database: Path) -> Where:
    """At the start: one warning in the log when the database lies on a share. Returns where the database lies."""
    where = locate(database.parent)
    if where.network:
        logger.warning(
            "The database lies on a network share (%s). SQLite can lose data there. Keep the data folder on a "
            "local disk; the documents may lie on a share.", where.fstype or "network",
        )
    elif where.kind == "unknown":
        logger.info("Could not tell whether the data folder lies on a network share")
    if data_dir != database.parent:
        # The data folder holds the backups and the secret key too; nothing else decides here.
        other = locate(data_dir)
        if other.network:
            logger.warning("The data folder lies on a network share (%s).", other.fstype or "network")
    return where
