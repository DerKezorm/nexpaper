"""Since 1.1.0: the operator's switches on the page Server, Sign-in, with the same rules in every app (plan
"Einstellungen", Anmeldung, card "Anmeldung"):

- **Password sign-in** goes off only while a provider is active (``provider_first``); the operator can always sign in
  with the password (the module oidc's rule).
- **"Require a second factor of everybody"** goes on only when it would not lock the operator out: the operator's own
  account has a second factor (an authenticator or a passkey), or signs in without a password (through a provider
  only), or came in through a provider that checks the second factor itself (``provider_checked``); else
  ``own_second_factor_first``. It goes **off only with the operator's password** (an operator without one: a fresh
  sign-in at the provider), as nexpaper and nexdiary asked.
- **Passkeys allowed**: no rule.

The public address belongs to the module oidc (``public_url_change``) and the app's settings; it is saved on its own.
The store keeps the switches under the app's own names (``model3.SignInStore``).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from . import factor
from .common import confirm, log
from .errors import AccountError
from .model import SECOND_FACTOR_ACTIVE, AccountId
from .model3 import SignInSettings


def has_own_factor(store: Any, account_id: AccountId) -> bool:
    """An authenticator or a passkey (``factor.has_factor``), or what the app's store says of it
    (``Store.second_factor`` ``active``: an app that keeps the second factor its own way)."""
    if factor.has_factor(store, account_id):
        return True
    return store.second_factor(account_id) == SECOND_FACTOR_ACTIVE


def may_require_factor(store: Any, account_id: AccountId, *, provider_checked: bool = False) -> bool:
    """Whether the operator may switch "Require a second factor of everybody" on now (see above). The page greys the
    box out while not (``view``: ``factor_may_go_on``)."""
    account = store.get_account(account_id)
    if account is None:
        return False
    return has_own_factor(store, account_id) or not account.has_password or provider_checked


def change(
    store: Any,
    actor_id: AccountId,
    *,
    password_login: bool | None = None,
    factor_required: bool | None = None,
    passkeys_allowed: bool | None = None,
    password: str = "",
    actor_confirmed: bool = False,
    provider_checked: bool = False,
) -> SignInSettings:
    """Change what is given (None: as it is), by an operator, with the rules above; one commit."""
    actor = store.get_account(actor_id)
    if actor is None or not actor.operator or actor.blocked:
        raise AccountError("not_allowed", "Only an operator may change the sign-in.", 403)
    now = store.sign_in_settings()
    wanted = replace(
        now,
        **{
            name: bool(value)
            for name, value in (
                ("password_login", password_login),
                ("factor_required", factor_required),
                ("passkeys_allowed", passkeys_allowed),
            )
            if value is not None
        },
    )
    if now.password_login and not wanted.password_login and store.active_providers() < 1:
        raise AccountError("provider_first", "Without an active provider the password sign-in stays on.", 409)
    if wanted.factor_required and not now.factor_required:
        if not may_require_factor(store, actor_id, provider_checked=provider_checked):
            raise AccountError(
                "own_second_factor_first", "Set up a second factor of your own first, or you would be locked out.", 409
            )
    if now.factor_required and not wanted.factor_required:
        # Weaker for everybody: the operator confirms it is them (a stranger at an open session must not).
        confirm(store, actor, password, actor_confirmed, without_password=True)
    if wanted == now:
        return now
    store.save_sign_in_settings(wanted)
    store.commit()
    log().info(
        "Sign-in settings changed password_login=%s factor_required=%s passkeys_allowed=%s",
        wanted.password_login,
        wanted.factor_required,
        wanted.passkeys_allowed,
    )
    return wanted


def view(store: Any, account_id: AccountId, *, provider_checked: bool = False) -> dict[str, object]:
    """What the card "Anmeldung" needs besides the public address: the switches, whether the password sign-in may go
    off (``password_may_go_off``: a provider is active) and the second factor may go on (``factor_may_go_on``), and the
    emergency hammer (``second_factor_off``)."""
    settings = store.sign_in_settings()
    return {
        "password_login": settings.password_login,
        "factor_required": settings.factor_required,
        "passkeys_allowed": settings.passkeys_allowed,
        "password_may_go_off": store.active_providers() > 0,
        "factor_may_go_on": may_require_factor(store, account_id, provider_checked=provider_checked),
        "second_factor_off": factor.switched_off(),
    }
