"""The second factor: a time-based code (TOTP), recovery codes, the sign-in that waits for the code, the operator's
reset. Passkeys are in ``passkeys``.

TOTP after RFC 6238 with HMAC-SHA1, 30 seconds, 6 digits, one step either side: the values every app uses today, so
that the authenticator apps set up under the older version keep working (the seed is base32, sealed by the app).
A code counts once: the store keeps the last step with one statement that only moves forward (``claim_step``).

Recovery codes: 10 new ones (``xxxxx-xxxxx``, no 0, o, 1, l, i), stored as ``h1:`` + HMAC-SHA256 with the app's
key (``FactorStore.recovery_key``). Lists of the older versions keep working: a plain SHA-256 of the code in small
letters (most apps) or in capitals (one app) is recognised too, whatever the count.

Setting up keeps the new seed for ten minutes, sealed in the store (``FactorStore.set_pending_totp``, since 0.3.3:
a restart between the QR code and the first code loses nothing; a store without it keeps the seed in memory as
before), and makes it the factor only once a code confirmed it; nothing unconfirmed is ever a factor. The sign-in that
waits for the code is in memory for five minutes and five attempts.

Every change of a factor is confirmed: with the password (or a fresh sign-in at the provider for an account without one,
``actor_confirmed`` from the app), also when an account replaces its authenticator; wrong passwords there are braked
like sign-ins (``confirmed``). Only the very first factor of an account in a session that can only set one up needs
nothing more (the app passes ``actor_confirmed``).

Nobody must have a second factor unless the operator says so (``FactorStore.factor_required``, off by default); then
the last factor of an account cannot be taken away by its owner, and ``common.next_step`` sends an account without
one to set one up first.

The emergency hammer (since 0.3.3): ``<APP>_SECOND_FACTOR_OFF`` in the environment (or the app's hook
``AppConfig.second_factor_off``) switches the second factor off for everybody, beating "required of everybody" and
``common.next_step``; ``switched_off()`` tells the app to show "Second factor is switched off" plainly
(``account.secondFactorOff``). Nothing is deleted: without the variable every factor counts again.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import quote

from . import brake, common, config
from .common import log
from .errors import AccountError
from .model import (
    MAIL_FACTOR_RESET,
    NEXT_SESSION,
    NEXT_SHOW_CODES,
    SECOND_FACTOR_ACTIVE,
    SECOND_FACTOR_NONE,
    SECOND_FACTOR_PASSKEY,
    SECOND_FACTOR_REQUIRED,
    Account,
    AccountId,
    Mail,
    Store,
)
from .model2 import KIND_DEVICE, FactorStore, Passkey, PasskeyStore, Session

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1
SEED_BYTES = 20
ENROLMENT_SECONDS = 600
PENDING_SECONDS = 300
MAX_ATTEMPTS = 5
#: Waiting sign-ins per account at the same time (two browsers, or one that asked twice); the oldest goes.
WAITING_PER_ACCOUNT = 3
RECOVERY_CODES = 10
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
RECOVERY_LENGTH = 10
RECOVERY_MARK = "h1:"
#: The operator's dialog "Reset the second factor", as ``SECTIONS.operatorFactorReset`` in ``konten.ts``; the
#: passkey parts show only for an account with passkeys (0.3.4).
FACTOR_RESET_PARTS = ("factorResetHint", "passkeys", "factorResetPasskeys", "factorResetDevices")
FACTOR_RESET_PASSKEY_PARTS = ("passkeys", "factorResetPasskeys")


class AppStore(Store, FactorStore, PasskeyStore, Protocol):
    """One store of the app that answers the accounts, the second factor and the passkeys."""


# --- Codes ------------------------------------------------------------------------------------------------------------


def new_seed() -> str:
    """A fresh seed, base32 without padding, the way authenticator apps take it."""
    return base64.b32encode(secrets.token_bytes(SEED_BYTES)).decode("ascii").rstrip("=")


def _seed_bytes(seed: str) -> bytes:
    cleaned = (seed or "").strip().replace(" ", "").upper()
    if not cleaned:
        raise ValueError("an empty seed verifies nothing")
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def code_at(seed: str, moment: float) -> str:
    """The code for a point in time, RFC 6238 with HMAC-SHA1."""
    counter = int(moment) // STEP_SECONDS
    digest = hmac.new(_seed_bytes(seed), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % (10**DIGITS)).zfill(DIGITS)


def matching_step(seed: str, typed: str, now: float | None = None) -> int | None:
    """The time step a code belongs to, or None. Every candidate is compared in constant time."""
    code = typed.strip().replace(" ", "").replace("-", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    current = int(time.time() if now is None else now) // STEP_SECONDS
    found = None
    for step in range(current - WINDOW, current + WINDOW + 1):
        if hmac.compare_digest(code_at(seed, step * STEP_SECONDS), code):
            found = step
    return found


def provisioning_uri(seed: str, issuer: str, label: str) -> str:
    """For the QR code: ``otpauth://totp/<issuer>:<label>``, the label being the username (as today)."""
    name = quote(f"{issuer}:{label}", safe=":")
    return (
        f"otpauth://totp/{name}?secret={seed}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}"
        f"&period={STEP_SECONDS}"
    )


