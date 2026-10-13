"""The intake folder: a folder in the container (a volume; a scanner in the network or a share writes into it), with one
subfolder per person. What lands in ``<folder>/<account>/`` comes into that person's inbox; what lands in the folder
itself or in a subfolder nobody has goes to the operator, marked as unknown.

* **Looked at, not listened to.** The folder is read every few seconds (``scan``): network shares tell nobody about
  changes. A file is taken only after it lay still for ``QUIET_SECONDS`` (size and time of its last change the same),
  so a scanner that is still writing is not interrupted.
* **Taken, then gone.** A file becomes a document through ``receiving.accept`` (kind from the content, the limits of
  the server) and is removed from the folder afterwards. What is not taken (a kind nexpaper does not read, too large,
  empty) is moved to ``abgelehnt/`` beside it with a short reason, never deleted.
* **Never twice.** The document and a row ``taken`` for the file are written in one transaction; the row is ``done``
  once the file is gone. A file found again after a restart with its row still ``taken`` (same size, same time) is only
  removed.
* **Only inside.** Links and junctions are not followed (neither folders nor files), nothing outside the folder is
  opened, hidden and temporary files (``.~``, ``~$``, ``.part``, ``.tmp`` ...) are left alone, and system folders of a
  NAS (``@eaDir``, ``#recycle``) too. Many files at once are taken in turns, a few per person and round.
* **Not just anywhere.** The folder may not be the data folder of nexpaper, contain it, lie inside it (except
  ``<data>/eingang``), lie in the program or in a system folder: the folder's files are moved and removed.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import logging
import os
import re
import secrets
import stat
import threading
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select, update

from .. import clock, config
from ..config import get_settings
from ..db import SessionLocal
from ..models import Account, IntakeItem
from ..names import clean_segment
from . import filetypes, intake, limits, settings_service, storage

logger = logging.getLogger("nexpaper.intake")

#: How long a file must lie still before it is taken.
QUIET_SECONDS = 10.0
#: Files taken in one round, and of one person in one round: everybody's files come in turns.
PER_ROUND = 40
PER_PERSON = 8
#: How deep subfolders inside a person's folder are looked into.
MAX_DEPTH = 4
#: Entries looked at in one round at most (a folder of a million files must not hold the round for minutes).
MAX_ENTRIES = 20000
PER_FOLDER_ENTRIES = 5000
#: The folder files that are not taken are moved to, beside them.
REJECTED = "abgelehnt"
DEFAULT_NAME = "eingang"
READ_PIECE = 1024 * 1024

#: Files left alone: hidden ones (``.``, which takes ``.~`` too), Office's lock files, what is still being written.
SKIP_PREFIXES = (".", "~$")
SKIP_SUFFIXES = (".part", ".tmp", ".temp", ".crdownload", ".partial", ".filepart", ".download", ".swp", ".lock")
SKIP_NAMES = frozenset({"thumbs.db", "desktop.ini", "icon\r"})
#: Folders left alone: hidden ones, a NAS's own (``@eaDir``, ``#recycle``, ``#snapshot``), Windows' own.
SKIP_DIR_PREFIXES = (".", "@", "#", "$", "~")
SKIP_DIRS = frozenset({"lost+found", "system volume information", REJECTED})
#: Places that are never an intake folder, nor inside one.
SYSTEM = ("/proc", "/sys", "/dev", "/etc", "/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/boot", "/run",
          "/var/lib", "/var/run", "/root")

REASONS = {
    "unsupported_type": ("This kind of file is not taken. "
                         "Use PDF, JPEG, PNG, TIFF, HEIC, WebP, AVIF or e-invoices as XML."),
    "xml_not_invoice": "XML is taken only as an e-invoice (UBL or CII).",
    "xml_doctype": "XML with a document type definition is not taken.",
    "too_large": "The file is larger than the limit of the server.",
    "empty_file": "The file is empty.",
    "hard_link": "The file has more than one name (a hard link); only plain files are taken.",
}


class FolderProblem(ValueError):
    """A folder that cannot be the intake folder; ``code`` says why."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def default_root() -> Path:
    return get_settings().data_dir / DEFAULT_NAME


def _real(path: Path | str) -> Path:
    return Path(os.path.realpath(path))


