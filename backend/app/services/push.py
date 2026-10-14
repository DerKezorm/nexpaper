"""Web Push, where it goes: the devices of each person, and sending to them.

* **The address of a device comes from outside.** The browser hands it over, so whoever holds a session could hand
  over any address and make the server send a request there. Only https, only the default port, never an address
  literal, and only to a known push service (``KNOWN_HOSTS``, plus what the operator adds); the name is resolved
  once per request, every address it gives must lie in the public internet, and the connection goes exactly there
  (``services/outbound.py``). No redirect is followed, the answer is read up to a few kilobytes, each request has a
  deadline.
* **What a device handed over is sealed** with the server's secret: the address is a key in itself, whoever knows
  it may send to the device. Only a keyed hash of it stays in the clear, so that signing up twice keeps one device.
* **A device that left is removed**: the push service answers 404 or 410 for an address that no longer exists.
  Anything else (429, 500, no answer) leaves it; the next message tries again.
* **Of a document, a message names the title at most.** What is sent is written by the server (a notice, a probe).
  The one exception, on purpose: a reminder of a deadline (``services/reminders.py``) names the kind of deadline, its
  day and the title of the document ("Kündigen bis Mi, 30.09.: Handyvertrag"), because a reminder that does not say
  what it is about is no help. Never an amount, the text, notes or tags; the push service and the lock screen see the
  title.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
import unicodedata
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..errors import error
from ..models import PushDevice, utcnow
from ..security import decrypt_secret, encrypt_secret, server_key
from . import outbound, settings_service, webpush

logger = logging.getLogger("nexpaper.push")

#: The push services of the browsers people use: Chrome and the browsers built on it (Google), Firefox (Mozilla),
#: Safari on Mac, iPhone and iPad (Apple), Edge and Windows (Microsoft). A device's address must lie on one of these
#: hosts or below it; the operator may add more (``push_hosts``).
KNOWN_HOSTS = ("fcm.googleapis.com", "push.services.mozilla.com", "web.push.apple.com", "notify.windows.com")
ENDPOINT_MAX = 1000
KEY_MAX = 200
NAME_MAX = 60
DEVICES_MAX = 10
HOSTS_MAX = 20
HOST_MAX = 253
CONTACT_MAX = 200
#: One message: the whole request, the answer included; the connection itself.
SECONDS = 10.0
CONNECT_SECONDS = 5.0
#: A push service answers with nothing or a line of JSON.
ANSWER_MAX = 4096
#: Messages on their way at once, on the whole server.
AT_ONCE = 8

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_MAIL = re.compile(r"^mailto:[^@\s:/?#]{1,64}@[a-z0-9.-]{1,190}\.[a-z]{2,63}$", re.IGNORECASE)

#: The English sentences for whoever uses the API directly; the interface has its own.
MESSAGES = {
    "push_endpoint_invalid": "This is not the address of a push service.",
    "push_endpoint_refused": "This address is never reached.",
    "push_service_unknown": "This push service is not one nexpaper sends to.",
    "push_unreachable": "The server cannot reach this push service.",
    "push_keys_invalid": "The keys of this device are not valid.",
    "push_too_many_devices": "Too many devices. Remove one first.",
    "push_name_invalid": "Use a shorter name without control characters.",
    "push_no_devices": "No device is signed up yet.",
    "push_contact_invalid": "Give an address starting with mailto: or https://.",
    "push_host_invalid": "This is not a host name.",
    "push_too_many_hosts": "Too many push services.",
}


def fail(code: str, status: int = 422, **values: Any) -> HTTPException:
    return error(code, MESSAGES.get(code, "Web Push did not work."), status, **values)


# --- Where a message may go -----------------------------------------------------------------------------------------


def normal_name(host: str) -> str:
    """A host name as it is compared, in lower case and as ASCII. ``ValueError`` for an address literal or anything
    that is not a name."""
    host = (host or "").strip().lower().rstrip(".")
    if host.startswith("["):
        raise ValueError("an address literal")
    try:
        outbound.ip_of(host)
    except ValueError:
        pass
    else:
        raise ValueError("an address literal")
    try:
        name = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("not a name") from exc
    if not name or len(name) > HOST_MAX or "." not in name or not all(_LABEL.match(part) for part in name.split(".")):
        raise ValueError("not a name")
    # A name of digits alone in its last part reads as an address to some resolvers ("10.0.0.1." or "0x7f.1").
    if name.rsplit(".", 1)[-1].isdigit():
        raise ValueError("not a name")
    return name


def hosts_of(values: dict[str, Any]) -> tuple[str, ...]:
    """The known push services and the ones the operator added."""
    added: list[str] = []
    for entry in values.get("push_hosts") or []:
        try:
            added.append(normal_name(str(entry)))
        except ValueError:
            continue
    return KNOWN_HOSTS + tuple(added)


def service_of(host: str, hosts: tuple[str, ...]) -> str | None:
    """Which allowed push service a host belongs to: the host itself or a name below it."""
    for entry in hosts:
        if host == entry or host.endswith("." + entry):
            return entry
    return None


def check_endpoint(db: Session, endpoint: Any) -> tuple[str, str]:
    """The address of a device as the browser handed it over, checked: https, the default port, a name (never an
    address), on a push service nexpaper sends to. Gives the address and its push service; raises ``fail`` else."""
    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > ENDPOINT_MAX:
        raise fail("push_endpoint_invalid")
    if any(ord(char) <= 32 or ord(char) == 127 for char in endpoint):
        raise fail("push_endpoint_invalid")
    try:
        # A broken bracket ("https://[::1"), a name that changes under NFKC: Python refuses them with ValueError.
        parts = urlsplit(endpoint)
        port = parts.port
        hostname = parts.hostname or ""
    except ValueError as exc:
        raise fail("push_endpoint_invalid") from exc
    if parts.scheme.lower() != "https" or parts.username is not None or parts.password is not None or parts.fragment:
        raise fail("push_endpoint_invalid")
    if port not in (None, 443):
        raise fail("push_endpoint_invalid")
    try:
        outbound.ip_of(hostname.strip("[]"))
    except ValueError:
        pass
    else:
        raise fail("push_endpoint_refused")
    try:
        host = normal_name(hostname)
    except ValueError as exc:
        raise fail("push_endpoint_invalid") from exc
    service = service_of(host, hosts_of(settings_service.get_all(db)))
    if service is None:
        raise fail("push_service_unknown")
    # Kept and used as checked: with the name in the ASCII form it was compared in. A name written in full-width
    # letters was taken for the push service it reads as, and sending to it then broke for every device.
    checked = urlunsplit(("https", host, parts.path, parts.query, ""))
    if not checked.isascii():
        raise fail("push_endpoint_invalid")
    return checked, service


def _public_only(ip: outbound.IP) -> None:
    """A push service lies in the public internet; a name that leads into an own network is turned down."""
    if not outbound.public(str(ip)):
        raise outbound.Refused("not public")


#: Resolves a name to its addresses; the tests put their own in.
resolver: Callable[[str, int], list[str]] = outbound.resolve
#: The way out; the tests put a stand-in of the push service here.
transport: httpx.BaseTransport | None = None
ticks: Callable[[], float] = time.monotonic


def _target(db: Session, endpoint: str) -> tuple[outbound.Target, str]:
    """The address checked against the list as it stands now, resolved once and pinned."""
    checked, service = check_endpoint(db, endpoint)
    try:
        return outbound.pin(checked, resolver, _public_only), service
    except outbound.Refused as exc:
        raise fail("push_endpoint_refused") from exc
    except outbound.Unreachable as exc:
        raise fail("push_unreachable", 502) from exc


# --- The devices of a person ----------------------------------------------------------------------------------------


@dataclass
class Device:
    uid: str
    endpoint: str
    p256dh: str
    auth: str
    name: str
    lang: str
    phone: bool
    created_at: datetime
    last_used_at: datetime | None


def _context(account_id: int, uid: str) -> str:
    return f"push-device:{account_id}:{uid}"


def _endpoint_key(endpoint: str) -> str:
    """A keyed hash of the address: the same browser twice is the same device, and the hash says nothing without
    the server's key."""
    key = hashlib.sha256(b"nexpaper|push-endpoint-key|" + server_key()).digest()
    return hmac.new(key, endpoint.encode("utf-8"), hashlib.sha256).hexdigest()


