"""What the flows share: time, tokens, the log, writing an account, who may act on whom, what follows a commit,
and which step of a session the app starts next."""

from __future__ import annotations

import logging
import re
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from . import brake, config
from .errors import AccountError
from .model import (
    NEXT_PASSKEY,
    NEXT_SECOND_FACTOR,
    NEXT_SECOND_FACTOR_SETUP,
    NEXT_SESSION,
    NEXT_SHOW_CODES,
    NEXT_SIGN_IN,
    SECOND_FACTOR_ACTIVE,
    SECOND_FACTOR_PASSKEY,
    SECOND_FACTOR_REQUIRED,
    Account,
    AccountId,
    Event,
    NewAccount,
    Store,
    Taken,
)

_LANGUAGE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}")


def log() -> logging.Logger:
    return logging.getLogger(config.current().log_name)


def utcnow() -> datetime:
    return datetime.now(UTC)


def expired(moment: datetime | None) -> bool:
    """A point in time that has passed; a time without a zone is read as UTC (as most apps store it)."""
    if moment is None:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment <= utcnow()


#: How old a sign-in at the provider may be to confirm a change for an account without a password (``actor_confirmed``).
FRESH_SIGN_IN_MINUTES = 5


def fresh_sign_in(signed_in_at: datetime | None, now: datetime | None = None) -> bool:
    """Whether a sign-in at the provider is fresh enough to confirm a change: at most ``FRESH_SIGN_IN_MINUTES`` old,
    not in the future. The app passes ``actor_confirmed=fresh_sign_in(<time of the provider's sign-in>)``."""
    if signed_in_at is None:
        return False
    moment = signed_in_at if signed_in_at.tzinfo else signed_in_at.replace(tzinfo=UTC)
    age = (now or utcnow()) - moment
    return timedelta(0) <= age <= timedelta(minutes=FRESH_SIGN_IN_MINUTES)


def new_token() -> str:
    """The token of a link: 32 random bytes, URL-safe. The store keeps only a hash of it."""
    return secrets.token_urlsafe(32)


def clean_language(raw: str) -> str:
    """A language tag as the browser sends it (``de``, ``en-GB``), "" for anything else."""
    text = (raw or "").strip()
    return text if _LANGUAGE.fullmatch(text) else ""


def taken_error(what: str) -> AccountError:
    if what == "email":
        return AccountError("email_taken", "This address belongs to another account already.", 409)
    if what == "display_name":
        return AccountError("display_name_taken", "Another account shows this name already.", 409)
    return AccountError("username_taken", "Someone has this username already.", 409)


def add_account(store: Store, new: NewAccount) -> AccountId:
    """``store.add_account``; a refusal of the database (another account was faster) rolls back and becomes
    ``username_taken``, ``email_taken`` or ``display_name_taken``."""
    try:
        return store.add_account(new)
    except Taken as error:
        store.rollback()
        raise taken_error(error.what) from error


def account_or_404(store: Store, account_id: AccountId) -> Account:
    account = store.get_account(account_id)
    if account is None:
        raise AccountError("not_found", "No such account.", 404)
    return account


def reload(store: Store, account_id: AccountId) -> Account:
    """The account as the store holds it after a write; a store that loses it is broken."""
    account = store.get_account(account_id)
    if account is None:
        raise RuntimeError(f"account {account_id!r} is gone right after it was written")
    return account


def wrong_password() -> AccountError:
    return AccountError("wrong_password", "The password is wrong.", 401)


def fresh_sign_in_needed() -> AccountError:
    return AccountError(
        "fresh_sign_in_needed", "Confirm with a fresh sign-in at your provider: this account has no password.", 403
    )


def too_many_attempts(wait: float) -> AccountError:
    return AccountError(
        "too_many_attempts", "Too many attempts. Wait a moment.", 429, retry_after=max(1, int(wait + 0.999))
    )


@contextmanager
def guarded(keys: tuple[str, ...]) -> Iterator[None]:
    """One attempt at a door behind the brake (``brake.door_key``): refused with ``too_many_attempts`` while a wait
    runs, counted as a failure, taken back when the body runs through."""
    wait = brake.BRAKE.claim(keys)
    if wait > 0:
        raise too_many_attempts(wait)
    yield
    brake.BRAKE.succeeded(keys)


def counted(keys: tuple[str, ...]) -> None:
    """One use of a door that is never taken back (a mail written, a request for a link): ``too_many_attempts``
    while a wait runs."""
    wait = brake.BRAKE.claim(keys)
    if wait > 0:
        raise too_many_attempts(wait)


def confirm(store: Store, account: Account, password: str, actor_confirmed: bool, *, without_password: bool) -> None:
    """The acting person shows it is them: with their password, or, when the app confirmed it already
    (``actor_confirmed``: a fresh sign-in at the provider for an account without a password, or the app's own check
    of the password with its brake), not again. ``without_password``: what an account without a password needs then
    (True: a fresh sign-in; False: nothing). A password typed here counts at the brake (``confirm:<account>``, five
    free, since 0.3.4 at every door: address, username, factor, the operator's actions), so that a session cannot
    guess the password through these pages."""
    if actor_confirmed:
        return
    if account.has_password:
        with guarded((brake.door_key(brake.DOOR_CONFIRM, account.id),)):
            if not store.check_password(account.id, password or ""):
                raise wrong_password()
        return
    if without_password:
        raise fresh_sign_in_needed()


