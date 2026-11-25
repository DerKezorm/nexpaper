"""What goes into a backup of nexpaper and how it comes back: the hooks of the shared module ``sicherung``
(``app/vendor/nexsicherung``, bauplaene/sicherung 1.0.0). The module runs everything around them (names, list,
schedule, keeping, upload, download, the copy before a restore, staging and the start).

The archive keeps nexpaper's format, so every backup made before the module stays readable and restorable: the
database, the settings in it and the server's secrets, in one ZIP. **Not the documents.**

The documents lie as readable files under ``<data>/dokumente`` and belong to the server's usual file backup; a copy of
them in every archive would make each one as big as the whole collection. The trial run names the documents the
restored database points at and that are missing (once there are documents).

* **The database is copied with SQLite's backup API**, never as a file: it runs in WAL mode, and a file copy misses
  what still sits in the ``-wal`` side file.
* **The manifest names the database with its size and sha256**, and the check before a restore compares both with what
  it unpacked: a flipped byte in the archive (the usual damage, a failing disk) is told as damaged, not as an error.
  The manifest itself is read up to ``MANIFEST_MAX`` bytes and no further, and its fields strictly by their kind.
* **A restore happens at the next start** (the module stages it in ``backups/restore-pending/``): ``unpack`` lays out
  the database and the key, ``apply`` swaps them before anything opens the database. The swap is made on temporary
  files and ends in ``os.replace``; whatever goes wrong before that leaves the live database as it was, and the module
  sets the staged folder aside (``restore-failed/``), tells the operators (``tell``) and the server starts on.
* **The trial run is the start, rehearsed.** It runs the same steps as the start on a scratch copy (the migrations up to
  today's schema, the end of the stored sign-ins) and demands every table and column nexpaper needs; triggers and views
  that nexpaper does not make are refused before anything runs. An archive that passes cannot stop the next start.
* **The search index is left out.** It is the largest part of the database (some 4 GB for 200,000 documents) and can be
  rebuilt from the text of the documents, which stays in the archive. The start after a restore makes the tables again
  and a job fills them (``search_index.queue_if_stale``). The trial run says so.

The archive holds ``secret.key``, the key the server seals its own secrets with (OIDC client secret, mail password,
AI key): without it a restore on another machine would bring those back unreadable. So an archive is as secret as
the database itself; downloading one asks for the operator's password once more (the module).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import time
import zipfile
import zlib
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError
from sqlalchemy import func, select, text

from .. import __version__, clock, private
from ..config import get_settings
from ..vendor import nexsicherung
from ..vendor.nexsicherung import Checked, Described, Part, Schedule
from ..vendor.nexsicherung.errors import BackupError
from . import settings_service

logger = logging.getLogger("nexpaper.backups")

MANIFEST = "nexpaper-backup.json"
DATABASE_ENTRY = "database/nexpaper.db"
#: The key the server encrypts its own secrets with (OIDC client secret, mail password): without it a restore on
#: another machine would bring those back unreadable. Whoever holds a backup holds the database anyway.
SECRET_ENTRY = "secret.key"
SQLITE_HEADER = b"SQLite format 3\x00"
_CHUNK = 1024 * 1024
#: The manifest is a few hundred bytes of JSON. More than this is read by nobody: an archive with a larger one is
#: refused, at the upload and in the list, so that none can make the server read megabytes at every look.
MANIFEST_MAX = 64 * 1024
#: What reading a damaged ZIP raises: a bad checksum, a broken compressed stream, a cut-off file, a method or a password
#: this reader does not know.
DAMAGE = (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError)
#: What an archive may unpack to, counted while it is read, never taken from what the archive says about itself: a
#: small ZIP can claim little and inflate to a full disk. The key is a line of text; the whole is what an upload may
#: carry.
SECRET_MAX = 4096
DATABASE_MAX = 16 * 1024**3
RESTORE_MAX = 64 * 1024**3
#: The trial run compares the checksums of the files on the disk as long as this many seconds last (the rest is only
#: looked for), so that it answers in good time on an archive of many gigabytes.
HASH_SECONDS = 20.0
#: The tables of the search index and the list of what is in it: not in the archive.
INDEX_TABLES = ("doc_fts", "doc_tri")

#: The schedule as nexpaper kept it before the module (``backup_schedule``, ``backup_keep``, their defaults in
#: ``settings_service.DEFAULTS``), with the time of day the module adds (``backup_time``): the night's hour nexpaper
#: used before (3 to 6) is 03:00.
DEFAULT_EVERY = "daily"
DEFAULT_TIME = "03:00"
DEFAULT_KEEP = 7

#: How long the trial run of this call may read files (``backups.check(name, hash_seconds=...)``); None:
#: ``HASH_SECONDS``.
_hash_seconds: ContextVar[float | None] = ContextVar("nexpaper_backup_hash_seconds", default=None)


@contextmanager
def reading_files_for(seconds: float):  # type: ignore[no-untyped-def]
    """The trial runs inside read the files on the disk for at most ``seconds``."""
    token = _hash_seconds.set(seconds)
    try:
        yield
    finally:
        _hash_seconds.reset(token)


@dataclass
class Manifest:
    version: str
    created: str
    kind: str
    note: str = ""
    accounts: int = 0
    #: Bytes and sha256 of the database inside.
    bytes: int = 0
    sha256: str = ""
    #: How many documents the database points at (0 in an archive of before there were documents).
    documents: int = 0
    #: Whether the search index is in the archive. It never is; an archive made elsewhere may have it.
    with_index: bool = False


class ManifestInvalid(BackupError):
    """The manifest is there and is JSON, but says things of the wrong kind (a count that is a word). Such an archive
    is listed as unusable, never trusted and never a cause of a server error."""


_Text = Annotated[StrictStr, Field(max_length=500)]
_Count = Annotated[StrictInt, Field(ge=0, le=2**62)]


class _ManifestFile(BaseModel):
    """What the manifest says about its own shape, strictly: no value is taken for another type."""

    model_config = ConfigDict(strict=True, extra="forbid")

    version: Annotated[StrictStr, Field(max_length=64)]
    created: Annotated[StrictStr, Field(max_length=64)]
    kind: Annotated[StrictStr, Field(max_length=32)]
    note: _Text = ""
    accounts: _Count = 0
    bytes: _Count = 0
    sha256: Annotated[StrictStr, Field(max_length=64)] = ""
    documents: _Count = 0
    with_index: StrictBool = False



def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _leave_out_index(connection: sqlite3.Connection) -> None:
    """The copy without the search index: its tables, the trigger that keeps them, and the list of what was indexed.
    ``VACUUM`` gives the room back; without it the copy would be as large as before and only compress better."""
    connection.commit()
    for table in INDEX_TABLES:
        connection.execute(f"DROP TABLE IF EXISTS {table}")
    connection.execute("DROP TRIGGER IF EXISTS documents_search_gone")
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'search_entries'")
    if exists.fetchone() is not None:
        connection.execute("DELETE FROM search_entries")
    connection.commit()
    connection.execute("VACUUM")


def _database_copy(target: Path) -> tuple[int, int]:
    """The database through SQLite's backup API, without the search index. Returns ``(accounts, documents)``."""
    source = sqlite3.connect(get_settings().database_path)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
        destination.execute("PRAGMA journal_mode=DELETE")
        destination.commit()
        _leave_out_index(destination)
        counts = []
        for table in ("users", "documents"):
            try:
                counts.append(int(destination.execute(f"SELECT count(*) FROM {table}").fetchone()[0]))  # noqa: S608
            except sqlite3.DatabaseError:
                counts.append(0)
        return counts[0], counts[1]
    finally:
        destination.close()
        source.close()



