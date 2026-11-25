"""The first account: the operator, set up with a setup code.

Whoever reaches a fresh server first would otherwise become its operator. So the first account brings a code: the one
in ``<APP>_SETUP_TOKEN``, else one made at the start of the process and written to the server's log at every start
while there is no account. Once an account exists there is neither code nor page; a running installation never asks
for it.

A code the operator fixes needs at least ``TOKEN_MIN`` characters (a shorter one is ignored, with a line in the log,
and the made code counts) and is compared exactly; the made code (``ABCD-EF01-2345``) is compared without regard to
case. The app's brake counts wrong codes like sign-ins (``login.attempt_key``). One setup at a time in the process,
and once in the life of the database (``Store.claim_setup``): two processes never both make an operator.

The address given here counts as confirmed at once: there is no mail server yet, and the account belongs to the person
who owns the server.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass

from . import config
from .common import add_account, clean_language, log, next_step, reload, tell
from .errors import AccountError
from .model import EVENT_CREATED, Account, Event, NewAccount, Store
from .names import check_password_rule, check_username, clean_display_name, clean_email

#: One setup at a time: two at once would each count no account yet and make two operators.
_lock = threading.Lock()
_generated: str | None = None
#: The shortest code an operator may fix in ``<APP>_SETUP_TOKEN``.
TOKEN_MIN = 16


def _given() -> str:
    """The code the operator fixed, when it is long enough."""
    given = config.current().given_setup_token()
    return given if len(given) >= TOKEN_MIN else ""


def setup_code() -> str:
    """The code the first account must bring: the one the operator fixed, else one made once per process."""
    global _generated
    given = _given()
    if given:
        return given
    if _generated is None:
        _generated = "-".join(secrets.token_hex(2).upper() for _ in range(3))
    return _generated


def forget_generated_code() -> None:
    """Tests: the next ``setup_code`` makes a new one, as a new start of the process would."""
    global _generated
    _generated = None


def needed(store: Store) -> bool:
    """The setup page is there: no account at all yet."""
    return store.count_accounts() == 0


def announce_setup(store: Store) -> None:
    """At every start while there is no account: the code in the log, where only whoever runs the server reads it."""
    if not needed(store):
        return
    cfg = config.current()
    if cfg.given_setup_token() and not _given():
        log().error("%s is shorter than %s characters and is ignored.", cfg.setup_token_env, TOKEN_MIN)
    if _given():
        log().warning("%s is not set up yet. Open it and give %s as the setup code.", cfg.app_name, cfg.setup_token_env)
    else:
        log().warning("%s is not set up yet. The setup code is %s (new at every start until set up).",
                      cfg.app_name, setup_code())


def _code_fits(code: str) -> bool:
    """A fixed code exactly, the made code without regard to case; both in constant time."""
    typed = (code or "").strip()
    if _given():
        return secrets.compare_digest(typed.encode("utf-8"), _given().encode("utf-8"))
    return secrets.compare_digest(typed.upper().encode("utf-8"), setup_code().upper().encode("utf-8"))


def check_code(store: Store, code: str) -> None:
    """Only a server without an account, and only with the setup code: for setting up, and for every other way to
    become its operator before that (restoring a backup before the setup). ``already_set_up`` or
    ``setup_code_wrong``."""
    if not needed(store):
        raise AccountError("already_set_up", f"{config.current().app_name} is set up already.", 409)
    if not _code_fits(code):
        log().warning("Setup refused, wrong setup code")
        raise AccountError("setup_code_wrong", "The setup code is wrong. It is in the server's log.", 403)


@dataclass(frozen=True)
class SetUp:
    """The operator's new account, and what the app starts next (``common.next_step``: a session, or one that must
    set up a second factor first)."""

    account: Account
    next: str


def setup(
    store: Store, *, code: str, display_name: str, username: str, email: str, password: str, language: str = ""
) -> SetUp:
    """The operator's account. ``already_set_up`` when any account exists, ``setup_code_wrong`` before anything
    else is looked at, then the fields in the order of the page. ``language`` comes from the browser silently (no
    field); the account changes it in its profile."""
    with _lock:
        check_code(store, code)
        shown = clean_display_name(display_name)
        if not shown:
            raise AccountError("display_name_empty", "Enter a display name.", 422)
        name = check_username(username)
        address = clean_email(email)
        check_password_rule(password)
        if not store.claim_setup():
            store.rollback()
            raise AccountError("already_set_up", f"{config.current().app_name} is set up already.", 409)
        account_id = add_account(
            store,
            NewAccount(
                username=name,
                display_name=shown,
                email=address,
                email_confirmed=True,
                password=password,
                language=clean_language(language),
                operator=True,
            ),
        )
        store.commit()
    log().info("Set up, operator account created name=%s", name)
    tell(store, Event(EVENT_CREATED, account_id))
    account = reload(store, account_id)
    return SetUp(account, next_step(store, account))
