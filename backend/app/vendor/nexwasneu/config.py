"""What the app tells the module once at start (``configure``): its name, its running version, where its texts lie
and which languages it has built in."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

#: The language every other one falls back to (W4). Its file holds every version any other file holds (W11).
FALLBACK = "en"
#: The first version of an app: nobody updates into it, so it needs no text (W11).
FIRST = "0.1.0"
#: How many unread versions the window shows at once after an update (W6); the rest under "Earlier versions".
UNREAD_LIMIT = 5


@dataclass(frozen=True)
class AppConfig:
    """The app's values.

    ``folder`` holds one file ``<language>.json`` per built-in language and ``released.json`` (the frozen texts, W12):
    ``backend/app/whatsnew`` (nexmail ``backend/app/wasneu``). ``languages`` are the app's built-in languages in its
    order, English among them (``("de", "en")``, nexpaper ``("de", "en", "fr")``); a language the operator uploaded
    reads English."""

    app_name: str
    version: str | Callable[[], str]
    folder: Path
    languages: tuple[str, ...] = ("de", "en")
    first: str = FIRST
    unread_limit: int = UNREAD_LIMIT

    def running(self) -> str:
        return self.version() if callable(self.version) else self.version


_config: AppConfig | None = None


def configure(config: AppConfig) -> AppConfig:
    """Set the app's values (at start, and in tests). English must be one of the languages."""
    if FALLBACK not in config.languages:
        raise ValueError(f"the languages must hold {FALLBACK!r}, the fallback of every other one")
    if config.unread_limit < 1:
        raise ValueError("unread_limit must be at least 1")
    global _config
    _config = config
    return config


def current() -> AppConfig:
    if _config is None:
        raise RuntimeError("nexwasneu is not configured: call nexwasneu.configure(AppConfig(...)) at start")
    return _config
