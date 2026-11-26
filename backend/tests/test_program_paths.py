"""Programs and other nex apps reach the places of the shared modules without nexpaper's tab header
(``X-Nexpaper-Client``): MCP and the OAuth of programs (mcp 1.1.0), trading, revoking and retiring tokens between nex
apps (verbinden 0.1.1). A page without the header stays refused everywhere else (400 ``client_required``). The contract
tests send the header for everybody, so they would not see a program turned away here."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.services import settings_service

from .conftest import TAB, new_client, person


@pytest.fixture
def program() -> TestClient:
    with SessionLocal() as db:
        settings_service.save(db, {"mcp_enabled": True})
    return TestClient(app, base_url="http://testserver")


def test_a_program_needs_no_tab_header_at_the_places_of_the_modules(program: TestClient) -> None:
    assert "x-nexpaper-client" not in {name.lower() for name in program.headers}
    registered = program.post("/api/oauth/register", json={"client_name": "Probe",
                                                           "redirect_uris": ["http://127.0.0.1:33418/callback"]})
    assert registered.status_code == 201, registered.text
    for path in ("/api/oauth/token", "/api/oauth/revoke", "/api/connect/token", "/api/connect/revoke",
                 "/api/connect/retire"):
        answer = program.post(path, data={"token": "x"})
        assert answer.status_code != 400 or answer.json().get("detail", {}).get("code") != "client_required", path
    answer = program.post("/api/mcp", headers={"Authorization": "Bearer npm_" + "x" * 43},
                          json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert answer.status_code == 401 and answer.json()["detail"]["code"] == "key_invalid"


def test_a_page_without_the_tab_header_stays_refused_elsewhere() -> None:
    with person("anna") as browser:
        browser.headers.pop("X-Nexpaper-Client", None)
        refused = browser.put("/api/v1/me/preferences", json={"ai": False})
        assert refused.status_code == 400 and refused.json()["detail"]["code"] == "client_required"
        refused = browser.post("/api/connect/partners/nextime/start", json={"address": "https://time.example.com"})
        assert refused.status_code == 400 and refused.json()["detail"]["code"] == "client_required"
        refused = browser.post("/api/v1/connections/mcp/requests/1/approve")
        assert refused.status_code == 400 and refused.json()["detail"]["code"] == "client_required"
    with new_client(None) as anonymous:
        assert anonymous.headers.get("X-Nexpaper-Client") == TAB["X-Nexpaper-Client"]
