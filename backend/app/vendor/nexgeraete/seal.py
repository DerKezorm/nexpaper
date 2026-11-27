"""The sealed push for the iPhone apps, byte for byte as nexnotes, nextasks, nexmail and nextime seal it (G15).

X25519 with a fresh key pair per message and device against the device's public key, HKDF-SHA256 over the shared
secret with an empty salt and the app's ``info`` (``nexnotes-push-v1``) to 32 bytes, ChaCha20-Poly1305 with a 12-byte
nonce and no associated data. ``enc`` = standard base64 with padding of ephemeral public key (32) + nonce (12) +
ciphertext and tag. The relay and Apple see only ``enc``.

The only part of the module that needs ``cryptography``; it is imported when a message is sealed, not before.
"""

from __future__ import annotations

import base64
import binascii
import os

#: The relay takes ``enc`` up to this length.
MAX_ENC = 3000


def _key(shared: bytes, info: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(shared)


def key_valid(value: str) -> bool:
    """A public X25519 key one can agree with: base64 of 32 bytes, and no point of small order."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

    try:
        raw = base64.b64decode(value, validate=True)
        X25519PrivateKey.generate().exchange(X25519PublicKey.from_public_bytes(raw))
    except (binascii.Error, ValueError):
        return False
    return True


def seal(
    plaintext: bytes | str,
    device_public_b64: str,
    info: str | bytes,
    ephemeral_private: bytes | None = None,
    nonce: bytes | None = None,
) -> str:
    """``enc`` for one device. Ephemeral key and nonce are random unless given (only tests give them)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    raw = serialization.Encoding.Raw
    public = serialization.PublicFormat.Raw
    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")
    if isinstance(info, str):
        info = info.encode("utf-8")
    eph = X25519PrivateKey.from_private_bytes(ephemeral_private) if ephemeral_private else X25519PrivateKey.generate()
    nonce = nonce if nonce is not None else os.urandom(12)
    if len(nonce) != 12:
        raise ValueError("nonce must be 12 bytes")
    device = X25519PublicKey.from_public_bytes(base64.b64decode(device_public_b64))
    key = _key(eph.exchange(device), info)
    sealed = ChaCha20Poly1305(key).encrypt(nonce, plaintext, None)
    enc = base64.b64encode(eph.public_key().public_bytes(raw, public) + nonce + sealed).decode()
    if len(enc) > MAX_ENC:
        raise ValueError("enc longer than 3000 characters")
    return enc


def unseal(enc: str, device_private_b64: str, info: str | bytes) -> bytes:
    """What the app decrypts. Raises ``cryptography.exceptions.InvalidTag`` for a wrong key or ``info``."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    if isinstance(info, str):
        info = info.encode("utf-8")
    raw = base64.b64decode(enc, validate=True)
    if len(raw) < 32 + 12 + 16:
        raise ValueError("enc too short")
    eph = X25519PublicKey.from_public_bytes(raw[:32])
    device = X25519PrivateKey.from_private_bytes(base64.b64decode(device_private_b64))
    key = _key(device.exchange(eph), info)
    return ChaCha20Poly1305(key).decrypt(raw[32:44], raw[44:], None)


def key_pair() -> tuple[str, str]:
    """A new device key pair (private, public) in base64: what the iPhone app makes; for tests and the reference."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    private = X25519PrivateKey.generate()
    raw = serialization.Encoding.Raw
    private_bytes = private.private_bytes(raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public_bytes = private.public_key().public_bytes(raw, serialization.PublicFormat.Raw)
    return base64.b64encode(private_bytes).decode(), base64.b64encode(public_bytes).decode()
