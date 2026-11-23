"""``GET /api/v1/deadlines`` names the page of each document (``url``), for nextime and other readers with a key.

The same rule as the dashboard card: the public address when the operator set one, else the address the request came
to; ``/dokument/<id>`` for a filed document, ``/eingang/<id>`` for one in the inbox. With a key of scope ``read`` as with
the browser.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account
from app.services import apikeys, settings_service

from .conftest import make_account, new_client
from .papers import Date, add_document, freeze, own_vault

NOON = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
TODAY = Date(2026, 10, 10)
DAY = timedelta(days=1)


@pytest.fixture(autouse=True)
def fresh_brake() -> Iterator[None]:
    apikeys.forget()
    yield
    apikeys.forget()


def urls(answer: dict[str, Any]) -> dict[int, str]:
    """The ``url`` of every item of every section, by document."""
    return {item["document_id"]: item["url"] for name in ("overdue", "soon", "later") for item in answer[name]["items"]}


def test_each_deadline_names_the_page_of_its_document(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert client.put("/api/v1/settings", json={"api_keys_allowed": True}).status_code == 200
    rita: Account = make_account("rita")
    with SessionLocal() as db:
        row = db.get(Account, rita.id)
        assert row is not None
        row.profile = {"timezone": "UTC"}
        db.commit()
    home = own_vault(rita)
    freeze(monkeypatch, NOON)
    filed = add_document(home, rita, "Strom", status="filed", content=None, dates=[("due", TODAY + DAY)])
    waiting = add_document(home, rita, "Versicherung", status="inbox", content=None, dates=[("due", TODAY + 2 * DAY)])
    with new_client(rita) as browser:
        answer = browser.post("/api/v1/api-keys", json={"name": "nextime", "scope": "read"})
        assert answer.status_code == 201, answer.text
        key = {"Authorization": f"Bearer {answer.json()['secret']}"}
        freeze(monkeypatch, NOON)
        # Without a public address: the address the request came to, through the key as through the browser.
        for asked in (client.get("/api/v1/deadlines", headers=key), browser.get("/api/v1/deadlines")):
            assert asked.status_code == 200, asked.text
            assert urls(asked.json()) == {
                filed: f"http://testserver/dokument/{filed}",
                waiting: f"http://testserver/eingang/{waiting}",
            }
        with SessionLocal() as db:
            settings_service.save(db, {"public_url": "https://paper.example.com/"})
        asked = client.get("/api/v1/deadlines", headers=key)
        assert asked.status_code == 200, asked.text
        assert urls(asked.json()) == {
            filed: f"https://paper.example.com/dokument/{filed}",
            waiting: f"https://paper.example.com/eingang/{waiting}",
        }
