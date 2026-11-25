"""Invitations: the operator gives an address (optional), a display name (optional) and the app's rights; never a
username. The person invited sees the fields of the setup without the code: display name (from the invitation),
username (a suggestion), email (from the invitation), password twice; below that "or" and one button per provider.

An invitation holds 1, 7 or 30 days as the operator chooses (7 by default). The address of the invitation counts
while it is not changed. A changed one counts with a mail server only after its confirmation link, without one at
once. An invitation into a space may also reach somebody who has an account: signed in, they join with it
(``join_invite``). Making, listing and mailing invitations stay the app's (it knows its rights and its mailer); the
module checks what the operator typed, gives the end, and runs accepting and joining.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote, urlsplit

from .common import (
    add_account,
    choose_days,
    clean_language,
    expired,
    log,
    new_token,
    next_step,
    reload,
    tell,
    utcnow,
)
from .errors import AccountError
from .model import (
    EVENT_CREATED,
    EVENT_JOINED,
    MAIL_CONFIRM_EMAIL,
    Account,
    AccountId,
    Event,
    Invite,
    Mail,
    NewAccount,
    Store,
)
from .names import (
    check_display_name,
    check_password_rule,
    check_username,
    clean_display_name,
    clean_email,
    display_name_taken,
    email_taken,
    free_username,
    same_address,
    suggest_username,
    username_taken,
)

#: How long the link that confirms a changed address holds.
CONFIRM_HOURS = 24
#: What the operator may choose for an invitation, and the default.
INVITE_DAYS = (1, 7, 30)
INVITE_DAYS_DEFAULT = 7


def invite_expires_at(days: int = INVITE_DAYS_DEFAULT) -> datetime:
    """The end of an invitation made now; ``invalid_days`` for anything but 1, 7 or 30."""
    return utcnow() + timedelta(days=choose_days(days, INVITE_DAYS))


@dataclass(frozen=True)
class InviteForm:
    """What the form of an invitation shows at first."""

    display_name: str
    username: str
    email: str


@dataclass(frozen=True)
class Accepted:
    """The new account; ``mail`` the confirmation link of an address other than the invitation's, when a mail server
    is there (the account has no address until it is opened); ``next`` what the app starts (``common.next_step``)."""

    account: Account
    mail: Mail | None = None
    next: str = ""


def public_url_needed() -> AccountError:
    return AccountError(
        "public_url_needed", "An invitation needs the public address of the app: enter it in the server settings.", 409
    )


def _base(raw: str | None) -> str:
    """Scheme, host, port and path of an address, without query and fragment; "" when it is no http(s) address."""
    parts = urlsplit((raw or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ""
    return f"{parts.scheme}://{parts.netloc}{parts.path}".rstrip("/")


def link_base(public_url: str | None, request_base: str | None = None) -> str:
    """Since 0.3.5: where the links of the app lead. The public address when one is entered, else the address the
    operator opened the app under right now (``request_base``: scheme, host, port and base path of the request, as
    nexnotes always did), so that an installation without an entered address can still invite. ``public_url_needed``
    only when both are missing."""
    base = _base(public_url) or _base(request_base)
    if not base:
        raise public_url_needed()
    return base


def invite_link(public_url: str, path: str, token: str, *, request_base: str | None = None) -> str:
    """The link of an invitation (or any link the app mails): the public address (else ``request_base``, since
    0.3.5), the app's path, the token. ``public_url_needed`` without either: a link to nowhere helps nobody."""
    return f"{link_base(public_url, request_base)}/{path.strip('/')}/{quote(token, safe='')}"


def invite_values(
    store: Store,
    *,
    email: str,
    display_name: str,
    existing_ok: bool = False,
    public_url: str | None = None,
    request_base: str | None = None,
) -> tuple[str, str]:
    """What the operator typed for a new invitation, checked: an address in the right form that no account has
    (``existing_ok``: an invitation into a space may go to an account's address, it joins with it), and a display
    name as people write it. ``public_url`` (since 0.3.2): the app's public address, None leaves it unchecked as
    before. Since 0.3.5 an empty one no longer refuses when ``request_base`` (the address of the operator's request)
    is there: the link takes that (``invite_link(..., request_base=…)``); ``public_url_needed`` only without both."""
    if public_url is not None:
        link_base(public_url, request_base)
    address = clean_email(email)
    if address and not existing_ok and email_taken(store, address):
        raise AccountError("email_taken", "This address belongs to another account already.", 409)
    return address, clean_display_name(display_name)


