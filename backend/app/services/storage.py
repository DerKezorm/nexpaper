"""The files on the disk, readable without nexpaper.

    <data>/dokumente/<vault>/<year>/<sender>/<date> <kind>.pdf

The name follows the fields of the document: when a person changes the sender, the kind, the date or the vault, the
file follows in the background (a ``rename`` job, ``services/jobs.py``). The file as it came is never overwritten and
its checksum does not change; older versions keep a name of their own (``... (version 1).pdf``), the searchable copy
that the next block makes sits beside them (``... (searchable).pdf``).

**Paths.** What a person typed goes through ``names.clean_segment`` (no path parts, no reserved names, a length that
fits). A path in the database is relative to ``dokumente/`` and is checked (``resolve``) before every use: nothing
outside it is ever read, written or removed, whatever the database says.

**Moving.** A file moves without overwriting (a hard link, then the old name goes; where the disk has no links, a
rename after checking that the target is free). The database learns the new path after the move, one file at a time; a
run that breaks off in between finds the file at its new place the next time and only writes the path down. A run that
broke off between the link and the removal of the old name leaves the file under both names: the next run sees the same
checksum under the new name, which no other version claims, removes the old name and writes the new one down.
``.incoming-*`` files a write left behind go at the next start (``sweep_incoming``).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Document, Kind, Sender, Vault, Version
from ..names import KIND_MAX, SEGMENT_MAX, clean_segment, folded

logger = logging.getLogger("nexpaper.storage")

FOLDER = "dokumente"
NO_DATE = "undated"
NO_SENDER = "no sender"
NO_KIND = "Document"
#: One move at a time inside this process; the check for a free name and the move belong together.
_moving = threading.Lock()
#: The files of a document are worked on by one at a time: the page tools (which read them and make new versions) and
#: the ``rename`` job (which moves them). A document takes the lock of its stripe; two documents of one stripe wait for
#: each other, which costs nothing but a moment.
_STRIPES = [threading.Lock() for _ in range(256)]


class StorageError(Exception):
    pass


class DocumentBusy(Exception):
    """The files of the document are being worked on right now: try again in a moment (the job waits for its turn)."""


def _stripes(document_ids: list[int]) -> list[threading.Lock]:
    return [_STRIPES[index] for index in sorted({int(i) % len(_STRIPES) for i in document_ids})]


class files_of:
    """``with files_of([ids], wait)``: the files of these documents to oneself, waited for at most ``wait`` seconds
    (``DocumentBusy`` when that was not enough). The locks are taken in one order, so two callers never wait for each
    other in a ring."""

    def __init__(self, document_ids: list[int], wait: float) -> None:
        self.locks = _stripes(document_ids)
        self.wait = wait
        self.held: list[threading.Lock] = []

    def __enter__(self) -> None:
        for lock in self.locks:
            taken = lock.acquire(timeout=self.wait) if self.wait > 0 else lock.acquire(blocking=False)
            if not taken:
                self.__exit__()
                raise DocumentBusy
            self.held.append(lock)

    def __exit__(self, *_exc: object) -> None:
        for lock in reversed(self.held):
            lock.release()
        self.held = []


def root() -> Path:
    return get_settings().data_dir / FOLDER


def safe_path(rel: str) -> Path:
    """The file a relative path names, inside ``dokumente/`` or ``StorageError``. Absolute paths, ``..``, drive letters
    and anything that resolves outside (a link, say) are refused."""
    if not rel or rel.startswith(("/", "\\")) or "\x00" in rel or re.match(r"^[A-Za-z]:", rel):
        raise StorageError("path")
    parts = re.split(r"[\\/]", rel)
    if any(part in ("", ".", "..") for part in parts):
        raise StorageError("path")
    base = root().resolve()
    target = (base / Path(*parts)).resolve()
    if base != target and base not in target.parents:
        raise StorageError("path")
    return target


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# --- Names ----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Parts:
    """The folders and the base name a document's files are named after."""

    folders: tuple[str, ...]
    stem: str


