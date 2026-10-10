"""Logging.

nexpaper writes its log to ``data/logs/nexpaper.log``. The file rolls over at a size limit, three older files
are kept, and files older than 14 days are deleted.

Messages are English on purpose: log lines end up in bug reports and web searches. ``tests/test_log_language.py``
keeps that rule.

⚠️ What never goes into the log, at any level: anything stored in a document (its text, notes, titles, senders, tags),
search terms, passwords, tokens, keys, session identifiers. Sizes, counts, accounts and results do.
``tests/test_log_secrets.py`` scans the code for the obvious mistakes.

Four levels, switchable at runtime
----------------------------------
``quiet``     only warnings and errors
``normal``    what happened: sign-ins, accounts, settings, backups, plus warnings and errors
``detailed``  plus the way there: every request
``trace``     plus what the libraries say. Only on request.

``detailed`` and ``trace`` switch themselves off: the file is a ring buffer, and a forgotten trace level would
overwrite exactly the lines one wanted to keep. ``NEXPAPER_LOG_LEVEL`` overrides the stored level, the emergency
exit for "the app does not even start".
"""

from __future__ import annotations

import logging
import re
import sys
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .. import private
from ..config import get_settings

BACKUP_COUNT = 3
RETENTION_DAYS = 14
MAX_BYTES_NORMAL = 5 * 1024 * 1024
MAX_BYTES_DEEP = 25 * 1024 * 1024

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(ctx)s] | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Libraries that would otherwise log every request.
NOISY_LOGGERS = ("httpx", "httpcore", "watchfiles", "multipart", "uvicorn.access")
#: Never finer than WARNING, at any level: SQLAlchemy writes every statement with its values from INFO on (document
#: texts, password and key hashes, sealed seeds), httpx the addresses it calls, uvicorn's access lines the paths with
#: invitation tokens (which our own request line masks), Pillow every Exif value of a photo from DEBUG on (a
#: description, a place, a device).
SILENT_LOGGERS = ("sqlalchemy.engine", "sqlalchemy.pool", "httpx", "httpcore", "uvicorn.access", "PIL")

MODES: dict[str, dict[str, int]] = {
    "quiet": {"app": logging.WARNING, "root": logging.WARNING, "libs": logging.WARNING},
    "normal": {"app": logging.INFO, "root": logging.INFO, "libs": logging.WARNING},
    "detailed": {"app": logging.DEBUG, "root": logging.INFO, "libs": logging.INFO},
    "trace": {"app": logging.DEBUG, "root": logging.DEBUG, "libs": logging.DEBUG},
}
DEEP_MODES = ("detailed", "trace")
DEFAULT_MODE = "normal"
#: How long detailed and trace may run; they always end (review before 1.0.0: "0" kept them on for good, writing
#: request paths and outside addresses for as long as nobody looked).
ALLOWED_MINUTES = (30, 60, 120, 480)
LEVEL_ORDER = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

LINE_PATTERN = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+"
    r"(?P<logger>\S+)\s"
    r"(?:\[(?P<ctx>[^\]]*)\]\s)?"
    r"\|\s(?P<message>.*)$"
)

# The request context is a *mutable* dict in the ContextVar: FastAPI runs sync dependencies in a thread pool
# with a copy of the context, and a value set there would be gone afterwards. The dict is shared.
_context: ContextVar[dict[str, str | None] | None] = ContextVar("nexpaper_log_context", default=None)


def bind_request(request_id: str) -> object:
    return _context.set({"rid": request_id, "actor": None})


def unbind_request(token: object) -> None:
    _context.reset(token)  # type: ignore[arg-type]


def set_actor(name: str | None) -> None:
    data = _context.get()
    if data is not None:
        data["actor"] = name


def current_request_id() -> str | None:
    data = _context.get()
    return data.get("rid") if data else None


def _one_line(text: str) -> str:
    """A log record is one line. A line break inside a message would let whoever controls a value (a request path, a
    file name) write a second, genuine-looking record: ``/api/x%0d%0a<date> INFO nexpaper.auth [-] | ...``."""
    return text.replace("\r", "\\r").replace("\n", "\\n")


#: A device token or an API key that ended up in a line (pasted into an address by mistake): never in the log.
_FEED_KEY = re.compile(r"(npd_|npk_|lnk_|lnx_)[A-Za-z0-9_-]+")
#: Tokens that stand in an address without a prefix of their own: invitations, links to set a new password and links
#: that confirm a mail address (the page ``/mail/<token>`` and the route ``/api/v1/email/confirm/<token>``), and the
#: links to a document (the page ``/l/<token>`` and the route ``/api/v1/l/<token>``; the token itself starts with
#: ``lnk_`` and is masked wherever it stands, ``_FEED_KEY``), and the links that confirm a sender address (the page
#: ``/absender/<token>`` and the route ``/api/v1/mail-senders/confirm/<token>``), and the links to an export (the page
#: ``/x/<token>`` and the route ``/api/v1/x/<token>``; the token starts with ``lnx_``).
_PATH_TOKEN = re.compile(
    r"(/(?:api/(?:v1/)?)?(?:invite|reset|mail|email/confirm|l|absender|mail-senders/confirm|x)/)[A-Za-z0-9_-]{12,}")
