"""The brakes (K10): one request per person at a time, a few per minute and per day, a few on the server at once, and a
day's limit for the whole server. In memory, like in every app before: a restart forgets them, which is fine for a
brake; only the server's day count lives in the store (a paid service must not get a second day after a restart)."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from .errors import AiRefused

#: The clock of the brakes; the tests put their own in.
ticks: Callable[[], float] = time.monotonic


def today() -> str:
    return datetime.now(UTC).date().isoformat()


class Pace:
    """Requests per minute and per day of one key (an account, or the operator's lists)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._minute: dict[Hashable, deque[float]] = {}
        self._day: dict[Hashable, tuple[str, int]] = {}

    def take(self, who: Hashable, per_minute: int, per_day: int, day: str) -> None:
        moment = ticks()
        with self._lock:
            seen = self._minute.setdefault(who, deque())
            while seen and moment - seen[0] > 60:
                seen.popleft()
            if len(seen) >= per_minute:
                raise AiRefused("ai_too_often", retry_after=60)
            stored_day, count = self._day.get(who, (day, 0))
            if stored_day != day:
                count = 0
            if per_day and count >= per_day:
                raise AiRefused("ai_day_used")
            seen.append(moment)
            self._day[who] = (day, count + 1)

    def forget(self) -> None:
        with self._lock:
            self._minute.clear()
            self._day.clear()


class Brake:
    def __init__(self) -> None:
        self.pace = Pace()
        self._writing: set[Hashable] = set()
        self._lock = threading.Lock()
        self._busy = 0

    @contextmanager
    def one_at_a_time(self, who: Hashable, at_once: int) -> Iterator[None]:
        """One request per person at a time (a double click makes one), and at most ``at_once`` on the server."""
        with self._lock:
            if who in self._writing:
                raise AiRefused("ai_busy")
            if self._busy >= at_once:
                raise AiRefused("ai_server_busy")
            self._writing.add(who)
            self._busy += 1
        try:
            yield
        finally:
            with self._lock:
                self._writing.discard(who)
                self._busy -= 1

    def forget(self) -> None:
        self.pace.forget()
        with self._lock:
            self._writing.clear()
            self._busy = 0


BRAKE = Brake()