def parts_for(db: Session, document: Document) -> Parts:
    vault = db.get(Vault, document.vault_id)
    assert vault is not None
    sender = db.get(Sender, document.sender_id) if document.sender_id else None
    kind = db.get(Kind, document.kind_id) if document.kind_id else None
    year = str(document.date.year) if document.date else NO_DATE
    folders = (
        clean_segment(vault.folder, "vault"),
        year,
        clean_segment(sender.name if sender else "", NO_SENDER),
    )
    day = document.date.isoformat() if document.date else NO_DATE
    return Parts(folders, f"{day} {clean_segment(kind.name if kind else '', NO_KIND, KIND_MAX)}")


def suffixes(version: Version, current: int, extension: str, archive: bool) -> str:
    """What follows the base name: ``(version n)`` for an older version, ``(searchable)`` for the copy that was read."""
    tags = []
    if version.n != current:
        tags.append(f"version {version.n}")
    if archive:
        tags.append("searchable")
    return (" (" + ", ".join(tags) + ")" if tags else "") + extension


def name_taken(db: Session, folders: tuple[str, ...], name: str, own: set[str],
               vacating: set[str] | None = None, document_id: int | None = None) -> bool:
    """Whether the name is not free: the document's own files count (they may be about to move), so does another file on
    the disk (case-insensitive) and another version in the database. ``vacating``: own files of ``document_id`` that
    are about to move elsewhere first; their names are free unless another document claims them."""
    key = folded("/".join((*folders, name)))
    if key in own:
        return True
    if vacating and key in vacating:
        return bool(db.scalar(select(func.count()).select_from(Version).where(
            Version.document_id != document_id,
            (func.lower(Version.original_path) == key) | (func.lower(Version.archive_path) == key))))
    directory = root().resolve().joinpath(*folders)
    if directory.is_dir() and any(folded(entry) == folded(name) for entry in os.listdir(directory)):
        return True
    return bool(db.scalar(select(func.count()).select_from(Version).where(
        (func.lower(Version.original_path) == key) | (func.lower(Version.archive_path) == key))))


def _already_named(current: str, folders: tuple[str, ...], base_name: str, extension: str) -> bool:
    """The file already sits where it belongs, possibly with a counter after the name (``... (2).pdf``): leave it, so
    that two documents with the same fields do not keep renaming each other."""
    wanted = "/".join(folders)
    directory, _, name = current.rpartition("/")
    if folded(directory) != folded(wanted):
        return False
    stem = base_name[: -len(extension)] if extension and base_name.endswith(extension) else base_name
    pattern = re.compile("^" + re.escape(folded(stem)) + r"( \(\d+\))?" + re.escape(folded(extension)) + "$")
    return bool(pattern.match(folded(name)))


def _arrived(current: str, ideal: str, sha256: str) -> bool:
    """The file is no longer at its recorded path, and the file at the new one is the same file (same checksum)."""
    try:
        here, there = safe_path(current), safe_path(ideal)
    except StorageError:
        return False
    return not here.exists() and there.is_file() and sha256_of(there) == sha256


def _claimed_elsewhere(db: Session, rel: str, version_id: int) -> bool:
    """Whether another version (of any document) has this path, as original or searchable copy."""
    key = folded(rel)
    return bool(db.scalar(select(func.count()).select_from(Version).where(
        Version.id != version_id,
        (func.lower(Version.original_path) == key) | (func.lower(Version.archive_path) == key))))


def _left_twice(db: Session, version: Version, current: str, ideal: str) -> bool:
    """A run that broke off between the link and the removal of the old name: the file is under its recorded path and
    under the new one, the same file (same checksum as recorded), and no other version claims the new one."""
    if not version.sha256 or folded(current) == folded(ideal):
        return False
    try:
        here, there = safe_path(current), safe_path(ideal)
    except StorageError:
        return False
    if not (here.is_file() and there.is_file()) or _claimed_elsewhere(db, ideal, version.id):
        return False
    return sha256_of(there) == version.sha256 and sha256_of(here) == version.sha256


