"""The addresses a person forwards documents from to the mailbox (My account, Upload, "Per Mail").

An address counts only once the link mailed to it was opened, as with the address of the account: otherwise anybody
could name somebody else's address and have their mail land in the own inbox. The link holds a random token of which
only the SHA-256 is kept; it works once and for 24 hours. The confirmed address of the account counts as well.

Whoever sends a mail can write any address into ``From``: the address tells who a mail is probably from, not who it is
from. That is why nothing from the mailbox is filed by itself; it waits in the inbox (``SECURITY.md``).
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .. import clock
from ..models import Account, MailSender
from ..security import hash_token
from . import emails, settings_service

logger = logging.getLogger("nexpaper.intake")

HOURS = 24
#: Addresses one account may have, confirmed or waiting.
MAX_PER_ACCOUNT = 20
#: Links one account may ask for in a while.
PER_ACCOUNT = 5


def key_of(address: str) -> str:
    return address.strip().casefold()


def of_account(db: Session, account_id: int) -> list[MailSender]:
    """The person's addresses; one whose link ran out unopened is not among them (and goes)."""
    now = clock.now()
    db.execute(delete(MailSender).where(MailSender.user_id == account_id, MailSender.confirmed_at.is_(None),
                                        MailSender.expires_at < now))
    db.commit()
    return list(db.scalars(select(MailSender).where(MailSender.user_id == account_id).order_by(MailSender.id)))


def count(db: Session, account_id: int) -> int:
    return int(db.scalar(select(func.count()).select_from(MailSender).where(MailSender.user_id == account_id)) or 0)


def start(db: Session, account: Account, address: str) -> tuple[MailSender, str]:
    """A link for the address (a new one replaces a waiting one of the same address). The token is returned once."""
    token = secrets.token_urlsafe(32)
    key = key_of(address)
    row = db.scalar(select(MailSender).where(MailSender.user_id == account.id, MailSender.address_key == key))
    if row is None:
        row = MailSender(user_id=account.id, address=address.strip(), address_key=key, created_at=clock.now())
        db.add(row)
    row.token_hash = hash_token(token)
    row.expires_at = clock.now() + timedelta(hours=HOURS)
    db.commit()
    logger.info("Sender address link made name=%s", account.name)
    return row, token


def link_to(db: Session, token: str) -> str:
    base = settings_service.public_url(db)
    return f"{base}/absender/{token}" if base else ""


def available(db: Session) -> bool:
    return emails.available(db)


def find(db: Session, token: str) -> tuple[MailSender, Account] | None:
    row = db.scalar(select(MailSender).where(MailSender.token_hash == hash_token(token)))
    if row is None or row.confirmed_at is not None or row.expires_at is None or row.expires_at <= clock.now():
        return None
    account = db.get(Account, row.user_id)
    if account is None or account.blocked_at is not None:
        return None
    return row, account


def confirm(db: Session, token: str) -> tuple[MailSender, Account] | None:
    """The address counts from now on; the link is used up in the same write (of two presses exactly one counts)."""
    found = find(db, token)
    if found is None:
        return None
    row, account = found
    done = db.execute(update(MailSender).where(MailSender.id == row.id, MailSender.confirmed_at.is_(None),
                                               MailSender.token_hash == row.token_hash)
                      .values(confirmed_at=clock.now(), token_hash="", expires_at=None))
    if int(done.rowcount or 0) != 1:  # type: ignore[attr-defined]
        db.rollback()
        return None
    db.commit()
    db.refresh(row)
    logger.info("Sender address confirmed name=%s", account.name)
    return row, account


def owners(db: Session, address: str) -> set[int]:
    """The accounts (not blocked) for which this address counts: a confirmed sender address, or the confirmed address
    of the account."""
    key = key_of(address)
    if not key:
        return set()
    found = set(db.scalars(select(MailSender.user_id).join(Account, Account.id == MailSender.user_id)
                           .where(MailSender.address_key == key, MailSender.confirmed_at.is_not(None),
                                  Account.blocked_at.is_(None))))
    for account_id, email in db.execute(select(Account.id, Account.email).where(
            Account.email_confirmed_at.is_not(None), Account.blocked_at.is_(None), Account.email != "")):
        if key_of(email) == key:
            found.add(int(account_id))
    return found
