"""Passkeys (WebAuthn), checked by ``py_webauthn`` as in nextrmnl, but here a passkey is a way in of its own: it
signs in without a password and without a code (a discoverable credential, the user verified on the device by finger,
face or PIN), and it counts as a second factor.

* **Who the browser talks to** (relying party) comes from the public address the operator set, never from the
  ``Host`` header a request brings: a passkey made for one name must not be asked for under a name a stranger chose.
  Without a public address passkeys work on ``localhost`` only. On plain ``http`` elsewhere browsers do not offer them.
* **Challenges** are 32 random bytes, kept in memory for five minutes and taken out when used: each counts once. The
  challenge of a sign-in is bound to a short-lived cookie of that browser, the one of adding a passkey to the
  session that asked. Two stores, so that nobody who is not signed in can crowd out the
  rest: the challenges of sign-ins (no account needed, so at most ``PER_ADDRESS`` open per sender, and the oldest
  go when the whole store is full) and the challenges of signed-in people (``PER_ACCOUNT`` per account).
* **The counter** an authenticator keeps is checked: an answer that does not count up is refused (a copied key), and
  it is written only where it still stood as read.

Nothing about a challenge reaches the log; a passkey shows up there by its name only.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .. import clock
from ..models import Account, Passkey
from . import settings_service

logger = logging.getLogger("nexpaper.auth")

CHALLENGE_SECONDS = 300
MAX_PASSKEYS = 10
NAME_MAX = 64
LOCALHOST = "localhost"
#: Sign-in challenges waiting at once, from everybody: a flood of "begin" cannot fill the memory. Past it the oldest go.
MAX_ANONYMOUS = 10_000
#: Sign-in challenges one sender may have open, and how many times it may ask before it rests (every "begin" counts,
#: see the route).
PER_ADDRESS = 20
BEGINS_PER_ADDRESS = 30
#: Challenges one signed-in account may have open (adding; one per session).
PER_ACCOUNT = 20


class PasskeyError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Party:
    rp_id: str
    #: The one origin the browser must report; None: any ``localhost`` (no public address set).
    origin: str | None


@dataclass
class _Challenge:
    value: bytes
    expires: float
    #: Who asked, for the limit per sender (sign-ins only).
    owner: str = ""


_lock = threading.Lock()
#: Sign-ins: key -> challenge, oldest first. Nobody is signed in, so the sender is all there is to count by.
_anonymous: dict[str, _Challenge] = {}
#: Signed-in people: account id -> (kind and session -> challenge).
_accounts: dict[int, dict[str, _Challenge]] = {}


def party(db: Session) -> Party:
    """The relying party, from the operator's public address. ``PasskeyError`` where browsers offer no passkeys."""
    base = settings_service.public_url(db)
    if not base:
        return Party(rp_id=LOCALHOST, origin=None)
    parts = urlsplit(base)
    host = (parts.hostname or "").lower()
    if not host:
        raise PasskeyError("passkeys_need_https", "Passkeys need nexpaper on https.", 409)
    if parts.scheme != "https" and host != LOCALHOST:
        raise PasskeyError("passkeys_need_https", "Passkeys need nexpaper on https (or localhost).", 409)
    return Party(rp_id=host, origin=f"{parts.scheme}://{parts.netloc.lower()}")


def available(db: Session, host: str | None = None) -> bool:
    """Whether the sign-in page offers passkeys. Under a public https address always; without one only where the page
    is open on ``localhost`` (``host``), as browsers offer nothing for another name."""
    try:
        party(db)
    except PasskeyError:
        return False
    if not settings_service.public_url(db):
        return (host or "").lower() == LOCALHOST
    return True


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _reported_origin(credential: dict[str, Any]) -> str:
    """The origin the browser wrote into its answer; empty when it cannot be read."""
    try:
        data = json.loads(_b64decode(str(credential["response"]["clientDataJSON"])))
        return str(data.get("origin", ""))[:200]
    except (KeyError, TypeError, ValueError, binascii.Error):
        return ""


def _expected_origin(where: Party, credential: dict[str, Any]) -> str:
    if where.origin is not None:
        return where.origin
    # Without a public address: only localhost, on whatever port the operator runs it. Anything else cannot pass.
    reported = _reported_origin(credential)
    parts = urlsplit(reported)
    if parts.scheme in ("http", "https") and (parts.hostname or "") == LOCALHOST and not parts.path:
        return reported
    return "https://" + LOCALHOST


