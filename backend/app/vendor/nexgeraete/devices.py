"""The devices of an account: making one, knowing it again by its key, the list, renaming, disconnecting, the
operator's view, the daily sweep.

**A device is a key** (the app's prefix and 32 random bytes, stored as SHA-256) with a name, a kind (``ios``,
``ipados``, ``mac``), the model, system and app version its app names in ``X-Nex-App`` (G5, G11), and the way it came
in. It acts as its account in ``/api/app/1``, never with more rights. It does not run out; it goes when it is
disconnected (here or in the app), with "sign out everywhere", when its account is deleted for good, or after 365 days
without any use (G27). While its account is blocked or deleted and still to be restored it rests (``account_blocked``,
no notification) and works again afterwards without pairing anew (G26)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from . import tokens
from .config import DEVICE_KINDS, SWITCH_APP, AppConfig
from .errors import DeviceRefused
from .model import AccountId, Device, DeviceChange, DeviceId, Holder, NewDevice, Store

_CLIENT = re.compile(r"([a-z][a-z0-9-]{0,40})/([0-9A-Za-z.+-]{1,32})(?: \(([^;()]{1,64})(?:; ([^;()]{1,64}))?\))?")


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Client:
    """What ``X-Nex-App: nexnotes-ios/1.3.0 (iPhone 16 Pro; iOS 18.1)`` says."""

    app: str
    version: str | None = None
    model: str | None = None
    system: str | None = None

    @property
    def kind(self) -> str | None:
        """The device's kind as the system names it, for an app that sends no ``device_kind``."""
        system = (self.system or "").lower()
        if system.startswith("ipados"):
            return "ipados"
        if system.startswith("macos"):
            return "mac"
        return "ios" if system.startswith("ios") else None


def client_of(header: str | None) -> Client | None:
    """The header ``X-Nex-App``; ``None`` without one or for one that does not fit (then nothing is noted)."""
    found = _CLIENT.fullmatch((header or "").strip())
    if found is None:
        return None
    app, version, model, system = found.groups()
    return Client(app=app, version=version, model=(model or "").strip() or None, system=(system or "").strip() or None)


@dataclass
class Caller:
    """Who calls a device route: its device and its account."""

    device: Device
    holder: Holder


def iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def entry(device: Device, this: DeviceId | None = None) -> dict[str, Any]:
    """A device as every route shows it: never its key, never its hash."""
    return {
        "id": device.id,
        "name": device.name,
        "kind": device.kind or DEVICE_KINDS[0],
        "model": device.model,
        "system": device.system,
        "app_version": device.app_version,
        "via": device.via,
        "created_at": iso(device.created_at),
        "last_seen_at": iso(device.last_seen_at),
        "push": device.push is not None,
        "this": this is not None and str(device.id) == str(this),
    }


def describe(device: Device) -> str:
    """The device in one line, for ``konten`` "Angemeldete Geräte" (``device_label``): its name, and the model where
    it says more."""
    if device.model and device.model != device.name:
        return f"{device.name} ({device.model})"
    return device.name


def _printable(raw: str | None) -> str:
    return " ".join("".join(char for char in (raw or "") if char.isprintable()).split())


def valid_name(config: AppConfig, raw: str | None) -> str:
    """A name typed by a person: spaces gathered, 1 to ``name_max`` characters, no control or invisible ones."""
    value = raw or ""
    if any(ord(char) < 32 or ord(char) == 127 or unicodedata.category(char) in ("Cc", "Cf") for char in value):
        raise DeviceRefused("name_invalid", max=config.name_max)
    clean = " ".join(value.split())
    if not clean or len(clean) > config.name_max:
        raise DeviceRefused("name_invalid", max=config.name_max)
    return clean


def kind_of(raw: str | None, client: Client | None) -> str:
    if raw in (None, ""):
        return (client.kind if client else None) or DEVICE_KINDS[0]
    if raw not in DEVICE_KINDS:
        raise DeviceRefused("invalid_input", fields=["device_kind"])
    return raw


def add(
    store: Store,
    config: AppConfig,
    holder: Holder,
    *,
    name: str | None,
    kind: str,
    via: str,
    client: Client | None = None,
    via_device: DeviceId | None = None,
    now: datetime | None = None,
) -> tuple[Device, str]:
    """A new device in the open transaction (the caller commits). The key is returned once and never stored. The name
    the app sent, else the model (iOS no longer gives the device's own name, G11), else "iPhone"."""
    if len(store.devices_of(holder.id)) >= config.max_devices:
        raise DeviceRefused("too_many_devices", max=config.max_devices)
    token = tokens.make_secret(config.token_prefix, config.token_bytes)
    label = _printable(name)[: config.name_max] or (client.model if client and client.model else "") or "iPhone"
    device = store.add_device(
        NewDevice(
            account_id=holder.id,
            name=label,
            kind=kind,
            token_hash=tokens.digest(token),
            prefix=token[: len(config.token_prefix) + 4],
            via=via,
            created_at=now or utcnow(),
            model=client.model if client else None,
            system=client.system if client else None,
            app_version=client.version if client else None,
            via_device=via_device,
        )
    )
    return device, token


