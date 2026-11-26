"""Since 1.1.0: what the app's store does for the operator's account functions (``manage``), the theme of an account
(``profiles.change_theme``) and the operator's sign-in settings (``signin``).

Kept apart from ``model`` and ``model2`` so that an adapter of 1.0.0 stays valid: an app that copies 1.1.0 adds these
methods to the store object it has (most apps answer every protocol with one object), and the contract tests of 1.1.0
ask for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .model import AccountId


class ManageStore(Protocol):
    """The operator's functions over the app's tables (role, blocked, deleted, storage limit, rights).

    ``Account.blocked_at``, ``Account.deleted_at``, ``Account.storage_limit`` and ``Account.rights`` come from
    ``get_account``; ``Account.blocked`` stays true for a blocked and for a deleted account."""

    def active_operators(self) -> int:
        """How many operators can still sign in: role operator, neither blocked nor deleted."""
        ...

    def set_operator(self, account_id: AccountId, operator: bool) -> None:
        """Operator (True) or member (False). Several operators are allowed (nexmail: the column that said "the one
        operator" now says it per account)."""
        ...

    def set_blocked(self, account_id: AccountId, at: datetime | None) -> None:
        """Blocked since ``at``; None unblocks (and sets the count of wrong passwords to 0, as nexnotes does)."""
        ...

    def set_deleted(self, account_id: AccountId, at: datetime | None) -> None:
        """Deleted at ``at`` (the account is gone for everybody, its things stay until ``purge_account``); None brings
        it back."""
        ...

    def shut_out(self, account_id: AccountId) -> None:
        """After blocking or deleting: no way in is left. Browser sessions and sign-ins that wait end, paired devices
        are disconnected, API keys, MCP and OAuth grants, calendar programs and providers are refused while the
        account is blocked or deleted (the app checks ``blocked`` wherever it lets something in), the key of known
        browsers is renewed. Nothing is deleted that unblocking should bring back (keys of programs may stay,
        refused)."""
        ...

    def deleted_before(self, moment: datetime) -> list[AccountId]:
        """Accounts deleted at or before ``moment`` (their days to bring them back are over)."""
        ...

    def purge_account(self, account_id: AccountId) -> None:
        """Gone for good, with everything the app says it owned (notes, mailboxes, documents, pages …; the app's
        rules: nexpaper hands documents on before). Its username stays reserved for ever (``name_reserved``)."""
        ...

    def set_storage_limit(self, account_id: AccountId, limit: int | None) -> None:
        """The account's storage limit in bytes, None for none (feature ``storage_limit``)."""
        ...

    def set_right(self, account_id: AccountId, right: str, allowed: bool) -> None:
        """A right of the app for this account (``ai``, ``immich``), in the app's own column (``ai_allowed``,
        ``ki_erlaubt``, ``immich_allowed``)."""
        ...


class ThemeStore(Protocol):
    def set_theme(self, account_id: AccountId, theme: str) -> None:
        """``light``, ``dark`` or ``system``, kept at the account (the app's own column where it had one:
        nexpaper and nexdiary ``profile.mode``, nexlore ``mode``)."""
        ...


@dataclass(frozen=True)
class SignInSettings:
    """The operator's switches on the page Server › Sign-in (the public address is the module oidc's and the app's)."""

    password_login: bool = True
    factor_required: bool = False
    passkeys_allowed: bool = True


class SignInStore(Protocol):
    def sign_in_settings(self) -> SignInSettings:
        """What the app has stored (its own names: nexmail ``passwort``, ``zwei_faktor_fuer_alle``,
        ``passkeys_erlaubt``)."""
        ...

    def save_sign_in_settings(self, settings: SignInSettings) -> None: ...

    def active_providers(self) -> int:
        """How many providers (module oidc) are active: without one, the password sign-in stays on."""
        ...