_QUERY_TOKEN = re.compile(r"([?&](?:access_token|token|key|code|state|code_challenge|code_verifier)=)[^&\s\"']+")


def redact(text: str) -> str:
    text = _FEED_KEY.sub(r"\1…", text)
    text = _PATH_TOKEN.sub(r"\1…", text)
    return _QUERY_TOKEN.sub(r"\1…", text)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        data = _context.get() or {}
        parts = [value for value in (data.get("rid"),) if value]
        actor = data.get("actor")
        if actor:
            parts.append(f"u:{actor}")
        record.ctx = _one_line(" ".join(parts)) if parts else "-"
        # Formatted once and then fixed, so the second handler sees the finished text. Tracebacks are added by the
        # formatter afterwards and keep their lines; ``read`` joins them to their record.
        if not getattr(record, "_one_line", False):
            record.msg = redact(_one_line(record.getMessage()))
            record.args = ()
            record._one_line = True  # type: ignore[attr-defined]
        # The text of an exception and of a stack goes through ``redact`` too (``logger.exception`` puts the words of
        # the exception after the message). The formatter keeps the finished text on the record (``exc_text``), so it is
        # made here, once, before any handler formats it. The lines of a traceback stay lines.
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


class _NoDuplicateAsgiTraceback(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage() != "Exception in ASGI application"


@dataclass(frozen=True)
class LogLine:
    time: str
    level: str
    logger: str
    message: str
    request_id: str | None = None
    user: str | None = None


@dataclass(frozen=True)
class ModeState:
    mode: str
    until: str | None
    fixed_by_env: bool


def log_dir() -> Path:
    directory = get_settings().data_dir / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    private.tighten(directory)
    return directory


def log_file() -> Path:
    return log_dir() / "nexpaper.log"


def rotated_files() -> list[Path]:
    return sorted(p for p in log_dir().glob("nexpaper.log.*") if p.is_file())


_handler: RotatingFileHandler | None = None
_console: logging.StreamHandler | None = None
_mode = DEFAULT_MODE
#: Reads and writes the stored mode; set by ``main`` once the database exists.
_store_read: Callable[[], tuple[str, datetime | None]] | None = None
_store_write: Callable[[str, datetime | None], None] | None = None


def env_mode() -> str | None:
    value = (get_settings().log_level or "").strip().lower()
    if value in MODES:
        return value
    return {"warning": "quiet", "warn": "quiet", "info": "normal", "debug": "detailed"}.get(value)


def setup() -> None:
    global _handler, _console
    root = logging.getLogger()
    uvicorn_error = logging.getLogger("uvicorn.error")
    for logger_ in (root, uvicorn_error):
        for existing in list(logger_.handlers):
            if getattr(existing, "_nexpaper", False):
                logger_.removeHandler(existing)

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    handler = RotatingFileHandler(log_file(), maxBytes=MAX_BYTES_NORMAL, backupCount=BACKUP_COUNT, encoding="utf-8")
    handler.setFormatter(formatter)
    handler.addFilter(_ContextFilter())
    handler._nexpaper = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    _handler = handler

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    console.addFilter(_ContextFilter())
    console._nexpaper = True  # type: ignore[attr-defined]
    root.addHandler(console)
    _console = console

    # uvicorn's own logger does not propagate; without this no crash of the server reaches the file.
    uvicorn_error.addHandler(handler)
    if not any(isinstance(f, _NoDuplicateAsgiTraceback) for f in uvicorn_error.filters):
        uvicorn_error.addFilter(_NoDuplicateAsgiTraceback())

    apply_mode(env_mode() or DEFAULT_MODE)
    purge_old()


def apply_mode(mode: str) -> None:
    global _mode
    levels = MODES.get(mode)
    if levels is None:
        mode, levels = DEFAULT_MODE, MODES[DEFAULT_MODE]
    _mode = mode
    logging.getLogger().setLevel(levels["root"])
    logging.getLogger("nexpaper").setLevel(levels["app"])
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(levels["libs"])
    for name in SILENT_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    if _handler is not None:
        _handler.maxBytes = MAX_BYTES_DEEP if mode in DEEP_MODES else MAX_BYTES_NORMAL
    if _console is not None:
        # Never finer than INFO on the console: the details belong in the file.
        _console.setLevel(max(levels["app"], logging.INFO))


def current_mode() -> str:
    return _mode


def attach_store(
    read: Callable[[], tuple[str, datetime | None]], write: Callable[[str, datetime | None], None]
) -> None:
    global _store_read, _store_write
    _store_read, _store_write = read, write


def _stored() -> tuple[str, datetime | None]:
    if _store_read is None:
        return DEFAULT_MODE, None
    mode, until = _store_read()
    return (mode if mode in MODES else DEFAULT_MODE), until


def _store(mode: str, until: datetime | None) -> None:
    if _store_write is not None:
        _store_write(mode, until)


def _now() -> datetime:
    return datetime.now(UTC)


def apply_stored_mode() -> None:
    """Take over the stored level, after ``init_db``."""
    forced = env_mode()
    if forced:
        apply_mode(forced)
        logging.getLogger("nexpaper").info("Logging started mode=%s source=NEXPAPER_LOG_LEVEL", forced)
        return
    mode, until = _stored()
    if mode in DEEP_MODES and until is not None and until <= _now():
        _store(DEFAULT_MODE, None)
        mode, until = DEFAULT_MODE, None
    apply_mode(mode)
    until_text = until.isoformat(timespec="seconds") if until else "-"
    logging.getLogger("nexpaper").info("Logging started mode=%s until=%s file=%s", mode, until_text, log_file())


def set_mode(mode: str, minutes: int = 0) -> ModeState:
    if mode not in MODES:
        raise ValueError(f"unknown log mode: {mode}")
    until = _now() + timedelta(minutes=minutes) if mode in DEEP_MODES and minutes else None
    _store(mode, until)
    before = _mode
    apply_mode(mode)
    logging.getLogger("nexpaper").info(
        "Log mode changed from=%s to=%s until=%s", before, mode, until.isoformat(timespec="seconds") if until else "-"
    )
    return state()


def state() -> ModeState:
    forced = env_mode()
    if forced:
        return ModeState(mode=forced, until=None, fixed_by_env=True)
    mode, until = _stored()
    if _expire(mode, until):
        until = None
    return ModeState(mode=_mode, until=until.isoformat(timespec="seconds") if until else None, fixed_by_env=False)


def enforce_expiry() -> bool:
    if env_mode():
        return False
    mode, until = _stored()
    return _expire(mode, until)


def _expire(mode: str, until: datetime | None) -> bool:
    if mode not in DEEP_MODES or until is None or until > _now():
        return False
    _store(DEFAULT_MODE, None)
    apply_mode(DEFAULT_MODE)
    logging.getLogger("nexpaper").info("Log mode %s expired, back to %s", mode, DEFAULT_MODE)
    return True


def purge_old(now: float | None = None) -> int:
    """Delete rotated files older than the retention."""
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


def parse_line(line: str) -> LogLine | None:
    match = LINE_PATTERN.match(line.rstrip("\n"))
    if match is None:
        return None
    request_id = user = None
    for part in (match["ctx"] or "").split():
        if part.startswith("u:"):
            user = part[2:]
        elif part != "-":
            request_id = part
    return LogLine(
        time=match["time"],
        level=match["level"],
        logger=match["logger"],
        message=match["message"],
        request_id=request_id,
        user=user,
    )


def read(limit: int = 200, level: str | None = None, search: str | None = None) -> list[LogLine]:
    """The newest lines first. ``level`` means this level and higher."""
    path = log_file()
    if not path.is_file():
        return []
    minimum = LEVEL_ORDER.index(level) if level in LEVEL_ORDER else 0
    needle = (search or "").strip().lower()
    result: list[LogLine] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    # Continuation lines (stack traces) belong to the line before them.
    merged: list[str] = []
    for raw in lines:
        if LINE_PATTERN.match(raw) or not merged:
            merged.append(raw)
        else:
            merged[-1] += raw
    for raw in reversed(merged):
        parsed = parse_line(raw.split("\n", 1)[0])
        if parsed is None:
            continue
        if raw.count("\n") > 1:
            parsed = LogLine(
                parsed.time, parsed.level, parsed.logger, raw.split("|", 1)[1].strip(), parsed.request_id, parsed.user
            )
        if LEVEL_ORDER.index(parsed.level) < minimum:
            continue
        haystack = f"{parsed.message} {parsed.request_id or ''} {parsed.user or ''}".lower()
        if needle and needle not in haystack:
            continue
        result.append(parsed)
        if len(result) >= limit:
            break
    return result


def clear() -> None:
    for path in rotated_files():
        try:
            path.unlink()
        except OSError:
            pass
    if _handler is not None:
        _handler.acquire()
        try:
            if _handler.stream:
                _handler.stream.close()
            log_file().write_text("", encoding="utf-8")
            _handler.stream = _handler._open()
        finally:
            _handler.release()
    elif log_file().is_file():
        log_file().write_text("", encoding="utf-8")
    logging.getLogger("nexpaper").info("Log cleared by operator")


async def run_forever(stop) -> None:
    """Watchdog: takes a deep level back after its time, purges old files once a day."""
    import asyncio

    last_purge = time.time()
    while not stop.is_set():
        try:
            enforce_expiry()
            if time.time() - last_purge > 86400:
                purge_old()
                last_purge = time.time()
        except Exception:
            logging.getLogger("nexpaper").exception("Log watchdog failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
        except TimeoutError:
            continue
