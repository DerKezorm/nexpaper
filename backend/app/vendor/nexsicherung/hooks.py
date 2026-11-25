"""What the app supplies: what goes into a backup and how it comes back. The module does everything around it (names,
list, schedule, keeping, upload, download, check before restore, the copy before a restore, staging and the start).

The app writes a subclass of ``AppHooks`` and hands an instance to ``configure``. Every method marked **required**
must be written; the others have defaults. The archive's format stays the app's: ``pack`` writes it, ``describe``,
``check``, ``unpack``/``apply`` (or ``restore_now``) read it, so every backup an app made before the module stays
readable and restorable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .model import Checked, Described, Part, Schedule


class AppHooks:
    # --- What goes in ----------------------------------------------------------------------------------------------

    def pack(self, target: Path, *, kind: str, note: str, created: str) -> None:
        """**Required.** Write the whole archive into ``target`` (an empty file only the owner may read; the module
        moves it to its final name afterwards and throws it away when this raises). The app's manifest carries
        ``kind``, ``note``, ``created`` (ISO time with zone) and the app's version, so that ``describe`` reads them
        back. The database through SQLite's backup API (``tools.copy_database``), never as a file copy."""
        raise NotImplementedError("APP: pack")

    def describe(self, path: Path) -> Described:
        """**Required.** What the archive at ``path`` says of itself (its manifest). Raise
        ``BackupError("backup_invalid", …)`` when it is not an archive of this app (no manifest, no database); called
        for every listing (cached by size and time of the file) and for an upload before it joins the list."""
        raise NotImplementedError("APP: describe")

    def check(self, path: Path, *, viewer: Any = None, archive_password: str | None = None) -> Checked:
        """**Required.** The trial run: is the archive whole (database ``integrity_check``, every file against its
        size and hash, nothing unknown in it), and what would a restore change? ``viewer`` is the account asking
        (whose own things the app may name). Never changes anything. For a locked archive without
        ``archive_password`` raise ``BackupError("archive_password_needed", …)``, with a wrong one
        ``BackupError("archive_password_wrong", …)``."""
        raise NotImplementedError("APP: check")

    # --- How it comes back: at the next start (restore = "restart") ------------------------------------------------

    def unpack(self, path: Path, pending: Path, *, archive_password: str | None = None) -> None:
        """**Required for restore = "restart".** Lay the archive out in the empty folder ``pending`` (database, key,
        files), each member checked again by name and size. The module writes its marker after this returns; a
        folder without it is thrown away at the start, never applied."""
        raise NotImplementedError("APP: unpack")

    def apply(self, pending: Path) -> None:
        """**Required for restore = "restart".** At the start, before anything opens the database: swap in what
        ``unpack`` laid out (files, database, key) and do the app's own steps after a restore (end every session,
        move sync counters on, rebuild an index). **All or nothing:** when it raises, the previous state must be in
        place again; the module then sets the folder aside, starts with the previous data and tells the operators."""
        raise NotImplementedError("APP: apply")

    def tidy(self) -> None:
        """At every start, before ``apply``: remove what an earlier restore set aside (``attachments.replaced-*``)."""

    # --- How it comes back: at once (restore = "now") --------------------------------------------------------------

    def restore_now(self, path: Path, *, archive_password: str | None = None) -> dict[str, Any]:
        """**Required for restore = "now"** (nexmail): put the archive's state in place while the app runs (close the
        database, swap, open again, end every session). Returns what the page may show (flat)."""
        raise NotImplementedError("APP: restore_now")

    # --- The list ---------------------------------------------------------------------------------------------------

    def remove(self, path: Path) -> None:
        """Delete an archive (and what belongs to it, e.g. nexmail's ``.json`` beside a ``.db``)."""
        path.unlink()

    def download(self, path: Path, *, archive_password: str | None = None) -> Path:
        """The file a download hands out for the archive at ``path``; the archive itself unless the app says
        otherwise. With ``AppConfig.download_password`` (nexmail) the operator chose ``archive_password`` for the file
        (at least 8 characters, typed twice on the page): the app writes its own encrypted, slim archive into a new
        file under ``archives.scratch(...)`` and returns it; the module deletes that file once it is sent."""
        return path

    # --- The schedule ------------------------------------------------------------------------------------------------

    def load_schedule(self) -> Schedule:
        """**Required.** The schedule from the app's settings, under the app's own keys (``backup_schedule``,
        ``backup_time``, ``backup_keep``; nexmail ``sicherung_takt``, ``sicherung_behalten``), with the app's
        defaults. Values of an older version are mapped here (nexmail ``taeglich`` → ``daily``)."""
        raise NotImplementedError("APP: load_schedule")

    def save_schedule(self, schedule: Schedule) -> None:
        """**Required.** Store the schedule under the app's keys, so that its settings route reads the same."""
        raise NotImplementedError("APP: save_schedule")

    # --- The storage --------------------------------------------------------------------------------------------------

    def parts(self) -> list[Part] | None:
        """What the app takes, by part, for the card "Speicher". None: the module measures the data folder by
        ``AppConfig.parts``."""
        return None

    def places(self) -> dict[str, Path]:
        """Folders whose disk is checked for a network share ("data", "database", nexpaper "documents"). None of the
        app's: the data folder and the folder of the database."""
        return {}

    # --- Telling ----------------------------------------------------------------------------------------------------

    def tell(self, event: str, details: dict[str, Any]) -> None:
        """Tell the operators (push, mail, the bell): ``backup_failed`` (a scheduled copy failed; details ``at``,
        ``reason``) and ``restore_failed`` (the restore at the start failed and the server runs with the data from
        before; details ``at``, ``name``). Called once per event; a failure here is logged and never stops anything."""
