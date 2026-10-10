"""Documents from the intake folder and the mailbox are read and found like uploads: their text goes into the index once
the worker read them, the search finds them for whom they belong to and for nobody else, and their origin stays."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import clock
from app.db import SessionLocal
from app.models import Account
from app.services import intake, intake_folder, settings_service

from .conftest import make_account, new_client
from .files import make_pdf
from .intake import process_all


class Clock:
    def __init__(self) -> None:
        self.at = 1000.0

    def __call__(self) -> float:
        return self.at


@pytest.fixture
def ticks(monkeypatch: pytest.MonkeyPatch) -> Iterator[Clock]:
    made = Clock()
    monkeypatch.setattr(clock, "monotonic", made)
    intake_folder.forget()
    yield made
    intake_folder.forget()


def titles(client: TestClient, q: str) -> set[str]:
    answer = client.get("/api/v1/search", params={"q": q})
    assert answer.status_code == 200, answer.text
    return {hit["document"]["title"] for hit in answer.json()["items"]}


def test_a_file_from_the_intake_folder_is_found_by_its_text(client: TestClient, operator: Account, ticks: Clock,
                                                              tmp_path: Path) -> None:
    root = tmp_path / "eingang"
    root.mkdir()
    with SessionLocal() as db:
        settings_service.save(db, {"folder_on": True, "folder_path": str(root)})
    jule = make_account("jule")
    stranger = make_account("tom")
    intake_folder.scan()
    (root / "jule" / "Scan 1.pdf").write_bytes(make_pdf(["Kaminkehrer Lindenau Rechnung Oktober 2026"]))
    intake_folder.scan()
    ticks.at += intake_folder.QUIET_SECONDS
    assert intake_folder.scan().taken == {"jule": 1}
    with new_client(jule) as browser:
        assert titles(browser, "kaminkehrer") == set(), "nothing is found before the worker read it"
    process_all()
    with new_client(jule) as browser:
        assert titles(browser, "kaminkehrer") == {"Scan 1"}
        assert titles(browser, "lindenau oktober") == {"Scan 1"}
        [hit] = browser.get("/api/v1/search", params={"q": "kaminkehrer"}).json()["items"]
        assert hit["document"]["source"] == "folder"
        assert browser.get(f"/api/v1/documents/{hit['document']['id']}/origin").json()["source"] == "folder"
    with new_client(stranger) as other:
        assert titles(other, "kaminkehrer") == set()


def test_an_attachment_from_the_mailbox_is_found_by_its_text(client: TestClient, operator: Account,
                                                             tmp_path: Path) -> None:
    jule = make_account("jule")
    stranger = make_account("tom")
    content = make_pdf(["Schornsteinfeger Bezirk Lindenau Gebuehrenbescheid"])
    path = tmp_path / "anhang.pdf"
    path.write_bytes(content)
    with SessionLocal() as db:
        made = intake.take(
            db, uid=jule.id, path=path, filename="Bescheid.pdf", kind="pdf", sha256=hashlib.sha256(content).hexdigest(),
            size=len(content), source="mail",
            item={"key": "box:1:7:1", "state": "taken", "sha256": hashlib.sha256(content).hexdigest(),
                  "size": len(content), "mtime_ns": 0, "message": "m1", "unknown": False, "detail": {}},
        )
        db.commit()
        document_id = made.id
    process_all()
    with new_client(jule) as browser:
        assert titles(browser, "schornsteinfeger") == {"Bescheid"}
        [hit] = browser.get("/api/v1/search", params={"q": "gebuehrenbescheid"}).json()["items"]
        assert hit["document"]["id"] == document_id and hit["document"]["source"] == "mail"
    with new_client(stranger) as other:
        assert titles(other, "schornsteinfeger") == set()
