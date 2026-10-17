"""Passwords, browser sessions, the brake against guessing, and the secrets the server keeps for itself.

Built after nextrmnl's: Argon2id for passwords, sessions as random tokens of which the database knows only the
hash, a brake per sender in memory and a lock per account in the database: five failures, then a quarter of an hour
of rest, per account and per address.

Sessions come in two lengths: with "stay signed in on this device" one lasts until it was not used for
``session_days`` (sliding, checked here, not left to the cookie); without, it ends with the browser and after
``SHORT_HOURS`` at the latest. A session right after the password of an account that still has to set up its second
factor is a stage of its own (``STAGE_SETUP``) and lives ``SETUP_MINUTES``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import threading
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from . import clock
from .config import get_settings
from .models import STAGE_FULL, Account, AuthSession, Device

logger = logging.getLogger("nexpaper.auth")

SESSION_COOKIE = "nexpaper_session" + get_settings().cookie_name_suffix()
MIN_PASSWORD = 12
#: After this many failures an account, and an address, waits a quarter of an hour. Not configurable on purpose.
MAX_FAILURES = 5
LOCK_MINUTES = 15
#: A session without "stay signed in" ends after this many hours, whatever happens.
SHORT_HOURS = 12
#: A session that may only set up the second factor ends after this many minutes.
SETUP_MINUTES = 15
#: How often a session's last use is written down: the interface asks often.
TOUCH_SECONDS = 300


def _hasher() -> PasswordHasher:
    settings = get_settings()
    return PasswordHasher(
        time_cost=settings.argon2_time, memory_cost=settings.argon2_memory_kib, parallelism=settings.argon2_parallelism
    )


#: Argon2 takes 64 MB per check. Sign-in needs no account, so without a limit a crowd of guesses at once could ask for
#: gigabytes (about 40 threads at a time); a small NAS would run out of memory.
HASHING_AT_ONCE = 4
#: Seconds a check waits for a free slot before the request answers busy.
HASH_WAIT = 15
_hashing = threading.BoundedSemaphore(HASHING_AT_ONCE)


class HashingBusy(Exception):
    """Every slot for checking passwords stayed taken: the request answers 503, the browser tries again."""


def _hash_slot() -> None:
    if not _hashing.acquire(timeout=HASH_WAIT):
        raise HashingBusy


def hash_password(password: str) -> str:
    _hash_slot()
    try:
        return _hasher().hash(password)
    finally:
        _hashing.release()


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    _hash_slot()
    try:
        return _hasher().verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    finally:
        _hashing.release()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def session_expiry(remember: bool, stage: str, now: datetime) -> datetime:
    """When a session started or used at ``now`` runs out."""
    if stage != STAGE_FULL:
        return now + timedelta(minutes=SETUP_MINUTES)
    if remember:
        return now + timedelta(days=get_settings().session_days)
    return now + timedelta(hours=SHORT_HOURS)


def start_session(
    db: Session, account: Account, ip: str, user_agent: str, *, remember: bool = True, stage: str = STAGE_FULL,
    second_factor_by_provider: bool = False,
) -> str:
    """Creates a browser session and returns the token for the cookie. ``second_factor_by_provider``: it came in
    through a provider whose entry checks the second factor itself (``AuthSession.second_factor_by_provider``)."""
    token = new_token()
    now = clock.now()
    db.add(
        AuthSession(
            token_hash=hash_token(token),
            account_id=account.id,
            created_at=now,
            last_seen_at=now,
            expires_at=session_expiry(remember, stage, now),
            ip=ip[:64],
            user_agent=user_agent[:255],
            remember=remember,
            stage=stage,
            second_factor_by_provider=second_factor_by_provider,
        )
    )
    if stage == STAGE_FULL:
        account.last_seen_at = now
    db.commit()
    return token


def current_session(db: Session, token: str | None, ip: str | None = None) -> tuple[AuthSession, Account] | None:
    """The session a cookie names and its account, or None when it ran out, its account is gone or blocked.

    A long session slides: every use moves its end ``session_days`` ahead (written down every few minutes only). A
    short one and one that may only set up the second factor never move."""
    if not token:
        return None
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if session is None:
        return None
    now = clock.now()
    if session.expires_at <= now:
        db.delete(session)
        db.commit()
        return None
    account = db.get(Account, session.account_id)
    if account is None or account.blocked_at is not None:
        return None
    if session.stage == STAGE_FULL and (now - session.last_seen_at).total_seconds() > TOUCH_SECONDS:
        session.last_seen_at = now
        account.last_seen_at = now
        if ip:
            session.ip = ip[:64]
        if session.remember:
            session.expires_at = session_expiry(True, STAGE_FULL, now)
        db.commit()
    return session, account


def session_account(db: Session, token: str | None) -> Account | None:
    """The account of a session of any stage (``current_session``)."""
    found = current_session(db, token)
    return found[1] if found else None


def end_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        db.commit()


def end_all_sessions(db: Session, account_id: int, except_token: str | None = None) -> None:
    """Every browser session of the account but ``except_token``, and every paired device: a new password or "sign
    out everywhere" is what one does when the account was taken. Keys made by hand in the interface stay; they are
    blocked there."""
    statement = delete(AuthSession).where(AuthSession.account_id == account_id)
    if except_token:
        statement = statement.where(AuthSession.token_hash != hash_token(except_token))
    db.execute(statement)
    db.execute(update(Device).where(Device.account_id == account_id, Device.revoked_at.is_(None))
               .values(revoked_at=clock.now()))
    db.commit()


def purge_sessions(db: Session) -> int:
    result = db.execute(delete(AuthSession).where(AuthSession.expires_at <= clock.now()))
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


class Brake:
    """Waiting time after failures, per sender. In memory only; the per-account lock is in the database.

    ``FREE`` failures pass; after that every further try waits ``PAUSE`` seconds from the last failure (five, then a
    quarter of an hour). A count is forgotten an hour after its last failure, and the table is thinned out when it
    grows: every new address (cheap with IPv6) would otherwise stay in memory for as long as the server runs.
    """

    FREE = MAX_FAILURES
    PAUSE = LOCK_MINUTES * 60
    FORGET_AFTER = 3600
    MAX_KEYS = 50_000

    def __init__(self, *, quiet: bool = False) -> None:
        self._lock = threading.Lock()
        self._fails: dict[str, tuple[int, float]] = {}
        #: Says nothing to the log when it engages: for the self-check of "Ready for the internet?".
        self._quiet = quiet

    def _current(self, key: str, now: float) -> tuple[int, float]:
        count, last = self._fails.get(key, (0, 0.0))
        return (0, 0.0) if count and now - last > self.FORGET_AFTER else (count, last)

    def wait_seconds(self, key: str, free: int | None = None) -> int:
        """Seconds to wait; ``free`` failures pass without (``FREE`` when not given)."""
        free = self.FREE if free is None else free
        now = clock.monotonic()
        with self._lock:
            count, last = self._current(key, now)
        if count < free:
            return 0
        remaining = last + self.PAUSE - now
        return max(0, int(remaining + 0.999))

    def claim(self, key: str, free: int | None = None) -> int:
        """Counts one more for ``key`` unless it must rest: the seconds to wait, or 0 when it was counted. Looking and
        counting in one step, so that of many at the same moment only ``free`` get through."""
        free = self.FREE if free is None else free
        now = clock.monotonic()
        with self._lock:
            count, last = self._current(key, now)
            if count >= free:
                return max(1, int(last + self.PAUSE - now + 0.999))
            self._fails[key] = (count + 1, now)
        return 0

    def failed(self, key: str, free: int | None = None) -> None:
        free = self.FREE if free is None else free
        now = clock.monotonic()
        with self._lock:
            count, _ = self._current(key, now)
            self._fails[key] = (count + 1, now)
            if count + 1 == free and not self._quiet:
                # The key names the kind and the sender (an address, never a password).
                logger.warning("Brake engaged after %s failures, %s minutes of rest key=%s", free, LOCK_MINUTES, key)
            if len(self._fails) > self.MAX_KEYS:
                self._fails = {k: v for k, v in self._fails.items() if now - v[1] <= self.FORGET_AFTER}
                while len(self._fails) > self.MAX_KEYS * 0.9:
                    self._fails.pop(next(iter(self._fails)))

    def succeeded(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)

    def forget(self) -> None:
        """For the tests."""
        with self._lock:
            self._fails.clear()


brake = Brake()


# --- Secrets the server reads on its own (OIDC client secret, mail password) ---------------------------------------

_AAD = b"nexpaper-server-secret-v1"
_NONCE = 12


def server_key() -> bytes:
    """The key derived from ``secret.key`` for what the server seals or signs for itself."""
    secret = get_settings().resolved_secret_key().encode("utf-8")
    return hashlib.sha256(b"nexpaper-secrets:" + secret).digest()



DEVICE_COOKIE = "nexpaper_device" + get_settings().cookie_name_suffix()
DEVICE_DAYS = 365
#: Accounts one browser remembers: a household may share a tablet.
DEVICE_ACCOUNTS_MAX = 5


def _device_entry(account_id: int) -> str:
    nonce = secrets.token_urlsafe(12)
    mark = hashlib.sha256(server_key() + f"device:{account_id}:{nonce}".encode()).hexdigest()[:32]
    return f"{account_id}.{nonce}.{mark}"


def _entry_account(entry: str) -> int | None:
    if entry.count(".") != 2:
        return None
    account, nonce, mark = entry.split(".")
    if not account.isdigit() or len(account) > 12:
        return None
    expected = hashlib.sha256(server_key() + f"device:{account}:{nonce}".encode()).hexdigest()[:32]
    return int(account) if secrets.compare_digest(mark, expected) else None


def device_token(account_id: int, current: str | None = None) -> str:
    """A browser that signed in as this account (and as the others it signed in as before, ``current``): it may
    still sign in while the account is locked against the rest of the world, and signing in from it again is no
    "new sign-in" (``services/notices.py``). Signed with the server's key; nothing about it is stored."""
    kept: list[str] = []
    for entry in (current or "")[:2000].split("~")[: DEVICE_ACCOUNTS_MAX * 2]:
        account = _entry_account(entry)
        if account is not None and account != account_id and len(kept) < DEVICE_ACCOUNTS_MAX - 1:
            kept.append(entry)
    return "~".join([_device_entry(account_id), *kept])


