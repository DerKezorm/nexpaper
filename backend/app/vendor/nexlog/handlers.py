"""Writing: the file that rolls over and the console, both through the same filters (one line, blacked out, request
and account in brackets), and the four levels applied to the loggers.

Four levels, switchable at run time:

``quiet``     only warnings and errors
``normal``    what happened: saves, renames, imports, sign-ins, backups, plus warnings and errors
``detailed``  plus the way there: every request, every file a watcher saw, index steps
``trace``     plus what the libraries say. Only on request.

What logs SQL with its values, the addresses httpx calls and uvicorn's access lines stays at WARNING at every level.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from logging.handlers import RotatingFileHandler

from . import context, files
from .config import current
from .masking import one_line, redact

#: Libraries that follow the level of the libraries (they would otherwise log every request).
NOISY_LOGGERS = ("httpx", "httpcore", "watchfiles", "multipart", "uvicorn.access")
#: Never finer than WARNING, at any level: SQL with its values (note texts, password hashes), the addresses httpx calls
#: (a webhook's token sits in its path), uvicorn's access lines (paths with invitation and share tokens).
SILENT_LOGGERS = ("sqlalchemy.engine", "sqlalchemy.pool", "httpx", "httpcore", "uvicorn.access")

MODES: dict[str, dict[str, int]] = {
    "quiet": {"app": logging.WARNING, "root": logging.WARNING, "libs": logging.WARNING},
    "normal": {"app": logging.INFO, "root": logging.INFO, "libs": logging.WARNING},
    "detailed": {"app": logging.DEBUG, "root": logging.INFO, "libs": logging.INFO},
    "trace": {"app": logging.DEBUG, "root": logging.DEBUG, "libs": logging.DEBUG},
}
DEEP_MODES = ("detailed", "trace")
DEFAULT_MODE = "normal"

_MARK = "_nexlog"
_handler: RotatingFileHandler | None = None
_console: logging.StreamHandler | None = None
_mode = DEFAULT_MODE


def app_logger() -> logging.Logger:
    return logging.getLogger(current().app_name)


def _guard_traceback(text: str) -> str:
    """A line of a traceback that looks like a record (an exception's words may hold one) is moved in by two spaces,
    so it stays part of its record."""
    return "\n".join(
        f"  {line}" if files.LINE_PATTERN.match(line) else line for line in text.split("\n")
    )


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.ctx = context.ctx_text()
        # Formatted once and then fixed, so the second handler sees the finished text.
        if not getattr(record, "_nexlog_done", False):
            record.msg = redact(one_line(record.getMessage()))
            record.args = ()
            if record.exc_info and not record.exc_text:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            if record.exc_text:
                record.exc_text = _guard_traceback(redact(record.exc_text))
            if record.stack_info:
                record.stack_info = _guard_traceback(redact(record.stack_info))
            record._nexlog_done = True  # type: ignore[attr-defined]
        return True


class _NoDuplicateAsgiTraceback(logging.Filter):
    """uvicorn repeats a crash the app's middleware already logged with its request."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().strip() != "Exception in ASGI application"


#: What uvicorn says for every live connection: "connection open", "connection closed" and
#: '... "WebSocket /api/notes/.../live" [accepted]'. Noise on "normal"; a detail of the deep modes.
_CONNECTION_LINES = re.compile(r'^(connection (open|closed)|.*"WebSocket [^"]*" (\[accepted\]|403|\d{3}).*)$')


class _QuietConnections(logging.Filter):
    """uvicorn's lines about each live connection count as DEBUG: kept only while a deep mode is on."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno > logging.INFO or not _CONNECTION_LINES.match(record.getMessage()):
            return True
        record.levelno, record.levelname = logging.DEBUG, "DEBUG"
        return _mode in DEEP_MODES


def _formatter() -> logging.Formatter:
    formatter = logging.Formatter(files.LOG_FORMAT, files.DATE_FORMAT)
    if current().utc:
        formatter.converter = time.gmtime
    return formatter


def setup(mode: str | None = None) -> None:
    """At start-up, after ``configure``: the file and the console on the root logger and on ``uvicorn.error`` (which
    does not propagate; without it no crash of the server reaches the file). Calling it again replaces the module's
    handlers and keeps everybody else's. ``mode``: the level until the stored one is applied (default: the
    environment's, else normal)."""
    global _handler, _console
    from .modes import env_mode

    root = logging.getLogger()
    uvicorn_error = logging.getLogger("uvicorn.error")
    for logger_ in (root, uvicorn_error):
        for existing in list(logger_.handlers):
            if getattr(existing, _MARK, False):
                logger_.removeHandler(existing)
                existing.close()

    formatter = _formatter()
    handler = RotatingFileHandler(
        files.log_file(), maxBytes=files.MAX_BYTES_NORMAL, backupCount=files.BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(formatter)
    handler.addFilter(_ContextFilter())
    setattr(handler, _MARK, True)
    root.addHandler(handler)
    _handler = handler

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    console.addFilter(_ContextFilter())
    setattr(console, _MARK, True)
    root.addHandler(console)
    _console = console

    uvicorn_error.addHandler(handler)
    if not any(isinstance(f, _NoDuplicateAsgiTraceback) for f in uvicorn_error.filters):
        uvicorn_error.addFilter(_NoDuplicateAsgiTraceback())
    if not any(isinstance(f, _QuietConnections) for f in uvicorn_error.filters):
        uvicorn_error.addFilter(_QuietConnections())

    apply_mode(mode or env_mode() or DEFAULT_MODE)
    files.purge_old()


def shutdown() -> None:
    """Take the module's handlers off again (tests, and an app that stops)."""
    global _handler, _console
    for logger_ in (logging.getLogger(), logging.getLogger("uvicorn.error")):
        for existing in list(logger_.handlers):
            if getattr(existing, _MARK, False):
                logger_.removeHandler(existing)
                existing.close()
    _handler = _console = None


def apply_mode(mode: str) -> None:
    """Set the loggers to a level at once (not stored; ``set_mode`` stores)."""
    global _mode
    levels = MODES.get(mode)
    if levels is None:
        mode, levels = DEFAULT_MODE, MODES[DEFAULT_MODE]
    config = current()
    _mode = mode
    logging.getLogger().setLevel(levels["root"])
    app_logger().setLevel(levels["app"])
    for name in (*NOISY_LOGGERS, *config.noisy_loggers):
        logging.getLogger(name).setLevel(levels["libs"])
    for name in (*SILENT_LOGGERS, *config.silent_loggers):
        logging.getLogger(name).setLevel(logging.WARNING)
    if _handler is not None:
        _handler.maxBytes = files.MAX_BYTES_DEEP if mode in DEEP_MODES else files.MAX_BYTES_NORMAL
    if _console is not None:
        # Never finer than INFO on the console: the details belong in the file.
        _console.setLevel(max(levels["app"], logging.INFO))


def current_mode() -> str:
    return _mode


def file_handler() -> RotatingFileHandler | None:
    return _handler


def clear() -> None:
    """Every line goes: the older files deleted, the current one emptied; then one line says the operator did it
    (WARNING, so it stands in the file at every level, with the account in brackets)."""
    for path in files.rotated_files():
        try:
            path.unlink()
        except OSError:
            pass
    if _handler is not None:
        _handler.acquire()
        try:
            if _handler.stream:
                _handler.stream.close()
            files.log_file().write_text("", encoding="utf-8")
            _handler.stream = _handler._open()
        finally:
            _handler.release()
    elif files.log_file().is_file():
        files.log_file().write_text("", encoding="utf-8")
    app_logger().warning("Log cleared by operator")
