"""Brakes on actions, per person and minute: a stolen session or a stuck script must not keep the server busy. Far above
what a person does by hand.

Kept in memory, per process: a restart forgets them, which is fine for a brake. The blocks that take uploads and
searches add their own kinds here.
"""

from __future__ import annotations

import threading
from collections import deque

from .. import clock
from ..errors import error

#: Per person and minute.
LIMITS = {
    #: Signing a device up for Web Push (its push service is looked up), a probe (it goes out to every device).
    "push": 20,
    "push_test": 10,
    #: Searches, from a browser, a device or a program: two a second for a minute, enough for a search field that asks
    #: while somebody types (with a short pause), far below what measuring the time of answers needs.
    "search": 120,
    #: The page tools: each run copies a whole document; a person works through a stack by hand far below this.
    "pagetools": 30,
}
#: The code and the sentence of the answer.
CODES = {
    "push": ("push_too_often", "Too many at once. Wait a minute."),
    "push_test": ("push_too_often", "Too many at once. Wait a minute."),
    "search": ("search_too_often", "Too many searches at once. Wait a moment."),
    "pagetools": ("tools_too_often", "Too many changes to pages at once. Wait a moment."),
}

_lock = threading.Lock()
_seen: dict[tuple[str, int], deque[float]] = {}


def take(kind: str, account_id: int) -> None:
    """One more of ``kind`` for this person, or ``429`` with ``Retry-After`` when the minute is full."""
    moment = clock.monotonic()
    with _lock:
        seen = _seen.setdefault((kind, account_id), deque())
        while seen and moment - seen[0] > 60:
            seen.popleft()
        if len(seen) >= LIMITS[kind]:
            code, text = CODES[kind]
            exc = error(code, text, 429)
            # Until the oldest of the minute drops out.
            exc.headers = {"Retry-After": str(max(1, int(60 - (moment - seen[0])) + 1))}
            raise exc
        seen.append(moment)


#: Brakes per hour (``take_hourly``): what each costs a run of the worker and is never done often by hand.
HOURLY_CODES = {
    #: Opening a protected PDF with a password (P1), per document and per person: a wrong guess is tried in the
    #: worker, and passwords are not to be guessed through the server.
    "pdf_password_document": ("pdf_password_too_often", "Too many tries for this PDF. Wait an hour."),
    "pdf_password_person": ("pdf_password_too_often", "Too many tries for this PDF. Wait an hour."),
}
_hourly: dict[tuple[str, int], deque[float]] = {}


def take_hourly(*brakes: tuple[str, int, int]) -> None:
    """One more of each ``(kind, key, limit)`` within the last hour, all or none: ``429`` with ``Retry-After`` when one
    of them is full (then none is taken)."""
    moment = clock.monotonic()
    with _lock:
        seen = []
        for kind, key, limit in brakes:
            found = _hourly.setdefault((kind, int(key)), deque())
            while found and moment - found[0] > 3600:
                found.popleft()
            if len(found) >= limit:
                code, text = HOURLY_CODES[kind]
                exc = error(code, text, 429)
                exc.headers = {"Retry-After": str(max(1, int(3600 - (moment - found[0])) + 1))}
                raise exc
            seen.append(found)
        for found in seen:
            found.append(moment)


def forget() -> None:
    """For the tests."""
    with _lock:
        _seen.clear()
        _hourly.clear()
