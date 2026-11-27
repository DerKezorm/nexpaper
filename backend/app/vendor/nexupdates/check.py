"""Whether a newer version is out: one question to one address, at most once a day, only while the operator wants it.

From nexnotes' ``services/updates.py`` (the eight apps had it nearly alike), with what the plan adds: the background
look once a day with one word to the operators' bell per new version (U3), the switch asked at setup (U1), and nothing
by itself while it is off. The answer is foreign input: at most ``MAX_ANSWER`` bytes, only a tag of the form
``v1.2.3`` counts, compared as numbers. No proxy or credentials from the environment, no cookies, a neutral name
(``nex-update-check``, without the server's version). A failed question keeps the last good answer and is asked again
after an hour; the log says so at most once a day.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from .config import current

#: Once a day at most; GitHub allows 60 questions an hour without signing in.
INTERVAL = timedelta(hours=24)
#: After a failed question, asked again sooner than a day.
RETRY = timedelta(hours=1)
#: The page should not wait on GitHub.
TIMEOUT = httpx.Timeout(6.0, connect=4.0)
#: GitHub's answer is a few KB; more is not a release.
MAX_ANSWER = 256 * 1024
#: The name the question goes out with: no version of the server, nothing of the app.
USER_AGENT = "nex-update-check"
HEADERS = {"accept": "application/vnd.github+json", "user-agent": USER_AGENT}
_PATTERN = re.compile(r"v?(\d{1,6})\.(\d{1,6})\.(\d{1,6})")


@dataclass(frozen=True)
class State:
    current: str
    latest: str | None = None
    newer: bool = False
    checked_at: datetime | None = None


_known: State | None = None
_lock = threading.Lock()
#: The day the log last said that a question did not get through.
_told_failure: date | None = None


def parse(text: object) -> tuple[int, int, int] | None:
    """``"v1.2.3"`` -> ``(1, 2, 3)``; anything else (also ``"v1.2.3-rc1"``, a trailing line break) -> None."""
    found = _PATTERN.fullmatch(text.strip()) if isinstance(text, str) else None
    if not found:
        return None
    return int(found.group(1)), int(found.group(2)), int(found.group(3))


def is_newer(latest: str, than: str) -> bool:
    """Numbers, not text: ``"0.10.0" > "0.9.0"`` is false as text, and that shows exactly once, at the tenth minor."""
    a, b = parse(latest), parse(than)
    return a is not None and b is not None and a > b


def _note_failure(problem: BaseException) -> None:
    global _told_failure
    today = datetime.now(UTC).date()
    if _told_failure != today:
        _told_failure = today
        current().logger.info("The update check did not get through: %s", type(problem).__name__)


def ask() -> str | None:
    """The newest release's tag, only when it reads as a version (``v1.2.3``): it is shown, put into an address and
    into the bell's words. Read up to ``MAX_ANSWER``; no proxy or credentials from the environment, no cookies."""
    config = current()
    try:
        with (
            httpx.Client(timeout=TIMEOUT, trust_env=False, headers=HEADERS, follow_redirects=False) as client,
            client.stream("GET", config.url()) as answer,
        ):
            answer.raise_for_status()
            body = bytearray()
            for chunk in answer.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_ANSWER:
                    raise ValueError("answer too large")
        found: Any = json.loads(bytes(body))
        tag = found.get("tag_name") if isinstance(found, dict) else None
        return tag.strip() if isinstance(tag, str) and parse(tag) is not None else None
    except Exception as problem:  # noqa: BLE001
        # Every exception, not a list of names: in Nexview httpx.InvalidURL slipped past httpx.HTTPError and took a
        # whole page with it. A side matter that fails must break nothing.
        _note_failure(problem)
        return None


def state(*, on: bool, force: bool = False) -> State:
    """The last known state; asked afresh when it is a day old (an hour after a failure) and the check is on, or
    when forced (the operator's button). Off and not forced: never a question."""
    global _known
    config = current()
    running = config.running()
    if not on and not force:
        return _known if _known is not None else State(current=running)
    now = datetime.now(UTC)
    with _lock:
        wait = INTERVAL if _known is not None and _known.latest else RETRY
        fresh = _known is not None and _known.checked_at is not None and now - _known.checked_at < wait
        if fresh and not force:
            return _known  # type: ignore[return-value]
        latest = ask()
        if latest is None and _known is not None and _known.latest:
            # One failed question (GitHub down, a proxy in the way) keeps what the last good one found.
            _known = replace(_known, checked_at=now, current=running, newer=is_newer(_known.latest, running))
            return _known
        _known = State(current=running, latest=latest, newer=bool(latest) and is_newer(latest or "", running),
                       checked_at=now)
        return _known


def forget() -> None:
    """For tests, and when the check is switched off."""
    global _known, _told_failure
    _known = None
    _told_failure = None


# --- The switch ----------------------------------------------------------------------------------------------------


def switch_on() -> bool:
    """The daily check as stored; while nothing is stored (an installation from before, never switched) the default,
    on (U1: running installations keep what they had)."""
    stored = current().read_switch()
    return current().default_on if stored is None else bool(stored)


def set_switch(on: bool) -> bool:
    config = current()
    config.write_switch(on)
    if not on:
        forget()
    config.logger.info("Daily update check switched %s", "on" if on else "off")
    return on


def at_setup(on: bool) -> bool:
    """U1: the answer to "Nach neuen Versionen sehen?" at the setup of a new installation (ticked by default). Only
    where nothing is stored yet: an installation from before keeps its value."""
    if current().read_switch() is None:
        return set_switch(bool(on))
    return switch_on()


# --- Telling the operators (U3) -----------------------------------------------------------------------------------


def devices_want() -> bool:
    """U24 (0.1.3): a device of an operator wants to hear of new versions (``devices_want``), and the app can tell it
    (``on_devices``). A failure of the app's question counts as no."""
    config = current()
    if config.devices_want is None or config.on_devices is None:
        return False
    try:
        return bool(config.devices_want())
    except Exception:  # a side matter never ends the look
        config.logger.exception("Asking for the devices failed")
        return False


def look_once() -> str | None:
    """The background's look: only while the switch is on and somebody is there to tell, the bell or (U24) a device of
    an operator that wants it (U19 otherwise), through ``state`` (so at most once a day); tells them once about a
    version newer than the running one and newer than any they were told about. Returns the version told about, else
    None."""
    config = current()
    if not switch_on():
        return None
    bell = config.on_newer is not None
    devices = devices_want()
    if not bell and not devices:
        # U19: without a bell and without a device that wants it, the background has no one to tell, so it does not
        # ask; the operator's page does.
        return None
    known = state(on=True)
    latest = known.latest
    if not latest or not known.newer:
        return None
    told = config.read_told()
    if told and not is_newer(latest, told):
        return None
    config.write_told(latest)
    if config.on_newer is not None:
        config.on_newer(latest)
    if devices and config.on_devices is not None:
        config.on_devices(latest)
    config.logger.info("A newer version is out version=%s", latest)
    return latest


async def run_forever(stop: Any, every: float = 3600.0) -> None:
    """Every hour a look (``look_once``); the network is asked at most once a day, and never while the switch is
    off. ``stop`` is an ``asyncio.Event``."""
    import asyncio

    while not stop.is_set():
        try:
            await asyncio.to_thread(look_once)
        except Exception:  # noqa: BLE001 - a side matter never ends the loop
            current().logger.exception("The update look failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=every)
        except TimeoutError:
            continue
