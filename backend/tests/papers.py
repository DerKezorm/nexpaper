"""Helpers for the tests of vaults and documents: made-up people, vaults, documents with a file, straight through the
services (the routes under test are called through a client)."""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app import clock
from app.db import SessionLocal
from app.models import MANAGE, Account, Document, Vault
from app.services import documents, vaults

from .conftest import make_account

#: A small PDF-looking file; the tests never open it as a PDF.
PDF = b"%PDF-1.4\n% made-up test document\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"


def own_vault(account: Account) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(Vault.id).where(Vault.personal_of == account.id)) or 0)


def shared_vault(name: str, manager: Account, *members: tuple[Account, str]) -> int:
    """A shared vault made by ``manager`` (as the operator would), with the members and rights named."""
    with SessionLocal() as db:
        operator = db.get(Account, manager.id)
        assert operator is not None
        vault = vaults.create_shared(db, operator, name, "folder")
        for account, right in members:
            vaults.set_member(db, manager.id, vault.id, account.id, right)
        return vault.id


def add_document(vault_id: int, owner: Account | None, title: str = "Strom Oktober", *, content: bytes | None = PDF,
                 **fields: Any) -> int:
    with SessionLocal() as db:
        return documents.create(db, vault_id=vault_id, owner_id=owner.id if owner else None, title=title,
                                content=content, **fields).id


def document(document_id: int) -> Document:
    with SessionLocal() as db:
        found = db.get(Document, document_id)
        assert found is not None
        db.expunge(found)
        return found


def freeze(monkeypatch: Any, moment: datetime) -> None:
    """The server's clock stands at ``moment`` (UTC)."""
    monkeypatch.setattr(clock, "now", lambda: moment)


def people(*names: str) -> list[Account]:
    return [make_account(name) for name in names]


__all__ = ["MANAGE", "PDF", "Date", "add_document", "document", "freeze", "own_vault", "people", "shared_vault"]
