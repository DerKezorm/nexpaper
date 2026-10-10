"""The history says where a change of the status went (filed, or back to the inbox), so the page can say "filed it"."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models import Account

from .papers import add_document, own_vault


def test_a_change_of_the_status_says_where_it_went(client: TestClient, operator: Account) -> None:
    doc = add_document(own_vault(operator), operator, "Waiting", status="inbox", content=None)
    assert client.patch(f"/api/v1/documents/{doc}", json={"status": "filed", "title": "Filed"}).status_code == 200
    assert client.patch(f"/api/v1/documents/{doc}", json={"status": "inbox"}).status_code == 200
    assert client.patch(f"/api/v1/documents/{doc}", json={"title": "Only the title"}).status_code == 200
    events = client.get(f"/api/v1/documents/{doc}/events").json()
    assert [e["detail"] for e in events[:3]] == [
        {"fields": ["title"]},
        {"fields": ["status"], "status": "inbox"},
        {"fields": ["title", "status"], "status": "filed"},
    ]
