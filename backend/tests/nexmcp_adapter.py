"""nexmcp contract tests: nexpaper's adapter (copied once from the module's template, now nexpaper's file).

The contract tests in ``backend/tests/nexmcp/`` run the module inside nexpaper: its start, its sessions
(``tests/conftest.py`` empties the database before every test), the ``Store`` over ``mcp_keys`` and its neighbours
(``app/services/mcp_store.py``), nexpaper's tools over its documents, the module's routes (``/api/mcp``, ``/api/oauth``,
``/api/v1/connections/mcp``) and the key module's routes under ``/api/v1/connections``. nexpaper had no MCP before:
no form of key or program to keep, the switch off from the start. The operator can take AI from an account
("KI erlaubt"), so ``has_ai``.
"""

from __future__ import annotations

import secrets
from typing import Any

from mcp_contract import LegacyKey, LegacyProgram, StandardAdapter


class Adapter(StandardAdapter):
    package = "app.vendor.nexmcp"
    keys_prefix = "/api/v1/connections"
    prefix = "/api/v1/connections/mcp"
    has_ai = True
    older_had_mcp_on = False

    def start(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app
        from app.models import MEMBER, OPERATOR
        from tests.conftest import TAB, make_account
        from tests.papers import add_document, own_vault

        self._accounts = {
            "owner": make_account("owen", MEMBER, password=secrets.token_urlsafe(12)),
            "other": make_account("otto", MEMBER, password=secrets.token_urlsafe(12)),
            "operator": make_account("olli", OPERATOR, password=secrets.token_urlsafe(12)),
        }
        owner, other = self._accounts["owner"], self._accounts["other"]
        self._mine = add_document(own_vault(owner), owner, "Electricity October", sender="Example Power")
        self._theirs = add_document(own_vault(other), other, "Private letter")
        self._clients: dict[str, Any] = {}
        self._main = TestClient(app, base_url="http://testserver", headers=TAB)
        self._main.__enter__()

    def start_older(self) -> None:
        # nexpaper had no MCP before: a database of 1.12.0 is one without anything of it, as a fresh one.
        self.start()

    def stop(self) -> None:
        for client in self._clients.values():
            client.close()
        self._main.__exit__(None, None, None)

    def client(self, role: str) -> Any:
        from tests.conftest import new_client

        if role not in self._clients:
            self._clients[role] = new_client(None if role == "anonymous" else self._accounts[role])
        return self._clients[role]

    def config(self) -> Any:
        from app.services.mcp_store import MCP

        return MCP

    def keys_config(self) -> Any:
        from app.services.schluessel_store import CONFIG

        return CONFIG

    def read_call(self) -> tuple[str, dict[str, Any]]:
        return "read_document", {"document_id": self._mine}

    def change_call(self) -> tuple[str, dict[str, Any]]:
        return "set_document_fields", {"document_id": self._mine, "title": "From the program"}

    def foreign_call(self) -> tuple[str, dict[str, Any]]:
        return "read_document", {"document_id": self._theirs}

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


__all__ = ["Adapter", "LegacyKey", "LegacyProgram"]
