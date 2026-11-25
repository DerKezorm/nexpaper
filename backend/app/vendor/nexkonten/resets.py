"""A forgotten password, two ways, the same in every app, and the emergency command.

A link by mail can only go out where a mail server is set up; many installations at home have none. Without one only
somebody who is signed in already and knows the account can help: the operator.

- **The person asks** ("Forgot your password?", one field "Username or email"): with a mail server and signing in by
  password on. The answer is always the same ("If there is an account with an address for this, a link is on its
  way."), and so is its time: ``forgot_in_background`` answers at once and looks, makes and mails in a worker. The
  link goes to the account's own address that counts, holds one hour, works once. An address that several accounts
  share finds no account; asked for by username, the link goes to the account's own address all the same.
- **The operator makes a link** under Accounts, with the operator's own password (an operator without one: a fresh
  sign-in at the provider): with a mail server and an address that counts it is mailed there, otherwise the app shows
  it once to pass on. It holds 1, 7 or 30 days (1 by default). A blocked account may get one; it stays blocked. The
  operator never sets a password, and makes no link for themself. An account through a provider only gets a first
  password this way only while signing in by password is on.
- **The emergency command** on the server makes the same link without an operator signed in (the only operator
  forgot the password): ``server_reset_link``.

A new password from a link ends every browser session and every sign-in waiting for its second factor; paired
devices, calendar programs, API keys and passkeys keep their access (``ResetDone.remaining``, "Disconnect all":
``disconnect_all``).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import brake, common, factor
from .common import expired, log, new_token, next_step, reload, tell, utcnow
from .errors import AccountError
from .login import resolve_login
from .model import (
    EVENT_PASSWORD_SET,
    MAIL_RESET,
    RESET_OPERATOR,
    RESET_SELF,
    RESET_SERVER,
    Access,
    Account,
    AccountId,
    Event,
    Mail,
    Reset,
    Store,
)
from .names import check_password_rule

#: How long a link holds that a person asked for: fixed.
SELF_HOURS = 1
#: What the operator (or the emergency command) may choose, in days, and the default.
OPERATOR_DAYS = (1, 7, 30)
OPERATOR_DAYS_DEFAULT = 1


@dataclass(frozen=True)
class ResetLink:
    """A link the operator (or the command) made. ``mail`` when it goes by mail (then ``token`` is ""), else ``token``
    to show once."""

    expires_at: datetime
    token: str = ""
    mail: Mail | None = None


@dataclass(frozen=True)
class ResetDone:
    """A new password was set through a link. ``origin`` says who made the link (the app shows "the operator set a
    link for you" at the next sign-in, say), ``remaining`` what still has access, ``next`` what the app starts
    (``common.next_step``; a blocked account: ``sign_in``)."""

    account: Account
    origin: str
    next: str
    remaining: list[Access] = field(default_factory=list)


def _mailable(account: Account) -> bool:
    """The account has an address of its own that counts (also one another account shares: the link is this
    account's, the address its own)."""
    return bool(account.email) and account.email_confirmed


def forgot(store: Store, typed: str) -> Mail | None:
    """What a person typed into "Forgot your password?": the mail to send, or None. Writes and commits a link, so
    its time differs: call it in a worker (``forgot_in_background``), never in the request."""
    account = resolve_login(store, typed)
    if account is None or not account.has_password or account.blocked or not _mailable(account):
        return None
    if brake.BRAKE.claim((brake.door_key(brake.DOOR_MAIL, account.id),)) > 0:
        # The brake at the account (``mail:<id>``, five free): nobody fills a mailbox with links. Nobody waits for
        # this answer, so it stays as quiet as every other.
        log().warning("Reset link held back by the brake name=%s", account.username)
        return None
    token = new_token()
    store.start_reset(account.id, token, utcnow() + timedelta(hours=SELF_HOURS), created_by=None, origin=RESET_SELF)
    store.commit()
    log().info("Reset link made name=%s by=the person", account.username)
    return Mail(MAIL_RESET, account.email, account.id, account.username, account.display_name, token, SELF_HOURS)


def forgot_in_background(
    typed: str,
    *,
    open_store: Callable[[], AbstractContextManager[Store]],
    send: Callable[[Mail], None],
    later: Callable[[Callable[[], None]], None],
    sender: str | None = None,
) -> None:
    """"Forgot your password?" as the request answers it: at once, the same for every input. ``later`` runs the
    rest in a worker (the app's background tasks): look up, make the link with its own store (``open_store``), mail
    it (``send``); a mail that fails takes its link with it. ``sender`` (since 0.3.4, ``brake.client_address``):
    the requests of one sender count at the brake (``forgot:<sender>``, ten free), ``too_many_attempts`` then, the
    same for every input; the account counts in the worker (``mail:<id>``, five links, then quietly none).

    ``send`` sends **at once** and raises when the mail did not go out (since 0.3.10 said plainly): never through an
    outbox that tries again later (``nexpost.outbox.queue``), but straight with ``nexpost.send.deliver``. A mail
    that fails takes its link with it (``reset_mail_failed``), so that no link stays behind that nobody got; with an
    outbox the link would stay and the person would wait for a mail that comes an hour later or never."""
    if sender is not None:
        common.counted((brake.door_key(brake.DOOR_FORGOT, sender),))

    def job() -> None:
        with open_store() as store:
            letter = forgot(store, typed)
            if letter is None:
                return
            try:
                send(letter)
            except Exception as error:  # noqa: BLE001 (nobody waits for this answer; the link must not stay)
                log().warning("Reset link not mailed name=%s: %r", letter.username, error)
                reset_mail_failed(store, letter.account_id)

    later(job)


def _link(store: Store, target: Account, days: int, created_by: AccountId | None, origin: str) -> tuple[str, datetime]:
    token = new_token()
    expires_at = utcnow() + timedelta(days=common.choose_days(days, OPERATOR_DAYS))
    store.start_reset(target.id, token, expires_at, created_by=created_by, origin=origin)
    store.commit()
    return token, expires_at


def reset_link(
    store: Store,
    account_id: AccountId,
    *,
    actor_id: AccountId,
    password: str = "",
    actor_confirmed: bool = False,
    mail: bool = False,
    password_login: bool = True,
    days: int = OPERATOR_DAYS_DEFAULT,
) -> ResetLink:
    """A link for another account, made by an operator, confirmed (password, or ``actor_confirmed``). ``mail``: a
    mail server and the public address are there; the link then goes to the account's address that counts, if it has
    one. ``password_login`` off: an account through a provider only gets no first password (``password_login_off``).
    A blocked account gets its link and stays blocked."""
    actor = store.get_account(actor_id)
    if actor is None or not actor.operator or actor.blocked:
        raise AccountError("not_allowed", "Only an operator may make this link.", 403)
    common.confirm(store, actor, password, actor_confirmed, without_password=True)
    if account_id == actor_id:
        raise AccountError("use_account_page", "Change your own password on your account page.", 409)
    target = common.account_or_404(store, account_id)
    if not target.has_password and not password_login:
        raise AccountError(
            "password_login_off", "Signing in by password is off; this account signs in through a provider.", 409
        )
    token, expires_at = _link(store, target, days, actor.id, RESET_OPERATOR)
    log().warning("Reset link made name=%s by=%s", target.username, actor.username)
    if mail and _mailable(target):
        letter = Mail(MAIL_RESET, target.email, target.id, target.username, target.display_name, token, days * 24)
        return ResetLink(expires_at, mail=letter)
    return ResetLink(expires_at, token=token)


def server_reset_link(store: Store, who: str, *, days: int = OPERATOR_DAYS_DEFAULT) -> ResetLink:
    """The emergency command in the container: a link for the account named by its current username or its address
    that counts, without an operator signed in. Kept with ``origin = RESET_SERVER`` (not "asked for by the person").
    Shown once on the console, never mailed."""
    target = resolve_login(store, who)
    if target is None:
        raise AccountError("not_found", "No such account.", 404)
    token, expires_at = _link(store, target, days, None, RESET_SERVER)
    log().warning("Reset link made name=%s by=the command on the server", target.username)
    return ResetLink(expires_at, token=token)


def reset_mail_failed(store: Store, account_id: AccountId) -> None:
    """The mail with the link did not go out: the link goes too, nobody holds it."""
    store.drop_resets(account_id)
    store.commit()


def _invalid() -> AccountError:
    return AccountError("reset_invalid", "This link has been used already or is not valid any more.", 404)


def _valid(store: Store, token: str, password_login: bool) -> tuple[Reset, Account]:
    reset = store.find_reset(token) if token else None
    if reset is None:
        raise _invalid()
    if expired(reset.expires_at):
        raise AccountError("reset_expired", "This link has expired.", 404)
    account = store.get_account(reset.account_id)
    if account is None:
        raise _invalid()
    if reset.origin == RESET_SELF and account.blocked:
        raise _invalid()
    if reset.origin == RESET_OPERATOR:
        # Made by somebody who is no longer an operator: it stops counting.
        creator = store.get_account(reset.created_by) if reset.created_by is not None else None
        if creator is None or not creator.operator or creator.blocked:
            raise _invalid()
    if not password_login and not account.operator:
        # Signing in by password is off: only the operator, who keeps the password as the way in, sets one.
        raise _invalid()
    return reset, account


def reset_state(store: Store, token: str, *, password_login: bool = True) -> Account:
    """The page of a link: whose it is (nothing is used up)."""
    return _valid(store, token, password_login)[1]


def use_reset(store: Store, token: str, password: str, *, password_login: bool = True) -> ResetDone:
    """The person behind the link sets a new password. The link goes first, in the same transaction (two requests
    with one link set one password); browser sessions and waiting sign-ins end, the rest is listed."""
    reset, account = _valid(store, token, password_login)
    check_password_rule(password)
    if not store.consume_reset(reset):
        store.rollback()
        raise _invalid()
    store.set_password(account.id, password)
    store.end_sessions(account.id)
    renew = getattr(store, "renew_device_key", None)  # part 2: known-browser marks of the account lose their worth
    if renew is not None:
        renew(account.id)
    store.commit()
    factor.drop_waiting(account.id)
    log().warning("Reset link used name=%s origin=%s", account.username, reset.origin)
    tell(store, Event(EVENT_PASSWORD_SET, account.id, details={"origin": reset.origin}))
    account = reload(store, account.id)
    return ResetDone(account, reset.origin, next_step(store, account), store.list_access(account.id))


def disconnect_all(store: Store, account_id: AccountId) -> int:
    """"Disconnect all" after a new password: every device, program password, API key and passkey of the account.
    The app lets only the account itself (signed in anew) or the operator do this."""
    account = common.account_or_404(store, account_id)
    count = store.revoke_access(account.id)
    store.commit()
    log().warning("Every device disconnected name=%s count=%s", account.username, count)
    return count