def _manifest(archive: zipfile.ZipFile) -> Manifest:
    """The manifest of an archive. ``BackupError`` when there is none or it is no JSON, ``ManifestInvalid`` when it is
    JSON that does not have the shape (types are checked strictly, see ``_ManifestFile``)."""
    try:
        info = archive.getinfo(MANIFEST)
        if info.file_size > MANIFEST_MAX:
            raise BackupError("backup_invalid", "the manifest of the archive is larger than a manifest can be")
        with archive.open(info) as source:
            data = source.read(MANIFEST_MAX + 1)
        if len(data) > MANIFEST_MAX:
            raise BackupError("backup_invalid", "the manifest of the archive is larger than a manifest can be")
        raw = json.loads(data.decode("utf-8"))
    except (KeyError, ValueError, TypeError) as exc:
        raise BackupError("backup_invalid", "the archive has no readable manifest") from exc
    except DAMAGE as exc:
        raise BackupError("backup_damaged", "the archive is damaged; its manifest cannot be read") from exc
    try:
        checked = _ManifestFile.model_validate(raw)
    except ValidationError as exc:
        raise ManifestInvalid("backup_invalid", "the manifest of the archive is not a manifest") from exc
    return Manifest(**checked.model_dump())



class _Tee:
    """A sink that writes what it is given and counts and hashes it on the way, so that the checksum is of what was
    unpacked, not of a second reading."""

    def __init__(self, sink: Any) -> None:
        self.sink = sink
        self.size = 0
        self.hasher = hashlib.sha256()

    def write(self, chunk: bytes) -> None:
        self.size += len(chunk)
        self.hasher.update(chunk)
        self.sink.write(chunk)

    def hexdigest(self) -> str:
        return self.hasher.hexdigest()