def _inside(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


def check_root(text: str) -> Path:
    """The folder a setting names, or ``FolderProblem``: ``folder_invalid`` (not an absolute path), ``folder_forbidden``
    (a place whose files must not be moved), ``folder_missing`` (not there, and not the default that is made). Empty
    names the default, ``<data>/eingang``."""
    raw = (text or "").strip()
    if not raw:
        return default_root()
    if len(raw) > 400 or any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise FolderProblem("folder_invalid")
    path = Path(raw)
    if not path.is_absolute() or ".." in re.split(r"[\\/]", raw):
        raise FolderProblem("folder_invalid")
    return path


def _windows_places() -> list[Path]:
    """The folders of Windows itself and its programs (only where nexpaper is run for development)."""
    found = []
    for name in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "ProgramW6432"):
        value = os.environ.get(name)
        if value:
            found.append(Path(value))
    return found


def _program_places() -> list[Path]:
    """Where nexpaper's own files lie: the code, the built interface, and in a checkout the whole project. In the image
    the code lies in ``/app/app``, so the project's folder is the root of the disk: taken as a place of the program, it
    would forbid every folder but ``<data>/eingang``."""
    places = [config.BACKEND_DIR, get_settings().frontend_dist]
    if config.PROJECT_DIR.parent != config.PROJECT_DIR:
        places.append(config.PROJECT_DIR)
    return [_real(place) for place in places]


def forbidden(path: Path) -> bool:
    """Whether a folder is one whose files nexpaper must not move: the root of a disk, nexpaper's data folder or one
    above it, a place inside it other than ``eingang``, the program, a system folder."""
    real = _real(path)
    if real.parent == real:
        return True
    data = _real(get_settings().data_dir)
    if _inside(data, real):
        return True
    if _inside(real, data) and not _inside(real, data / DEFAULT_NAME):
        return True
    for program in _program_places():
        if _inside(real, program) and not _inside(real, data / DEFAULT_NAME):
            return True
        if _inside(program, real):
            return True
    places = [Path(place) for place in SYSTEM] if os.name != "nt" else _windows_places()
    return any(_inside(real, _real(place)) for place in places)


def usable_root(text: str, make: bool = False) -> Path:
    """The folder as it is used: checked, not forbidden, there (the default is made when ``make``)."""
    path = check_root(text)
    if forbidden(path):
        raise FolderProblem("folder_forbidden")
    if make and path == default_root():
        path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise FolderProblem("folder_missing")
    return path


def _is_link(entry: os.DirEntry[str]) -> bool:
    if entry.is_symlink():
        return True
    junction = getattr(entry, "is_junction", None)
    return bool(junction and junction())


