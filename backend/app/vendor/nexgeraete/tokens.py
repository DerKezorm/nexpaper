"""Keys, secrets and codes the way every app makes and keeps them: a device key is the app's prefix and
``secrets.token_urlsafe(32)`` (nexmail 48), stored as the SHA-256 of the whole key (prefix included, UTF-8) in 64 hex
characters. A key made by any earlier version has the same hash here: nothing is moved or hashed again. Secrets and
codes are compared in fixed time."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

from .config import ALPHABET

#: The longest key any app accepts before it looks anything up.
MAX_LENGTH = 200
#: RFC 7636: a verifier is 43 to 128 of these characters; an S256 challenge is 43 characters of base64url.
_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}")
_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}")
#: The ``state`` the app sends to ``/app-connect`` (nexnotes).
_STATE = re.compile(r"[A-Za-z0-9_-]{8,128}")


def make_secret(prefix: str = "", nbytes: int = 32) -> str:
    """``prefix`` and ``nbytes`` random bytes in URL-safe Base64 without padding."""
    return prefix + secrets.token_urlsafe(nbytes)


def digest(value: str) -> str:
    """What the app stores: SHA-256 of the whole value, UTF-8, in lower-case hex (64 characters)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def same(one: str, other: str) -> bool:
    """Equal, compared in fixed time."""
    return hmac.compare_digest(one.encode("utf-8"), other.encode("utf-8"))


def bearer(header: str | None) -> str | None:
    """The key from ``Authorization: Bearer <key>`` (the word in any case); ``None`` without one."""
    if not header or header[:7].lower() != "bearer ":
        return None
    token = header[7:].strip()
    return token or None


def plausible(token: str | None, prefixes: tuple[str, ...], max_length: int = MAX_LENGTH) -> bool:
    """Whether ``token`` may be a device key at all: one of the prefixes, not too long, printable ASCII only."""
    if not token or len(token) > max_length or not token.isascii() or not token.isprintable():
        return False
    return any(token.startswith(prefix) for prefix in prefixes)


def make_code(length: int) -> str:
    """A code to type, ``length`` letters of ``ALPHABET`` (8: 40 bits, enough only with the brake and ten minutes)."""
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def show_code(raw: str) -> str:
    """In groups of four: ``K7MQ-R4TX`` (nexpaper ``ABCD-EFGH-JKMN``)."""
    return "-".join(raw[index : index + 4] for index in range(0, len(raw), 4))


def code_key(typed: str | None, length: int) -> str | None:
    """A code as people type it, the way it is hashed: small letters, dashes and spaces are all the same. ``None``
    when it cannot be a code of ``length`` (then it may be a one-time code of the sign-in)."""
    clean = "".join(char for char in (typed or "") if char not in " -\t").upper()
    if len(clean) != length or any(char not in ALPHABET for char in clean):
        return None
    return clean


def state_ok(state: str | None) -> bool:
    return bool(state) and _STATE.fullmatch(state or "") is not None


def challenge_ok(challenge: str | None) -> bool:
    return bool(challenge) and _CHALLENGE.fullmatch(challenge or "") is not None


def pkce_ok(verifier: str | None, challenge: str) -> bool:
    """RFC 7636 S256: ``BASE64URL(SHA256(verifier))`` without padding equals the challenge (fixed time)."""
    if not verifier or _VERIFIER.fullmatch(verifier) is None:
        return False
    made = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    return same(made, challenge)
