"""The sign-in brake in memory, and the sender's address behind a proxy.

Every app runs one worker, so the brake lives in its memory (a restart forgets it; the lock of an account after ten
wrong passwords is in the database, ``Store.is_locked``). An attempt is checked and counted in one step under one lock
(``claim``): many attempts at once cannot all pass before the first failure is counted.

Counts as ``login.attempt_key`` gives them, two per attempt: the sender (30 free) and the account or what was typed
(5 free). After the free ones each further failure waits longer: 5 seconds, doubled each time, at most 15 minutes. A
count lives one hour from its first failure (also when failures keep coming), unless a wait still runs.

A right attempt (``succeeded``) takes back what it counted: the account's count starts anew, and the sender's loses
the one failure ``claim`` counted for it, so that a family behind one address never fills the sender's count with
right passwords. A browser that knows the account (``sessions.known_mark``) counts in a pot of its own
(``browser=<its mark>``, 5 free), neither at the sender nor at the account: a stranger who types the name of the
owner never brakes the owner's own browser, also not from behind the same router (decided 25.11.2026; until 0.3.2
such a browser counted at the sender, which ``known_browser=True`` without a mark still does for older callers).

Every other door counts through the same brake (since 0.3.4), each with a key ``door_key(<door>, <what>)``:
``confirm:<account>`` a password typed to confirm a change (one's own address, username, factor, or an operator's
action on another account: counted at the operator), ``code:<account>`` a code of the second factor at sign-in,
``mail:<account>`` a mail a person makes the module write (a forgotten password, the link for a new address; these are
never taken back), ``forgot:<sender>`` the requests to "Forgot your password?" from one sender. The module claims them
itself (``common.guarded``); an app with a route of its own uses the same keys.

At most 50 000 counts are kept; when full, the ones whose hour is over go first, then senders and typed text before
accounts, the least recently failed first.

The sender's address: behind proxies the app trusts (``<APP>_TRUSTED_PROXIES``, CIDR) the rightmost hop of
``X-Forwarded-For`` that is not one of them; IPv6 counts per /64. Without trusted proxies the peer of the connection.
"""

from __future__ import annotations

import hashlib
import ipaddress
import threading
import time
from dataclasses import dataclass, field

FREE = {
    "sender": 30, "account": 5, "typed": 5, "browser": 5, "confirm": 5, "code": 5, "mail": 5, "forgot": 10,
}
FREE_OTHER = 5
FIRST_WAIT = 5.0
LONGEST_WAIT = 15 * 60.0
FORGET_AFTER = 3600.0
MAX_COUNTS = 50_000
SENDER = "sender:"
BROWSER = "browser:"

#: The doors besides the sign-in (since 0.3.4); ``door_key`` makes their keys.
DOOR_CONFIRM = "confirm"
DOOR_CODE = "code"
DOOR_MAIL = "mail"
DOOR_FORGOT = "forgot"
DOORS = (DOOR_CONFIRM, DOOR_CODE, DOOR_MAIL, DOOR_FORGOT)


def door_key(door: str, what: object) -> str:
    """The count of one door: ``<door>:<account id>``, or ``forgot:<sender>`` (an empty sender counts as ``none``)."""
    if door not in DOORS:
        raise ValueError(f"unknown door {door!r}")
    return f"{door}:{str(what).strip() or 'none'}"


@dataclass
class _Count:
    failures: int = 0
    start: float = 0.0
    last: float = 0.0
    blocked_until: float = 0.0

    def over(self, moment: float) -> bool:
        """The hour of this count is over and no wait runs."""
        return moment - self.start > FORGET_AFTER and moment >= self.blocked_until


def browser_key(mark: str) -> str:
    """The pot of one known browser: its mark (``sessions.known_mark``), hashed. A pot key passes unchanged."""
    if mark.startswith(BROWSER):
        return mark
    return BROWSER + hashlib.sha256(mark.encode("utf-8")).hexdigest()[:32]


def _kept(keys: tuple[str, ...] | list[str], known_browser: bool, browser: str = "") -> list[str]:
    if browser:
        return [browser_key(browser)]
    return [key for key in keys if key.startswith(SENDER)] if known_browser else list(keys)