def _same_as_manifest(tee: _Tee, manifest: Manifest) -> bool:
    """The database as unpacked against the size and the sha256 the manifest names (a field the manifest leaves empty,
    as an archive made elsewhere may, is not compared)."""
    if manifest.sha256 and tee.hexdigest() != manifest.sha256:
        return False
    return not manifest.bytes or tee.size == manifest.bytes


class _Budget:
    """Bytes an unpacking may still write, shared by every entry of one archive."""

    def __init__(self, total: int) -> None:
        self.left = total


def _copy_limited(source: Any, sink: Any, limit: int, budget: _Budget) -> int:
    """Copies at most ``limit`` bytes and no more than the budget holds; ``backup_too_large`` past either."""
    written = 0
    while chunk := source.read(_CHUNK):
        written += len(chunk)
        budget.left -= len(chunk)
        if written > limit or budget.left < 0:
            raise BackupError("backup_too_large", "the archive unpacks to more than a backup may hold")
        if sink is not None:
            sink.write(chunk)
    return written



def _rehearse(scratch: Path) -> bool:
    """The start, run on the copy of the database: the steps that bring it to today's schema, the end of the stored
    sign-ins, and a look for everything nexpaper needs. A database that stops any of it would stop every start after the
    restore. Only the kind of the error is logged, never its text (it can quote the database's contents)."""
    from .. import db

    try:
        db.rehearse(scratch)
        _end_restored_sessions(scratch)
    except Exception as exc:  # noqa: BLE001 - whatever goes wrong here means the archive cannot be used
        logger.warning("The trial run of a backup could not start its database error=%s", type(exc).__name__)
        return False
    return True



@dataclass
class _Revived:
    devices: int = 0
    keys: int = 0
    links: int = 0
    link_documents: int = 0
    pdf_passwords: int = 0
    upload_requests: int = 0


#: What is alive: the token hash and when it ends (empty: it does not), by table. The same question to the backup and to
#: this server. A further document of a link (N2) is its link's hash and the document's number: one that a link valid in
#: the backup shows, and no living link shows here now, comes back with the restore.
_ALIVE = (
    ("devices", "SELECT token_hash, NULL FROM devices WHERE revoked_at IS NULL"),
    ("keys", "SELECT token_hash, expires_at FROM api_keys WHERE blocked_at IS NULL"),
    ("links", "SELECT token_hash, until FROM links WHERE revoked_at IS NULL"),
    ("link_documents", ("SELECT l.token_hash || ':' || d.document_id, l.until FROM link_documents d "
                        "JOIN links l ON l.id = d.link_id WHERE l.revoked_at IS NULL")),
    # A kept PDF password is one by its sealed value (a fresh nonce each time): one deleted since does not come back
    # under the number of a new one.
    ("pdf_passwords", "SELECT sealed, NULL FROM pdf_passwords"),
    # An upload request takes files while it is not revoked, before its end, and not all its files are there: one that
    # is used up, revoked or gone here and open in the backup takes files again after a restore.
    ("upload_requests", ("SELECT token_hash, until FROM upload_requests WHERE revoked_at IS NULL "
                         "AND received < max_files")),
)