def devices_of(token: str | None) -> frozenset[int]:
    """The accounts a device cookie was given for, as far as this server signed them; empty when none."""
    if not token:
        return frozenset()
    found = (_entry_account(entry) for entry in token[:2000].split("~")[: DEVICE_ACCOUNTS_MAX * 2])
    return frozenset(account for account in found if account is not None)


def device_of(token: str | None) -> int | None:
    """The account a device cookie was given to last, or None when it is missing or not signed by this server."""
    if not token:
        return None
    return _entry_account(token[:2000].split("~")[0])


def _aad(context: str) -> bytes:
    # A context of its own per kind of secret: an AI key sealed for one account cannot be passed off as another's,
    # nor as a request of the AI list. Without one, the old secrets (OIDC, mail) read as before.
    return _AAD + b":" + context.encode("utf-8") if context else _AAD


def encrypt_secret(text: str, context: str = "") -> str:
    """AES-256-GCM with a key from ``secret.key``, stored as hex."""
    if not text:
        return ""
    nonce = os.urandom(_NONCE)
    return (nonce + AESGCM(server_key()).encrypt(nonce, text.encode("utf-8"), _aad(context))).hex()


def decrypt_secret(stored: str, context: str = "") -> str:
    if not stored:
        return ""
    try:
        sealed = bytes.fromhex(stored)
        return AESGCM(server_key()).decrypt(sealed[:_NONCE], sealed[_NONCE:], _aad(context)).decode("utf-8")
    except (InvalidTag, ValueError):
        # A different secret.key than the one that encrypted it: the value is lost, not the app.
        return ""
