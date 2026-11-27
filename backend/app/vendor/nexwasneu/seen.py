"""What one account has read (W5): the app keeps it with the account (``whats_new_seen``, nexmail
``wasneu_gesehen``); the module only asks and sets it through a ``Viewer`` the app builds per request."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .config import current


@dataclass(frozen=True)
class Viewer:
    """The signed-in account as the module needs it: the version it read (``""`` when unknown), whether it is an
    operator (W8), how to store a version it read, and the language of its account (the page may ask for another)."""

    seen: str
    operator: bool
    mark: Callable[[str], None]
    language: str | None = None


def seen_for_new_account() -> str:
    """The value a new account starts with: the running version, so that a fresh account is not greeted with news."""
    return current().running()


def mark_seen(viewer: Viewer) -> str:
    """The account read or put away the running version (also from an app's old route, W10); returns it."""
    version = current().running()
    viewer.mark(version)
    return version