def _skip_file(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith(SKIP_PREFIXES) or lowered.endswith(SKIP_SUFFIXES) or lowered in SKIP_NAMES


def _skip_dir(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith(SKIP_DIR_PREFIXES) or lowered in SKIP_DIRS


#: Names Windows does not allow as a folder (only where nexpaper is run for development).
_WINDOWS_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE)


def folder_name(name: str) -> str | None:
    """The subfolder of an account: its name as it signs in (``NAME_PATTERN`` allows nothing a folder could not be),
    except ``abgelehnt`` (where files that are not taken go)."""
    from .accounts import NAME_PATTERN

    if not NAME_PATTERN.match(name) or name.lower() in SKIP_DIRS or name.endswith("."):
        return None
    if os.name == "nt" and _WINDOWS_RESERVED.match(name):
        return None
    return name


def prepare(db_names: list[str], root: Path) -> None:
    """A subfolder for each person (made, never a link followed). A subfolder that cannot be made is said once, and
    again only after it worked in between."""
    for name in db_names:
        folder = folder_name(name)
        if folder is None:
            continue
        target = root / folder
        try:
            if target.is_symlink() or getattr(target, "is_junction", lambda: False)():
                continue
            target.mkdir(exist_ok=True)
            _said.discard(f"prepare:{name}")
        except OSError:
            _say_once(f"prepare:{name}", "Intake folder: a subfolder could not be made account=%s", name)


#: How often it is checked again whether files may be moved and removed in the folder.
WRITABLE_SECONDS = 60.0
_writable: dict[str, tuple[float, bool]] = {}


def writable(root: Path, fresh: bool = False) -> bool:
    """Whether nexpaper may make, move and remove files in the folder: tried with a hidden file of its own. A folder
    where it may only read is not taken from (a file that cannot be removed would come in again and again)."""
    key = str(root)
    moment = clock.monotonic()
    known = _writable.get(key)
    if known is not None and not fresh and moment - known[0] < WRITABLE_SECONDS:
        return known[1]
    probe = root / f".nexpaper-probe-{secrets.token_hex(6)}"
    moved = probe.with_name(probe.name + "-moved")
    ok = True
    try:
        handle = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
        os.close(handle)
        os.rename(probe, moved)
        os.unlink(moved)
    except OSError:
        ok = False
        for leftover in (probe, moved):
            with contextlib.suppress(OSError):
                leftover.unlink()
    _writable[key] = (moment, ok)
    return ok


# --- One round -------------------------------------------------------------------------------------------------------


@dataclass
class _Watch:
    size: int
    mtime_ns: int
    since: float


@dataclass
class Found:
    """A file that lay still long enough: whose it is, where it stands."""

    path: Path
    rel: str
    top: Path
    owner: int
    unknown: bool
    folder: str
    size: int
    mtime_ns: int


@dataclass
class Round:
    taken: dict[str, int] = field(default_factory=dict)
    rejected: int = 0
    waiting: int = 0


#: What was seen of each file in the rounds before, to know when it lay still. In memory: a restart waits again.
_watch: dict[str, _Watch] = {}
#: Files that could not be moved or removed (a read-only share): tried again only when they change.
_stuck: set[tuple[str, int, int]] = set()
_running = threading.Lock()
_said: set[str] = set()


def forget() -> None:
    """For the tests."""
    _watch.clear()
    _stuck.clear()
    _said.clear()
    _writable.clear()


def _say_once(key: str, message: str, *args: object) -> None:
    if key not in _said:
        _said.add(key)
        logger.warning(message, *args)


def _walk(root: Path, top: Path, rel: str, depth: int, out: list[tuple[Path, str, os.stat_result]],
          budget: list[int]) -> None:
    """The files below ``top`` (links and junctions not followed, skipped names left out)."""
    try:
        entries = list(os.scandir(top / rel if rel else top))
    except OSError:
        return
    entries.sort(key=lambda entry: entry.name)
    for entry in entries:
        if budget[0] <= 0:
            return
        budget[0] -= 1
        if _is_link(entry):
            continue
        name = entry.name
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        inner = f"{rel}/{name}" if rel else name
        if stat.S_ISDIR(info.st_mode):
            if depth < MAX_DEPTH and not _skip_dir(name):
                _walk(root, top, inner, depth + 1, out, budget)
        elif stat.S_ISREG(info.st_mode) and not _skip_file(name):
            out.append((top / inner, inner, info))


Entry = tuple[Path, str, int, bool, str, os.stat_result]


def _candidates(root: Path, people: dict[str, int], blocked: set[str], operator: int | None) -> list[Entry]:
    """Every file of the folder with whose it is: ``(path, rel, owner, unknown, folder, stat)``."""
    found: list[Entry] = []
    budget = [MAX_ENTRIES]
    try:
        entries = sorted(os.scandir(root), key=lambda entry: entry.name)
    except OSError:
        return found
    for entry in entries:
        if budget[0] <= 0:
            break
        budget[0] -= 1
        if _is_link(entry):
            continue
        name = entry.name
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode):
            if operator is not None and not _skip_file(name):
                found.append((root / name, name, operator, True, "", info))
            continue
        if not stat.S_ISDIR(info.st_mode) or _skip_dir(name):
            continue
        key = name.casefold()
        if key in blocked:
            continue
        owner = people.get(key)
        unknown = owner is None
        if unknown:
            if operator is None:
                continue
            owner = operator
        files: list[tuple[Path, str, os.stat_result]] = []
        # Every subfolder has a budget of its own: a person with a hundred thousand files does not hide the others'.
        _walk(root, root / name, "", 1, files, [PER_FOLDER_ENTRIES])
        for path, inner, file_info in files:
            found.append((path, f"{name}/{inner}", owner, unknown, name, file_info))
    return found


def _stable(path: Path, info: os.stat_result, moment: float) -> bool:
    key = str(path)
    seen = _watch.get(key)
    if seen is None or seen.size != info.st_size or seen.mtime_ns != info.st_mtime_ns:
        _watch[key] = _Watch(info.st_size, info.st_mtime_ns, moment)
        return False
    return moment - seen.since >= QUIET_SECONDS


