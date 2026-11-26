"""What the contract tests ask of an app: the ``StandardAdapter`` the app's adapter extends, and helpers. The tests run
the module inside the app: its own start (with ``nexki.settings.adopt``), its accounts and operators, its ``Store``
over its own tables with its older names, its own uses of the AI, the module's routes. A stand-in service answers
(``ReferenceService`` from the module's ``tests-fuer-apps/reference/service.py``, copied next to these tests): as a
real server on 127.0.0.1 (the own network) or, for names on the internet, as a transport behind a resolver that names
a public address. Never a real service, never a real key. They never change; the app fills in its adapter
(``backend/tests/nexki_adapter.py``)."""

from __future__ import annotations

import importlib
import time
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType
from typing import Any

from nexki_service import ReferenceService

#: The public address the tests give names on the internet (never connected to: the transport answers).
PUBLIC = "93.184.215.14"
#: A key for the tests; no service anywhere knows it.
KEY = "test-key-reference-0001"


class StandardAdapter:
    """Defaults; every method marked ``APP`` is the app's to write."""

    package = "app.vendor.nexki"
    server_prefix = "/api/server/ai"
    me_prefix = "/api/me/ai"
    #: The kinds of older installation of this app the contract test "Bestand" starts from: ``shared`` (nexpaper,
    #: nexdiary), ``own`` (nexmail), ``both`` (nexlore). An app without AI before: ().
    older_forms: tuple[str, ...] = ()

    def start(self) -> None:
        """APP: a freshly installed app, started as in production, with ``owner``, ``other`` (members) and
        ``operator``."""
        raise NotImplementedError("APP: start")

    def start_older(self, form: str, base: str, key: str) -> None:
        """APP: the database the older version of this app wrote, with a working AI service at ``base`` (an address
        on 127.0.0.1) and its ``key`` stored the old way (for ``own``: the account ``owner``'s), then the new version
        started on it."""
        raise NotImplementedError("APP: start_older")

    def stop(self) -> None:
        """APP: close the database, remove temporary folders."""

    def client(self, role: str) -> Any:
        """APP: a TestClient as ``owner``, ``other``, ``operator`` or ``anonymous``."""
        raise NotImplementedError("APP: client")

    def config(self) -> Any:
        """APP: the app's ``nexki.AppConfig``."""
        raise NotImplementedError("APP: config")

    def store(self) -> Any:
        """APP: the app's ``nexki.Store`` (for ``for_programs``, what ``schluessel`` and ``mcp`` ask)."""
        raise NotImplementedError("APP: store")

    def account_id(self, role: str) -> Any:
        raise NotImplementedError("APP: account_id")

    def manual(self, role: str, text: str) -> Any:
        """APP: one of the app's button tasks as ``role`` with ``text`` in it, through the app's own route; the
        response."""
        raise NotImplementedError("APP: manual")

    def automatic(self, role: str, text: str) -> Any:
        """APP: one of the app's automatic tasks for ``role`` with ``text``, run now (in the app a job); returns
        nothing or a response, refusals as ``nexki.AiRefused``."""
        raise NotImplementedError("APP: automatic")

    def app_refused(self, role: str, text: str) -> Any:
        """APP: a request the app's own check turns down (nexmail received mail with its switch off, nexpaper a
        personal vault); ``None`` where the app has no check of its own."""
        return None

    def take_ai(self, role: str) -> None:
        """APP: "KI erlaubt" off for the account (Server › Konten › Verwalten)."""
        raise NotImplementedError("APP: take_ai")

    def give_ai(self, role: str) -> None:
        raise NotImplementedError("APP: give_ai")

    def shut_out(self, role: str) -> None:
        """APP: block the account (module konten)."""
        raise NotImplementedError("APP: shut_out")

    def let_in(self, role: str) -> None:
        raise NotImplementedError("APP: let_in")

    def dump(self) -> str:
        """APP: everything the app stores, as text (database dump): no key, no sent text in the clear."""
        raise NotImplementedError("APP: dump")


def package(adapter: Any) -> ModuleType:
    return importlib.import_module(adapter.package)


def detail(response: Any) -> dict[str, Any]:
    data = response.json()
    found = data.get("detail") if isinstance(data, dict) else None
    return found if isinstance(found, dict) else {}


def code(response: Any) -> str:
    return str(detail(response).get("code") or "")


def operator_puts(adapter: Any, **body: Any) -> Any:
    return adapter.client("operator").put(adapter.server_prefix, json=body)


def shared(adapter: Any, base: str, *, api: str = "openai", model: str = "plain", key: str = "",
           enabled: bool = True) -> dict[str, Any]:
    """The operator's service for all, switched on."""
    done = operator_puts(adapter, mode="shared", api=api, url=base, model=model, key=key, enabled=enabled)
    assert done.status_code == 200, done.text
    return done.json()


def own(adapter: Any, *, hosts: list[str] | None = None) -> None:
    """Each account its own service, switched on, with the operator's hosts."""
    done = operator_puts(adapter, mode="own", enabled=True, hosts=hosts or [])
    assert done.status_code == 200, done.text


@contextmanager
def internet(adapter: Any, service: ReferenceService, names: dict[str, list[str]] | None = None) -> Iterator[list[str]]:
    """Names on the internet: ``*.example.com`` resolves to ``PUBLIC`` (or as ``names`` says), the reference service
    answers as a transport. Yields the names asked, in order."""
    found = package(adapter).client
    asked: list[str] = []
    before = (found.transport, found.resolver)

    def resolver(host: str, port: int) -> list[str]:
        asked.append(host)
        if names and host in names:
            return list(names[host])
        if host.endswith("example.com"):
            return [PUBLIC]
        return before[1](host, port)

    found.transport, found.resolver = service.transport(), resolver
    try:
        yield asked
    finally:
        found.transport, found.resolver = before


@contextmanager
def resolving(adapter: Any, names: dict[str, list[str]]) -> Iterator[None]:
    """Names that resolve as ``names`` says (no connection made: for refusals)."""
    found = package(adapter).client
    before = found.resolver
    found.resolver = lambda host, port: list(names[host]) if host in names else before(host, port)
    try:
        yield
    finally:
        found.resolver = before


@contextmanager
def fast_clock(adapter: Any, factor: float = 100.0) -> Iterator[None]:
    """The clock of the deadlines runs ``factor`` times as fast: 180 s of a task are 1.8 s."""
    found = package(adapter).client
    before = found.ticks
    start = time.monotonic()
    found.ticks = lambda: start + (time.monotonic() - start) * factor
    try:
        yield
    finally:
        found.ticks = before


def last_body(service: ReferenceService, path_end: str = "/chat/completions") -> dict[str, Any]:
    bodies = [seen.body for seen in service.seen if seen.path.endswith(path_end)]
    assert bodies, [seen.path for seen in service.seen]
    return bodies[-1]
