"""Accounts: what is nexpaper's own beside the shared account module (``vendor/nexkonten``, store
``services/konten_store.py``), which runs the setup, signing in, invitations and the profile.

Here: counting accounts, the lock after wrong passwords where nexpaper checks a password itself (confirming an act,
the code step), changing the own password, and the invitations the operator makes (a link with an end date; whoever
follows it makes an account through the module).
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import timedelta
from functools import lru_cache

from sqlalchemy import delete, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .. import __version__, clock
from ..models import MEMBER, ROLES, SIGN_IN_PASSWORD, Account, Invite, utcnow
from ..security import LOCK_MINUTES, MAX_FAILURES, hash_password, hash_token, verify_password

logger = logging.getLogger("nexpaper.auth")

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
#: Enough to catch a typo, not a validation of the address: the mail server has the last word.
EMAIL_PATTERN = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")
#: How long an invitation may run, in days; the one who invites picks within this.
INVITE_DAYS = (1, 7, 30)


class AccountError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(Account)) or 0)


def by_name(db: Session, name: str) -> Account | None:
    return db.scalar(select(Account).where(func.lower(Account.name) == name.strip().lower()))


def create_with_password(db: Session, name: str, password: str, role: str = MEMBER, *, commit: bool = True) -> Account:
    if role not in ROLES:
        raise ValueError("unknown role")
    account = Account(
        name=name.strip().lower(),
        role=role,
        sign_in=SIGN_IN_PASSWORD,
        password_hash=hash_password(password),
        whats_new_seen=__version__,
    )
    db.add(account)
    if commit:
        db.commit()
    else:
        db.flush()
    logger.info("Account created name=%s role=%s sign_in=password", account.name, role)
    return account


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """A hash to verify against for an unknown name: the answer takes as long as for a wrong password."""
    return hash_password(secrets.token_urlsafe(24))


def is_locked(account: Account) -> bool:
    return account.locked_until is not None and account.locked_until > clock.now()


def note_failure(db: Session, account: Account) -> None:
    """A wrong password: counted per account, locked after too many, whoever the sender is."""
    account.failed_logins += 1
    if account.failed_logins >= MAX_FAILURES:
        account.locked_until = clock.now() + timedelta(minutes=LOCK_MINUTES)
        account.failed_logins = 0
        logger.warning("Account locked after %s failures name=%s minutes=%s", MAX_FAILURES, account.name, LOCK_MINUTES)
    else:
        logger.warning(
            "Check failed name=%s (%s of %s before lockout)", account.name, account.failed_logins, MAX_FAILURES
        )
    db.commit()


def note_success(db: Session, account: Account) -> None:
    account.failed_logins = 0
    account.locked_until = None
    account.last_seen_at = utcnow()
    db.commit()


def check_password(account: Account, password: str) -> bool:
    return account.sign_in == SIGN_IN_PASSWORD and verify_password(password, account.password_hash)


def change_password(db: Session, account: Account, current: str, new: str) -> None:
    if not verify_password(current, account.password_hash):
        raise AccountError("wrong_password", "The current password is wrong.", 401)
    account.password_hash = hash_password(new)
    db.commit()
    logger.info("Password changed name=%s", account.name)


# --- Invitations ---------------------------------------------------------------------------------------------------


def create_invite(
    db: Session, by: Account, *, days: int, email: str = "", display_name: str = "", mailed: bool = False,
) -> tuple[Invite, str]:
    if days not in INVITE_DAYS:
        raise AccountError("invalid_days", "Choose 1, 7 or 30 days.", 422)
    token = secrets.token_urlsafe(24)
    invite = Invite(
        token_hash=hash_token(token), email=email.strip()[:255], created_by=by.id,
        expires_at=utcnow() + timedelta(days=days), display_name=display_name[:80], mailed=mailed,
    )
    db.add(invite)
    db.commit()
    logger.info("Invite created by=%s days=%s", by.name, days)
    return invite, token


def expired(invite: Invite) -> bool:
    return invite.expires_at <= utcnow()


def find_invite(db: Session, token: str) -> Invite | None:
    """A usable invitation: known and not run out."""
    invite = db.scalar(select(Invite).where(Invite.token_hash == hash_token(token)))
    if invite is None or expired(invite):
        return None
    return invite


def consume(db: Session, invite: Invite) -> bool:
    """Takes the invitation away, in the open transaction; False when another request took it first. Of two requests
    at the same moment the database lets exactly one delete the row, so a link is used once whatever the timing."""
    try:
        return int(db.execute(delete(Invite).where(Invite.id == invite.id)).rowcount or 0) == 1
    except OperationalError:
        db.rollback()
        return False


def open_invites(db: Session) -> list[Invite]:
    """Every invitation not used yet, also those that ran out (the list says so; the operator withdraws them)."""
    return list(db.scalars(select(Invite).order_by(Invite.created_at)))