def plan(db: Session, document: Document) -> list[tuple[Version, str, str]]:
    """What has to move: ``(version, "original" | "archive", new relative path)`` for every file that is not where its
    document's fields say it belongs, in the order the moves are to be made.

    A file that is already named right stays (its name is taken). A file that moves gives its name up: when a new
    version becomes the current one, it takes the plain name from the version before, which moves to ``(version n)``
    first (the list is ordered so that a name is left before it is taken)."""
    versions = list(db.scalars(select(Version).where(Version.document_id == document.id).order_by(Version.n.desc())))
    if not versions:
        return []
    parts = parts_for(db, document)
    wanted: list[tuple[Version, str, str, str, str]] = []
    staying: set[str] = set()
    for version in versions:
        for which, rel in (("original", version.original_path), ("archive", version.archive_path)):
            if not rel:
                continue
            extension = Path(rel).suffix.lower() if which == "original" else ".pdf"
            name = parts.stem + suffixes(version, document.current_version, extension, which == "archive")
            if _already_named(rel, parts.folders, name, extension):
                staying.add(folded(rel))
                continue
            wanted.append((version, which, rel, extension, name))
    vacating = {folded(rel) for _version, _which, rel, _extension, _name in wanted}
    chosen: set[str] = set(staying)
    moves: list[tuple[Version, str, str]] = []
    for version, which, rel, extension, name in wanted:
        ideal = "/".join((*parts.folders, name))
        if which == "original" and version.sha256 and (
                _arrived(rel, ideal, version.sha256) or _left_twice(db, version, rel, ideal)):
            # A run that broke off after the move (or between link and removal): the file already stands where
            # it was going.
            chosen.add(folded(ideal))
            moves.append((version, which, ideal))
            continue
        candidate, counter = name, 1
        while (folded("/".join((*parts.folders, candidate))) in chosen
               or name_taken(db, parts.folders, candidate, staying, vacating - {folded(rel)}, document.id)):
            counter += 1
            stem = name[: -len(extension)] if extension and name.endswith(extension) else name
            candidate = f"{stem} ({counter}){extension}"
        target = "/".join((*parts.folders, candidate))
        chosen.add(folded(target))
        moves.append((version, which, target))
    return _in_order(moves)


def _in_order(moves: list[tuple[Version, str, str]]) -> list[tuple[Version, str, str]]:
    """The moves so that a file leaves a name before another one takes it. A ring of names (which the names of
    versions never make) keeps the order it has; the move into a name still taken then fails and is tried again."""
    def source(move: tuple[Version, str, str]) -> str:
        version, which, _target = move
        return folded(version.original_path if which == "original" else version.archive_path)

    left = list(moves)
    ordered: list[tuple[Version, str, str]] = []
    while left:
        sources = {source(move) for move in left}
        ready = [move for move in left if folded(move[2]) not in sources or folded(move[2]) == source(move)]
        if not ready:
            ordered.extend(left)
            break
        ordered.extend(ready)
        left = [move for move in left if move not in ready]
    return ordered


# --- Moving ---------------------------------------------------------------------------------------------------------


