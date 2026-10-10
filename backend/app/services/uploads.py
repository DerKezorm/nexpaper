"""Uploading in pieces, with resumption: for apps, scripts and every file too large for one request.

1. **Announce** (``start``): size, SHA-256, file name, vault. When the person already has a document with this very file
   (one they may see: ``services/similar.py``) the answer is "already there" with that document and **nothing is
   transferred**. Else an upload id, the size of a piece and what has arrived so far (nothing).
2. **Pieces** (``append``): each at the offset where the last ended, in order. A piece at any other offset (a gap, or an
   overlap) is refused with the offset the server expects; so an app that lost its connection asks for the state
   (``status``) and goes on from there. Pieces go straight to a file in ``<data>/uploads/``; nothing is held in memory.
3. **Finish** (``finish``): the whole file is checked against the announced SHA-256 and its kind is read from the
   content; if either is wrong the upload is thrown away. Then it becomes a document. Finishing twice (a double click)
   makes one document: the claim is one statement that exactly one caller wins, and a caller after it gets the same
   document.
4. **Abort** (``abort``), or time: an upload ends 24 hours after its last piece and ``sweep`` removes what ran out.

An upload id belongs to the account that made it; anybody else's answers 404. The bytes an account may have open at once
and how many uploads are limits the operator sets.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import shutil
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..errors import error
from ..models import EDIT, Document, Upload
from . import filetypes, limits, receiving, rights, similar, storage

logger = logging.getLogger("nexpaper.uploads")

FOLDER = "uploads"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
OPEN, FINISHING, DONE = "open", "finishing", "done"
#: Uploads being written at this moment in this process: one writer per upload.
_writing: set[str] = set()
_writing_lock = threading.Lock()


def folder() -> Path:
    return get_settings().data_dir / FOLDER


def part_path(upload_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", upload_id):
        raise ValueError("id")
    return folder() / f"{upload_id}.part"


@dataclass
class Started:
    upload: Upload | None
    #: The document the person already has with this file; then there is no upload.
    existing: Document | None = None
    #: The upload is one that was open already for this file (the person comes back after a closed tab).
    resumed: bool = False


def _lapsed(upload: Upload) -> bool:
    return upload.expires_at <= clock.now()


def _mine(db: Session, uid: int, upload_id: str) -> Upload:
    upload = db.get(Upload, upload_id) if re.fullmatch(r"[0-9a-f]{32}", upload_id) else None
    if upload is None or upload.user_id != uid:
        raise error("not_found", "Not found.", 404)
    if upload.state != DONE and _lapsed(upload):
        _remove(db, upload)
        raise error("upload_expired", "This upload has run out. Start it again.", 410)
    return upload


def _remove(db: Session, upload: Upload) -> None:
    part_path(upload.id).unlink(missing_ok=True)
    db.execute(delete(Upload).where(Upload.id == upload.id))
    db.commit()


# --- Announce ---------------------------------------------------------------------------------------------------------


def start(
    db: Session, uid: int, *, vault_id: int | None, filename: str, size: int, sha256: str, source: str,
    key_id: int | None = None, document_id: int | None = None,
) -> Started:
    sha256 = sha256.lower()
    if not SHA256.match(sha256):
        raise error("invalid_input", "The checksum is the SHA-256 as 64 hexadecimal digits.", 422, fields=["sha256"])
    current = limits.current(db)
    if size < 1:
        raise error("empty_file", "The file is empty.", 422)
    if size > current.max_file:
        raise error("too_large", f"The file is larger than the limit of {current.max_file // limits.MB} MB.", 413,
                    max_mb=current.max_file // limits.MB)
    if document_id is not None:
        # A new version of a document (the page tools): the right to change it, not a vault, decides; a key that only
        # brings files in has none. The file the document has now is not sent again.
        if key_id is not None:
            raise error("key_scope", "A key for uploading cannot add versions.", 403)
        from . import pagetools

        document = pagetools.ready_for_version(db, uid, document_id)
        if pagetools.current_version(db, document).sha256 == sha256:
            raise error("same_file", "This file is the current version already.", 409)
        target = document.vault_id
    else:
        target = receiving.resolve_vault(db, uid, vault_id)
        # The same file the person may see already: nothing is transferred. Only what they may see counts, so a file
        # kept where they cannot look is treated like a new one.
        twin = similar.same_file(db, uid, sha256)
        if twin is not None:
            return Started(upload=None, existing=twin)
    now = clock.now()
    open_rows = list(db.scalars(select(Upload).where(Upload.user_id == uid, Upload.state == OPEN)))
    live = [row for row in open_rows if not _lapsed(row)]
    for row in open_rows:
        if _lapsed(row):
            _remove(db, row)
    # The same file announced again (a closed tab, a phone that came back): the upload that waits goes on where it is.
    again = next((row for row in sorted(live, key=lambda r: r.created_at, reverse=True)
                  if row.sha256 == sha256 and row.size == size and row.vault_id == target
                  and row.api_key_id == key_id and row.target_document_id == document_id), None)
    if again is not None:
        _settle(db, again)
        return Started(upload=again, resumed=True)
    if len(live) >= current.open_count:
        raise error("too_many_uploads", "Too many uploads are open at once. Finish or cancel one first.", 429)
    if sum(row.size for row in live) + size > current.open_bytes:
        raise error("upload_space", "The uploads that are open take all the space this account may use. Finish or "
                    "cancel one first.", 429)
    folder().mkdir(parents=True, exist_ok=True)
    try:
        if shutil.disk_usage(folder()).free < size:
            raise error("disk_full", "The server has no room for this file.", 507)
    except OSError:
        pass
    upload = Upload(
        id=secrets.token_hex(16), user_id=uid, vault_id=target, filename=filetypes.file_name(filename),
        size=size, sha256=sha256, received=0, source=source, state=OPEN, created_at=now,
        expires_at=now + timedelta(hours=limits.UPLOAD_HOURS), api_key_id=key_id, target_document_id=document_id,
    )
    db.add(upload)
    db.commit()
    part_path(upload.id).touch()
    return Started(upload=upload)


def open_ones(db: Session, uid: int) -> list[Upload]:
    """The uploads of this account that wait for more pieces, newest first."""
    found = list(db.scalars(select(Upload).where(Upload.user_id == uid, Upload.state == OPEN)
                            .order_by(Upload.created_at.desc())))
    live = []
    for row in found:
        if _lapsed(row):
            _remove(db, row)
        else:
            _settle(db, row)
            live.append(row)
    return live


def status(db: Session, uid: int, upload_id: str) -> Upload:
    upload = _mine(db, uid, upload_id)
    if upload.state == OPEN:
        _settle(db, upload)
    return upload


def _settle(db: Session, upload: Upload, writer: bool = False) -> None:
    """The file and the record agree on how much has arrived. A piece written and not yet counted (a stop in between) is
    cut off; a file shorter than the record (it was damaged) lowers the record. While a piece is being received the
    bytes beyond the record are that piece, not a rest: only the writer itself (``writer``) settles then, a question
    for the state in the meantime leaves the file alone."""
    if not writer:
        with _writing_lock:
            if upload.id in _writing:
                return
    path = part_path(upload.id)
    have = _length(path)
    if have > upload.received:
        with path.open("r+b") as handle:
            handle.truncate(upload.received)
    elif have < upload.received:
        db.execute(update(Upload).where(Upload.id == upload.id).values(received=have))
        db.commit()
        upload.received = have
        if not path.exists():
            path.touch()


def _length(path: Path) -> int:
    """How many bytes the file has. Asked of the file itself, not of its folder: on Windows the size in the folder lags
    behind while another handle writes."""
    try:
        with path.open("rb") as handle:
            return handle.seek(0, os.SEEK_END)
    except FileNotFoundError:
        return 0

# --- Pieces -----------------------------------------------------------------------------------------------------------


async def append(db: Session, uid: int, upload_id: str, offset: int, stream: AsyncIterator[bytes]) -> Upload:
    upload = _mine(db, uid, upload_id)
    if upload.state != OPEN:
        raise error("upload_closed", "This upload is finished.", 409)
    with _writing_lock:
        if upload.id in _writing:
            raise error("upload_busy", "A piece of this upload is being received.", 409)
        _writing.add(upload.id)
    try:
        db.refresh(upload)
        _settle(db, upload, writer=True)
        if offset != upload.received:
            raise error("offset_mismatch", "The piece does not start where the last one ended.", 409,
                        received=upload.received)
        room = upload.size - upload.received
        written = 0
        path = part_path(upload.id)
        too_big = False
        try:
            with path.open("ab") as handle:
                async for chunk in stream:
                    written += len(chunk)
                    if written > room or written > limits.MAX_PIECE:
                        too_big = True
                        break
                    handle.write(chunk)
        except OSError as exc:
            _cut(path, upload.received)
            raise error("disk_full", "The server cannot store the file.", 507) from exc
        except BaseException:
            # The connection broke in the middle of a piece: the bytes of it are cut off, the record still says how far
            # the pieces that were complete reach.
            _cut(path, upload.received)
            raise
        if too_big:
            _cut(path, upload.received)
            if written > room:
                raise error("exceeds_size", "The piece reaches past the size that was announced.", 413,
                            received=upload.received)
            raise error("piece_too_large", "A piece is at most 64 MB.", 413, received=upload.received)
        if written == 0:
            raise error("empty_piece", "The piece is empty.", 422, received=upload.received)
        db.execute(update(Upload).where(Upload.id == upload.id, Upload.state == OPEN).values(
            received=upload.received + written, expires_at=clock.now() + timedelta(hours=limits.UPLOAD_HOURS)))
        db.commit()
        db.refresh(upload)
        return upload
    finally:
        with _writing_lock:
            _writing.discard(upload.id)


def _cut(path: Path, length: int) -> None:
    try:
        with path.open("r+b") as handle:
            handle.truncate(length)
    except OSError:
        pass


# --- Finish and abort -------------------------------------------------------------------------------------------------


def finish(db: Session, uid: int, upload_id: str) -> tuple[Document, Document | None, bool]:
    """The upload becomes a document. Returns the document, the one the person already has with this very file (if any),
    and whether this call made it (False: an earlier call did and this one returns the same document)."""
    upload = _mine(db, uid, upload_id)
    if upload.state == DONE and upload.document_id:
        done = db.get(Document, upload.document_id)
        if done is None:
            raise error("not_found", "Not found.", 404)
        return done, similar.visible_duplicate(db, uid, done), False
    claimed = db.execute(update(Upload).where(Upload.id == upload.id, Upload.state == OPEN, Upload.user_id == uid)
                         .values(state=FINISHING)).rowcount
    db.commit()
    if claimed != 1:
        raise error("upload_busy", "This upload is being finished.", 409)
    try:
        return _make_document(db, uid, upload)
    except Exception:
        db.rollback()
        # Back to receiving unless the upload was thrown away on purpose.
        db.execute(update(Upload).where(Upload.id == upload.id, Upload.state == FINISHING).values(state=OPEN))
        db.commit()
        raise


def _discard(db: Session, upload: Upload) -> None:
    db.rollback()
    _remove(db, upload)


def _make_document(db: Session, uid: int, upload: Upload) -> tuple[Document, Document | None, bool]:
    path = part_path(upload.id)
    # The right to add is looked at again now: it may have been taken away since the upload was announced. A new
    # version needs the right to change its document (``pagetools.accept_version`` asks).
    if upload.target_document_id is None:
        rights.require_vault(db, uid, upload.vault_id, EDIT)
    _settle(db, upload)
    if upload.received != upload.size:
        raise error("incomplete", "Not all of the file has arrived.", 409, received=upload.received, size=upload.size)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        head = handle.read(filetypes.HEAD)
        digest.update(head)
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != upload.sha256:
        _discard(db, upload)
        raise error("checksum_mismatch", "The file that arrived is not the one that was announced. The upload was "
                    "thrown away.", 422)
    try:
        found = filetypes.sniff(head)
    except filetypes.NotAccepted as exc:
        _discard(db, upload)
        raise error(exc.reason, exc.text, 415) from exc
    # Staged in the document folder before the write lock is taken (across disks that is a copy, which takes time); the
    # part file stays until the document exists, so a failure leaves the upload whole.
    staged = storage.incoming_path("up-")
    try:
        try:
            os.link(path, staged)
        except OSError:
            shutil.copyfile(path, staged)
        if upload.target_document_id is not None:
            from . import pagetools

            pagetools.accept_version(db, uid, upload.target_document_id, path=staged, kind=found.kind,
                                     sha256=upload.sha256, size=upload.size)
            path.unlink(missing_ok=True)
            db.execute(update(Upload).where(Upload.id == upload.id).values(state=DONE,
                                                                           document_id=upload.target_document_id))
            db.commit()
            target = db.get(Document, upload.target_document_id)
            if target is None:
                raise error("not_found", "Not found.", 404)
            return target, None, True
        document, twin = receiving.accept(
            db, uid=uid, vault_id=upload.vault_id, filename=upload.filename, path=staged, kind=found.kind,
            sha256=upload.sha256, size=upload.size, source=upload.source)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    path.unlink(missing_ok=True)
    db.execute(update(Upload).where(Upload.id == upload.id).values(state=DONE, document_id=document.id))
    db.commit()
    logger.info("Upload finished document_id=%s bytes=%s", document.id, upload.size)
    return document, twin, True


def abort(db: Session, uid: int, upload_id: str) -> None:
    upload = _mine(db, uid, upload_id)
    if upload.state == FINISHING:
        raise error("upload_busy", "This upload is being finished.", 409)
    with _writing_lock:
        if upload.id in _writing:
            raise error("upload_busy", "A piece of this upload is being received.", 409)
    _remove(db, upload)


# --- Housekeeping -----------------------------------------------------------------------------------------------------


def sweep(db: Session) -> int:
    """Uploads that ran out go (record and file); finished ones are forgotten a day after they ended; a part file with
    no
    record goes after a day. Returns how many records went."""
    now = clock.now()
    gone = 0
    for upload in list(db.scalars(select(Upload).where(Upload.expires_at <= now, Upload.state != FINISHING))):
        part_path(upload.id).unlink(missing_ok=True)
        db.execute(delete(Upload).where(Upload.id == upload.id))
        gone += 1
    db.commit()
    known = set(db.scalars(select(Upload.id)))
    directory = folder()
    if directory.is_dir():
        for entry in directory.iterdir():
            if entry.suffix == ".part" and entry.stem not in known:
                try:
                    old = now.timestamp() - entry.stat().st_mtime > limits.UPLOAD_HOURS * 3600
                except OSError:
                    continue
                if old:
                    entry.unlink(missing_ok=True)
    if gone:
        logger.info("Uploads that ran out removed count=%s", gone)
    return gone


def recover(db: Session) -> None:
    """At start: an upload that was being finished when the server stopped receives again (its file is still whole)."""
    db.execute(update(Upload).where(Upload.state == FINISHING).values(state=OPEN))
    db.commit()


def open_bytes(db: Session, uid: int) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(Upload.size), 0)).where(Upload.user_id == uid,
                                                                             Upload.state == OPEN)) or 0)

