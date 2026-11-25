"""nexpost contract tests: nexpaper's adapter (copied once from the module's template, now nexpaper's file).

The contract tests in ``backend/tests/nexpost/`` run the module against nexpaper's real store
(``app.services.post_store``) over the operator's settings and the table ``mail_outbox``. The database is the one of
the test session (``tests/conftest.py`` empties it before every test).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from post_contract import Legacy, StandardAdapter, password


class Adapter(StandardAdapter):
    package = "app.vendor.nexpost"

    def start(self) -> None:
        from app.services import post_store

        post_store.configure()

    def stop(self) -> None:
        from app.vendor import nexpost

        nexpost.use_smtp(None)

    @contextmanager
    def store(self) -> Iterator[Any]:
        from app.db import SessionLocal
        from app.services.post_store import PostStore

        with SessionLocal() as db:
            yield PostStore(db)

    def raw_text(self) -> str:
        from sqlalchemy import text

        from app.db import engine

        parts: list[str] = []
        with engine.connect() as connection:
            for table in ("settings", "mail_outbox"):
                parts += [repr(tuple(row)) for row in connection.execute(text(f"SELECT * FROM {table}"))]  # noqa: S608
        return "\n".join(parts)

    def legacy(self) -> Legacy:
        """The mail server as the settings page of 1.12.0 saved it (``PUT /api/v1/settings``: the keys ``smtp_*``, the
        password sealed with the server's key); 1.12.0 had no outbox (its mail went out at once)."""
        from app.db import SessionLocal
        from app.security import encrypt_secret
        from app.services import settings_service
        from app.vendor.nexpost.model import MailSettings

        secret = password()
        with SessionLocal() as db:
            settings_service.save(db, {
                "smtp_host": "smtp.example.com",
                "smtp_port": 465,
                "smtp_security": "tls",
                "smtp_user": "paper@example.com",
                "smtp_password_enc": encrypt_secret(secret),
                "smtp_from": "paper@example.com",
            })
        return Legacy(
            settings=MailSettings(
                host="smtp.example.com",
                port=465,
                security="tls",
                user="paper@example.com",
                password=secret,
                sender="paper@example.com",
                sender_name="",
            ),
            queued=0,
        )

    def new_sign_in_letter(self, where: str, sender: str) -> Any:
        """The letter nexpaper writes for "New sign-in" (``notices.sign_in_letter``, the same the background mail
        sends): an account with an address that counts, the public address set, the User-Agent ``where``. ``sender``
        is not handed to the letter at all (nexpaper's notice keeps it for nothing but the push to the own devices)."""
        del sender
        from app import clock
        from app.db import SessionLocal
        from app.models import Account
        from app.security import hash_password
        from app.services import notices, settings_service

        with SessionLocal() as db:
            settings_service.save(db, {"public_url": "https://paper.example.com"})
            account = Account(name="alex", display_name="Alex", role="member", sign_in="password",
                              password_hash=hash_password(password()), email="alex@example.com", email_counts=True)
            db.add(account)
            db.commit()
            db.refresh(account)
            return notices.sign_in_letter(db, account, account.email, where, clock.now(),
                                          settings_service.public_url(db))

    #: The page Server › Mail (``routers/mail.py``).
    mail_prefix = "/api/v1/server/mail"

    def account(self, address: str, *, language: str, name: str, confirmed: bool) -> Any:
        """An account of nexpaper with this address, its language and display name; confirmed or not."""
        import secrets

        from app import clock
        from app.db import SessionLocal
        from app.models import Account
        from app.security import hash_password

        with SessionLocal() as db:
            row = Account(name=f"p{secrets.token_hex(4)}", display_name=name, role="member", sign_in="password",
                          password_hash=hash_password(password()), email=address, email_counts=True,
                          language=language, email_confirmed_at=clock.now() if confirmed else None)
            db.add(row)
            db.commit()
            return row.id

    def client(self, role: str) -> Any:
        """nexpaper's own app (``routers/mail.py`` mounts ``nexpost.api.router``), signed in as ``role``."""
        from app.db import SessionLocal
        from app.models import MEMBER, OPERATOR, Account
        from tests.conftest import make_account, new_client

        if role == "anonymous":
            return new_client()
        name = "olli" if role == "operator" else "mika"
        with SessionLocal() as db:
            row = db.query(Account).filter_by(name=name).one_or_none()
            if row is not None:
                db.expunge(row)
        return new_client(row or make_account(name, OPERATOR if role == "operator" else MEMBER))