def move_without_overwriting(source: Path, target: Path) -> None:
    """``source`` to ``target``; never over an existing file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with _moving:
        if target.exists():
            raise StorageError("target exists")
        try:
            os.link(source, target)
        except FileExistsError as exc:
            raise StorageError("target exists") from exc
        except OSError:
            # No hard links on this disk (some network shares): a rename, now that the name is known to be free.
            os.rename(source, target)
            return
        os.unlink(source)


def prune_empty(directory: Path) -> None:
    """Folders left empty by a move go, up to (not including) ``dokumente/``."""
    base = root().resolve()
    current = directory
    while current != base and base in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def run_rename(db: Session, document_id: int) -> int:
    """Brings the files of a document to the names its fields give. Idempotent: what is in place is left alone, a move
    that was made but not written down is written down. Returns how many files moved. While a page tool works on the
    document, ``DocumentBusy`` (the job waits for the next round)."""
    with files_of([document_id], 0):
        return _rename(db, document_id)


def _rename(db: Session, document_id: int) -> int:
    document = db.get(Document, document_id)
    if document is None:
        return 0
    moved = 0
    for version, which, target in plan(db, document):
        current = version.original_path if which == "original" else version.archive_path
        source = safe_path(current)
        destination = safe_path(target)
        if not source.exists():
            # A run that broke off after the move: the file is already where it was going, and is the same file.
            intact = destination.exists() and (
                which != "original" or not version.sha256 or sha256_of(destination) == version.sha256
            )
            if not intact:
                raise StorageError("file missing")
        elif which == "original" and destination.exists() and _left_twice(db, version, current, target):
            # Both names hold the file: the old one goes, nothing is copied or overwritten.
            os.unlink(source)
        else:
            move_without_overwriting(source, destination)
            if which == "original" and version.size and destination.stat().st_size != version.size:
                raise StorageError("size changed")
        if which == "original":
            version.original_path = target
        else:
            version.archive_path = target
        db.commit()
        prune_empty(source.parent)
        moved += 1
    return moved


def remove_files(rels: list[str]) -> int:
    """Deletes the files of a document gone for good; a missing file is not an error. Folders left empty go too."""
    removed = 0
    for rel in rels:
        try:
            path = safe_path(rel)
        except StorageError:
            logger.warning("A stored path was refused and its file left alone")
            continue
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            pass
        prune_empty(path.parent)
    return removed


INCOMING = ".incoming-"


def sweep_incoming() -> int:
    """At start, before anything writes: what a write that broke off left under a temporary name goes. Returns how
    many."""
    base = root()
    if not base.is_dir():
        return 0
    removed = 0
    for directory, _folders, files in os.walk(base):
        for name in files:
            if name.startswith(INCOMING):
                try:
                    (Path(directory) / name).unlink()
                    removed += 1
                except OSError:
                    logger.warning("A temporary file could not be removed")
    if removed:
        logger.info("Temporary files of broken-off writes removed count=%s", removed)
    return removed


def incoming_path(label: str = "") -> Path:
    """A fresh temporary name inside ``dokumente/`` (so on the same disk as every place a file can go to, and swept at
    the next start when a write broke off). The folder is made."""
    base = root()
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{INCOMING}{label}{secrets.token_hex(8)}"


def adopt(source: Path, rel: str) -> Path:
    """A finished file that stands somewhere (another folder, another disk) becomes the file at ``rel``, without
    overwriting. On one disk it is a link and a removal; across disks it is copied to a temporary name beside the target
    first. ``source`` is gone afterwards."""
    destination = safe_path(rel)
    try:
        move_without_overwriting(source, destination)
        return destination
    except OSError:
        if destination.exists():
            raise
    # Another disk: copy beside the target, then put in place.
    temporary = incoming_path("copy-")
    try:
        shutil.copyfile(source, temporary)
        move_without_overwriting(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    source.unlink(missing_ok=True)
    return destination


def free_name(db: Session, folders: tuple[str, ...], name: str, own: set[str] | None = None) -> str:
    """``name`` or the first ``name (2)`` ... that neither the disk nor a version in the database has."""
    extension = Path(name).suffix
    stem = name[: -len(extension)] if extension else name
    candidate, counter = name, 1
    while name_taken(db, folders, candidate, own or set()):
        counter += 1
        candidate = f"{stem} ({counter}){extension}"
    return candidate


def archive_target(db: Session, document: Document, version: Version) -> str:
    """Where the PDF made from a picture goes, next to the original: ``<name> (searchable).pdf`` in the folders of the
    document's fields."""
    parts = parts_for(db, document)
    name = parts.stem + suffixes(version, document.current_version, ".pdf", True)
    return "/".join((*parts.folders, free_name(db, parts.folders, name)))


def write_new(rel: str, content: bytes) -> Path:
    """A file that did not exist: written whole to a temporary name and put in place without overwriting."""
    destination = safe_path(rel)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{INCOMING}{os.getpid()}-{threading.get_ident()}-{destination.name[:20]}")
    temporary.write_bytes(content)
    try:
        move_without_overwriting(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


__all__ = ["SEGMENT_MAX", "DocumentBusy", "Parts", "StorageError", "adopt", "archive_target", "files_of", "free_name",
           "incoming_path", "move_without_overwriting", "parts_for", "plan", "remove_files", "root", "run_rename",
           "safe_path", "sha256_of", "sweep_incoming", "write_new"]
