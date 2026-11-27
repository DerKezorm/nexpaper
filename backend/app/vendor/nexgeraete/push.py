"""Notifications through the push relay (G15–G17, G25).

A device signs up with ``PUT /api/app/1/push {ticket, key, understands}``: the relay's ticket, its public X25519 key
and the kinds it understands. A ticket belongs to one device of the account (a device paired again brings its ticket,
and the old pairing must not get everything twice). Each message is sealed for exactly that device (``seal.py``) and
posted to ``<relay>/v1/send`` as ``{ticket, enc, collapse?, quiet?}``; only a 410 drops the ticket (the app brings a new
one), any other failure leaves it.

Nothing goes out while the account is blocked or deleted, the operator has the app switched off, or the device is
disconnected (it has no row). A device gets a kind only if it understands it (an app that sends no ``understands``
gets exactly ``legacy_kinds``, G16) and has not switched it off (G25); ``operator_only`` kinds only reach operators."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from . import seal
from .config import SWITCH_APP, AppConfig, PushKind
from .devices import Caller
from .errors import DeviceRefused
from .model import AccountId, Device, DeviceId, Holder, PushState, Store

logger = logging.getLogger("nexgeraete.push")

#: The longest ticket taken (the relay's are far shorter); the relay takes ``collapse`` up to 64 characters.
TICKET_MAX = 2000
COLLAPSE_MAX = 64
#: How long a post to the relay may take.
RELAY_SECONDS = 5.0

#: ``send(url, body) -> HTTP status``: what posts to the relay. Tests and the reference put a recorder in its place.
Send = Callable[[str, dict[str, Any]], int]


def post(url: str, body: dict[str, Any]) -> int:
    """The default ``send``: JSON over ``urllib``, without the environment's proxy, at most five seconds."""
    data = json.dumps(body, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})  # noqa: S310
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=RELAY_SECONDS) as answer:
            return int(answer.status)
    except urllib.error.HTTPError as error:
        return int(error.code)


@dataclass
class Told:
    """What became of one message: devices that took it, tickets gone (410), failures that may pass."""

    sent: int = 0
    gone: int = 0
    failed: int = 0


def register(
    store: Store,
    config: AppConfig,
    caller: Caller,
    ticket: str,
    key: str,
    understands: list[str] | tuple[str, ...] | None = None,
    *,
    chosen: bool = True,
) -> None:
    """Sign a device up for notifications. ``chosen`` False (G61): ``understands`` is the app's translation of an older
    form of its own (nextime: ``alerts`` of the TestFlight app), not the device's word; the store keeps it so that
    ``chooses_kinds`` stays false."""
    if not ticket or len(ticket) > TICKET_MAX or not key or len(key) > 100 or not seal.key_valid(key):
        raise DeviceRefused("push_ticket_invalid")
    kinds = None if understands is None else tuple(dict.fromkeys(str(kind)[:32] for kind in understands[:100]))
    for other in store.devices_of(caller.holder.id):
        if str(other.id) != str(caller.device.id) and other.push is not None and other.push.ticket == ticket:
            store.set_push(other.id, None)
    store.set_push(
        caller.device.id,
        PushState(ticket=ticket, key=key, understands=kinds, chosen=None if kinds is None else bool(chosen)),
    )
    store.commit()


def unregister(store: Store, config: AppConfig, caller: Caller) -> None:
    """No more notifications for this device; it stays paired."""
    store.set_push(caller.device.id, None)
    store.commit()


def offered(config: AppConfig, holder: Holder) -> list[PushKind]:
    """The kinds the account may switch on its devices: ``operator_only`` ones only for operators."""
    return [kind for kind in config.all_kinds if holder.operator or not kind.operator_only]


def kinds(config: AppConfig, device: Device, holder: Holder, language: str) -> list[dict[str, Any]]:
    """The list of the app's settings and of the browser's card: id, words, on or off on this device."""
    found = []
    for kind in offered(config, holder):
        title, hint = kind.words(language, config.app)
        found.append(
            {
                "id": kind.id,
                "title": title,
                "hint": hint,
                "on": bool(device.kinds.get(kind.id, kind.default_on)),
                "operator_only": kind.operator_only,
            }
        )
    return found