def clean_name(value: Any) -> str:
    """A device's name: spaces gathered, no control or invisible characters, at most ``NAME_MAX``; never empty."""
    if not isinstance(value, str):
        raise fail("push_name_invalid")
    if any(ord(char) < 32 or ord(char) == 127 or unicodedata.category(char) == "Cf" for char in value):
        raise fail("push_name_invalid")
    clean = " ".join(value.split())
    if not clean or len(clean) > NAME_MAX:
        raise fail("push_name_invalid")
    return clean


def _open(account_id: int, row: Any) -> Device | None:
    try:
        content = json.loads(decrypt_secret(row.content, _context(account_id, row.uid)))
    except ValueError:
        content = None
    if not isinstance(content, dict):
        logger.warning("A sealed push device did not open")
        return None
    return Device(uid=row.uid, endpoint=str(content.get("endpoint", "")), p256dh=str(content.get("p256dh", "")),
                  auth=str(content.get("auth", "")), name=str(content.get("name", "")),
                  lang=str(content.get("lang", "")), phone=content.get("phone") is True, created_at=row.created_at,
                  last_used_at=row.last_used_at)


def _seal(account_id: int, uid: str, device: dict[str, Any]) -> str:
    return encrypt_secret(json.dumps(device, ensure_ascii=False, separators=(",", ":")), _context(account_id, uid))


