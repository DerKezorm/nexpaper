"""nexupdates contract tests: nexpaper's adapter (copied once from the module's template, now nexpaper's file).

The contract tests in ``backend/tests/nexupdates/`` run the module inside nexpaper: its start
(``app/services/updates.py`` configures the module on the settings table, key ``update_check``), its sessions
(``tests/conftest.py`` empties the database before every test), its checks of accounts and operators, the routes under
``/api/v1/about`` (``app/routers/about.py``) and its setup route ``POST /api/v1/setup`` with the box "Nach neuen
Versionen sehen".

nexpaper has no bell of its own; since geraete 0.1.0 (G18) the operators' devices are told once about a new version
(``on_newer`` → ``geraete_store.announce``), so the background looks once a day while the switch is on, and the
contract (updates 0.1.2) checks that as the bell (``has_bell = True``). ``bell`` is every version handed to
``on_newer``; ``bell_notices`` the title each operator's devices get, in the language of the account.
"""

from __future__ import annotations

import secrets
from typing import Any

from updates_contract import StandardAdapter


class Adapter(StandardAdapter):
    package = "app.vendor.nexupdates"
    prefix = "/api/v1/about"
    also: tuple[str, ...] = ()
    has_bell = True

    def start(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app
        from tests.conftest import TAB

        self._clients: dict[str, Any] = {}
        self._main = TestClient(app, base_url="http://testserver", headers=TAB)
        self._main.__enter__()
        self.restart()

    def stop(self) -> None:
        for client in self._clients.values():
            client.close()
        self._main.__exit__(None, None, None)
        if hasattr(self, "_on_newer"):
            from app.services import updates

            updates._on_newer = self._on_newer  # type: ignore[assignment]

    def restart(self) -> None:
        from app.services import updates

        # nexpaper's start configures the module on its settings (at import, as in production).
        updates.configure()
        if not hasattr(self, "_told"):
            self._told: list[str] = []
            self._on_newer = updates._on_newer

            def recorded(version: str) -> None:
                self._told.append(version)
                self._on_newer(version)

            updates._on_newer = recorded  # type: ignore[assignment]

    def bell(self) -> list[str]:
        return list(self._told)

    def bell_notices(self) -> list[tuple[str, str, str]]:
        """What each operator's devices got as the title (``nexgeraete.notices.newer``), per version told."""
        from app.db import SessionLocal
        from app.services import geraete_store
        from app.vendor.nexgeraete import notices

        found = []
        with SessionLocal() as db:
            data = geraete_store.GeraeteStore(db)
            for account in data.operators():
                holder = data.holder(account)
                assert holder is not None
                for version in self._told:
                    title = notices.words(holder.language)["update_title"].format(
                        app=geraete_store.CONFIG.app, version=version.strip().removeprefix("v"))
                    found.append((holder.language, version, title))
        return found

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
