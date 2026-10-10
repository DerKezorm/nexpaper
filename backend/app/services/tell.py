"""A message to a person in the background: a push to their devices and, with a mail server and a confirmed address, a
mail. The texts come in both languages and are chosen per device (push) and per account (mail); the message names
numbers and where to look, never the contents of a document.

Used for the notices that are about the whole server and not about one request: the check of the files found a
problem, the import from Paperless is done. (The notice of a ready export and of a new sign-in have their own words and
stay with their modules.)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from email.message import EmailMessage

from sqlalchemy import select

from ..models import OPERATOR, Account
from . import notices

logger = logging.getLogger("nexpaper.tell")


@dataclass(frozen=True)
class Notice:
    #: ``{"de": (title, body), "en": (title, body)}``.
    texts: dict[str, tuple[str, str]]
    #: A path of nexpaper that a tap opens.
    url: str
    #: The same tag replaces an earlier message on the device.
    tag: str
    #: The mail says it in English; ``{where}`` is the full address of the page (or its name without a public address).
    mail_subject: str
    mail_body: str


def operators() -> list[int]:
    from ..db import SessionLocal

    with SessionLocal() as db:
        return list(db.scalars(select(Account.id).where(Account.role == OPERATOR, Account.blocked_at.is_(None))))


def person(account_id: int, notice: Notice) -> None:
    """Tells one person, in the background."""
    notices.later(_send, account_id, notice)


def operator(notice: Notice) -> None:
    """Tells every operator, in the background."""
    for account_id in operators():
        person(account_id, notice)


def _send(account_id: int, notice: Notice) -> None:
    from ..db import SessionLocal
    from . import mailer, push, settings_service

    with SessionLocal() as db:
        account = db.get(Account, account_id)
        if account is None or account.blocked_at is not None:
            return
        language = notices.language_of(account.language)
        mail_to = account.email if account.email and account.email_confirmed_at and mailer.configured(db) else ""
        base = settings_service.public_url(db)

    def message_for(lang: str) -> push.Message:
        title, body = notice.texts[notices.language_of(lang or language)]
        return push.Message(title=title, body=body, url=notice.url, desk=notice.url, tag=notice.tag)

    push.send_to_person(account_id, message_for)
    if not mail_to:
        return
    message = EmailMessage()
    message["To"] = mail_to
    message["Subject"] = notice.mail_subject
    message.set_content(notice.mail_body.format(where=f"{base}{notice.url}" if base else "nexpaper"))
    with SessionLocal() as db:
        try:
            mailer.send_message(db, message)
        except mailer.MailError:
            logger.warning("A notice was not mailed tag=%s", notice.tag)
