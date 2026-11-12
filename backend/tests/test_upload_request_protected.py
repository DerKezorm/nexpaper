"""Protected PDFs (P1) and upload requests (U1) together: a PDF with a password that somebody without an account sends
through a request lands in the personal vault of the person who asked, but none of that person's kept passwords is
tried on it. Whoever holds the address must not learn whether one of them fits (``pdf_passwords.whose``); the file
waits for its password like any other. Every password is made at run time."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, Document, PdfPassword, Version
from app.services import pdf_passwords, processing

from .conftest import new_client
from .intake import process_all
from .papers import own_vault
from .test_pdf_passwords import protected, word
from .test_pdf_passwords_whose import keep_for
from .test_upload_requests import documents_of, fresh, jule, make, send, stranger, token_of  # noqa: F401 - fixtures


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Every run of the worker, whether it carried passwords (True) or not."""
    seen: list[bool] = []
    real = processing._spawn

    def spawn(request: dict[str, Any], timeout: int, cwd: str) -> Any:
        seen.append(bool(request.get("passwords")))
        return real(request, timeout, cwd)

    monkeypatch.setattr(processing, "_spawn", spawn)
    return seen


def test_a_protected_pdf_through_a_request_tries_none_of_the_kept_passwords(
        jule: Account, runs: list[bool]) -> None:  # noqa: F811
    secret = word()
    keep_for(jule, secret)
    with new_client(jule) as browser:
        token = token_of(make(browser))
    with stranger() as outside:
        answer = send(outside, token, "gehalt.pdf", protected(secret))
    assert answer.status_code == 201, answer.text
    runs.clear()
    process_all()
    (document,) = documents_of(jule)
    assert document.vault_id == own_vault(jule) and document.source == "request"
    # The worker ran, and never with a password: the file waits for one.
    assert runs and True not in runs
    with new_client(jule) as browser:
        seen = browser.get(f"/api/v1/documents/{document.id}").json()
        lines = [e["action"] for e in browser.get(f"/api/v1/documents/{document.id}/events").json()]
    assert seen["process_error"] == "encrypted" and seen["original_protected"] == ""
    assert pdf_passwords.OPENED not in lines
    with SessionLocal() as db:
        assert db.scalar(select(PdfPassword.last_matched_at).where(PdfPassword.user_id == jule.id)) is None
        row = db.get(Document, document.id)
        version = db.scalar(select(Version).where(Version.document_id == document.id))
        assert row is not None and version is not None
        # Brought by nobody of the server, though the version names the person it came for.
        assert version.created_by == jule.id
        assert pdf_passwords.whose(db, row, version) is None


def test_the_request_is_neither_an_upload_of_the_person_nor_a_delivery_for_them() -> None:
    assert "request" not in pdf_passwords.UPLOADED_SOURCES
    assert "request" not in pdf_passwords.DELIVERED_SOURCES


def test_the_person_opens_it_with_the_password_typed(jule: Account, client: TestClient) -> None:  # noqa: F811
    """Waiting is not a dead end: the person who asked types the password, as for any protected PDF."""
    secret = word()
    with new_client(jule) as browser:
        token = token_of(make(browser))
    with stranger() as outside:
        assert send(outside, token, "gehalt.pdf", protected(secret)).status_code == 201
    process_all()
    (document,) = documents_of(jule)
    with new_client(jule) as browser:
        answer = browser.post(f"/api/v1/documents/{document.id}/unlock", json={"password": secret})
        assert answer.status_code == 200, answer.text
        process_all()
        seen = browser.get(f"/api/v1/documents/{document.id}").json()
    assert seen["process_error"] == "" and seen["original_protected"] == "password"