def devices_of(db: Session, account_id: int) -> list[Device]:
    rows = db.execute(select(PushDevice.uid, PushDevice.content, PushDevice.created_at, PushDevice.last_used_at)
                      .where(PushDevice.user_id == account_id).order_by(PushDevice.created_at, PushDevice.id)).all()
    return [device for device in (_open(account_id, row) for row in rows) if device is not None]


def view(device: Device) -> dict[str, Any]:
    """What the interface shows of a device: never its address or keys."""
    return {"id": device.uid, "name": device.name, "phone": device.phone, "since": device.created_at.isoformat(),
            "last": device.last_used_at.isoformat() if device.last_used_at else None}


def list_devices(db: Session, account_id: int) -> list[dict[str, Any]]:
    return [view(device) for device in devices_of(db, account_id)]


def has_devices(db: Session, account_id: int) -> bool:
    return db.scalar(select(func.count()).select_from(PushDevice).where(PushDevice.user_id == account_id)) != 0


def lookup(db: Session, account_id: int, endpoint: Any) -> str | None:
    """The id of the own device with this address, or None: so that a browser knows whether it is signed up."""
    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > ENDPOINT_MAX:
        return None
    return db.scalar(select(PushDevice.uid).where(PushDevice.user_id == account_id,
                                                  PushDevice.endpoint_key == _endpoint_key(endpoint)))


def add_device(db: Session, account_id: int, *, endpoint: Any, p256dh: Any, auth: Any, name: str,
               lang: str, phone: bool = False) -> tuple[dict[str, Any], bool]:
    """Signs a device up, or finds it again: the same address twice (a double tap, a second sign-up) stays one
    device, with the keys it has now. Gives the device and whether it is new."""
    checked, _service = check_endpoint(db, endpoint)
    if not isinstance(p256dh, str) or not isinstance(auth, str) or len(p256dh) > KEY_MAX or len(auth) > KEY_MAX:
        raise fail("push_keys_invalid")
    if not webpush.valid_keys(p256dh, auth):
        raise fail("push_keys_invalid")
    # The name leads where it was checked now, too: a push service of the list that a name leads into an own network
    # is refused at the door, not only when the first message goes.
    db.rollback()
    _target(db, checked)
    key = _endpoint_key(checked)
    content: dict[str, Any] = {"endpoint": checked, "p256dh": p256dh, "auth": auth, "name": clean_name(name),
                               "lang": lang[:16], "phone": bool(phone)}
    found = db.scalar(select(PushDevice).where(PushDevice.user_id == account_id, PushDevice.endpoint_key == key))
    if found is not None:
        current = _open(account_id, found)
        if current is not None:
            content["name"] = current.name
        found.content = _seal(account_id, found.uid, content)
        db.commit()
        device = _open(account_id, found)
        assert device is not None
        return view(device), False
    count = db.scalar(select(func.count()).select_from(PushDevice).where(PushDevice.user_id == account_id)) or 0
    if count >= DEVICES_MAX:
        raise fail("push_too_many_devices", 409, max=DEVICES_MAX)
    uid = secrets.token_hex(16)
    made = db.execute(sqlite_insert(PushDevice).values(
        uid=uid, user_id=account_id, endpoint_key=key, content=_seal(account_id, uid, content),
        created_at=utcnow().replace(microsecond=0), last_used_at=None,
    ).on_conflict_do_nothing(index_elements=[PushDevice.user_id, PushDevice.endpoint_key]))
    db.commit()
    row = db.scalar(select(PushDevice).where(PushDevice.user_id == account_id, PushDevice.endpoint_key == key))
    assert row is not None
    if made.rowcount:  # type: ignore[attr-defined]
        # Counted before and checked again after: of devices signed up at the same moment, the ones that came first
        # stay; one past the limit takes itself back out.
        first = list(db.scalars(select(PushDevice.id).where(PushDevice.user_id == account_id)
                                .order_by(PushDevice.id).limit(DEVICES_MAX)))
        if row.id not in first:
            db.execute(delete(PushDevice).where(PushDevice.id == row.id))
            db.commit()
            raise fail("push_too_many_devices", 409, max=DEVICES_MAX)
    device = _open(account_id, row)
    assert device is not None
    if made.rowcount:  # type: ignore[attr-defined]
        logger.info("Push device signed up")
    return view(device), bool(made.rowcount)  # type: ignore[attr-defined]


