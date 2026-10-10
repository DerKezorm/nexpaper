"""Inputs: what the intake folder (``services/intake_folder.py``) and the mailbox (``services/intake_mail.py``) bring
in, and what both have in common.

* **Everything ends in ``receiving.accept``**, as an upload does: the file is checked for its kind and size, becomes a
  document of the person in the vault they chose for their uploads, waits in their inbox and is read by the worker.
  Nothing is filed by itself.
* **Never twice.** A row in ``intake_items`` is written in the same transaction as the document: a folder file stands
  ``taken`` until it is gone from the folder, a part of a mail is known by UIDVALIDITY, UID and its number. A restart
  in between finds the row and does not take the file again.
* **Where it came from** stays with the document (``origin``): the folder or the mail, and whether nobody could be
  told from it (``unknown``: it went to the operator).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import clock
from ..db import SessionLocal
from ..models import OPERATOR, Account, Document, IntakeItem
from . import receiving, settings_service

logger = logging.getLogger("nexpaper.intake")

FOLDER = "folder"
MAIL = "mail"
TAKEN = "taken"
DONE = "done"
#: Rows of the folder whose document is gone are kept this long, then forgotten.
KEEP_DAYS = 90
#: How often the folder is looked at, and the mailbox fetched.
FOLDER_SECONDS = 5.0
MAIL_SECONDS = 300.0


def operator_id(db: Session) -> int | None:
    """The operator who gets what nobody else can be told from: the first one that is not blocked."""
    found = db.scalar(select(Account.id).where(Account.role == OPERATOR, Account.blocked_at.is_(None))
                      .order_by(Account.id).limit(1))
    return int(found) if found is not None else None


def account_named(db: Session, name: str) -> Account | None:
    """The account of this name (as people sign in with it), if it may receive: not blocked."""
    cleaned = name.strip().casefold()
    if not cleaned:
        return None
    row = db.scalar(select(Account).where(Account.name == cleaned))
    if row is None or row.blocked_at is not None:
        return None
    return row


def take(
    db: Session, *, uid: int, path: Path, filename: str, kind: str, sha256: str, size: int, source: str,
    item: dict[str, Any], title: str | None = None,
) -> Document:
    """A complete file on the disk (``path``, moved away) becomes a document of ``uid`` in the vault they chose for
    their uploads, and ``item`` (the columns of an ``IntakeItem``) is written in the same transaction."""
    vault_id = receiving.resolve_vault(db, uid, None)

    def note(session: Session, document: Document) -> None:
        session.add(IntakeItem(document_id=document.id, source=source, at=clock.now(), **item))

    document, _twin = receiving.accept(
        db, uid=uid, vault_id=vault_id, filename=filename, path=path, kind=kind, sha256=sha256, size=size,
        source=source, title=title, also=note,
    )
    return document


def origin(db: Session, document_id: int) -> IntakeItem | None:
    return db.scalar(select(IntakeItem).where(IntakeItem.document_id == document_id).order_by(IntakeItem.id).limit(1))


def prune(db: Session) -> int:
    """Rows of the folder whose document is gone and that are long done."""
    cutoff = clock.now() - timedelta(days=KEEP_DAYS)
    result = db.execute(delete(IntakeItem).where(IntakeItem.source == FOLDER, IntakeItem.state == DONE,
                                                 IntakeItem.document_id.is_(None), IntakeItem.at < cutoff))
    db.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def switched_on(key: str) -> bool:
    with SessionLocal() as db:
        return bool(settings_service.get(db, key))


async def _every(stop: asyncio.Event, seconds: float, run: Callable[[], Any], label: str) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(run)
        except Exception:
            logger.exception("Intake run failed part=%s", label)
        try:
            await asyncio.wait_for(stop.wait(), seconds)
        except TimeoutError:
            continue


def _mail_round() -> None:
    from . import intake_mail

    if not switched_on("mail_on"):
        return
    try:
        intake_mail.fetch()
    except intake_mail.MailBusy:
        return
    except intake_mail.MailFailure:
        # Said in the log and kept as the last result for the settings; the next round tries again.
        return


#: Folder rounds between two prunings of old rows (about an hour).
PRUNE_ROUNDS = 720
_rounds = [0]


def _folder_round() -> None:
    from . import intake_folder

    intake_folder.scan()
    _rounds[0] += 1
    if _rounds[0] % PRUNE_ROUNDS == 1:
        with SessionLocal() as db:
            prune(db)


async def run_forever(stop: asyncio.Event) -> None:
    """The folder every few seconds, the mailbox every 5 minutes; each does nothing while it is switched off."""
    await asyncio.gather(
        _every(stop, FOLDER_SECONDS, _folder_round, "folder"),
        _every(stop, MAIL_SECONDS, _mail_round, "mail"),
    )