@dataclass
class Brake:
    """One per process (``BRAKE``)."""

    counts: dict[str, _Count] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def _free(self, key: str) -> int:
        return FREE.get(key.partition(":")[0], FREE_OTHER)

    def _sweep(self, moment: float) -> None:
        if len(self.counts) < MAX_COUNTS:
            return
        for key in [key for key, count in self.counts.items() if count.over(moment)]:
            self.counts.pop(key, None)
        if len(self.counts) < MAX_COUNTS:
            return
        # Accounts are kept longest: a sender with many names must not push the count of an account out.
        order = sorted(self.counts, key=lambda key: (key.startswith("account:"), self.counts[key].last))
        for key in order[: len(self.counts) - MAX_COUNTS + 1]:
            self.counts.pop(key, None)

    def _wait_locked(self, keys: list[str], moment: float) -> float:
        waits = [
            count.blocked_until - moment
            for key in keys
            if (count := self.counts.get(key)) is not None and not count.over(moment)
        ]
        return max([0.0, *waits])

    def _failed_locked(self, keys: list[str], moment: float) -> float:
        self._sweep(moment)
        longest = 0.0
        for key in keys:
            count = self.counts.get(key)
            if count is None or count.over(moment):
                count = self.counts[key] = _Count(start=moment)
            count.failures += 1
            count.last = moment
            over = count.failures - self._free(key)
            if over > 0:
                wait = min(FIRST_WAIT * 2 ** (over - 1), LONGEST_WAIT)
                count.blocked_until = max(count.blocked_until, moment + wait)
                longest = max(longest, wait)
        return longest

    def wait(
        self,
        keys: tuple[str, ...] | list[str],
        now: float | None = None,
        *,
        known_browser: bool = False,
        browser: str = "",
    ) -> float:
        """Seconds to wait before the next attempt may run (0: it may), without counting."""
        moment = time.monotonic() if now is None else now
        with self.lock:
            return self._wait_locked(_kept(keys, known_browser, browser), moment)

    def failed(
        self,
        keys: tuple[str, ...] | list[str],
        now: float | None = None,
        *,
        known_browser: bool = False,
        browser: str = "",
    ) -> float:
        """Count a failure at every key; the longest wait that follows."""
        moment = time.monotonic() if now is None else now
        with self.lock:
            return self._failed_locked(_kept(keys, known_browser, browser), moment)

    def claim(
        self,
        keys: tuple[str, ...] | list[str],
        now: float | None = None,
        *,
        known_browser: bool = False,
        browser: str = "",
    ) -> float:
        """Check and count in one step: the wait when the attempt must not run (nothing counted then), else 0 and
        the attempt counted as a failure until ``succeeded``. ``browser``: the mark of a browser that knows the
        account (``sessions.known_mark``); the attempt then counts in that browser's own pot only."""
        moment = time.monotonic() if now is None else now
        kept = _kept(keys, known_browser, browser)
        with self.lock:
            waiting = self._wait_locked(kept, moment)
            if waiting > 0:
                return waiting
            self._failed_locked(kept, moment)
            return 0.0

    def succeeded(self, keys: tuple[str, ...] | list[str], *, browser: str = "") -> None:
        """The attempt was right: the account's count starts anew (and the browser's pot, with ``browser``); the
        sender's loses the failure ``claim`` counted."""
        with self.lock:
            for key in [*keys, *([browser_key(browser)] if browser else [])]:
                if not key.startswith(SENDER):
                    self.counts.pop(key, None)
                    continue
                count = self.counts.get(key)
                if count is None:
                    continue
                count.failures = max(0, count.failures - 1)
                if count.failures <= self._free(key):
                    count.blocked_until = 0.0
                if count.failures == 0:
                    self.counts.pop(key, None)

    def forget(self) -> None:
        with self.lock:
            self.counts.clear()


BRAKE = Brake()


def _networks(trusted: str | list[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    entries = trusted.split(",") if isinstance(trusted, str) else trusted
    found = []
    for entry in entries:
        text = entry.strip()
        if text:
            try:
                found.append(ipaddress.ip_network(text, strict=False))
            except ValueError:
                continue
    return found


def _counted(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is None:
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address.ipv4_mapped or address) if isinstance(address, ipaddress.IPv6Address) else str(address)


def client_address(peer: str, forwarded_for: str, trusted: str | list[str]) -> str:
    """The sender as the brake counts it. A hop that is no address counts as itself (``hop:<text>``, cut short), never
    as the proxy before it: otherwise one sender with a broken header would brake everybody behind that proxy."""
    networks = _networks(trusted)
    try:
        current = ipaddress.ip_address((peer or "").strip())
    except ValueError:
        return peer or "unknown"
    if not networks or not any(current in network for network in networks):
        return _counted(current)
    for hop in reversed([part.strip() for part in (forwarded_for or "").split(",") if part.strip()]):
        try:
            address = ipaddress.ip_address(hop)
        except ValueError:
            return "hop:" + "".join(char for char in hop if char.isprintable())[:64]
        if not any(address in network for network in networks):
            return _counted(address)
        current = address
    return _counted(current)