def rename(db: Session, account_id: int, uid: str, name: Any) -> dict[str, Any]:
    row = db.scalar(select(PushDevice).where(PushDevice.user_id == account_id, PushDevice.uid == uid))
    device = _open(account_id, row) if row is not None else None
    if row is None or device is None:
        raise error("not_found", "Not found.", 404)
    content = {"endpoint": device.endpoint, "p256dh": device.p256dh, "auth": device.auth, "name": clean_name(name),
               "lang": device.lang, "phone": device.phone}
    row.content = _seal(account_id, uid, content)
    db.commit()
    renamed = _open(account_id, row)
    assert renamed is not None
    return view(renamed)


def remove(db: Session, account_id: int, uid: str) -> None:
    """One own device; somebody else's answers like one that does not exist."""
    gone = db.execute(delete(PushDevice).where(PushDevice.user_id == account_id, PushDevice.uid == uid))
    db.commit()
    if not gone.rowcount:  # type: ignore[attr-defined]
        raise error("not_found", "Not found.", 404)
    logger.info("Push device removed by its owner")


def count_all(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(PushDevice)) or 0)


def renew_keys(db: Session) -> None:
    """A new key pair; every device signed up with the old one goes, it could not take a message any more."""
    webpush.renew(db)
    db.execute(delete(PushDevice))
    db.commit()


# --- Sending --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    title: str
    body: str
    #: A path of nexpaper that a tap opens.
    url: str
    #: The same tag replaces an earlier message on the device instead of stacking up.
    tag: str
    urgency: str = "normal"
    #: Where a tap leads on a computer, when that is not ``url``.
    desk: str = ""


@dataclass
class Result:
    sent: int = 0
    gone: int = 0
    failed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"sent": self.sent, "gone": self.gone, "failed": self.failed}


_slots = threading.BoundedSemaphore(AT_ONCE)


def _deliver(db_factory: Callable[[], Session], key: Any, subject: str, device: Device, message: Message) -> str:
    """One message to one device: ``sent``, ``gone`` (the push service no longer knows it) or ``failed``. Whatever
    goes wrong with one device stays with it: the others get their message all the same."""
    try:
        return _deliver_one(db_factory, key, subject, device, message)
    except Exception:  # one device must never hold up the others
        logger.exception("Push not sent: an unexpected failure with one device")
        return "failed"


def _deliver_one(db_factory: Callable[[], Session], key: Any, subject: str, device: Device, message: Message) -> str:
    with db_factory() as db:
        try:
            place, service = _target(db, device.endpoint)
        except HTTPException as exc:
            code = exc.detail.get("code") if isinstance(exc.detail, dict) else exc.status_code
            logger.warning("Push not sent reason=%s", code)
            return "failed"
    data = webpush.payload(message.title, message.body, message.url, message.tag, message.desk)
    body = webpush.encrypt(data, device.p256dh, device.auth)
    headers = {
        "Authorization": webpush.vapid_header(key, device.endpoint, subject),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(webpush.TTL_SECONDS),
        "Urgency": message.urgency,
    }
    if not _slots.acquire(timeout=SECONDS):
        logger.warning("Push not sent service=%s reason=busy", service)
        return "failed"
    # The status is what counts; a body past the limit is thrown away, its status still read (a 410 removes the device).
    heads: list[int] = []
    try:
        started = ticks()
        with outbound.client(transport) as session:
            answer = outbound.send(session, "POST", place, headers, deadline=started + SECONDS, ticks=ticks,
                                   limit=ANSWER_MAX, connect_seconds=CONNECT_SECONDS, content=body,
                                   accept=lambda head: heads.append(head.status_code))
        status = answer.status_code
    except outbound.TooLarge:
        status = heads[0] if heads else 0
    except (outbound.Late, httpx.TimeoutException):
        logger.warning("Push not sent service=%s reason=timeout", service)
        return "failed"
    except (outbound.Refused, httpx.HTTPError) as exc:
        logger.warning("Push not sent service=%s reason=%s", service, type(exc).__name__)
        return "failed"
    finally:
        _slots.release()
    if 200 <= status < 300:
        logger.info("Push sent service=%s", service)
        return "sent"
    if status in (404, 410):
        logger.info("Push device gone service=%s status=%s", service, status)
        return "gone"
    logger.warning("Push refused service=%s status=%s", service, status)
    return "failed"


