"""nexpaper's tools for AI programs (the shared MCP module, mcp 1.1.0; Entwurf MCP-Modul, nexpaper): each goes through the
services of the web app with the rights of the key's account, sees only what the account sees (and only the vaults the
key was limited to), changes only with the level "write" and a right to change in the vault, and the log never names a
document. The module's walls, OAuth, rights and requests are the contract tests' (``tests/nexmcp``).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models import EDIT, READ, Account
from app.services import mcp_store, tell
from app.vendor.nexmcp.brake import BRAKE

from .conftest import make_account, new_client
from .papers import add_document, document, own_vault, shared_vault

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n"


@pytest.fixture(autouse=True)
def _mcp_open() -> None:
    from app.db import SessionLocal
    from app.services import settings_service

    BRAKE.forget()
    with SessionLocal() as db:
        settings_service.save(db, {"mcp_enabled": True})


def key(browser: TestClient, *, right: str = "write", areas: list[int] | None = None) -> str:
    body: dict[str, Any] = {"kind": "mcp", "name": "Notebook", "right": right}
    if areas is not None:
        body["areas"] = areas
    made = browser.post("/api/v1/connections/keys", json=body)
    assert made.status_code == 201, made.text
    return str(made.json()["secret"])


def call(secret: str, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    answer = TestClient(new_client().app).post(
        "/api/mcp", headers={"Authorization": f"Bearer {secret}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}})
    assert answer.status_code == 200, answer.text
    return answer.json()["result"]


def data(result: dict[str, Any]) -> Any:
    assert not result.get("isError"), result
    return result["structuredContent"]


def refused(result: dict[str, Any]) -> str:
    assert result.get("isError"), result
    return str(result["content"][0]["text"])


def names(secret: str) -> set[str]:
    answer = TestClient(new_client().app).post(
        "/api/mcp", headers={"Authorization": f"Bearer {secret}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    return {tool["name"] for tool in answer.json()["result"]["tools"]}


@pytest.fixture
def people() -> dict[str, Any]:
    owner, other = make_account("owen"), make_account("otto")
    boss = make_account("olli", "operator")
    office = shared_vault("Office", boss, (owner, READ), (other, EDIT))
    mine = add_document(own_vault(owner), owner, "Electricity October", sender="Example Power", amount=4200)
    waiting = add_document(own_vault(owner), owner, "Scan of today", status="inbox")
    theirs = add_document(own_vault(other), other, "Private letter")
    shared = add_document(office, other, "Office lease")
    return {"owner": owner, "other": other, "office": office, "mine": mine, "waiting": waiting, "theirs": theirs,
            "shared": shared, "browser": new_client(owner)}


def test_reading_tools_see_what_the_account_sees_and_nothing_else(people: dict[str, Any]) -> None:
    secret = key(people["browser"], right="read")
    vaults = {vault["id"] for vault in data(call(secret, "list_vaults"))["vaults"]}
    assert vaults == {own_vault(people["owner"]), people["office"]}
    found = data(call(secret, "read_document", {"document_id": people["mine"]}))
    assert (found["title"], found["sender"], found["amount_cents"]) == ("Electricity October", "Example Power", 4200)
    assert "text" in found and "file" not in json.dumps(list(found))
    assert data(call(secret, "read_document", {"document_id": people["shared"]}))["title"] == "Office lease"
    assert refused(call(secret, "read_document", {"document_id": people["theirs"]})) == "Not found."
    assert refused(call(secret, "read_document", {"document_id": 999_999})) == "Not found."
    hits = {hit["id"] for hit in data(call(secret, "search_documents", {"query": "e"}))["documents"]}
    assert people["theirs"] not in hits
    inbox = {entry["id"] for entry in data(call(secret, "list_inbox"))["documents"]}
    assert inbox == {people["waiting"]}
    assert set(data(call(secret, "list_deadlines"))) >= {"today", "overdue", "soon", "later"}


def test_a_key_limited_to_one_vault_sees_no_other(people: dict[str, Any]) -> None:
    secret = key(people["browser"], areas=[people["office"]])
    assert {vault["id"] for vault in data(call(secret, "list_vaults"))["vaults"]} == {people["office"]}
    assert refused(call(secret, "read_document", {"document_id": people["mine"]})) == "Not found."
    assert refused(call(secret, "search_documents", {"query": "e", "vault_id": own_vault(people["owner"])})) \
        == "Not found."
    hits = {hit["id"] for hit in data(call(secret, "search_documents", {"query": "e"}))["documents"]}
    assert people["mine"] not in hits
    assert refused(call(secret, "set_document_fields", {"document_id": people["mine"], "title": "x"})) == "Not found."
    assert document(people["mine"]).title == "Electricity October"


def test_a_reading_key_has_no_changing_tools(people: dict[str, Any]) -> None:
    secret = key(people["browser"], right="read")
    assert names(secret) == {"list_vaults", "search_documents", "read_document", "list_inbox", "list_deadlines",
                             "request_status"}
    assert "No tool called" in refused(call(secret, "trash_document", {"document_id": people["mine"]}))
    assert document(people["mine"]).status == "filed"


def test_changing_tools_change_only_what_the_account_may_change(people: dict[str, Any]) -> None:
    secret = key(people["browser"])
    changed = data(call(secret, "set_document_fields", {"document_id": people["mine"], "title": "Power October",
                                                        "amount_cents": 4300, "tags": ["home"]}))
    assert (changed["title"], changed["amount_cents"], changed["tags"]) == ("Power October", 4300, ["home"])
    # Reading only in the shared vault: the web app's refusal, nothing changed.
    assert refused(call(secret, "set_document_fields", {"document_id": people["shared"], "title": "Mine now"})) \
        != "Not found."
    assert document(people["shared"]).title == "Office lease"
    assert "date" in refused(call(secret, "set_document_fields", {"document_id": people["mine"], "date": "2026-02-31"}))
    filed = data(call(secret, "accept_suggestions", {"document_ids": [people["waiting"], people["theirs"]]}))
    assert filed["filed"] == [people["waiting"]] and filed["failed"] == [{"id": people["theirs"], "code": "not_found"}]
    assert document(people["waiting"]).status == "filed"
    assert data(call(secret, "trash_document", {"document_id": people["mine"]}))["trashed"] is True
    assert document(people["mine"]).status == "trash"


def test_a_waiting_request_tells_the_account_on_its_devices(people: dict[str, Any],
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    told: list[tuple[int, Any]] = []
    monkeypatch.setattr(tell, "person", lambda account_id, notice: told.append((account_id, notice)))
    browser = people["browser"]
    secret = key(browser)
    key_id = next(entry["id"] for entry in browser.get("/api/v1/connections/keys").json()["keys"]
                  if entry["kind"] == "mcp")
    assert browser.put(f"/api/v1/connections/mcp/keys/{key_id}/rights",
                       json={"rights": {"trash_document": "ask"}}).status_code == 200
    asked = data(call(secret, "trash_document", {"document_id": people["mine"]}))
    assert asked["status"] == "waiting" and document(people["mine"]).status == "filed"
    assert [account for account, _notice in told] == [people["owner"].id]
    notice = told[0][1]
    assert notice.url == f"/mcp/requests/{asked['request']}" and set(notice.texts) == {"de", "en", "fr"}
    assert "Notebook" in notice.texts["de"][1]


def test_the_log_names_the_tool_never_a_document(people: dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
    secret = key(people["browser"])
    with caplog.at_level(logging.DEBUG):
        call(secret, "read_document", {"document_id": people["mine"]})
        call(secret, "search_documents", {"query": "Electricity"})
        call(secret, "set_document_fields", {"document_id": people["mine"], "title": "Secret title"})
    said = "\n".join(record.getMessage() for record in caplog.records)
    assert "MCP tool called tool=read_document" in said
    for word in ("Electricity", "Example Power", "Secret title", "npm_"):
        assert word not in said


def test_without_ai_for_the_account_no_tool_answers(people: dict[str, Any]) -> None:
    from app.db import SessionLocal

    secret = key(people["browser"])
    with SessionLocal() as db:
        row = db.get(Account, people["owner"].id)
        assert row is not None
        row.ai_allowed = False
        db.commit()
    answer = TestClient(new_client().app).post(
        "/api/mcp", headers={"Authorization": f"Bearer {secret}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert answer.status_code == 401 and answer.json()["detail"]["code"] == "ai_rests"


@pytest.mark.parametrize("language", ["de", "en", "fr"])
def test_the_page_has_words_for_every_tool(language: str) -> None:
    words = json.loads((FRONTEND / f"{language}.json").read_text(encoding="utf-8"))["mcp"]
    assert list(words["tools"]) == [tool.name for tool in mcp_store.MCP.tools]
    assert set(words["levels"]) >= set(mcp_store.MCP.levels)
