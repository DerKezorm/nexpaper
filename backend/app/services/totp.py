"""The second factor: time-based one-time codes (RFC 6238) plus recovery codes. Taken over from nextrmnl.

* The seed is stored encrypted with the server secret (``security.encrypt_secret``), the recovery codes as HMACs with
  a key of the server's (``h1:`` and hex): whoever reads the database alone cannot test guesses against them. Lists
  made before that hold plain SHA-256 hashes; both forms are accepted, and every new list is made in the new one.
  Seed and codes are shown once, at enrolment, and never logged.
* Enrolment takes two steps. ``begin_enrolment`` draws a seed and keeps it in memory for ten minutes; confirming
  needs a code from the app (proves the app holds the seed) and the account's password (proves the person at the
  keyboard is the owner). Only then is the seed stored.
* A sign-in with a second factor takes two steps as well. The password step opens nothing: it parks the sign-in in
  memory under a random token and hands the browser that token in a cookie. The code step turns it into the
  session. Five wrong codes end the pending sign-in; every wrong code counts against the account like a wrong
  password, and the password step does not reset that count (only a passed code does), so knowing the password is
  no way around the lockout.
* A code counts once. The time step of the last accepted code is stored, and a code at or before that step is
  refused: something read over a shoulder cannot be replayed within its thirty seconds.

Implemented here rather than with a library: RFC 6238 is thirty lines, and the tests hold the RFC's own vectors.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import secrets
import struct
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import quote

import segno
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models import SIGN_IN_OIDC, Account, Passkey
from ..security import decrypt_secret, encrypt_secret, server_key
from . import settings_service

ISSUER = "nexpaper"
STEP_SECONDS = 30
DIGITS = 6
#: Steps before and after the current one that are still accepted: clocks drift, people are slow.
WINDOW = 1
SEED_BYTES = 20
ENROLMENT_SECONDS = 600
PENDING_SECONDS = 300
#: Wrong codes before a pending sign-in is thrown away and the password has to be given again.
MAX_ATTEMPTS = 5
RECOVERY_CODES = 8
#: No 0, o, 1, l, i: the codes get typed from paper.
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
RECOVERY_LENGTH = 10


# --- Codes ------------------------------------------------------------------------------------------------------------


def generate_seed() -> str:
    """A fresh seed, base32 without padding, the way authenticator apps take it."""
    return base64.b32encode(secrets.token_bytes(SEED_BYTES)).decode("ascii").rstrip("=")


class SeedUnreadable(Exception):
    """The stored seed cannot be opened: the server secret is not the one that sealed it."""


def _seed_bytes(seed: str) -> bytes:
    cleaned = seed.strip().replace(" ", "").upper()
    if not cleaned:
        # An empty seed would make every code computable by anyone; it must never verify anything.
        raise SeedUnreadable()
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def code_at(seed: str, moment: float, step: int = STEP_SECONDS, digits: int = DIGITS) -> str:
    """The code for a point in time, RFC 6238 with HMAC-SHA1."""
    counter = int(moment) // step
    digest = hmac.new(_seed_bytes(seed), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % (10**digits)).zfill(digits)


def normalize_code(code: str) -> str:
    return code.strip().replace(" ", "").replace("-", "")


def verify_code(seed: str, code: str, *, after_step: int = 0, now: float | None = None) -> int | None:
    """The time step the code belongs to, or None. Steps at or before ``after_step`` are refused (replay)."""
    typed = normalize_code(code)
    if len(typed) != DIGITS or not typed.isdigit():
        return None
    moment = time.time() if now is None else now
    current = int(moment) // STEP_SECONDS
    matched: int | None = None
    # Every candidate is compared, in constant time each, so that the timing does not tell which one matched.
    for candidate in range(current - WINDOW, current + WINDOW + 1):
        expected = code_at(seed, candidate * STEP_SECONDS)
        if hmac.compare_digest(expected, typed) and candidate > after_step:
            matched = candidate
    return matched


def provisioning_uri(seed: str, account_name: str) -> str:
    label = quote(f"{ISSUER}:{account_name}", safe=":")
    return f"otpauth://totp/{label}?secret={seed}&issuer={ISSUER}&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"


def qr_svg(uri: str) -> str:
    """The QR code as SVG, dark modules on white with a quiet zone, so that a phone reads it on a dark page too.

    With the SVG namespace: the page shows it as a ``data:`` image, and a browser draws an SVG in an ``<img>`` only
    when it names its namespace (nextrmnl showed a broken image without it)."""
    out = io.BytesIO()
    code = segno.make(uri, error="m")
    code.save(out, kind="svg", scale=4, dark="#111827", light="#ffffff", border=4, xmldecl=False, svgns=True)
    return out.getvalue().decode("utf-8")


# --- Recovery codes ---------------------------------------------------------------------------------------------------


def generate_recovery_codes(count: int = RECOVERY_CODES) -> list[str]:
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LENGTH))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


#: Marks a recovery code stored as an HMAC; a list entry without it is a SHA-256 hash from before.
RECOVERY_MARK = "h1:"


def _cleaned(code: str) -> str:
    return code.strip().replace("-", "").replace(" ", "").lower()


def hash_recovery(code: str) -> str:
    """The form a recovery code is stored in: an HMAC-SHA256 with a key derived from the server's secret."""
    key = hashlib.sha256(b"nexpaper-recovery-codes:" + server_key()).digest()
    return RECOVERY_MARK + hmac.new(key, _cleaned(code).encode("utf-8"), hashlib.sha256).hexdigest()


