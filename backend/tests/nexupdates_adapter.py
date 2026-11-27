"""nexupdates contract tests: nexpaper's adapter (copied once from the module's template, now nexpaper's file).

The contract tests in ``backend/tests/nexupdates/`` run the module inside nexpaper: its start
(``app/services/updates.py`` configures the module on the settings table, key ``update_check``), its sessions
(``tests/conftest.py`` empties the database before every test), its checks of accounts and operators, the routes under
``/api/v1/about`` (``app/routers/about.py``) and its setup route ``POST /api/v1/setup`` with the box "Nach neuen
Versionen sehen".

nexpaper has no bell of its own (``has_bell = False``, U19); it pairs devices (module geraete, ``has_devices = True``):
a device of an operator that understands and wants the kind ``update`` counts as a bell (U24, G56), so only then does
the background look, at most once a day. ``want_on_device`` pairs such an iPhone for the operator in the module's store
and switches the kind; the relay is a recorder (``geraete_store.SEND``), and what it got is unsealed with the device's
key (``devices_told``).
"""

from __future__ import annotations

import json
import secrets
from typing import Any

from updates_contract import StandardAdapter


class Adapter(StandardAdapter):
    package = "app.vendor.nexupdates"
    prefix = "/api/v1/about"
    also: tuple[str, ...] = ()
    has_bell = False
    has_devices = True

    def start(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app
        from app.services import geraete_store
        from tests.conftest import TAB

        self._clients: dict[str, Any] = {}
        self._phone: tuple[Any, str] | None = None
        self.relayed: list[dict[str, Any]] = []
        geraete_store.SEND = lambda _url, body: self.relayed.append(body) or 200
        self._main = TestClient(app, base_url="http://testserver", headers=TAB)
        self._main.__enter__()
        self.restart()

    def stop(self) -> None:
        from app.services import geraete_store

        for client in self._clients.values():
            client.close()
        self._main.__exit__(None, None, None)
        geraete_store.SEND = None

    def restart(self) -> None:
        from app.services import updates

        # nexpaper's start configures the module on its settings (at import, as in production).
        updates.configure()

    def want_on_device(self, on: bool) -> None:
        """The operator's iPhone, paired once and signed up for ``update``; the kind switched on or off."""
        from app.db import SessionLocal
        from app.services import geraete_store
        from app.vendor import nexgeraete
        from app.vendor.nexgeraete import seal

        operator = self._account("operator")
        with SessionLocal() as db:
            store = geraete_store.GeraeteStore(db)
            if self._phone is None:
                holder = store.holder(operator.id)
                assert holder is not None
                device, _key = nexgeraete.devices.add(store, geraete_store.CONFIG, holder, name="Ollis iPhone",
                                                      kind="ios", via=nexgeraete.VIA_QR)
                private, public = seal.key_pair()
                store.set_push(device.id, nexgeraete.PushState("olli-phone", public, ("update",)))
                self._phone = (device.id, private)
            store.set_kinds(self._phone[0], {"update": on})
            store.commit()

    def devices_told(self) -> list[str]:
        """The versions the relay carried to the operator's iPhone, unsealed with its key."""
        from app.services import geraete_store
        from app.vendor.nexgeraete import seal

        if self._phone is None:
            return []
        told = []
        for body in self.relayed:
            message = json.loads(seal.unseal(body["enc"], self._phone[1], geraete_store.CONFIG.push_info))
            if message.get("type") == "update":
                told.append("v" + str(message["version"]))
        return told

    def _account(self, role: str) -> Any:
        """The operator set up at ``setup`` when there is one, else made now; a member made now."""
        from app.db import SessionLocal
        from app.models import MEMBER, OPERATOR, Account
        from tests.conftest import make_account

        wanted = OPERATOR if role == "operator" else MEMBER
        with SessionLocal() as db:
            found = db.query(Account).filter_by(role=wanted).order_by(Account.id).first()
            if found is not None:
                db.expunge(found)
                return found
        return make_account("olli" if role == "operator" else "mia", wanted, password=secrets.token_urlsafe(12))

    def client(self, role: str) -> Any:
        from tests.conftest import new_client

        if role not in self._clients:
            self._clients[role] = new_client(None if role == "anonymous" else self._account(role))
        return self._clients[role]

    def stored_switch(self) -> Any:
        from app.db import SessionLocal
        from app.models import Setting

        with SessionLocal() as db:
            row = db.get(Setting, "update_check")
            return None if row is None else row.value

    def store_legacy_switch(self, on: bool) -> None:
        """As nexpaper 1.12.0 wrote it: the settings table, key ``update_check``, a JSON boolean."""
        from app.db import SessionLocal
        from app.services import settings_service

        with SessionLocal() as db:
            settings_service.save(db, {"update_check": on})

    def setup(self, on: bool) -> None:
        from tests.conftest import PASSWORD, SETUP_CODE, new_client

        with new_client() as browser:
            answer = browser.post("/api/v1/setup", json={
                "code": SETUP_CODE, "name": "olga", "password": PASSWORD, "language": "de", "update_check": on,
            })
        assert answer.status_code == 200, answer.text
