"""Passkeys: signing in with finger, face or the device's PIN, without a password, and as a second factor.

Built on ``webauthn`` (3.0.1) as nexpaper and nexdiary do: a key that lives on the device (discoverable), user
verification required, signing in without a username (the browser offers whichever passkey of this site it holds).
The relying party is the public address of the app: its host is the ``rp_id``, its origin (with its port) the one the
browser must report; https, or http on ``localhost`` only (browsers offer passkeys nowhere else). Challenges live five
minutes in memory and count once. The sign count only moves forward (``claim_counter``).

The challenges never lock anybody out: a sign-in (nobody signed in yet) holds at most 20 open ones per sender, the
sender's oldest goes for a new one, and when the memory is full the oldest of all go; adding a passkey keeps three per
account apart from them. Adding a passkey is confirmed with the password (or a fresh sign-in, ``actor_confirmed``).

The operator turns passkeys on or off for the server (``PasskeyStore.passkeys_allowed``, on by default); off, no new
passkey is added and none signs in, but none is deleted.
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from . import common, factor
from .common import log
from .errors import AccountError
from .model import Account, AccountId, Store
from .model2 import FactorStore, Passkey, PasskeyStore

CHALLENGE_SECONDS = 300
MAX_PASSKEYS = 10
NAME_MAX = 60
#: Open sign-in challenges at most; past that the oldest go.
MAX_OPEN = 5000
#: Open sign-in challenges per sender; past that the sender's oldest goes.
PER_SENDER = 20
#: Open challenges for adding a passkey, per account.
PER_ACCOUNT = 3
LOCALHOST = "localhost"


class AppStore(Store, FactorStore, PasskeyStore, Protocol):
    """One store of the app for accounts, second factor and passkeys."""


@dataclass(frozen=True)
class Party:
    """Where passkeys belong: the host of the public address, and its origin."""

    rp_id: str
    origin: str


def party(public_url: str, origin: str = "", request_url: str = "") -> Party:
    """The relying party of an app from its public address (``https://notes.example.com``). ``origin`` is the
    ``Origin`` header of the request: a page on ``localhost`` (a secure context without https, often on another port
    than the public address) gets exactly that host and port; any other origin changes nothing. Browsers send no
    ``Origin`` with a GET on the same page: then ``request_url`` (the address the request came to, path and all)
    stands in for it, by its scheme, host and port only. The page shows the passkey section only where
    ``window.isSecureContext`` holds."""
    seen = urlsplit((origin or "").strip())
    if not (origin or "").strip() and (request_url or "").strip():
        asked = urlsplit(request_url.strip())
        seen = urlsplit(f"{asked.scheme}://{asked.netloc}")
    if (seen.hostname or "").lower() == LOCALHOST and seen.scheme in ("http", "https") and not seen.path.strip("/"):
        public_url = f"{seen.scheme}://{seen.netloc}"
    parts = urlsplit(public_url.strip())
    host = (parts.hostname or "").lower()
    if not host or parts.scheme not in ("http", "https"):
        raise AccountError("passkeys_off", "Passkeys need the public address of the app.", 409)
    if parts.scheme != "https" and host != LOCALHOST:
        raise AccountError("passkeys_off", "Passkeys need the app on https (or localhost).", 409)
    return Party(host, f"{parts.scheme}://{parts.netloc.lower()}")


@dataclass
class _Held:
    challenge: bytes
    owner: str
    until: float


_lock = threading.Lock()
#: Sign-ins by token, oldest first; ``owner`` is the sender.
_sign_ins: OrderedDict[str, _Held] = OrderedDict()
#: Additions by token, oldest first; ``owner`` is the account.
_adds: OrderedDict[str, _Held] = OrderedDict()


def _drop_expired(table: OrderedDict[str, _Held], now: float) -> None:
    while table:
        key, held = next(iter(table.items()))
        if held.until >= now:
            return
        table.pop(key, None)


def _keep(table: OrderedDict[str, _Held], key: str, held: _Held, per_owner: int) -> None:
    now = time.monotonic()
    with _lock:
        _drop_expired(table, now)
        if held.owner:  # without a sender only the whole memory limits: no shared count for the unknown
            mine = [old for old, entry in table.items() if entry.owner == held.owner]
            for old in mine[: max(0, len(mine) - per_owner + 1)]:
                table.pop(old, None)
        while len(table) >= MAX_OPEN:
            table.popitem(last=False)
        table[key] = held


def _take(table: OrderedDict[str, _Held], key: str) -> _Held | None:
    with _lock:
        held = table.pop(key, None)
    if held is None or held.until < time.monotonic():
        return None
    return held


def _allowed(store: AppStore) -> None:
    if not store.passkeys_allowed():
        raise AccountError("passkeys_off", "Passkeys are turned off on this server.", 409)


def clean_name(name: str) -> str:
    """One line, no control characters, at most ``NAME_MAX``; "Passkey" when nothing is left."""
    text = " ".join("".join(char if char.isprintable() else " " for char in (name or "")).split())
    return text[:NAME_MAX] or "Passkey"


def _too_many() -> AccountError:
    return AccountError("too_many_passkeys", f"At most {MAX_PASSKEYS} passkeys per account.", 409)


def begin_register(
    store: AppStore,
    account_id: AccountId,
    where: Party,
    *,
    app_name: str,
    password: str = "",
    actor_confirmed: bool = False,
) -> tuple[str, str]:
    """A new passkey for the signed-in account, confirmed with its password (or a fresh sign-in at the provider for an
    account without one, or by the app: ``actor_confirmed``, as in a session that can only set up a factor): the token
    for the browser's cookie and the options (JSON). The account's user handle is stored here and committed, so that
    ``finish_register`` in another request finds the same."""
    _allowed(store)
    account = common.account_or_404(store, account_id)
    factor.confirmed(store, account, password, actor_confirmed, without_password=True)
    keys = store.passkeys_of(account.id)
    if len(keys) >= MAX_PASSKEYS:
        raise _too_many()
    handle = store.user_handle(account.id)
    store.commit()
    token = secrets.token_urlsafe(32)
    challenge = secrets.token_bytes(32)
    _keep(_adds, token, _Held(challenge, str(account.id), time.monotonic() + CHALLENGE_SECONDS), PER_ACCOUNT)
    options = generate_registration_options(
        rp_id=where.rp_id,
        rp_name=app_name,
        user_id=handle,
        user_name=account.username,
        user_display_name=account.display_name or account.username,
        challenge=challenge,
        timeout=CHALLENGE_SECONDS * 1000,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=key.credential_id) for key in keys],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    return token, options_to_json(options)


def finish_register(
    store: AppStore, account_id: AccountId, token: str, credential: dict[str, Any], where: Party, *, name: str = ""
) -> Passkey:
    """The browser's answer to ``begin_register``: the new passkey, stored."""
    _allowed(store)
    held = _take(_adds, token or "")
    if held is None or held.owner != str(account_id):
        raise AccountError("passkey_expired", "That took too long. Start again.", 410)
    account = common.account_or_404(store, account_id)
    if len(store.passkeys_of(account.id)) >= MAX_PASSKEYS:
        raise _too_many()
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=held.challenge,
            expected_rp_id=where.rp_id,
            expected_origin=where.origin,
            require_user_verification=True,
        )
    except Exception as error:  # webauthn raises many kinds for a bad answer
        log().warning("Passkey not added name=%s: %s", account.username, error.__class__.__name__)
        raise AccountError("passkey_invalid", "The browser's answer did not check out.", 422) from error
    if store.find_passkey(verified.credential_id) is not None:
        raise AccountError("passkey_exists", "This passkey is registered already.", 409)
    passkey = Passkey(
        uid=secrets.token_hex(16),
        account_id=account.id,
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        name=clean_name(name),
        created_at=common.utcnow(),
    )
    store.add_passkey(passkey)
    store.commit()
    log().info("Passkey added name=%s", account.username)
    return passkey


