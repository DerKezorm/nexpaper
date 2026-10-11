"""The manifest of the app on the home screen, in the language of the browser.

A long press on the app's symbol (Android) shows its shortcuts, "Upload" and "Take a photo"; those names and the
description come in the first language of the browser's ``Accept-Language`` that nexpaper has: the two it ships and
those the operator added (``services/locales.py``). Anything else gets English. The rest of the manifest is the file
of the built interface, unchanged.

The words for German and English are the ones under ``manifest`` in the interface's ``de.json`` and ``en.json`` (a test
holds both the same). A language file of the operator may bring its own ``manifest`` texts, also for ``de`` and ``en``,
as for every other text; what it leaves out comes from English (or from the shipped language it lays itself over).
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from . import locales

logger = logging.getLogger("nexpaper.manifest")

FALLBACK = "en"
KEYS = ("description", "upload", "uploadShort", "camera", "cameraShort")
SHIPPED: dict[str, dict[str, str]] = {
    "de": {"description": "Eine leichte Ablage für die Papiere von Haushalten und kleinen Firmen.",
           "upload": "Hochladen", "uploadShort": "Hochladen", "camera": "Fotografieren", "cameraShort": "Kamera"},
    "en": {"description": "A light paper filing cabinet for households and small firms.",
           "upload": "Upload", "uploadShort": "Upload", "camera": "Take a photo", "cameraShort": "Camera"},
}
#: The shortcuts by their address: which words name them.
SHORTCUTS = {"/schnell": ("upload", "uploadShort"), "/kamera": ("camera", "cameraShort")}
#: A name on the home screen; longer is no name but a mistake in a file.
MAX_TEXT = 120
#: Languages read from ``Accept-Language``; a browser sends a handful.
MAX_LANGUAGES = 20


def _known() -> set[str]:
    return set(SHIPPED) | {item.code for item in locales.available()}


def _weighted(header: str) -> list[str]:
    """The languages of ``Accept-Language`` by their weight (``q``), the order of the header among equal weights."""
    found: list[tuple[float, int, str]] = []
    for position, part in enumerate(header.split(",")[:MAX_LANGUAGES]):
        code, _, rest = part.strip().partition(";")
        weight = 1.0
        rest = rest.strip()
        if rest.startswith("q="):
            try:
                weight = float(rest[2:])
            except ValueError:
                continue
        code = code.strip()
        if code and code != "*" and weight > 0:
            found.append((-weight, position, code))
    return [code for _weight, _position, code in sorted(found)]


def choose(accept_language: str) -> str:
    """The first language of the browser that nexpaper has (``pt-BR``, else ``pt``), else English."""
    known = _known()
    for code in _weighted(accept_language or ""):
        language, _, region = code.partition("-")
        exact = f"{language.lower()}-{region.upper()}" if len(region) == 2 else code
        for candidate in (exact, language.lower()):
            if candidate in known:
                return candidate
    return FALLBACK


def texts(language: str) -> dict[str, str]:
    """The words for ``language``: the operator's file over the shipped words, English for what neither has."""
    words = dict(SHIPPED[FALLBACK])
    words.update(SHIPPED.get(language, {}))
    if language in SHIPPED and not (locales.locales_dir() / f"{language}.json").is_file():
        return words
    try:
        added = locales.load(language)
    except (OSError, ValueError):
        return words
    section = added.get("manifest")
    if isinstance(section, dict):
        for key in KEYS:
            value = section.get(key)
            if isinstance(value, str) and value.strip() and len(value) <= MAX_TEXT:
                words[key] = value.strip()
    return words


def localized(base: dict[str, Any], language: str) -> dict[str, Any]:
    """The manifest of the built interface with the words of ``language``."""
    words = texts(language)
    manifest = copy.deepcopy(base)
    manifest["lang"] = language
    manifest["description"] = words["description"]
    for shortcut in manifest.get("shortcuts") or []:
        names = SHORTCUTS.get(shortcut.get("url", "")) if isinstance(shortcut, dict) else None
        if names:
            shortcut["name"], shortcut["short_name"] = words[names[0]], words[names[1]]
    return manifest
