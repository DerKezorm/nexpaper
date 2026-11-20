"""Paired devices: a phone, a later native app or a script speaks for an account with a token of its own.

The token travels in ``Authorization: Bearer`` next to the session cookie of a browser (``deps.require_account``). It
is made from a signed-in browser, or by a device of the same account for the owner's other device (``sibling``), shown
once, and stored as its SHA-256. A
device acts with the rights of its account, no more. It stops working when the account is blocked, locked or
deleted, and when it is revoked; the second factor was met at pairing, so the device does not ask for it again.

**The token.** ``npd_`` and 43 random characters. It never reaches the log. A wrong one counts like a wrong password
for the sender (the brake in ``deps``).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
import unicodedata
from collections import defaultdict, deque
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import detail, error
from ..models import Account, Device, utcnow

logger = logging.getLogger("nexpaper.auth")

TOKEN_PREFIX = "npd_"
#: How many devices an account may hold (revoked ones do not count).
MAX_DEVICES = 30
NAME_MAX = 80
#: ``last_used_at`` is written at most this often.
USED_EVERY = timedelta(minutes=1)


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def clean_name(value: str) -> str:
    """Spaces gathered, no control or invisible characters, at most ``NAME_MAX``; never empty."""
    if any(ord(char) < 32 or ord(char) == 127 or unicodedata.category(char) == "Cf" for char in value):
        raise error("device_name_invalid", "A device name cannot hold control or invisible characters.", 422)
    clean = " ".join(value.split())
    if not clean or len(clean) > NAME_MAX:
        raise error("device_name_invalid", f"Use 1 to {NAME_MAX} characters.", 422)
    return clean


def add(db: Session, account_id: int, name: str, via: str = "token") -> tuple[Device, str]:
    """A new device in the open transaction, not yet committed (pairing by a code commits it together with the code it
    used up). The token is returned once and never stored."""
    name = clean_name(name)
    live = db.scalars(select(Device.id).where(Device.account_id == account_id, Device.revoked_at.is_(None))).all()
    if len(live) >= MAX_DEVICES:
        raise error("too_many_devices", f"An account holds at most {MAX_DEVICES} devices.", 409)
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = Device(account_id=account_id, name=name, token_hash=digest(token),
                 prefix=token[: len(TOKEN_PREFIX) + 4], created_at=utcnow(), via=via)
    db.add(row)
    db.flush()
    return row, token


def make(db: Session, account: Account, name: str) -> tuple[Device, str]:
    """A new device; the token is returned once and never stored."""
    row, token = add(db, account.id, name)
    db.commit()
    db.refresh(row)
    logger.info("Device paired device_id=%s via=token", row.uid)
    return row, token


#: Devices one account may bring in through a device it has, per hour (``sibling``).
SIBLINGS_PER_HOUR = 5

_siblings_lock = threading.Lock()
_siblings: dict[int, deque[float]] = defaultdict(deque)


def sibling(db: Session, account: Account, parent: str, name: str, now: float | None = None) -> tuple[Device, str]:
    """A token of its own for another device of the same account, asked for by a device it already has.

    The iPhone app hands its connection to the owner's iPad through their iCloud Keychain; the iPad takes it once to
    come in under its own name, so it stands in the list on its own and can be revoked alone. It gets the rights of the
    account, the same as the device asking: a device can do all its account may do through a token anyway, and nothing
    of the browser's side (making keys, the way in, the operator's routes). At most ``SIBLINGS_PER_HOUR`` per account,
    so a token is no factory of tokens. The second factor was met when the asking device was paired."""
    now = time.monotonic() if now is None else now
    with _siblings_lock:
        seen = _siblings[account.id]
        while seen and now - seen[0] > 3600:
            seen.popleft()
        if len(seen) >= SIBLINGS_PER_HOUR:
            raise HTTPException(status_code=429, headers={"Retry-After": "3600"}, detail=detail(
                "too_many_new_devices", "Too many new devices in an hour. Try again later.", retry_after=3600))
        seen.append(now)
    row, token = add(db, account.id, name, via="device")
    db.commit()
    db.refresh(row)
    logger.info("Device paired device_id=%s via=device by device_id=%s", row.uid, parent)
    return row, token


def forget() -> None:
    """Tests: the count of brought-in devices starts empty."""
    with _siblings_lock:
        _siblings.clear()


def listing(db: Session, account_id: int) -> list[Device]:
    """The live devices of an account, the most recently made first."""
    return list(db.scalars(select(Device).where(Device.account_id == account_id, Device.revoked_at.is_(None))
                           .order_by(Device.created_at.desc(), Device.id.desc())))


def revoke(db: Session, account_id: int, uid: str) -> bool:
    """Ends one device of the account. False when there is none (another account's looks the same)."""
    row = db.scalar(select(Device).where(Device.uid == uid, Device.account_id == account_id,
                                         Device.revoked_at.is_(None)))
    if row is None:
        return False
    row.revoked_at = clock.now()
    db.commit()
    logger.info("Device revoked device_id=%s", uid)
    return True


def authenticate(db: Session, token: str | None) -> tuple[Device, Account] | None:
    """The device and its account for a token, or None: no such token, revoked, or the account blocked or locked.
    Whether a second factor is still to be set up is the caller's to check."""
    if not token or not token.startswith(TOKEN_PREFIX) or len(token) > 200:
        return None
    row = db.scalar(select(Device).where(Device.token_hash == digest(token)))
    if row is None or row.revoked_at is not None:
        return None
    account = db.get(Account, row.account_id)
    now = clock.now()
    if account is None or account.blocked_at is not None or (
            account.locked_until is not None and account.locked_until > now):
        return None
    if row.last_used_at is None or now - row.last_used_at >= USED_EVERY:
        row.last_used_at = now
        db.commit()
    db.expunge(row)
    return row, account
