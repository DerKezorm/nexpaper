"""Whether a newer nexpaper is out: the shared module ``nexupdates`` (updates 0.1.1) on nexpaper's settings.

The public GitHub API is asked for the newest release when an operator opens the about page (``GET
/api/v1/about/updates``) and the last answer is older than a day (an hour after one that failed), when an operator
presses "Jetzt nachsehen", and since geraete 0.1.0 by the background at most once a day while the switch is on: a newer
version is told once to the operators' devices that understand it (G18, ``geraete_store.announce``; nexpaper has no
bell of its own, the about page shows it as before). A member's page never asks and learns nothing of the check (U15,
U21). Nothing goes out but the question itself: no names, no documents, no settings, not the version of this server.
Off means "not by itself": the button still asks.

The switch stays where it was, ``update_check`` in the settings table, with its value; a new installation answers it
at setup (U1, ``nexupdates.at_setup``). The project pages are switched off, so the about page names none (U18).

The names of the module stand here (``state``, ``forget``, ``parse``, ``is_newer``, ``State`` …), as before.
"""

from __future__ import annotations

# nexpaper's version under a name of its own: the module's star import brings the module's ``__version__``.
from .. import __version__ as NEXPAPER_VERSION
from ..config import get_settings
from ..vendor import nexupdates
from ..vendor.nexupdates import *  # the names this file had before the module

REPO = "DerKezorm/nexpaper"
REPO_URL = f"https://github.com/{REPO}"
RELEASES_URL = f"{REPO_URL}/releases"
#: The project page; empty while the project pages are switched off (U18): the about page leaves the row out then.
PROJECT_URL = ""
#: Where the switch lives in the settings table (as before the module).
SWITCH = "update_check"
#: The version the operators' devices were last told about (geraete 0.1.0): nobody hears of a version twice.
TOLD = "update_told"


def _read_switch() -> bool | None:
    """The daily check as stored; None while nothing is stored (the default of the settings then holds: on)."""
    from ..db import SessionLocal
    from ..models import Setting

    with SessionLocal() as db:
        row = db.get(Setting, SWITCH)
        return None if row is None or row.value is None else bool(row.value)


def _write_switch(on: bool) -> None:
    from ..db import SessionLocal
    from . import settings_service

    with SessionLocal() as db:
        settings_service.save(db, {SWITCH: bool(on)})


def _read_told() -> str | None:
    from ..db import SessionLocal
    from . import settings_service

    with SessionLocal() as db:
        found = settings_service.get(db, TOLD)
    return str(found) if found else None


def _write_told(version: str) -> None:
    from ..db import SessionLocal
    from . import settings_service

    with SessionLocal() as db:
        settings_service.save(db, {TOLD: version})


def _on_newer(version: str) -> None:
    from . import geraete_store

    geraete_store.announce(version)


def configure() -> nexupdates.AppConfig:
    """nexpaper's settings for the module; at import, and again by a test that moved the data folder."""
    return nexupdates.configure(
        nexupdates.AppConfig(
            app_name="nexpaper",
            version=lambda: NEXPAPER_VERSION,
            repo=REPO,
            project_url=PROJECT_URL,
            update_url=lambda: get_settings().update_url,
            read_switch=_read_switch,
            write_switch=_write_switch,
            read_told=_read_told,
            write_told=_write_told,
            # nexpaper has no bell; since geraete 0.1.0 (G18) the operators' devices hear of a new version once
            # (looked up at the call: the contract tests listen). The about page shows it as before.
            on_newer=lambda version: _on_newer(version),
        )
    )


configure()
