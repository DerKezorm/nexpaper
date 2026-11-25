"""Signing in with a password: one field "Username or email", then the password.

With an @ the field is an address, otherwise a username; both without regard to case. An address counts only when it
counts for the account (``email_confirmed``) and no other account has it (an older version may have given one
address to several accounts: none of them signs in by it, each still by its username). The display name never
counts, nor does a former username: in the browser only the current name signs in.

Every refusal is the same, whatever was wrong: ``wrong_credentials``, "Username, email or password is wrong.", and an
unknown name costs the same time as a wrong password. A blocked account hears that it is blocked only after its right
password.

Failures count at the account, however it was named (``Store.note_failure``); after the app's limit it is locked
(``Store.is_locked``), and a locked account answers like a wrong password. A browser that signed in as the account
before (``known_browser``, the account its cookie names) gets in all the same, and its failures do not count: a
stranger can lock an account against the world, not against its owner. Checks of one account run one after another.
The app's brake counts every attempt twice (``attempt_key``): at the sender, and at the account it names or, when
it names none, at what was typed. Both counts are checked, whatever the input: a brake that counted unknown input at
the sender alone would answer "too many attempts" for unknown names only and tell which names exist. Every failure
costs one write and one commit, also for an unknown name (``Store.note_failure(None)``): the time of the answer does
not tell either.

Calendar and address book programs (DAV) sign in with ``background_account``: current name, former name or address,
and always their own device password, which the app checks.
"""

from __future__ import annotations

import hashlib
import threading

from .common import log
from .errors import AccountError
from .model import Account, AccountId, Store
from .names import EMAIL_MAX, same_address

#: Longer than any username or address: not looked up at all.
LOGIN_MAX = EMAIL_MAX

_locks: dict[object, threading.Lock] = {}
_locks_guard = threading.Lock()


def _one_check_at_a_time(account_id: AccountId) -> threading.Lock:
    """Checks of one account's password in turn: many wrong ones at once would all pass the lock test before the
    first failure was counted."""
    with _locks_guard:
        return _locks.setdefault(account_id, threading.Lock())


def _unique(found: list[Account], address: str) -> Account | None:
    same = [account for account in found if same_address(account.email, address)]
    return same[0] if len(same) == 1 else None


def by_address(store: Store, address: str) -> Account | None:
    """The one account an address signs in: its address counts, and no other account has it."""
    account = _unique(store.find_by_email(address), address)
    return account if account is not None and account.email_confirmed else None


def by_username(store: Store, typed: str) -> Account | None:
    """The account of a current username in any case. Should an older version hold two names that differ only in
    case, the one written exactly as typed counts, else neither."""
    found = [account for account in store.find_by_username(typed) if account.username.lower() == typed.lower()]
    if len(found) == 1:
        return found[0]
    exact = [account for account in found if account.username == typed]
    return exact[0] if len(exact) == 1 else None


def resolve_login(store: Store, typed: str) -> Account | None:
    """The account meant by what was typed into "Username or email"; None when there is none (or none for sure)."""
    text = (typed or "").strip()
    if not text or len(text) > LOGIN_MAX:
        return None
    if "@" in text:
        return by_address(store, text)
    return by_username(store, text)


def background_account(store: Store, typed: str) -> Account | None:
    """The account a calendar or address book program names as its user: the current username, a former one, or
    the account's address (which, no other account having it, need not count yet: the device password decides).
    Its paths hang on a fixed key of the account, never on a name; the app checks the device password."""
    text = (typed or "").strip()
    if not text or len(text) > LOGIN_MAX:
        return None
    if "@" in text:
        return _unique(store.find_by_email(text), text)
    current = by_username(store, text)
    if current is not None:
        return current
    former = store.find_by_former_name(text)
    return former[0] if len({account.id for account in former}) == 1 else None


def attempt_key(store: Store, typed: str, sender: str) -> tuple[str, str]:
    """The two counts of the app's brake for a sign-in, a request for a link or a setup code: the sender
    (``sender:<address>``), and the account the field names however it is named (``account:<id>``: username or
    address, any case, one count) or, naming none, what was typed (``typed:<hash>``). The app counts and checks
    **both**, for every input, and refuses when either is full."""
    account = resolve_login(store, typed)
    digest = hashlib.sha256((typed or "").strip().lower().encode("utf-8")).hexdigest()[:24]
    target = f"account:{account.id}" if account is not None else f"typed:{digest}"
    # An unknown sender never shares one count with every other unknown sender: it counts with what it aims at.
    origin = (sender or "").strip() or f"none:{target}"
    return f"sender:{origin}", target



def wrong_credentials(account_id: AccountId | None = None) -> AccountError:
    error = AccountError("wrong_credentials", "Username, email or password is wrong.", 401)
    error.account_id = account_id
    return error


def authenticate(
    store: Store, typed: str, password: str, *, known_browser: AccountId | None = None
) -> Account:
    """The account for a username or address and its password; ``wrong_credentials`` for anything that does not fit
    (with ``account_id`` set when the account is known), ``account_blocked`` only after the right password.
    Failures are counted at the account and committed. A success is not noted here: the app calls ``succeeded``
    once the whole sign-in is done (after the second factor where there is one)."""
    account = resolve_login(store, typed)
    if account is None or not account.has_password:
        store.check_password(None, password or "")
        store.note_failure(None)
        store.commit()
        log().warning("Sign-in failed for an unknown account or one without a password")
        raise wrong_credentials()
    known = known_browser is not None and known_browser == account.id
    with _one_check_at_a_time(account.id):
        if store.is_locked(account.id) and not known:
            store.check_password(None, password or "")
            store.note_failure(None)
            store.commit()
            log().warning("Sign-in refused, account locked name=%s", account.username)
            raise wrong_credentials(account.id)
        if not store.check_password(account.id, password or ""):
            if not known:
                store.note_failure(account.id)
                store.commit()
            log().warning("Sign-in failed, wrong credentials name=%s", account.username)
            raise wrong_credentials(account.id)
    if account.blocked:
        log().warning("Sign-in refused, account blocked name=%s", account.username)
        error = AccountError("account_blocked", "This account is blocked. Ask the operator.", 403)
        error.account_id = account.id
        raise error
    return account


def succeeded(store: Store, account_id: AccountId) -> None:
    """The whole sign-in is done: the count of failures starts anew."""
    store.note_success(account_id)
    store.commit()


def duplicate_email(store: Store, account: Account) -> bool:
    """The account's address is held by another account too (left by an older version): it finds no account, and
    the operator's list says so."""
    if not account.email:
        return False
    others = [entry for entry in store.find_by_email(account.email) if same_address(entry.email, account.email)]
    return any(entry.id != account.id for entry in others)
