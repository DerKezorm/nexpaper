"""The app's settings for the module: its name, version, repository and project page, the address it asks (or the
one ``<APP>_UPDATE_URL`` names), and the hooks to its storage and its bell. Set once at start-up with ``configure``;
the module's functions read them with ``current``."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

#: Until the operator decides (setup) or switched before the module: on, as in eight apps before (U1).
DEFAULT_ON = True


@dataclass
class AppConfig:
    """``app_name`` names the logger (``<app>.updates``) and the bell's words. ``version`` is the running version
    (text or a function). ``repo`` is ``DerKezorm/<app>`` on GitHub; ``project_url`` the project page, empty for none.
    ``update_url`` is what ``<APP>_UPDATE_URL`` says (text or function; empty: GitHub's ``releases/latest``).

    The hooks, all the app's own storage and its bell:

    - ``read_switch() -> bool | None``: the daily check as stored (``update_check``; nexmail ``update_pruefen``), None
      while nothing is stored;
    - ``write_switch(on)``: store it;
    - ``read_told() -> str | None`` / ``write_told(version)``: the version the operators were last told about (nexlore
      ``notify_version``), so nobody hears of a version twice;
    - ``on_newer(version)``: tell the operators once (U3; the app's bell, e.g. nexlore ``notify.operators``); None for
      an app without a bell;
    - since 0.1.3 (U24), an app that pairs devices (module ``geraete``): ``devices_want() -> bool``, True while a
      device of an operator understands and wants the kind ``update`` (``nexgeraete.notices.update_wanted``), and
      ``on_devices(version)``, telling those devices (``nexgeraete.notices.newer``). Such a device counts as a bell:
      while there is one, the background looks at most once a day, also in an app without a bell. Both None: no
      devices.
    """

    app_name: str
    version: str | Callable[[], str]
    repo: str
    read_switch: Callable[[], bool | None]
    write_switch: Callable[[bool], None]
    read_told: Callable[[], str | None] = lambda: None
    write_told: Callable[[str], None] = lambda _version: None
    on_newer: Callable[[str], None] | None = None
    devices_want: Callable[[], bool] | None = None
    on_devices: Callable[[str], None] | None = None
    project_url: str = ""
    license: str = "AGPL-3.0"
    update_url: str | Callable[[], str] = ""
    default_on: bool = DEFAULT_ON
    logger_name: str = ""

    def running(self) -> str:
        return self.version() if callable(self.version) else self.version

    def url(self) -> str:
        given = self.update_url() if callable(self.update_url) else self.update_url
        return (given or "").strip() or f"https://api.github.com/repos/{self.repo}/releases/latest"

    @property
    def repo_url(self) -> str:
        return f"https://github.com/{self.repo}"

    @property
    def releases_url(self) -> str:
        return f"{self.repo_url}/releases"

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(self.logger_name or f"{self.app_name}.updates")


_current: AppConfig | None = None


def configure(config: AppConfig) -> AppConfig:
    """Set the app's settings (once at start-up; tests may set them again). Forgets the last answer."""
    global _current
    _current = config
    from . import check

    check.forget()
    return config


def current() -> AppConfig:
    if _current is None:
        raise RuntimeError("nexupdates is not configured: call nexupdates.configure(AppConfig(...)) at start-up")
    return _current
