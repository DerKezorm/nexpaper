"""A stand-in for a push service, as the transport of nexpaper's requests: it takes a message the way a real one does
and keeps what came. Every device it hands out has a key pair made for the run, so a test reads what nexpaper sent:
decrypted here by RFC 8291 itself (written out below, not with the library nexpaper encrypts with) and by
``http_ece`` as a second opinion. The VAPID signature is checked against the key in the header.

Nothing is switched off for it: its host is added to the operator's list of push services, its name resolves to a
public address (only in the tests, never connected to), and a request must come to that address with its name in
the Host header."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field
from typing import Any

import http_ece
import httpx
import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.services import outbound, webpush

HOST = "push.example.com"
#: What the stand-in's name resolves to in the tests: a public address, so the check for own networks runs as it does
#: for a real push service. Nothing ever connects to it, the transport answers.
ADDRESS = "93.184.215.14"


def hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def rfc8291_decrypt(body: bytes, private: ec.EllipticCurvePrivateKey, auth: bytes) -> bytes:
    """RFC 8291 with the header of RFC 8188 (aes128gcm), one record, step by step as the RFC has it."""
    salt, record_size, id_length = body[:16], int.from_bytes(body[16:20], "big"), body[20]
    sender_public = body[21:21 + id_length]
    ciphertext = body[21 + id_length:]
    assert record_size >= len(ciphertext), "one record"
    receiver_public = webpush.public_bytes(private)
    shared = private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender_public))
    ikm = hkdf(auth, shared, b"WebPush: info\x00" + receiver_public + sender_public, 32)
    key = hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    padded = AESGCM(key).decrypt(nonce, ciphertext, None)
    unpadded = padded.rstrip(b"\x00")
    assert unpadded.endswith(b"\x02"), "the last record ends with the delimiter 2"
    return unpadded[:-1]


@dataclass
class Device:
    endpoint: str
    p256dh: str
    auth: str
    private: ec.EllipticCurvePrivateKey
    secret: bytes

    def subscription(self, **extra: Any) -> dict[str, Any]:
        return {"endpoint": self.endpoint, "p256dh": self.p256dh, "auth": self.auth, **extra}


@dataclass
class Received:
    device: str
    headers: dict[str, str]
    url: str
    message: dict[str, Any]
    claims: dict[str, Any]


@dataclass
class FakePushService:
    devices: dict[str, Device] = field(default_factory=dict)
    received: list[Received] = field(default_factory=list)
    #: The status a device's address answers with (default 201).
    answers: dict[str, int] = field(default_factory=dict)
    #: Every request that came, also those refused.
    requests: list[httpx.Request] = field(default_factory=list)

    def device(self, host: str = HOST) -> Device:
        private = ec.generate_private_key(ec.SECP256R1())
        secret = os.urandom(16)
        token = secrets.token_urlsafe(24)
        found = Device(endpoint=f"https://{host}/wpush/v2/{token}", p256dh=webpush.b64url(webpush.public_bytes(private)),
                       auth=webpush.b64url(secret), private=private, secret=secret)
        self.devices[token] = found
        return found

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        token = request.url.path.rsplit("/", 1)[-1]
        assert request.url.host == ADDRESS, "connected to the address that was checked"
        assert request.headers["host"] == HOST, "the name stays in the Host header"
        device = self.devices.get(token)
        if device is None:
            return httpx.Response(404)
        status = self.answers.get(token, 201)
        if status >= 300:
            return httpx.Response(status)
        authorization = request.headers["authorization"]
        assert authorization.startswith("vapid t=")
        token_part, key_part = authorization[len("vapid t="):].split(", k=")
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), webpush.unb64url(key_part))
        claims = jwt.decode(token_part, public, algorithms=["ES256"], audience=f"https://{HOST}")
        body = request.read()
        assert request.headers["content-encoding"] == "aes128gcm"
        plain = rfc8291_decrypt(body, device.private, device.secret)
        second = http_ece.decrypt(body, private_key=device.private, auth_secret=device.secret, version="aes128gcm")
        assert plain == second
        self.received.append(Received(device=token, headers=dict(request.headers), url=str(request.url),
                                      message=json.loads(plain), claims=claims))
        return httpx.Response(status)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def bodies(self) -> list[str]:
        return [entry.message["body"] for entry in self.received]


def public_resolver(host: str, port: int) -> list[str]:
    """The stand-in's name and the known push services resolve to a public address; anything else does not exist."""
    if host == HOST or host.endswith((".googleapis.com", ".mozilla.com", ".apple.com", ".windows.com")):
        return [ADDRESS]
    raise outbound.Unreachable(host)
