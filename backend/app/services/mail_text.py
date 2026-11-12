"""The text of a mail as a document: for mails that bring nothing nexpaper takes (an order confirmation forwarded, a
booking, a note to oneself), when the operator switched it on (Settings, Inputs, Mailbox; off from the start).

* **Whose.** Only a mail that belongs to a person for sure: it comes from an address the person confirmed, or it is
  sent to their plus address (``intake_mail.assign``), and the mailbox's own server did not say that DMARC failed
  (``intake_mail.failed_check``). A mail that goes to the operator as unknown never gives a document of its text, and
  a mail with a part that is taken stays as it was (its text is not taken).
* **What.** The plain text of the mail; from HTML only the text, read from its markup by the mail worker in its own
  process with its limits (``app/mail_worker.py``, ``op: text``): nothing is drawn or fetched. At most 200 KB of it,
  set as a plain PDF with a head (``app/mail_sheet.py``). Less than 20 signs is no document.
* **The document.** Comes into the person's inbox like any other piece of the mailbox: source ``mail``, its title the
  subject (without "Fwd:", "WG:" and the like), its date the mail's. Its text is the mail's text, kept when it is made:
  the reading of the document takes it instead of recognising the PDF again (``install``).
* **Once.** Noted like a part of the mail (``<box>:<uidvalidity>:<uid>:text``), and known again by the Message-ID and
  the checksum of the PDF when the same mail comes a second time.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date as Date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..db import SessionLocal
from ..models import Account, Document, IntakeItem, Version, VersionText
from . import filetypes, intake, search_index, storage

logger = logging.getLogger("nexpaper.intake")

#: The last part of the key a mail's text is noted with (a part of a mail has its number there).
PART = "text"
#: The text a document is made of, at most (UTF-8 bytes).
TEXT_MAX = 200 * 1024
#: What the worker's list of page texts may hold at most (bytes): the text and the head, as UTF-8, and JSON's escapes.
TEXTS_MAX = TEXT_MAX * 6 + 64 * 1024
#: "Fwd:", "WG:", "AW:" and their kin at the start of a subject, also several and with a number ("AW[2]:").
_PREFIX = re.compile(r"^\s*(?:(?:fwd?|wg|aw|re|antw|tr|wtr)\s*(?:\[\d{1,3}\])?\s*:\s*)+", re.IGNORECASE)


def wanted(text_on: bool, *, takeable: int, unknown: bool) -> bool:
    """Whether the text of a mail becomes a document: switched on, nothing in the mail is taken (also nothing that was
    over a limit), and it belongs to a person for sure."""
    return text_on and takeable == 0 and not unknown


def title_of(subject: str, language: str) -> str:
    from ..mail_sheet import words_of

    title = _PREFIX.sub("", subject).strip()
    return title[:200] or words_of(language)["no_subject"]


def language_of(db: Session, uid: int) -> str:
    owner = db.get(Account, uid)
    return "en" if owner is not None and (owner.language or "").lower().startswith("en") else "de"


@dataclass
class Made:
    """What the mail worker made of a mail's text: the PDF and the text of its pages, or why not."""

    error: str = ""
    empty: bool = False
    pdf: Path | None = None
    texts: list[str] = field(default_factory=list)
    subject: str = ""
    day: Date | None = None
    cut: bool = False


def read(raw: bytes, folder: Path, language: str) -> Made:
    """The mail's text read and set as a PDF by the mail worker, in its own process with its limits."""
    from . import intake_mail

    answer = intake_mail._work(raw, folder, {"op": "text", "language": language, "text_max": TEXT_MAX,
                                             "nesting": intake_mail.MAX_NESTING,
                                             "parts_limit": intake_mail.MAX_PARTS})
    if answer is None:
        return Made(error="too_elaborate")
    if not answer.get("ok"):
        return Made(error=str(answer.get("error") or "unreadable"))
    if answer.get("empty"):
        return Made(empty=True)
    pdf, texts = Path(str(answer.get("pdf") or "")), Path(str(answer.get("texts") or ""))
    if pdf.parent != folder or texts.parent != folder or not pdf.is_file() or not texts.is_file():
        return Made(error="unreadable")
    try:
        with texts.open("rb") as handle:
            pages = json.loads(handle.read(TEXTS_MAX).decode("utf-8"))
    except (OSError, ValueError):
        return Made(error="unreadable")
    if not isinstance(pages, list) or not pages or not all(isinstance(page, str) for page in pages):
        return Made(error="unreadable")
    day: Date | None = None
    try:
        day = Date.fromisoformat(str(answer.get("day") or ""))
    except ValueError:
        day = None
    from .documents import DATE_MAX, DATE_MIN

    if day is not None and not DATE_MIN <= day <= DATE_MAX:
        day = None
    return Made(pdf=pdf, texts=[page.replace("\f", "\n") for page in pages], subject=str(answer.get("subject") or ""),
                day=day, cut=bool(answer.get("cut")))


