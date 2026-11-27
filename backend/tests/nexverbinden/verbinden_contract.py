"""What the contract tests ask of an app: the ``StandardAdapter`` the app's adapter extends, and the ``World`` in which
the app and its partner (``verbinden_partner.ReferenceApp``, any app of the catalog) reach each other without a
network: every request one app makes to the other goes through ``reach.TRANSPORT`` to the other's routes, the names
resolve through ``reach.RESOLVER``. The tests never change; the app fills in its adapter
(``backend/tests/nexverbinden_adapter.py``)."""

from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi.testclient import TestClient
from verbinden_partner import ReferenceApp

#: Where the names point: every app outside on the internet, ``home.example.com`` in the own network.
PUBLIC = "93.184.215.14"
HOME = "192.168.1.20"


class StandardAdapter:
    """Defaults; every method marked ``APP`` is the app's to write."""

    package = "app.vendor.nexverbinden"
    #: APP: an app of the catalog this app connects with (``config().partners``); the tests play it.
    partner = ""
    #: APP: the app's public address in the tests (``https://tasks.example.com``).
    base = ""
    #: The older version had a connection typed in by hand with ``partner`` (its key ends within a week).
    older_link = False
    #: APP: after ``start``, the app's ``nexverbinden.Store`` (for ``retry_waiting``, as the app's clock calls it).
    store: Any = None
    #: The display names of ``owner`` and ``other`` in the app (since 0.1.2; an app with other names says so).
    names: dict[str, str] = {"owner": "kim", "other": "sam"}  # noqa: RUF012 (read only)
    #: Since 0.1.8 (B1, V43): the shown names the app's ``Store.account_card`` gives ``owner`` and ``other``, where
    #: they differ from ``names`` ("Kim Example"); empty: the consent page shows the name alone.
    shown_names: dict[str, str] = {}  # noqa: RUF012 (read only)

    def start(self, folder: Path, *, older: bool = False) -> None:
        """APP: the app started as in production, with ``owner``, ``other`` and ``operator``; ``older``: on a database
        the older version wrote (an API key of ``owner`` in ``older_key``, and with ``older_link`` a connection typed
        in by hand with ``partner``)."""
        raise NotImplementedError("APP: start")

    def stop(self) -> None:
        """APP: close the database."""

    def asgi(self) -> Any:
        """APP: the app's ASGI app (its FastAPI)."""
        raise NotImplementedError("APP: asgi")

    def client(self, role: str | None) -> TestClient:
        """APP: a ``TestClient`` at ``base`` as ``owner``, ``other``, ``operator`` (browser sessions), or ``None``."""
        raise NotImplementedError("APP: client")

    def config(self) -> Any:
        """APP: the app's ``nexverbinden.AppConfig``."""
        raise NotImplementedError("APP: config")

    def account_id(self, role: str) -> Any:
        """APP (since 0.1.2): the id of the account of ``owner`` or ``other`` as the app's Store knows it."""
        raise NotImplementedError("APP: account_id")

    def disconnected(self) -> list[tuple[Any, str]]:
        """APP (since 0.1.4, V-13): every call of the app's ``on_disconnected`` so far as (account id, partner), in
        order (the app drops its own rows of the connection there, nexmail its task and calendar link)."""
        raise NotImplementedError("APP: disconnected")

    def block(self, role: str, blocked: bool = True) -> None:
        """APP: block (or free) the account as the operator does."""
        raise NotImplementedError("APP: block")

    def probe(self, purpose: str) -> str | tuple[str, str, Any] | None:
        """APP: a ``GET`` route of the app that a connection with ``purpose`` opens (``/api/v1/tasks``), or since 0.1.2
        ``(method, route, body)`` for a purpose that writes (``("PATCH", "/api/v1/tasks/1", {"completed": True})``);
        ``None`` only when the app grants no purpose at all."""
        raise NotImplementedError("APP: probe")

    def areas_seen(self, purpose: str, answer: Any) -> set[str]:
        """APP: the ids of the areas whose things the answer of ``probe(purpose)`` shows (JSON of the answer)."""
        raise NotImplementedError("APP: areas_seen")

    def write_into(self, purpose: str, area: Any) -> tuple[str, str, Any]:
        """APP (since 0.1.7, V41), only for an app whose partner writes there with areas (nexlore and nexnotes
        ``notes.add``, nexpaper ``documents.add``, nextasks ``tasks.write``): ``(method, route, body)`` of a write of
        ``purpose`` into the area ``area`` of ``owner`` (an id from ``areas_choice``). Into an area the connection was
        given it must succeed (2xx), into any other the app refuses it (403 or 404)."""
        raise NotImplementedError("APP: write_into")

    def people(self, answer: Any) -> list[dict[str, Any]]:
        """APP, only for an app that grants ``people.read`` (nexfolk, V29): the persons in the answer of
        ``probe("people.read")`` (JSON of the answer)."""
        raise NotImplementedError("APP: people")

    def everything(self) -> str:
        """APP: all text the app keeps (its database as text), to look for tokens in it."""
        raise NotImplementedError("APP: everything")

    def own_tables(self) -> dict[str, Any]:
        """APP: the rows of the app's own tables of its earlier connections and keys (they stay untouched)."""
        raise NotImplementedError("APP: own_tables")

    #: APP: with ``older``: an API key of ``owner`` of the older version and a route it opens.
    older_key = ""
    older_key_path = ""


