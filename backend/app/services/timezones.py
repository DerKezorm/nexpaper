"""The time zone of a person: what the browser reported, the server's own until then. Used where the server writes
a time for somebody (a notice of a new sign-in) and where "today" depends on where they are (the deadlines of the
dashboard, the documents whose keeping time is over: ``keeping.today_of``). Nothing that decides who may see or
change a document reads it."""

from __future__ import annotations

from datetime import datetime, tzinfo
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from ..models import Account


@lru_cache(maxsize=1)
def time_zones() -> frozenset[str]:
    return frozenset(available_timezones())


def valid_time_zone(name: Any) -> bool:
    return isinstance(name, str) and 0 < len(name) <= 64 and name in time_zones()


def zone_of(account: Account) -> tzinfo:
    """The person's time zone as the browser reported it; the server's own until then."""
    profile = account.profile if isinstance(account.profile, dict) else {}
    name = profile.get("timezone")
    if valid_time_zone(name):
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    zone = datetime.now().astimezone().tzinfo
    assert zone is not None
    return zone
