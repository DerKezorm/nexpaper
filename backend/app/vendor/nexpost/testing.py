"""Since 1.0.0: catching the system mail in an app's own tests, both ways it leaves: at once (``send.deliver``, the way
"Forgot your password?" of ``konten`` sends since 0.3.10) and through the outbox (``outbox.queue``, everything else).

A test of the app (the test "Bestand" first of all) that read its mail only from the outbox missed the mail that goes
out at once; nexnotes, nextime and nexfolk each caught ``send.deliver`` on their own. This is that catch, the same in
every app::

    from app.vendor.nexpost import testing

    with testing.catch_mail() as caught:
        ...                                    # the request that mails
    assert [letter.to for letter in caught.letters] == ["kim@example.org"]

What goes out at once is kept instead of sent (no mail server needed, as long as the settings name one: a missing one
still answers ``mail_off`` like the real ``deliver``); ``fail=True`` refuses it like a mail server that cannot be
reached (``mail_unreachable``). What goes into the outbox is kept **and** still queued, so that a test that reads the
outbox keeps its checks. Not loaded by ``nexpost/__init__.py``; only the standard library. The app calls the module
as ``nexpost.send.deliver`` and ``nexpost.outbox.queue`` (never a name it imported once), otherwise nothing is
caught.

Since E44 every way of the module goes through ``send.deliver`` (the outbox, ``deliver_now``, ``test_mail``, the
letters of the app), and while ``catch_mail`` is on **no test reaches a real mail server**: ``smtplib.SMTP``,
``smtplib.SMTP_SSL`` and ``socket.create_connection`` to port 25, 465 or 587 raise ``RealMailAttempt`` (a
``BaseException``, so that no ``except Exception`` of the outbox swallows it), and the block fails at its end if one was
tried anyway. ``use_smtp`` (the contract tests' ``FakeServer``) is no real server and stays allowed.
"""

from __future__ import annotations

import smtplib
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from . import outbox, send
from .errors import MailError
from .model import Letter, MailSettings, Store


@dataclass
class Caught:
    """The letters of one ``catch_mail``: ``sent`` at once, ``queued`` into the outbox, ``letters`` both in order,
    ``refused`` those ``fail`` turned away."""

    sent: list[Letter] = field(default_factory=list)
    queued: list[Letter] = field(default_factory=list)
    letters: list[Letter] = field(default_factory=list)
    refused: list[Letter] = field(default_factory=list)
    #: Since E44: every try to reach a real mail server while the block ran (each also raised ``RealMailAttempt``).
    attempts: list[str] = field(default_factory=list)


#: The ports of a mail server.
MAIL_PORTS = frozenset({25, 465, 587})


class RealMailAttempt(BaseException):
    """A test tried to reach a real mail server while ``catch_mail`` was on."""


@contextmanager
def catch_mail(*, fail: bool = False) -> Iterator[Caught]:
    """Catch every letter the app sends at once or queues, until the block ends (then both are as before)."""
    caught = Caught()
    real_deliver, real_queue = send.deliver, outbox.queue

    def deliver(settings: MailSettings, letter: Letter) -> None:
        if not getattr(settings, "configured", True):
            raise MailError("mail_off", "No mail server is set up.")
        if fail:
            caught.refused.append(letter)
            raise MailError("mail_unreachable", "The mail server cannot be reached.")
        caught.sent.append(letter)
        caught.letters.append(letter)

    def queue(store: Store, letter: Letter) -> int | str:
        caught.queued.append(letter)
        caught.letters.append(letter)
        return real_queue(store, letter)

    real_smtp, real_smtp_ssl, real_connect = smtplib.SMTP, smtplib.SMTP_SSL, socket.create_connection

    def refuse(what: str) -> RealMailAttempt:
        caught.attempts.append(what)
        return RealMailAttempt(f"a test tried to reach a real mail server ({what}) while catch_mail was on")

    def smtp(*args: Any, **kwargs: Any) -> Any:
        raise refuse(f"smtplib.SMTP{args[:2]!r}")

    def smtp_ssl(*args: Any, **kwargs: Any) -> Any:
        raise refuse(f"smtplib.SMTP_SSL{args[:2]!r}")

    def connect(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
        port = address[1] if isinstance(address, tuple) and len(address) > 1 else None
        if port in MAIL_PORTS:
            raise refuse(f"socket.create_connection({address!r})")
        return real_connect(address, *args, **kwargs)

    send.deliver = deliver  # type: ignore[assignment]
    outbox.queue = queue  # type: ignore[assignment]
    smtplib.SMTP = smtp  # type: ignore[assignment,misc]
    smtplib.SMTP_SSL = smtp_ssl  # type: ignore[assignment,misc]
    socket.create_connection = connect  # type: ignore[assignment]
    try:
        yield caught
    finally:
        send.deliver = real_deliver  # type: ignore[assignment]
        outbox.queue = real_queue  # type: ignore[assignment]
        smtplib.SMTP = real_smtp  # type: ignore[misc]
        smtplib.SMTP_SSL = real_smtp_ssl  # type: ignore[misc]
        socket.create_connection = real_connect
    if caught.attempts:
        raise AssertionError(f"a test tried to reach a real mail server: {caught.attempts}")
