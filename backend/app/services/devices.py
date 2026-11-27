"""Paired devices: a phone, a later native app or a script speaks for an account with a token of its own.

The token travels in ``Authorization: Bearer`` next to the session cookie of a browser (``deps.require_account``). It
is made from a signed-in browser, by a pairing code, or by a device of the same account for the owner's other device
(``sibling``), shown once, and stored as its SHA-256. A device acts with the rights of its account, no more.

Since 1.13.0 the shared module geraete knows the devices (``services/geraete_store.py``): it checks a token
(``check``), brings in a sibling and pairs by a code, the same in every nex app. A device rests while its account is
blocked, deleted with its days to bring it back, or locked for a while (G26), and works again afterwards; it ends when
it is revoked, with "sign out everywhere", when its account is deleted for good, and after a year without use (G27).
The second factor was met at pairing; when the operator asks for one the account has not set up, the device waits.

**The token.** ``npd_`` and 43 random characters. It never reaches the log. A wrong one counts like a wrong password
for the sender (the brake in ``deps``).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import unicodedata
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import detail, error
from ..models import Account, Device, utcnow
from ..vendor import nexgeraete
from . import geraete_store

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
    """A new device in the open transaction, not yet committed (an app's code of OAuth commits it together with the
    code it used up). The token is returned once and never stored."""
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


#: Devices one account may bring in through a device it has, per hour (``sibling``), counted in the database.
SIBLINGS_PER_HOUR = geraete_store.CONFIG.siblings_per_hour


def refused(refusal: nexgeraete.DeviceRefused) -> HTTPException:
    """A refusal of the module in the shape of ``/api/v1`` (the codes the published iPhone app reads)."""
    if refusal.code == "too_many_new_devices":
        return HTTPException(status_code=429, headers={"Retry-After": "3600"}, detail=detail(
            "too_many_new_devices", "Too many new devices in an hour. Try again later.", retry_after=3600))
    if refusal.code == "too_many_devices":
        return error("too_many_devices", f"An account holds at most {MAX_DEVICES} devices.", 409)
    if refusal.code in ("app_disabled", "app_pairing_disabled"):
        return error(refusal.code, refusal.message, 403)
    return error("token_invalid", "No valid device token.", 401)


def sibling(db: Session, account: Account, parent: str, name: str,
            client: nexgeraete.Client | None = None) -> tuple[Device, str]:
    """A token of its own for another device of the same account, asked for by a device it already has.

    The iPhone app hands its connection to the owner's iPad through their iCloud Keychain; the iPad takes it once to
    come in under its own name, so it stands in the list on its own and can be revoked alone. It gets the rights of the
    account, the same as the device asking, and nothing of the browser's side. At most ``SIBLINGS_PER_HOUR`` per
    account and hour, counted in the database (the module's ``pairing.sibling``, G9), so a token is no factory of
    tokens and a restart forgets nothing."""
    name = clean_name(name)
    data = geraete_store.GeraeteStore(db)
    device, holder = data.device(parent), data.holder(account.id)
    if device is None or holder is None:
        raise error("token_invalid", "No valid device token.", 401)
    try:
        done = nexgeraete.pairing.sibling(data, geraete_store.CONFIG, nexgeraete.Caller(device, holder), name=name,
                                          client=client, now=clock.now())
    except nexgeraete.DeviceRefused as refusal:
        db.rollback()
        raise refused(refusal) from None
    logger.info("Device paired device_id=%s via=device by device_id=%s", done.device.id, parent)
    geraete_store.after_pairing(db, done)
    row = data.row(done.device.id)
    assert row is not None
    return row, done.token


def forget() -> None:
    """Tests: nothing is kept in memory any more (the brought-in devices are counted in the database)."""


def listing(db: Session, account_id: int) -> list[Device]:
    """The live devices of an account, the most recently made first."""
    return list(db.scalars(select(Device).where(Device.account_id == account_id, Device.revoked_at.is_(None))
                           .order_by(Device.created_at.desc(), Device.id.desc())))


def revoke(db: Session, account_id: int, uid: str) -> bool:
    """Ends one device of the account (the module's ``disconnect``). False when there is none (another account's
    looks the same)."""
    try:
        nexgeraete.devices.disconnect(geraete_store.GeraeteStore(db), geraete_store.CONFIG, account_id, uid)
    except nexgeraete.DeviceRefused:
        db.rollback()
        return False
    logger.info("Device revoked device_id=%s", uid)
    return True


def check(db: Session, token: str | None, client: nexgeraete.Client | None = None
          ) -> tuple[nexgeraete.Caller, Account]:
    """The device and its account for a token (the module's ``authenticate``, G12), the account detached; else
    ``nexgeraete.DeviceRefused``: no such token or revoked, the account out (blocked, deleted, locked: the device
    rests), the second factor owed, the app switched off by the operator. Notes "last used" at most once a minute,
    with what ``X-Nex-App`` says."""
    caller = nexgeraete.authenticate(geraete_store.GeraeteStore(db), geraete_store.CONFIG, token, client=client,
                                     now=clock.now())
    account = db.get(Account, int(caller.holder.id))
    if account is None:
        raise nexgeraete.DeviceRefused("device_disconnected")
    db.expunge(account)
    return caller, account

