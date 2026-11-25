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