def _alive(rows: Any) -> set[str]:
    """The hashes among ``(hash, end)`` rows that are not over yet."""
    now = clock.now().astimezone(UTC)
    alive = set()
    for token_hash, end in rows:
        if end is not None:
            try:
                moment = end if isinstance(end, datetime) else datetime.fromisoformat(str(end))
            except ValueError:
                continue
            if (moment if moment.tzinfo else moment.replace(tzinfo=UTC)) <= now:
                continue
        alive.add(str(token_hash))
    return alive


def _revived(connection_path: Path) -> _Revived:
    """How many devices, keys and links a restore would bring back to life: valid in the backup, not valid on this
    server any more (revoked, blocked or removed since). A person who locked a lost phone out after the backup would
    find it paired again; the trial run says so, with numbers."""
    from ..db import SessionLocal

    counts: dict[str, int] = {}
    connection = sqlite3.connect(f"file:{connection_path.as_posix()}?mode=ro", uri=True)
    try:
        with SessionLocal() as live:
            for key, query in _ALIVE:
                try:
                    then = _alive(connection.execute(query).fetchall())
                except sqlite3.DatabaseError:
                    continue
                now = _alive(live.execute(text(query)).fetchall())
                counts[key] = len(then - now)
    finally:
        connection.close()
    return _Revived(counts.get("devices", 0), counts.get("keys", 0), counts.get("links", 0),
                    counts.get("link_documents", 0), counts.get("pdf_passwords", 0),
                    counts.get("upload_requests", 0))


@dataclass
class _Files:
    """What the files on the disk say about the documents of a database."""

    documents: int = 0
    missing: int = 0
    changed: int = 0
    not_compared: int = 0
    newer: int = 0


def _files_of(*, connection_path: Path, hash_seconds: float) -> _Files:
    """The documents of the (unpacked) database of an archive against the files in the document folder of this server.
    Opens the database read only; a database that lacks the tables (an archive of before there were documents) holds no
    documents."""
    from . import filecheck

    found = _Files()
    connection = sqlite3.connect(f"file:{connection_path.as_posix()}?mode=ro", uri=True)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not {"documents", "versions"} <= tables:
            return found
        has_hash = any(row[1] == "archive_sha256" for row in connection.execute("PRAGMA table_info(versions)"))
        archive_hash = "v.archive_sha256" if has_hash else "''"
        found.documents = int(connection.execute("SELECT count(*) FROM documents").fetchone()[0])
        highest = 0
        sequence = None
        if "sqlite_sequence" in tables:
            sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name = 'documents'").fetchone()
        if sequence is not None:
            highest = int(sequence[0])
        else:
            highest = int(connection.execute("SELECT coalesce(max(id), 0) FROM documents").fetchone()[0])
        deadline = time.monotonic() + hash_seconds
        missing: set[int] = set()
        changed: set[int] = set()
        query = ("SELECT d.id, v.original_path, v.sha256, v.archive_path, " + archive_hash + " FROM versions v "  # noqa: S608
                 "JOIN documents d ON d.id = v.document_id WHERE d.status != 'processing' ORDER BY d.id, v.n")
        for document_id, original, original_sha, archive, archive_sha in connection.execute(query):
            for rel, expected in ((original, original_sha), (archive, archive_sha)):
                if not rel:
                    continue
                reading = time.monotonic() < deadline
                what, _digest, _size = filecheck.look(str(rel), str(expected or ""), compare=reading,
                                                      deadline=deadline)
                if what == filecheck.UNREAD:
                    # The time ran out in the middle of a large file: it is there, nothing more is known of it.
                    found.not_compared += 1
                elif what == filecheck.MISSING:
                    missing.add(document_id)
                elif what == filecheck.CHANGED:
                    changed.add(document_id)
                if not reading and what == "ok":
                    found.not_compared += 1
        found.missing = len(missing)
        found.changed = len(changed - missing)
        for document_id in sorted(missing)[:20]:
            logger.info("A file of document %s is missing on the disk, seen by the trial run of a backup", document_id)
    except sqlite3.DatabaseError:
        return _Files()
    finally:
        connection.close()
    from ..db import SessionLocal
    from ..models import Document

    with SessionLocal() as db:
        found.newer = int(db.scalar(select(func.count()).select_from(Document).where(Document.id > highest)) or 0)
    return found