def _keep_anonymous(key: str, owner: str) -> bytes:
    """A challenge for a sign-in. A sender holds at most ``PER_ADDRESS`` open ones (``PasskeyError`` 429 past that);
    when the whole store is full the oldest go, so that sign-ins never stop for want of room."""
    value = secrets.token_bytes(32)
    now = time.monotonic()
    with _lock:
        mine = [k for k, entry in _anonymous.items() if entry.owner == owner and entry.expires > now]
        if len(mine) >= PER_ADDRESS:
            raise PasskeyError("too_many_attempts", "Too many attempts. Try again later.", 429)
        if len(_anonymous) >= MAX_ANONYMOUS:
            for stale in [k for k, entry in _anonymous.items() if entry.expires <= now]:
                del _anonymous[stale]
            while len(_anonymous) >= MAX_ANONYMOUS:
                del _anonymous[next(iter(_anonymous))]
        _anonymous[key] = _Challenge(value, now + CHALLENGE_SECONDS, owner)
    return value


def _keep_for_account(account_id: int, key: str) -> bytes:
    """A challenge for adding a passkey: in the account's own place. A session asking again
    replaces its own; past ``PER_ACCOUNT`` the account's expired ones go, then its oldest."""
    value = secrets.token_bytes(32)
    now = time.monotonic()
    with _lock:
        mine = _accounts.setdefault(account_id, {})
        mine.pop(key, None)
        for stale in [k for k, entry in mine.items() if entry.expires <= now]:
            del mine[stale]
        while len(mine) >= PER_ACCOUNT:
            del mine[next(iter(mine))]
        mine[key] = _Challenge(value, now + CHALLENGE_SECONDS)
    return value


def _take_anonymous(key: str) -> bytes | None:
    with _lock:
        entry = _anonymous.pop(key, None)
    if entry is None or entry.expires <= time.monotonic():
        return None
    return entry.value


def _take_for_account(account_id: int, key: str) -> bytes | None:
    with _lock:
        mine = _accounts.get(account_id)
        entry = mine.pop(key, None) if mine else None
        if mine is not None and not mine:
            del _accounts[account_id]
    if entry is None or entry.expires <= time.monotonic():
        return None
    return entry.value


def _sign_in_key(token: str) -> str:
    return "sign-in:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def listing(db: Session, account_id: int) -> list[Passkey]:
    return list(db.scalars(select(Passkey).where(Passkey.user_id == account_id).order_by(Passkey.created_at)))


def _descriptors(keys: list[Passkey]) -> list[PublicKeyCredentialDescriptor]:
    return [PublicKeyCredentialDescriptor(id=key.credential_id) for key in keys]


def _handle(db: Session, account: Account) -> bytes:
    """The account's user handle, made at its first passkey."""
    if not account.passkey_handle:
        account.passkey_handle = secrets.token_hex(32)
        db.commit()
    return bytes.fromhex(account.passkey_handle)


# --- Adding a passkey -----------------------------------------------------------------------------------------------


def begin_registration(db: Session, account: Account, session_uid: str) -> str:
    where = party(db)
    keys = listing(db, account.id)
    if len(keys) >= MAX_PASSKEYS:
        raise PasskeyError("too_many_passkeys", f"At most {MAX_PASSKEYS} passkeys per account.", 409)
    challenge = _keep_for_account(account.id, "add:" + session_uid)
    options = generate_registration_options(
        rp_id=where.rp_id,
        rp_name="nexpaper",
        user_id=_handle(db, account),
        user_name=account.name,
        user_display_name=account.display_name or account.name,
        challenge=challenge,
        timeout=CHALLENGE_SECONDS * 1000,
        exclude_credentials=_descriptors(keys),
        # A way in of its own: the key lives on the device (discoverable) and asks for finger, face or PIN.
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    return options_to_json(options)


def finish_registration(
    db: Session, account: Account, session_uid: str, credential: dict[str, Any], name: str
) -> Passkey:
    where = party(db)
    challenge = _take_for_account(account.id, "add:" + session_uid)
    if challenge is None:
        raise PasskeyError("passkey_expired", "That took too long. Start again.", 410)
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=where.rp_id,
            expected_origin=_expected_origin(where, credential),
            require_user_verification=True,
        )
    except (WebAuthnException, KeyError, TypeError, ValueError) as exc:
        logger.warning("Passkey not added name=%s: %s", account.name, type(exc).__name__)
        raise PasskeyError("passkey_invalid", "The browser's answer did not check out.") from exc
    if db.scalar(select(Passkey.id).where(Passkey.credential_id == verified.credential_id)) is not None:
        raise PasskeyError("passkey_exists", "This passkey is already registered.", 409)
    if len(listing(db, account.id)) >= MAX_PASSKEYS:
        raise PasskeyError("too_many_passkeys", f"At most {MAX_PASSKEYS} passkeys per account.", 409)
    row = Passkey(
        uid=secrets.token_hex(16),
        user_id=account.id,
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        name=clean_name(name),
        created_at=clock.now(),
    )
    db.add(row)
    db.commit()
    logger.info("Passkey added name=%s passkey=%s", account.name, row.name)
    return row


def clean_name(name: str) -> str:
    """One line, no control characters, at most ``NAME_MAX``; "Passkey" when nothing is left."""
    text = " ".join("".join(char for char in name if char.isprintable()).split())
    return text[:NAME_MAX] or "Passkey"


