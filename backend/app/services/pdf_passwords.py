"""Protected PDFs (P1): opening one with a password a person types, and the passwords a person keeps.

**Opening.** A PDF that needs a password waits in the inbox with ``process_error`` ``encrypted``. A person who may
change it (``edit``) types the password: the worker (``app/worker.py``, ``unlock``) opens the original with it, right in
the request and within the worker's time limit, and writes the PDF without its encryption beside the original. That copy
becomes the version's searchable copy at once; the document is then read like any other (the job ``process``), from the
copy. The original stays as it came, with its checksum; the version is marked (``original_protected``).

The password goes the shortest way: in the body of the request, into the worker on its standard input (never as an
argument, never in its environment, never in a file), and nowhere else. It is never written to the table of jobs: the
run is made in the request, so there is nothing to hand over to a job. A wrong password leaves the document as it was;
every try counts against a brake (``TRIES_PER_DOCUMENT`` per document and hour, ``TRIES_PER_PERSON`` per person and
hour).

**Kept passwords.** Only when the person ticks "keep it for future documents", under a name of their own, at most
``MAX``. Sealed with the server's secret (``security.encrypt_secret``, bound to the person: a row moved to somebody else
does not open), never shown again, only renamed and deleted. When a protected PDF comes into the inbox of its owner (any
way: browser, phone, the folder, the mailbox, the import) and the first run of the worker says it needs a password, the
worker runs a second time with the owner's passwords, unsealed for that run only; never with anybody else's. The history
then says it was opened with a kept password, never which. A new ``secret.key`` makes them unreadable: they are lost,
and the list says so (as for the mailbox's password).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import error
from ..models import EDIT, INBOX, PROCESSING, Document, PdfPassword, Version
from ..security import decrypt_secret, encrypt_secret
from . import brakes, changes, jobs, limits, rights, storage

logger = logging.getLogger("nexpaper.pdf_passwords")

#: The most passwords a person keeps.
MAX = 10
NAME_MAX = 60
#: The longest password taken, in characters (the newest PDF encryption reads 127 bytes, the older ones 32).
PASSWORD_MAX = 512
#: Tries to open one document per hour, and tries of one person per hour (every try runs the worker).
TRIES_PER_DOCUMENT = 5
TRIES_PER_PERSON = 20
#: What ``versions.original_protected`` holds.
PASSWORD, RESTRICTED = "password", "restricted"
#: The line in the history: who opened it (a person typed it, or a kept password of the owner did).
OPENED = "pdf_opened"


def _context(user_id: int) -> str:
    return f"pdf-password:{int(user_id)}"


def clean_name(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise error("invalid_pdf_password_name", "A name cannot hold control characters.", 422)
    name = " ".join(value.split())
    if not name or len(name) > NAME_MAX:
        raise error("invalid_pdf_password_name", f"Use 1 to {NAME_MAX} characters.", 422, max=NAME_MAX)
    return name


def _check_password(value: str) -> None:
    if not value or len(value) > PASSWORD_MAX:
        raise error("invalid_pdf_password", f"Use 1 to {PASSWORD_MAX} characters.", 422, max=PASSWORD_MAX)
    if "\x00" in value:
        raise error("invalid_pdf_password", "A password cannot hold a zero character.", 422)


# --- The list ---------------------------------------------------------------------------------------------------------


@dataclass
class Listed:
    row: PdfPassword
    #: It can still be unsealed (the ``secret.key`` it was sealed with is the one now).
    readable: bool


def entries(db: Session, uid: int) -> list[PdfPassword]:
    return list(db.scalars(select(PdfPassword).where(PdfPassword.user_id == uid).order_by(PdfPassword.id)))


def listed(db: Session, uid: int) -> list[Listed]:
    """The caller's entries, each with whether it can still be used. The value is unsealed only to know that and
    dropped at once; it never leaves this function."""
    return [Listed(row, bool(decrypt_secret(row.sealed, _context(uid)))) for row in entries(db, uid)]


def _own(db: Session, uid: int, entry_id: int) -> PdfPassword:
    """The caller's entry; anybody else's answers like one that does not exist (the operator's too)."""
    row = db.get(PdfPassword, entry_id)
    if row is None or row.user_id != uid:
        raise error("not_found", "Not found.", 404)
    return row


def rename(db: Session, uid: int, entry_id: int, name: str) -> PdfPassword:
    name = clean_name(name)
    changes.write_lock(db)
    row = _own(db, uid, entry_id)
    row.name = name
    db.commit()
    return row


def delete(db: Session, uid: int, entry_id: int) -> None:
    changes.write_lock(db)
    row = _own(db, uid, entry_id)
    db.delete(row)
    db.commit()


def _keep(db: Session, uid: int, name: str, password: str) -> str:
    """Inside the caller's transaction, under the write lock: the password kept for ``uid`` under ``name``. ``known``
    when the person keeps it already (nothing new is made), ``kept`` else; ``409 too_many_pdf_passwords`` at ``MAX``."""
    have = entries(db, uid)
    for row in have:
        if decrypt_secret(row.sealed, _context(uid)) == password:
            return "known"
    if len(have) >= MAX:
        raise error("too_many_pdf_passwords", f"At most {MAX} kept passwords.", 409, max=MAX)
    db.add(PdfPassword(user_id=uid, name=name, sealed=encrypt_secret(password, _context(uid)), created_at=clock.now()))
    return "kept"


def for_owner(db: Session, owner_id: int | None) -> list[tuple[int, str]]:
    """The owner's kept passwords that can still be unsealed, oldest first, as (id, password): for one run of the
    worker, and for nothing else. Nobody else's are ever added."""
    if not owner_id:
        return []
    found = []
    for row in entries(db, owner_id):
        password = decrypt_secret(row.sealed, _context(owner_id))
        if password:
            found.append((row.id, password))
    return found


def matched(db: Session, entry_id: int, owner_id: int | None) -> None:
    """Inside the caller's transaction: the entry opened a PDF just now (only if it is still the owner's)."""
    row = db.get(PdfPassword, entry_id)
    if row is not None and row.user_id == owner_id:
        row.last_matched_at = clock.now()


# --- Opening a document with a typed password ------------------------------------------------------------------------


@dataclass
class Opened:
    document: Document
    #: ``kept``, ``known`` (the person keeps it already) or empty (not asked to keep it).
    kept: str


def _locked(document: Document) -> bool:
    return document.status == INBOX and document.process_error == "encrypted"


def open_with(db: Session, uid: int, document_id: int, password: str, *, keep: bool = False,
              name: str | None = None) -> Opened:
    """Opens the protected PDF of a document with ``password`` (the caller needs ``edit``). See the top of this file.
    ``409 not_protected`` when the document does not wait for a password; ``422 wrong_pdf_password`` when it does not
    open the PDF (the document stays as it was); ``429`` past the brake."""
    _check_password(password)
    kept_name = clean_name(name or "") if keep else ""
    access = rights.require_document(db, uid, document_id, EDIT)
    document = access.document
    if not _locked(document):
        raise error("not_protected", "This document does not wait for a password.", 409)
    if keep and len(entries(db, uid)) >= MAX:
        raise error("too_many_pdf_passwords", f"At most {MAX} kept passwords.", 409, max=MAX)
    version = db.scalar(select(Version).where(Version.document_id == document.id,
                                              Version.n == document.current_version))
    if version is None:
        raise error("not_found", "Not found.", 404)
    try:
        source = storage.safe_path(version.original_path)
    except storage.StorageError:
        raise error("not_found", "Not found.", 404) from None
    if not source.is_file():
        raise error("file_missing", "The file of this version is missing on the disk.", 409)
    # Only now, after every reason that is no try at all: one try more, for the document and for the person.
    brakes.take_hourly(("pdf_password_document", document.id, TRIES_PER_DOCUMENT),
                       ("pdf_password_person", uid, TRIES_PER_PERSON))
    version_id, version_n = version.id, version.n
    current = limits.current(db)
    db.rollback()  # no transaction stays open while the worker runs
    out = storage.incoming_path("open-")
    outcome = _run_unlock(source, password, out, current)
    try:
        if not outcome.ok:
            if outcome.error == "encrypted":
                logger.info("A PDF was not opened: wrong password document_id=%s", document_id)
                raise error("wrong_pdf_password", "This password does not open the PDF.", 422)
            logger.info("A PDF could not be opened document_id=%s error=%s", document_id, outcome.error)
            raise error("pdf_" + outcome.error if outcome.error in ("broken", "too_large") else "try_again",
                        "The PDF could not be opened this time.", 422 if outcome.error in ("broken", "too_large")
                        else 503)
        unlocked = outcome.data.get("unlocked")
        with storage.files_of([document_id], 30):
            return _settle(db, uid, document_id, version_id, version_n, out if unlocked is not None else None,
                           unlocked, password if keep else "", kept_name)
    except storage.DocumentBusy:
        raise error("busy", "The files of this document are being worked on. Try again in a moment.", 409) from None
    finally:
        out.unlink(missing_ok=True)


def _run_unlock(source: Path, password: str, out: Path, current: Any) -> Any:
    from . import processing

    passwords = [password]
    try:
        return processing.spawn({"op": "unlock", "source": str(source), "out": str(out), "passwords": passwords,
                                 "memory_mb": current.memory_mb}, max(30, int(current.timeout_seconds)))
    finally:
        passwords.clear()


def _settle(db: Session, uid: int, document_id: int, version_id: int, version_n: int, opened: Path | None,
            unlocked: int | None, keep_password: str, kept_name: str) -> Opened:
    """Under the write lock: the opened copy becomes the version's searchable copy, the document is read again from it,
    and the password is kept when asked. A document that changed meanwhile (opened by another try, read, deleted) is
    left alone: ``409 not_protected``."""
    changes.write_lock(db)
    access = rights.require_document(db, uid, document_id, EDIT)
    document = access.document
    version = db.get(Version, version_id)
    if not _locked(document) or version is None or version.n != version_n or document.current_version != version_n:
        db.rollback()
        raise error("not_protected", "This document does not wait for a password.", 409)
    if opened is not None and opened.is_file():
        old = version.archive_path
        target = storage.archive_target(db, document, version)
        version.archive_sha256 = storage.sha256_of(opened)
        storage.adopt(opened, target)
        version.archive_path = target
        version.original_protected = PASSWORD if unlocked else RESTRICTED
        if old and old != target:
            storage.remove_files([old])
    kept = ""
    if keep_password and unlocked:
        kept = _keep(db, uid, kept_name, keep_password)
    document.status = PROCESSING
    document.process_error = ""
    document.change_seq = changes.next_seq(db)
    changes.record(db, document.id, OPENED, user_id=uid, detail={"by": "typed"})
    jobs.enqueue(db, jobs.PROCESS, document.id)
    db.commit()
    logger.info("A protected PDF was opened document_id=%s kept=%s", document_id, bool(kept))
    return Opened(document, kept)


__all__ = ["MAX", "Opened", "delete", "entries", "for_owner", "listed", "matched", "open_with", "rename"]
