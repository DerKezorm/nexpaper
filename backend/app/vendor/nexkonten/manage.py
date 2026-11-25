"""Since 1.1.0: the operator's account functions, the same in every app (plan "Einstellungen", Accounts; decided
25.11.2026: "Kontofunktionen überall gleich").

- **Several operators:** "Make operator" and "Make member" (nexmail's "Hand over" goes; its old route may stay as
  make the other one operator, then oneself member). There is always at least one operator who can sign in: the last
  one is never made a member, blocked or deleted (``last_operator``, as nexnotes counted).
- **Block and unblock:** a blocked account has no way in (``ManageStore.shut_out``); everything in it stays. Unblocking
  does not bring back the sessions of before.
- **Delete with 30 days to bring back:** the account is gone for everybody at once, its things stay for
  ``DELETE_DAYS`` days; the operator brings it back in that time (``restore``), after it ``purge_due`` removes it for
  good (the app calls it in its housekeeping, nexnotes every six hours).
- **Per app, from the table ``config.FEATURES``:** a storage limit per account (nexnotes, nexpaper, nexdiary,
  nexlore), the rights "AI allowed" (nexmail, nexpaper, nexdiary, nexlore) and "Immich allowed" (nexdiary).

None of this on the operator's own account (``cannot_*_self``); what changes or ends an account asks for the
operator's own password (an operator without one: a fresh sign-in at the provider, ``actor_confirmed``), the boxes of
rights save at once without it (decided 25.11.2026, list of the operator). The store says what happens in the app's
tables (``model3.ManageStore``); after the commit it hears an ``Event`` (``EVENT_BLOCKED`` …) for what follows in the
app (content of a deleted account hidden, spaces handed on).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from . import config
from .common import acting, log, reload, tell, utcnow
from .errors import AccountError
from .model import (
    EVENT_BLOCKED,
    EVENT_DELETED,
    EVENT_PURGED,
    EVENT_RESTORED,
    EVENT_ROLE_CHANGED,
    EVENT_UNBLOCKED,
    Account,
    AccountId,
    Event,
)

#: How long a deleted account can be brought back (nexnotes, nextime, nexfolk had 30).
DELETE_DAYS = 30
#: The largest storage limit (10 TB, as nexnotes took it).
STORAGE_LIMIT_MAX = 10 * 1024**4


@dataclass(frozen=True)
class Removed:
    """A deleted account and the moment it goes for good."""

    account: Account
    purge_at: datetime


def purge_at(deleted_at: datetime) -> datetime:
    """When an account deleted at ``deleted_at`` goes for good."""
    return deleted_at + timedelta(days=DELETE_DAYS)


def is_active_operator(account: Account) -> bool:
    return account.operator and account.blocked_at is None and account.deleted_at is None and not account.blocked


def _app() -> str:
    try:
        return config.current().app_name
    except RuntimeError:
        return "the app"


def _keep_an_operator(store: Any, account: Account) -> None:
    """The last operator that can still sign in is never made a member, blocked or deleted."""
    if is_active_operator(account) and store.active_operators() <= 1:
        raise AccountError("last_operator", f"{_app()} needs at least one operator.", 409)


def _not_self(account_id: AccountId, actor_id: AccountId, code: str) -> None:
    if account_id == actor_id:
        raise AccountError(code, "Not on your own account; that is changed under your own settings.", 409)


def _operator(store: Any, account_id: AccountId, actor_id: AccountId, password: str, actor_confirmed: bool) -> Account:
    target, _actor = acting(
        store,
        account_id,
        actor_id,
        password,
        confirm_self=True,
        self_without_password=True,
        actor_confirmed=actor_confirmed,
    )
    if account_id == actor_id:
        actor = store.get_account(actor_id)
        if actor is None or not actor.operator or actor.blocked:
            raise AccountError("not_allowed", "Only an operator may do this.", 403)
    return target


def _deleted(account: Account) -> bool:
    return account.deleted_at is not None


def set_role(
    store: Any,
    account_id: AccountId,
    operator: bool,
    *,
    actor_id: AccountId,
    password: str = "",
    actor_confirmed: bool = False,
) -> Account:
    """"Make operator" (``operator=True``) or "Make member". Never on one's own account (``cannot_demote_self``), never
    the last operator who can sign in (``last_operator``); a deleted account is ``not_found``."""
    _not_self(account_id, actor_id, "cannot_demote_self")
    target = _operator(store, account_id, actor_id, password, actor_confirmed)
    if _deleted(target):
        raise AccountError("not_found", "No such account.", 404)
    if target.operator == operator:
        return target
    if not operator:
        _keep_an_operator(store, target)
    store.set_operator(account_id, operator)
    store.commit()
    log().info("Role changed account=%s operator=%s", account_id, operator)
    tell(store, Event(EVENT_ROLE_CHANGED, account_id, details={"operator": operator}))
    return reload(store, account_id)


def block(
    store: Any, account_id: AccountId, *, actor_id: AccountId, password: str = "", actor_confirmed: bool = False
) -> Account:
    """Block: no way in any more, everything stays. Again on a blocked account: nothing happens."""
    _not_self(account_id, actor_id, "cannot_block_self")
    target = _operator(store, account_id, actor_id, password, actor_confirmed)
    if _deleted(target):
        raise AccountError("not_found", "No such account.", 404)
    if target.blocked_at is not None:
        return target
    _keep_an_operator(store, target)
    store.set_blocked(account_id, utcnow())
    store.shut_out(account_id)
    store.commit()
    log().info("Account blocked account=%s", account_id)
    tell(store, Event(EVENT_BLOCKED, account_id))
    return reload(store, account_id)


def unblock(
    store: Any, account_id: AccountId, *, actor_id: AccountId, password: str = "", actor_confirmed: bool = False
) -> Account:
    """Unblock: the account signs in again; sessions of before stay ended."""
    _not_self(account_id, actor_id, "cannot_block_self")
    target = _operator(store, account_id, actor_id, password, actor_confirmed)
    if _deleted(target):
        raise AccountError("not_found", "No such account.", 404)
    if target.blocked_at is None:
        return target
    store.end_sessions(account_id)
    store.set_blocked(account_id, None)
    store.commit()
    log().info("Account unblocked account=%s", account_id)
    tell(store, Event(EVENT_UNBLOCKED, account_id))
    return reload(store, account_id)


def remove(
    store: Any, account_id: AccountId, *, actor_id: AccountId, password: str = "", actor_confirmed: bool = False
) -> Removed:
    """Delete: gone for everybody at once and shut out; for ``DELETE_DAYS`` days the operator brings it back. Again on
    a deleted account: nothing happens."""
    _not_self(account_id, actor_id, "cannot_delete_self")
    target = _operator(store, account_id, actor_id, password, actor_confirmed)
    if target.deleted_at is not None:
        return Removed(target, purge_at(target.deleted_at))
    _keep_an_operator(store, target)
    moment = utcnow()
    store.set_deleted(account_id, moment)
    store.shut_out(account_id)
    store.commit()
    log().info("Account deleted account=%s days=%s", account_id, DELETE_DAYS)
    tell(store, Event(EVENT_DELETED, account_id))
    return Removed(reload(store, account_id), purge_at(moment))


def restore(
    store: Any, account_id: AccountId, *, actor_id: AccountId, password: str = "", actor_confirmed: bool = False
) -> Account:
    """Bring a deleted account back while its days run (after them ``not_found``); blocked before, blocked after."""
    target = _operator(store, account_id, actor_id, password, actor_confirmed)
    if target.deleted_at is None:
        return target
    if purge_at(target.deleted_at) <= utcnow():
        raise AccountError("not_found", "No such account.", 404)
    store.end_sessions(account_id)
    store.set_deleted(account_id, None)
    store.commit()
    log().info("Account restored account=%s", account_id)
    tell(store, Event(EVENT_RESTORED, account_id))
    return reload(store, account_id)


def purge_due(store: Any, *, now: datetime | None = None) -> list[AccountId]:
    """Remove for good every account deleted ``DELETE_DAYS`` days ago or longer, one commit each (a failure leaves the
    others done). The app calls it in its housekeeping."""
    limit = (now or utcnow()) - timedelta(days=DELETE_DAYS)
    gone: list[AccountId] = []
    for account_id in store.deleted_before(limit):
        try:
            store.purge_account(account_id)
            store.commit()
        except Exception:  # noqa: BLE001 (one account that fails must not hold the others back)
            store.rollback()
            log().exception("Removing a deleted account for good failed account=%s", account_id)
            continue
        gone.append(account_id)
        log().info("Deleted account removed for good account=%s", account_id)
        tell(store, Event(EVENT_PURGED, account_id))
    return gone


def _feature(feature: str) -> None:
    if not config.current().has(feature):
        raise AccountError("feature_off", f"{_app()} has no {feature.replace('_', ' ')} per account.", 404)


def set_storage_limit(
    store: Any,
    account_id: AccountId,
    limit: int | None,
    *,
    actor_id: AccountId,
    password: str = "",
    actor_confirmed: bool = False,
) -> Account:
    """The account's storage limit in bytes (None: none), only in apps with the feature ``storage_limit``; with the
    operator's password, on the own account too."""
    _feature(config.FEATURE_STORAGE_LIMIT)
    number = isinstance(limit, int) and not isinstance(limit, bool)
    if limit is not None and (not number or not 0 <= limit <= STORAGE_LIMIT_MAX):
        raise AccountError("invalid_limit", "The limit is a number of bytes from 0 to 10 TB.", 422)
    target = _operator(store, account_id, actor_id, password, actor_confirmed)
    if _deleted(target):
        raise AccountError("not_found", "No such account.", 404)
    store.set_storage_limit(account_id, limit)
    store.commit()
    log().info("Storage limit set account=%s limit=%s", account_id, limit)
    return reload(store, account_id)


def set_right(store: Any, account_id: AccountId, right: str, allowed: bool, *, actor_id: AccountId) -> Account:
    """A right of the app (``ai``, ``immich``) for an account, a box that saves at once (no password); only rights
    the app has (``feature_off``)."""
    if right not in config.RIGHTS:
        raise AccountError("feature_off", "No such right.", 404)
    _feature(right)
    target = _operator(store, account_id, actor_id, "", True)
    if _deleted(target):
        raise AccountError("not_found", "No such account.", 404)
    store.set_right(account_id, right, bool(allowed))
    store.commit()
    log().info("Right set account=%s right=%s allowed=%s", account_id, right, bool(allowed))
    return reload(store, account_id)


def caps() -> dict[str, bool]:
    """What the dialog "Manage" offers in this app (``AccountCaps`` in ``konten.ts``, the switches of 1.1.0): the
    same for every app, plus its features."""
    app = config.current()
    return {
        "roles": True,
        "blocking": True,
        "remove": True,
        "restore": True,
        "storageLimit": app.has(config.FEATURE_STORAGE_LIMIT),
        "ai": app.has(config.FEATURE_AI),
        "immich": app.has(config.FEATURE_IMMICH),
    }
