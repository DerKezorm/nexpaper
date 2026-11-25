"""The files: ``<log_dir>/<app>.log`` and the older ones the rollover left (``<app>.log.1`` … ``.3``), every line in
the form all eight apps already wrote::

    2026-11-25 14:05:00 WARNING  nexnotes.api [a1b2c3 u:kim] | Slow request: GET /api/notes -> 200 in 3200ms

So every file an app wrote before the module is read as it is; nothing is converted. The time is the server's local
clock, or UTC where the app always wrote UTC (nexmail, ``AppConfig.utc``). Lines that do not match (the lines of a
traceback, nexmail's raw line breaks) belong to the record before them."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import current

BACKUP_COUNT = 3
RETENTION_DAYS = 14
MAX_BYTES_NORMAL = 5 * 1024 * 1024
MAX_BYTES_DEEP = 25 * 1024 * 1024
#: The largest download; older files that do not fit are named in its first line.
DOWNLOAD_LIMIT = 20 * 1024 * 1024

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(ctx)s] | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LEVEL_ORDER = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

LINE_PATTERN = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+"
    r"(?P<logger>\S+)\s"
    r"(?:\[(?P<ctx>[^\]]*)\]\s)?"
    r"\|\s(?P<message>.*)$"
)


@dataclass(frozen=True)
class LogLine:
    time: str
    level: str
    logger: str
    message: str
    request_id: str | None = None
    user: str | None = None
    #: ``time`` as a moment with its offset, for the reader's own clock.
    at: str | None = None


def log_dir() -> Path:
    config = current()
    directory = config.folder()
    directory.mkdir(parents=True, exist_ok=True)
    if config.tighten is not None:
        config.tighten(directory)
    return directory


def log_file() -> Path:
    return log_dir() / f"{current().app_name}.log"


def rotated_files() -> list[Path]:
    """The older files, ``.1`` (the newest of them) first."""
    name = current().app_name
    found = [path for path in log_dir().glob(f"{name}.log.*") if path.is_file()]

    def number(path: Path) -> int:
        suffix = path.name.rsplit(".", 1)[-1]
        return int(suffix) if suffix.isdigit() else 10_000

    return sorted(found, key=lambda path: (number(path), path.name))


def moment_of(written: str) -> str | None:
    """The time of a line with its offset: the server's local clock, or UTC where the app writes UTC."""
    try:
        parsed = datetime.strptime(written, DATE_FORMAT)
    except ValueError:
        return None
    if current().utc:
        return parsed.replace(tzinfo=UTC).isoformat()
    return parsed.astimezone().isoformat()


def parse_line(line: str) -> LogLine | None:
    match = LINE_PATTERN.match(line.rstrip("\r\n"))
    if match is None:
        return None
    request_id = user = None
    for part in (match["ctx"] or "").split():
        if part.startswith("u:"):
            user = part[2:] or None
        elif part != "-":
            request_id = part
    return LogLine(
        time=match["time"],
        level=match["level"],
        logger=match["logger"],
        message=match["message"],
        request_id=request_id,
        user=user,
        at=moment_of(match["time"]),
    )


def _records(path: Path) -> list[str]:
    """The records of one file, oldest first; a line that does not start a record joins the one before."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return []
    merged: list[str] = []
    for raw in lines:
        if LINE_PATTERN.match(raw.rstrip("\r\n")) or not merged:
            merged.append(raw)
        else:
            merged[-1] += raw
    return merged


def _newest_first() -> Iterator[LogLine]:
    """Every record of the current file and then of the older ones, newest first."""
    for path in (log_file(), *rotated_files()):
        if not path.is_file():
            continue
        for raw in reversed(_records(path)):
            head, _, rest = raw.partition("\n")
            parsed = parse_line(head)
            if parsed is None:
                continue
            if rest.strip():
                # A traceback (or nexmail's raw line breaks): the message with its lines.
                body = raw.split("| ", 1)[1].rstrip("\r\n") if "| " in raw else raw.rstrip("\r\n")
                parsed = LogLine(
                    parsed.time, parsed.level, parsed.logger, body.replace("\r\n", "\n"), parsed.request_id,
                    parsed.user, parsed.at,
                )
            yield parsed


def read(limit: int = 200, level: str | None = None, search: str | None = None, offset: int = 0) -> list[LogLine]:
    """The newest lines first, from the ``offset``-th that fits on (the next page), the older files included.
    ``level`` means this level and higher; ``search`` looks in the message, the source, the request and the account,
    regardless of case."""
    minimum = LEVEL_ORDER.index(level) if level in LEVEL_ORDER else 0
    needle = (search or "").strip().casefold()
    result: list[LogLine] = []
    for line in _newest_first():
        if LEVEL_ORDER.index(line.level) < minimum:
            continue
        if needle:
            haystack = f"{line.message} {line.logger} {line.request_id or ''} {line.user or ''}".casefold()
            if needle not in haystack:
                continue
        if offset > 0:
            offset -= 1
            continue
        result.append(line)
        if len(result) >= limit:
            break
    return result


def purge_old(now: float | None = None) -> int:
    """Delete older files past the retention (14 days)."""
    limit = (now or time.time()) - RETENTION_DAYS * 86400
    removed = 0
    for path in rotated_files():
        try:
            if path.stat().st_mtime < limit:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def download_name(now: datetime | None = None) -> str:
    return f"{current().app_name}-log-{(now or datetime.now(UTC)).strftime('%Y-%m-%d')}.txt"


def download_text() -> str:
    """Every file as one text, oldest first, each under ``===== <name> =====``; files that would pass the limit are
    named in the first line instead. The newest files are chosen first, so the current one is always there."""
    chosen: list[tuple[Path, str]] = []
    missing: list[str] = []
    total = 0
    for path in (log_file(), *rotated_files()):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        if total + len(content) > DOWNLOAD_LIMIT and chosen:
            missing.append(path.name)
            continue
        chosen.append((path, content))
        total += len(content)
    parts = [f"===== {path.name} =====\n{content}" for path, content in reversed(chosen)]
    if missing:
        parts.insert(0, f"===== left out (too large): {', '.join(reversed(missing))} =====\n")
    return "\n".join(parts)
