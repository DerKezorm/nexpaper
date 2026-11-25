"""The list of backups: names, making a copy, listing, deleting, keeping, bringing one in from elsewhere.

* **Names:** ``<app>-YYYY-MM-DD-HHMMSS.zip`` (UTC), ``-2`` … for a second copy in the same second, ``-upload`` for
  one brought in. Only names of this pattern (and the app's ``legacy_names``) are ever opened, listed or deleted; a
  name is never joined to a path before it matched.
* **A copy is written under a hidden name** (``.<name>.part``) and moved to its name when whole; a failed one is
  thrown away, the older ones stay. A full disk says so (``backup_disk_full``, 507).
* **Only automatic copies are pruned** (``scheduled`` and ``update``), the newest ``keep`` stay; one made by hand or
  brought in from elsewhere stays until deleted.
* **One at a time:** while a copy is made, another one is refused (``backup_running``, 409); the schedule waits.
"""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from . import space, state, tools
from .config import current
from .errors import BackupError
from .model import AUTOMATIC_KINDS, KINDS, MANUAL, Described, Entry

UPLOADED = "-upload.zip"
PENDING = "restore-pending"
FAILED = "restore-failed"
#: Hidden work files older than this are leftovers of a stopped process and go.
LEFTOVER_SECONDS = 6 * 3600

#: Held while a copy is made, a restore is staged or an upload joins the list.
lock = threading.RLock()
_described: dict[str, tuple[tuple[int, int], Described | None]] = {}
_described_lock = threading.Lock()


def folder() -> Path:
    return current().backups


def known_name(name: str) -> bool:
    config = current()
    if len(name) > 80:
        return False
    return bool(config.name_pattern.fullmatch(name)) or any(pattern.fullmatch(name) for pattern in config.legacy_names)


def path_of(name: str) -> Path:
    """The archive of that name, or ``not_found``: the name must match the app's patterns and be a plain file (no
    link) right in the backups folder."""
    if not known_name(name):
        raise BackupError("not_found", "no such backup")
    path = folder() / name
    if not path.is_file() or path.is_symlink():
        raise BackupError("not_found", "no such backup")
    return path


def describe(path: Path) -> Described | None:
    """The app's ``describe``, remembered by size and time of the file (the schedule lists every minute)."""
    try:
        info = path.stat()
    except OSError:
        return None
    key = (info.st_size, info.st_mtime_ns)
    with _described_lock:
        found = _described.get(path.name)
        if found is not None and found[0] == key:
            return found[1]
    try:
        described: Described | None = current().hooks.describe(path)
        if described.kind not in KINDS:
            described.kind = MANUAL
    except BackupError:
        described = None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        current().logger.info("A backup could not be read name=%s: %s", path.name, exc.__class__.__name__)
        described = None
    with _described_lock:
        _described[path.name] = (key, described)
    return described


def forget(name: str | None = None) -> None:
    with _described_lock:
        if name is None:
            _described.clear()
        else:
            _described.pop(name, None)


def _created_of(path: Path, described: Described | None) -> str:
    if described is not None and described.created:
        return described.created
    found = _STAMP.search(path.name)
    if found:
        try:
            return datetime.strptime(found.group(1), "%Y-%m-%d-%H%M%S").replace(tzinfo=UTC).isoformat()
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")


_STAMP = re.compile(r"-(\d{4}-\d{2}-\d{2}-\d{6})(?:-(\d+))?(?:-upload)?\.zip$")


def _sort_key(entry: Entry) -> tuple[float, int]:
    """By the time the archive names; two of the same second by their number (``-2`` after the first)."""
    try:
        moment = datetime.fromisoformat(entry.created).timestamp()
    except ValueError:
        moment = 0.0
    found = _STAMP.search(entry.name)
    return moment, int(found.group(2)) if found and found.group(2) else 1


def entries() -> list[Entry]:
    """Every archive of the app, newest first. A file with one of the app's names that ``describe`` refuses is listed
    as not readable (so it can be deleted), never pruned or restored."""
    base = folder()
    if not base.is_dir():
        return []
    found: list[Entry] = []
    for path in base.iterdir():
        if not known_name(path.name) or not path.is_file() or path.is_symlink():
            continue
        try:
            if path.stat().st_size == 0 and running():
                # The name a copy under way reserved; it is filled when the copy is whole.
                continue
        except OSError:
            continue
        described = describe(path)
        try:
            size = path.stat().st_size
            created = _created_of(path, described)
        except OSError:
            continue
        uploaded = path.name.endswith(UPLOADED)
        if described is None:
            found.append(Entry(path.name, size, created, MANUAL, "", "", uploaded, readable=False))
            continue
        found.append(Entry(path.name, size, created, described.kind, described.note, described.version, uploaded,
                           described.locked, True, dict(described.facts)))
    return sorted(found, key=_sort_key, reverse=True)