def _in_turns(found: list[Found]) -> list[Found]:
    """The files in turns: one of each person, then the next of each, ``PER_PERSON`` each and ``PER_ROUND`` in all."""
    queues: dict[int, list[Found]] = {}
    for one in found:
        queues.setdefault(one.owner, []).append(one)
    order: list[Found] = []
    for turn in range(PER_PERSON):
        for owner in sorted(queues):
            if turn < len(queues[owner]):
                order.append(queues[owner][turn])
    return order[:PER_ROUND]


def scan() -> Round:
    """One round over the folder: what lay still is taken. Does nothing while the folder is switched off (and forgets
    what it saw), and never runs twice at once."""
    result = Round()
    if not _running.acquire(blocking=False):
        return result
    try:
        return _scan(result)
    finally:
        _running.release()


def _scan(result: Round) -> Round:
    with SessionLocal() as db:
        values = settings_service.get_all(db)
        if not values["folder_on"]:
            _watch.clear()
            return result
        try:
            root = usable_root(str(values["folder_path"] or ""), make=True)
        except FolderProblem as exc:
            _say_once(f"root:{exc.code}", "Intake folder cannot be used reason=%s", exc.code)
            return result
        if not writable(root):
            # Taken files could not be removed and would come in again: nothing is taken until it may be.
            _say_once("root:folder_readonly", "Intake folder cannot be used reason=folder_readonly")
            return result
        for key in [key for key in _said if key.startswith("root:")]:
            _said.discard(key)
        accounts = db.execute(select(Account.id, Account.name, Account.blocked_at)).all()
        operator = intake.operator_id(db)
        max_file = limits.current(db).max_file
    people = {name.casefold(): uid for uid, name, blocked in accounts if blocked is None and folder_name(name)}
    blocked = {name.casefold() for _uid, name, blocked_at in accounts if blocked_at is not None}
    prepare(sorted(name for _uid, name, blocked_at in accounts if blocked_at is None), root)
    moment = clock.monotonic()
    still: list[Found] = []
    present: set[str] = set()
    closed: dict[str, bool] = {}
    for path, rel, owner, unknown, folder, info in _candidates(root, people, blocked, operator):
        present.add(str(path))
        if (str(path), info.st_size, info.st_mtime_ns) in _stuck:
            continue
        if folder and folder not in closed:
            # A subfolder nexpaper may only read (another owner on the share) is left alone, like the whole folder.
            closed[folder] = not writable(root / folder)
            if closed[folder]:
                _say_once(f"sub:{folder}", "Intake folder: a subfolder cannot be used reason=folder_readonly")
            else:
                _said.discard(f"sub:{folder}")
        if folder and closed[folder]:
            continue
        if _stable(path, info, moment):
            top = root / folder if folder else root
            still.append(Found(path, rel, top, owner, unknown, folder, info.st_size, info.st_mtime_ns))
        else:
            result.waiting += 1
    for key in list(_watch):
        if key not in present:
            del _watch[key]
    for item in _in_turns(still):
        _take(root, item, max_file, result)
    for name, count in sorted(result.taken.items()):
        logger.info("Intake folder: %s file(s) taken account=%s", count, name)
    if result.rejected:
        logger.info("Intake folder: %s file(s) set aside", result.rejected)
    return result


# --- One file --------------------------------------------------------------------------------------------------------


def _open(path: Path, root: Path, size: int, mtime_ns: int) -> int | None:
    """The file opened for reading, without following a link, and only when it still is the regular file that lay still
    there, inside the folder. None otherwise."""
    try:
        if not _inside(_real(path.parent), _real(root)):
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        handle = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(handle)
        before = os.lstat(path)
    except OSError:
        os.close(handle)
        return None
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(before.st_mode) or info.st_size != size
            or info.st_mtime_ns != mtime_ns or (info.st_ino and before.st_ino and info.st_ino != before.st_ino)):
        os.close(handle)
        return None
    return handle


