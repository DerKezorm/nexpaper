"""nexki contract tests: nexpaper's adapter (copied once from the module's template, now nexpaper's file).

The contract tests in ``backend/tests/nexki/`` run the module inside nexpaper: its start (``main._adopt_ai`` runs
``nexki.settings.adopt``), its sessions (``tests/conftest.py`` empties the database before every test), the store over
its settings and tables (``services/ki_store.py`` in ``services/mcp_store.McpStore``) and the module's routes under
``/api/v1/server/ai`` and ``/api/v1/me/ai``.

nexpaper has no button task: its only AI task, ``propose``, runs in the background for a new document
(``services/ai_proposals.py``). ``automatic`` is that task's request (``ai_proposals.ask``, as the job makes it).
``manual`` is skipped: the contract has no form for an app without a button task (``einst-fragen/
nexpaper-module.md``); nexpaper's own tests hold the chain, the network, the day's limit and the Bestand of its form
through the task and the older routes (``test_ai.py``, ``test_ai_proposals.py``, ``test_ki.py``).
"""

from __future__ import annotations

import secrets
import sqlite3
from datetime import UTC, datetime
from typing import Any

import pytest
from ki_contract import StandardAdapter


class Adapter(StandardAdapter):
    package = "app.vendor.nexki"
    server_prefix = "/api/v1/server/ai"
    me_prefix = "/api/v1/me/ai"
    older_forms: tuple[str, ...] = ("shared",)

    def _accounts_made(self) -> None:
        from app.models import MEMBER, OPERATOR
        from tests.conftest import make_account

        self._accounts = {
            "owner": make_account("owen", MEMBER, password=secrets.token_urlsafe(12)),
            "other": make_account("otto", MEMBER, password=secrets.token_urlsafe(12)),
            "operator": make_account("olli", OPERATOR, password=secrets.token_urlsafe(12)),
        }

    def _started(self) -> None:
        from fastapi.testclient import TestClient

        from app.db import SessionLocal
        from app.main import app
        from app.services import ai
        from tests.conftest import TAB

        self._clients: dict[str, Any] = {}
        self._sessions: list[Any] = []
        # nexpaper's start: ``adopt`` runs in the lifespan.
        self._main = TestClient(app, base_url="http://testserver", headers=TAB)
        self._main.__enter__()
        ai.forget()
        self._session = SessionLocal

    def start(self) -> None:
        self._accounts_made()
        self._started()

    def start_older(self, form: str, base: str, key: str) -> None:
        """As nexpaper 1.12.0 wrote it: the operator's service ``local`` at ``base``, model ``plain``, the key sealed in
        ``operator:ai-key``; no main switch, no way stored."""
        from app.db import SessionLocal
        from app.security import encrypt_secret
        from app.services import settings_service

        assert form == "shared"
        self._accounts_made()
        with SessionLocal() as db:
            settings_service.save(db, {"ai_provider": "local", "ai_url": base, "ai_model": "plain",
                                       "ai_key_enc": encrypt_secret(key, "operator:ai-key")})
        self._started()

    def stop(self) -> None:
        for client in self._clients.values():
            client.close()
        for session in self._sessions:
            session.close()
        self._main.__exit__(None, None, None)

    def client(self, role: str) -> Any:
        from tests.conftest import new_client

        if role not in self._clients:
            self._clients[role] = new_client(None if role == "anonymous" else self._accounts[role])
        return self._clients[role]

    def config(self) -> Any:
        from app.services.ki_store import CONFIG

        return CONFIG

    def store(self) -> Any:
        from app.services.mcp_store import McpStore

        session = self._session()
        self._sessions.append(session)
        return McpStore(session)

    def account_id(self, role: str) -> Any:
        return self._accounts[role].id

    def manual(self, role: str, text: str) -> Any:
        pytest.skip("nexpaper has no button task: its only AI task (propose) runs in the background")

    def automatic(self, role: str, text: str) -> Any:
        from app.services import ai_proposals

        mark = "DOC-" + secrets.token_hex(8)
        return ai_proposals.ask(self.account_id(role), text, ["Invoice", "Contract"], "", mark)

    def _set(self, role: str, **values: Any) -> None:
        from app.db import SessionLocal
        from app.models import Account

        with SessionLocal() as db:
            row = db.get(Account, self.account_id(role))
            assert row is not None
            for name, value in values.items():
                setattr(row, name, value)
            db.commit()

    def take_ai(self, role: str) -> None:
        self._set(role, ai_allowed=False)

    def give_ai(self, role: str) -> None:
        self._set(role, ai_allowed=True)

    def shut_out(self, role: str) -> None:
        self._set(role, blocked_at=datetime.now(UTC))

    def let_in(self, role: str) -> None:
        self._set(role, blocked_at=None)

    def dump(self) -> str:
        from app.config import get_settings

        with sqlite3.connect(get_settings().database_path) as plain:
            return "\n".join(plain.iterdump())


__all__ = ["Adapter"]
