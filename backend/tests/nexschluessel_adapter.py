"""nexschluessel contract tests: nexpaper's adapter (copied once from the module's template, now nexpaper's file).

The contract tests in ``backend/tests/nexschluessel/`` run the module against nexpaper's real start, its sessions
(``tests/conftest.py`` empties the database before every test), its ``Store`` over ``api_keys``
(``app/services/schluessel_store.py``), the module's routes under ``/api/v1/connections`` and nexpaper's own route for
programs, ``GET /api/v1/me``. ``legacy_keys`` names every form of key nexpaper handed out before the module: a key for
reading (a dashboard card, a script), one for uploading (a scanner) and the iPhone shortcut's key (uploading, no end),
all ``npk_``, all made by ``services/apikeys.make`` as nexpaper made them since 1.0.0. Since mcp 1.1.0 the second
kind ``mcp`` (MCP keys ``npm_`` in ``mcp_keys``, limited to vaults where the owner wants), presented at ``POST
/api/mcp``; the operator can take AI from an account (``has_ai``).
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from schluessel_contract import LegacyKey, StandardAdapter


class Adapter(StandardAdapter):
    package = "app.vendor.nexschluessel"
    prefix = "/api/v1/connections"
    has_ai = True

    def start(self) -> None:
        from fastapi.testclient import TestClient

        from app.db import SessionLocal
        from app.main import app
        from app.models import MEMBER, OPERATOR
        from app.services import settings_service
        from tests.conftest import TAB, make_account

        self._accounts = {
            "owner": make_account("owen", MEMBER, password=secrets.token_urlsafe(12)),
            "other": make_account("otto", MEMBER, password=secrets.token_urlsafe(12)),
            "operator": make_account("olli", OPERATOR, password=secrets.token_urlsafe(12)),
        }
        # The interface and MCP are off in a new nexpaper; the operator opened them (the tests switch them off themselves).
        with SessionLocal() as db:
            settings_service.save(db, {"api_keys_allowed": True, "mcp_enabled": True})
        self._clients: dict[str, Any] = {}
        self._main = TestClient(app, base_url="http://testserver", headers=TAB)
        self._main.__enter__()

    def stop(self) -> None:
        for client in self._clients.values():
            client.close()
        self._main.__exit__(None, None, None)

    def config(self) -> Any:
        from app.services.schluessel_store import CONFIG

        return CONFIG

    def client(self, role: str) -> Any:
        from tests.conftest import new_client

        if role not in self._clients:
            self._clients[role] = new_client(None if role == "anonymous" else self._accounts[role])
        return self._clients[role]

    def legacy_keys(self) -> list[LegacyKey]:
        return [
            LegacyKey("API key for reading", "api", "npk_", "read"),
            LegacyKey("API key for uploading", "api", "npk_", "upload"),
            LegacyKey("iPhone shortcut key", "api", "npk_", "upload"),
        ]

    def make_legacy(self, spec: LegacyKey, *, account: str = "owner", expired: bool = False) -> str:
        """As nexpaper's ``apikeys.make`` wrote them; the shortcut's card made its key the same way (``upload``,
        never runs out, named "iPhone-Kurzbefehl")."""
        from app.db import SessionLocal
        from app.models import Account, ApiKey, utcnow
        from app.services import apikeys

        shortcut = spec.label.startswith("iPhone")
        name = "iPhone-Kurzbefehl" if shortcut else spec.label
        days = None if shortcut or spec.right == "upload" else 365
        with SessionLocal() as db:
            row = db.get(Account, self._accounts[account].id)
            assert row is not None
            key, secret = apikeys.make(db, row, name, spec.right, days)
            if expired:
                stored = db.get(ApiKey, key.id)
                assert stored is not None
                stored.expires_at = utcnow() - timedelta(hours=1)
                db.commit()
        return secret

    def probe(self, kind: str, secret: str) -> int:
        from app.services import apikeys
        from app.vendor.nexmcp.brake import BRAKE

        if kind == "mcp":
            BRAKE.forget()
            answer = self.client("anonymous").post(
                "/api/mcp", headers={"Authorization": f"Bearer {secret}"},
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
            return answer.status_code
        # The brake of 120 requests a minute per key is nexpaper's own and stays; the tests ask far less.
        apikeys.forget()
        answer = self.client("anonymous").get("/api/v1/me", headers={"Authorization": f"Bearer {secret}"})
        return answer.status_code

    def owe_factor(self) -> None:
        """The operator requires a second factor and the owner, who has a password, has none. Its browser still reaches
        its keys (``deps.KEYS_WHILE_OWED``): it may make them, they rest until the factor is there."""
        from tests.conftest import require_second_factor

        require_second_factor(True)

    def foreign_area(self) -> Any:
        """The personal vault of ``other``: an MCP key of the owner can never be limited to it."""
        from tests.papers import own_vault

        return own_vault(self._accounts["other"])

    def _ai(self, account: str, on: bool) -> None:
        from app.db import SessionLocal
        from app.models import Account

        with SessionLocal() as db:
            row = db.get(Account, self._accounts[account].id)
            assert row is not None
            row.ai_allowed = on
            db.commit()

    def take_ai(self, account: str = "owner") -> None:
        self._ai(account, False)

    def give_ai(self, account: str = "owner") -> None:
        self._ai(account, True)