def acting(
    store: Store,
    account_id: AccountId,
    actor_id: AccountId,
    password: str,
    *,
    confirm_self: bool,
    self_without_password: bool = False,
    actor_confirmed: bool = False,
) -> tuple[Account, Account]:
    """The account acted on and the one acting. Somebody else's account: only an operator who is not blocked, with
    the operator's own password or, for an operator without one, a fresh sign-in at the provider (``actor_confirmed``
    from the app). One's own: confirmed where ``confirm_self`` (``self_without_password``: an account without a
    password needs a fresh sign-in too)."""
    target = account_or_404(store, account_id)
    if actor_id == account_id:
        if confirm_self:
            confirm(store, target, password, actor_confirmed, without_password=self_without_password)
        return target, target
    actor = store.get_account(actor_id)
    if actor is None or not actor.operator or actor.blocked:
        raise AccountError("not_allowed", "Only an operator may change another account.", 403)
    confirm(store, actor, password, actor_confirmed, without_password=True)
    return target, actor


def choose_days(days: int, choices: tuple[int, ...]) -> int:
    """How long a link holds, out of what the operator may choose."""
    if days not in choices:
        raise AccountError("invalid_days", f"Choose one of {', '.join(str(day) for day in choices)} days.", 422)
    return days


def tell(store: Store, event: Event) -> None:
    """``store.notify`` after a commit. Never raises: what the app does then cannot undo the outcome."""
    try:
        store.notify(event)
    except Exception as error:  # noqa: BLE001 (a follow-up of the app must never turn a done thing into an error)
        log().warning("Follow-up of %s failed for account %s: %r", event.kind, event.account_id, error)




def provider_checks(store: object, account_id: AccountId, provider_checked: bool = False) -> bool:
    """Since 0.3.10: the provider checks the second factor itself, so "second factor for everybody" asks none of its
    own here (nexdiary, nexpaper). ``provider_checked``: this sign-in came through a provider whose entry checks it
    (the app knows that from its provider's settings); the store's hook ``provider_checks_factor(account_id)`` (off
    where the store has none) says it for the account as a whole (an account through such providers only). A factor
    the account set up itself is asked all the same."""
    if provider_checked:
        return True
    hook = getattr(store, "provider_checks_factor", None)
    return bool(hook is not None and hook(account_id))


def next_step(store: Store, account: Account, *, provider_checked: bool = False) -> str:
    """What the app starts for an account that just got in (``NEXT_*`` in ``model``). ``provider_checked`` (since
    0.3.10): it came through a provider that checks the second factor itself; then "second factor for everybody"
    sends it neither to set one up nor to its passkey (``provider_checks``), an authenticator of its own is asked as
    before."""
    if account.blocked:
        return NEXT_SIGN_IN
    if config.current().second_factor_is_off():
        # The emergency hammer (``<APP>_SECOND_FACTOR_OFF``) beats every second factor and the switch for everybody.
        return NEXT_SESSION
    state = store.second_factor(account.id)
    if state == SECOND_FACTOR_ACTIVE:
        return NEXT_SECOND_FACTOR
    if state in (SECOND_FACTOR_PASSKEY, SECOND_FACTOR_REQUIRED) and provider_checks(
        store, account.id, provider_checked
    ):
        # Only the switch for everybody asked a factor here, and the provider has checked one.
        return NEXT_SESSION
    if state == SECOND_FACTOR_PASSKEY:
        return NEXT_PASSKEY
    if state == SECOND_FACTOR_REQUIRED:
        return NEXT_SECOND_FACTOR_SETUP
    return NEXT_SESSION


#: Since 0.3.5: the dialog "Session expired" (the session ended while a page was open; the page stays underneath),
#: its parts for each step, top to bottom, as ``SESSION_EXPIRED`` in ``konten.ts`` names them. It starts at
#: ``sign_in`` (``or``: "or" and the provider buttons as on the sign-in page; ``password`` and its button only where
#: the account has a password) and then shows what ``next_step`` answers after the password or the provider: the code,
#: the passkey, setting a factor up, the recovery codes. ``session``: nothing left, the dialog closes, the page goes
#: on. An account whose second factor is a passkey gets there too (a code alone would leave it stuck).
SESSION_EXPIRED_PARTS: dict[str, tuple[str, ...]] = {
    NEXT_SIGN_IN: ("sessionExpiredHint", "password", "signInAgain", "or"),
    NEXT_SECOND_FACTOR: ("code", "signInAgain"),
    NEXT_PASSKEY: ("passkeySignIn",),
    NEXT_SECOND_FACTOR_SETUP: ("factorRequired", "totpSetup", "passkeyAdd"),
    NEXT_SHOW_CODES: ("recoveryCodesHint", "recoveryCodes"),
    NEXT_SESSION: (),
}


def session_expired_parts(step: str) -> tuple[str, ...]:
    """Since 0.3.5: what the dialog "Session expired" shows for a step (``next_step``); an unknown one starts over."""
    return SESSION_EXPIRED_PARTS.get(step, SESSION_EXPIRED_PARTS[NEXT_SIGN_IN])


def address_hint(address: str) -> str:
    """An address as far as a stranger may read it: the first letter and the domain (``m***@example.com``)."""
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}" if domain else ""
