"""The profile: display name, username, language and address, changed by the person (and by the operator under
Accounts).

**Username:** everybody changes their own, within the rules and only when the name is free: no other account has it
now (without regard to case, unique in the database too, so that two changes at the same moment do not both get
through), had it once, or shows it as display name. An account with a password confirms with it. It counts at once;
sessions and devices stay (they hang on the account's id). The old name stays reserved for ever and keeps working only
for things in the background (calendar programs, an inbox folder), never for signing in. A confirmed address hears
"Your username is now …". A display name that is exactly the old username follows the new one; any other stays. The
operator changes it with the operator's own password, an operator without one after a fresh sign-in at the provider
(``actor_confirmed``).

**Display name:** unique (``names.display_key``), may be empty in the profile (the username shows).

**Language:** kept at the account, part of the profile.

**Address:** changed only with the password (an account without one: a fresh sign-in at the provider). With a mail
server a new one counts only after its confirmation link, until then the old one; without one at once. The old
address hears of the change where a mail can go: every old address that counted, not only one proven by link
(decided 25.11.2026). The link can be sent again. **Taking one's own address away needs the password too** (decided
for 0.3.10, replacing "removing always works"): without an address "Forgot your password?" reaches nobody, so a
stranger at an open session must not do it. The operator may only take an address away, never set one (or a
password link could go to an address of the operator's choosing), with the operator's own password. Whenever the
address in effect changes, open links a person asked for to the old one stop counting.

**Proving an address that counts already** (since 0.3.10, ``prove_email``): an app that sends things that must reach
the right person (nexpaper's inbox) needs an address proven by link; one that counts without (an address of an
older version, one typed without a mail server) gets its link afterwards, the same link and time as a new address.

**Address from a provider:** an account through a provider only follows the provider's address
(``follow_provider_email``), which never counts at once and never takes an address another account has. An account
with a password is only offered it (since 0.3.3, ``provider_email`` answers ``offered``): the profile asks "Use the
address from <provider>?", and ``take_offered_email`` takes it like a change of address (with the password, by link
where a mail server is there); ``dismiss_offered_email`` says no.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, replace
from datetime import timedelta

from . import brake, common, config, names
from .common import acting, address_hint, log, reload, tell
from .errors import AccountError
from .model import (
    EMAIL_OWN,
    EMAIL_PROVIDER,
    EVENT_EMAIL_CHANGED,
    EVENT_EMAIL_PROVEN,
    EVENT_RENAMED,
    MAIL_CONFIRM_EMAIL,
    MAIL_EMAIL_CHANGED,
    MAIL_USERNAME_CHANGED,
    RESET_SELF,
    Account,
    AccountId,
    EmailChange,
    Event,
    Mail,
    Store,
    Taken,
)

#: How long the link that confirms an address holds.
CONFIRM_HOURS = 24

#: ``provider_email``: the account follows the provider's address now; it is only offered (an account with a
#: password); nothing happened.
PROVIDER_EMAIL_TAKEN = "taken"
PROVIDER_EMAIL_OFFERED = "offered"
PROVIDER_EMAIL_NONE = ""


@dataclass(frozen=True)
class EmailChanged:
    """The account after the change. ``pending`` is the address that waits for its link (``mail`` says what to
    send), "" when the change counted at once. ``notice`` is the mail to the old address, where one can go."""

    account: Account
    pending: str = ""
    mail: Mail | None = None
    notice: Mail | None = None


def change_username(
    store: Store,
    account_id: AccountId,
    new: str,
    *,
    actor_id: AccountId,
    password: str = "",
    actor_confirmed: bool = False,
) -> Mail | None:
    """A new username for the account; the notice for its confirmed address, None when it has none or nothing
    changed. The store hears ``EVENT_RENAMED`` with the old and the new name after the commit."""
    target, actor = acting(store, account_id, actor_id, password, confirm_self=True, actor_confirmed=actor_confirmed)
    name = names.check_username(new)
    if name == target.username:
        return None
    if names.username_taken(store, name, except_id=target.id):
        raise AccountError("username_taken", "Someone has this username already.", 409)
    try:
        store.set_username(target.id, name)
        if target.display_name and target.display_name == target.username:
            store.set_display_name(target.id, name)
    except Taken as error:
        store.rollback()
        raise common.taken_error(error.what) from error
    store.commit()
    log().info("Username changed name=%s from=%s by=%s", name, target.username, actor.username)
    tell(store, Event(EVENT_RENAMED, target.id, old=target.username, new=name))
    if target.email and target.email_confirmed:
        return Mail(MAIL_USERNAME_CHANGED, target.email, target.id, name, target.display_name)
    return None


def change_display_name(
    store: Store,
    account_id: AccountId,
    new: str,
    *,
    actor_id: AccountId,
    password: str = "",
    actor_confirmed: bool = False,
) -> Account:
    """The display name; empty shows the username, another account's (or a username) is taken. One's own without a
    password, somebody else's as operator, confirmed."""
    target, actor = acting(store, account_id, actor_id, password, confirm_self=False, actor_confirmed=actor_confirmed)
    shown = names.check_display_name(store, new, target.id, required=False)
    try:
        store.set_display_name(target.id, shown)
    except Taken as error:
        store.rollback()
        raise common.taken_error(error.what) from error
    store.commit()
    if actor.id != target.id:
        log().info("Display name changed name=%s by=%s", target.username, actor.username)
    return reload(store, target.id)


