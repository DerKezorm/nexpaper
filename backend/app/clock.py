"""The server's clock, in one place so that tests can set it (``monkeypatch.setattr(clock, "now", ...)``)."""

from __future__ import annotations

import time
from datetime import UTC, datetime


def now() -> datetime:
    """The current moment, in UTC."""
    return datetime.now(UTC)


def monotonic() -> float:
    """Seconds on a clock that never goes back, for waits in memory (the sign-in brake). Tests set it too."""
    return time.monotonic()