def package(adapter: StandardAdapter) -> ModuleType:
    return importlib.import_module(adapter.package)


class World:
    """The app and its partner, reaching each other through the module's stand-ins."""

    def __init__(self, pkg: ModuleType, app: StandardAdapter, partner: ReferenceApp) -> None:
        self.pkg = pkg
        self.app = app
        self.partner = partner
        self.down: set[str] = set()
        #: Every token that went from one app to the other (to look for them where they must not be).
        self.tokens: list[str] = []
        self._apps = {self.host(app.base): app.asgi(), self.host(partner.base): partner.api}
        self._kept: tuple[Any, Any] | None = None
        #: Since 0.1.8 (B2): hosts besides ``home.…`` whose name points into the own network.
        self.at_home: set[str] = set()

    @staticmethod
    def host(base: str) -> str:
        return urlsplit(base).netloc

    def install(self) -> None:
        reach = self.pkg.reach
        self._kept = (reach.TRANSPORT, reach.RESOLVER)
        reach.TRANSPORT = httpx.MockTransport(self._handle)
        reach.RESOLVER = lambda host, port: [HOME if host.startswith("home.") or host in self.at_home else PUBLIC]
        self.pkg.connect.BRAKE.forget()

    def uninstall(self) -> None:
        if self._kept is not None:
            self.pkg.reach.TRANSPORT, self.pkg.reach.RESOLVER = self._kept

    def _handle(self, request: httpx.Request) -> httpx.Response:
        host = request.headers.get("host", "")
        if host in self.down or host not in self._apps:
            raise httpx.ConnectError("down", request=request)
        body = request.content
        self._note(body.decode("utf-8", errors="replace"), form=True)
        headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
        with TestClient(self._apps[host], base_url=f"https://{host}") as client:
            answer = client.request(request.method, request.url.raw_path.decode("ascii"), headers=headers, content=body)
        self._note(answer.text, form=False)
        return httpx.Response(answer.status_code, headers=dict(answer.headers), content=answer.content)

    def _note(self, text: str, *, form: bool) -> None:
        found: dict[str, Any] = {}
        if form:
            found = {key: values[0] for key, values in parse_qs(text).items()}
        else:
            try:
                loaded = json.loads(text) if text else {}
                found = loaded if isinstance(loaded, dict) else {}
            except ValueError:
                return
        for name in ("access_token", "refresh_token", "reverse_access", "reverse_refresh", "code"):
            value = found.get(name)
            if isinstance(value, str) and len(value) > 20 and value not in self.tokens:
                self.tokens.append(value)

    def program(self) -> TestClient:
        """A client as another app or a program calls: no session, none of the app's own headers (a tab guard of the
        app must let programs through on the module's routes between the apps)."""
        return TestClient(self.app.asgi(), base_url=self.app.base)

    # --- sides ------------------------------------------------------------------------------------------------------

    def side(self, which: str) -> tuple[Any, str, str]:
        """(a client maker, own name, own base) of ``app`` or ``partner``."""
        if which == "app":
            return self.app.client, self.app.config().app_name, self.app.base
        return self.partner.client, self.partner.name, self.partner.base

    def other(self, which: str) -> str:
        return "partner" if which == "app" else "app"

    # --- connecting -------------------------------------------------------------------------------------------------

    def start(self, which: str = "app", role: str = "owner", **body: Any) -> Any:
        """"Mit <other> verbinden" on ``which``; since 0.1.8 (V42) at the address the operator set (``world`` sets it
        on both sides), an ``address`` in ``body`` is not taken."""
        clients, _, _ = self.side(which)
        _, other_name, _ = self.side(self.other(which))
        return clients(role).post(f"{self.pkg.PREFIX}/partners/{other_name}/start", json=body)

    def set_address(self, which: str, address: str | None) -> None:
        """Since 0.1.8 (V42): the operator of ``which`` sets the address of the other app ("" or ``None``: none)."""
        _, other_name, _ = self.side(self.other(which))
        if which == "app":
            found = self.app.client("operator").put(
                f"{self.pkg.PREFIX}/admin", json={"addresses": {other_name: address or ""}}
            )
            assert found.status_code == 200, found.text
            return
        kept = self.partner.store.setting("addresses") or {}
        kept = {name: url for name, url in {**kept, other_name: address or ""}.items() if url}
        self.partner.store.set_setting("addresses", kept)
        self.partner.store.commit()

    def consent_params(self, go: str) -> dict[str, str]:
        return {key: values[0] for key, values in parse_qs(urlsplit(go).query).items()}

    def connect(self, which: str = "app", role: str = "owner", *, allow: bool = True, areas: Any = None) -> Any:
        """The whole way: start on ``which``, agree on the other side, come back. The answer of the return."""
        started = self.start(which, role)
        assert started.status_code == 200, started.text
        params = self.consent_params(started.json()["go"])
        clients, _, _ = self.side(self.other(which))
        info = clients(role).get(f"{self.pkg.PREFIX}/consent", params=params)
        assert info.status_code == 200, info.text
        agreed = clients(role).post(f"{self.pkg.PREFIX}/consent", json={**params, "allow": allow, "areas": areas})
        assert agreed.status_code == 200, agreed.text
        back = self.consent_params(agreed.json()["redirect"])
        own_clients, _, _ = self.side(which)
        return own_clients(role).post(f"{self.pkg.PREFIX}/return", json=back)

    def card(self, which: str, role: str = "owner") -> dict[str, Any]:
        clients, _, _ = self.side(which)
        _, other_name, _ = self.side(self.other(which))
        found = clients(role).get(f"{self.pkg.PREFIX}/partners")
        assert found.status_code == 200, found.text
        return next(view for view in found.json() if view["partner"] == other_name)

    def partner_connection(self, role: str = "owner") -> Any:
        from verbinden_partner import ROLES

        return self.partner.store.connection(ROLES[role][0], self.app.config().app_name)

    def partner_calls_app(self, path: Any, role: str = "owner") -> Any:
        """The partner asks the app with its connection (``connect.call``); the answer or the ``Refused``. ``path``: a
        route (GET) or ``(method, route, body)`` as the adapter's ``probe`` names it."""
        from datetime import UTC, datetime

        from verbinden_partner import ROLES

        method, route, body = ("GET", path, None) if isinstance(path, str) else path
        try:
            return self.pkg.call(
                self.partner.store,
                self.partner.config,
                ROLES[role][0],
                self.app.config().app_name,
                method,
                route,
                datetime.now(UTC),
                body=body,
            )
        except self.pkg.Refused as refusal:
            return refusal

    def expire_partner_access(self, role: str = "owner") -> None:
        """What the partner holds of the app runs out now: its next call refreshes first."""
        from dataclasses import replace
        from datetime import UTC, datetime, timedelta

        connection = self.partner_connection(role)
        held = json.loads(self.partner.store.unseal(connection.held))
        held["expires"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        self.partner.store.save(replace(connection, held=self.partner.store.seal(json.dumps(held))))
        self.partner.store.commit()

    def expire_partner_issued(self, role: str = "owner", *, idle_days: int = 0) -> None:
        """What the app holds of the partner runs out now (and, with ``idle_days``, was last used that long ago)."""
        from dataclasses import replace
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        connection = self.partner_connection(role)
        changed = replace(connection, issued_access_expires=now - timedelta(minutes=1))
        if idle_days:
            changed = replace(
                changed, used_at=now - timedelta(days=idle_days), created_at=now - timedelta(days=idle_days)
            )
        self.partner.store.save(changed)
        self.partner.store.commit()


def world(pkg: ModuleType, adapter: StandardAdapter, folder: Path, *, older: bool = False) -> Iterator[World]:
    (folder / "app").mkdir(parents=True, exist_ok=True)
    (folder / "partner").mkdir(parents=True, exist_ok=True)
    adapter.start(folder / "app", older=older)
    partner = ReferenceApp(pkg, adapter.partner, f"https://{adapter.partner}.example.com", folder / "partner")
    made = World(pkg, adapter, partner)
    made.install()
    # Since 0.1.8 (V42, B3): only the operator sets the other app up; here on both sides, as a server with both apps.
    made.set_address("app", partner.base)
    made.set_address("partner", adapter.base)
    try:
        yield made
    finally:
        made.uninstall()
        adapter.stop()
        partner.db.close()
