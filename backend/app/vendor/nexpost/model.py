"""The data of system mail and the ``Store`` the app implements over its own tables.

The settings live where the app keeps them today (``settings`` with ``smtp_host`` … in most apps, ``einstellung``
with ``system_smtp_*`` in one); the store maps them. The password reaches the store in plain text and leaves it only
opened: the store seals it with the app's own key and context, so a password saved under the older version keeps
working. The outbox is a table of the app (``notify_outbox`` where it has one).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
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


#: Since 1.1.0: the headers a letter may carry beyond those ``send.message`` sets: one-click unsubscribing (RFC 8058,
#: nextasks' reports and events) and the language of the text. Nothing else, so that no app can add a header that
#: changes where a mail goes (``Bcc``, ``Reply-To``) by accident.
EXTRA_HEADERS = ("Content-Language", "List-Unsubscribe", "List-Unsubscribe-Post")
#: Since 1.1.0: how long a ``kind`` and a ``key`` may be (the outbox tables keep them in short columns).
KIND_LIMIT = 32
KEY_LIMIT = 120


def _headers(given: object) -> tuple[tuple[str, str], ...]:
    """Headers as pairs, in order: from a mapping, from pairs, or from lists (a letter read back from JSON)."""
    if not given:
        return ()
    pairs = given.items() if isinstance(given, Mapping) else given
    found: list[tuple[str, str]] = []
    for pair in pairs:  # type: ignore[union-attr]
        name, value = pair
        name = str(name)
        if name not in EXTRA_HEADERS:
            raise ValueError(f"a letter cannot carry the header {name!r} (allowed: {', '.join(EXTRA_HEADERS)})")
        text = " ".join("".join(" " if char < " " or char == "\x7f" else char for char in str(value)).split())
        if text:
            found.append((name, text))
    return tuple(found)


@dataclass(frozen=True)
class Letter:
    """A mail ready to send: one line subject, plain text, and HTML (``""`` for text only).

    Since 1.1.0 two more fields, both with defaults (a letter of 1.0.0, also one read back from an outbox row of 1.0.0,
    is still a letter): ``headers``, pairs of the ``EXTRA_HEADERS`` (``Content-Language``, one-click unsubscribing), and
    ``key``, the app's name for this one mail (``daily:42:2026-11-25``): the outbox takes a letter with a key it holds
    already only once (``Store.add_to_outbox``)."""

    to: str
    subject: str
    text: str
    html: str = ""
    kind: str = ""
    headers: tuple[tuple[str, str], ...] = ()
    key: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", _headers(self.headers))
        if len(self.kind) > KIND_LIMIT or len(self.key) > KEY_LIMIT:
            raise ValueError(f"kind (at most {KIND_LIMIT}) or key (at most {KEY_LIMIT}) too long")

    def header(self, name: str) -> str:
        """The value of one of the extra headers, "" when the letter has none."""
        return next((value for key, value in self.headers if key == name), "")


def letter_data(letter: Letter) -> dict[str, object]:
    """Since 1.1.0: a letter as plain data for a JSON column of the outbox (``headers`` as lists)."""
    return {
        "to": letter.to,
        "subject": letter.subject,
        "text": letter.text,
        "html": letter.html,
        "kind": letter.kind,
        "headers": [list(pair) for pair in letter.headers],
        "key": letter.key,
    }


def letter_from(data: Mapping[str, object]) -> Letter:
    """Since 1.1.0: a letter back from ``letter_data`` or from the JSON an app of 1.0.0 stored (``Letter.__dict__``:
    without ``headers`` and ``key``); names a letter does not have are left out."""
    return Letter(
        to=str(data.get("to", "")),
        subject=str(data.get("subject", "")),
        text=str(data.get("text", "")),
        html=str(data.get("html", "") or ""),
        kind=str(data.get("kind", "") or ""),
        headers=data.get("headers") or (),  # type: ignore[arg-type]
        key=str(data.get("key", "") or ""),
    )


@dataclass(frozen=True)
class Recipient:
    """Since 1.1.0: where a letter to an account goes (``Store.recipient``): the address the app mails this account
    at, the account's language (``de``, ``en``, ``fr``; "" for the operator's), its name for the greeting and its time
    zone (an IANA name, "" for the server's)."""

    address: str
    language: str = ""
    name: str = ""
    time_zone: str = ""


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
        """A new outbox row, due at once; its id. Keeps the whole letter (since 1.1.0 also ``headers`` and ``key``).
        Since 1.1.0: a letter with a ``key`` the outbox holds already (waiting, sent or given up) adds nothing; the id
        of the row that has it."""
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

    # Since 1.1.0.

    def waiting(self) -> int:
        """How many mails wait in the outbox (neither sent nor given up), for the operator's page."""
        ...

    def on_commit(self, callback: Callable[[], None]) -> None:
        """Call ``callback`` once, after the next commit of this store's transaction went through (SQLAlchemy:
        ``event.listen(session, "after_commit", …, once=True)``); not after a rollback. ``outbox.queue`` hands it
        ``outbox.nudge``: a queued mail goes out at once, not at the next round of the worker."""
        ...

    def recipient(self, account: object) -> Recipient | None:
        """Where a letter of the app to this account goes (its id, as the app names accounts): the address the app
        mails it at (as a rule the confirmed one), its language, name and time zone; None when it has none (no
        account, no address, not confirmed, blocked)."""
        ...