def legacy_hash_recovery(code: str) -> str:
    """The form before: a plain SHA-256. Only to recognise lists made then."""
    return hashlib.sha256(_cleaned(code).encode("utf-8")).hexdigest()


def recovery_hashes(codes: list[str]) -> str:
    return json.dumps([hash_recovery(code) for code in codes])


def load_recovery(stored: str) -> list[str]:
    try:
        data = json.loads(stored or "[]")
    except ValueError:
        return []
    return [entry for entry in data if isinstance(entry, str)] if isinstance(data, list) else []


def use_recovery(stored: str, code: str) -> str | None:
    """The stored list without the used code, or None when the code is not in it."""
    hashes = load_recovery(stored)
    wanted = (hash_recovery(code), legacy_hash_recovery(code))
    remaining = [entry for entry in hashes if not any(hmac.compare_digest(entry, form) for form in wanted)]
    if len(remaining) == len(hashes):
        return None
    return json.dumps(remaining)


def passkey_count(db: Session, account_id: int) -> int:
    return int(db.scalar(select(func.count()).select_from(Passkey).where(Passkey.user_id == account_id)) or 0)


def has_second_factor(db: Session, account: Account) -> bool:
    """A code from an app, or a passkey."""
    return bool(account.totp_secret_enc) or passkey_count(db, account.id) > 0


def provider_only(account: Account) -> bool:
    """The account signs in through a provider only: it has no password here."""
    return account.sign_in == SIGN_IN_OIDC and not account.password_hash


def provider_checks(_db: Session, account: Account) -> bool:
    """"Require a second factor" does not reach this account here (Bauplan 01, "Zweiter Faktor"): it signs in through a
    provider only (the provider's way in is the only one; its own second factor, if it has one, is still asked after a
    provider that does not check it), or the session that asks came in through a provider whose entry checks the
    second factor itself (``second_factor_by_provider``). The same account with its password is asked as before."""
    return provider_only(account) or bool(getattr(account, "second_factor_by_provider", False))


def setup_required(db: Session, account: Account) -> bool:
    """The operator requires a second factor (the default), and this account has none yet. Such an account sets it up
    before it reaches anything else; not an account through a provider only, nor a session through a provider that
    checks one (``provider_checks``)."""
    return (
        bool(settings_service.get(db, "two_factor_required"))
        and not provider_checks(db, account)
        and not has_second_factor(db, account)
    )


def keys_wait(db: Session, account: Account) -> bool:
    """A device token or an API key of this account waits: the operator requires a second factor, the account has a
    password and none of its own. A key has no provider behind it, so a session through a provider that checks the
    second factor does not free it."""
    return (
        bool(settings_service.get(db, "two_factor_required"))
        and not provider_only(account)
        and not has_second_factor(db, account)
    )


def claim_step(db: Session, account_id: int, step: int) -> bool:
    """Takes the time step of an accepted code, only if it is later than the last one taken: of two requests with the
    same code at the same moment exactly one wins (checked and written in one statement)."""
    result = db.execute(
        update(Account).where(Account.id == account_id, Account.totp_last_step < step).values(totp_last_step=step)
    )
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0) == 1