def change_language(store: Store, account_id: AccountId, language: str) -> Account:
    """The account's own language; a tag that is none (or "") means the browser's."""
    account = common.account_or_404(store, account_id)
    store.set_language(account.id, common.clean_language(language))
    store.commit()
    return reload(store, account.id)


def _set_email(store: Store, account_id: AccountId, address: str, *, proven: bool) -> None:
    try:
        store.set_email(account_id, address, confirmed=True, proven=proven, source=EMAIL_OWN)
    except Taken as error:
        store.rollback()
        raise common.taken_error(error.what) from error


def _notice(account: Account, new: str) -> Mail | None:
    """To the old address after a change: only where it counted, and only when it is another than the new one."""
    if not account.email or not account.email_confirmed or names.same_address(account.email, new):
        return None
    return Mail(MAIL_EMAIL_CHANGED, account.email, account.id, account.username, account.display_name,
                new_hint=address_hint(new))


def change_email(
    store: Store,
    account_id: AccountId,
    new: str,
    *,
    password: str = "",
    actor_confirmed: bool = False,
    mail: bool = False,
) -> EmailChanged:
    """The account's own address, with its password (``actor_confirmed``: the app confirmed, an account without a
    password by a fresh sign-in at its provider). ``mail``: a mail server and the public address are there, so the
    new address waits for its link and the old one hears of a removal; otherwise it counts at once. "" takes the
    address away (and what waits), with the password as well (since 0.3.10 decided, not only done)."""
    target, _ = acting(
        store, account_id, account_id, password, confirm_self=True, self_without_password=True,
        actor_confirmed=actor_confirmed,
    )
    address = names.clean_email(new)
    if not address:
        store.drop_email_change(target.id)
        store.set_email(target.id, "", confirmed=True, proven=False, source=EMAIL_OWN)
        store.drop_resets(target.id, origin=RESET_SELF)
        store.commit()
        log().info("Email removed name=%s", target.username)
        tell(store, Event(EVENT_EMAIL_CHANGED, target.id, old=target.email, new=""))
        return EmailChanged(reload(store, target.id), notice=_notice(target, "") if mail else None)
    if names.same_address(address, target.email) and target.email_confirmed and target.email_source == EMAIL_OWN:
        raise AccountError("email_same", "This is your address already.", 409)
    if names.email_taken(store, address, except_id=target.id):
        raise AccountError("email_taken", "This address belongs to another account already.", 409)
    if mail:
        # Every link written counts at the brake (``mail:<id>``, five free): no session sends mail to anybody at will.
        common.counted((brake.door_key(brake.DOOR_MAIL, target.id),))
        token = common.new_token()
        store.start_email_change(target.id, address, token, common.utcnow() + timedelta(hours=CONFIRM_HOURS))
        store.commit()
        log().info("Email change waits for its link name=%s", target.username)
        letter = Mail(MAIL_CONFIRM_EMAIL, address, target.id, target.username, target.display_name, token,
                      CONFIRM_HOURS)
        return EmailChanged(reload(store, target.id), address, letter)
    store.drop_email_change(target.id)
    _set_email(store, target.id, address, proven=False)
    store.drop_resets(target.id, origin=RESET_SELF)
    store.commit()
    log().info("Email changed name=%s", target.username)
    tell(store, Event(EVENT_EMAIL_CHANGED, target.id, old=target.email, new=address))
    return EmailChanged(reload(store, target.id))