def _end_restored_sessions(database: Path) -> None:
    """Sign-ins stored in the backup would come back to life, even ones ended since: everybody signs in anew. The state
    of the check of the files goes too: the files on the disk may not be the ones the backup knew, so the check runs
    again at the next start instead of waiting for its week."""
    connection = sqlite3.connect(database)
    try:
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='auth_sessions'").fetchone():
            connection.execute("DELETE FROM auth_sessions")
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='settings'").fetchone():
            connection.execute("DELETE FROM settings WHERE key = 'files_check'")
        connection.commit()
    finally:
        connection.close()



def _swap(pending: Path) -> dict[str, Any]:
    """Puts the staged files in place. Everything that can fail is done on temporary files next to the live ones; the
    live database is touched only by the ``os.replace`` at the end. Staged files stay until the end, so a stop in
    between only means the next start does it again."""
    settings = get_settings()
    manifest = json.loads((pending / MANIFEST).read_text(encoding="utf-8"))
    target = settings.database_path
    staged = target.with_name(target.name + ".restoring")
    key = settings.data_dir / "secret.key"
    key_staged = key.with_name(key.name + ".restoring")
    try:
        shutil.copyfile(pending / "nexpaper.db", staged)
        _end_restored_sessions(staged)
        if (pending / "secret.key").is_file():
            shutil.copyfile(pending / "secret.key", key_staged)
            try:
                key_staged.chmod(0o600)
            except OSError:
                pass
        os.replace(staged, target)
        # Left behind, SQLite would read the old database's WAL into the restored one.
        for suffix in ("-wal", "-shm", "-journal"):
            target.with_name(target.name + suffix).unlink(missing_ok=True)
        if key_staged.is_file():
            os.replace(key_staged, key)
    finally:
        staged.unlink(missing_ok=True)
        key_staged.unlink(missing_ok=True)
    return manifest



FAILED_TEXTS = {
    "de": ("Wiederherstellen gescheitert",
           "Die Sicherung ließ sich beim Neustart nicht einspielen. Der Server läuft mit den Daten von vorher weiter."),
    "en": ("Restore failed",
           "The backup could not be put in place at the restart. The server went on with the data it had."),
}




# --- What goes in ---------------------------------------------------------------------------------------------------


def write_archive(target: Path, *, kind: str, note: str, created: str, version: str = __version__) -> Manifest:
    """The archive as nexpaper made it before the module and as ``pack`` makes it now: the database through the backup
    API without the search index, the key, the manifest last (an archive without it is recognisably incomplete).
    ``target`` is an empty file only the owner may read. Returns the manifest written."""
    # The working copy of the database carries the process and a counter of its own: never shared with another one.
    database = target.with_name(f".{target.name}.{os.getpid()}-{time.time_ns()}.db")
    try:
        # Only the owner's before a byte is in it: the archive holds the key and everything else.
        private.new_file(database)
        accounts, documents = _database_copy(database)
        manifest = Manifest(version=version, created=created, kind=kind, note=note, accounts=accounts,
                            bytes=database.stat().st_size, sha256=_hash_file(database), documents=documents)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.write(database, DATABASE_ENTRY)
            key = get_settings().data_dir / "secret.key"
            if key.is_file():
                archive.write(key, SECRET_ENTRY)
            # Last: an archive without its manifest is recognisably incomplete.
            archive.writestr(MANIFEST, json.dumps(asdict(manifest), ensure_ascii=False))
    finally:
        database.unlink(missing_ok=True)
    logger.info("Backup made kind=%s accounts=%s documents=%s bytes=%s", kind, manifest.accounts, manifest.documents,
                manifest.bytes)
    return manifest


# --- The trial run --------------------------------------------------------------------------------------------------


