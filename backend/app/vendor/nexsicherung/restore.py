"""Checking and restoring.

* **Check first:** ``check`` is the trial run (the app's ``check``) plus the module's own rules: an archive of a
  newer version of the app is never restored (``too_new``), one of an older version is, and the app's start brings it
  up to date. Nothing changes.
* **Before a restore the current state is kept** as a copy of kind ``update`` ("before restoring <name>"): the way
  back.
* **restore = "restart"** (every app but nexmail): ``stage_restore`` lays the archive out in
  ``backups/restore-pending/`` (the app's ``unpack``), writes the module's marker last, and the route ends the
  process (``restart_soon``); Docker starts it again and ``apply_pending``, called before anything opens the
  database, hands the folder to the app's ``apply``. A folder without the marker is half-written and thrown away.
  When ``apply`` fails, the folder is set aside in ``backups/restore-failed/``, the server starts with the data from
  before, the page says so and the operators are told once (``report_failed_restore`` after the start).
* **restore = "now"** (nexmail): ``restore_now`` checks, keeps the current state, and hands the archive to the
  app's ``restore_now`` while it runs.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import threading
import time
import zlib
from pathlib import Path
from typing import Any

from . import archives, state, tools
from .config import NOW, RESTART, current
from .errors import BackupError
from .model import UPDATE, Brief, Checked

MARKER = "nexsicherung-pending.json"


def check(name: str, *, viewer: Any = None, archive_password: str | None = None) -> Brief:
    """The trial run of the archive ``name``: whole or not, too new or not, what a restore would change."""
    config = current()
    path = archives.path_of(name)
    described = archives.describe(path)
    if described is None:
        return Brief(name, "", "manual", "", "", name.endswith(archives.UPLOADED), False, False, [], False, "", {}, {})
    too_new = bool(described.version) and tools.newer(described.version, config.version)
    try:
        checked = config.hooks.check(path, viewer=viewer, archive_password=archive_password)
    except zlib.error as exc:
        # A deflated member the app's check read without ``tools.DAMAGE``: damaged, never a 500.
        config.logger.info("A backup could not be inflated name=%s: %s", name, exc)
        checked = Checked(database_ok=False, files_ok=False)
    return Brief(
        name=name, created=described.created or "", kind=described.kind, note=described.note,
        version=described.version, uploaded=name.endswith(archives.UPLOADED), database_ok=checked.database_ok,
        files_ok=checked.files_ok, damaged=list(checked.damaged)[:20], too_new=too_new, blocked=checked.blocked,
        facts=dict(described.facts), details=dict(checked.details), blocked_text=checked.blocked_text,
    )


def _refuse_unless_usable(brief: Brief) -> None:
    if brief.too_new:
        raise BackupError("backup_too_new", f"the archive comes from version {brief.version}, newer than this one; "
                                            "nothing was changed")
    if brief.blocked:
        text = brief.blocked_text or "this archive cannot be restored here; nothing was changed"
        raise BackupError(brief.blocked, text, 400)
    if not brief.usable:
        raise BackupError("backup_damaged", "the archive is damaged; nothing was changed")


def pending_folder() -> Path:
    return archives.folder() / archives.PENDING


def failed_folder() -> Path:
    return archives.folder() / archives.FAILED


def stage_restore(name: str, *, viewer: Any = None, archive_password: str | None = None) -> Brief:
    """Check, keep the current state as a copy, and lay the archive out for the next start."""
    config = current()
    if config.restore != RESTART:
        raise RuntimeError("this app restores at once: restore_now")
    with archives.lock:
        brief = check(name, viewer=viewer, archive_password=archive_password)
        _refuse_unless_usable(brief)
        archives.create(kind=UPDATE, note=f"before restoring {name}")
        pending = pending_folder()
        tools.remove_tree(pending)
        tools.private_folder(pending)
        try:
            config.hooks.unpack(archives.path_of(name), pending, archive_password=archive_password)
            marker = {"name": name, "created": brief.created, "version": brief.version, "at": tools.now_iso()}
            # Last: the marker says the folder is complete.
            (pending / MARKER).write_text(json.dumps(marker), encoding="utf-8")
        except BaseException:
            tools.remove_tree(pending)
            raise
    config.logger.warning("Backup staged for the next start name=%s", name)
    return brief


def restart_soon(delay: float = 1.5) -> None:
    """End the process shortly, after the answer went out; Docker starts it again (``restart: unless-stopped``)."""

    def stop() -> None:
        time.sleep(delay)
        current().logger.info("%s stops to restore a backup", current().app_name)
        if os.name == "nt":
            os._exit(3)
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except OSError:
            os._exit(0)
        time.sleep(10)
        os._exit(0)

    threading.Thread(target=stop, name="restart-for-restore", daemon=True).start()


def apply_pending() -> bool:
    """At the start, before anything opens the database: swap in a staged restore. Returns whether one was. A failed
    one is set aside and the start goes on with the data from before (never half of both)."""
    config = current()
    try:
        # The app calls it at its start as well (restore = "now" has no apply_pending to rely on); twice is harmless.
        archives.tidy_at_start()
    except Exception:
        config.logger.exception("Tidying the backups folder at the start failed")
    try:
        config.hooks.tidy()
    except Exception:
        config.logger.exception("Tidying after an earlier restore failed")
    pending = pending_folder()
    if not pending.is_dir():
        return False
    marker_path = pending / MARKER
    if not marker_path.is_file():
        config.logger.warning("An incomplete restore was found and thrown away")
        tools.remove_tree(pending)
        return False
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        marker = {}
    try:
        config.hooks.apply(pending)
    except Exception as exc:
        config.logger.exception("Restoring the backup failed; the server starts with the data from before")
        failed = failed_folder()
        tools.remove_tree(failed)
        try:
            os.replace(pending, failed)
            (failed / "failed.json").write_text(json.dumps({"at": tools.now_iso(), "error": exc.__class__.__name__}),
                                                encoding="utf-8")
        except OSError:
            tools.remove_tree(pending)
        state.update(restore_failure={"at": tools.now_iso(), "name": str(marker.get("name", "")), "told": False})
        return False
    tools.remove_tree(pending)
    archives.forget()
    state.update(restored={"at": tools.now_iso(), "name": str(marker.get("name", ""))}, restore_failure=None)
    config.logger.warning("Backup restored name=%s", marker.get("name"))
    return True


def report_failed_restore() -> bool:
    """After the start (once the app can tell its operators): a restore that failed at the start is told, once."""
    remembered = state.read().get("restore_failure")
    if not isinstance(remembered, dict) or remembered.get("told"):
        return False
    try:
        current().hooks.tell("restore_failed", {"at": remembered.get("at"), "name": remembered.get("name")})
    except Exception:
        current().logger.exception("Telling the operators of a failed restore failed")
        return False
    state.update(restore_failure={**remembered, "told": True})
    return True


def restore_now(name: str, *, viewer: Any = None, archive_password: str | None = None) -> tuple[Brief, dict[str, Any]]:
    """For restore = "now": check, keep the current state, and put the archive's in place while the app runs."""
    config = current()
    if config.restore != NOW:
        raise RuntimeError("this app restores at the next start: stage_restore")
    with archives.lock:
        brief = check(name, viewer=viewer, archive_password=archive_password)
        _refuse_unless_usable(brief)
        archives.create(kind=UPDATE, note=f"before restoring {name}")
        result = config.hooks.restore_now(archives.path_of(name), archive_password=archive_password)
    state.update(restored={"at": tools.now_iso(), "name": name})
    config.logger.warning("Backup restored name=%s", name)
    return brief, dict(result or {})


def forget_failed() -> None:
    """The operator saw the failed restore: the folder set aside goes, the page says nothing more."""
    shutil.rmtree(failed_folder(), ignore_errors=True)
    state.update(restore_failure=None)