def _open(store: Store, key: str) -> Invite:
    invite = store.find_invite(key) if key else None
    if invite is None:
        raise AccountError("invite_invalid", "This invitation has been used already or is not valid any more.", 404)
    if expired(invite.expires_at):
        raise AccountError("invite_expired", "This invitation has expired.", 404)
    return invite


def invite_form(store: Store, key: str) -> InviteForm:
    """The fields as the page fills them: the display name and address of the invitation (a display name another
    account shows stays empty), as username the one an older version fixed (when it still fits the rules and is
    free) or a suggestion from the display name, numbered when it is taken."""
    invite = _open(store, key)
    shown = clean_display_name(invite.display_name)
    if display_name_taken(store, shown):
        shown = ""
    fixed = invite.username.strip()
    if fixed and not username_taken(store, fixed):
        # A name an older version fixed stays as it was, also against today's rules (capitals, "_kim").
        name = fixed
    else:
        base = suggest_username(shown or invite.display_name)
        if not base and invite.email:
            base = suggest_username(invite.email.split("@", 1)[0])
        name = free_username(store, base) if base else ""
    return InviteForm(display_name=shown, username=name, email=invite.email)


def accept_invite(
    store: Store,
    key: str,
    *,
    display_name: str,
    username: str,
    email: str,
    password: str,
    language: str = "",
    mail: bool = False,
    older_request: bool = False,
    proven: bool = False,
) -> Accepted:
    """A new account with the rights of the invitation. The invitation goes first, in the same transaction, with one
    statement that must hit exactly one row: two people with the same link at the same moment make one account.

    ``older_request``: the request came from a client of the older version, which sent no display name: the username
    stands in for it (left empty when another account shows it). ``proven``: the app mailed this very link to the
    invitation's address itself, so an unchanged address is proven too (not for an invitation several may follow).
    A name an older version fixed in the invitation is taken as it is, also against today's rules."""
    invite = _open(store, key)
    fixed = invite.username.strip()
    typed = (username or "").strip()
    name = typed if fixed and typed == fixed and "@" not in typed and len(typed) <= 64 else check_username(username)
    if username_taken(store, name):
        raise AccountError("username_taken", "Someone has this username already.", 409)
    if older_request and not clean_display_name(display_name):
        shown = "" if display_name_taken(store, name) else name
    else:
        shown = check_display_name(store, display_name, required=True)
    address = clean_email(email)
    if address and email_taken(store, address):
        raise AccountError("email_taken", "This address belongs to another account already.", 409)
    check_password_rule(password)
    if not store.consume_invite(invite):
        store.rollback()
        raise AccountError("invite_invalid", "This invitation has been used already or is not valid any more.", 404)
    # The invitation's own address counts without a link: it reached this person. Not for an invitation several may
    # follow (it may have been passed on): then it is an address like any typed one.
    from_invite = bool(address) and same_address(address, invite.email) and not invite.reusable
    waiting = bool(address) and mail and not from_invite
    account_id = add_account(
        store,
        NewAccount(
            username=name,
            display_name=shown,
            email="" if waiting else address,
            email_confirmed=True,
            password=password,
            language=clean_language(language),
            invite=invite,
            email_proven=proven and from_invite,
        ),
    )
    letter = None
    if waiting:
        token = new_token()
        store.start_email_change(account_id, address, token, utcnow() + timedelta(hours=CONFIRM_HOURS))
        letter = Mail(MAIL_CONFIRM_EMAIL, address, account_id, name, shown, token, CONFIRM_HOURS)
    store.commit()
    log().info("Invitation accepted, account created name=%s", name)
    tell(store, Event(EVENT_CREATED, account_id, invite=invite))
    account = reload(store, account_id)
    return Accepted(account, letter, next_step(store, account))


def join_invite(store: Store, key: str, account_id: AccountId) -> Account:
    """The signed-in account follows an invitation (into a space): it gets the invitation's rights in addition to its
    own, the invitation is used up (unless reusable), and the store hears ``EVENT_JOINED`` after the commit."""
    invite = _open(store, key)
    account = store.get_account(account_id)
    if account is None or account.blocked:
        raise AccountError("not_allowed", "This account cannot join.", 403)
    if not store.consume_invite(invite):
        store.rollback()
        raise AccountError("invite_invalid", "This invitation has been used already or is not valid any more.", 404)
    store.accept_invite(account.id, invite)
    store.commit()
    log().info("Invitation accepted by an existing account name=%s", account.username)
    tell(store, Event(EVENT_JOINED, account.id, invite=invite))
    return reload(store, account.id)
