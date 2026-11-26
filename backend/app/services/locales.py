"""The operator's own languages: JSON files in ``<data_dir>/locales`` (``NEXPAPER_LOCALES_DIR``), from the shared
module sprachen 1.0.0 (E51). The folder stays where it was, so every file laid there before still counts; every name of
before stands here unchanged (``available``, ``load``, ``valid_code``, ``save``, ``remove``, ``forget``,
``locales_dir``, ``LocaleError``, ``MAX_BYTES`` …). The routes under ``/api/v1/locales`` are the module's
(``main.py``): the same ways and answers as before, the list now with the built-in languages first (``built_in``,
``own``).

English, German and French ship inside the frontend; a file for one of them lays its texts over the shipped ones. The
page makes the template itself (it knows the English texts), so the server has none.

Below the module: how nexpaper reads a browser's ``Accept-Language`` (the manifest, a new account's language).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..config import get_settings
from ..vendor import nexsprachen
from ..vendor.nexsprachen import *  # the module's names stand here as they did before

#: The languages nexpaper ships, in the order of its menus.
BUILT_IN = {"de": "Deutsch", "en": "English", "fr": "Français"}


def _folder() -> Path:
    directory = get_settings().locales_dir
    if directory is None:  # the settings validator fills it; this only satisfies the type
        raise RuntimeError("locales_dir is not set")
    return directory


def start() -> None:
    """nexpaper's languages at its start: the module set up with nexpaper's folder of before (its files stay valid),
    then, right after, what a stopped upload left there removed (``tidy_at_start``, sprachen step 10)."""
    nexsprachen.configure(nexsprachen.AppConfig(app_name="nexpaper", folder=_folder, built_in=BUILT_IN))
    nexsprachen.tidy_at_start()


start()


def codes() -> set[str]:
    """Every language nexpaper speaks: built in, and every usable file of the operator."""
    return set(BUILT_IN) | {item.code for item in nexsprachen.available()}


# --- The browser's languages ------------------------------------------------------------------------------------------

#: How much of ``Accept-Language`` is read. A browser sends well under 200 characters; every entry within this counts.
MAX_ACCEPT = 4096
#: A language range: a language, then subtags of letters and digits (``de``, ``pt-BR``, ``zh-Hant-TW``).
_RANGE = re.compile(r"^[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*$")


def _weight(params: list[str]) -> float | None:
    """The weight among the parameters of an entry: ``q`` in any case and at any place (1 without one). None when the
    weight is not a number from 0 to 1: such an entry is broken and counts not at all."""
    for param in params:
        name, _, value = param.partition("=")
        if name.strip().lower() != "q":
            continue
        try:
            weight = float(value.strip())
        except ValueError:
            return None
        return weight if 0 <= weight <= 1 else None
    return 1.0


def accepted(header: str) -> list[str]:
    """The languages of ``Accept-Language`` by their weight, the order of the header among equal weights. ``*``, a
    weight of 0 and broken entries are left out."""
    found: list[tuple[float, int, str]] = []
    for position, part in enumerate((header or "")[:MAX_ACCEPT].split(",")):
        code, *params = part.split(";")
        code = code.strip()
        weight = _weight(params)
        if weight and code != "*" and _RANGE.match(code):
            found.append((-weight, position, code))
    return [code for _weight, _position, code in sorted(found)]


def _canonical(subtags: list[str]) -> str:
    """``PT-br`` as ``pt-BR``, ``zh-hant`` as ``zh-Hant``: the way the files are named."""
    out = [subtags[0].lower()]
    for tag in subtags[1:]:
        out.append(tag.upper() if len(tag) == 2 else tag.title() if len(tag) == 4 else tag.lower())
    return "-".join(out)


def best_match(header: str, known: set[str]) -> str:
    """The first language of the browser that is in ``known``: with its region or script (``pt-BR``), else the
    language alone (``pt``). Empty when none is."""
    for code in accepted(header):
        subtags = code.split("-")
        for size in range(len(subtags), 0, -1):
            candidate = _canonical(subtags[:size])
            if candidate in known:
                return candidate
    return ""
