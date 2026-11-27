"""nexpaper's side of the shared module ``vendor/nexgeraete`` (geraete 0.1.1): its ``AppConfig`` and the ``Store`` over
``devices`` and ``pairings``.

The module pairs, lists, renames and disconnects devices the same in every nex app, knows a device again by its key and
sends notifications through the relay; the rows stay where nexpaper wrote them since 1.3.0: ``devices`` (``uid`` as the
module's id, ``npd_``, the SHA-256 hex of the whole token, ``revoked_at`` for a disconnected one, which the store never
hands out) and ``pairings`` (``kind = qr`` for a QR code and its code, ``kind = connect`` for the one-time code of the
sign-in in the browser; OAuth's codes stay nexpaper's own). Every device paired so far keeps working, and so do the
published iPhone app's ways under ``/api/v1`` (``routers/devices.py``, ``routers/pairing.py``), which call the module in
their old shapes.

nexpaper's own: a 12-letter code valid for five minutes (on the old ways one waiting at a time, a new one ends the one
before), the QR link ``nexpaper://pair?server=…&code=…`` the published app reads (G58), the names ``device`` (brought
in by another device, the module's ``icloud``) and ``qr`` (the code, the module's ``code``) in the old answers, the
mail "New sign-in" after a new device (G29, G50, ``on_paired``), the daily ``sweep`` (G27) and the notice of a new
version to the operators' devices that want it (G56: ``update_wanted`` and ``newer`` for ``nexupdates``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .. import __version__, clock
from ..db import SessionLocal
from ..models import OPERATOR, Account, Device, Pairing
from ..vendor import nexgeraete
from ..vendor.nexgeraete import AppConfig
from ..vendor.nexgeraete.model import ConnectCode, DeviceChange, Holder, NewDevice, NewPairing, PushState
from ..vendor.nexgeraete.model import Device as ModuleDevice
from ..vendor.nexgeraete.model import Pairing as ModulePairing
from . import settings_service

logger = logging.getLogger("nexpaper.auth")

#: The published iPhone app (nexpaper-ios) in the App Store.
APP_STORE_URL = "https://apps.apple.com/app/nexpaper/id6824032969"

#: nexpaper's devices: ``npd_`` and 32 random bytes as before, a code of twelve letters for five minutes. nexpaper sends
#: no notifications through the relay of its own yet (it has Web Push for browsers), so it has no kinds; the module's
#: ``update`` and ``security`` reach only apps that say they understand them. The published app speaks ``/api/v1`` and
#: never the module's old forms; ``nex`` is the form of ``/api/app/1``.
CONFIG = AppConfig(
    app="nexpaper",
    scheme="nexpaper",
    token_prefix="npd_",
    form=nexgeraete.FORM_NEX,
    code_length=12,
    pairing_minutes=5,
    # G57: up to five QR codes may wait on the module's route (several windows at once); nexpaper's old way ends the one
    # before with a new one (``pairing.start(replace=True)``: ``/api/v1/devices/pairing``).
    open_pairings=5,
    max_devices=30,
    app_store_url=APP_STORE_URL,
    # G58: the QR link is ``nexpaper://pair?server=…&code=…`` as nexpaper-ios up to 1.3 reads it (and trades the code at
    # ``POST /api/v1/devices/pair``), then ``address``, ``pairing`` and ``secret`` for an app built on NexKonto.
    link_form="pair",
    # A device is known by its ``uid`` (32 hex characters), as ``/api/v1/devices`` has always named it.
    device_id=str,
)

#: The operator's switches and nexpaper's settings behind them (the card "Interfaces" under Server › Connections, the
#: shared key module's): both on from the start.
SWITCH_SETTINGS = {nexgeraete.SWITCH_APP: "app_enabled", nexgeraete.SWITCH_PAIRING: "app_pairing_allowed"}

#: Pairing codes of the module (``qr``) and the one-time codes of the sign-in in the browser.
KIND_QR = "qr"
KIND_CONNECT = "connect"
#: What the older versions wrote into ``devices.via`` for a device brought in over iCloud.
OLD_SIBLING = "device"

#: What posts to the relay; the contract tests put a recorder here (``tests/nexgeraete_adapter.py``).
SEND: Callable[[str, dict[str, Any]], int] | None = None


def send(url: str, body: dict[str, Any]) -> int:
    return (SEND or nexgeraete.push.post)(url, body)


def now() -> datetime:
    """nexpaper's clock, looked up at each call (tests move it)."""
    return clock.now()


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=clock.now().tzinfo)