def new_recovery_codes() -> list[str]:
    codes = []
    for _ in range(RECOVERY_CODES):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LENGTH))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def _cleaned(code: str) -> str:
    return code.strip().replace("-", "").replace(" ", "")


def stored_form(key: bytes, code: str) -> str:
    return RECOVERY_MARK + hmac.new(key, _cleaned(code).lower().encode("utf-8"), hashlib.sha256).hexdigest()


def recognised_forms(key: bytes, code: str) -> tuple[str, ...]:
    """The forms a typed code may be stored in: the current one, and the plain SHA-256 of older versions, in small
    letters and in capitals."""
    cleaned = _cleaned(code)
    return (
        stored_form(key, code),
        hashlib.sha256(cleaned.lower().encode("utf-8")).hexdigest(),
        hashlib.sha256(cleaned.upper().encode("utf-8")).hexdigest(),
    )


# --- State ------------------------------------------------------------------------------------------------------------


def switched_off() -> bool:
    """The emergency hammer is down: nobody is asked for a second factor. The app shows ``account.secondFactorOff``
    plainly (top of the account pages and the operator's settings) while it is."""
    return config.current().second_factor_is_off()


def announce_switched_off() -> bool:
    """At start-up: a warning in the log while the hammer is down. True when it is."""
    off = switched_off()
    if off:
        log().warning("Second factor switched off for everybody by %s", config.current().second_factor_off_env)
    return off


def _required(store: FactorStore | AppStore) -> bool:
    return store.factor_required() and not switched_off()


def has_factor(store: FactorStore | AppStore, account_id: AccountId) -> bool:
    """A confirmed TOTP or a passkey."""
    if store.totp_seed(account_id):
        return True
    passkeys = getattr(store, "passkeys_of", None)
    return bool(passkeys and passkeys(account_id))


def state(store: AppStore, account_id: AccountId, *, provider_checked: bool = False) -> str:
    """What ``Store.second_factor`` answers, for an app that lets the module decide.

    ``active``: a time-based code (asked after the password). A passkey counts as a second factor: where the operator
    asks one of everybody, an account with a passkey and no authenticator answers ``passkey`` (the passkey is the
    second step, no authenticator is required of it); without the switch a passkey is a way in of its own and the
    password alone signs in as before (``none``). ``required``: the operator asks one and the account has none.

    Since 0.3.10: where the provider checks the second factor itself (``provider_checked`` for this sign-in, or the
    store's hook ``provider_checks_factor``, off by default), the switch for everybody asks nothing here: ``none``. An
    authenticator of the account's own stays ``active``."""
    if switched_off():
        return SECOND_FACTOR_NONE
    if store.totp_seed(account_id):
        return SECOND_FACTOR_ACTIVE
    required = _required(store) and not common.provider_checks(store, account_id, provider_checked)
    passkeys = getattr(store, "passkeys_of", None)
    if passkeys is not None and passkeys(account_id):
        return SECOND_FACTOR_PASSKEY if required else SECOND_FACTOR_NONE
    return SECOND_FACTOR_REQUIRED if required else SECOND_FACTOR_NONE


