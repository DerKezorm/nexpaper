"""Pairing a device (G6–G10): four ways in, one result (a key of the device's own).

* **QR code** ("iPhone oder iPad verbinden"): a pairing of ten minutes for one device, its id and a secret of 256 bits
  in the link ``<scheme>://connect?server=…&address=…&pairing=…&secret=…`` (both names of the address, G6);
* **code to type**, under the QR code: ``K7MQ-R4TX``, the same pairing (G7);
* **sign-in in the browser**: the page ``/app-connect`` hands the app a one-time code (five minutes, once) with the
  app's ``state`` and, where the app sent one, its PKCE ``challenge`` (G8); ``POST pairing/code`` takes it like a typed
  code and checks the ``verifier``;
* **another own device** (iCloud): a device's key asks for one of its own for the new device, at most five an hour,
  counted in the database (G9).

Unknown, wrong, expired and used answer the same (``pairing_gone``); secrets are compared in fixed time even without a
row; a pairing and a one-time code are used in one conditional UPDATE (of two pickups exactly one hits). The brake per
sender is the router's (``api.py``)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote

from . import tokens
from .config import SWITCH_APP, VIA_BROWSER, VIA_CODE, VIA_ICLOUD, VIA_QR, AppConfig
from .devices import Caller, Client, add, kind_of, utcnow
from .errors import DeviceRefused
from .model import AccountId, ConnectCode, Device, Holder, NewPairing, Pairing, Store

#: The longest secret or one-time code looked at.
_LONGEST = 200


@dataclass(frozen=True)
class Started:
    """A new pairing: the secret and the code exist in plain text only here."""

    pairing: Pairing
    secret: str
    #: ``K7MQ-R4TX``.
    code: str
    link: str
    address: str


@dataclass(frozen=True)
class Paired:
    """A new device and its key (shown this once)."""

    token: str
    device: Device
    holder: Holder


def connect_link(config: AppConfig, address: str, pairing_id: str, secret: str) -> str:
    """The QR code's link. ``server=`` for nexnotes and nextime, ``address=`` for nextasks, nexlore, nexmail; every
    app passes over the part it does not know."""
    where = quote(address, safe="")
    return (
        f"{config.scheme}://connect?server={where}&address={where}&pairing={quote(pairing_id, safe='')}"
        f"&secret={quote(secret, safe='')}"
    )


def ready(store: Store, config: AppConfig) -> None:
    """New devices may come in: the app and the pairing switch are on (else 403)."""
    if not store.switch(SWITCH_APP):
        raise DeviceRefused("app_disabled")
    if not store.switch(config.pairing_switch):
        raise DeviceRefused("app_pairing_disabled")


def start(
    store: Store,
    config: AppConfig,
    account_id: AccountId,
    *,
    address: str,
    replace: bool = False,
    now: datetime | None = None,
) -> Started:
    """A new pairing of the account. At most ``open_pairings`` wait at once (``409 too_many_pairings``); with
    ``replace`` the open ones end instead (nexpaper: a new code ends the one before)."""
    ready(store, config)
    now = now or utcnow()
    waiting = store.open_pairings(account_id, now)
    if replace:
        for row in waiting:
            store.remove_pairing(row.id)
    elif len(waiting) >= config.open_pairings:
        raise DeviceRefused("too_many_pairings", max=config.open_pairings)
    secret = tokens.make_secret()
    code = tokens.make_code(config.code_length)
    row = store.add_pairing(
        NewPairing(
            id=tokens.make_secret(nbytes=12),
            account_id=account_id,
            secret_hash=tokens.digest(secret),
            code_hash=tokens.digest(code),
            created_at=now,
            expires_at=now + timedelta(minutes=config.pairing_minutes),
        )
    )
    store.commit()
    return Started(row, secret, tokens.show_code(code), connect_link(config, address, row.id, secret), address)


def _own(store: Store, account_id: AccountId, pairing_id: str) -> Pairing:
    row = store.pairing(pairing_id[:64])
    if row is None or str(row.account_id) != str(account_id):
        raise DeviceRefused("not_found")
    return row


def state(
    store: Store, config: AppConfig, account_id: AccountId, pairing_id: str, now: datetime | None = None
) -> tuple[str, Device | None]:
    """``waiting``, ``used`` (with the device, if it is still there) or ``expired``."""
    row = _own(store, account_id, pairing_id)
    if row.used_at is not None:
        return "used", store.device(row.device_id) if row.device_id is not None else None
    return ("expired" if row.expires_at <= (now or utcnow()) else "waiting"), None


def withdraw(store: Store, config: AppConfig, account_id: AccountId, pairing_id: str) -> None:
    row = _own(store, account_id, pairing_id)
    if row.used_at is None:
        store.remove_pairing(row.id)
        store.commit()


def _fits(store: Store, account_id: AccountId) -> Holder:
    """The account may take a new device now: not blocked or deleted, owing no second factor."""
    holder = store.holder(account_id)
    if holder is None or holder.out or holder.factor_owed:
        raise DeviceRefused("pairing_gone")
    return holder


def _use(
    store: Store,
    config: AppConfig,
    row: Pairing,
    via: str,
    name: str | None,
    kind: str | None,
    client: Client | None,
    now: datetime,
) -> Paired:
    if row.used_at is not None or row.expires_at <= now:
        raise DeviceRefused("pairing_gone")
    try:
        holder = _fits(store, row.account_id)
    except DeviceRefused:
        # The account may not let a device in now: the code is used up all the same.
        store.use_pairing(row.id, None, now)
        store.commit()
        raise
    device, token = add(store, config, holder, name=name, kind=kind_of(kind, client), via=via, client=client, now=now)
    if not store.use_pairing(row.id, device.id, now):
        store.rollback()
        raise DeviceRefused("pairing_gone")
    store.commit()
    return Paired(token, device, holder)


def redeem(
    store: Store,
    config: AppConfig,
    pairing_id: str | None,
    secret: str | None,
    *,
    name: str | None = None,
    kind: str | None = None,
    client: Client | None = None,
    now: datetime | None = None,
) -> Paired:
    """The key for the id and secret of the QR code. Compared even without a row, so that an unknown id does not
    answer faster than a wrong secret."""
    ready(store, config)
    now = now or utcnow()
    row = store.pairing((pairing_id or "")[:64]) if pairing_id else None
    expected = row.secret_hash if row is not None else tokens.digest("")
    right = tokens.same(expected, tokens.digest((secret or "")[:_LONGEST]))
    if row is None or not right or not secret:
        raise DeviceRefused("pairing_gone")
    return _use(store, config, row, VIA_QR, name, kind, client, now)


def redeem_code(
    store: Store,
    config: AppConfig,
    code: str | None,
    *,
    verifier: str | None = None,
    name: str | None = None,
    kind: str | None = None,
    client: Client | None = None,
    now: datetime | None = None,
) -> Paired:
    """Every code (G7): a typed code of ``code_length`` letters finds its pairing; anything else is taken as the
    one-time code of the sign-in in the browser, used once whatever follows. Where the page got a ``challenge``, the
    ``verifier`` must fit it: one that does not has used the code up (one try for whoever intercepted it)."""
    ready(store, config)
    now = now or utcnow()
    typed = tokens.code_key(code, config.code_length)
    if typed is not None:
        row = store.pairing_by_code(tokens.digest(typed))
        if row is None:
            raise DeviceRefused("pairing_gone")
        return _use(store, config, row, VIA_CODE, name, kind, client, now)
    if not code or len(code) > _LONGEST:
        raise DeviceRefused("pairing_gone")
    found = store.take_connect_code(tokens.digest(code), now)
    store.commit()
    if found is None:
        raise DeviceRefused("pairing_gone")
    if found.challenge is not None and not tokens.pkce_ok(verifier, found.challenge):
        raise DeviceRefused("pairing_gone")
    holder = _fits(store, found.account_id)
    device, token = add(
        store, config, holder, name=name, kind=kind_of(kind, client), via=VIA_BROWSER, client=client, now=now
    )
    store.commit()
    return Paired(token, device, holder)


def consent(
    store: Store,
    config: AppConfig,
    account_id: AccountId,
    app_state: str | None,
    *,
    challenge: str | None = None,
    now: datetime | None = None,
) -> str:
    """"Verbinden" on ``/app-connect``: the link back into the app, ``<scheme>://connected?code=…&state=…``, with a
    one-time code (five minutes, once) of which only the hash is kept."""
    if not tokens.state_ok(app_state):
        raise DeviceRefused("invalid_input", fields=["state"])
    if challenge is not None and not tokens.challenge_ok(challenge):
        raise DeviceRefused("invalid_input", fields=["challenge"])
    ready(store, config)
    now = now or utcnow()
    code = tokens.make_secret()
    store.add_connect_code(
        ConnectCode(
            code_hash=tokens.digest(code),
            account_id=account_id,
            state=app_state or "",
            challenge=challenge,
            created_at=now,
            expires_at=now + timedelta(minutes=config.connect_minutes),
        )
    )
    store.commit()
    return f"{config.scheme}://connected?code={quote(code, safe='')}&state={quote(app_state or '', safe='')}"


def sibling(
    store: Store,
    config: AppConfig,
    caller: Caller,
    *,
    name: str | None = None,
    kind: str | None = None,
    client: Client | None = None,
    now: datetime | None = None,
) -> Paired:
    """A key of its own for another device of the same account, asked for by a device it has (iCloud). The new one
    has the rights of the one asking, no more. At most ``siblings_per_hour`` per account, counted in the database:
    devices of the account that came in over iCloud in the last hour (G9), so a restart forgets nothing."""
    ready(store, config)
    now = now or utcnow()
    hour = timedelta(hours=1)
    recent = sorted(
        device.created_at
        for device in store.devices_of(caller.holder.id)
        if device.via == VIA_ICLOUD and device.created_at is not None and now - device.created_at < hour
    )
    if len(recent) >= config.siblings_per_hour:
        wait = max(1, math.ceil((hour - (now - recent[0])).total_seconds()))
        raise DeviceRefused("too_many_new_devices", retry_after=wait, max=config.siblings_per_hour)
    device, token = add(
        store,
        config,
        caller.holder,
        name=name,
        kind=kind_of(kind, client),
        via=VIA_ICLOUD,
        client=client,
        via_device=caller.device.id,
        now=now,
    )
    store.commit()
    return Paired(token, device, caller.holder)
