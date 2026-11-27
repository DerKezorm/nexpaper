"""nexverbinden contract tests: nexpaper's adapter (copied once from the module's template, now nexpaper's file).

The contract tests in ``backend/tests/nexverbinden/`` run the module inside nexpaper with nextime as its partner
(nextime reads nexpaper's deadlines, ``deadlines.read``; nexpaper uses nothing of nextime). nexpaper starts on the
database of the test run (``tests/conftest.py`` empties it before every test), its public address set to ``base``; the
owner has deadlines in two vaults (its own and a shared one). The older version had no connection of its own: its way
in was an API key of the owner (``npk_``), which keeps opening ``/api/v1/me``.
"""

from __future__ import annotations

import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from verbinden_contract import StandardAdapter


class Adapter(StandardAdapter):
    package = "app.vendor.nexverbinden"
    partner = "nextime"
    base = "https://paper.example.com"
    older_link = False
    #: verbinden 0.1.8 (B1): the consent page names the account with its display name beside the name it signs in with.
    shown_names = {"owner": "Kim Example", "other": "Sam Example"}  # noqa: RUF012 (read only)
    #: verbinden 0.1.13: nexfolk asks how many documents are from a contact (``services/person_documents.py``).
    about_purpose = "documents.about"

    def start(self, folder: Path, *, older: bool = False) -> None:
        from app.db import SessionLocal
        from app.models import MEMBER, OPERATOR
        from app.services import apikeys, settings_service, verbinden_store
        from tests.conftest import TAB, make_account
        from tests.papers import add_document, own_vault, shared_vault

        self._accounts = {
            "owner": make_account("kim", MEMBER, password=secrets.token_urlsafe(12)),
            "other": make_account("sam", MEMBER, password=secrets.token_urlsafe(12)),
            "operator": make_account("op", OPERATOR, password=secrets.token_urlsafe(12)),
        }
        owner = self._accounts["owner"]
        with SessionLocal() as db:
            for role, shown in self.shown_names.items():
                row = db.get(type(owner), self._accounts[role].id)
                row.display_name = shown
            db.commit()
        due = datetime.now(UTC).date() + timedelta(days=5)
        office = shared_vault("Office", self._accounts["operator"], (owner, "edit"))
        add_document(own_vault(owner), owner, "Electricity", dates=[("due", due)])
        add_document(office, owner, "Rent", dates=[("due", due)])
        with SessionLocal() as db:
            settings_service.save(db, {"public_url": self.base})
            if older:
                # As 1.12.0 left it: the owner's key for a program, the interface switched on by the operator.
                settings_service.save(db, {"api_keys_allowed": True})
                row = db.get(type(owner), owner.id)
                _key, self.older_key = apikeys.make(db, row, "Calendar", "read", 90)
                self.older_key_path = "/api/v1/me"
        # Every end of a connection as nexpaper's hook hears it (verbinden 0.1.4, ``disconnected``).
        self._ended: list[tuple[Any, str]] = []
        self._hook = verbinden_store.on_disconnected

        def heard(store: Any, account_id: Any, partner: str) -> None:
            self._ended.append((account_id, partner))
            self._hook(store, account_id, partner)

        verbinden_store.on_disconnected = heard  # type: ignore[assignment]
        self._session = SessionLocal()
        self.store = verbinden_store.VerbindenStore(self._session)
        self._clients: dict[str | None, TestClient] = {}
        self._tab = TAB

    def stop(self) -> None:
        from app.services import verbinden_store

        verbinden_store.on_disconnected = self._hook  # type: ignore[assignment]
        for client in self._clients.values():
            client.close()
        self._session.close()

    def disconnected(self) -> list[tuple[Any, str]]:
        return list(self._ended)

    def asgi(self) -> Any:
        from app.main import app

        return app

    def client(self, role: str | None) -> TestClient:
        from tests.conftest import sign_in

        if role not in self._clients:
            browser = TestClient(self.asgi(), base_url=self.base, headers=self._tab)
            if role is not None:
                sign_in(browser, self._accounts[role])
            self._clients[role] = browser
        return self._clients[role]

    def config(self) -> Any:
        from app.services.verbinden_store import CONFIG

        return CONFIG

    def account_id(self, role: str) -> Any:
        return self._accounts[role].id

    def block(self, role: str, blocked: bool = True) -> None:
        from app.db import SessionLocal
        from app.models import Account

        with SessionLocal() as db:
            row = db.get(Account, self._accounts[role].id)
            assert row is not None
            row.blocked_at = datetime.now(UTC) if blocked else None
            db.commit()

    def lock(self, role: str, locked: bool = True) -> None:
        """verbinden 0.2.1: locked for a while after failed sign-ins, as the sign-in brake leaves it."""
        from app.db import SessionLocal
        from app.models import Account

        with SessionLocal() as db:
            row = db.get(Account, self._accounts[role].id)
            assert row is not None
            row.locked_until = datetime.now(UTC) + timedelta(minutes=15) if locked else None
            db.commit()

    def require_second_factor(self, role: str, required: bool = True) -> None:
        """verbinden 0.2.1: the operator requires a second factor; ``role`` (with a password) has none yet."""
        from tests.conftest import require_second_factor

        require_second_factor(required)

    def about_seed(self, purpose: str, area: Any, person: Any) -> None:
        """A filed document of the owner in the vault ``area`` whose sender is the person (by name)."""
        from tests.papers import add_document

        assert purpose == self.about_purpose
        add_document(int(str(area)), self._accounts["owner"], "Letter", sender=person.name,
                     date=datetime.now(UTC).date())

    def probe(self, purpose: str) -> str | None:
        return {"deadlines.read": "/api/v1/deadlines", "documents.add": "/api/v1/vaults",
                # verbinden 0.1.13: the module's fixed place for a purpose about a person (nexfolk's only).
                "documents.about": "/api/connect/about/documents.about?name=Pat%20Example"}.get(purpose)

    def areas_seen(self, purpose: str, answer: Any) -> set[str]:
        if purpose == "documents.add":
            return {str(vault["id"]) for vault in answer}
        return {str(item["vault_id"]) for part in ("overdue", "soon", "later") for item in answer[part]["items"]}

    def everything(self) -> str:
        from app.config import get_settings

        self._session.commit()
        with sqlite3.connect(get_settings().database_path) as plain:
            return "\n".join(plain.iterdump())

    def own_tables(self) -> dict[str, Any]:
        from app.config import get_settings

        with sqlite3.connect(get_settings().database_path) as plain:
            return {"api_keys": [tuple(row) for row in plain.execute(
                "SELECT id, account_id, name, scope, token_hash, prefix, expires_at, blocked_at FROM api_keys")]}