# --- Confirming a change -------------------------------------------------------------------------------------------


#: Since 0.3.4 in ``common`` (every door counts at the brake); kept here for callers of 0.3.3.
too_many_attempts = common.too_many_attempts


def confirmed(
    store: Store, account: Account, password: str, actor_confirmed: bool, *, without_password: bool
) -> None:
    """``common.confirm``, which counts a wrong password at the brake (``confirm:<id>``, five free) as a sign-in
    would. Kept for callers of 0.3.3."""
    common.confirm(store, account, password, actor_confirmed, without_password=without_password)


# --- Setting up -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Enrolment:
    """An authenticator waiting for its first code: the seed (to type in by hand), the ``otpauth://`` address (the
    app draws the QR code from it) and, since 0.3.4, until when it waits."""

    seed: str
    uri: str
    expires_at: datetime | None = None


@dataclass(frozen=True)
class Confirmed:
    """The factor counts; ``codes`` are shown once (only when the account had none). ``next``: ``show_codes`` when
    there are codes to show (at sign-in: show them before the session), else ``session``."""

    codes: list[str]
    next: str = NEXT_SESSION


_enrolments: dict[AccountId, tuple[str, float]] = {}
_enrolments_lock = threading.Lock()


def begin_totp(store: AppStore, account_id: AccountId, *, issuer: str) -> Enrolment:
    """A new seed for the account, waiting ten minutes for its first code: sealed in the store and committed (a store
    without ``set_pending_totp`` keeps it in memory). It is no factor yet."""
    account = common.account_or_404(store, account_id)
    seed = new_seed()
    until = common.utcnow() + timedelta(seconds=ENROLMENT_SECONDS)
    keep = getattr(store, "set_pending_totp", None)
    if keep is not None:
        keep(account.id, seed, until)
        store.commit()
    else:
        with _enrolments_lock:
            _enrolments[account.id] = (seed, time.monotonic() + ENROLMENT_SECONDS)
    return Enrolment(seed, provisioning_uri(seed, issuer, account.username), until)


def pending_setup(store: AppStore, account_id: AccountId, *, issuer: str) -> Enrolment | None:
    """Since 0.3.4: the authenticator that waits for its first code, once more (the page was reloaded, the QR code
    closed, another tab): the same seed and address as ``begin_totp`` gave, until it expires; None when nothing waits
    (the page offers "Set up" again). Reading it changes nothing: the clock is not restarted, and a factor already set
    up keeps counting until a code confirms the new one."""
    account = common.account_or_404(store, account_id)
    held = _enrolment_held(store, account.id)
    if held is None:
        return None
    seed, until = held
    return Enrolment(seed, provisioning_uri(seed, issuer, account.username), until)


def _enrolment_held(store: AppStore, account_id: AccountId) -> tuple[str, datetime] | None:
    """The seed that waits for its first code and until when, None when there is none or it waited too long."""
    pending = getattr(store, "pending_totp", None)
    if pending is not None:
        held = pending(account_id)
        if held is None or common.expired(held[1]):
            return None
        seed, until = held
        return seed, until if until.tzinfo is not None else until.replace(tzinfo=UTC)
    with _enrolments_lock:
        kept = _enrolments.get(account_id)
    left = kept[1] - time.monotonic() if kept is not None else -1.0
    return (kept[0], common.utcnow() + timedelta(seconds=left)) if kept is not None and left >= 0 else None


def _waiting_seed(store: AppStore, account_id: AccountId) -> str | None:
    held = _enrolment_held(store, account_id)
    return held[0] if held is not None else None


def _drop_waiting_seed(store: AppStore, account_id: AccountId) -> None:
    drop = getattr(store, "set_pending_totp", None)
    if drop is not None:
        drop(account_id, None, None)
    with _enrolments_lock:
        _enrolments.pop(account_id, None)


