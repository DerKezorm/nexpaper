"""nexpaper on the shared AI module (ki 0.1.0, Entwurf KI-Anbieter): what an installation of before set up keeps working
(Bestand: the same service, model and key, the main switch on, "Einer für alle"); a new one starts closed; the main
switch, "Jedes Konto selbst" with an own access and "Was ging hinaus" through nexpaper's one task, the proposals for a
new document. Against a stand-in for the model (``httpx.MockTransport``), never a real service or key."""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import _adopt_ai
from app.models import Account, Setting
from app.security import encrypt_secret
from app.services import ai, settings_service

from .conftest import new_client
from .files import make_pdf
from .intake import upload_and_read
from .papers import shared_vault
from .test_ai import Model
from .test_ai_proposals import GOOD, LETTER, asked

HOME = "http://ollama.example.com:11434/v1/"
CLOUD = "https://ai.example.com/v1/"


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> Iterator[Model]:
    stand_in = Model()
    stand_in.text = json.dumps(GOOD)
    ai.transport = httpx.MockTransport(stand_in.handle)
    monkeypatch.setattr(ai, "resolver", lambda host, port: ["192.168.1.20"] if "ollama" in host else ["93.184.216.34"])
    yield stand_in
    ai.transport = None


def test_an_installation_of_before_keeps_its_service(client: TestClient, operator: Account, model: Model) -> None:
    key = "sk-test-" + "k" * 24
    with SessionLocal() as db:
        # The database as 1.12.0 left it: nothing of the module stored yet (the test's start already ran ``adopt``).
        db.query(Setting).filter(Setting.key.in_(("ai_enabled", "ai_mode", "ai_hosts", "ai_hosts_adopted"))).delete()
        db.commit()
        settings_service.save(db, {"ai_provider": "local", "ai_url": HOME, "ai_model": "plain",
                                   "ai_key_enc": encrypt_secret(key, "operator:ai-key")})
    _adopt_ai()
    view = client.get("/api/v1/server/ai").json()
    assert (view["enabled"], view["mode"], view["api"], view["model"], view["key_set"]) == (
        True, "shared", "openai", "plain", True)
    old = client.get("/api/v1/settings/ai").json()
    assert (old["provider"], old["url"], old["model"], old["key_set"]) == ("local", HOME, "plain", True)
    assert client.get("/api/v1/ai").json()["provider"] == "local"
    document = upload_and_read(client, "Brief.pdf", make_pdf(LETTER), shared_vault("Haushalt", operator))
    assert document["suggest"]["title"] == "ai"
    sent = asked(model)[-1]
    assert sent.url.host == "192.168.1.20" and sent.headers["authorization"] == f"Bearer {key}"
    assert json.loads(sent.content)["model"] == "plain"
    # A second start changes nothing (but the count of today's one request).
    _adopt_ai()
    assert client.get("/api/v1/server/ai").json() == {**view, "used_today": 1}


def test_a_new_installation_starts_closed(client: TestClient, operator: Account, model: Model) -> None:
    view = client.get("/api/v1/server/ai").json()
    assert view["enabled"] is False and view["mode"] == "shared" and view["key_set"] is False
    assert client.get("/api/v1/me/ai").json()["reason"] == "ai_off"
    upload_and_read(client, "Brief.pdf", make_pdf(LETTER), shared_vault("Haushalt", operator))
    assert asked(model) == []


def test_the_main_switch_closes_and_opens_without_deleting(client: TestClient, operator: Account,
                                                           model: Model) -> None:
    assert client.put("/api/v1/settings/ai", json={"provider": "openai", "url": CLOUD, "model": "m",
                                                    "key": "sk-test-key"}).status_code == 200
    assert client.get("/api/v1/server/ai").json()["enabled"] is True
    vault = shared_vault("Haushalt", operator)
    upload_and_read(client, "Eins.pdf", make_pdf(LETTER), vault)
    assert len(asked(model)) == 1
    closed = client.put("/api/v1/server/ai", json={"enabled": False}).json()
    assert closed["enabled"] is False and closed["model"] == "m" and closed["key_set"] is True
    assert client.get("/api/v1/ai").json()["provider"] == "none"
    upload_and_read(client, "Zwei.pdf", make_pdf(LETTER), vault)
    assert len(asked(model)) == 1
    assert client.put("/api/v1/server/ai", json={"enabled": True}).status_code == 200
    upload_and_read(client, "Drei.pdf", make_pdf(LETTER), vault)
    assert len(asked(model)) == 2


def test_each_account_its_own_service_where_the_operator_chose_so(client: TestClient, operator: Account,
                                                                  model: Model) -> None:
    assert client.put("/api/v1/server/ai", json={"enabled": True, "mode": "own",
                                                 "hosts": ["ollama.example.com:11434"]}).status_code == 200
    own = client.put("/api/v1/me/ai", json={"api": "openai", "url": HOME, "model": "mine", "key": "sk-own-key"})
    assert own.status_code == 200, own.text
    assert own.json()["own"]["key_set"] is True and "sk-own-key" not in own.text
    upload_and_read(client, "Brief.pdf", make_pdf(LETTER), shared_vault("Haushalt", operator))
    sent = asked(model)[-1]
    assert sent.headers["authorization"] == "Bearer sk-own-key" and json.loads(sent.content)["model"] == "mine"
    # Off the operator's list, the same access stops at the next request.
    assert client.put("/api/v1/server/ai", json={"hosts": []}).status_code == 200
    upload_and_read(client, "Zwei.pdf", make_pdf(LETTER), shared_vault("Büro", operator))
    assert len(asked(model)) == 1


def test_what_went_out_is_a_line_without_content(client: TestClient, operator: Account, model: Model) -> None:
    client.put("/api/v1/settings/ai", json={"provider": "openai", "url": CLOUD, "model": "m", "key": "sk-test-key"})
    upload_and_read(client, "Brief.pdf", make_pdf(LETTER), shared_vault("Haushalt", operator))
    events = client.get("/api/v1/me/ai/events").json()
    assert len(events) == 1 and events[0]["manual"] is False and events[0]["sent"] is None
    assert events[0]["task"] == "propose" and events[0]["outcome"] == "ok" and events[0]["to"] == "ai.example.com"
    with new_client(None) as nobody:
        assert nobody.get("/api/v1/me/ai/events").status_code == 401
    assert client.delete("/api/v1/me/ai/events").json() == {"cleared": 1}
