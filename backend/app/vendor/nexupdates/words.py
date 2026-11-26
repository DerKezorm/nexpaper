"""The words of the bell (U3) in the operator's language: one notice per new version. ``{app}`` the app's name,
``{version}`` the version without ``v``. Ortsangaben with „›“ (E46)."""

from __future__ import annotations

from .config import current

WORDS: dict[str, dict[str, str]] = {
    "de": {
        "title": "{app} {version} ist erschienen",
        "text": "Was neu ist, steht unter Einstellungen › Über {app}.",
    },
    "en": {
        "title": "{app} {version} is out",
        "text": "What is new is under Settings › About {app}.",
    },
    "fr": {
        "title": "{app} {version} est disponible",
        "text": "Les nouveautés sont sous Réglages › À propos de {app}.",
    },
}


def notice(language: str | None, version: str) -> dict[str, str]:
    """Title and text of the bell's notice about ``version`` in ``language`` (``de``, ``en``, ``fr``; else English)."""
    words = WORDS.get((language or "").lower().split("-")[0], WORDS["en"])
    values = {"app": current().app_name, "version": version.strip().removeprefix("v")}
    return {key: text.format(**values) for key, text in words.items()}
