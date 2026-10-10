"""Helpers for the tests of bringing files in: uploading through the routes, running the worker's jobs, looking at the
disk, setting the limits."""

from __future__ import annotations

import hashlib
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import clock
from app.db import SessionLocal
from app.models import Account, ApiKey, Document, Version
from app.services import apikeys, jobs, settings_service, storage

from .conftest import DATA_DIR


def post_files(client: TestClient, *items: tuple[str, bytes], vault_id: int | None = None, **kwargs: Any) -> Any:
    """``POST /api/v1/documents`` with the files ``(name, content)``, the way a browser sends them."""
    parts = [("file", (name, content, "application/octet-stream")) for name, content in items]
    query = f"?vault_id={vault_id}" if vault_id is not None else ""
    return client.post(f"/api/v1/documents{query}", files=parts, **kwargs)


def upload_one(client: TestClient, name: str, content: bytes, vault_id: int | None = None) -> dict[str, Any]:
    """One file uploaded and taken: the document as the route answers it."""
    answer = post_files(client, (name, content), vault_id=vault_id)
    assert answer.status_code == 201, answer.text
    return answer.json()["items"][0]["document"]  # type: ignore[no-any-return]


def process_all(rounds: int = 8) -> int:
    """The worker's jobs, run now and here (the background loop is off in the tests), round after round until none is
    waiting: a job that failed and may be tried again waits for the next round, as it does in the loop. Returns how many
    runs there were."""
    total = 0
    for _ in range(rounds):
        ran = jobs.run_pending()
        total += ran
        if not ran:
            break
    return total


def upload_and_read(client: TestClient, name: str, content: bytes, vault_id: int | None = None) -> dict[str, Any]:
    """Uploaded, read by the worker, and fetched again: the document as it stands in the inbox."""
    made = upload_one(client, name, content, vault_id)
    process_all()
    answer = client.get(f"/api/v1/documents/{made['id']}")
    assert answer.status_code == 200
    return answer.json()  # type: ignore[no-any-return]


def disk_files() -> list[Path]:
    """Every file under ``dokumente/``, temporary ones included."""
    base = Path(DATA_DIR) / storage.FOLDER
    if not base.is_dir():
        return []
    return sorted(path for path in base.rglob("*") if path.is_file())


def upload_folder_files() -> list[Path]:
    base = Path(DATA_DIR) / "uploads"
    return sorted(path for path in base.glob("*") if path.is_file()) if base.is_dir() else []


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def limit(**values: int) -> None:
    """The operator's limits, set for a test (``upload_max_mb=1`` and so on)."""
    with SessionLocal() as db:
        settings_service.save(db, values)


def version_of(document_id: int, n: int = 1) -> Version:
    with SessionLocal() as db:
        found = db.scalar(select(Version).where(Version.document_id == document_id, Version.n == n))
        assert found is not None
        db.expunge(found)
        return found


def row_of(document_id: int) -> Document:
    with SessionLocal() as db:
        found = db.get(Document, document_id)
        assert found is not None
        db.expunge(found)
        return found


def upload_key(account: Account, scope: str = "upload") -> str:
    """An API key of the scope (``upload`` cannot be made through the interface yet: it is written straight in), shown
    as the secret a program would carry."""
    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": True})
        secret = apikeys.KEY_PREFIX + os.urandom(24).hex()
        db.add(ApiKey(account_id=account.id, name="scanner", scope=scope, token_hash=apikeys.digest(secret),
                      prefix=secret[:8], created_at=clock.now()))
        db.commit()
    return secret


def device_token(client: TestClient) -> str:
    return client.post("/api/v1/devices", json={"name": "phone"}).json()["token"]  # type: ignore[no-any-return]


def run_for(seconds: float) -> Any:
    """The clock of the server moved ``seconds`` ahead; returns the function that undoes it (for ``monkeypatch``)."""
    return lambda: clock.now() + timedelta(seconds=seconds)
