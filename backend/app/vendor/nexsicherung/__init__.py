"""nexsicherung: storage and backups of every nex app, the same everywhere.

Vendored unchanged into ``backend/app/vendor/nexsicherung/``; a test in the app compares the files with the checksums
in ``MANIFEST.json``, so a change is made in the module's source, never in the copy.

The module runs the backups (names, list, schedule, keeping, upload, download, check, the copy before a restore,
staging and the start); **what** goes into a backup and **how** it comes back is the app's, through its ``AppHooks``.

- ``config``: ``configure(AppConfig(app_name, data_dir, version, hooks, ...))`` at start-up;
- ``hooks``: ``AppHooks``, what the app writes (``pack``, ``describe``, ``check``, ``unpack``/``apply`` or
  ``restore_now``, ``load_schedule``/``save_schedule`` …);
- ``archives``: ``create``, ``entries``, ``remove``, ``prune``, ``receive``;
- ``restore``: ``check``, ``stage_restore``, ``apply_pending``, ``report_failed_restore``, ``restore_now``;
- ``plan``: ``run_forever`` (a task in the lifespan), ``run_job``, ``summary``, ``checked``, ``save``;
- ``space``: the card "Speicher" (``overview``), where a folder lies (``locate``, ``warn_at_start``);
- ``tools``: helpers for the app's hooks (database copy and check, hashes, members within limits);
- ``routes`` (FastAPI, imported on its own): ``router(...)`` and ``legacy_router(...)``.

Only the standard library is needed, and FastAPI for ``routes``.
"""

from __future__ import annotations

from . import archives, plan, restore, space, state, tools
from .config import NOW, RESTART, AppConfig, configure, current
from .errors import CODES, BackupError
from .hooks import AppHooks
from .model import (
    AUTOMATIC_KINDS,
    DAILY,
    EVERY,
    KINDS,
    MANUAL,
    MONTHLY,
    OFF,
    SCHEDULED,
    UPDATE,
    WEEKLY,
    Brief,
    Checked,
    Described,
    Entry,
    Part,
    Schedule,
    Where,
)

__version__ = "1.0.0"

__all__ = [
    "AUTOMATIC_KINDS",
    "CODES",
    "DAILY",
    "EVERY",
    "KINDS",
    "MANUAL",
    "MONTHLY",
    "NOW",
    "OFF",
    "RESTART",
    "SCHEDULED",
    "UPDATE",
    "WEEKLY",
    "AppConfig",
    "AppHooks",
    "BackupError",
    "Brief",
    "Checked",
    "Described",
    "Entry",
    "Part",
    "Schedule",
    "Where",
    "__version__",
    "archives",
    "configure",
    "current",
    "plan",
    "restore",
    "space",
    "state",
    "tools",
]
