"""The mails of the shared account module, through the shared post module: the account module says what to send
(``nexkonten.Mail``), this builds the link from the public address and the token, writes the letter
(``nexpost.letters``) in the language of the account, else the first operator's, else English, and sends it.

Two ways out, as in 1.12.0 for what somebody waits for:

- ``send_now``: at once, through ``mailer.send_letter`` (the link for a new address, a link for a new password, the
  invitation). A server that does not take it leaves the letter in the outbox for another try
  (``services/post_store.py``), unless the caller wants to hear it failed (``keep=False``).
- ``queue``: into the outbox (a new sign-in, a new username, a changed address, a reset second factor), sent within a
  minute by the worker.
"""

from __future__ import annotations

import logging
from datetime import tzinfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import OPERATOR, Account
from ..vendor import nexkonten, nexpost
from . import mailer, settings_service
from .post_store import PostStore

logger = logging.getLogger("nexpaper.mail")

#: Where each link leads in the interface, as in 1.12.0 (``/reset/<token>``, ``/mail/<token>``).
PAGES = {
    nexkonten.MAIL_RESET: "/reset/",
    nexkonten.MAIL_CONFIRM_EMAIL: "/mail/",
}


def link_for(db: Session, mail: nexkonten.Mail, base: str = "") -> str:
    page = PAGES.get(mail.kind)
    if not page or not mail.token:
        return ""
    return f"{base or settings_service.public_url(db)}{page}{mail.token}"


def can_mail(db: Session) -> bool:
    """A mail server and the public address (a link in a mail never points anywhere a request made up)."""
    return mailer.configured(db) and bool(settings_service.public_url(db))


def account_named(db: Session, name: str) -> Account | None:
    return db.scalar(select(Account).where(func.lower(Account.name) == (name or "").strip().lower()))


def language_for(db: Session, account: Account | None) -> str:
    """The language of a mail to ``account``: its own, else the first operator's, else English (the post module has
    German, English and French)."""
    choices: list[str] = []
    if account is not None:
        choices.append(account.language)
    first = db.scalar(select(Account).where(Account.role == OPERATOR).order_by(Account.id).limit(1))
    if first is not None:
        choices.append(first.language)
    for choice in choices:
        short = (choice or "").strip().lower()[:2]
        if short in nexpost.letters.LANGUAGES:
            return short
    return "en"


def letter_of(db: Session, mail: nexkonten.Mail, *, by: str = "", where: str = "", days: int = 0,
              base: str = "", link: str = "", time_zone: tzinfo | None = None) -> nexpost.Letter:
    """The letter of a mail of the account module; ``ValueError``/``MailError`` for an address it refuses. ``link``:
    a page of nexpaper the letter points to where the mail has no link of its own (the notice of a new sign-in);
    ``time_zone`` the person's, for the moment of a new sign-in."""
    account = db.get(Account, int(mail.account_id)) if str(mail.account_id).isdigit() else None
    return nexpost.letters.from_account_mail(mail, language=language_for(db, account),
                                             link=link_for(db, mail, base) or link, by=by, where=where, days=days,
                                             time_zone=time_zone)


def queue(db: Session, mail: nexkonten.Mail | None, *, by: str = "", where: str = "", days: int = 0) -> bool:
    """Into the outbox (committed here); False when nothing went in (no mail, no server, an address the post module
    refuses)."""
    if mail is None:
        return False
    if not mailer.configured(db):
        # Said in the log, not in silence (without the address).
        logger.info("Mail not queued kind=%s reason=no mail server", mail.kind)
        return False
    try:
        letter = letter_of(db, mail, by=by, where=where, days=days)
    except (nexpost.MailError, ValueError) as exc:
        logger.warning("Mail not queued kind=%s reason=%s", mail.kind, type(exc).__name__)
        return False
    nexpost.outbox.queue(PostStore(db), letter)
    db.commit()
    return True


def send_now(db: Session, mail: nexkonten.Mail | None, *, days: int = 0, keep: bool = True, base: str = "") -> bool:
    """At once through the mail server. ``keep``: a mail the server did not take waits in the outbox for another
    try (True: it counts as on its way). ``keep=False``: ``mailer.MailError`` for the caller. False when there is
    nothing to send or no server. ``base``: the address the link points to when there is no public one (the
    operator's own page)."""
    if mail is None or not mailer.configured(db):
        return False
    try:
        letter = letter_of(db, mail, days=days, base=base)
    except (nexpost.MailError, ValueError) as exc:
        logger.warning("Mail not sent kind=%s reason=%s", mail.kind, type(exc).__name__)
        if keep:
            return False
        raise mailer.MailError("invalid_email", "This is not a mail address.") from exc
    try:
        mailer.send_letter(db, letter)
    except mailer.MailError:
        if not keep:
            raise
        nexpost.outbox.queue(PostStore(db), letter)
        db.commit()
        logger.info("Mail waits in the outbox kind=%s", mail.kind)
    return True