def confirm_totp(
    store: AppStore, account_id: AccountId, code: str, *, password: str = "", actor_confirmed: bool = False
) -> Confirmed:
    """The code of the new seed confirms it: from now on it counts. Confirmed with the password (or by the app), except
    in a session that can only set up a factor (the app passes ``actor_confirmed``). Replacing an authenticator that
    is set up already needs the password, or a fresh sign-in for an account without one, like taking it away."""
    account = common.account_or_404(store, account_id)
    confirmed(store, account, password, actor_confirmed, without_password=has_factor(store, account.id))
    seed = _waiting_seed(store, account.id)
    if seed is None:
        raise AccountError("enrolment_expired", "That took too long. Start again.", 410)
    step = matching_step(seed, code)
    if step is None:
        raise AccountError("code_wrong", "The code is wrong.", 422)
    _drop_waiting_seed(store, account.id)
    store.set_totp(account.id, seed)
    store.claim_step(account.id, step)
    codes: list[str] = []
    if not store.recovery_hashes(account.id):
        codes = new_recovery_codes()
        key = store.recovery_key()
        store.set_recovery(account.id, [stored_form(key, entry) for entry in codes])
    store.commit()
    log().info("Second factor set up name=%s", account.username)
    return Confirmed(codes, NEXT_SHOW_CODES if codes else NEXT_SESSION)


def new_codes(
    store: AppStore, account_id: AccountId, *, password: str = "", actor_confirmed: bool = False
) -> list[str]:
    """Ten new recovery codes; the old ones stop counting."""
    account = common.account_or_404(store, account_id)
    confirmed(store, account, password, actor_confirmed, without_password=True)
    if not has_factor(store, account.id):
        raise AccountError("factor_missing", "Set up a second factor first.", 409)
    codes = new_recovery_codes()
    key = store.recovery_key()
    store.set_recovery(account.id, [stored_form(key, entry) for entry in codes])
    store.commit()
    log().info("New recovery codes name=%s", account.username)
    return codes


def _last_factor_guard(store: AppStore, account_id: AccountId, *, removing_totp: bool, removing_passkey: bool) -> None:
    if not _required(store):
        return
    totp_left = bool(store.totp_seed(account_id)) and not removing_totp
    passkeys = len(store.passkeys_of(account_id)) - (1 if removing_passkey else 0)
    if not totp_left and passkeys <= 0:
        raise AccountError("factor_required", "A second factor is required here; set up another one first.", 409)


def disable_totp(
    store: AppStore, account_id: AccountId, *, password: str = "", actor_confirmed: bool = False
) -> None:
    """The owner takes the time-based code away (not the last factor where one is required). The one way for every
    app (since 0.3.5 the apps keep no route of their own for it): confirmed with the password or a fresh sign-in at
    the provider, counted at the brake (``confirm:<id>``), the recovery codes go with it unless a passkey stays, and
    a setup that waits for its first code ends too (since 0.3.5), so that switched off means off."""
    account = common.account_or_404(store, account_id)
    confirmed(store, account, password, actor_confirmed, without_password=True)
    _last_factor_guard(store, account.id, removing_totp=True, removing_passkey=False)
    store.set_totp(account.id, None)
    _drop_waiting_seed(store, account.id)
    if not store.passkeys_of(account.id):
        store.set_recovery(account.id, [])
    store.commit()
    log().info("Second factor removed name=%s", account.username)


@dataclass(frozen=True)
class ResetOverview:
    """What the operator's dialog "Reset the second factor" shows before the reset (since 0.3.3): whether the account
    has an authenticator, how many recovery codes are left, its passkeys (each with its name; "Remove the passkeys
    too", ticked by default) and its paired devices ("Disconnect the paired devices too", ticked by default)."""

    authenticator: bool
    recovery_codes: int
    passkeys: list[Passkey]
    devices: list[Session]

    @property
    def parts(self) -> tuple[str, ...]:
        """Since 0.3.4: the parts of the dialog, top to bottom, as ``SECTIONS.operatorFactorReset`` names them, for
        this account: the passkeys and the box "Remove the passkeys too" only when it has passkeys (the same as
        ``factorResetParts`` in ``konten.ts``)."""
        return tuple(
            part for part in FACTOR_RESET_PARTS if self.passkeys or part not in FACTOR_RESET_PASSKEY_PARTS
        )


