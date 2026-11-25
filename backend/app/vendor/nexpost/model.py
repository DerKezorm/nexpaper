"""The data of system mail and the ``Store`` the app implements over its own tables.

The settings live where the app keeps them today (``settings`` with ``smtp_host`` … in most apps, ``einstellung``
with ``system_smtp_*`` in one); the store maps them. The password reaches the store in plain text and leaves it only
opened: the store seals it with the app's own key and context, so a password saved under the older version keeps
working. The outbox is a table of the app (``notify_outbox`` where it has one).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

#: ``MailSettings.security``.
STARTTLS = "starttls"
TLS = "tls"
NONE = "none"
SECURITY = (STARTTLS, TLS, NONE)


@dataclass(frozen=True)
class MailSettings:
    """The mail server. ``password`` is the opened password ("" for none). ``sender_name`` "" means the app's name.
    ``ca_file``: a file of trusted certificates of the app's own (a server with a certificate of its own CA)."""

    host: str = ""
    port: int = 587
    security: str = STARTTLS
    user: str = ""
    password: str = ""
    sender: str = ""
    sender_name: str = ""
    ca_file: str = ""

    @property
    def configured(self) -> bool:
        """A server and a sender: mail can go out."""
        return bool(self.host.strip() and self.sender.strip())


@dataclass(frozen=True)
class Letter:
    """A mail ready to send: one line subject, plain text, and HTML (``""`` for text only)."""

    to: str
    subject: str
    text: str
    html: str = ""
    kind: str = ""


@dataclass(frozen=True)
class OutboxItem:
    """One mail waiting in the outbox. ``attempts`` made so far, ``next_at`` when to try again, ``error`` the last."""

    id: int | str
    letter: Letter
    created_at: datetime
    next_at: datetime
    attempts: int = 0
    error: str = ""


@dataclass(frozen=True)
class MailStatus:
    """For the operator's page: the last mail that went out, the last error and when."""

    last_ok_at: datetime | None = None
    last_error: str = ""
    last_error_at: datetime | None = None


class Store(Protocol):
    """Implemented by the app."""

    def mail_settings(self) -> MailSettings:
        """The settings with the password opened (the app's own key and context, also for a password the older
        version saved)."""
        ...

    def save_mail_settings(self, settings: MailSettings, password: str | None) -> None:
        """Store the settings; ``password`` None keeps the stored one (the form never shows it), "" removes it."""
        ...

    def add_to_outbox(self, letter: Letter, now: datetime) -> int | str:
        """A new outbox row, due at once; its id."""
        ...

    def due(self, now: datetime, limit: int) -> list[OutboxItem]:
        """Rows whose ``next_at`` has come, oldest first, not given up and not sent."""
        ...

    def claim(self, item_id: int | str, now: datetime, until: datetime) -> bool:
        """Take a due row for this worker with one statement (``next_at`` moves to ``until``); False when another
        worker took it."""
        ...

    def mark_sent(self, item_id: int | str) -> None:
        """The row went out (deleted, or marked)."""
        ...

    def mark_failed(self, item_id: int | str, attempts: int, next_at: datetime | None, error: str) -> None:
        """Another try at ``next_at``; None: given up (kept for the operator's page)."""
        ...

    def note_result(self, status: MailStatus) -> None: ...

    def mail_status(self) -> MailStatus: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