def running() -> bool:
    """Whether a copy, a staging or an upload is under way right now."""
    if lock.acquire(blocking=False):
        lock.release()
        return False
    return True


def _write_failed(exc: BaseException) -> BackupError:
    full = space.disk_full(exc)
    reason = "disk_full" if full else "write_failed"
    state.update(failure={"at": tools.now_iso(), "reason": reason})
    if full:
        return BackupError("backup_disk_full", "The disk is full; the backup was not written. The older ones stay.")
    return BackupError("backup_write_failed", "The backup could not be written. The older backups stay.")


def create(*, kind: str = MANUAL, note: str = "", wait: bool = True) -> Path:
    """A new archive, written by the app's ``pack``. Returns its path. ``wait`` False: refuse with ``backup_running``
    while another copy is made (a click on "Jetzt sichern"); True: wait for it (a copy before an update)."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind}")
    config = current()
    if not lock.acquire(blocking=wait):
        raise BackupError("backup_running", "A backup is being made right now.")
    try:
        base = tools.private_folder(folder())
        moment = datetime.now(UTC)
        final = tools.reserve(base, f"{config.app_name}-{tools.stamp(moment)}", ".zip")
        work = base / f".{final.name}.part"
        try:
            tools.new_file(work)
            config.hooks.pack(work, kind=kind, note=note[:200], created=moment.isoformat(timespec="seconds"))
            os.replace(work, final)
        except BackupError:
            final.unlink(missing_ok=True)
            raise
        except Exception as exc:
            final.unlink(missing_ok=True)
            config.logger.exception("A backup could not be written")
            raise _write_failed(exc) from exc
        finally:
            work.unlink(missing_ok=True)
            space.forget()
        state.update(failure=None)
        config.logger.info("Backup made kind=%s name=%s bytes=%s", kind, final.name, final.stat().st_size)
        return final
    finally:
        lock.release()


def remove(name: str) -> None:
    path = path_of(name)
    current().hooks.remove(path)
    forget(name)
    space.forget()
    current().logger.info("Backup deleted name=%s", name)


def prune(keep: int) -> int:
    """Delete the automatic copies beyond the newest ``keep`` (at least one stays)."""
    automatic = [entry for entry in entries()
                 if entry.readable and entry.kind in AUTOMATIC_KINDS and not entry.uploaded]
    removed = 0
    for entry in automatic[max(keep, 1):]:
        try:
            current().hooks.remove(folder() / entry.name)
        except OSError as exc:
            current().logger.warning("An old backup could not be removed name=%s: %s", entry.name, exc.strerror)
            continue
        forget(entry.name)
        removed += 1
    if removed:
        space.forget()
        current().logger.info("Old automatic backups removed count=%s", removed)
    return removed


def tidy_leftovers() -> None:
    """Hidden work files a stopped process left (``.<name>.part``, ``.upload-…``, ``.check-…``), older than six
    hours."""
    base = folder()
    if not base.is_dir():
        return
    for leftover in base.glob(".*"):
        try:
            if leftover.is_file() and time.time() - leftover.stat().st_mtime > LEFTOVER_SECONDS:
                leftover.unlink()
        except OSError:
            continue


# --- Bringing one in from elsewhere ---------------------------------------------------------------------------------


def temporary_upload() -> Path:
    """Where an upload lands while it arrives: in the backups folder, only the owner's, under a hidden name."""
    base = tools.private_folder(folder())
    path = base / f".upload-{os.getpid()}-{time.time_ns()}.part"
    tools.new_file(path)
    return path


def scratch(label: str) -> Path:
    """A hidden name in the backups folder for a file of a check (removed by the caller, or as a leftover)."""
    base = tools.private_folder(folder())
    return base / f".{label}-{os.getpid()}-{time.time_ns()}"


def receive(received: Path) -> str:
    """An archive brought in from elsewhere (a move to a new server): if the app's ``describe`` takes it for one of its
    own, it joins the list as ``<app>-<its stamp>-upload.zip`` and waits there to be checked and restored like any
    other. Nothing is unpacked here."""
    config = current()
    try:
        described = config.hooks.describe(received)
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError("backup_invalid", "not a backup of this app") from exc
    moment = datetime.now(UTC)
    if described.created:
        try:
            moment = datetime.fromisoformat(described.created)
        except ValueError:
            pass
    with lock:
        base = tools.private_folder(folder())
        final = tools.reserve(base, f"{config.app_name}-{tools.stamp(moment)}", UPLOADED)
        os.replace(received, final)
        space.forget()
    config.logger.warning("Backup received name=%s version=%s", final.name, described.version)
    return final.name