def reset_overview(store: AppStore, account_id: AccountId, *, actor_id: AccountId) -> ResetOverview:
    """For the operator's dialog (the app checks the operator's role): what a reset would take away."""
    if account_id == actor_id:
        raise AccountError("use_account_page", "Change your own second factor in your profile.", 409)
    target = common.account_or_404(store, account_id)
    sessions_of = getattr(store, "sessions_of", None)
    devices = [entry for entry in sessions_of(target.id) if entry.kind == KIND_DEVICE] if sessions_of else []
    return ResetOverview(
        authenticator=bool(store.totp_seed(target.id)),
        recovery_codes=len(store.recovery_hashes(target.id)),
        passkeys=list(store.passkeys_of(target.id)),
        devices=devices,
    )


def operator_reset(
    store: AppStore,
    account_id: AccountId,
    *,
    actor_id: AccountId,
    password: str = "",
    actor_confirmed: bool = False,
    disconnect_devices: bool = True,
    remove_passkeys: bool = True,
) -> Mail | None:
    """The operator takes the factors of another account away (time-based code, recovery codes and, with
    ``remove_passkeys``, its passkeys): its owner lost the phone. The dialog shows them first (``reset_overview``) and
    asks "Remove the passkeys too", ticked by default (since 0.3.3): a lost phone may carry a passkey. Every browser
    session and waiting sign-in of the account ends, and with ``disconnect_devices`` (on by default; the page asks
    "Disconnect the devices too") its paired devices too: the lost phone may be one of them. A confirmed address
    hears of it."""
    if account_id == actor_id:
        raise AccountError("use_account_page", "Change your own second factor in your profile.", 409)
    target, actor = common.acting(
        store, account_id, actor_id, password, confirm_self=True, actor_confirmed=actor_confirmed
    )
    store.set_totp(target.id, None)
    _drop_waiting_seed(store, target.id)
    store.set_recovery(target.id, [])
    if remove_passkeys:
        store.remove_passkeys(target.id)
    store.end_sessions(target.id)
    if disconnect_devices:
        everywhere = getattr(store, "end_everywhere", None)
        if everywhere is not None:
            everywhere(target.id, None)
        else:
            store.revoke_access(target.id)
    drop_waiting(target.id)
    store.commit()
    log().warning("Second factor reset name=%s by=%s", target.username, actor.username)
    if target.email and target.email_confirmed:
        return Mail(MAIL_FACTOR_RESET, target.email, target.id, target.username, target.display_name)
    return None


# --- Checking a code ------------------------------------------------------------------------------------------------


def check_code(store: AppStore, account_id: AccountId, typed: str) -> str:
    """A time-based code or a recovery code of the account: ``"totp"`` or ``"recovery"``; ``code_wrong`` else.
    Each counts once, also for two requests at the same moment. Commits what it used up. Every code counts at the
    brake (``code:<account>``, five free, since 0.3.4): also across waiting sign-ins, each of which ends after five."""
    keys = (brake.door_key(brake.DOOR_CODE, account_id),)
    wait = brake.BRAKE.claim(keys)
    if wait > 0:
        store.rollback()
        raise too_many_attempts(wait)
    method = _matching_code(store, account_id, typed)
    if method is None:
        store.rollback()
        raise AccountError("code_wrong", "The code is wrong.", 422)
    brake.BRAKE.succeeded(keys)
    return method