# --- Answers to a challenge ----------------------------------------------------------------------------------------


class Refused(Exception):
    """A passkey answer that does not let anybody in. ``account`` is set when the passkey belongs to one: the failure
    then counts against that account as well."""

    def __init__(self, reason: str, account: Account | None = None) -> None:
        super().__init__(reason)
        self.reason, self.account = reason, account


def _credential_id(credential: dict[str, Any]) -> bytes | None:
    raw = credential.get("rawId") or credential.get("id")
    if not isinstance(raw, str) or len(raw) > 1400:
        return None
    try:
        return _b64decode(raw)
    except (ValueError, binascii.Error):
        return None


def _check(db: Session, where: Party, challenge: bytes, key: Passkey, account: Account,
           credential: dict[str, Any]) -> None:
    """Verifies the signed answer of ``key`` and counts its use; ``Refused`` else."""
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=where.rp_id,
            expected_origin=_expected_origin(where, credential),
            credential_public_key=key.public_key,
            credential_current_sign_count=key.sign_count,
            require_user_verification=True,
        )
    except (WebAuthnException, KeyError, TypeError, ValueError) as exc:
        if "sign count" in str(exc).lower():
            logger.warning("Passkey refused, its counter did not count up (a copied key?) name=%s passkey=%s",
                           account.name, key.name)
            raise Refused("counter", account) from exc
        logger.warning("Passkey refused name=%s passkey=%s: %s", account.name, key.name, type(exc).__name__)
        raise Refused("invalid", account) from exc
    # Written only where the counter still stands as read: two answers at once cannot both count.
    result = db.execute(
        update(Passkey)
        .where(Passkey.id == key.id, Passkey.sign_count == key.sign_count)
        .values(sign_count=verified.new_sign_count, last_used_at=clock.now())
    )
    db.commit()
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        raise Refused("raced", account)


def begin_sign_in(db: Session, address: str) -> tuple[str, str]:
    """A sign-in with a passkey and nothing else: the token for the browser's cookie, and the options. The browser
    offers whichever passkey of this site it holds. ``address`` is the sender, for the limit of open challenges."""
    where = party(db)
    token = secrets.token_urlsafe(32)
    challenge = _keep_anonymous(_sign_in_key(token), address)
    options = generate_authentication_options(
        rp_id=where.rp_id,
        challenge=challenge,
        timeout=CHALLENGE_SECONDS * 1000,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return token, options_to_json(options)


def finish_sign_in(db: Session, token: str | None, credential: dict[str, Any]) -> Account:
    """The account whose passkey answered, or ``Refused``. The challenge counts once, whatever the answer."""
    where = party(db)
    challenge = _take_anonymous(_sign_in_key(token)) if token else None
    if challenge is None:
        raise Refused("expired")
    credential_id = _credential_id(credential)
    key = db.scalar(select(Passkey).where(Passkey.credential_id == credential_id)) if credential_id else None
    if key is None:
        logger.warning("Passkey sign-in with an unknown passkey")
        raise Refused("unknown")
    account = db.get(Account, key.user_id)
    if account is None:
        raise Refused("unknown")
    handle = credential.get("response", {}).get("userHandle") if isinstance(credential.get("response"), dict) else None
    if handle:
        try:
            matches = secrets.compare_digest(_b64decode(str(handle)), bytes.fromhex(account.passkey_handle or ""))
        except (ValueError, binascii.Error):
            matches = False
        if not matches:
            logger.warning("Passkey sign-in with a user handle of another account name=%s", account.name)
            raise Refused("handle", account)
    _check(db, where, challenge, key, account, credential)
    return account


# --- Keeping ---------------------------------------------------------------------------------------------------------


def remove(db: Session, account_id: int, uid: str) -> Passkey | None:
    row = db.scalar(select(Passkey).where(Passkey.uid == uid, Passkey.user_id == account_id))
    if row is None:
        return None
    db.delete(row)
    db.commit()
    return row


def remove_all(db: Session, account_id: int) -> int:
    rows = listing(db, account_id)
    for row in rows:
        db.delete(row)
    db.commit()
    return len(rows)


def view(row: Passkey) -> dict[str, Any]:
    return {
        "id": row.uid,
        "name": row.name,
        "created_at": row.created_at.isoformat(),
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "credential": bytes_to_base64url(row.credential_id)[:8],
    }


def sweep() -> int:
    """Challenges nobody answered go from memory."""
    now = time.monotonic()
    count = 0
    with _lock:
        for key in [key for key, entry in _anonymous.items() if entry.expires <= now]:
            del _anonymous[key]
            count += 1
        for account_id, mine in list(_accounts.items()):
            for key in [key for key, entry in mine.items() if entry.expires <= now]:
                del mine[key]
                count += 1
            if not mine:
                del _accounts[account_id]
    return count


def forget() -> None:
    """For the tests: nothing waits."""
    with _lock:
        _anonymous.clear()
        _accounts.clear()