def _copy(handle: int, max_file: int) -> tuple[Path | None, str, str, int, str]:
    """The file copied into ``dokumente/`` under a temporary name while its kind is read and its checksum made:
    ``(temporary path, kind, sha256, size, problem)``; ``problem`` is a code of ``REASONS`` when it is not taken."""
    digest = hashlib.sha256()
    head = bytearray()
    size = 0
    target: Path | None = None
    out = None
    kind = ""
    try:
        while True:
            chunk = os.read(handle, READ_PIECE)
            if not chunk:
                break
            size += len(chunk)
            if size > max_file:
                return _drop(target, out, "too_large")
            digest.update(chunk)
            if out is None:
                head += chunk
                if len(head) < filetypes.HEAD:
                    continue
                try:
                    kind = filetypes.sniff(bytes(head)).kind
                except filetypes.NotAccepted as exc:
                    return _drop(target, out, exc.reason if exc.reason in REASONS else "unsupported_type")
                target = storage.incoming_path("in-")
                out = target.open("wb")
                out.write(bytes(head))
                head = bytearray()
            else:
                out.write(chunk)
        if out is None:
            if size == 0:
                return _drop(target, out, "empty_file")
            try:
                kind = filetypes.sniff(bytes(head)).kind
            except filetypes.NotAccepted as exc:
                return _drop(target, out, exc.reason if exc.reason in REASONS else "unsupported_type")
            target = storage.incoming_path("in-")
            out = target.open("wb")
            out.write(bytes(head))
        out.close()
        return target, kind, digest.hexdigest(), size, ""
    except BaseException:
        _drop(target, out, "")
        raise


def _drop(target: Path | None, out: object, problem: str) -> tuple[None, str, str, int, str]:
    if out is not None:
        try:
            out.close()  # type: ignore[attr-defined]
        except OSError:
            pass
    if target is not None:
        target.unlink(missing_ok=True)
    return None, "", "", 0, problem


def _free(folder: Path, name: str) -> Path:
    stem, dot, ending = name.rpartition(".")
    if not dot or not stem:
        stem, ending = name, ""
    candidate = folder / name
    counter = 1
    while candidate.exists() or candidate.is_symlink():
        counter += 1
        candidate = folder / (f"{stem} ({counter}).{ending}" if ending else f"{stem} ({counter})")
    return candidate


def aside_name(name: str) -> str:
    """The name a file that is not taken gets in ``abgelehnt/``: cleaned, short, its ending kept."""
    stem, dot, ending = name.rpartition(".")
    if not dot or not stem or len(ending) > 10:
        return clean_segment(name, "file", 100)
    return f"{clean_segment(stem, 'file', 100)}.{clean_segment(ending, 'bin', 10)}"


def _set_aside(root: Path, item: Found, problem: str, result: Round) -> None:
    """A file that is not taken goes to ``abgelehnt/`` beside it, with a short reason; never deleted. Only a file that
    really lies inside the folder is moved, and only to a place inside it."""
    place = item.top / REJECTED
    try:
        inside = _real(root)
        if (place.is_symlink() or not _inside(_real(item.path.parent), inside)
                or not _inside(_real(item.top), inside) or os.path.islink(item.path)):
            raise OSError(errno.EPERM, "link")
        place.mkdir(exist_ok=True)
        target = _free(place, aside_name(item.path.name))
        os.rename(item.path, target)
        reason = REASONS.get(problem, REASONS["unsupported_type"])
        note = target.with_name(target.name + ".grund.txt")
        with note.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(f"Not taken by nexpaper: {reason}\n")
    except OSError:
        _stuck.add((str(item.path), item.size, item.mtime_ns))
        _say_once(f"aside:{item.path}", "Intake folder: a file could not be set aside reason=%s", problem)
        return
    _watch.pop(str(item.path), None)
    result.rejected += 1


def _same(info: os.stat_result, other: os.stat_result) -> bool:
    """Whether two looks at a file see the same file, unchanged: size, time of the last change, its number."""
    if stat.S_ISLNK(other.st_mode) or info.st_size != other.st_size or info.st_mtime_ns != other.st_mtime_ns:
        return False
    return not (info.st_ino and other.st_ino and (info.st_ino != other.st_ino or info.st_dev != other.st_dev))


def _remove(path: Path, read: os.stat_result | None = None) -> str:
    """Removes the file that was taken: ``removed``; ``changed`` when another file stands there now (a scanner that
    writes the same name again), which is left for the next round; ``failed`` when it may not be removed."""
    try:
        if read is not None and not _same(read, os.lstat(path)):
            return "changed"
        path.unlink()
    except FileNotFoundError:
        return "removed"
    except OSError:
        return "failed"
    return "removed"