def resend_email_link(store: Store, account_id: AccountId) -> Mail:
    """"Send the link again": a new link for the address that waits (the one before stops counting), 24 hours from
    now. ``no_pending_email`` when nothing waits. Counts at the brake (``mail:<id>``, since 0.3.4)."""
    account = common.account_or_404(store, account_id)
    if not account.pending_email:
        raise AccountError("no_pending_email", "No address waits for its link.", 409)
    common.counted((brake.door_key(brake.DOOR_MAIL, account.id),))
    token = common.new_token()
    store.start_email_change(account.id, account.pending_email, token, common.utcnow() + timedelta(hours=CONFIRM_HOURS))
    store.commit()
    return Mail(MAIL_CONFIRM_EMAIL, account.pending_email, account.id, account.username, account.display_name, token,
                CONFIRM_HOURS)


def _change(store: Store, token: str) -> tuple[EmailChange, Account]:
    change = store.find_email_change(token) if token else None
    if change is None:
        raise AccountError("email_link_invalid", "This link has been used already or is not valid any more.", 404)
    if common.expired(change.expires_at):
        raise AccountError("email_link_expired", "This link has expired.", 404)
    account = store.get_account(change.account_id)
    if account is None or account.blocked:
        raise AccountError("email_link_invalid", "This link has been used already or is not valid any more.", 404)
    return change, account


def email_change_state(store: Store, token: str) -> EmailChange:
    """The page of a confirmation link: which address it confirms (nothing is used up)."""
    return _change(store, token)[0]


def confirm_email(store: Store, token: str) -> EmailChanged:
    """The address of the link counts from now on and is proven. The link works once; an address another account
    took meanwhile is refused. ``notice`` goes to the old address."""
    change, account = _change(store, token)
    if not store.consume_email_change(change):
        store.rollback()
        raise AccountError("email_link_invalid", "This link has been used already or is not valid any more.", 404)
    if names.email_taken(store, change.address, except_id=account.id):
        store.rollback()
        raise AccountError("email_taken", "This address belongs to another account already.", 409)
    _set_email(store, account.id, change.address, proven=True)
    if account.email_confirmed and names.same_address(change.address, account.email):
        # The address that counted already is proven now (``prove_email``): nothing else changes.
        store.commit()
        log().info("Email proven name=%s", account.username)
        tell(store, Event(EVENT_EMAIL_PROVEN, account.id, old=account.email, new=change.address))
        return EmailChanged(reload(store, account.id))
    store.drop_resets(account.id, origin=RESET_SELF)
    store.commit()
    log().info("Email confirmed name=%s", account.username)
    tell(store, Event(EVENT_EMAIL_CHANGED, account.id, old=account.email, new=change.address))
    return EmailChanged(reload(store, account.id), notice=_notice(account, change.address))


def prove_email(store: Store, account_id: AccountId) -> Mail:
    """Since 0.3.10: a link that proves the address the account has and that counts already ("Confirm by link", for
    the nexpaper inbox and the like; ``change_email`` answers ``email_same`` there). Nothing changes until the link is
    opened (``confirm_email``): then the address is proven, it stays the same and no open link of "Forgot your
    password?" goes. The same mail and time as for a new address (``MAIL_CONFIRM_EMAIL``, ``CONFIRM_HOURS``), counted at
    the brake (``mail:<id>``); "Send the link again" and "Withdraw" work as for a new address. ``nothing_to_prove``
    without an address that counts, or with one proven already; ``email_taken`` while another account has it too."""
    account = common.account_or_404(store, account_id)
    if not account.email or not account.email_confirmed or account.email_proven:
        raise AccountError("nothing_to_prove", "There is no address left to confirm by link.", 409)
    if names.email_taken(store, account.email, except_id=account.id):
        raise AccountError("email_taken", "This address belongs to another account already.", 409)
    common.counted((brake.door_key(brake.DOOR_MAIL, account.id),))
    token = common.new_token()
    store.start_email_change(account.id, account.email, token, common.utcnow() + timedelta(hours=CONFIRM_HOURS))
    store.commit()
    log().info("Email proof waits for its link name=%s", account.username)
    return Mail(MAIL_CONFIRM_EMAIL, account.email, account.id, account.username, account.display_name, token,
                CONFIRM_HOURS)


