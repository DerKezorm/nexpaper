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
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

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

    send.deliver = deliver  # type: ignore[assignment]
    outbox.queue = queue  # type: ignore[assignment]
    try:
        yield caught
    finally:
        send.deliver = real_deliver  # type: ignore[assignment]
        outbox.queue = real_queue  # type: ignore[assignment]