def set_kinds(store: Store, config: AppConfig, device: Device, holder: Holder, changes: Mapping[str, bool]) -> Device:
    """Switch kinds on or off on one device; a kind the account is not offered is refused before anything changes."""
    allowed = {kind.id for kind in offered(config, holder)}
    for kind_id in changes:
        if kind_id not in allowed:
            raise DeviceRefused("kind_unknown")
    merged = {**device.kinds, **{kind_id: bool(on) for kind_id, on in changes.items()}}
    store.set_kinds(device.id, merged)
    store.commit()
    device.kinds = merged
    return device


def understood(config: AppConfig, device: Device, kind: str) -> bool:
    if device.push is None:
        return False
    known = device.push.understands if device.push.understands is not None else config.legacy_kinds
    return kind in known


def wanted(config: AppConfig, device: Device, holder: Holder, kind: str) -> bool:
    found = config.kind(kind)
    if found is None or (found.operator_only and not holder.operator):
        return False
    return bool(device.kinds.get(kind, found.default_on))


def plaintext(message: Mapping[str, Any] | bytes) -> bytes:
    """What the device decrypts: compact JSON in the order the app gave the fields (or the app's own bytes)."""
    if isinstance(message, bytes):
        return message
    return json.dumps(dict(message), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def tell(
    store: Store,
    config: AppConfig,
    account_id: AccountId,
    kind: str,
    message: Mapping[str, Any] | bytes,
    *,
    collapse: str = "",
    quiet: bool = False,
    badge: int | None = None,
    skip: DeviceId | None = None,
    send: Send | None = None,
) -> Told:
    """One message of ``kind`` to every device of the account that may get it (``skip``: one device left out, the new
    one of a ``security`` notice). ``quiet``: a silent push that wakes the app (nextime); ``badge``: the number on the
    app's icon (nexmail). The app's own events call this; the module calls it for ``update`` and ``security``."""
    told = Told()
    relay = config.relay()
    holder = store.holder(account_id)
    if not relay or holder is None or holder.out or not store.switch(SWITCH_APP):
        return told
    body_text = plaintext(message)
    poster = send or post
    for device in store.devices_of(account_id):
        if device.push is None or (skip is not None and str(device.id) == str(skip)):
            continue
        if not understood(config, device, kind) or not wanted(config, device, holder, kind):
            continue
        try:
            enc = seal.seal(body_text, device.push.key, config.push_info)
        except ValueError:
            logger.info("Push to one device failed: its key is not usable")
            told.failed += 1
            continue
        body: dict[str, Any] = {"ticket": device.push.ticket, "enc": enc}
        if collapse:
            body["collapse"] = collapse[:COLLAPSE_MAX]
        if quiet:
            body["quiet"] = True
        if badge is not None:
            body["badge"] = badge
        try:
            status = poster(f"{relay}/v1/send", body)
        except (OSError, ValueError) as error:
            logger.info("Push to one device failed: %s", type(error).__name__)
            told.failed += 1
            continue
        if status == 410:
            logger.info("A push ticket is gone; removing it")
            store.set_push(device.id, None)
            store.commit()
            told.gone += 1
        elif status == 200:
            told.sent += 1
        else:
            logger.info("Push to one device failed: HTTP %s", status)
            told.failed += 1
    return told


def tell_operators(
    store: Store,
    config: AppConfig,
    kind: str,
    message: Callable[[Holder], Mapping[str, Any] | bytes],
    *,
    collapse: str = "",
    send: Send | None = None,
) -> Told:
    """One message to every operator, in the words of each (``message(holder)``)."""
    total = Told()
    for account_id in store.operators():
        holder = store.holder(account_id)
        if holder is None or not holder.operator:
            continue
        told = tell(store, config, account_id, kind, message(holder), collapse=collapse, send=send)
        total.sent += told.sent
        total.gone += told.gone
        total.failed += told.failed
    return total