def withdraw_email_change(store: Store, account_id: AccountId) -> None:
    """The address that waits for its link is withdrawn; the one in effect stays."""
    common.account_or_404(store, account_id)
    store.drop_email_change(account_id)
    store.commit()


def remove_email(
    store: Store,
    account_id: AccountId,
    *,
    actor_id: AccountId,
    password: str = "",
    actor_confirmed: bool = False,
    mail: bool = False,
) -> EmailChanged:
    """Take an account's address away (and what waits for a link). The operator can do this, never set one; the old
    address hears of it where a mail can go. One's own only with the password (an account without one: a fresh
    sign-in at the provider), decided for 0.3.10; the operator with the operator's own."""
    target, actor = acting(
        store, account_id, actor_id, password, confirm_self=True, self_without_password=True,
        actor_confirmed=actor_confirmed,
    )
    store.drop_email_change(target.id)
    store.set_email(target.id, "", confirmed=True, proven=False, source=EMAIL_OWN)
    store.drop_resets(target.id, origin=RESET_SELF)
    store.commit()
    log().info("Email removed name=%s by=%s", target.username, actor.username)
    tell(store, Event(EVENT_EMAIL_CHANGED, target.id, old=target.email, new=""))
    return EmailChanged(reload(store, target.id), notice=_notice(target, "") if mail else None)


def _keep_offer(store: Store, account_id: AccountId, address: str, provider: str) -> bool:
    """``Store.set_offered_email`` with the provider's name where the store takes it (0.3.4); False without it."""
    keep = getattr(store, "set_offered_email", None)
    if keep is None:
        return False
    try:
        takes_name = "provider" in inspect.signature(keep).parameters
    except (TypeError, ValueError):
        takes_name = False
    if takes_name:
        keep(account_id, address, provider=provider)
    else:
        keep(account_id, address)
    return True


def follow_provider_email(store: Store, account_id: AccountId, raw: str) -> bool:
    """``provider_email`` for callers of 0.3.2: True when the address was taken."""
    return provider_email(store, account_id, raw) == PROVIDER_EMAIL_TAKEN


def provider_email(store: Store, account_id: AccountId, raw: str, *, provider: str = "") -> str:
    """What a provider says about the address of an account at a sign-in or a link, for the OIDC binding (inside its
    transaction: nothing is committed here). An account through a provider only follows it (``taken``) when it has no
    address of its own: none, or one that came from a provider. An account with a password is only offered it
    (``offered``, decided 25.11.2026): the person takes it in the profile. ``provider`` (since 0.3.4): the
    provider's name as its button shows it, kept with the offer for "Use the address from <provider>?". An address
    the person declined is never offered again, only another one. The provider's address never counts at once
    and is never proven (the provider may let anybody set any address), and it is never taken or offered when another
    account has it."""
    account = common.account_or_404(store, account_id)
    try:
        address = names.clean_email(raw)
    except AccountError:
        return PROVIDER_EMAIL_NONE
    if not address or names.same_address(address, account.email):
        return PROVIDER_EMAIL_NONE
    if account.has_password:
        return _offer(store, account, address, provider)
    if account.email and account.email_source != EMAIL_PROVIDER:
        return PROVIDER_EMAIL_NONE
    if names.email_taken(store, address, except_id=account.id):
        log().warning("Provider address not taken, another account has it name=%s", account.username)
        return PROVIDER_EMAIL_NONE
    store.set_email(account.id, address, confirmed=False, proven=False, source=EMAIL_PROVIDER)
    store.drop_resets(account.id, origin=RESET_SELF)
    log().info("Provider address followed name=%s", account.username)
    return PROVIDER_EMAIL_TAKEN


def _offer(store: Store, account: Account, address: str, provider: str) -> str:
    if names.same_address(address, account.declined_email):
        # "No, thanks" holds for this address for good (decided 25.11.2026); a standing offer of another one goes.
        if account.offered_email:
            _keep_offer(store, account.id, "", "")
        return PROVIDER_EMAIL_NONE
    if names.same_address(address, account.offered_email) and (
        not provider or provider == account.offered_email_provider
    ):
        return PROVIDER_EMAIL_OFFERED
    if names.email_taken(store, address, except_id=account.id) or not _keep_offer(
        store, account.id, address, provider
    ):
        return PROVIDER_EMAIL_NONE
    log().info("Provider address offered name=%s", account.username)
    return PROVIDER_EMAIL_OFFERED


