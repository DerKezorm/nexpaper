"""The level the operator chose, stored by the app, and its end.

``detailed`` and ``trace`` switch themselves off (after an hour on the page; 30, 60, 120 or 480 minutes over the
API): the files are a ring, and a forgotten deep level would overwrite exactly the lines one wanted to keep. The
environment variable (``NEXNOTES_LOG_LEVEL``) overrides the stored level, the emergency exit for "the app does not
even start".

The app stores the level where it always did (``attach_store``): nexnotes and most apps ``log_mode`` and
``log_mode_until`` in their settings, nexmail ``protokoll_stufe`` and ``protokoll_stufe_bis`` with German names. The
module understands both, so a level stored before the module stays in force with its end."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from . import files, handlers
from .config import current
from .handlers import DEEP_MODES, DEFAULT_MODE, MODES

#: How long a deep level may run; it always ends.
ALLOWED_MINUTES = (30, 60, 120, 480)
#: What the page sends with a deep level ("Ausführlich (1 Stunde)").
PAGE_MINUTES = 60
#: Other names for the levels: the environment's usual words and nexmail's stored German names.
ALIASES = {
    "warning": "quiet",
    "warn": "quiet",
    "info": "normal",
    "debug": "detailed",
    "leise": "quiet",
    "ausfuehrlich": "detailed",
    "ausführlich": "detailed",
    "alles": "trace",
}


@dataclass(frozen=True)
class ModeState:
    mode: str
    until: str | None
    fixed_by_env: bool


_store_read: Callable[[], tuple[Any, Any]] | None = None
_store_write: Callable[[str, datetime | None], None] | None = None


def normalize_mode(value: Any) -> str | None:
    """A level by its name or an alias, else None."""
    text = str(value or "").strip().lower()
    if text in MODES:
        return text
    return ALIASES.get(text)


def normalize_until(value: Any) -> datetime | None:
    """The stored end as a moment in UTC: a ``datetime`` (without zone: UTC), an ISO text, ``""`` or None."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def env_mode() -> str | None:
    """The level the environment fixes, or None."""
    return normalize_mode(current().environment())


def attach_store(read: Callable[[], tuple[Any, Any]], write: Callable[[str, datetime | None], None]) -> None:
    """``read()`` -> (mode, until) as the app stored them (any of the forms ``normalize_*`` reads); ``write(mode,
    until)`` stores the module's English name and a moment in UTC (or None). Set once the database exists."""
    global _store_read, _store_write
    _store_read, _store_write = read, write


def detach_store() -> None:
    global _store_read, _store_write
    _store_read = _store_write = None


def _stored() -> tuple[str, datetime | None]:
    if _store_read is None:
        return DEFAULT_MODE, None
    raw_mode, raw_until = _store_read()
    mode = normalize_mode(raw_mode) or DEFAULT_MODE
    until = normalize_until(raw_until)
    if mode in DEEP_MODES and until is None and str(raw_until or "").strip():
        # An end that cannot be read counts as past (nexmail did so): a deep level never stays on by mistake.
        until = datetime.min.replace(tzinfo=UTC)
    return mode, until


def _store(mode: str, until: datetime | None) -> None:
    if _store_write is not None:
        _store_write(mode, until)


def _now() -> datetime:
    return datetime.now(UTC)


def _log() -> logging.Logger:
    return handlers.app_logger()


def apply_stored_mode() -> None:
    """Take over the stored level, after the database exists (and after ``attach_store``)."""
    forced = env_mode()
    if forced:
        handlers.apply_mode(forced)
        _log().info("Logging started mode=%s source=%s", forced, current().variable)
        return
    mode, until = _stored()
    if mode in DEEP_MODES and (until is None or until <= _now()):
        # A deep level ends: past its time, or stored without an end (it never runs for good).
        _store(DEFAULT_MODE, None)
        mode, until = DEFAULT_MODE, None
    handlers.apply_mode(mode)
    until_text = until.isoformat(timespec="seconds") if until else "-"
    _log().info("Logging started mode=%s until=%s file=%s", mode, until_text, files.log_file())


def set_mode(mode: str, minutes: int = 0) -> ModeState:
    """Store and apply a level. A deep level runs ``minutes`` (one of ``ALLOWED_MINUTES``; 0: an hour), the others
    for good."""
    chosen = normalize_mode(mode)
    if chosen is None:
        raise ValueError(f"unknown log mode: {mode}")
    until = None
    if chosen in DEEP_MODES:
        until = _now() + timedelta(minutes=minutes or PAGE_MINUTES)
    _store(chosen, until)
    before = handlers.current_mode()
    handlers.apply_mode(chosen)
    _log().info(
        "Log mode changed from=%s to=%s until=%s", before, chosen, until.isoformat(timespec="seconds") if until else "-"
    )
    return state()


def state() -> ModeState:
    """The level in force, its end, and whether the environment fixes it. A deep level past its end ends here."""
    forced = env_mode()
    if forced:
        return ModeState(mode=forced, until=None, fixed_by_env=True)
    mode, until = _stored()
    if _expire(mode, until):
        until = None
    shown = handlers.current_mode()
    if shown not in DEEP_MODES:
        until = None
    return ModeState(mode=shown, until=until.isoformat(timespec="seconds") if until else None, fixed_by_env=False)


def enforce_expiry() -> bool:
    """End a deep level past its time; True if it ended."""
    if env_mode():
        return False
    mode, until = _stored()
    return _expire(mode, until)


def _expire(mode: str, until: datetime | None) -> bool:
    if mode not in DEEP_MODES or (until is not None and until > _now()):
        return False
    _store(DEFAULT_MODE, None)
    handlers.apply_mode(DEFAULT_MODE)
    _log().info("Log mode %s expired, back to %s", mode, DEFAULT_MODE)
    return True


async def run_forever(stop: asyncio.Event, every: float = 60) -> None:
    """The watchdog, as a task of the app: ends a deep level after its time (checked every minute), deletes older
    files past the retention once a day."""
    last_purge = time.time()
    while not stop.is_set():
        try:
            enforce_expiry()
            if time.time() - last_purge > 86400:
                files.purge_old()
                last_purge = time.time()
        except Exception:  # noqa: BLE001 (the watchdog must outlive any failure; it is logged)
            _log().exception("Log watchdog failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=every)
        except TimeoutError:
            continue
