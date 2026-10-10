"""Helpers for the tests of the search: a document's text written as the worker would leave it (through the real path:
the text, a new change number, the index before the commit), and a search through the interface."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Document, Version
from app.services import changes, processing


def give_text(document_id: int, *pages: str, ocr_pages: int = 0) -> None:
    """The text of the document's current version, as reading the file would leave it."""
    with SessionLocal() as db:
        changes.write_lock(db)
        document = db.get(Document, document_id)
        assert document is not None
        version = db.scalar(select(Version).where(Version.document_id == document_id,
                                                  Version.n == document.current_version))
        assert version is not None
        processing._keep_text(db, version, list(pages), ocr_pages, "deu" if ocr_pages else "")
        document.change_seq = changes.next_seq(db)
        db.commit()


def search(client: TestClient, q: str = "", **params: Any) -> dict[str, Any]:
    answer = client.get("/api/v1/search", params={"q": q, **params})
    assert answer.status_code == 200, answer.text
    return answer.json()


def titles(client: TestClient, q: str = "", **params: Any) -> list[str]:
    return [hit["document"]["title"] for hit in search(client, q, **params)["items"]]


def found(client: TestClient, q: str = "", **params: Any) -> set[str]:
    return set(titles(client, q, limit=100, **params))


def marked(text: str, marks: list[list[int]]) -> list[str]:
    """The pieces of ``text`` the marks name (offsets in UTF-16 code units)."""
    units = text.encode("utf-16-le")
    return [units[start * 2 : end * 2].decode("utf-16-le") for start, end in marks]