def _language(db: Session, account: Account) -> str:
    from .kontenpost import language_for

    found = language_for(db, account)
    return found if found in nexgeraete.config.LANGUAGES else "en"


def module_via(stored: str | None) -> str | None:
    """The way in as the module names it: a device brought in by another one of the account is ``icloud``."""
    return nexgeraete.VIA_ICLOUD if stored == OLD_SIBLING else stored


def old_via(stored: str | None) -> str:
    """The way in as ``/api/v1`` named it before the module: ``device`` (iCloud) and ``qr`` (the code)."""
    if stored == nexgeraete.VIA_ICLOUD:
        return OLD_SIBLING
    if stored == nexgeraete.VIA_CODE:
        return KIND_QR
    return stored or "token"


def is_out(account: Account, moment: datetime | None = None) -> bool:
    """Blocked, deleted with its days to bring it back, or locked for a while after wrong passwords: its devices rest
    (G26) and work again afterwards."""
    moment = moment or clock.now()
    locked = account.locked_until is not None and _aware(account.locked_until) > moment  # type: ignore[operator]
    return account.blocked_at is not None or account.deleted_at is not None or bool(locked)


class GeraeteStore:
    """The module's ``Store`` over one session (one transaction per request)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- devices -----------------------------------------------------------------------------------------------

    @staticmethod
    def _device(row: Device) -> ModuleDevice:
        push = None
        if row.push_ticket and row.push_key:
            understands = row.push_understands
            push = PushState(row.push_ticket, row.push_key,
                             tuple(str(kind) for kind in understands) if isinstance(understands, list) else None)
        return ModuleDevice(
            id=row.uid,
            account_id=row.account_id,
            name=row.name,
            kind=row.kind,
            model=row.model,
            system=row.system,
            app_version=row.app_version,
            via=module_via(row.via),
            created_at=_aware(row.created_at),
            last_seen_at=_aware(row.last_used_at),
            push=push,
            kinds=dict(row.push_kinds) if isinstance(row.push_kinds, dict) else {},
        )

    def row(self, device_id: Any) -> Device | None:
        """The live row of a device (by its uid), or None."""
        return self.db.scalar(select(Device).where(Device.uid == str(device_id), Device.revoked_at.is_(None)))

    def devices_of(self, account_id: Any) -> list[ModuleDevice]:
        rows = self.db.scalars(select(Device).where(Device.account_id == int(account_id), Device.revoked_at.is_(None))
                               .order_by(Device.created_at.desc(), Device.id.desc()))
        return [self._device(row) for row in rows]

    def device(self, device_id: Any) -> ModuleDevice | None:
        row = self.row(device_id)
        return self._device(row) if row is not None else None

    def device_by_hash(self, token_hash: str) -> ModuleDevice | None:
        row = self.db.scalar(select(Device).where(Device.token_hash == token_hash, Device.revoked_at.is_(None)))
        return self._device(row) if row is not None else None

    def add_device(self, new: NewDevice) -> ModuleDevice:
        row = Device(account_id=int(new.account_id), name=new.name[:80], token_hash=new.token_hash,
                     prefix=new.prefix[:16], created_at=new.created_at, via=new.via, kind=new.kind,
                     model=new.model[:80] if new.model else None, system=new.system[:80] if new.system else None,
                     app_version=new.app_version[:40] if new.app_version else None)
        self.db.add(row)
        self.db.flush()
        return self._device(row)

    def change_device(self, device_id: Any, change: DeviceChange) -> ModuleDevice:
        row = self.row(device_id)
        assert row is not None
        if change.name is not None:
            row.name = change.name[:80]
        if change.model is not None:
            row.model = change.model[:80]
        if change.system is not None:
            row.system = change.system[:80]
        if change.app_version is not None:
            row.app_version = change.app_version[:40]
        self.db.flush()
        return self._device(row)

    def remove_device(self, device_id: Any) -> None:
        """Disconnected as nexpaper always did: the row stays with ``revoked_at`` (the token's hash opens nothing any
        more), and its notifications go."""
        self.db.execute(update(Device).where(Device.uid == str(device_id), Device.revoked_at.is_(None))
                        .values(revoked_at=clock.now(), push_ticket=None, push_key=None, push_understands=None))
        self.db.flush()

    def touch(self, device_id: Any, when: datetime) -> None:
        self.db.execute(update(Device).where(Device.uid == str(device_id)).values(last_used_at=when))

    def idle_devices(self, before: datetime) -> list[ModuleDevice]:
        rows = self.db.scalars(select(Device).where(
            Device.revoked_at.is_(None), func.coalesce(Device.last_used_at, Device.created_at) < before))
        return [self._device(row) for row in rows]

    def set_push(self, device_id: Any, state: PushState | None) -> None:
        row = self.row(device_id)
        if row is None:
            return
        row.push_ticket = state.ticket if state else None
        row.push_key = state.key if state else None
        row.push_understands = list(state.understands) if state and state.understands is not None else None
        self.db.flush()

    def set_kinds(self, device_id: Any, kinds: dict[str, bool]) -> None:
        row = self.row(device_id)
        if row is not None:
            row.push_kinds = dict(kinds)
            self.db.flush()

    # --- accounts ------------------------------------------------------------------------------------------------

    def holder(self, account_id: Any) -> Holder | None:
        from . import totp

        row = self.db.get(Account, int(account_id))
        if row is None:
            return None
        return Holder(
            id=row.id,
            name=row.display_name or row.name,
            login=row.name,
            email=row.email or "",
            avatar=row.avatar_at.isoformat() if row.avatar_at else "",
            operator=row.role == OPERATOR,
            out=is_out(row),
            language=_language(self.db, row),
            factor_owed=totp.setup_required(self.db, row),
        )

    def operators(self) -> list[Any]:
        return list(self.db.scalars(select(Account.id).where(
            Account.role == OPERATOR, Account.blocked_at.is_(None), Account.deleted_at.is_(None)).order_by(Account.id)))

    # --- pairings and codes --------------------------------------------------------------------------------------

    def _lock(self) -> None:
        """Taking a code reads and then writes: the write lock first, so that of two at the same moment one waits and
        then finds the code used (``changes.write_lock``)."""
        from .changes import write_lock

        write_lock(self.db)

    @staticmethod
    def _id(row: Pairing) -> str:
        # A code of before the module (five minutes at most) has no uid; it is known by its row.
        return row.uid or f"legacy-{row.id}"

    def _pairing_row(self, pairing_id: str) -> Pairing | None:
        if pairing_id.startswith("legacy-") and pairing_id[7:].isdigit():
            row = self.db.get(Pairing, int(pairing_id[7:]))
            return row if row is not None and row.uid is None and row.kind == KIND_QR else None
        return self.db.scalar(select(Pairing).where(Pairing.uid == pairing_id, Pairing.kind == KIND_QR))

    def _pairing(self, row: Pairing | None) -> ModulePairing | None:
        if row is None:
            return None
        device = self.db.get(Device, row.device_id) if row.device_id is not None else None
        return ModulePairing(
            id=self._id(row),
            account_id=row.account_id,
            secret_hash=row.secret_hash or "",
            code_hash=row.code_hash,
            created_at=_aware(row.created_at),  # type: ignore[arg-type]
            expires_at=_aware(row.expires_at),  # type: ignore[arg-type]
            used_at=_aware(row.used_at),
            device_id=device.uid if device is not None else None,
        )

    def add_pairing(self, new: NewPairing) -> ModulePairing:
        row = Pairing(account_id=int(new.account_id), kind=KIND_QR, code_hash=new.code_hash, created_at=new.created_at,
                      expires_at=new.expires_at, uid=new.id[:32], secret_hash=new.secret_hash)
        self.db.add(row)
        self.db.flush()
        found = self._pairing(row)
        assert found is not None
        return found

    def pairing(self, pairing_id: str) -> ModulePairing | None:
        self._lock()
        return self._pairing(self._pairing_row(pairing_id))

    def pairing_by_code(self, code_hash: str) -> ModulePairing | None:
        self._lock()
        return self._pairing(self.db.scalar(select(Pairing).where(Pairing.code_hash == code_hash,
                                                                  Pairing.kind == KIND_QR)))

    def open_pairings(self, account_id: Any, moment: datetime) -> list[ModulePairing]:
        rows = self.db.scalars(select(Pairing).where(Pairing.account_id == int(account_id), Pairing.kind == KIND_QR,
                                                     Pairing.used_at.is_(None), Pairing.expires_at > moment))
        return [found for found in (self._pairing(row) for row in rows) if found is not None]

    def use_pairing(self, pairing_id: str, device_id: Any, when: datetime) -> bool:
        row = self._pairing_row(pairing_id)
        if row is None:
            return False
        device = self.row(device_id) if device_id is not None else None
        hit = self.db.execute(
            update(Pairing).where(Pairing.id == row.id, Pairing.used_at.is_(None), Pairing.expires_at > when)
            .values(used_at=when, device_id=device.id if device is not None else None)
        ).rowcount  # type: ignore[attr-defined]
        self.db.flush()
        return int(hit or 0) == 1

    def remove_pairing(self, pairing_id: str) -> None:
        row = self._pairing_row(pairing_id)
        if row is not None:
            self.db.execute(delete(Pairing).where(Pairing.id == row.id))
            self.db.flush()

    def add_connect_code(self, new: ConnectCode) -> None:
        self.db.add(Pairing(account_id=int(new.account_id), kind=KIND_CONNECT, code_hash=new.code_hash,
                            created_at=new.created_at, expires_at=new.expires_at, state=new.state[:200],
                            challenge=new.challenge or ""))
        self.db.flush()

    def take_connect_code(self, code_hash: str, when: datetime) -> ConnectCode | None:
        self._lock()
        hit = self.db.execute(
            update(Pairing).where(Pairing.code_hash == code_hash, Pairing.kind == KIND_CONNECT,
                                  Pairing.used_at.is_(None), Pairing.expires_at > when).values(used_at=when)
        ).rowcount  # type: ignore[attr-defined]
        if int(hit or 0) != 1:
            return None
        row = self.db.scalar(select(Pairing).where(Pairing.code_hash == code_hash))
        assert row is not None
        return ConnectCode(code_hash=row.code_hash, account_id=row.account_id, state=row.state or "",
                           challenge=row.challenge or None, created_at=_aware(row.created_at),  # type: ignore[arg-type]
                           expires_at=_aware(row.expires_at))  # type: ignore[arg-type]

    # --- settings ------------------------------------------------------------------------------------------------

    def switch(self, name: str) -> bool:
        return bool(settings_service.get(self.db, SWITCH_SETTINGS[name]))

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()


def address(request: Any) -> str:
    """The public address the operator set (it goes before the browser's in the QR code, G47); empty without one."""
    with SessionLocal() as db:
        return settings_service.public_url(db)


def store() -> Iterator[GeraeteStore]:
    """The dependency of the module's routes: one session per request."""
    with SessionLocal() as db:
        yield GeraeteStore(db)


# --- After a new device (G29) ---------------------------------------------------------------------------------------


def on_paired(holder: Holder, device: ModuleDevice) -> None:
    """The mail "New sign-in" after every new device, as after a sign-in from a browser nexpaper does not know: to an
    address that counts, unless the person switched the notice off; in the background. It names the device
    (``nexgeraete.notices.letter``, G50: „„Kims iPhone“ (iPhone 16 Pro)“) and the moment, never a network."""
    from . import notices

    notices.later(_mail_paired, int(holder.id), device, clock.now())


def paired_letter(db: Session, account: Account, device: ModuleDevice, moment: datetime) -> Any:
    """The letter "New sign-in" for a new device (G50): the shared post module's, through ``nexgeraete.notices.letter``
    (``from_account_mail`` reads a User-Agent and names browsers only), with the button to the page Security under the
    public address only, in the person's language and time zone. ``ValueError``/``MailError`` for an address the post
    module refuses."""
    from ..vendor import nexkonten, nexpost
    from . import kontenpost, notices, timezones

    assert account.email
    base = settings_service.public_url(db)
    mail = nexkonten.Mail(kind=nexkonten.MAIL_NEW_SIGN_IN, to=account.email.strip(), account_id=account.id,
                          username=account.name, display_name=account.display_name or "", at=moment)
    return nexgeraete.notices.letter(nexpost.letters, mail, device, language=kontenpost.language_for(db, account),
                                     link=f"{base}{notices.SECURITY_PATH}" if base else "",
                                     time_zone=timezones.zone_of(account))


def _mail_paired(account_id: int, device: ModuleDevice, moment: datetime) -> None:
    from ..vendor import nexpost
    from . import post_store

    with SessionLocal() as db:
        account = db.get(Account, account_id)
        if account is None or not post_store.configured(db) or not account.email_counts or not account.email:
            return
        profile = account.profile if isinstance(account.profile, dict) else {}
        if profile.get("notify_login") is False:
            return
        try:
            letter = paired_letter(db, account, device, moment)
        except Exception:  # noqa: BLE001 (an address the post module refuses: no mail, the device stands)
            logger.warning("New device not mailed name=%s", account.name)
            return
        try:
            post_store.send_now(db, letter)
        except nexpost.MailError:
            post_store.queue(db, letter)
            logger.warning("New device notice waits in the outbox name=%s", account.name)
            return
        logger.info("New device mailed name=%s", account.name)


def paired_hook(holder: Holder, device: ModuleDevice) -> None:
    """What the module's routes call after a pairing (looked up at each call: the contract tests listen)."""
    on_paired(holder, device)


def after_pairing(db: Session, done: nexgeraete.Paired) -> None:
    """What the module's routes do after a pairing (``api.app_router``), for nexpaper's old ways under ``/api/v1``:
    the mail, then ``security`` to the account's other devices. Neither changes the result."""
    try:
        paired_hook(done.holder, done.device)
    except Exception as error:  # noqa: BLE001
        logger.warning("After pairing, the mail failed: %s", type(error).__name__)
    try:
        nexgeraete.notices.paired(GeraeteStore(db), CONFIG, done, send=send)
    except Exception as error:  # noqa: BLE001
        logger.warning("After pairing, the notice failed: %s", type(error).__name__)


# --- Daily and once per version --------------------------------------------------------------------------------------


def sweep() -> int:
    """G27: every device not used for 365 days is disconnected (the housekeeping calls it once a day)."""
    with SessionLocal() as db:
        gone = nexgeraete.devices.sweep(GeraeteStore(db), CONFIG, clock.now())
    if gone:
        logger.info("Devices unused for a year disconnected count=%s", gone)
    return gone


def update_wanted() -> bool:
    """G56, ``nexupdates`` ``devices_want``: a device of an operator understands and wants the kind ``update``; then
    (and only with the update check allowed) the background looks at most once a day."""
    with SessionLocal() as db:
        return nexgeraete.notices.update_wanted(GeraeteStore(db), CONFIG)


def newer(version: str) -> None:
    """G56, ``nexupdates`` ``on_devices``: the operators' devices that want it hear of the new version once, with the
    link to what is new."""
    shown = version.strip().removeprefix("v")
    with SessionLocal() as db:
        base = settings_service.public_url(db)
        nexgeraete.notices.newer(GeraeteStore(db), CONFIG, shown, __version__,
                                 f"{base}/settings/about" if base else "", send=send)