def check_archive(path: Path, *, hash_seconds: float = HASH_SECONDS) -> Checked:
    """The trial run: is the archive whole (the checksum of the manifest agrees with what is inside), can its database
    be opened and started like the real thing, and what does it hold? And what would the restore do to the documents:
    which files of the archive's documents are missing on the disk or have another checksum (read for at most
    ``hash_seconds``, in a large file too; the rest is only looked for), and how many documents of today it would drop.
    ``backup_damaged`` when the archive cannot be read to its end or does not match its manifest. Changes nothing."""
    from .. import db

    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise BackupError("backup_invalid", "not a ZIP archive") from exc
    with archive:
        try:
            manifest = _manifest(archive)
        except ManifestInvalid:
            logger.warning("A backup with a manifest of the wrong shape was looked at")
            return Checked(database_ok=False, details={"schema": 0})
        members = {info.filename: info for info in archive.infolist()}
        budget = _Budget(RESTORE_MAX)
        database_ok = False
        schema = 0
        found = _Files()
        revived = _Revived()
        if DATABASE_ENTRY in members:
            scratch = nexsicherung.archives.scratch("check")
            try:
                try:
                    with archive.open(DATABASE_ENTRY) as source, open(scratch, "wb") as raw:
                        tee = _Tee(raw)
                        _copy_limited(source, tee, DATABASE_MAX, budget)
                except DAMAGE as exc:
                    raise BackupError("backup_damaged", "the archive is damaged; nothing was changed") from exc
                if not _same_as_manifest(tee, manifest):
                    raise BackupError("backup_damaged", "the database in the archive is not the one the manifest names")
                with open(scratch, "rb") as head:
                    is_sqlite = head.read(16) == SQLITE_HEADER
                if is_sqlite:
                    connection = sqlite3.connect(scratch)
                    try:
                        whole = connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                        schema = int(connection.execute("PRAGMA user_version").fetchone()[0])
                    finally:
                        connection.close()
                    # A database this nexpaper cannot open would stop every start after the restore: one from a newer
                    # version, or one without a version. An older one is fine; the start brings it up.
                    database_ok = whole and 1 <= schema <= db.SCHEMA_VERSION
                    if database_ok:
                        database_ok = _rehearse(scratch)
                    if database_ok:
                        found = _files_of(connection_path=scratch, hash_seconds=hash_seconds)
                        revived = _revived(scratch)
            except (sqlite3.DatabaseError, OSError):
                database_ok = False
            finally:
                scratch.unlink(missing_ok=True)
        # An archive of ours holds exactly these three parts. Anything else came from elsewhere.
        foreign = sorted(info.filename for info in archive.infolist()
                         if not info.is_dir() and info.filename not in (MANIFEST, DATABASE_ENTRY, SECRET_ENTRY))
        if foreign:
            database_ok = False
    details = {
        # The schema version of the database inside (``db.SCHEMA_VERSION``); 0 when it could not be read.
        "schema": schema,
        # How many documents the database inside points at.
        "documents": found.documents,
        # Documents of the archive with a file that is not in the document folder, and with a file that has another
        # checksum (a file counts once per document). ``not_compared``: files only looked for, not read, because the
        # time for reading ran out.
        "missing_documents": found.missing,
        "changed_documents": found.changed,
        "not_compared": found.not_compared,
        # Documents the server has now that the archive does not know (they would go; their files stay in the folder).
        "newer_documents": found.newer,
        # The search is built anew after the restore (always, when there are documents): it works while that goes on,
        # with fewer hits at first.
        "rebuilds_index": found.documents > 0 and schema >= 6,
        # What a restore brings back to life: devices, keys and links that were valid when the backup was made and are
        # revoked, blocked or gone on this server now; further documents of such a link (N2); kept PDF passwords (P1);
        # upload requests (U1). Numbers only, never a name.
        "revived_devices": revived.devices,
        "revived_keys": revived.keys,
        "revived_links": revived.links,
        "revived_link_documents": revived.link_documents,
        "revived_pdf_passwords": revived.pdf_passwords,
        "revived_upload_requests": revived.upload_requests,
    }
    too_new = schema > db.SCHEMA_VERSION
    return Checked(
        database_ok=database_ok, files_ok=not foreign, damaged=foreign[:20], details=details,
        # A database of a newer schema is refused with the code nexpaper always had for it (the module refuses an
        # archive of a newer version by itself; this holds when the version in the manifest does not say so).
        blocked="backup_too_new" if too_new else "",
        blocked_text="the archive comes from a newer nexpaper; nothing was changed" if too_new else "",
    )