def begin_sign_in(store: AppStore, where: Party, *, sender: str = "") -> tuple[str, str]:
    """A sign-in with a passkey and nothing else: the token for the browser's cookie and the options (JSON).
    ``sender`` is the address as the brake counts it (``brake.client_address``): at most 20 open sign-ins per sender."""
    _allowed(store)
    token = secrets.token_urlsafe(32)
    challenge = secrets.token_bytes(32)
    _keep(_sign_ins, token, _Held(challenge, sender, time.monotonic() + CHALLENGE_SECONDS), PER_SENDER)
    options = generate_authentication_options(
        rp_id=where.rp_id,
        challenge=challenge,
        timeout=CHALLENGE_SECONDS * 1000,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return token, options_to_json(options)


def _decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _credential_id(credential: dict[str, Any]) -> bytes | None:
    raw = credential.get("rawId") or credential.get("id")
    if not isinstance(raw, str) or len(raw) > 1400:
        return None
    try:
        return _decode(raw)
    except (ValueError, binascii.Error):
        return None


def refused() -> AccountError:
    return AccountError("passkey_invalid", "This passkey did not sign you in.", 401)


def finish_sign_in(store: AppStore, token: str, credential: dict[str, Any], where: Party) -> Account:
    """The account whose passkey answered. The challenge counts once, whatever the answer; a blocked account hears so
    only after a valid answer. The app starts the session (a passkey is both factors: no code is asked)."""
    _allowed(store)
    held = _take(_sign_ins, token or "")
    if held is None:
        raise AccountError("passkey_expired", "That took too long. Start again.", 410)
    credential_id = _credential_id(credential)
    key = store.find_passkey(credential_id) if credential_id else None
    account = store.get_account(key.account_id) if key is not None else None
    if key is None or account is None:
        log().warning("Passkey sign-in with an unknown passkey")
        raise refused()
    response = credential.get("response")
    handle = response.get("userHandle") if isinstance(response, dict) else None
    if handle:
        try:
            same = secrets.compare_digest(_decode(str(handle)), store.user_handle(account.id))
        except (ValueError, binascii.Error):
            same = False
        if not same:
            log().warning("Passkey sign-in with the handle of another account name=%s", account.username)
            raise refused()
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=held.challenge,
            expected_rp_id=where.rp_id,
            expected_origin=where.origin,
            credential_public_key=key.public_key,
            credential_current_sign_count=key.sign_count,
            require_user_verification=True,
        )
    except Exception as error:  # webauthn raises many kinds for a bad answer
        log().warning("Passkey refused name=%s: %s", account.username, error.__class__.__name__)
        raise refused() from error
    if not store.claim_counter(key.uid, key.sign_count, verified.new_sign_count):
        store.rollback()
        raise refused()
    store.commit()
    if account.blocked:
        raise AccountError("account_blocked", "This account is blocked. Ask the operator.", 403)
    log().info("Signed in with a passkey name=%s", account.username)
    return account


def remove(
    store: AppStore, account_id: AccountId, uid: str, *, password: str = "", actor_confirmed: bool = False
) -> bool:
    """The owner removes one of their passkeys (not the last factor where one is required)."""
    account = common.account_or_404(store, account_id)
    factor.confirmed(store, account, password, actor_confirmed, without_password=True)
    required = store.factor_required() and not factor.switched_off()
    if required and not store.totp_seed(account.id) and len(store.passkeys_of(account.id)) <= 1:
        raise AccountError("factor_required", "A second factor is required here; set up another one first.", 409)
    removed = store.remove_passkey(account.id, uid)
    store.commit()
    return removed


def view(passkey: Passkey) -> dict[str, object]:
    """What the profile lists of a passkey (never the key itself)."""
    return {
        "uid": passkey.uid,
        "name": passkey.name,
        "created_at": passkey.created_at.isoformat(),
        "last_used_at": passkey.last_used_at.isoformat() if passkey.last_used_at else None,
    }


def options_json(options: str) -> dict[str, Any]:
    """The options as a dict (for apps that wrap them into their answer)."""
    return dict(json.loads(options))


def forget() -> None:
    """Tests: no open challenge left."""
    with _lock:
        _sign_ins.clear()
        _adds.clear()
