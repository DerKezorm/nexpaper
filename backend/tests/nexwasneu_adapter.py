"""nexwasneu contract tests: nexpaper's adapter (copied once from the module's template, now nexpaper's file).

The contract tests in ``backend/tests/nexwasneu/`` run the module inside nexpaper: its configuration in ``main.py``
(texts in ``backend/app/whatsnew/``, German, English and French), its routes under ``/api/v1/whats-new`` with
nexpaper's sessions (``deps.whats_new_viewer``), the route of before ``POST /api/v1/me/whats-new/seen`` and the field
``whats_new_seen`` in ``/api/v1/auth/me``. The database is the one of the test session (``tests/conftest.py`` empties it before every test);
the operator and the member are made when a test asks for a client.
"""

from __future__ import annotations

import itertools
from typing import Any

from wasneu_contract import StandardAdapter

NAMES = {"operator": "tester", "member": "member"}
_new = itertools.count()


class Adapter(StandardAdapter):
    package = "app.vendor.nexwasneu"
    root_package = "app"
    prefix = "/api/v1/whats-new"
    old_seen: tuple[str, ...] = ("/api/v1/me/whats-new/seen",)
    me = "/api/v1/auth/me"
    me_field = "whats_new_seen"

    def start(self) -> None:
        self._clients: list[Any] = []

    def stop(self) -> None:
        for client in self._clients:
            client.close()

    def _account(self, role: str) -> Any:
        from app.db import SessionLocal
        from app.models import MEMBER, OPERATOR, Account
        from tests.conftest import make_account

        with SessionLocal() as db:
            row = db.query(Account).filter_by(name=NAMES[role]).one_or_none()
            if row is not None:
                db.expunge(row)
        return row if row is not None else make_account(NAMES[role], OPERATOR if role == "operator" else MEMBER)

    def client(self, role: str) -> Any:
        from tests.conftest import new_client

        client = new_client(None if role == "anonymous" else self._account(role))
        self._clients.append(client)
        return client

    def stored_seen(self, role: str) -> str:
        from app.db import SessionLocal
        from app.models import Account

        with SessionLocal() as db:
            row = db.get(Account, self._account(role).id)
            assert row is not None
            return row.whats_new_seen or ""

    def set_seen(self, role: str, version: str) -> None:
        from app.db import SessionLocal
        from app.models import Account

        with SessionLocal() as db:
            row = db.get(Account, self._account(role).id)
            assert row is not None
            row.whats_new_seen = version
            db.commit()

    def new_account_seen(self) -> str:
        """As setup and invitations make an account (``KontenStore.add_account``)."""
        from app.db import SessionLocal
        from app.models import Account
        from app.services.konten_store import KontenStore
        from app.vendor.nexkonten import NewAccount

        name = f"new{next(_new)}"
        with SessionLocal() as db:
            KontenStore(db).add_account(NewAccount(username=name, display_name="", email="", email_confirmed=False,
                                                   password="a long enough password"))
            db.commit()
            row = db.query(Account).filter_by(name=name).one()
            return row.whats_new_seen