def _settle_taken(item: Found) -> bool:
    """A file whose document was made before (a restart came between taking and removing it): removed now, its row
    done. Returns whether the file was one of those."""
    with SessionLocal() as db:
        row = db.scalar(select(IntakeItem).where(IntakeItem.source == intake.FOLDER, IntakeItem.key == item.rel,
                                                 IntakeItem.state == intake.TAKEN))
        if row is None:
            return False
        if row.size != item.size or row.mtime_ns != item.mtime_ns:
            # Another file under the same name: the one taken is gone, its row is done.
            row.state = intake.DONE
            db.commit()
            return False
        try:
            seen = os.lstat(item.path)
        except OSError:
            seen = None
        unchanged = seen is not None and seen.st_size == item.size and seen.st_mtime_ns == item.mtime_ns
        removed = _remove(item.path, seen) if unchanged and seen is not None else "changed"
        if removed != "failed":
            row.state = intake.DONE
            db.commit()
            _watch.pop(str(item.path), None)
        else:
            _stuck.add((str(item.path), item.size, item.mtime_ns))
            _say_once(f"remove:{item.path}", "Intake folder: a file taken before could not be removed")
        return True


def _take(root: Path, item: Found, max_file: int, result: Round) -> None:
    if _settle_taken(item):
        return
    handle = _open(item.path, root, item.size, item.mtime_ns)
    if handle is None:
        _watch.pop(str(item.path), None)
        return
    try:
        if os.fstat(handle).st_nlink > 1:
            temporary, kind, sha256, size, problem = None, "", "", 0, "hard_link"
        else:
            temporary, kind, sha256, size, problem = _copy(handle, max_file)
        changed = os.fstat(handle)
    finally:
        os.close(handle)
    if changed.st_size != item.size or changed.st_mtime_ns != item.mtime_ns:
        # Written to while it was read: it waits for another quiet spell.
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        _watch.pop(str(item.path), None)
        return
    if temporary is None:
        _set_aside(root, item, problem, result)
        return
    detail = {"folder": item.folder, "file": item.path.name[:200]}
    try:
        with SessionLocal() as db:
            intake.take(
                db, uid=item.owner, path=temporary, filename=item.path.name, kind=kind, sha256=sha256, size=size,
                source=intake.FOLDER,
                item={"key": item.rel, "state": intake.TAKEN, "sha256": sha256, "size": item.size,
                      "mtime_ns": item.mtime_ns, "unknown": item.unknown, "detail": detail},
            )
            owner = db.get(Account, item.owner)
            name = owner.name if owner is not None else str(item.owner)
    except Exception as exc:  # noqa: BLE001 - one file that fails must not stop the others
        temporary.unlink(missing_ok=True)
        _watch.pop(str(item.path), None)
        # Tried again in the next quiet spell; said once, not every round.
        _say_once(f"take:{item.path}", "Intake folder: a file could not be taken error=%s", type(exc).__name__)
        return
    result.taken[name] = result.taken.get(name, 0) + 1
    _watch.pop(str(item.path), None)
    if _remove(item.path, changed) != "failed":
        # Removed; or another file stands under the name now, which is a new one for the next round.
        with SessionLocal() as db:
            db.execute(update(IntakeItem).where(IntakeItem.source == intake.FOLDER, IntakeItem.key == item.rel,
                                                IntakeItem.state == intake.TAKEN).values(state=intake.DONE))
            db.commit()
    else:
        _stuck.add((str(item.path), item.size, item.mtime_ns))
        _say_once(f"remove:{item.path}", "Intake folder: a file was taken but could not be removed")


def person_problem(used: str, name: str) -> str:
    """``folder_readonly`` when the person's subfolder is there and nexpaper may not move or remove files in it."""
    folder = folder_name(name)
    if folder is None:
        return ""
    target = Path(used) / folder
    if not target.is_dir():
        return ""
    return "" if writable(target) else "folder_readonly"


def describe(root_text: str) -> tuple[str, str]:
    """The folder as the settings show it: ``(path, problem)``; the problem is empty when the folder can be used."""
    try:
        path = check_root(root_text)
    except FolderProblem as exc:
        return root_text, exc.code
    try:
        usable_root(root_text, make=False)
    except FolderProblem as exc:
        if exc.code == "folder_missing" and path == default_root():
            return str(path), ""
        return str(path), exc.code
    if not writable(path):
        return str(path), "folder_readonly"
    return str(path), ""

