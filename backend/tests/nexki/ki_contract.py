"""What the contract tests ask of an app: the ``StandardAdapter`` the app's adapter extends, and helpers. The tests run
the module inside the app: its own start (with ``nexki.settings.adopt``), its accounts and operators, its ``Store``
over its own tables with its older names, its own uses of the AI, the module's routes. A stand-in service answers
(``ReferenceService`` from the module's ``tests-fuer-apps/reference/service.py``, copied next to these tests): as a
real server on 127.0.0.1 (the own network) or, for names on the internet, as a transport behind a resolver that names
a public address. Never a real service, never a real key. They never change; the app fills in its adapter
(``backend/tests/nexki_adapter.py``)."""

from __future__ import annotations

import importlib
import json
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
    #: nexdiary), ``own`` (nexmail), ``both`` (nexlore). An app without AI before: (). Since 0.1.2 (K-9) an app with
    #: ``own`` also starts ``own_unset`` (the same way, no account's service set up) and names its way to ``adopt``.
    older_forms: tuple[str, ...] = ()
    #: Since 0.1.1 (E55): where the app's own routes of its tasks (``manual``) keep older status and codes of a refusal,
    #: the module's code -> (status, the app's code); nexdiary ``{"ai_off": (403, "ai_off"), "ai_day_used": (429,
    #: "ai_daily_limit")}``. The module's routes always answer with the module's.
    old_codes: dict[str, tuple[int, str]] = {}  # noqa: RUF012 (read only)
    #: Since 0.1.2 (K-8, K-10): which kinds of task the app has. An app without button tasks (nexpaper: only
    #: proposals) runs the cases through ``automatic``, an app without automatic tasks (nexmail) through ``manual``;
    #: only the cases of one kind (what went out word for word, the line without content) fall away, deselected.
    has_manual = True
    has_automatic = True

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
    """The code of a refusal: ``detail.code``, or since 0.1.2 (K-4) ``detail`` itself where an app's older route
    answers it as text (nexmail ``"ki_nicht_erreichbar"``, E55)."""
    data = response.json()
    found = data.get("detail") if isinstance(data, dict) else None
    if isinstance(found, str):
        return found
    return str(detail(response).get("code") or "")


def values(adapter: Any, response: Any, role: str = "owner") -> dict[str, Any]:
    """The values of a refusal (``answered``, ``seconds``, ``said``): from ``detail``, or since 0.1.2 (K-4, K-7) where
    the app's older route answers ``detail`` as text, from the newest line of the account's "what went out"."""
    data = response.json()
    found = data.get("detail") if isinstance(data, dict) else None
    if isinstance(found, dict):
        return found
    events = adapter.client(role).get(f"{adapter.me_prefix}/events").json()
    return dict(events[0].get("values") or {}) if events else {}


class Done:
    """The answer of an automatic task in the form of a response (since 0.1.2): 200 with its text, or the refusal."""

    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self._body = body
        self.text = json.dumps(body)

    def json(self) -> dict[str, Any]:
        return self._body


def task(adapter: Any, role: str, text: str) -> Any:
    """One task of the app as ``role`` with ``text``: a button task where the app has one (``manual``, its response),
    else an automatic one (K-10), its outcome as a response."""
    if adapter.has_manual:
        return adapter.manual(role, text)
    nexki = package(adapter)
    try:
        found = adapter.automatic(role, text)
    except nexki.AiRefused as refused:
        return Done(refused.status, {"detail": refused.as_dict()})
    if hasattr(found, "status_code"):
        return found
    return Done(200, {"text": found if isinstance(found, str) else ""})


def said(adapter: Any, response: Any, module_code: str) -> bool:
    """Whether the app's own route (``manual``) refused with ``module_code``: the module's status and code, or the
    older ones the app keeps there (``old_codes``, E55). An automatic task (``task`` without button tasks) says the
    module's."""
    status, _ = package(adapter).errors.CODES[module_code]
    older = adapter.old_codes if adapter.has_manual else {}
    wanted_status, wanted_code = older.get(module_code, (status, module_code))
    return bool(response.status_code == wanted_status and code(response) == wanted_code)


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
