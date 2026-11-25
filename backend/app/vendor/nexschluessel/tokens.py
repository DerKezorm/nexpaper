"""The secret of a key, the way all eight apps make and keep it: the app's prefix and ``secrets.token_urlsafe(32)``
(43 characters ``A-Z a-z 0-9 - _``), stored as the SHA-256 of the whole key (prefix included, UTF-8) in 64 hex
characters, shown as the prefix and a few characters. A key made by any earlier version therefore has the same hash
here: nothing is moved or hashed again."""

from __future__ import annotations

import hashlib
import secrets

#: The longest key any app accepts before it looks anything up.
MAX_LENGTH = 200


def make_secret(prefix: str, nbytes: int = 32) -> str:
    """A new key: ``prefix`` and ``nbytes`` random bytes in URL-safe Base64 without padding."""
    return prefix + secrets.token_urlsafe(nbytes)


def digest(token: str) -> str:
    """What the app stores: SHA-256 of the whole key, UTF-8, in lower-case hex (64 characters)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def shown_prefix(token: str, prefix: str, extra: int = 4) -> str:
    """The part a list shows: the prefix and ``extra`` characters (``ntk_AbCd``; nexmail ``nxm_AbCdEf``)."""
    return token[: len(prefix) + extra]


def bearer(header: str | None) -> str | None:
    """The key from ``Authorization: Bearer <key>`` (the word in any case, as every app reads it); ``None``
    without one. No other header and no query parameter carries a key."""
    if not header or header[:7].lower() != "bearer ":
        return None
    token = header[7:].strip()
    return token or None


def plausible(token: str, prefixes: tuple[str, ...], max_length: int = MAX_LENGTH) -> bool:
    """Whether ``token`` may be a key at all: one of the prefixes, not too long, printable ASCII only."""
    if not token or len(token) > max_length or not token.isascii() or not token.isprintable():
        return False
    return any(token.startswith(prefix) for prefix in prefixes)
