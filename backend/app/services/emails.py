"""The mail address of an account, changed only by a link sent to the new address.

The address is where "Forgot your password?" and the notice of a new sign-in go, so it is the way back into an account:
whoever can change it can take the account. A change therefore asks for the password once more (``routers/emails.py``),
and the new address counts only after somebody opened the link that was mailed to it.

* The link holds a random token. Only its SHA-256 is stored; it works once and runs out after 24 hours; at most one is
  open per account, a new one replaces the one before. Until it is used the old address stays as it was.
* The link is built from the public address the operator set, never from the ``Host`` header a request brings.
* Taking it is atomic: of two requests with one link exactly one writes the address.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..models import Account, EmailConfirmation, utcnow
from ..security import hash_token
from . import mailer, notices, settings_service

logger = logging.getLogger("nexpaper.auth")

#: How long a link holds.
HOURS = 24
#: Mails one account may ask for in a while before it waits.
PER_ACCOUNT = 5


def available(db: Session) -> bool:
    """A link can be sent: a mail server is set up and the public address is known (the link comes from nothing
    else)."""
    return bool(mailer.configured(db) and settings_service.public_url(db))


def pending_of(db: Session, account_id: int) -> str:
    """The address waiting for its link, if one is open and has not run out; else empty."""
    row = db.scalar(select(EmailConfirmation).where(EmailConfirmation.account_id == account_id))
    return row.address if row is not None and row.expires_at > utcnow() else ""


def start(db: Session, account: Account, address: str) -> tuple[EmailConfirmation, str]:
    """A new link for the address, the one before gone. The token is returned once, never stored."""
    token = secrets.token_urlsafe(32)
    db.execute(delete(EmailConfirmation).where(EmailConfirmation.account_id == account.id))
    row = EmailConfirmation(account_id=account.id, address=address, token_hash=hash_token(token),
                            expires_at=utcnow() + timedelta(hours=HOURS))
    db.add(row)
    db.commit()
    logger.info("Mail address link made name=%s", account.name)
    return row, token


def link_to(db: Session, token: str) -> str:
    """The address of the page that confirms; empty without a public address."""
    base = settings_service.public_url(db)
    return f"{base}/mail/{token}" if base else ""


def withdraw(db: Session, account_id: int) -> bool:
    gone = db.execute(delete(EmailConfirmation).where(EmailConfirmation.account_id == account_id))
    db.commit()
    return bool(gone.rowcount)  # type: ignore[attr-defined]


def find(db: Session, token: str) -> tuple[EmailConfirmation, Account] | None:
    """A usable link and its account: known, not run out, the account there and not blocked."""
    row = db.scalar(select(EmailConfirmation).where(EmailConfirmation.token_hash == hash_token(token)))
    if row is None or row.expires_at <= utcnow():
        return None
    account = db.get(Account, row.account_id)
    if account is None or account.blocked_at is not None:
        return None
    return row, account


def _hint(address: str) -> str:
    """An address as far as a stranger may read it: the first letter and the domain."""
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}"


def _tell_old(old: str, name: str, new: str) -> None:
    from ..db import SessionLocal

    with SessionLocal() as db:
        try:
            if new:
                mailer.send_changed(db, old, name=name, new_hint=_hint(new))
            else:
                mailer.send_removed(db, old, name=name)
        except mailer.MailError:
            logger.warning("The old address was not told of the change name=%s", name)
            return
    logger.info("The old address was told of the change name=%s", name)


def notify_old(db: Session, old: str, name: str, new: str) -> bool:
    """Tells a confirmed old address that the address of the account changed (``new`` empty: was taken away), in the
    background, through the mail server of the operator. Without one nothing can be sent: that is said in the log, not
    in silence (without the addresses). Whether it is being sent."""
    if not mailer.configured(db):
        logger.info("The old address was not told: no mail server is set up name=%s", name)
        return False
    notices.later(_tell_old, old, name, new)
    return True


def confirm(db: Session, token: str) -> tuple[Account, bool] | None:
    """Writes the address the link is for; None when the link does not hold. The link is taken away in the same
    transaction that writes the address. Gives the account and whether the old address (one that was confirmed) is
    being told: through the same mail server, in the background."""
    found = find(db, token)
    if found is None:
        return None
    row, account = found
    address = row.address
    try:
        taken = int(db.execute(delete(EmailConfirmation).where(EmailConfirmation.id == row.id)).rowcount or 0) == 1
    except OperationalError:
        db.rollback()
        return None
    if not taken:
        db.rollback()
        return None
    old = account.email.strip()
    was_confirmed = bool(old) and account.email_confirmed_at is not None and old.lower() != address.lower()
    account.email = address
    account.email_confirmed_at = utcnow()
    account.email_from_provider = False
    db.commit()
    logger.info("Mail address confirmed name=%s", account.name)
    return account, was_confirmed and notify_old(db, old, account.name, address)
