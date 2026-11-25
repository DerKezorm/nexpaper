"""The schedule: "Automatisch" Aus / Jede Nacht / Jede Woche / Jeden Monat, at a wall clock time, keeping so many
copies.

* **When:** a scheduled copy is due once the latest slot (today's time, or yesterday's while today's is still ahead)
  has passed and no scheduled copy was made since it; for "weekly" the last one must be at least six days and 18
  hours older than the slot; for "monthly" the slot is the time on the first of the month. A server that was off at
  the time makes the copy at its next look (the same day or a day late), then returns to the time. The first
  scheduled copy is made at the first look.
* **A failed copy** is noted (the page shows it, the operators are told once) and tried again an hour later at the
  earliest, not every minute.
* **Keeping:** after each scheduled copy, and when the number is lowered, the automatic copies beyond it go.
* The look runs every minute (``run_forever``), first a minute after the start.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, time, timedelta, tzinfo
from typing import Any

from . import archives, state, tools
from .config import current
from .errors import BackupError
from .model import DAILY, EVERY, KEEP_MAX, KEEP_MIN, MONTHLY, OFF, SCHEDULED, TIME, WEEKLY, Schedule

INTERVAL_SECONDS = 60
RETRY_AFTER = timedelta(hours=1)
WEEK_TOLERANCE = timedelta(days=6, hours=18)


def checked(every: Any, at: Any, keep: Any) -> Schedule:
    """A schedule from what the page sent, or a refusal with a fixed code."""
    if every not in EVERY:
        raise BackupError("schedule_invalid", "The schedule is off, daily, weekly or monthly.")
    if not isinstance(at, str) or not TIME.fullmatch(at):
        raise BackupError("time_invalid", "Enter a time such as 03:00.")
    if isinstance(keep, bool) or not isinstance(keep, int) or not KEEP_MIN <= keep <= KEEP_MAX:
        raise BackupError("keep_invalid", f"Keep between {KEEP_MIN} and {KEEP_MAX} backups.")
    return Schedule(every, at, keep)


def load() -> Schedule:
    """The app's schedule; a value it cannot have is read as its nearest safe one (off, 03:00, 7)."""
    found = current().hooks.load_schedule()
    every = found.every if found.every in EVERY else OFF
    at = found.time if isinstance(found.time, str) and TIME.fullmatch(found.time) else "03:00"
    keep = found.keep if isinstance(found.keep, int) and KEEP_MIN <= found.keep <= KEEP_MAX else 7
    return Schedule(every, at, keep)


def save(schedule: Schedule) -> Schedule:
    """Store the schedule through the app and drop what the new number no longer keeps."""
    current().hooks.save_schedule(schedule)
    archives.prune(schedule.keep)
    return schedule


def _zone() -> tzinfo | None:
    return current().zone()


def latest_slot(at: str, now: datetime, zone: tzinfo | None) -> datetime:
    """The latest moment at ``at`` (``HH:MM``) in ``zone`` (None: the server's own) that is not after ``now``."""
    hour, minute = (int(part) for part in at.split(":"))
    local = now.astimezone(zone) if zone is not None else now.astimezone()
    for days_back in (0, 1, 2):
        day = (local - timedelta(days=days_back)).date()
        naive = datetime.combine(day, time(hour, minute))
        slot = naive.replace(tzinfo=zone) if zone is not None else naive.astimezone()
        if slot <= now:
            return slot
    return now  # pragma: no cover - two days back is always earlier


def latest_month_slot(at: str, now: datetime, zone: tzinfo | None) -> datetime:
    """The latest first of a month at ``at`` in ``zone`` that is not after ``now``."""
    hour, minute = (int(part) for part in at.split(":"))
    local = now.astimezone(zone) if zone is not None else now.astimezone()
    year, month = local.year, local.month
    for _ in range(2):
        naive = datetime(year, month, 1, hour, minute)
        slot = naive.replace(tzinfo=zone) if zone is not None else naive.astimezone()
        if slot <= now:
            return slot
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return now  # pragma: no cover - the month before is always earlier


def due(schedule: Schedule, last: datetime | None, now: datetime, zone: tzinfo | None = None,
        failed_at: datetime | None = None) -> bool:
    """Whether a scheduled copy is due at ``now``; ``last`` is when the newest scheduled copy was made, ``failed_at``
    when the last scheduled attempt failed."""
    if schedule.every not in (DAILY, WEEKLY, MONTHLY):
        return False
    if failed_at is not None and now - failed_at < RETRY_AFTER:
        return False
    if last is None:
        return True
    if schedule.every == MONTHLY:
        return last < latest_month_slot(schedule.time, now, zone)
    slot = latest_slot(schedule.time, now, zone)
    if schedule.every == DAILY:
        return last < slot
    return slot - last >= WEEK_TOLERANCE


def _moment(text: Any) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def last_scheduled() -> datetime | None:
    for entry in archives.entries():
        if entry.readable and entry.kind == SCHEDULED and not entry.uploaded:
            return _moment(entry.created)
    return None


def _tell(event: str, details: dict[str, Any]) -> None:
    try:
        current().hooks.tell(event, details)
    except Exception:
        current().logger.exception("Telling the operators failed event=%s", event)


def run_job(now: datetime | None = None) -> bool:
    """One look: make a scheduled copy when one is due, then keep only the newest. Returns whether one was made."""
    config = current()
    archives.tidy_leftovers()
    schedule = load()
    moment = now or datetime.now(UTC)
    remembered = state.read()
    failed_at = _moment((remembered.get("scheduled_failure") or {}).get("at"))
    if not due(schedule, last_scheduled(), moment, _zone(), failed_at):
        return False
    try:
        archives.create(kind=SCHEDULED, wait=False)
    except BackupError as exc:
        if exc.code == "backup_running":
            return False
        details = {"at": tools.now_iso(), "reason": exc.code}
        first = not remembered.get("scheduled_failure")
        state.update(scheduled_failure=details)
        if first:
            _tell("backup_failed", details)
        config.logger.warning("The scheduled backup failed: %s", exc.code)
        return False
    state.update(scheduled_failure=None)
    archives.prune(schedule.keep)
    return True


async def run_forever(stop: asyncio.Event, *, interval: float = INTERVAL_SECONDS) -> None:
    """The look every ``interval`` seconds until ``stop`` is set (a task in the app's lifespan)."""
    while not stop.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        try:
            await asyncio.to_thread(run_job)
        except Exception:
            current().logger.exception("Backup job failed")


def summary() -> dict[str, Any]:
    """What the card "Sicherung" shows above the list: the schedule, the zone of its time, the last copy, a failure,
    whether a copy is under way, a restore that failed at the start."""
    found = archives.entries()
    schedule = load()
    remembered = state.read()
    zone = _zone()
    name = getattr(zone, "key", None) or (datetime.now().astimezone().tzname() if zone is None else str(zone))
    last = next((entry for entry in found if entry.readable), None)
    failure = remembered.get("failure") or remembered.get("scheduled_failure")
    return {
        "schedule": {"every": schedule.every, "time": schedule.time, "keep": schedule.keep},
        "zone": name,
        "last": {"created": last.created, "size": last.size, "kind": last.kind} if last else None,
        "count": len(found),
        "kept": sum(1 for entry in found if entry.readable and entry.kind in ("scheduled", "update")
                    and not entry.uploaded),
        "failure": failure,
        "running": archives.running(),
        "restore_failure": remembered.get("restore_failure"),
        "restored": remembered.get("restored"),
        "restore": current().restore,
        "download_password": current().download_password,
    }
