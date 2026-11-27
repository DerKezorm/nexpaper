"""nexgeraete contract tests: nexpaper's adapter (copied once from the module's template, now nexpaper's file).

The contract tests in ``backend/tests/nexgeraete/`` run the module inside nexpaper: its start, its sessions
(``tests/conftest.py`` empties the database before every test), its ``Store`` over ``devices`` and ``pairings``
(``app/services/geraete_store.py``), its own device route ``GET /api/app/1/me`` (``app/routers/app_devices.py``), the
module's routers under ``/api/app/1`` and ``/api/v1`` (``app/main.py``), and the accounts' ways through the shared
account module (block, delete, bring back, purge).

``legacy_devices`` are the four ways nexpaper paired a device before the module (1.3.0 to 1.12.0), written as those
versions wrote them: a token made in the browser (``via = token``), a QR code (``qr``), an app over OAuth
(``app:nexpaper-mobile``) and the iPad brought in over iCloud (``device``); none had a push ticket (nexpaper sent
nothing through the relay). The relay is a recorder (``geraete_store.SEND``), nexpaper's clock moves (``app.clock``).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from pathlib import Path
from typing import Any

from geraete_contract import LegacyDevice, Made, Relay, StandardAdapter

#: The ways of before and what they wrote into ``devices.via``.
LEGACY = {
    "token made in the browser": "token",
    "QR code": "qr",
    "app over OAuth": "app:nexpaper-mobile",
    "iPad brought in over iCloud": "device",
}
ROLES = {"owner": ("kim", "member"), "other": ("mila", "member"), "operator": ("olli", "operator")}


class Adapter(StandardAdapter):
    package = "app.vendor.nexgeraete"
    app_prefix = "/api/app/1"
    browser_prefix = "/api/v1"

    def start(self) -> None:
        from app import clock
        from app.services import geraete_store
        from app.vendor.nexkonten.brake import BRAKE
        from tests.conftest import make_account

        self.relay = Relay()
        geraete_store.SEND = self.relay
        self.clients: dict[str, Any] = {}
        self.ids: dict[str, int] = {}
        for role, (name, kind) in ROLES.items():
            self.ids[role] = make_account(name, kind).id
        self.offset = timedelta(0)
        self._now = clock.now
        clock.now = lambda: self._now() + self.offset  # type: ignore[assignment]
        self.paired: list[tuple[Any, str]] = []
        self._on_paired = geraete_store.on_paired

        def recorded(holder: Any, device: Any) -> None:
            self.paired.append((holder.id, device.name))
            self._on_paired(holder, device)

        geraete_store.on_paired = recorded  # type: ignore[assignment]
        BRAKE.forget()

    def stop(self) -> None:
        from app import clock
        from app.services import geraete_store

        for client in self.clients.values():
            client.close()
        clock.now = self._now  # type: ignore[assignment]
        geraete_store.SEND = None
        geraete_store.on_paired = self._on_paired  # type: ignore[assignment]

    def restart(self) -> None:
        """nexpaper keeps nothing of devices in memory; new clients, the same database."""
        for client in self.clients.values():
            client.close()
        self.clients = {}

    def config(self) -> Any:
        from app.services import geraete_store

        return geraete_store.CONFIG

    def client(self, role: str) -> Any:
        from fastapi.testclient import TestClient

        from app.db import SessionLocal
        from app.main import app
        from app.models import Account
        from tests.conftest import new_client

        if role not in self.clients:
            if role == "anonymous":
                # A program or an iPhone app: no cookie, no tab header.
                self.clients[role] = TestClient(app, base_url="http://testserver")
            else:
                with SessionLocal() as db:
                    row = db.get(Account, self.ids[role])
                    assert row is not None
                    db.expunge(row)
                self.clients[role] = new_client(row)
        return self.clients[role]

    def account_id(self, role: str) -> Any:
        return self.ids[role]

    def legacy_devices(self) -> list[LegacyDevice]:
        return [LegacyDevice(label) for label in LEGACY]

    def make_legacy(self, spec: LegacyDevice, *, account: str = "owner") -> Made:
        """As 1.12.0 wrote a device (``services/devices.add``): ``npd_`` and 32 random bytes, the SHA-256 hex of the
        whole token, the first eight characters as ``prefix``, ``via``; none of the module's columns."""
        from sqlalchemy import text

        from app import clock
        from app.db import SessionLocal

        token = "npd_" + secrets.token_urlsafe(32)
        made_at = clock.now() - timedelta(days=3)
        with SessionLocal() as db:
            db.execute(text(
                "INSERT INTO devices (uid, account_id, name, token_hash, prefix, created_at, last_used_at, revoked_at, "
                "via) VALUES (:uid, :account, :name, :hash, :prefix, :made, :made, NULL, :via)"), {
                    "uid": secrets.token_hex(16), "account": self.ids[account], "name": spec.label,
                    "hash": hashlib.sha256(token.encode("utf-8")).hexdigest(), "prefix": token[:8],
                    "made": made_at.replace(tzinfo=None), "via": LEGACY[spec.label]})
            db.commit()
        return Made(token)

    def probe(self, token: str | None, headers: dict[str, str] | None = None) -> Any:
        sent = dict(headers or {})
        if token is not None:
            sent["Authorization"] = f"Bearer {token}"
        return self.device_client().get(f"{self.app_prefix}/me", headers=sent)

    def database_text(self) -> bytes:
        from app.config import get_settings
        from app.db import engine

        engine.dispose()
        path = Path(get_settings().database_path)
        return b"".join(Path(str(path) + rest).read_bytes() for rest in ("", "-wal")
                        if Path(str(path) + rest).is_file())

    def _manage(self, action: str, account: str) -> None:
        """Through the shared account module, as the operator's page does. Blocking and deleting end the account's
        browser sessions in nexpaper; its browser signs in anew afterwards."""
        from app.db import SessionLocal
        from app.services.konten_store import KontenStore
        from app.vendor.nexkonten import manage
        from tests.conftest import PASSWORD

        with SessionLocal() as db:
            getattr(manage, action)(KontenStore(db), self.ids[account], actor_id=self._actor(account),
                                    password=PASSWORD)
        old = self.clients.pop(account, None)
        if old is not None:
            old.close()

    def _actor(self, account: str) -> Any:
        """The operator acts; on the operator's own account a second operator does (nobody blocks themselves)."""
        from tests.conftest import make_account

        if account != "operator":
            return self.ids["operator"]
        if "second operator" not in self.ids:
            self.ids["second operator"] = make_account("otto", "operator").id
        return self.ids["second operator"]

    def block(self, account: str = "owner") -> None:
        self._manage("block", account)

    def unblock(self, account: str = "owner") -> None:
        self._manage("unblock", account)

    def remove(self, account: str = "owner") -> None:
        self._manage("remove", account)

    def restore(self, account: str = "owner") -> None:
        self._manage("restore", account)

    def purge(self, account: str = "owner") -> None:
        from app.db import SessionLocal
        from app.models import Account
        from tests.conftest import remove_for_good

        with SessionLocal() as db:
            row = db.get(Account, self.ids[account])
            deleted = row is not None and row.deleted_at is not None
        if not deleted:
            self.remove(account)
        remove_for_good(self.ids[account])

    def owe_factor(self, account: str = "owner") -> None:
        """The operator asks for a second factor; ``account`` has none, the others have one."""
        from app.db import SessionLocal
        from app.models import Account
        from app.services import totp
        from tests.conftest import require_second_factor

        with SessionLocal() as db:
            for role, number in self.ids.items():
                row = db.get(Account, number)
                assert row is not None
                row.totp_secret_enc = "" if role == account else totp.seal_seed(totp.generate_seed())
            db.commit()
        require_second_factor(True)

    def switch(self, name: str, on: bool) -> None:
        from app.db import SessionLocal
        from app.services import geraete_store, settings_service

        with SessionLocal() as db:
            settings_service.save(db, {geraete_store.SWITCH_SETTINGS[name]: on})

    def travel(self, delta: timedelta) -> None:
        """nexpaper's clock moves on; the browsers sign in anew (their sessions ran out on the way)."""
        self.offset += delta
        for role in [role for role in self.clients if role != "anonymous"]:
            self.clients.pop(role).close()

    def tell(self, account: str, kind: str) -> None:
        """nexpaper sends no kind of its own through the relay yet: the module's ``push.tell`` with its store."""
        from app.db import SessionLocal
        from app.services import geraete_store
        from app.vendor.nexgeraete import push

        with SessionLocal() as db:
            push.tell(geraete_store.GeraeteStore(db), geraete_store.CONFIG, self.ids[account], kind,
                      {"type": kind, "title": "Kim Example", "text": "changed something"}, send=self.relay)

    def announce(self, version: str) -> None:
        """The way of ``updates.on_devices`` (``services/updates.py``, G56): ``geraete_store.newer``, with the version
        nexpaper runs."""
        from app.services import geraete_store

        geraete_store.newer(version)

    def update_wanted(self) -> bool:
        """What nexpaper gives ``nexupdates`` as ``devices_want`` (G56)."""
        from app.services import geraete_store

        return geraete_store.update_wanted()

    def running(self) -> str:
        from app import __version__

        return __version__

    def sweep(self) -> int:
        from app.services import geraete_store

        return geraete_store.sweep()

    def paired_mails(self) -> list[tuple[Any, str]]:
        return list(self.paired)
