"""What the contract tests ask of an app: the ``StandardAdapter`` the app's adapter extends, and small helpers.

The contract tests run the module's flows against the app's real ``Store`` over the app's real tables, and the
sign-in through the app's own route where the adapter says so. They never change; the app fills in its adapter
(``backend/tests/nexkonten_adapter.py``).
"""

from __future__ import annotations

import importlib
import io
import secrets
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any


@dataclass
class Legacy:
    """What the older version of the app left, after the app's migration ran over it.

    ``logins``: every sign-in that worked before, as ``(typed, password, works)``: by username, by address where the
    older version took one, and those that must not work any more or never did (an address several accounts share, a
    blocked account, an account through a provider only). ``invites``: tokens of invitations the older version left
    open; ``fixed_names``: the username an older invitation fixed, by token."""

    logins: list[tuple[str, str, bool]] = field(default_factory=list)
    invites: list[str] = field(default_factory=list)
    fixed_names: dict[str, str] = field(default_factory=dict)
    #: Sign-ins through a provider that worked before, as ``(subject, works)`` (``provider_sign_in``).
    provider_logins: list[tuple[str, bool]] = field(default_factory=list)
    #: Second factors the older version set up (since 0.3.0), as ``(username, seed, codes)``: the base32 seed of the
    #: authenticator app and the recovery codes it showed, in the form the person would type them. Both keep working.
    factors: list[tuple[str, str, list[str]]] = field(default_factory=list)


def password() -> str:
    """A password made at run time (16 characters): no password is written into a test."""
    return secrets.token_urlsafe(12)


def png(width: int = 8, height: int = 8) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 80, 40)).save(out, format="PNG")
    return out.getvalue()


