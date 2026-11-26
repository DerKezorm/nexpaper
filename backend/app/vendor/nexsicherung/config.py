"""The app's settings for the module: its name, its folders, its version, its hooks. Set once at start-up with
``configure``; the module's functions read them with ``current``."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import tzinfo
from pathlib import Path

from .hooks import AppHooks

RESTART = "restart"
NOW = "now"

#: The largest upload the module takes, unless the app says otherwise (64 GiB, as nexnotes, nextasks, nexpaper).
UPLOAD_MAX = 64 * 1024**3


@dataclass
class AppConfig:
    """``app_name`` names the archives (``<app>-YYYY-MM-DD-HHMMSS.zip``) and the logger. ``data_dir`` holds
    ``folder`` (the backups, default ``data_dir/backups``). ``version`` is the running version: an archive of a newer
    one is never restored. ``restore`` is ``"restart"`` (staged, swapped at the next start; every app but nexmail) or
    ``"now"`` (nexmail). ``legacy_names``: patterns of names the app used before the module (nexmail
    ``nexmail-YYYYMMDD-HHMMSS.db``); listed, checked, restored and deleted like the module's own. ``parts`` maps a part
    of the card "Speicher" to the names at the top of ``data_dir`` that belong to it; the rest counts as ``other``.
    ``time_zone``: the zone of the schedule's wall clock time (a ``tzinfo`` or a callable giving one); None is the
    server's own. ``download_password``: see the field."""

    app_name: str
    data_dir: Path
    version: str
    hooks: AppHooks
    folder: Path | None = None
    database_path: Path | None = None
    restore: str = RESTART
    legacy_names: tuple[re.Pattern[str], ...] = ()
    parts: dict[str, tuple[str, ...]] = field(default_factory=dict)
    upload_max: int = UPLOAD_MAX
    time_zone: tzinfo | Callable[[], tzinfo] | None = None
    logger_name: str = ""
    #: A download asks for a password of its own and the app's ``download`` hook encrypts with it (nexmail's slim,
    #: encrypted archive); every other app hands out the backup itself.
    download_password: bool = False
    #: Since E38: the keys of the app's own questions in the dialog "Wiederherstellen" (nexmail ``address``: whether the
    #: public address from the archive applies); the answers go to the app's ``unpack``/``restore_now`` as ``options``
    #: and lie in the staged folder for ``apply`` (``restore.staged_options``). Others are refused.
    restore_options: tuple[str, ...] = ()

    @property
    def backups(self) -> Path:
        return self.folder if self.folder is not None else self.data_dir / "backups"

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(self.logger_name or f"{self.app_name}.backups")

    @property
    def name_pattern(self) -> re.Pattern[str]:
        """The names the module gives: ``<app>-2026-11-25-031500.zip``, ``-2`` for a second in the same second,
        ``-upload`` for one brought in from elsewhere. The same pattern the apps used before."""
        return re.compile(rf"^{re.escape(self.app_name)}-\d{{4}}-\d{{2}}-\d{{2}}-\d{{6}}(-\d+)?(-upload)?\.zip$")

    def zone(self) -> tzinfo | None:
        given = self.time_zone
        return given() if callable(given) else given

    def database_names(self) -> tuple[str, ...]:
        if self.database_path is None:
            base = f"{self.app_name}.db"
        else:
            base = self.database_path.name
        return (base, base + "-wal", base + "-shm", base + "-journal")


_current: AppConfig | None = None


def configure(config: AppConfig) -> AppConfig:
    """Set the app's configuration (at start-up, before ``apply_pending``)."""
    global _current
    if config.restore not in (RESTART, NOW):
        raise ValueError("restore is 'restart' or 'now'")
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", config.app_name):
        raise ValueError("app_name is a short lower-case name")
    _current = config
    # What the module remembered of another configuration (another data folder in a test) is not this one's.
    from . import archives, space

    archives.forget()
    space.forget()
    return config


def current() -> AppConfig:
    if _current is None:
        raise RuntimeError("nexsicherung.configure(...) was not called")
    return _current


def reset() -> None:
    """Forget the configuration (tests)."""
    global _current
    _current = None