def send_to_person(account_id: int, message_for: Callable[[str], Message]) -> Result:
    """One message to every device of a person, each in the language it signed up in (``message_for`` gets it).
    A device that left is removed; the others note when they last took a message."""
    from ..db import SessionLocal

    result = Result()
    with SessionLocal() as db:
        if not has_devices(db, account_id):
            return result
        devices = devices_of(db, account_id)
        key = webpush.server_key(db)
        subject = webpush.subject(db)
    if not devices:
        return result
    messages = [message_for(device.lang) for device in devices]
    with ThreadPoolExecutor(max_workers=min(4, len(devices))) as pool:
        outcomes = list(pool.map(lambda pair: _deliver(SessionLocal, key, subject, *pair), zip(devices, messages,
                                                                                               strict=True)))
    sent = [device.uid for device, outcome in zip(devices, outcomes, strict=True) if outcome == "sent"]
    gone = [device.uid for device, outcome in zip(devices, outcomes, strict=True) if outcome == "gone"]
    with SessionLocal() as db:
        if sent:
            db.execute(update(PushDevice).where(PushDevice.user_id == account_id, PushDevice.uid.in_(sent))
                       .values(last_used_at=utcnow().replace(microsecond=0)))
        if gone:
            db.execute(delete(PushDevice).where(PushDevice.user_id == account_id, PushDevice.uid.in_(gone)))
        db.commit()
    result.sent, result.gone = len(sent), len(gone)
    result.failed = len(devices) - len(sent) - len(gone)
    return result


# --- The operator ---------------------------------------------------------------------------------------------------


def check_contact(value: Any) -> str:
    """Empty, ``mailto:`` with an address, or an https address without anything but a host and a path."""
    if not isinstance(value, str):
        raise fail("push_contact_invalid")
    text = value.strip()
    if not text:
        return ""
    if len(text) > CONTACT_MAX or any(ord(char) <= 32 or ord(char) == 127 for char in text):
        raise fail("push_contact_invalid")
    if _MAIL.match(text):
        return text
    parts = urlsplit(text)
    if parts.scheme == "https" and parts.hostname and not parts.username and not parts.password \
            and not parts.query and not parts.fragment:
        return text
    raise fail("push_contact_invalid")


def operator_view(db: Session) -> dict[str, Any]:
    """What the operator's card shows: whether it is ready, how many devices there are on the server (never whose),
    the start and end of the public key, who the push services may contact, and the lists."""
    values = settings_service.get_all(db)
    public = webpush.public_key(db)
    return {
        "devices": count_all(db),
        "key": f"{public[:4]}…{public[-4:]}",
        "contact": str(values.get("push_contact") or ""),
        "contact_used": webpush.subject(db),
        "known": list(KNOWN_HOSTS),
        "hosts": [str(entry) for entry in values.get("push_hosts") or []],
    }


def operator_save(db: Session, *, contact: Any = None, hosts: list[str] | None = None) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    if contact is not None:
        changes["push_contact"] = check_contact(contact)
    if hosts is not None:
        kept: list[str] = []
        for line in hosts:
            if not isinstance(line, str) or not line.strip():
                continue
            try:
                name = normal_name(line)
            except ValueError as exc:
                raise fail("push_host_invalid", 422, entry=str(line).strip()[:80]) from exc
            if name not in kept and name not in KNOWN_HOSTS:
                kept.append(name)
        if len(kept) > HOSTS_MAX:
            raise fail("push_too_many_hosts", 422, max=HOSTS_MAX)
        changes["push_hosts"] = kept
    settings_service.save(db, changes)
    logger.info("The operator changed Web Push fields=%s", ",".join(sorted(changes)) or "nothing")
    return operator_view(db)


def forget() -> None:
    """For the tests: the way out back to the real one."""
    global transport, resolver
    transport = None
    resolver = outbound.resolve
