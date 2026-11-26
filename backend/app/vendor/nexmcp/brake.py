"""The brakes, kept in the memory of the process (as every app had them): requests per key and minute, calls of an
expensive tool per key and minute, wrong keys per sender, registrations of programs per sender and hour and for the
whole server per minute. A restart forgets them; that is accepted (it was so in all four apps)."""

from __future__ import annotations

import hashlib
import ipaddress
import threading
import time
from collections import defaultdict, deque

WINDOW = 60.0
#: Wrong keys are counted for this long.
WRONG_WINDOW = 15 * 60.0
HOUR = 3600.0


class Brake:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[str, deque[float]] = defaultdict(deque)

    def forget(self) -> None:
        with self._lock:
            self._seen.clear()

    def _count(self, key: str, window: float, now: float) -> deque[float]:
        seen = self._seen[key]
        while seen and now - seen[0] >= window:
            seen.popleft()
        return seen

    def take(self, key: str, limit: int, window: float = WINDOW, now: float | None = None) -> bool:
        """True while ``key`` stays under ``limit`` in the window; counts this one."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            seen = self._count(key, window, moment)
            if len(seen) >= limit:
                return False
            seen.append(moment)
            return True

    def wait_seconds(self, key: str, free: int, now: float | None = None) -> int:
        """How long ``key`` waits after more than ``free`` failures in ``WRONG_WINDOW``: until the oldest of them is
        out of the window; 0 while within ``free``."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            seen = self._count(key, WRONG_WINDOW, moment)
            if len(seen) < free:
                return 0
            return max(1, int(WRONG_WINDOW - (moment - seen[0])) + 1)

    def failed(self, key: str, now: float | None = None) -> None:
        moment = time.monotonic() if now is None else now
        with self._lock:
            self._count(key, WRONG_WINDOW, moment).append(moment)


def wrong_key_pot(address: str, token: str | None) -> str:
    """Since 1.1.2 (M-18): where the wrong keys of a request count. With a known sender per sender (``sender_of``);
    where the app does not know it (``sender`` gives ``""``, nexmail behind a proxy without ``NEXMAIL_CLIENT_IP``) per
    key brought, so that a stranger's wrong keys never make a right key of someone else wait."""
    if address:
        return "mcp:" + sender_of(address)
    return "mcp:key:" + hashlib.sha256((token or "").encode("utf-8")).hexdigest()[:24]


def sender_of(address: str) -> str:
    """The sender as the brakes count it: an IPv4 address, or the /64 of an IPv6 address (one machine has many)."""
    try:
        found = ipaddress.ip_address(address)
    except ValueError:
        return address[:64]
    if found.version == 6:
        return str(ipaddress.ip_network(f"{found}/64", strict=False))
    return str(found)


#: One brake per process, shared by the routes (tests call ``BRAKE.forget()``).
BRAKE = Brake()
