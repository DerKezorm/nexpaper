"""Whether a newer nexpaper is out: the shared module ``nexupdates`` (updates 0.1.1) on nexpaper's settings.

The public GitHub API is asked for the newest release only when an operator opens the about page (``GET
/api/v1/about/updates``) and the last answer is older than a day (an hour after one that failed), or when an operator
presses "Jetzt nachsehen". A member's page never asks and learns nothing of the check (U15, U21). nexpaper has no bell,
so nothing looks in the background (U19): ``NEXPAPER_DISABLE_BACKGROUND`` has nothing to do with it. Nothing goes out
but the question itself: no names, no documents, no settings, not the version of this server. Off means "not by
itself": the button still asks.

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
            # No bell in nexpaper (U19): the operators hear of a new version on the about page only.
            on_newer=None,
        )
    )


configure()
