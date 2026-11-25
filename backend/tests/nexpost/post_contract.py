"""What the contract tests ask of an app: the ``StandardAdapter`` the app's adapter extends, the mail server of the
tests, and small helpers.

The contract tests run the module against the app's real ``Store`` over the app's real tables; no mail leaves the
machine (``use_smtp`` puts ``FakeServer`` in place of the network). They never change; the app fills in its adapter
(``backend/tests/nexpost_adapter.py``).
"""

from __future__ import annotations

import importlib
import secrets
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from email.message import EmailMessage
from types import ModuleType
from typing import Any


@dataclass
class Legacy:
    """What the older version left, after the app's start ran over it. ``settings``: the mail server as it must read
    now (``MailSettings`` with the password opened); ``queued``: mails the older version left waiting in its outbox
    (0 where it had none), which still go out."""

    settings: Any
    queued: int = 0


def password() -> str:
    """A password made at run time: no password is written into a test."""
    return secrets.token_urlsafe(12)


#: The first bytes of a PNG and a little more: a logo for the tests of the module (an app gives its own).
LOGO = b"\x89PNG\r\n\x1a\n" + b"logo of the tests"


@dataclass
class FakeServer:
    """The mail server of the tests. ``fail`` holds exceptions of ``smtplib`` the next steps raise, in turn: an
    ``SMTPAuthenticationError`` at the login, any other at sending."""

    sent: list[EmailMessage] = field(default_factory=list)
    logins: list[tuple[str, str]] = field(default_factory=list)
    fail: list[BaseException] = field(default_factory=list)
    connections: int = 0

    def factory(self, settings: Any, timeout: float, context: Any) -> _Connection:
        self.connections += 1
        return _Connection(self)


class _Connection:
    def __init__(self, server: FakeServer) -> None:
        self.server = server

    def login(self, user: str, secret: str) -> None:
        import smtplib

        if self.server.fail and isinstance(self.server.fail[0], smtplib.SMTPAuthenticationError):
            raise self.server.fail.pop(0)
        self.server.logins.append((user, secret))

    def send_message(self, message: EmailMessage) -> None:
        if self.server.fail:
            raise self.server.fail.pop(0)
        self.server.sent.append(message)

    def quit(self) -> None:
        return None


class StandardAdapter:
    """Defaults; every method marked ``APP`` is the app's to write."""

    #: Where the vendored package lives in the app.
    package = "app.vendor.nexpost"

    def start(self) -> None:
        """APP: an empty app with a fresh database, ``nexpost.configure(...)`` as at start-up."""
        raise NotImplementedError("APP: start")

    def stop(self) -> None:
        """APP: close the database, remove temporary folders."""

    def store(self) -> AbstractContextManager[Any]:
        """APP: the app's ``Store`` over one session (one transaction), closed afterwards. Two stores open at the same
        time are two connections (two workers)."""
        raise NotImplementedError("APP: store")

    def raw_text(self) -> str:
        """APP: every value of the app's tables of settings and outbox, as one text (to look for a password kept in
        plain text)."""
        raise NotImplementedError("APP: raw_text")

    def legacy(self) -> Legacy:
        """APP: the database of the older version with its mail server saved by its own settings page (its key
        names, its values of encryption, its sealed password) and mails waiting where it had an outbox, then the
        app's own start; see ``Legacy``. Replaces what ``start`` made."""
        raise NotImplementedError("APP: legacy")

    def new_sign_in_letter(self, where: str, sender: str) -> Any:
        """APP (since 1.0.0): the letter the app writes for the mail "New sign-in" (``nexkonten.sessions.new_sign_in``
        turned into a ``Letter`` the way the app does it, e.g. its ``letter_of``/``queue`` caught with
        ``nexpost.testing.catch_mail``): an account with a confirmed address signs in from a browser it does not know,
        with the User-Agent ``where``, from the address ``sender``. The letter names the browser on its system and the
        moment, links the app's page Security (the button "See signed-in devices"), and never names ``sender``."""
        raise NotImplementedError("APP: new_sign_in_letter")

    #: Since 1.1.0: where the app mounts ``nexpost.api.router``.
    mail_prefix = "/api/server/mail"

    def account(self, address: str, *, language: str, name: str, confirmed: bool) -> Any:
        """APP (since 1.1.0): a new account of the app with this address (confirmed or not), language and name,
        committed; its id as ``Store.recipient`` takes it."""
        raise NotImplementedError("APP: account")

    def client(self, role: str) -> Any:
        """APP (since 1.1.0): a test client of the app (``fastapi.testclient.TestClient``) with ``nexpost.api.router``
        mounted at ``mail_prefix``, signed in as ``role``: ``anonymous`` (no session), ``member``, ``operator``."""
        raise NotImplementedError("APP: client")


def post_package(adapter: Any) -> ModuleType:
    package = importlib.import_module(adapter.package)
    for name in ("letters", "settings", "send", "outbox", "app_letters"):
        importlib.import_module(f"{adapter.package}.{name}")
    return package
