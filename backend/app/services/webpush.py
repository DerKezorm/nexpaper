"""Web Push, the cryptography: notifications straight to a browser or an app on the home screen.

Taken over from nexsift. A device signs up in the interface; the browser hands over an address at its push service
(Google, Apple, Mozilla, Microsoft) and two keys. nexpaper encrypts every message for that device (RFC 8291,
aes128gcm) and signs the request with its own key pair (VAPID, RFC 8292): the push service sees that something
arrives and for whom, never what. Where a message may go is ``services/push.py``.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import http_ece
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..models import Setting
from ..security import decrypt_secret, encrypt_secret
from . import settings_service

#: How long a push service keeps a message for a device that is offline, in seconds: a notice of today is of no
#: use tomorrow.
TTL_SECONDS = 12 * 3600
#: How long a signature is valid; push services refuse more than a day.
VAPID_SECONDS = 12 * 3600
#: What a message may say at most; far below the 4 KB push services take after encryption.
TITLE_MAX = 80
BODY_MAX = 600
#: The key pair is sealed with the server's secret, in a context of its own.
KEY_CONTEXT = "operator:vapid"
#: Where nobody set a contact: well formed, and plainly a placeholder. Apple refuses ``localhost``.
PLACEHOLDER_CONTACT = "mailto:admin@example.com"

_lock = threading.Lock()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def public_bytes(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def _load(stored: str) -> ec.EllipticCurvePrivateKey | None:
    pem = decrypt_secret(stored, KEY_CONTEXT)
    if not pem:
        return None
    key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    return key if isinstance(key, ec.EllipticCurvePrivateKey) else None


def _sealed_new_key() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode("ascii")
    return encrypt_secret(pem, KEY_CONTEXT)


def server_key(db: Session) -> ec.EllipticCurvePrivateKey:
    """nexpaper's own key pair, made at the first need and kept sealed. Every device signed up is bound to its public
    half: a new pair means signing every device up again. Two processes at their first need make one pair: the
    second insert finds the first and does nothing, and both read the one that stands."""
    with _lock:
        stored = str(settings_service.get(db, "push_key_enc") or "")
        key = _load(stored) if stored else None
        if key is not None:
            return key
        db.execute(sqlite_insert(Setting).values(key="push_key_enc", value=_sealed_new_key())
                   .on_conflict_do_nothing(index_elements=[Setting.key]))
        db.commit()
        stored = str(settings_service.get(db, "push_key_enc") or "")
        key = _load(stored)
        if key is None:
            # A key sealed under another secret.key: of no use any more. A new pair; the devices sign up again.
            settings_service.save(db, {"push_key_enc": _sealed_new_key()})
            key = _load(str(settings_service.get(db, "push_key_enc")))
        assert key is not None
        return key


def renew(db: Session) -> None:
    """A new key pair in place of the old one (the caller removes every device signed up with the old one)."""
    with _lock:
        settings_service.save(db, {"push_key_enc": _sealed_new_key()})


def public_key(db: Session) -> str:
    """The application server key the browser needs to sign up (base64url, uncompressed point)."""
    return b64url(public_bytes(server_key(db)))


def encrypt(plaintext: bytes, p256dh: str, auth: str, *, sender: ec.EllipticCurvePrivateKey | None = None,
            salt: bytes | None = None) -> bytes:
    """The body of one message for one device (RFC 8291, aes128gcm). ``sender`` and ``salt`` are fresh for every
    message."""
    return http_ece.encrypt(
        plaintext,
        salt=salt or os.urandom(16),
        private_key=sender or ec.generate_private_key(ec.SECP256R1()),
        dh=unb64url(p256dh),
        auth_secret=unb64url(auth),
        version="aes128gcm",
    )


def vapid_header(key: ec.EllipticCurvePrivateKey, endpoint: str, subject: str, now: float | None = None) -> str:
    """``Authorization: vapid t=…, k=…`` for one push service (RFC 8292)."""
    parts = urlsplit(endpoint)
    claims = {
        "aud": f"{parts.scheme}://{parts.hostname}",
        "exp": int((time.time() if now is None else now) + VAPID_SECONDS),
        "sub": subject,
    }
    token = jwt.encode(claims, key, algorithm="ES256", headers={"typ": "JWT"})
    return f"vapid t={token}, k={b64url(public_bytes(key))}"


def subject(db: Session) -> str:
    """Who sends, for the push service to contact: what the operator set, else the public https address, else a
    placeholder that is at least well formed."""
    contact = str(settings_service.get(db, "push_contact") or "").strip()
    if contact:
        return contact
    public = settings_service.public_url(db)
    if public.startswith("https://"):
        return public
    return PLACEHOLDER_CONTACT


def payload(title: str, body: str, url: str, tag: str, desk: str = "") -> bytes:
    """What the service worker shows: a title, a sentence, where a tap leads (a path of nexpaper; ``desk`` in its
    place on a computer, where there is no quick upload to open) and a tag, so that a second notice replaces the
    first instead of stacking up."""
    data: dict[str, Any] = {"title": title[:TITLE_MAX], "body": body[:BODY_MAX], "url": url, "tag": tag}
    if desk:
        data["desk"] = desk
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def valid_keys(p256dh: str, auth: str) -> bool:
    """Keys of the right form: a point on P-256, uncompressed, and an auth secret of 16 bytes."""
    try:
        point = unb64url(p256dh)
        secret = unb64url(auth)
    except (ValueError, TypeError):
        return False
    if len(point) != 65 or point[0] != 4 or len(secret) != 16:
        return False
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    except ValueError:
        return False
    return True
