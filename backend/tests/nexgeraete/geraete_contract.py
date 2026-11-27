"""What the contract tests ask of an app: the ``StandardAdapter`` the app's adapter extends, and small helpers.

The contract tests run the module inside the app: the app's own start, its sessions and operators, its own ``Store``
over its own tables, its own device route (``GET /api/app/1/me``), the module's routers mounted from
``nexgeraete.api``. Above all they prove that **every device paired before the module still works** (``Bestand``), and
that **the published iPhone apps notice nothing** (``alte Form``). They never change; the app fills in its adapter
(``backend/tests/nexgeraete_adapter.py``).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from datetime import timedelta
from types import ModuleType
from typing import Any

#: The header of the apps built on NexKonto: the answer comes in the new form, and model, system and version are noted.
NEW = {"X-Nex-App": "sample-ios/2.1.0 (iPhone 16 Pro; iOS 18.1)"}


@dataclass(frozen=True)
class LegacyDevice:
    """A form of device the app paired before the module (each way, each table form)."""

    #: For the test's name ("QR code", "iCloud sibling", "with push ticket").
    label: str
    #: Whether the older version had a push ticket and key at it.
    push: bool = False


@dataclass
class Made:
    """A device written the old way: its key, and the private push key where it has a ticket."""

    token: str
    private_key: str | None = None
    ticket: str | None = None


@dataclass
class Relay:
    """The push relay as the tests see it: every post, and the status to answer per ticket (default 200)."""

    sent: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    answers: dict[str, int] = field(default_factory=dict)

    def __call__(self, url: str, body: dict[str, Any]) -> int:
        self.sent.append((url, body))
        return self.answers.get(str(body.get("ticket")), 200)

    def to(self, ticket: str) -> list[dict[str, Any]]:
        return [body for _, body in self.sent if body.get("ticket") == ticket]


class StandardAdapter:
    """Defaults; every method marked ``APP`` is the app's to write."""

    #: Where the vendored package lives in the app.
    package = "app.vendor.nexgeraete"
    #: Where the app mounts ``nexgeraete.api.app_router`` and ``browser_router``.
    app_prefix = "/api/app/1"
    browser_prefix = "/api"
    #: The relay recorder the app's ``send`` posts to (``Relay()``); set in ``start``.
    relay: Relay

    def start(self) -> None:
        """APP: an empty app (fresh database), started as in production, with three accounts: ``owner`` and
        ``other`` (members, no second factor) and ``operator``. The module's routers get ``send=self.relay`` and the
        app's clock, which ``travel`` moves on."""
        raise NotImplementedError("APP: start")

    def stop(self) -> None:
        """APP: close the database, remove temporary folders."""

    def restart(self) -> None:
        """APP: the same database in a newly started app (nothing kept in memory)."""
        raise NotImplementedError("APP: restart")

    def config(self) -> Any:
        """APP: the app's ``nexgeraete.AppConfig`` (the one its routers use)."""
        raise NotImplementedError("APP: config")

    def client(self, role: str) -> Any:
        """APP: a ``TestClient`` as ``"owner"``, ``"other"``, ``"operator"`` (a browser session), or ``"anonymous"``."""
        raise NotImplementedError("APP: client")

    def device_client(self) -> Any:
        """A ``TestClient`` without a session: what an iPhone app is."""
        return self.client("anonymous")

    def account_id(self, role: str) -> Any:
        """APP: the id of ``role``'s account."""
        raise NotImplementedError("APP: account_id")

    def legacy_devices(self) -> list[LegacyDevice]:
        """APP: every form of device the older version wrote (each way in, with and without a push ticket)."""
        raise NotImplementedError("APP: legacy_devices")

    def make_legacy(self, spec: LegacyDevice, *, account: str = "owner") -> Made:
        """APP: write a device of ``spec`` exactly the way the older version did (its service function, or the row as
        it wrote it: prefix, SHA-256 hex, its columns, the module's columns empty) and return its key."""
        raise NotImplementedError("APP: make_legacy")

    def probe(self, token: str | None, headers: dict[str, str] | None = None) -> Any:
        """APP: present ``token`` to a real device route of the app (``GET /api/app/1/me`` or what it has) and return
        the answer."""
        raise NotImplementedError("APP: probe")

    def database_text(self) -> bytes:
        """APP: every byte the app keeps about devices (its database file), to prove no key is stored."""
        raise NotImplementedError("APP: database_text")

    def block(self, account: str = "owner") -> None:
        """APP: the operator blocks ``account`` the app's way (``konten`` ``block``)."""
        raise NotImplementedError("APP: block")

    def unblock(self, account: str = "owner") -> None:
        raise NotImplementedError("APP: unblock")

    def remove(self, account: str = "owner") -> None:
        """APP: ``account`` is deleted and may be restored within 30 days."""
        raise NotImplementedError("APP: remove")

    def restore(self, account: str = "owner") -> None:
        raise NotImplementedError("APP: restore")

    def purge(self, account: str = "owner") -> None:
        """APP: ``account`` is deleted for good."""
        raise NotImplementedError("APP: purge")

    def owe_factor(self, account: str = "owner") -> None:
        """APP: the operator requires a second factor; ``account`` has none."""
        raise NotImplementedError("APP: owe_factor")

    def switch(self, name: str, on: bool) -> None:
        """APP: the operator's switch ``app`` or ``pairing`` (Server › Verbindungen), as the app stores it."""
        raise NotImplementedError("APP: switch")

    def travel(self, delta: timedelta) -> None:
        """APP: the app's clock moves on by ``delta``."""
        raise NotImplementedError("APP: travel")

    def tell(self, account: str, kind: str) -> None:
        """APP: the app sends a message of its own ``kind`` to ``account`` (its event, or ``nexgeraete.push.tell``)."""
        raise NotImplementedError("APP: tell")

    def announce(self, version: str) -> None:
        """APP: ``updates`` found ``version`` (``on_newer``; the app hands it to ``nexgeraete.notices.newer``)."""
        raise NotImplementedError("APP: announce")

    def sweep(self) -> int:
        """APP: the app's daily run (``nexgeraete.devices.sweep``)."""
        raise NotImplementedError("APP: sweep")

    def paired_mails(self) -> list[tuple[Any, str]]:
        """APP: what the hook ``on_paired`` was given so far (account id, device name): the mail "Neue Anmeldung"."""
        raise NotImplementedError("APP: paired_mails")