def take(taken: Any, raw: bytes, folder: Path, *, key: str, owner: int, marker: str, sender: str, subject: str,
         budget: Callable[[int, int], bool] | None) -> None:
    """The text of the mail becomes a document of ``owner`` (``taken`` is the mailbox's ``Taken`` of this mail)."""
    from . import intake_mail

    with SessionLocal() as db:
        language = language_of(db, owner)
    made = read(raw, folder, language)
    if made.error:
        taken.error = made.error
        return
    if made.empty or made.pdf is None:
        logger.info("Mailbox: a mail with nothing to take had no text for a document")
        return
    taken.takeable = 1
    taken.text = True
    size = made.pdf.stat().st_size
    if budget is not None and not budget(owner, size):
        taken.deferred = True
        return
    sha256 = intake_mail._sha256(made.pdf)
    with SessionLocal() as db:
        known = db.scalar(select(IntakeItem.id).where(IntakeItem.source == intake.MAIL, IntakeItem.key == key))
        if known is None and marker:
            known = db.scalar(select(IntakeItem.id).where(IntakeItem.source == intake.MAIL,
                                                          IntakeItem.message == marker, IntakeItem.sha256 == sha256))
        if known is not None:
            taken.known += 1
            return
        title = title_of(made.subject or subject, language)
        body = "\f".join(made.texts)

        def keep(session: Session, document: Document) -> None:
            session.flush()
            version = session.scalar(select(Version).where(Version.document_id == document.id, Version.n == 1))
            if version is None:
                raise RuntimeError("version")
            session.add(VersionText(version_id=version.id, document_id=document.id, text=body, pages=len(made.texts),
                                    ocr_pages=0, languages="", digest=search_index.text_digest(body),
                                    created_at=clock.now()))
            if made.day is not None:
                # The date of the mail is the document's; a date in its text does not take its place.
                from .sorting import PERSON

                document.date = made.day
                document.suggest = {"date": PERSON}

        temporary = storage.incoming_path("mail-")
        try:
            shutil.move(str(made.pdf), str(temporary))
            intake.take(
                db, uid=owner, path=temporary, filename="mail.pdf", kind=filetypes.PDF, sha256=sha256, size=size,
                source=intake.MAIL, title=title,
                item={"key": key, "state": intake.DONE, "sha256": sha256, "size": size, "message": marker,
                      "unknown": False, "detail": {"from": sender[:255], "subject": subject, "file": "", "text": True}},
                detail={"mail_text": True}, more=keep,
            )
        except Exception as exc:  # noqa: BLE001 - the mail is tried again in the next run
            temporary.unlink(missing_ok=True)
            logger.warning("Mailbox: the text of a mail could not be taken error=%s", type(exc).__name__)
            taken.failed += 1
            return
    taken.files += 1
    taken.bytes += size


# --- Reading the document: its text is there already ------------------------------------------------------------------


def is_mail_text(db: Session, document: Document) -> bool:
    item = intake.origin(db, document.id)
    return item is not None and item.source == intake.MAIL and isinstance(item.detail, dict) \
        and item.detail.get("text") is True


def given(db: Session, document: Document, version: Version) -> list[str] | None:
    """The text of the pages of a document made of a mail's text (its first version, as it was made), else None."""
    if version.n != 1 or version.note != intake.MAIL or not is_mail_text(db, document):
        return None
    row = db.get(VersionText, version.id)
    if row is None:
        return None
    return row.text.split("\f") if row.text else [""]


def install() -> None:
    """The reading of a document (``processing.STEPS``) takes the kept text of a mail's text instead of recognising its
    PDF, and does not look for blank separator pages in it (a page of a mail is never one). The steps are wrapped once,
    found by their names; any other document is read as before."""
    from . import processing, separators

    def recognize_or_given(step: Callable[..., Any]) -> Callable[..., Any]:
        def run(db: Session, document: Document, version: Version, work: Any) -> Any:
            texts = given(db, document, version)
            if texts is None:
                return step(db, document, version, work)
            db.rollback()
            return processing.Outcome(True, data={"texts": texts, "ocr_pages": 0, "languages": "",
                                                  "searchable": False})

        run.mail_text = True  # type: ignore[attr-defined]
        run.__name__ = step.__name__
        return run

    def blanks_or_none(step: Callable[..., Any]) -> Callable[..., Any]:
        def run(db: Session, document: Document, version: Version, work: Any) -> Any:
            if given(db, document, version) is not None:
                db.rollback()
                return processing.Outcome(True)
            return step(db, document, version, work)

        run.mail_text = True  # type: ignore[attr-defined]
        run.__name__ = step.__name__
        return run

    wrappers = {processing.recognize_text: recognize_or_given, separators.find_blanks: blanks_or_none}
    for index, step in enumerate(processing.STEPS):
        if getattr(step, "mail_text", False):
            continue
        if step in wrappers:
            processing.STEPS[index] = wrappers[step](step)


def installed() -> bool:
    from . import processing

    return sum(1 for step in processing.STEPS if getattr(step, "mail_text", False)) == 2


install()
