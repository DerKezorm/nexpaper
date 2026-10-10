"""Setting a new password by a link.

The operator cannot set a password for anybody. Instead a person gets a link and sets their own: sent by the
operator ("Send a link to reset"), or asked for by the person on the sign-in page ("Forgot your password?") where a
mail server is set up and the account has an address.

* The link holds a random token. Only its SHA-256 is stored; it works once and runs out after 24 hours; at most one
  link is open per account, a new one replaces the one before.
* A link made for somebody else's request goes only to the address on record, and is built from the public address
  the operator set, never from the ``Host`` header a request brings.
* Using it sets the password, ends every session and every sign-in waiting for its second factor, and lifts a lock.
  The second factor stays: only the operator can take it (the reset of the second factor, its own act).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..models import SIGN_IN_PASSWORD, Account, PasswordReset, utcnow
from ..security import brake, end_all_sessions, hash_password, hash_token
from . import mailer, settings_service, totp

logger = logging.getLogger("nexpaper.auth")

#: How long a link holds.
HOURS = 24
#: Links one address may ask for, and one account may be sent, before they wait (the brake rests a quarter of an hour
#: after the last one; counts are forgotten after an hour).
PER_ADDRESS = 8
PER_ACCOUNT = 3
#: Accounts that share one mail address and are all reached by it.
PER_MAIL = 5


def available(db: Session) -> bool:
    """"Forgot your password?" is offered: mail works, the public address is known (the link comes from nothing
    else) and signing in with a password is on."""
    return bool(
        mailer.configured(db) and settings_service.public_url(db) and settings_service.get(db, "password_login")
    )


def make(db: Session, account: Account, by: Account | None = None) -> tuple[PasswordReset, str]:
    """A new link for the account, the one before gone. The token is returned once, never stored."""
    token = secrets.token_urlsafe(32)
    db.execute(delete(PasswordReset).where(PasswordReset.account_id == account.id))
    row = PasswordReset(
        account_id=account.id, token_hash=hash_token(token), created_by=by.id if by else None,
        expires_at=utcnow() + timedelta(hours=HOURS),
    )
    db.add(row)
    db.commit()
    logger.info("Password link made name=%s by=%s", account.name, by.name if by else "the person")
    return row, token


def link_to(db: Session, token: str) -> str:
    """The address of the page that takes the new password; empty without a public address."""
    base = settings_service.public_url(db)
    return f"{base}/reset/{token}" if base else ""


def find(db: Session, token: str) -> tuple[PasswordReset, Account] | None:
    """A usable link and its account: known, not run out, the account there and not blocked."""
    row = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == hash_token(token)))
    if row is None or row.expires_at <= utcnow():
        return None
    account = db.get(Account, row.account_id)
    if account is None or account.blocked_at is not None:
        return None
    return row, account


def accounts_for(db: Session, who: str) -> list[Account]:
    """The accounts a person who asks for a link means: by name, or by the mail address on record. Only accounts that
    sign in with a password, are not blocked and have an address to send to."""
    typed = who.strip().lower()[:255]
    if not typed:
        return []
    found = list(db.scalars(select(Account).where(Account.name == typed)))
    if "@" in typed:
        found += [row for row in db.scalars(select(Account).where(Account.email != ""))
                  if row.email.strip().lower() == typed and row not in found]
    return [row for row in found if row.sign_in == SIGN_IN_PASSWORD and row.blocked_at is None
            and row.email.strip()][:PER_MAIL]


def key_of(who: str) -> str:
    """What the brake counts a request for a link by: a short hash of what was typed, so that a name that does not
    exist is held back exactly like one that does."""
    return hashlib.sha256(who.strip().lower().encode("utf-8")).hexdigest()[:24]


def use(db: Session, token: str, password: str) -> Account | None:
    """Sets the password the link is for; None when the link does not hold. The link is taken away in the same
    transaction that writes the password: of two requests with one link at the same moment exactly one sets it."""
    found = find(db, token)
    if found is None:
        return None
    row, account = found
    sealed = hash_password(password)
    try:
        taken = int(db.execute(delete(PasswordReset).where(PasswordReset.id == row.id)).rowcount or 0) == 1
    except OperationalError:
        db.rollback()
        return None
    if not taken:
        db.rollback()
        return None
    account.password_hash = sealed
    account.sign_in = SIGN_IN_PASSWORD
    account.failed_logins = 0
    account.locked_until = None
    db.execute(delete(PasswordReset).where(PasswordReset.account_id == account.id))
    db.commit()
    end_all_sessions(db, account.id)
    totp.forget_account(account.id)
    logger.warning("Password set through a link name=%s", account.name)
    return account


def issue_and_send(account_ids: list[int]) -> None:
    """For people who asked for a link themselves, in the background (``notices.later``): the link is made and mailed
    to the address on record, an account at most ``PER_ACCOUNT`` times in a while, whoever asks and however. The request
    that asked has answered by then, the same for every name."""
    from ..db import SessionLocal

    for account_id in account_ids:
        key = f"forgot-account:{account_id}"
        with SessionLocal() as db:
            account = db.get(Account, account_id)
            if account is None or not account.email.strip():
                continue
            if brake.claim(key, PER_ACCOUNT):
                logger.warning("Password link left out, too many for this account name=%s", account.name)
                continue
            _row, token = make(db, account)
            link = link_to(db, token)
            if not link:
                continue
            try:
                mailer.send_reset(db, account.email.strip(), link, name=account.name, hours=HOURS)
            except mailer.MailError:
                logger.warning("Password link not mailed name=%s", account.name)
                continue
            logger.info("Password link mailed name=%s", account.name)
