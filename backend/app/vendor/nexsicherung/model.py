"""What the module passes around: the schedule, what an archive says of itself, an entry of the list, the result of a
check, a part of the storage. Plain data, no behaviour."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MANUAL = "manual"
SCHEDULED = "scheduled"
UPDATE = "update"
KINDS = (MANUAL, SCHEDULED, UPDATE)
#: Pruned when more than ``keep`` of them lie there; a copy made by hand or brought in from elsewhere never is.
AUTOMATIC_KINDS = (SCHEDULED, UPDATE)

OFF = "off"
DAILY = "daily"
WEEKLY = "weekly"
MONTHLY = "monthly"
#: "Automatisch": Aus / Jede Nacht / Jede Woche (Bauplan Einstellungen, Speicher und Sicherung) / Jeden Monat (am 1.,
#: entschieden beim Bauen: nexmail konnte es, also alle).
EVERY = (OFF, DAILY, WEEKLY, MONTHLY)
TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
KEEP_MIN = 1
KEEP_MAX = 365


@dataclass(frozen=True)
class Schedule:
    """When scheduled copies are made and how many are kept. ``time`` is a wall clock time ``HH:MM`` in the server's
    time zone (``AppConfig.time_zone``)."""

    every: str = DAILY
    time: str = "03:00"
    keep: int = 7


@dataclass
class Described:
    """What an archive says of itself, read by the app's ``describe`` (its manifest). ``created`` is an ISO time with
    zone (None when it cannot be read, e.g. a locked archive). ``facts`` are the app's counts for the list (``notes``,
    ``files``, ``accounts`` …): their keys and values are the app's, flat, as its listing answered them before.
    ``locked``: the archive is encrypted and its check and restore need its own password (nexmail)."""

    created: str | None
    kind: str = MANUAL
    note: str = ""
    version: str = ""
    facts: dict[str, Any] = field(default_factory=dict)
    locked: bool = False


@dataclass
class Entry:
    """A line of the list. ``readable`` False: a file with one of the app's names that its ``describe`` refused (cut
    off, damaged); listed so that it can be deleted, never pruned and never restored."""

    name: str
    size: int
    created: str
    kind: str
    note: str
    version: str
    uploaded: bool = False
    locked: bool = False
    readable: bool = True
    facts: dict[str, Any] = field(default_factory=dict)

    def flat(self) -> dict[str, Any]:
        """The shape of the apps' own listings before the module: the facts at the top level."""
        shown = {key: value for key, value in self.__dict__.items() if key != "facts"}
        return {**self.facts, **shown}


@dataclass
class Checked:
    """The app's answer to "is this archive whole, and what would a restore change?".

    ``database_ok``/``files_ok``: whole or not (``damaged`` names the first broken members). ``blocked``: a code that
    forbids the restore although the archive is whole (nexdiary ``backup_other_master_key``), with ``blocked_text``.
    ``details``: the app's own findings, flat (``would_add``, ``notes_add_titles``, ``revived_keys`` …), as its check
    answered them before; the page shows them through the app's own words."""

    database_ok: bool
    files_ok: bool = True
    damaged: list[str] = field(default_factory=list)
    blocked: str = ""
    blocked_text: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Brief:
    """The module's result of a check: the entry, the app's findings, and whether a restore may go ahead."""

    name: str
    created: str
    kind: str
    note: str
    version: str
    uploaded: bool
    database_ok: bool
    files_ok: bool
    damaged: list[str]
    too_new: bool
    blocked: str
    facts: dict[str, Any]
    details: dict[str, Any]
    blocked_text: str = ""

    @property
    def usable(self) -> bool:
        return self.database_ok and self.files_ok and not self.too_new and not self.blocked

    def view(self) -> dict[str, Any]:
        """For the module's own route: nested, so no fact of an app can shadow a field of the module."""
        return {
            "name": self.name, "created": self.created, "kind": self.kind, "note": self.note,
            "version": self.version, "uploaded": self.uploaded, "database_ok": self.database_ok,
            "files_ok": self.files_ok, "damaged": self.damaged, "too_new": self.too_new, "blocked": self.blocked,
            "blocked_text": self.blocked_text,
            "usable": self.usable, "facts": self.facts, "details": self.details,
        }

    def flat(self) -> dict[str, Any]:
        """The shape of the apps' own check before the module: facts and findings at the top level."""
        own = self.view()
        own.pop("facts")
        own.pop("details")
        return {**self.facts, **self.details, **own}


@dataclass(frozen=True)
class Part:
    """A part of what the app takes on the disk. ``within``: the key of the part this one is a share of ("davon
    Originale" within "documents"), not added to the sum. ``complete`` False: counting stopped at the time limit."""

    key: str
    bytes: int
    within: str = ""
    complete: bool = True


@dataclass(frozen=True)
class Where:
    #: ``network``, ``local`` or ``unknown``.
    kind: str
    #: The file system type as the system calls it (``nfs4``), or empty.
    fstype: str = ""

    @property
    def network(self) -> bool:
        return self.kind == "network"