def package(adapter: Any) -> ModuleType:
    found = importlib.import_module(adapter.package)
    importlib.import_module(f"{adapter.package}.api")
    return found


def code_of(answer: Any) -> str:
    """The code of a refusal in any form: ``detail.code`` or, nexmail, ``detail`` itself."""
    detail = answer.json().get("detail")
    return detail if isinstance(detail, str) else str(detail.get("code"))


def auth(token: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **(NEW if extra is None else extra)}


def start_pairing(app: Any, role: str = "owner") -> dict[str, Any]:
    answer = app.client(role).post(f"{app.browser_prefix}/app-pairing", json={})
    assert answer.status_code == 201, answer.text
    return answer.json()


def pick_up(app: Any, started: dict[str, Any], *, name: str = "Kim's iPhone", kind: str = "ios",
            headers: dict[str, str] | None = None) -> Any:
    return app.device_client().post(
        f"{app.app_prefix}/pairing/{started['id']}/key",
        json={"secret": started["secret"], "device_name": name, "device_kind": kind},
        headers=NEW if headers is None else headers,
    )


def new_device(app: Any, role: str = "owner", *, name: str = "Kim's iPhone") -> str:
    """A device paired with the QR code by a new app; its key."""
    answer = pick_up(app, start_pairing(app, role), name=name)
    assert answer.status_code == 200, answer.text
    return str(answer.json()["token"])


def listed(app: Any, role: str = "owner") -> list[dict[str, Any]]:
    answer = app.client(role).get(f"{app.browser_prefix}/app-devices")
    assert answer.status_code == 200, answer.text
    return list(answer.json()["devices"])


def sign_up_push(app: Any, token: str, *, understands: list[str] | None = None,
                 ticket: str = "ticket-one") -> str:
    """The device signs up for notifications with a fresh key pair; returns its private key."""
    seal = importlib.import_module(f"{app.package}.seal")
    private, public = seal.key_pair()
    body: dict[str, Any] = {"ticket": ticket, "key": public}
    if understands is not None:
        body["understands"] = understands
    answer = app.device_client().put(f"{app.app_prefix}/push", json=body, headers=auth(token))
    assert answer.status_code == 204, answer.text
    return str(private)


def ok(status: int) -> bool:
    return 200 <= status < 300