# --- How it comes back ----------------------------------------------------------------------------------------------


def unpack_archive(path: Path, pending: Path) -> None:
    """The database and the key laid out in ``pending`` for the next start, each compared again with the manifest and
    counted against its limit while it is read (the archive may have changed since the trial run)."""
    budget = _Budget(RESTORE_MAX)
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = _manifest(archive)
            with archive.open(DATABASE_ENTRY) as source, open(pending / "nexpaper.db", "wb") as raw:
                tee = _Tee(raw)
                _copy_limited(source, tee, DATABASE_MAX, budget)
            if not _same_as_manifest(tee, manifest):
                raise BackupError("backup_damaged", "the archive is damaged; nothing was changed")
            if SECRET_ENTRY in archive.namelist():
                with archive.open(SECRET_ENTRY) as source, open(pending / "secret.key", "wb") as sink:
                    _copy_limited(source, sink, SECRET_MAX, budget)
            # Last: the manifest says the database and the key are complete (the module's marker follows).
            (pending / MANIFEST).write_bytes(json.dumps(asdict(manifest), ensure_ascii=False).encode())
    except KeyError as exc:
        raise BackupError("backup_invalid", "the archive holds no database") from exc
    except DAMAGE as exc:
        raise BackupError("backup_damaged", "the archive is damaged; nothing was changed") from exc


def restore_failed_notice() -> Any:
    from . import tell

    return tell.Notice(
        texts=FAILED_TEXTS, url="/settings/storage", tag="restore-failed",
        mail_subject="nexpaper: the restore of a backup failed",
        mail_body=("The backup you chose could not be put in place when nexpaper restarted. The server went on with "
                   "the data it had, and the staged files were put aside in the backups folder (restore-failed)."
                   "\n\nThe backups and the log: {where}\n"),
    )


