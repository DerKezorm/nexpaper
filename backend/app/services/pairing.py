"""Pairing a device with a code it uses once: the QR code under My account, and OAuth 2 with PKCE for apps.

Both end in the same place: a device token (``npd_``, ``services/devices.py``) for the account, with a name of its own,
listed with the signed-in devices and revocable one by one. Only a full session of a signed-in browser makes a code
(the second factor was met there), so a device never gets in past the second factor.

**The QR code.** ``start_qr`` makes a code of twelve letters and digits (about 59 bits), valid for five minutes and
once. A new code ends the one before. The device sends it with a name of its own to ``POST /api/v1/devices/pair``
(``redeem_qr``) and gets the token. A wrong code counts against the sender like a wrong password (the brake per
address in the router). Two devices with the same code at the same moment: the one whose write comes first wins, the
other hears "no such code" (the code is marked used in the same statement that checks it).

**OAuth 2 with PKCE** (RFC 6749, RFC 7636, RFC 8252). An app opens ``/oauth/authorize`` of the web app in the browser
with its ``client_id``, a ``redirect_uri`` from the fixed list of that app, ``code_challenge`` (S256 only; ``plain`` is
refused) and ``state``. The person signs in as always (password and second factor, or the provider) and allows it; the
browser goes back to the app with a code that is valid for two minutes and once. The app trades it with the
``code_verifier`` at ``POST /api/v1/oauth/token`` for the device token. A verifier of the right form that does not
fit, another ``redirect_uri`` or another app uses the code up: whoever intercepted the code without the verifier gets
one try, not many. A verifier that is not of the form RFC 7636 asks for is refused before the code is looked at (it
cannot fit any challenge), and leaves the code as it was.

Codes are stored as their SHA-256 only, never in the log.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from .. import clock
from ..models import Account, Device, Pairing
from . import devices, totp

logger = logging.getLogger("nexpaper.auth")

QR = "qr"
OAUTH = "oauth"
#: How long a QR code stays valid.
QR_LIFETIME = timedelta(minutes=5)
#: How long the code an app gets back stays valid.
OAUTH_LIFETIME = timedelta(minutes=2)
#: Letters and digits that cannot be taken for one another (no I, L, O, 0, 1).
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
QR_GROUPS = 3
QR_GROUP = 4
_QR_SHAPE = re.compile(rf"^[{ALPHABET}]{{{QR_GROUPS * QR_GROUP}}}$")
#: RFC 7636: the verifier is 43 to 128 of these characters; the S256 challenge is 43 of base64url.
_VERIFIER = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43}$")
STATE_MAX = 500


def digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def normal_qr(code: str) -> str:
    """A code as people type it: lower case, spaces and dashes are all the same."""
    return re.sub(r"[\s-]", "", code or "").upper()[:64]


def _fits(account: Account | None) -> bool:
    now = clock.now()
    return account is not None and account.blocked_at is None and (
        account.locked_until is None or account.locked_until <= now)


# --- The QR code ------------------------------------------------------------------------------------------------------


def start_qr(db: Session, account_id: int) -> tuple[Pairing, str]:
    """A new code for the account; one that was still open is ended. The code is returned once."""
    raw = "".join(secrets.choice(ALPHABET) for _ in range(QR_GROUPS * QR_GROUP))
    code = "-".join(raw[index : index + QR_GROUP] for index in range(0, len(raw), QR_GROUP))
    now = clock.now()
    db.execute(delete(Pairing).where(Pairing.account_id == account_id, Pairing.kind == QR, Pairing.used_at.is_(None)))
    row = Pairing(account_id=account_id, kind=QR, code_hash=digest(raw), created_at=now, expires_at=now + QR_LIFETIME)
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("Pairing code made pairing_id=%s", row.id)
    return row, code


@dataclass
class QrState:
    state: str
    expires_at: object | None = None
    device: Device | None = None


def qr_state(db: Session, account_id: int) -> QrState:
    """What became of the newest code of the account: ``open``, ``used`` (with the device), ``expired`` or ``none``."""
    row = db.scalar(select(Pairing).where(Pairing.account_id == account_id, Pairing.kind == QR)
                    .order_by(Pairing.id.desc()).limit(1))
    if row is None:
        return QrState("none")
    if row.used_at is not None:
        device = db.get(Device, row.device_id) if row.device_id is not None else None
        return QrState("used", row.expires_at, device)
    if row.expires_at <= clock.now():
        return QrState("expired", row.expires_at)
    return QrState("open", row.expires_at)


def cancel_qr(db: Session, account_id: int) -> None:
    db.execute(delete(Pairing).where(Pairing.account_id == account_id, Pairing.kind == QR, Pairing.used_at.is_(None)))
    db.commit()


def _use(db: Session, kind: str, code_hash: str) -> Pairing | None:
    """Marks the code used, in the statement that checks it is open: of two at the same moment, one gets it."""
    now = clock.now()
    taken = db.execute(
        update(Pairing).where(Pairing.code_hash == code_hash, Pairing.kind == kind, Pairing.used_at.is_(None),
                              Pairing.expires_at > now).values(used_at=now)
    )
    if taken.rowcount != 1:  # type: ignore[attr-defined]
        db.rollback()
        return None
    return db.scalar(select(Pairing).where(Pairing.code_hash == code_hash))


def redeem_qr(db: Session, code: str, name: str) -> tuple[Device, str, Account] | None:
    """The device for a code, or None (no such code, used, run out, or the account may not sign in now)."""
    devices.clean_name(name)
    raw = normal_qr(code)
    if not _QR_SHAPE.match(raw):
        return None
    row = _use(db, QR, digest(raw))
    if row is None:
        return None
    return _finish(db, row, name, "qr")


def _finish(db: Session, row: Pairing, name: str, via: str) -> tuple[Device, str, Account] | None:
    account = db.get(Account, row.account_id)
    if not _fits(account) or totp.setup_required(db, account):  # type: ignore[arg-type]
        # The code is used up all the same: the account may not let a device in now.
        db.commit()
        return None
    assert account is not None
    device, token = devices.add(db, account.id, name, via)
    row.device_id = device.id
    db.commit()
    db.refresh(device)
    db.expunge(account)
    logger.info("Device paired device_id=%s via=%s", device.uid, via)
    return device, token, account


# --- OAuth 2 with PKCE ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Client:
    """An app that may ask for a device token: its name and where the code may go back to."""

    id: str
    name: str
    #: Exact addresses (an app's own scheme).
    redirects: tuple[str, ...] = ()
    #: ``http://127.0.0.1:<port>/callback`` and ``http://[::1]:<port>/callback`` with any port (RFC 8252, 7.3).
    loopback: bool = False


#: The registered apps. A new one comes with a release of nexpaper, never through a setting: the list is the wall.
CLIENTS: dict[str, Client] = {
    client.id: client for client in (
        Client("nexpaper-mobile", "nexpaper for iPhone and Android", redirects=("nexpaper://oauth/callback",)),
        Client("nexpaper-desktop", "nexpaper on the computer", loopback=True),
    )
}
LOOPBACK_HOSTS = ("127.0.0.1", "[::1]")
LOOPBACK_PATH = "/callback"


def redirect_allowed(client: Client, uri: str) -> bool:
    if len(uri) > 300 or any(ord(char) <= 32 or ord(char) == 127 for char in uri):
        return False
    if uri in client.redirects:
        return True
    if not client.loopback:
        return False
    try:
        parts = urlsplit(uri)
        port = parts.port
    except ValueError:
        return False
    host = parts.netloc.rsplit(":", 1)[0] if port is not None else parts.netloc
    # Written exactly so: ``HTTP://`` would be read the same, but the list is a list of spellings.
    return (uri.startswith("http://") and parts.scheme == "http" and host in LOOPBACK_HOSTS and port is not None
            and 1024 <= port <= 65535
            and parts.path == LOOPBACK_PATH and not parts.query and not parts.fragment and "@" not in parts.netloc)


class OAuthProblem(Exception):
    """A request the app made wrongly. ``back``: the address that tells the app (None: the app is not known or its
    address not allowed, so nothing may go back to it)."""

    def __init__(self, code: str, text: str, back: str | None = None) -> None:
        super().__init__(text)
        self.code, self.text, self.back = code, text, back


def back_to(uri: str, values: dict[str, str]) -> str:
    return uri + ("&" if "?" in uri else "?") + urlencode(values)


@dataclass(frozen=True)
class Asked:
    client: Client
    redirect_uri: str
    challenge: str
    state: str
    device_name: str


def check(client_id: str, redirect_uri: str, response_type: str, challenge: str, method: str, state: str,
          device_name: str) -> Asked:
    """The request of an app, checked. The app and its address first: without them nothing goes back anywhere."""
    client = CLIENTS.get(client_id or "")
    if client is None:
        raise OAuthProblem("oauth_client_unknown", "This app is not known to nexpaper.")
    if not redirect_allowed(client, redirect_uri or ""):
        raise OAuthProblem("oauth_redirect_refused", "This app may not be answered at this address.")
    if len(state or "") > STATE_MAX:
        raise OAuthProblem("oauth_invalid_request", "The state is too long.")
    tell = {"state": state} if state else {}
    if response_type != "code":
        raise OAuthProblem("oauth_invalid_request", "Only response_type=code is offered.",
                           back_to(redirect_uri, {"error": "unsupported_response_type", **tell}))
    if method != "S256" or not _CHALLENGE.match(challenge or ""):
        raise OAuthProblem("oauth_pkce_required", "PKCE with S256 is required.",
                           back_to(redirect_uri, {"error": "invalid_request",
                                                  "error_description": "code_challenge with S256 is required", **tell}))
    name = " ".join((device_name or "").split())[: devices.NAME_MAX] or client.name
    if any(ord(char) < 32 or ord(char) == 127 or unicodedata.category(char) == "Cf" for char in name):
        name = client.name
    return Asked(client, redirect_uri, challenge, state or "", name)


def authorize(db: Session, account_id: int, asked: Asked) -> str:
    """The person allowed it: the address that takes the code back to the app."""
    code = secrets.token_urlsafe(32)
    now = clock.now()
    db.add(Pairing(account_id=account_id, kind=OAUTH, code_hash=digest(code), created_at=now,
                   expires_at=now + OAUTH_LIFETIME, client_id=asked.client.id, redirect_uri=asked.redirect_uri,
                   challenge=asked.challenge, device_name=asked.device_name))
    db.commit()
    logger.info("App allowed client=%s", asked.client.id)
    return back_to(asked.redirect_uri, {"code": code, **({"state": asked.state} if asked.state else {})})


def denied(asked: Asked) -> str:
    return back_to(asked.redirect_uri, {"error": "access_denied", **({"state": asked.state} if asked.state else {})})


def s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def trade(db: Session, *, code: str, verifier: str, client_id: str, redirect_uri: str
          ) -> tuple[Device, str, Account] | None:
    """The device for an app's code, or None: the code is unknown, used, run out, for another app or address, or the
    verifier does not fit. A try with a code that exists and a verifier of the right form uses the code up."""
    if not code or len(code) > 200 or not _VERIFIER.match(verifier or ""):
        return None
    row = _use(db, OAUTH, digest(code))
    if row is None:
        return None
    if (row.client_id != client_id or row.redirect_uri != redirect_uri
            or not hmac.compare_digest(s256(verifier), row.challenge)):
        db.commit()
        logger.warning("App code refused client=%s", CLIENTS[row.client_id].id if row.client_id in CLIENTS else "-")
        return None
    return _finish(db, row, row.device_name or CLIENTS[row.client_id].name, "app:" + row.client_id)


#: How long a used or run-out code stays: the page that showed it asks what became of it for a little while.
KEEP = timedelta(hours=1)


def sweep(db: Session) -> int:
    """Codes that were used or ran out more than ``KEEP`` ago go (the background, once an hour)."""
    before = clock.now() - KEEP
    gone = db.execute(delete(Pairing).where(or_(Pairing.used_at < before, Pairing.expires_at < before))).rowcount
    db.commit()
    return int(gone or 0)