def take_offered_email(
    store: Store,
    account_id: AccountId,
    *,
    password: str = "",
    actor_confirmed: bool = False,
    mail: bool = False,
) -> EmailChanged:
    """The person takes the address a provider offered ("Use the address from <provider>?"): a change of address
    like ``change_email`` (the password; with a mail server it waits for its link), then the offer is gone. Without an
    offer nothing changes."""
    account = common.account_or_404(store, account_id)
    if not account.offered_email:
        return EmailChanged(account)
    done = change_email(
        store, account.id, account.offered_email, password=password, actor_confirmed=actor_confirmed, mail=mail
    )
    store.set_offered_email(account.id, "")
    store.commit()
    return replace(done, account=reload(store, account.id))


def dismiss_offered_email(store: Store, account_id: AccountId) -> None:
    """The person does not want the offered address ("No, thanks"): for good, for exactly this address (since 0.3.4,
    ``Store.set_declined_email``); the offer comes back only with another address."""
    account = common.account_or_404(store, account_id)
    if account.offered_email:
        decline = getattr(store, "set_declined_email", None)
        if decline is not None:
            decline(account.id, account.offered_email)
        store.set_offered_email(account.id, "")
        store.commit()
        log().info("Provider address declined name=%s", account.username)


# --- Since 1.1.0: the box "Address not confirmed yet" (E23) ---------------------------------------------------------


def needs_proof(account: Account, *, mail_server: bool) -> bool:
    """Whether the profile shows "Address not confirmed yet" with "Send link" (``prove_email``): an address that counts
    but was never proven by link, while a mail server can send one. Decided 25.11.2026 (E23): addresses of before the
    update count as proven (the app's migration to 1.1.0 marks them, ``proven`` for every address that counts; nexpaper
    keeps its unproven ones), so the box only shows for an address entered from now on and not yet proven."""
    waiting = bool(account.pending_email)
    return bool(account.email) and account.email_confirmed and not account.email_proven and not waiting and mail_server


# --- Since 1.1.0: light or dark, for the account on every device ------------------------------------------------------

#: The values of ``ThemeSegment`` (ui): light, dark, as the device says. The order of the segment.
THEMES = ("light", "dark", "system")
#: What an account that never chose shows: as the device says (plan "Einstellungen", Darstellung).
THEME_DEFAULT = "system"


def theme_of(account: Account) -> str:
    """The account's choice, ``THEME_DEFAULT`` while it has none."""
    return account.theme if account.theme in THEMES else THEME_DEFAULT


def browser_theme(raw: object) -> str:
    """A value a browser kept before 1.1.0 (``nexnotes.theme`` = ``dark``; nexmail's JSON ``"dark"``; nextime's
    ``system``), as one of ``THEMES``, else "" (nothing to take)."""
    if not isinstance(raw, str):
        return ""
    value = raw.strip().strip('"').strip().lower()
    return value if value in THEMES else ""


def change_theme(store: Store, account_id: AccountId, theme: str) -> Account:
    """Light, dark or as the device says, for the account on every device (decided 25.11.2026, E5): the person sets
    it in Appearance; no password."""
    if theme not in THEMES:
        raise AccountError("theme_invalid", "The theme is light, dark or system.", 422)
    account = common.account_or_404(store, account_id)
    store.set_theme(account.id, theme)  # type: ignore[attr-defined]
    store.commit()
    return reload(store, account.id)


def adopt_theme(store: Store, account_id: AccountId, browser_value: object) -> str:
    """At the first load after 1.1.0: an account of before that has chosen nothing yet takes, once, (a) the value its
    browser really kept (the person's choice: ``browser_value`` is what the app read from its own storage, never what
    the browser prefers, ``prefers-color-scheme``), else (b) what the app showed before
    (``AppConfig.theme_default_before``: nexmail and nexlore ``dark``), so that nothing changes at the update (E45).
    One that has a choice keeps it; a new account has ``system`` from the start. Returns the theme in effect."""
    account = common.account_or_404(store, account_id)
    if account.theme in THEMES:
        return account.theme
    taken = browser_theme(browser_value)
    source = "browser"
    if not taken:
        taken, source = config.current().theme_default_before, "the app's default of before"
    store.set_theme(account.id, taken)  # type: ignore[attr-defined]
    store.commit()
    log().info("Theme taken name=%s theme=%s from=%s", account.username, taken, source)
    return taken