class StandardAdapter:
    """Defaults; every method marked ``APP`` is the app's to write."""

    #: Where the vendored package lives in the app.
    package = "app.vendor.nexkonten"
    #: Wrong passwords until the app locks an account; None for an app without a lock.
    lock_after: int | None = 10
    #: What the app has (since 0.3.2). An app without it says so here; the tests that need it pass over that part
    #: instead of being skipped, and the rest of each test still runs. ``blocking``: accounts can be blocked (the
    #: operator's switch; an app that only removes accounts has none). ``required_second_factor``: a second factor
    #: can be required of a single account (beyond the switch for everybody). ``reusable_invites``: invitations several
    #: may follow (into a space).
    blocking: bool = True
    required_second_factor: bool = True
    reusable_invites: bool = True

    def start(self) -> None:
        """APP: an empty app with a fresh database, ``nexkonten.configure(...)`` as at start-up."""
        raise NotImplementedError("APP: start")

    def stop(self) -> None:
        """APP: close the database, remove temporary folders."""

    def store(self) -> AbstractContextManager[Any]:
        """APP: the app's ``Store`` over one session (one transaction), closed afterwards. Two stores open at the same
        time are two connections: the tests use that for two requests at the same moment."""
        raise NotImplementedError("APP: store")

    def seed(
        self,
        username: str,
        *,
        display_name: str = "",
        email: str = "",
        email_confirmed: bool = True,
        email_proven: bool = False,
        email_source: str = "",
        password: str | None = None,
        operator: bool = False,
        blocked: bool = False,
        picture: bool = False,
        second_factor: str = "none",
    ) -> Any:
        """APP: an account written straight into the tables, as the app (or its older version) would have it, without
        any check: ``username`` as given (capitals, one letter), ``password`` None for an account through a provider
        only, ``picture`` True for a picture of its own, ``second_factor`` ``"none"``, ``"active"`` (it has one) or
        ``"required"`` (the app requires one it has not set up). Returns the account's id. Two accounts may get one
        address."""
        raise NotImplementedError("APP: seed")

    def make_invite(
        self,
        *,
        email: str = "",
        display_name: str = "",
        username: str = "",
        expired: bool = False,
        reusable: bool = False,
    ) -> str:
        """APP: an open invitation for a member, made by the first operator (``seed`` one first), as the app's own
        route makes it; ``username`` only for an invitation of the older version that fixed one; ``reusable`` an
        invitation into a space several may follow (where the app has them; otherwise the same as not). Returns the
        token of the link."""
        raise NotImplementedError("APP: make_invite")

    def open_session(self, account_id: Any, kind: str = "browser") -> Any:
        """APP: something of the account that may sign it in: ``"browser"`` a browser session, ``"waiting"`` a
        sign-in that waits for its second factor, ``"known_browser"`` the mark a browser keeps after signing in as the
        account (``login.authenticate``'s ``known_browser``: signed, random per account), ``"device"`` a paired
        device (or a calendar program's password, an API key, a passkey: what the app has), ``"program"`` (since
        0.3.0) a calendar or address book program's password or an API key, what stays on "sign out everywhere"
        (None where the app has none). Returns what ``session_alive`` needs."""
        raise NotImplementedError("APP: open_session")

    def session_alive(self, handle: Any) -> bool:
        """APP: whether that still counts."""
        raise NotImplementedError("APP: session_alive")

    def delete_account(self, account_id: Any) -> None:
        """APP: the app's own way of deleting an account (for good, or to a bin first)."""
        raise NotImplementedError("APP: delete_account")

    def raw_text(self) -> str:
        """APP: every value in the app's tables of accounts, invitations and links, as one text (to look for a
        token kept in plain text)."""
        raise NotImplementedError("APP: raw_text")

    def legacy(self) -> Legacy:
        """APP: the database of the older version with accounts of every kind (password with and without address,
        provider only with its link, blocked, second factor, an address two accounts share, an open invitation), then
        the app's own start with its migration; see ``Legacy``. Replaces what ``start`` made."""
        raise NotImplementedError("APP: legacy")

    def switch(self, name: str, on: bool) -> None:
        """APP (since 0.3.0): set an operator's switch as the app's settings page does: ``"factor_required"``
        (second factor for everybody, off in a new installation) or ``"passkeys_allowed"`` (on in a new
        installation)."""
        raise NotImplementedError("APP: switch")

    def oidc_store(self) -> AbstractContextManager[Any]:
        """APP: the app's store for the OIDC module (``nexoidc.Store``: ``clean_name``, ``name_taken``,
        ``create_account``) over one session, closed afterwards."""
        raise NotImplementedError("APP: oidc_store")

    def account_of(self, oidc_account_id: Any) -> Any:
        """APP: the account id of the konten store for an id the OIDC store gave (the same in most apps)."""
        return oidc_account_id

    def provider_sign_in(self, subject: str) -> Any:
        """APP: a sign-in through the app's provider for this subject (the app's own fake provider of its nexoidc
        tests): the account id it reaches, None when refused."""
        raise NotImplementedError("APP: provider_sign_in")

    def sign_in(self, typed: str, password: str) -> Any:
        """The account id a sign-in with "Username or email" and password reaches, None when it is refused. APP:
        through the app's own sign-in route (with its field names), up to the session or the code of the second
        factor; the default asks the module only."""
        package = konten_package(self)
        with self.store() as store:
            try:
                return package.login.authenticate(store, typed, password).id
            except package.AccountError:
                return None

    def sign_in_from(self, typed: str, password: str, sender: str) -> tuple[int, Any]:
        """Since 0.3.10: a sign-in from the address ``sender`` behind the module's brake, as ``(status, account id)``:
        ``(200, id)`` when it gets in (a session, or the step of the second factor), ``(401, None)`` refused like a
        wrong password (whatever the app's old code is), ``(429, None)`` too many attempts, ``(403, None)`` blocked.
        APP: through the app's own sign-in route with the sender as the app reads it (``TestClient(app,
        client=(sender, 50000))``, or ``X-Forwarded-For`` behind a proxy the test trusts); the default asks the module
        only (``login.sign_in``)."""
        package = konten_package(self)
        with self.store() as store:
            try:
                return 200, package.login.sign_in(store, typed, password, sender=sender).id
            except package.AccountError as error:
                return error.status, None

    def listed_invites(self) -> list[dict[str, Any]]:
        """APP (since 0.3.10): the open invitations as the operator's list gets them from the app's own route, each a
        dict with at least ``email`` and ``expired`` (bool, what the app gives the list as ``ListedInvite.expired``).
        An expired invitation stays in that list until it is withdrawn."""
        raise NotImplementedError("APP: listed_invites")


def konten_package(adapter: Any) -> ModuleType:
    package = importlib.import_module(adapter.package)
    for name in (
        "common",
        "names",
        "login",
        "setup",
        "invites",
        "profiles",
        "resets",
        "pictures",
        "factor",
        "sessions",
        "avatars",
        "passkeys",
    ):
        importlib.import_module(f"{adapter.package}.{name}")
    return package
