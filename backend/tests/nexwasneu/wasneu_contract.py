"""What every app's adapter offers the contract tests, and the texts the tests put in place of the app's own.

Copied unchanged into every app (``backend/tests/nexwasneu/``). The app's adapter
(``backend/tests/nexwasneu_adapter.py``) derives from ``StandardAdapter`` and fills in what is marked there."""

from __future__ import annotations

import dataclasses
import importlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

#: The running version while the routes are tested on the contract's own texts.
RUNNING = "2.3.0"


class StandardAdapter:
    """The app as the contract sees it. ``client(role)`` gives a test client signed in as ``"operator"`` or
    ``"member"``, or ``"anonymous"``."""

    #: Where the vendored package lives, and the app's own package (its texts lie inside it, so the image has them).
    package = "app.vendor.nexwasneu"
    root_package = "app"
    #: Where the app mounted ``nexwasneu.api.router`` (nexpaper ``/api/v1/whats-new``).
    prefix = "/api/whats-new"
    #: The app's routes of before that put the running version away (W10); each must keep working.
    old_seen: tuple[str, ...] = ("/api/me/whats-new/seen",)
    #: The route that names the account with the version it read, and the field (E53: stays).
    me = "/api/auth/me"
    me_field = "whats_new_seen"

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        pass

    def client(self, role: str) -> Any:
        raise NotImplementedError

    def stored_seen(self, role: str) -> str:
        """The version the account of ``role`` read, as the app stores it."""
        raise NotImplementedError

    def set_seen(self, role: str, version: str) -> None:
        """Store ``version`` as read for the account of ``role`` (as an older version of the app left it)."""
        raise NotImplementedError

    def new_account_seen(self) -> str:
        """Make a new account the way the app does (invitation, provider, setup) and return what it stored as read."""
        raise NotImplementedError


def contract_package(app: StandardAdapter) -> ModuleType:
    return importlib.import_module(app.package)


def entry(language: str, version: str, *, operator_only: bool = False, with_operator: bool = False) -> dict[str, Any]:
    """An entry the tests can tell apart: its language and version stand in the lead and every title."""
    mark = f"{language} {version}"
    sections = [{"title": f"Part {mark}", "where": f"Where {mark}", "body": f"Body {mark}",
                 **({"operator": True} if operator_only else {})}]
    if with_operator:
        sections.append({"title": f"Operators {mark}", "where": "Server", "body": "Nothing to do.", "operator": True})
    return {"lead": f"Lead {mark}", "sections": sections, "smallTitle": "Also", "small": [f"Small {mark}"]}


def texts(languages: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """The contract's texts: 1.0.0 only in English (the others read it in English), 2.1.0 only for operators, 2.3.0
    (the running one) with a part for operators, 2.2.1 a fix with a text, 2.4.0 not out yet, and two entries the module
    must leave out."""
    files: dict[str, dict[str, Any]] = {}
    for language in languages:
        every: dict[str, Any] = {}
        if language == "en":
            every["1.0.0"] = entry(language, "1.0.0")
            every["2.0.5"] = {"lead": "", "sections": [], "smallTitle": "", "small": []}
            every["v2.0.6"] = entry(language, "2.0.6")
        every["2.0.0"] = entry(language, "2.0.0")
        every["2.1.0"] = entry(language, "2.1.0", operator_only=True)
        every["2.2.0"] = entry(language, "2.2.0")
        every["2.2.1"] = entry(language, "2.2.1")
        every[RUNNING] = entry(language, RUNNING, with_operator=True)
        every["2.4.0"] = entry(language, "2.4.0")
        files[language] = every
    return files


@contextmanager
def swapped(app: StandardAdapter, folder: Path, version: str = RUNNING, **more: Any) -> Iterator[ModuleType]:
    """The app's configuration with the contract's texts in ``folder`` and ``version`` as the running one, restored
    afterwards."""
    package = contract_package(app)
    before = package.current()
    folder.mkdir(parents=True, exist_ok=True)
    for language, every in texts(before.languages).items():
        (folder / f"{language}.json").write_text(json.dumps(every, ensure_ascii=False), encoding="utf-8")
    package.configure(dataclasses.replace(before, folder=folder, version=version, **more))
    package.forget()
    try:
        yield package
    finally:
        package.configure(before)
        package.forget()
