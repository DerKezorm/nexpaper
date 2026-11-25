"""A passkey in software for the contract tests: it answers the browser's part of WebAuthn (``navigator.credentials``)
with a fresh P-256 key, as a phone or a laptop would, "none" attestation, user present and verified.

Nothing here talks to a server; the tests hand the answers to ``passkeys.finish_register`` and ``finish_sign_in``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import struct
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

UP, UV, AT = 0x01, 0x04, 0x40


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Device:
    """One passkey: its key, its id, its count, and the user handle the site gave it."""

    def __init__(self, origin: str, rp_id: str) -> None:
        self.origin = origin
        self.rp_id = rp_id
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(32)
        self.count = 0
        self.user_handle = b""

    def _client_data(self, kind: str, challenge: str, origin: str | None) -> bytes:
        data = {"type": kind, "challenge": challenge, "origin": origin or self.origin, "crossOrigin": False}
        return json.dumps(data, separators=(",", ":")).encode("utf-8")

    def public_key(self) -> bytes:
        """The public key as COSE, the way the site keeps it."""
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    def _auth_data(self, flags: int, attested: bool) -> bytes:
        data = hashlib.sha256(self.rp_id.encode("ascii")).digest() + bytes([flags]) + struct.pack(">I", self.count)
        if attested:
            data += bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id + self.public_key()
        return data

    def create(self, options: str | dict[str, Any], *, origin: str | None = None) -> dict[str, Any]:
        """The answer to ``begin_register``'s options."""
        given = json.loads(options) if isinstance(options, str) else options
        self.user_handle = unb64url(given["user"]["id"])
        client_data = self._client_data("webauthn.create", given["challenge"], origin)
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": self._auth_data(UP | UV | AT, True)})
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {"clientDataJSON": b64url(client_data), "attestationObject": b64url(attestation)},
        }

    def get(
        self,
        options: str | dict[str, Any],
        *,
        origin: str | None = None,
        count_up: bool = True,
        user_handle: bytes | None = None,
    ) -> dict[str, Any]:
        """The answer to ``begin_sign_in``'s options: signed with the key, the count one higher (unless not)."""
        given = json.loads(options) if isinstance(options, str) else options
        if count_up:
            self.count += 1
        client_data = self._client_data("webauthn.get", given["challenge"], origin)
        auth_data = self._auth_data(UP | UV, False)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "authenticatorData": b64url(auth_data),
                "signature": b64url(signature),
                "userHandle": b64url(self.user_handle if user_handle is None else user_handle),
            },
        }