def claim_recovery(db: Session, account_id: int, before: str, after: str) -> bool:
    """Writes the list without the used code, only if nobody changed the list since it was read: a recovery code
    counts once, also for two requests at the same moment."""
    result = db.execute(
        update(Account).where(Account.id == account_id, Account.totp_recovery == before).values(totp_recovery=after)
    )
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0) == 1


# --- Seeds at rest ----------------------------------------------------------------------------------------------------


def seal_seed(seed: str) -> str:
    return encrypt_secret(seed)


def open_seed(stored: str) -> str:
    """The seed, or ``SeedUnreadable`` when the server secret changed: then the second factor fails closed, the way
    the OIDC secret does, instead of accepting codes derived from nothing."""
    seed = decrypt_secret(stored)
    if not seed:
        raise SeedUnreadable()
    return seed


# --- What waits in memory ---------------------------------------------------------------------------------------------


@dataclass
class PendingSignIn:
    account_id: int
    expires: float
    attempts: int = 0
    #: "Stay signed in on this device", as ticked at the password; the code step may change it.
    remember: bool = True


@dataclass
class _Enrolment:
    seed: str
    expires: float


@dataclass
class _Store:
    enrolments: dict[int, _Enrolment] = field(default_factory=dict)
    pending: dict[str, PendingSignIn] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


_store = _Store()


def begin_enrolment(account_id: int) -> str:
    seed = generate_seed()
    with _store.lock:
        _store.enrolments[account_id] = _Enrolment(seed=seed, expires=time.monotonic() + ENROLMENT_SECONDS)
    return seed


def pending_seed(account_id: int) -> str | None:
    with _store.lock:
        entry = _store.enrolments.get(account_id)
        if entry is None:
            return None
        if entry.expires <= time.monotonic():
            del _store.enrolments[account_id]
            return None
        return entry.seed


def drop_enrolment(account_id: int) -> None:
    with _store.lock:
        _store.enrolments.pop(account_id, None)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def start_pending(account_id: int, remember: bool = True) -> str:
    """Parks the password step and returns the token for the cookie."""
    token = secrets.token_urlsafe(32)
    with _store.lock:
        # One pending sign-in per account: a second password step replaces the first.
        for key, entry in list(_store.pending.items()):
            if entry.account_id == account_id:
                del _store.pending[key]
        _store.pending[_hash(token)] = PendingSignIn(
            account_id=account_id, expires=time.monotonic() + PENDING_SECONDS, remember=remember
        )
    return token


def get_pending(token: str | None) -> PendingSignIn | None:
    if not token:
        return None
    with _store.lock:
        entry = _store.pending.get(_hash(token))
        if entry is None:
            return None
        if entry.expires <= time.monotonic():
            del _store.pending[_hash(token)]
            return None
        return entry


def fail_pending(token: str) -> bool:
    """Counts a wrong code. Returns whether the pending sign-in still stands."""
    with _store.lock:
        entry = _store.pending.get(_hash(token))
        if entry is None:
            return False
        entry.attempts += 1
        if entry.attempts >= MAX_ATTEMPTS:
            del _store.pending[_hash(token)]
            return False
        return True


def finish_pending(token: str) -> PendingSignIn | None:
    """Takes the pending sign-in out of the store; the caller turns it into a session."""
    with _store.lock:
        return _store.pending.pop(_hash(token), None)


def forget_account(account_id: int) -> None:
    """Nothing waits for an account whose second factor was just reset or that was deleted."""
    with _store.lock:
        _store.enrolments.pop(account_id, None)
        for key, entry in list(_store.pending.items()):
            if entry.account_id == account_id:
                del _store.pending[key]


def sweep() -> int:
    now = time.monotonic()
    with _store.lock:
        stale_enrolments = [key for key, entry in _store.enrolments.items() if entry.expires <= now]
        stale_pending = [key for key, entry in _store.pending.items() if entry.expires <= now]
        for key in stale_enrolments:
            del _store.enrolments[key]
        for key in stale_pending:
            del _store.pending[key]
    return len(stale_enrolments) + len(stale_pending)


def forget() -> None:
    """For the tests: nothing waits."""
    with _store.lock:
        _store.enrolments.clear()
        _store.pending.clear()
