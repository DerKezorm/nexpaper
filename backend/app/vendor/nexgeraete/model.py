"""What the module and the app hand each other: a device as the module sees it (never its key, never its hash in an
answer), the account behind it, pairings and one-time codes, and the ``Store``: the app's tables behind a few calls.
Every app keeps its tables and the form of its rows (nexnotes ``api_tokens kind=device`` and ``push_devices``,
nextime/nextasks/nexlore ``app_devices``, nexmail ``sitzung art=geraet``, nexpaper ``devices``); the store translates.
Times are aware datetimes in UTC."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

AccountId = int | str
DeviceId = int | str


@dataclass(frozen=True)
class PushState:
    """Where a device's notifications go: the relay's ticket, the device's public X25519 key (base64), and the kinds
    it says it understands (``None``: an app that says nothing, it gets ``AppConfig.legacy_kinds``)."""

    ticket: str
    key: str
    understands: tuple[str, ...] | None = None


@dataclass
class Device:
    """One paired iPhone, iPad or Mac as the app holds it."""

    id: DeviceId
    account_id: AccountId
    name: str
    #: ``ios``, ``ipados``, ``mac`` (``DEVICE_KINDS``); ``None`` in apps that did not keep it.
    kind: str | None = None
    #: From ``X-Nex-App``: "iPhone 16 Pro", "iOS 18.1", the app's version. ``None`` where nothing came.
    model: str | None = None
    system: str | None = None
    app_version: str | None = None
    #: ``qr``, ``code``, ``browser``, ``icloud`` or what an older version wrote; ``None`` where unknown.
    via: str | None = None
    created_at: datetime | None = None
    last_seen_at: datetime | None = None
    push: PushState | None = None
    #: The kinds switched on or off on this device; a kind missing here has its ``default_on``.
    kinds: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class Holder:
    """The account behind a device."""

    id: AccountId
    #: The name others see (display name, else the username).
    name: str
    login: str = ""
    email: str = ""
    #: What the app answers as ``avatar`` (nexnotes: when the picture changed, ISO; empty without one).
    avatar: str = ""
    operator: bool = False
    #: Blocked, or deleted and still to be restored: its devices rest (``401 account_blocked``, no push; G26).
    out: bool = False
    #: ``de``, ``en`` or ``fr``.
    language: str = "en"
    #: The operator requires a second factor the account has not set up: its devices rest until it has.
    factor_owed: bool = False


@dataclass(frozen=True)
class NewDevice:
    """A device for the app to store. ``token_hash`` is the SHA-256 of the whole key in hex, as every app stores it;
    ``prefix`` is the visible start (prefix and four characters) for apps that keep one."""

    account_id: AccountId
    name: str
    kind: str
    token_hash: str
    prefix: str
    via: str
    created_at: datetime
    model: str | None = None
    system: str | None = None
    app_version: str | None = None
    #: The device that brought this one in over iCloud (nexnotes ``via_token_id``), or ``None``.
    via_device: DeviceId | None = None


@dataclass(frozen=True)
class DeviceChange:
    """``None`` leaves a part as it is."""

    name: str | None = None
    model: str | None = None
    system: str | None = None
    app_version: str | None = None


@dataclass(frozen=True)
class Pairing:
    """A QR code and the code beside it: ten minutes, one device."""

    id: str
    account_id: AccountId
    secret_hash: str
    code_hash: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None
    device_id: DeviceId | None = None


@dataclass(frozen=True)
class NewPairing:
    id: str
    account_id: AccountId
    secret_hash: str
    code_hash: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ConnectCode:
    """The one-time code the sign-in in the browser hands to the app (five minutes, once), with the app's ``state``
    and, where the app sent one, its PKCE ``challenge`` (S256)."""

    code_hash: str
    account_id: AccountId
    state: str
    challenge: str | None
    created_at: datetime
    expires_at: datetime


@runtime_checkable
class Store(Protocol):
    """The app's tables. One transaction per request: the module calls ``commit()`` once a result stands."""

    def devices_of(self, account_id: AccountId) -> list[Device]:
        """The account's devices, newest first."""
        ...

    def device(self, device_id: DeviceId) -> Device | None: ...

    def device_by_hash(self, token_hash: str) -> Device | None:
        """The device whose stored hash is ``token_hash`` (SHA-256 hex of the presented key)."""
        ...

    def add_device(self, new: NewDevice) -> Device:
        """Store a device as the app stores devices (its table, its columns)."""
        ...

    def change_device(self, device_id: DeviceId, change: DeviceChange) -> Device: ...

    def remove_device(self, device_id: DeviceId) -> None:
        """Disconnect: the key and the push ticket go."""
        ...

    def touch(self, device_id: DeviceId, when: datetime) -> None:
        """Note ``last seen``."""
        ...

    def idle_devices(self, before: datetime) -> list[Device]:
        """Every device of every account last seen before ``before`` (never seen: made before it), for ``sweep``."""
        ...

    def holder(self, account_id: AccountId) -> Holder | None:
        """The account; ``None`` when it is gone for good."""
        ...

    def operators(self) -> list[AccountId]:
        """The accounts that run the server (for ``update``)."""
        ...

    def add_pairing(self, new: NewPairing) -> Pairing: ...

    def pairing(self, pairing_id: str) -> Pairing | None: ...

    def pairing_by_code(self, code_hash: str) -> Pairing | None: ...

    def open_pairings(self, account_id: AccountId, now: datetime) -> list[Pairing]:
        """The account's pairings neither used nor expired."""
        ...

    def use_pairing(self, pairing_id: str, device_id: DeviceId | None, when: datetime) -> bool:
        """Mark it used by ``device_id`` only if it is still open (``used_at`` empty, ``expires_at`` after ``when``),
        in one conditional UPDATE: of two pickups at the same moment exactly one gets ``True``."""
        ...

    def remove_pairing(self, pairing_id: str) -> None: ...

    def add_connect_code(self, new: ConnectCode) -> None: ...

    def take_connect_code(self, code_hash: str, when: datetime) -> ConnectCode | None:
        """Use the code once, in one conditional UPDATE (unused, not expired), and return it; else ``None``."""
        ...

    def set_push(self, device_id: DeviceId, state: PushState | None) -> None: ...

    def set_kinds(self, device_id: DeviceId, kinds: dict[str, bool]) -> None: ...

    def switch(self, name: str) -> bool:
        """The operator's switch ``app`` or ``pairing`` under the app's own setting and default (on)."""
        ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class GoneStore(Protocol):
    """Optional (nexnotes, nextime): the hashes of keys an earlier version deleted with a block or deletion of their
    account (``app_gone_devices``). Such a key hears ``account_blocked`` while its account is out, else
    ``device_disconnected``; since G26 no key is deleted for a block any more."""

    def gone_account(self, token_hash: str) -> AccountId | None: ...
