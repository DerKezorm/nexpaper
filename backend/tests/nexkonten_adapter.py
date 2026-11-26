"""nexkonten contract tests: nexpaper's adapter (copied once from the module's template, now nexpaper's file).

The contract tests in ``backend/tests/nexkonten/`` run the module's flows against nexpaper's real ``Store``
(``app.services.konten_store``) over nexpaper's real tables, and sign in through nexpaper's own route
``POST /api/v1/auth/login`` with its field names (``name``, ``password``).

The database is the one of the test session (``tests/conftest.py`` empties it before every test and runs ``init_db``).
``legacy()`` loads the database that 1.12.0 itself built (``tests/bestand``).

⚠️ **What nexpaper does not have is said, not faked:** nexpaper's invitations are used by one person each
(``reusable_invites``), and a second factor is required only by the operator's switch for everybody
(``two_factor_required``, the contract's ``switch``), never of one account alone (``required_second_factor``): the
contract passes over those parts. An invitation that fixes a username is skipped with its reason (1.12.0 never made
one).
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from konten_contract import Legacy, StandardAdapter, png

TAB = {"X-Nexpaper-Client": "tab-contract"}


class Adapter(StandardAdapter):
    package = "app.vendor.nexkonten"
    #: 10 wrong passwords, then 15 minutes (``security.MAX_FAILURES``, ``LOCK_MINUTES``).
    lock_after: int | None = 10
    #: What nexpaper has (the contract passes over the rest instead of skipping it).
    blocking: bool = True
    required_second_factor: bool = False
    reusable_invites: bool = False

    def start(self) -> None:
        from app.security import brake
        from app.services import konten_store, totp

        konten_store.configure()
        konten_store.PICTURE_IN_THREAD = False
        brake.forget()
        totp.forget()

    def stop(self) -> None:
        from app.db import engine
        from app.services import konten_store

        konten_store.PICTURE_IN_THREAD = True
        engine.dispose()

    @contextmanager
    def store(self) -> Iterator[Any]:
        from app.db import SessionLocal
        from app.services.konten_store import KontenStore

        with SessionLocal() as db:
            yield KontenStore(db)

    def seed(
        self,
        username: str,
        *,
        display_name: str = "",
        email: str = "",
        email_confirmed: bool = True,
        email_proven: bool = False,
        email_source: str = "",
        password: str | None = None,
        operator: bool = False,
        blocked: bool = False,
        picture: bool = False,
        second_factor: str = "none",
    ) -> Any:
        from app.db import SessionLocal
        from app.models import MEMBER, OPERATOR, SIGN_IN_OIDC, SIGN_IN_PASSWORD, Account, utcnow
        from app.security import hash_password
        from app.services import totp

        avatar = png() if picture else None
        with SessionLocal() as db:
            row = Account(
                name=username,
                display_name=display_name,
                email=email,
                email_counts=bool(email_confirmed),
                email_confirmed_at=utcnow() if email and email_proven else None,
                email_from_provider=bool(email) and email_source == "provider",
                role=OPERATOR if operator else MEMBER,
                sign_in=SIGN_IN_PASSWORD if password else SIGN_IN_OIDC,
                password_hash=hash_password(password) if password else "",
                blocked_at=utcnow() if blocked else None,
                avatar=avatar,
                avatar_at=utcnow() if picture else None,
                totp_secret_enc=totp.seal_seed(totp.generate_seed()) if second_factor == "active" else "",
            )
            db.add(row)
            db.commit()
            return row.id

    def _operator_id(self) -> int:
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models import OPERATOR, Account

        with SessionLocal() as db:
            found = db.scalar(select(Account.id).where(Account.role == OPERATOR).order_by(Account.id).limit(1))
        return found if found is not None else self.seed("first-operator", operator=True, password="x" * 16)

    def make_invite(
        self,
        *,
        email: str = "",
        display_name: str = "",
        username: str = "",
        expired: bool = False,
        reusable: bool = False,
    ) -> str:
        """As ``POST /api/v1/invites`` makes it (``accounts.create_invite``)."""
        if username:
            pytest.skip("nexpaper's invitations never fixed a username")
        from app.db import SessionLocal
        from app.models import Account, utcnow
        from app.services import accounts

        with SessionLocal() as db:
            by = db.get(Account, self._operator_id())
            assert by is not None
            invite, token = accounts.create_invite(db, by, days=7, email=email, display_name=display_name)
            if expired:
                invite.expires_at = utcnow() - timedelta(minutes=5)
            db.commit()
        return token

    def open_session(self, account_id: Any, kind: str = "browser") -> Any:
        """``browser`` a browser session, ``waiting`` a sign-in waiting for its code (``totp.start_pending``),
        ``device`` a paired device (``devices``), ``program`` an API key, ``known_browser`` the mark in the device
        cookie."""
        from app.db import SessionLocal
        from app.models import Account
        from app.security import server_key, start_session
        from app.services import apikeys, devices, totp
        from app.services.konten_store import KontenStore
        from app.vendor.nexkonten import sessions

        with SessionLocal() as db:
            row = db.get(Account, account_id)
            assert row is not None
            if kind == "browser":
                return ("browser", start_session(db, row, "127.0.0.1", "contract"))
            if kind == "waiting":
                return ("waiting", totp.start_pending(row.id))
            if kind == "device":
                device, _token = devices.make(db, row, "Probe")
                return ("device", device.id)
            if kind == "program":
                key, _token = apikeys.make(db, row, "Probe", "read")
                return ("key", key.id)
            if kind == "known_browser":
                store = KontenStore(db)
                mark = sessions.mark(server_key(), store.device_key(row.id))
                db.commit()
                return ("known", row.id, sessions.add_mark("", mark))
        raise ValueError(kind)

    def session_alive(self, handle: Any) -> bool:
        if handle is None:
            return False
        from app.db import SessionLocal
        from app.models import Account, ApiKey, Device
        from app.security import server_key, session_account
        from app.services import totp
        from app.vendor.nexkonten import sessions

        with SessionLocal() as db:
            if handle[0] == "browser":
                return session_account(db, handle[1]) is not None
            if handle[0] == "waiting":
                return totp.get_pending(handle[1]) is not None
            if handle[0] == "device":
                device = db.get(Device, handle[1])
                return device is not None and device.revoked_at is None
            if handle[0] == "key":
                return db.get(ApiKey, handle[1]) is not None
            if handle[0] == "known":
                row = db.get(Account, handle[1])
                return bool(row and row.device_key) and sessions.is_known(handle[2], server_key(), row.device_key)
        raise ValueError(handle)

    def switch(self, name: str, on: bool) -> None:
        from app.db import SessionLocal
        from app.services import konten_store, settings_service

        key = {"factor_required": konten_store.SWITCH_FACTOR_REQUIRED, "passkeys_allowed": konten_store.SWITCH_PASSKEYS}
        with SessionLocal() as db:
            settings_service.save(db, {key[name]: on})

    def delete_account(self, account_id: Any) -> None:
        """nexpaper deletes for good, as the operator's list does (``DELETE /api/v1/accounts/{id}``): the name stays
        reserved, the own vault goes with the account."""
        from app.db import SessionLocal
        from app.models import Account
        from app.models_accounts import FormerName
        from app.services import vaults

        with SessionLocal() as db:
            row = db.get(Account, account_id)
            assert row is not None
            vaults.before_account_delete(db, row.id, choice="delete_documents", by=self._operator_id(),
                                         account_name=row.name)
            db.add(FormerName(account_id=None, name=row.name))
            db.delete(row)
            db.commit()

    def raw_text(self) -> str:
        from sqlalchemy import text

        from app.db import engine

        parts: list[str] = []
        with engine.connect() as connection:
            for table in ("users", "invites", "password_resets", "email_confirmations", "former_names",
                          "auth_sessions"):
                parts += [repr(tuple(row)) for row in connection.execute(text(f"SELECT * FROM {table}"))]  # noqa: S608
        return "\n".join(parts)

    def legacy(self) -> Legacy:
        """The database 1.12.0 built (``tests/bestand``), then nexpaper's start (``init_db``)."""
        from app.config import get_settings
        from app.db import engine, init_db
        from tests.bestand.build import dump_file, manifest_file, totp_seed

        engine.dispose()
        target = get_settings().database_path
        for rest in ("", "-wal", "-shm"):
            Path(str(target) + rest).unlink(missing_ok=True)
        connection = sqlite3.connect(str(target))
        try:
            connection.executescript(gzip.decompress(dump_file().read_bytes()).decode("utf-8"))
            connection.execute("UPDATE auth_sessions SET expires_at = datetime('now', '+30 days')")
            connection.execute("UPDATE invites SET expires_at = datetime('now', '+7 days')")
            connection.commit()
        finally:
            connection.close()
        init_db()

        manifest = json.loads(manifest_file().read_text(encoding="utf-8"))
        self.manifest = manifest
        count: dict[str, int] = {}
        for entry in manifest["accounts"]:
            if entry["email"]:
                count[entry["email"].lower()] = count.get(entry["email"].lower(), 0) + 1
        logins: list[tuple[str, str, bool]] = []
        for entry in manifest["accounts"]:
            name, secret, address = entry["name"], entry.get("password") or "", entry["email"]
            if not secret:
                logins.append((name, "", False))
                continue
            open_ = not entry.get("blocked")
            logins += [(name, secret, open_), (name.upper(), secret, open_)]
            if address:
                # Every address of 1.12.0 counts (the decision on the Bestand); one two accounts share signs in
                # nobody (rule 3).
                logins.append((address.upper(), secret, open_ and count[address.lower()] == 1))
        deleted = manifest["deleted"]
        logins.append((deleted["name"], deleted["password"], False))
        subjects = [entry["provider"]["sub"] for entry in manifest["accounts"] if entry.get("provider")]
        return Legacy(
            logins=logins,
            invites=[entry["token"] for entry in manifest["open_invites"]],
            fixed_names={},
            provider_logins=[(sub, True) for sub in subjects],
            factors=[
                (entry["name"], totp_seed(entry["second_factor"]), list(entry["recovery_codes"]))
                for entry in manifest["accounts"]
                if entry.get("second_factor")
            ],
        )

    @contextmanager
    def oidc_store(self) -> Iterator[Any]:
        from app.db import SessionLocal
        from app.services.oidc_store import SqlStore

        with SessionLocal() as db:
            yield SqlStore(db)

    def provider_sign_in(self, subject: str) -> Any:
        """Through nexpaper's OIDC routes and the fake provider of ``tests/oidc_helpers``, with the provider the
        database of 1.12.0 holds (``tests/bestand``)."""
        from urllib.parse import urlencode, urlsplit

        from fastapi.testclient import TestClient

        from app.main import app
        from app.security import brake
        from app.vendor import nexoidc
        from app.vendor.nexoidc import attempt, protocol
        from tests.bestand.build import manifest_file
        from tests.oidc_helpers import fakes

        manifest = getattr(self, "manifest", None) or json.loads(manifest_file().read_text(encoding="utf-8"))
        data = manifest["provider"]
        person = next(
            (entry["provider"] for entry in manifest["accounts"] if entry.get("provider", {}).get("sub") == subject),
            {"sub": subject, "preferred_username": "nobody", "name": "", "email": ""},
        )
        network = fakes.Network()
        nexoidc.use_transport(network.transport())
        protocol.clear_caches()
        attempt.forget_used_states()
        brake.forget()
        try:
            fake = network.add(fakes.FakeProvider(data["issuer"], client_id=data["client_id"],
                                                  client_secret=data["client_pass"]))
            fake.person = dict(person)
            browser = TestClient(app, base_url="http://testserver", follow_redirects=False, headers=TAB)
            start = browser.get(f"/api/v1/oidc/{data['slug']}/start")
            target = start.headers.get("location", "")
            path = urlsplit(fakes.query_of(target)["redirect_uri"]).path
            back = browser.get(f"{path}?{urlencode(fake.authorize(target))}")
            if "error=" in back.headers.get("location", ""):
                return None
            me = browser.get("/api/v1/auth/me")
            return me.json()["id"] if me.status_code == 200 else None
        finally:
            nexoidc.use_transport(None)
            protocol.clear_caches()
            attempt.forget_used_states()

    def sign_in(self, typed: str, password: str) -> Any:
        """Through ``POST /api/v1/auth/login`` (field ``name``) up to the session or the code of the second factor.
        The brake is emptied first: it counts in memory and would answer in a test that tries many."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.security import brake

        brake.forget()
        browser = TestClient(app, base_url="http://testserver", headers=TAB)
        answer = browser.post("/api/v1/auth/login", json={"name": typed, "password": password})
        if answer.status_code != 200:
            return None
        package = __import__(self.package, fromlist=["login"])
        with self.store() as store:
            account = package.login.resolve_login(store, typed)
        return account.id if account is not None else None

    def sign_in_from(self, typed: str, password: str, sender: str) -> tuple[int, Any]:
        """Through ``POST /api/v1/auth/login`` from the address ``sender`` (nexpaper reads the client's address; no
        proxy is trusted in the tests), as ``(status, account id)``. The brake is not emptied: it is what is tested."""
        from fastapi.testclient import TestClient

        from app.main import app

        browser = TestClient(app, base_url="http://testserver", headers=TAB, client=(sender, 50000))
        answer = browser.post("/api/v1/auth/login", json={"name": typed, "password": password})
        if answer.status_code != 200:
            return answer.status_code, None
        package = __import__(self.package, fromlist=["login"])
        with self.store() as store:
            account = package.login.resolve_login(store, typed)
        return 200, account.id if account is not None else None

    def listed_invites(self) -> list[dict[str, Any]]:
        """``GET /api/v1/invites`` as the operator's list gets it: expired invitations stay until withdrawn."""
        from app.db import SessionLocal
        from app.routers.invites import list_invites

        with SessionLocal() as db:
            return [{"email": row["email"], "expired": bool(row["expired"])}
                    for row in list_invites(None, db)]  # type: ignore[arg-type]

    def forgot_through_route(self, typed: str, *, mail_fails: bool) -> tuple[list[str], int]:
        """``POST /api/v1/auth/forgot`` with a mail server and the public address set; the work after the answer runs
        in nexpaper's background pool (``notices.later``), waited for here. The mail goes through
        ``nexpost.send.deliver`` (``post_store.send_now``), caught by ``nexpost.testing.catch_mail``."""
        from fastapi.testclient import TestClient
        from sqlalchemy import func, select

        from app.db import SessionLocal
        from app.main import app
        from app.models_accounts import MailOutbox
        from app.security import brake
        from app.services import notices, settings_service
        from app.vendor.nexpost import testing

        brake.forget()
        with SessionLocal() as db:
            settings_service.save(db, {"smtp_host": "mail.example.com", "smtp_from": "paper@example.com",
                                       "public_url": "https://paper.example.com"})
            before = int(db.scalar(select(func.count()).select_from(MailOutbox)) or 0)
        with testing.catch_mail(fail=mail_fails) as caught:
            browser = TestClient(app, base_url="http://testserver", headers=TAB)
            answer = browser.post("/api/v1/auth/forgot", json={"name": typed})
            assert answer.status_code == 202, answer.text
            notices.settle()
        with SessionLocal() as db:
            after = int(db.scalar(select(func.count()).select_from(MailOutbox)) or 0)
        return [letter.to for letter in caught.sent], after - before

    def picture_status(self, owner: Any, viewer: Any | None) -> int:
        """``GET /api/v1/avatars/{id}`` from a browser signed in as ``viewer`` (a real session), or from none."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.security import SESSION_COOKIE

        browser = TestClient(app, base_url="http://testserver", headers=TAB)
        if viewer is not None:
            browser.cookies.set(SESSION_COOKIE, self.open_session(viewer)[1])
        return browser.get(f"/api/v1/avatars/{owner}").status_code

    # --- Since konten 1.1.0 -----------------------------------------------------------------------------------------

    #: E23: nexpaper keeps the addresses 1.12.0 never proved by a link as unproven (the line "Address not confirmed"
    #: was already there); every other app marks the addresses of before as proven.
    keeps_unproven_addresses = True

    def age_deletion(self, account_id: Any, days: int) -> None:
        """The moment of the deletion ``days`` back, with the block mark a deletion sets (``KontenStore.set_deleted``)."""
        from app.db import SessionLocal
        from app.models import Account

        with SessionLocal() as db:
            row = db.get(Account, account_id)
            assert row is not None and row.deleted_at is not None
            moved = row.deleted_at - timedelta(days=days)
            if row.blocked_at is not None and row.blocked_at == row.deleted_at:
                row.blocked_at = moved
            row.deleted_at = moved
            db.commit()

    def provider_active(self, on: bool) -> None:
        """One active provider in ``oidc_providers`` (the table of the module oidc), or none."""
        from sqlalchemy import delete

        from app.db import SessionLocal
        from app.models import OidcProvider, utcnow

        with SessionLocal() as db:
            db.execute(delete(OidcProvider))
            if on:
                db.add(OidcProvider(slug="probe", label="Probe", issuer="https://id.example.com", client_id="nexpaper",
                                    client_secret_enc="", scopes="openid email profile", enabled=True,
                                    auto_create=False, trusts_second_factor=False, managed="", position=0,
                                    redirect_path="/api/v1/oidc/probe/callback", created_at=utcnow()))
            db.commit()

    def readiness(self, operator: Any) -> dict[str, Any]:
        """``GET /api/v1/server/readiness`` over https, as the operator in a signed-in browser."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.security import SESSION_COOKIE

        browser = TestClient(app, base_url="https://testserver", headers=TAB)
        browser.cookies.set(SESSION_COOKIE, self.open_session(operator)[1])
        answer = browser.get("/api/v1/server/readiness")
        assert answer.status_code == 200, answer.text
        return answer.json()
