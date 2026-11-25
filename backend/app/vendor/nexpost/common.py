"""Time and the log."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from . import config


def log() -> logging.Logger:
    return logging.getLogger(config.current().log_name)


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