def _matching_code(store: AppStore, account_id: AccountId, typed: str) -> str | None:
    seed = store.totp_seed(account_id)
    if seed:
        step = matching_step(seed, typed)
        if step is not None and store.claim_step(account_id, step):
            store.commit()
            return "totp"
    hashes = store.recovery_hashes(account_id)
    if hashes and not typed.strip().isdigit():
        forms = recognised_forms(store.recovery_key(), typed)
        for stored in hashes:
            if any(hmac.compare_digest(stored, form) for form in forms):
                if store.claim_recovery(account_id, stored):
                    store.commit()
                    log().warning("Recovery code used account=%s left=%s", account_id, len(hashes) - 1)
                    return "recovery"
                break
    return None


# --- The sign-in that waits for the code ------------------------------------------------------------------------------


@dataclass
class _Waiting:
    account_id: AccountId
    remember: bool
    provider_checked: bool
    until: float
    attempts: int = 0


@dataclass(frozen=True)
class Waited:
    """The waiting sign-in is done: the app starts the session with these."""

    account_id: AccountId
    remember: bool
    provider_checked: bool
    method: str


_waiting: dict[str, _Waiting] = {}
_waiting_lock = threading.Lock()


def _key(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def start_waiting(account_id: AccountId, *, remember: bool = True, provider_checked: bool = False) -> str:
    """After the password (or a provider that does not check the factor): the token of the waiting sign-in, for a
    cookie of five minutes. Up to three per account at the same time, the oldest goes: a stranger who knows the
    password cannot throw the owner's own waiting sign-in out with one of his own."""
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _waiting_lock:
        for key in [key for key, held in _waiting.items() if held.until < now]:
            _waiting.pop(key, None)
        mine = [key for key, held in _waiting.items() if held.account_id == account_id]
        for key in mine[: max(0, len(mine) - WAITING_PER_ACCOUNT + 1)]:
            _waiting.pop(key, None)
        _waiting[_key(token)] = _Waiting(account_id, remember, provider_checked, now + PENDING_SECONDS)
    return token


def drop_waiting(account_id: AccountId) -> None:
    """Every waiting sign-in of the account ends (new password, reset, block)."""
    with _waiting_lock:
        for key in [key for key, held in _waiting.items() if held.account_id == account_id]:
            _waiting.pop(key, None)


def waiting_account(token: str) -> AccountId | None:
    with _waiting_lock:
        held = _waiting.get(_key(token))
    return held.account_id if held is not None and held.until >= time.monotonic() else None


def finish_waiting(store: AppStore, token: str, typed: str) -> Waited:
    """The code for a waiting sign-in. Each attempt is counted before its code is checked, under the lock: five codes
    at most, also for many requests at the same moment; then it ends (the password is asked again). A blocked account
    is refused here too."""
    key = _key(token)
    with _waiting_lock:
        held = _waiting.get(key)
        if held is not None and (held.until < time.monotonic() or held.attempts >= MAX_ATTEMPTS):
            _waiting.pop(key, None)
            held = None
        if held is not None:
            held.attempts += 1
    if held is None:
        raise AccountError("sign_in_expired", "That took too long. Sign in again.", 401)
    account = store.get_account(held.account_id)
    if account is None or account.blocked:
        with _waiting_lock:
            _waiting.pop(key, None)
        raise AccountError("account_blocked", "This account is blocked. Ask the operator.", 403)
    try:
        method = check_code(store, held.account_id, typed)
    except AccountError:
        with _waiting_lock:
            if held.attempts >= MAX_ATTEMPTS:
                _waiting.pop(key, None)
        raise
    with _waiting_lock:
        _waiting.pop(key, None)
    return Waited(held.account_id, held.remember, held.provider_checked, method)


def finish_waiting_by_passkey(token: str, account_id: AccountId) -> Waited | None:
    """A passkey of the same account answered instead of a code (``passkeys.finish_sign_in``)."""
    key = _key(token)
    with _waiting_lock:
        held = _waiting.get(key)
        if held is None or held.until < time.monotonic() or held.account_id != account_id:
            return None
        _waiting.pop(key, None)
    return Waited(held.account_id, held.remember, held.provider_checked, "passkey")


def forget() -> None:
    """Tests: no enrolment and no waiting sign-in left."""
    with _enrolments_lock:
        _enrolments.clear()
    with _waiting_lock:
        _waiting.clear()
