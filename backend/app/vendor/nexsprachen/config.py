"""The app's settings for the module: its name, the folder of the operator's own languages, its built-in languages and
the texts of the template. Set once at start-up with ``configure``; the module's functions read them with
``current``."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: English is the language every nex app ships and the one an incomplete file falls back to.
FALLBACK = "en"


@dataclass
class AppConfig:
    """``app_name`` names the logger (``<app>.locales``) and the template's file (``<app>-language-template.json``).

    ``folder`` holds one JSON file per language (``nl.json``), a path or a function giving one (nexnotes
    ``<data_dir>/locales`` or ``NEXNOTES_LOCALES_DIR``). ``built_in`` maps the code of each language the app ships to
    its name in itself (``{"de": "Deutsch", "en": "English"}``); a file for one of them lays its texts over the
    shipped ones. ``fallback`` is the language whatever a file leaves out appears in. ``template`` gives the texts of
    the template (the app's texts in ``fallback``, as its frontend has them), None when the app's page makes the
    template itself (nexnotes)."""

    app_name: str
    folder: Path | Callable[[], Path]
    built_in: Mapping[str, str] = field(default_factory=lambda: {"de": "Deutsch", "en": "English"})
    fallback: str = FALLBACK
    template: Callable[[], Mapping[str, Any]] | None = None
    logger_name: str = ""

    def directory(self) -> Path:
        given = self.folder
        return Path(given() if callable(given) else given)

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(self.logger_name or f"{self.app_name}.locales")


_current: AppConfig | None = None


def configure(config: AppConfig) -> AppConfig:
    """Set the app's settings (once at start-up; tests may set them again). Forgets what the list remembered."""
    global _current
    _current = config
    from . import store

    store.forget()
    return config


def current() -> AppConfig:
    if _current is None:
        raise RuntimeError("nexsprachen is not configured: call nexsprachen.configure(AppConfig(...)) at start-up")
    return _current