class NexpaperHooks(nexsicherung.AppHooks):
    # --- What goes in

    def pack(self, target: Path, *, kind: str, note: str, created: str) -> None:
        write_archive(target, kind=kind, note=note, created=created)

    def describe(self, path: Path) -> Described:
        try:
            with zipfile.ZipFile(path) as archive:
                manifest = _manifest(archive)
                if DATABASE_ENTRY not in archive.namelist():
                    raise BackupError("backup_invalid", "the archive holds no database")
        except zipfile.BadZipFile as exc:
            raise BackupError("backup_invalid", "not a ZIP archive") from exc
        try:
            datetime.fromisoformat(manifest.created)
        except (TypeError, ValueError) as exc:
            raise BackupError("backup_invalid", "the archive has no readable date") from exc
        return Described(created=manifest.created, kind=manifest.kind, note=manifest.note, version=manifest.version,
                         facts={"accounts": manifest.accounts, "documents": manifest.documents})

    def check(self, path: Path, *, viewer: Any = None, archive_password: str | None = None) -> Checked:
        seconds = _hash_seconds.get()
        return check_archive(path, hash_seconds=HASH_SECONDS if seconds is None else seconds)

    # --- How it comes back, at the next start

    def unpack(self, path: Path, pending: Path, *, archive_password: str | None = None) -> None:
        unpack_archive(path, pending)

    def apply(self, pending: Path) -> None:
        if not (pending / MANIFEST).is_file() or not (pending / "nexpaper.db").is_file():
            raise BackupError("backup_invalid", "the staged restore is incomplete")
        manifest = _swap(pending)
        logger.info("Backup restored created=%s", manifest.get("created"))

    def tidy(self) -> None:
        """At every start, before a staged restore is applied.

        * A restore staged by nexpaper before the module (1.11 and older) has the database and the manifest in
          ``restore-pending/`` but not the module's marker; the old version wrote the manifest last, so with both there
          it is complete and gets the marker (else the module would throw it away).
        * An empty archive a stopped process left: the module names an archive before ``pack`` writes it, and a process
          stopped in between leaves that name empty, listed as unreadable for good. TODO sicherung 1.0.1: the module
          writes under a working name and tidies itself (E29); then this part goes."""
        from ..vendor.nexsicherung import restore

        pending = restore.pending_folder()
        marker = pending / restore.MARKER
        if pending.is_dir() and not marker.exists() and (pending / MANIFEST).is_file() \
                and (pending / "nexpaper.db").is_file():
            try:
                staged = json.loads((pending / MANIFEST).read_text(encoding="utf-8"))
                created = str(staged.get("created") or "") if isinstance(staged, dict) else ""
                marker.write_text(json.dumps({"name": "", "created": created, "version": "", "at": ""}),
                                  encoding="utf-8")
                logger.info("A restore staged before the shared backup module is taken over")
            except (OSError, ValueError):
                pass
        folder = nexsicherung.archives.folder()
        if folder.is_dir():
            for path in folder.glob("nexpaper-*.zip"):
                try:
                    if path.is_file() and path.stat().st_size == 0 and nexsicherung.archives.known_name(path.name):
                        path.unlink()
                        logger.warning("An empty backup left by a stopped process was removed name=%s", path.name)
                except OSError:
                    continue

    # --- The schedule, under nexpaper's own keys

    def load_schedule(self) -> Schedule:
        from ..db import SessionLocal

        with SessionLocal() as db:
            every = settings_service.get(db, "backup_schedule")
            at = settings_service.get(db, "backup_time")
            keep = settings_service.get(db, "backup_keep")
        model = nexsicherung.model
        return Schedule(
            every=every if every in nexsicherung.EVERY else DEFAULT_EVERY,
            time=at if isinstance(at, str) and model.TIME.match(at) else DEFAULT_TIME,
            keep=keep if isinstance(keep, int) and not isinstance(keep, bool)
            and model.KEEP_MIN <= keep <= model.KEEP_MAX else DEFAULT_KEEP,
        )

    def save_schedule(self, schedule: Schedule) -> None:
        from ..db import SessionLocal

        with SessionLocal() as db:
            settings_service.save(db, {"backup_schedule": schedule.every, "backup_time": schedule.time,
                                       "backup_keep": schedule.keep})

    # --- The storage

    def parts(self) -> list[Part]:
        """The card "Speicher": the documents (of them the originals, by the sizes noted when they came in), the
        database (of it the search index), the cache of page pictures, the exports and the backups."""
        from . import exports, pages, space, storage

        documents = space.folder_size(storage.root())
        cache = space.folder_size(pages.cache_root())
        exported = space.folder_size(exports.folder())
        # Counted each time (the module measures at most once a minute, and anew after a backup was made or deleted):
        # a few files, and the card should show a new one at once.
        saved, _files, saved_complete = space.count_folder(nexsicherung.archives.folder())
        index = space.index_bytes()
        found = [
            Part("documents", int(documents["bytes"]), complete=bool(documents["complete"])),
            Part("originals", space.originals_bytes(), within="documents"),
            Part("database", space.database_bytes()),
        ]
        if index is not None:
            found.append(Part("index", index, within="database"))
        found += [
            Part("pages", int(cache["bytes"]), complete=bool(cache["complete"])),
            Part("exports", int(exported["bytes"]), complete=bool(exported["complete"])),
            Part("backups", saved, complete=saved_complete),
        ]
        return found

    def places(self) -> dict[str, Path]:
        """The documents may lie on a disk of their own (a share is fine for them; the card names it)."""
        from . import storage

        root = storage.root()
        return {"documents": root if root.exists() else get_settings().data_dir}

    # --- Telling

    def tell(self, event: str, details: dict[str, Any]) -> None:
        if event != "restore_failed":
            return
        from . import tell

        tell.operator(restore_failed_notice())


def configure() -> NexpaperHooks:
    """The module set up for nexpaper: its folders, version and hooks. At the start, before ``apply_pending``; done on
    import too, so the tests find it configured."""
    settings = get_settings()
    hooks = NexpaperHooks()
    nexsicherung.configure(nexsicherung.AppConfig(
        app_name="nexpaper", data_dir=settings.data_dir, version=__version__, hooks=hooks,
        database_path=settings.database_path,
    ))
    return hooks
