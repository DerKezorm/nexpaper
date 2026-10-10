"""Accounts: the first is the operator, the others come by invitation or through OIDC.

An invitation is a link with an end date, made by the operator: whoever follows it makes an account.

After nextrmnl's accounts: the name is checked before the password, and an unknown name costs the same time as a
wrong password, so that neither answer nor timing tells which names exist.
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
from datetime import timedelta
from functools import lru_cache

from sqlalchemy import delete, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .. import __version__, clock
from ..config import get_settings
from ..models import MEMBER, OPERATOR, ROLES, SIGN_IN_OIDC, SIGN_IN_PASSWORD, Account, Invite, utcnow
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
    return db.scalar(select(Account).where(Account.name == name.strip().lower()))


def check_name(db: Session, name: str) -> str:
    cleaned = name.strip().lower()
    if not NAME_PATTERN.match(cleaned):
        raise AccountError("invalid_account_name", "Use 2 to 64 letters, digits, dots, dashes or underscores.", 422)
    if by_name(db, cleaned) is not None:
        raise AccountError("name_taken", "This name is already taken.", 409)
    return cleaned


def create_with_password(db: Session, name: str, password: str, role: str = MEMBER, *, commit: bool = True) -> Account:
    if role not in ROLES:
        raise ValueError("unknown role")
    account = Account(
        name=check_name(db, name),
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


#: One setup at a time: two at once each counted no account yet and made two operators.
_setup_lock = threading.Lock()
_generated_code: str | None = None


def setup_code() -> str:
    """What the first account must bring: ``NEXPAPER_SETUP_TOKEN``, else a code made at start and written to the log.
    Whoever reaches a fresh instance first would otherwise become its operator."""
    global _generated_code
    given = get_settings().setup_token.strip()
    if given:
        return given
    if _generated_code is None:
        _generated_code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
    return _generated_code


def announce_setup_code(db: Session) -> None:
    """At start, while nobody has set nexpaper up: the code in the log, where only whoever runs the server reads it."""
    if count(db) == 0:
        if get_settings().setup_token.strip():
            logger.warning("nexpaper is not set up yet. Open it and give NEXPAPER_SETUP_TOKEN as the setup code.")
        else:
            logger.warning("nexpaper is not set up yet. The setup code is %s (new at every start until set up).",
                           setup_code())


def create_operator(db: Session, name: str, password: str, code: str) -> Account:
    with _setup_lock:
        if count(db) > 0:
            raise AccountError("already_set_up", "nexpaper is already set up.", 409)
        if not secrets.compare_digest(code.strip().upper().encode(), setup_code().upper().encode()):
            raise AccountError("setup_code_wrong", "The setup code is wrong. It is in the server's log.", 403)
        return create_with_password(db, name, password, OPERATOR)


def create_oidc(db: Session, name: str, subject: str, email: str) -> Account:
    base = re.sub(r"[^a-z0-9._-]", "-", name.strip().lower()).strip("-._") or "user"
    candidate = base[:60]
    suffix = 1
    while by_name(db, candidate) is not None or not NAME_PATTERN.match(candidate):
        suffix += 1
        candidate = f"{base[:57]}-{suffix}"
    account = Account(
        name=candidate,
        role=MEMBER,
        sign_in=SIGN_IN_OIDC,
        oidc_subject=subject,
        email=email,
        # The provider vouches for its address.
        email_confirmed_at=utcnow() if email else None,
        email_from_provider=bool(email),
        whats_new_seen=__version__,
    )
    db.add(account)
    db.commit()
    logger.info("Account created name=%s role=%s sign_in=oidc", account.name, MEMBER)
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


_account_locks: dict[int, threading.Lock] = {}
_account_locks_guard = threading.Lock()


def _one_check_at_a_time(account_id: int) -> threading.Lock:
    """Checks of one account's password in turn: 60 wrong ones at once all passed the lock test before the first
    failure was counted, and 46 were checked instead of 10."""
    with _account_locks_guard:
        return _account_locks.setdefault(account_id, threading.Lock())


def authenticate(db: Session, name: str, password: str, devices: frozenset[int] = frozenset()) -> Account:
    """Checks name and password; counts failures and locks the account after too many.

    A locked account answers like a wrong password (no hint that the name exists), except to a browser that signed in
    as it before (``devices``, the accounts its cookie names): a stranger guessing can lock the account against the
    world, not against its owner.
    Failures from that browser do not count towards the lock.
    """
    account = by_name(db, name)
    if account is None or account.sign_in != SIGN_IN_PASSWORD or account.blocked_at is not None:
        verify_password(password, _dummy_hash())
        logger.warning("Sign-in failed for an unknown account")
        raise AccountError("wrong_credentials", "Name or password is wrong.", 401)
    known_device = account.id in devices
    with _one_check_at_a_time(account.id):
        db.refresh(account)
        if is_locked(account) and not known_device:
            verify_password(password, _dummy_hash())
            logger.warning("Sign-in refused, account locked name=%s", account.name)
            raise AccountError("wrong_credentials", "Name or password is wrong.", 401)
        if not verify_password(password, account.password_hash):
            if not known_device:
                note_failure(db, account)
            raise AccountError("wrong_credentials", "Name or password is wrong.", 401)
        from . import totp

        if not totp.has_second_factor(db, account):
            # With a second factor, only the code resets the count of failures: otherwise whoever knows the password
            # could guess codes forever, a new password step before each lockout.
            note_success(db, account)
    return account


def check_password(account: Account, password: str) -> bool:
    return account.sign_in == SIGN_IN_PASSWORD and verify_password(password, account.password_hash)


def change_password(db: Session, account: Account, current: str, new: str) -> None:
    if not verify_password(current, account.password_hash):
        raise AccountError("wrong_password", "The current password is wrong.", 401)
    account.password_hash = hash_password(new)
    db.commit()
    logger.info("Password changed name=%s", account.name)


# --- Invitations ---------------------------------------------------------------------------------------------------


def create_invite(db: Session, by: Account, *, days: int, email: str = "") -> tuple[Invite, str]:
    if days not in INVITE_DAYS:
        raise AccountError("invalid_days", "Choose 1, 7 or 30 days.", 422)
    token = secrets.token_urlsafe(24)
    invite = Invite(
        token_hash=hash_token(token), email=email.strip()[:255], created_by=by.id,
        expires_at=utcnow() + timedelta(days=days),
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


def accept_invite(db: Session, token: str, name: str, password: str) -> Account:
    invite = find_invite(db, token)
    if invite is None:
        raise AccountError("invite_invalid", "This invitation is not valid any more.", 404)
    check_name(db, name)
    # The invitation goes before the account comes, in one transaction: two requests with the same link at the same
    # moment make one account, not two.
    if not consume(db, invite):
        db.rollback()
        raise AccountError("invite_invalid", "This invitation is not valid any more.", 404)
    try:
        account = create_with_password(db, name, password, commit=False)
    except AccountError:
        db.rollback()
        raise
    if invite.email and not account.email:
        account.email = invite.email
    db.commit()
    logger.info("Invite used name=%s", account.name)
    return account


def open_invites(db: Session) -> list[Invite]:
    return list(db.scalars(select(Invite).where(Invite.expires_at > utcnow()).order_by(Invite.created_at)))
