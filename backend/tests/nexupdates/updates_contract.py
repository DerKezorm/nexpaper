"""What the contract tests ask of an app: the ``StandardAdapter`` the app's adapter extends, and the stand-in for
GitHub (``FakeGitHub``), which answers ``releases/latest`` and counts every question.

The contract tests run the module inside the app: its own start (``nexupdates.configure`` with its storage and bell),
its own checks of accounts and operators, the routes mounted from ``nexupdates.api``. The stand-in takes the place of
the network as a server on 127.0.0.1 named by ``AppConfig.update_url`` (set by the conftest after the app's start, as
``<APP>_UPDATE_URL`` would); nothing reaches GitHub.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any


@dataclass
class Seen:
    """One question as the stand-in received it."""

    method: str
    url: str
    headers: dict[str, str]


@dataclass
class FakeGitHub:
    """GitHub's ``releases/latest`` as a test wants it, as a real server on 127.0.0.1 (so the app's real client goes
    over the network, its proxies and limits included): ``tag`` (None: no ``tag_name``), ``status``, ``body`` (in
    place of the JSON), ``fail`` (the connection breaks without an answer). ``requests`` holds every question."""

    tag: str | None = "v99.0.0"
    status: int = 200
    body: bytes | None = None
    fail: bool = False
    requests: list[Seen] = field(default_factory=list)

    def __post_init__(self) -> None:
        import http.server
        import threading

        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                outer.requests.append(Seen("GET", f"{outer.url.rsplit('/repos/', 1)[0]}{self.path}",
                                           {key.lower(): value for key, value in self.headers.items()}))
                if outer.fail:
                    self.close_connection = True
                    self.connection.shutdown(2)
                    return
                body = outer.body if outer.body is not None else json.dumps(
                    {"tag_name": outer.tag, "name": "Release"} if outer.tag is not None else {"message": "Not Found"}
                ).encode()
                self.send_response(outer.status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: Any) -> None:
                return None

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/repos/DerKezorm/app/releases/latest"
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


class StandardAdapter:
    """Defaults; every method marked ``APP`` is the app's to write."""

    #: Where the vendored package lives in the app.
    package = "app.vendor.nexupdates"
    #: Where the app mounts ``nexupdates.api.router`` (nexpaper ``/api/v1/about``).
    prefix = "/api/about"
    #: Further prefixes the same routes are mounted under.
    also: tuple[str, ...] = ()
    #: Since 0.1.2: False for an app without a bell (U19: ``configure`` without ``on_newer``; it asks only when an
    #: operator opens "Über"). Then ``bell`` and ``bell_notices`` are never called, and the tests check instead that
    #: the background never asks.
    has_bell = True

    def start(self) -> None:
        """APP: an empty app with a fresh database and data folder, started as in production (``configure``), with an
        operator and a member; the switch as a new installation has it before setup (nothing stored)."""
        raise NotImplementedError("APP: start")

    def stop(self) -> None:
        """APP: close the database, remove temporary folders."""

    def restart(self) -> None:
        """APP: start the app again on the same data (``configure`` as in production)."""
        raise NotImplementedError("APP: restart")

    def client(self, role: str) -> Any:
        """APP: a ``TestClient``: ``"operator"``, ``"member"`` or ``"anonymous"``."""
        raise NotImplementedError("APP: client")

    def stored_switch(self) -> Any:
        """APP: the daily check as the app's storage holds it, raw (``update_check``; nexmail ``update_pruefen``);
        None while nothing is stored."""
        raise NotImplementedError("APP: stored_switch")

    def store_legacy_switch(self, on: bool) -> None:
        """APP: the switch written the way the version before the module did (its key, its form: nexmail ``"0"``)."""
        raise NotImplementedError("APP: store_legacy_switch")

    def setup(self, on: bool) -> None:
        """APP: the setup of a new installation as the operator does it, with the box "Nach neuen Versionen sehen"
        ticked (``on``) or not (U1; the app's setup route calls ``nexupdates.at_setup``)."""
        raise NotImplementedError("APP: setup")

    def bell(self) -> list[str]:
        """APP (only with ``has_bell``): the versions one operator's bell was told about, oldest first (U3)."""
        raise NotImplementedError("APP: bell")

    def bell_notices(self) -> list[tuple[str, str, str]]:
        """APP (only with ``has_bell``): every notice of the bell as (language of the operator's account, version,
        title), U17."""
        raise NotImplementedError("APP: bell_notices")

    def description(self) -> dict[str, Any]:
        """The app's OpenAPI description, also when it does not publish it (default: what the client's app makes)."""
        return self.client("anonymous").app.openapi()  # type: ignore[no-any-return]

    def look(self) -> None:
        """The background's look, as the app runs it (default ``nexupdates.look_once``)."""
        contract_package(self).look_once()


def contract_package(adapter: Any) -> ModuleType:
    package = importlib.import_module(adapter.package)
    importlib.import_module(f"{adapter.package}.api")
    return package


def plug(adapter: Any, fake: FakeGitHub) -> None:
    """Point the app's own configuration at the stand-in, as ``<APP>_UPDATE_URL`` would."""
    import dataclasses

    package = contract_package(adapter)
    package.configure(dataclasses.replace(package.current(), update_url=fake.url))


def background_stays_quiet(adapter: Any, fake: FakeGitHub) -> None:
    """Without a bell (U19): the background's look asks nobody and tells nobody, however often it runs."""
    package = contract_package(adapter)
    before = len(fake.requests)
    for _ in range(2):
        package.forget()
        assert package.look_once() is None
    assert len(fake.requests) == before, "an app without a bell asked in the background"