def _idle(config: AppConfig, device: Device, now: datetime) -> bool:
    last = device.last_seen_at or device.created_at
    return last is not None and now - last > timedelta(days=config.idle_days)


def authenticate(
    store: Store, config: AppConfig, token: str | None, *, client: Client | None = None, now: datetime | None = None
) -> Caller:
    """The device behind a key, else ``DeviceRefused`` (G12): ``device_disconnected`` (no such device, disconnected,
    365 days unused, its account gone for good), ``account_blocked`` (blocked or deleted, the device rests),
    ``second_factor_required``, ``app_disabled`` (the operator's switch; the device stays). Notes "last seen" at most
    once a minute, and with it what ``X-Nex-App`` says (model, system, version)."""
    now = now or utcnow()
    if not tokens.plausible(token, config.prefixes):
        raise DeviceRefused("device_disconnected")
    hashed = tokens.digest(token or "")
    device = store.device_by_hash(hashed)
    if device is None:
        gone = getattr(store, "gone_account", None)
        account = gone(hashed) if gone is not None else None
        if account is not None:
            holder = store.holder(account)
            if holder is not None and holder.out:
                raise DeviceRefused("account_blocked")
        raise DeviceRefused("device_disconnected")
    holder = store.holder(device.account_id)
    if holder is None:
        raise DeviceRefused("device_disconnected")
    if holder.out:
        raise DeviceRefused("account_blocked")
    if _idle(config, device, now):
        store.remove_device(device.id)
        store.commit()
        raise DeviceRefused("device_disconnected")
    if holder.factor_owed:
        raise DeviceRefused("second_factor_required")
    if not store.switch(SWITCH_APP):
        raise DeviceRefused("app_disabled")
    if device.last_seen_at is None or now - device.last_seen_at >= config.seen_every:
        store.touch(device.id, now)
        device.last_seen_at = now
        if client is not None and (client.model, client.system, client.version) != (
            device.model,
            device.system,
            device.app_version,
        ):
            device = store.change_device(
                device.id, DeviceChange(model=client.model, system=client.system, app_version=client.version)
            )
            device.last_seen_at = now
        store.commit()
    return Caller(device=device, holder=holder)


def _own(store: Store, account_id: AccountId, device_id: DeviceId) -> Device:
    device = store.device(device_id)
    if device is None or str(device.account_id) != str(account_id):
        raise DeviceRefused("not_found")
    return device


def listing(store: Store, config: AppConfig, account_id: AccountId, this: DeviceId | None = None) -> list[dict]:
    return [entry(device, this) for device in store.devices_of(account_id)]


def rename(store: Store, config: AppConfig, account_id: AccountId, device_id: DeviceId, name: str | None) -> Device:
    _own(store, account_id, device_id)
    changed = store.change_device(device_id, DeviceChange(name=valid_name(config, name)))
    store.commit()
    return changed


def disconnect(store: Store, config: AppConfig, account_id: AccountId, device_id: DeviceId) -> None:
    """The device has no access from this moment on and gets no more notifications; another account's: 404."""
    _own(store, account_id, device_id)
    store.remove_device(device_id)
    store.commit()


def disconnect_all(store: Store, config: AppConfig, account_id: AccountId) -> int:
    """Every device of the account; browsers, API keys and calendar programs stay."""
    found = store.devices_of(account_id)
    for device in found:
        store.remove_device(device.id)
    store.commit()
    return len(found)


def of_account(store: Store, config: AppConfig, account_id: AccountId) -> dict[str, Any]:
    """What the operator sees of an account (G28): how many, which kind and model, last seen; never names or more."""
    found = store.devices_of(account_id)
    return {
        "count": len(found),
        "devices": [
            {"kind": device.kind or DEVICE_KINDS[0], "model": device.model, "last_seen_at": iso(device.last_seen_at)}
            for device in found
        ],
    }


def sweep(store: Store, config: AppConfig, now: datetime | None = None) -> int:
    """The daily run: every device unused for ``idle_days`` is disconnected (G27). Returns how many."""
    now = now or utcnow()
    before = now - timedelta(days=config.idle_days)
    found = [device for device in store.idle_devices(before) if _idle(config, device, now)]
    for device in found:
        store.remove_device(device.id)
    store.commit()
    return len(found)
