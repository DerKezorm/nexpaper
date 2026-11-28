"""The reference of a document (issue #13): one free field per document, named by each vault, in the API, the rules,
the search, the tools for AI programs and the list of an export."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models import EDIT, READ, Account
from app.services import documents, mcp_store
from app.vendor.nexmcp.brake import BRAKE

from .conftest import make_account, new_client
from .files import make_pdf
from .intake import upload_and_read
from .papers import add_document, document, own_vault, shared_vault


def reference_of(browser: TestClient, document_id: int) -> str:
    answer = browser.get(f"/api/v1/documents/{document_id}")
    assert answer.status_code == 200, answer.text
    return str(answer.json()["reference"])


def test_a_document_carries_one_reference(client: TestClient, operator: Account) -> None:
    made = add_document(own_vault(operator), operator, "Befund")
    assert reference_of(client, made) == ""
    changed = client.patch(f"/api/v1/documents/{made}", json={"reference": "  N°  4711 "})
    assert changed.status_code == 200 and changed.json()["reference"] == "N° 4711"
    # The history names the field, never its value.
    lines = client.get(f"/api/v1/documents/{made}/events").json()
    assert lines[0]["detail"]["fields"] == ["reference"] and "4711" not in str(lines)
    # The same value again changes nothing, and writes no line.
    assert client.patch(f"/api/v1/documents/{made}", json={"reference": "N° 4711"}).status_code == 200
    assert len(client.get(f"/api/v1/documents/{made}/events").json()) == len(lines)
    for wrong in ("a\u0000b", "x" * (documents.REFERENCE_MAX + 1)):
        refused = client.patch(f"/api/v1/documents/{made}", json={"reference": wrong})
        assert refused.status_code == 422 and refused.json()["detail"]["code"] == "invalid_reference"
    assert reference_of(client, made) == "N° 4711"
    # Empty and null take it away.
    assert client.patch(f"/api/v1/documents/{made}", json={"reference": ""}).json()["reference"] == ""
    client.patch(f"/api/v1/documents/{made}", json={"reference": "P1"})
    assert client.patch(f"/api/v1/documents/{made}", json={"reference": None}).json()["reference"] == ""


def test_only_who_may_change_the_document_sets_it_and_a_move_keeps_it(client: TestClient, operator: Account) -> None:
    reader, editor = make_account("rita"), make_account("eddi")
    practice = shared_vault("Praxis", operator, (reader, READ), (editor, EDIT))
    made = add_document(practice, operator, "Röntgenbild")
    with new_client(reader) as browser:
        assert browser.patch(f"/api/v1/documents/{made}", json={"reference": "17"}).status_code == 403
    with new_client(editor) as browser:
        assert browser.patch(f"/api/v1/documents/{made}", json={"reference": "17"}).json()["reference"] == "17"
    assert client.post(f"/api/v1/documents/{made}/move", json={"vault_id": own_vault(operator)}).status_code == 200
    assert reference_of(client, made) == "17"


def test_the_list_finds_a_reference_and_the_ones_without(client: TestClient, operator: Account) -> None:
    vault = own_vault(operator)
    first, second, other, none = (add_document(vault, operator, title) for title in ("A", "B", "C", "D"))
    for number, value in ((first, "P 4711"), (second, "p 4711"), (other, "P 47112")):
        client.patch(f"/api/v1/documents/{number}", json={"reference": value})

    def ids(**query: Any) -> set[int]:
        answer = client.get("/api/v1/documents", params=query)
        assert answer.status_code == 200, answer.text
        return {item["id"] for item in answer.json()["items"]}

    # The very reference, blanks joined and the case of the letters aside; not one that only begins so.
    assert ids(reference=" p  4711") == {first, second}
    assert ids(has_reference=True) == {first, second, other}
    assert ids(has_reference=False) == {none}
    assert ids(reference="P 4711", vault_id=vault) == {first, second}
    # Nobody else sees them through the filter.
    with new_client(make_account("fremd")) as browser:
        assert browser.get("/api/v1/documents", params={"reference": "P 4711"}).json()["items"] == []


def test_each_vault_names_the_field_or_hides_it(client: TestClient, operator: Account) -> None:
    manager, editor = make_account("mara"), make_account("emil")
    practice = shared_vault("Praxis", operator, (manager, "manage"), (editor, EDIT))
    mine = own_vault(manager)
    with new_client(manager) as browser:
        before = browser.get(f"/api/v1/vaults/{practice}").json()
        assert (before["reference_name"], before["reference_hidden"]) == ("", False)
        named = browser.patch(f"/api/v1/vaults/{practice}", json={"reference_name": "  Patientenakte "})
        assert named.status_code == 200 and named.json()["reference_name"] == "Patientenakte"
        # A personal vault keeps its person's name, but names and hides its field.
        assert browser.patch(f"/api/v1/vaults/{mine}", json={"name": "Anders"}).status_code == 409
        hidden = browser.patch(f"/api/v1/vaults/{mine}", json={"reference_hidden": True, "reference_name": "Akte"})
        assert hidden.status_code == 200
        assert (hidden.json()["reference_name"], hidden.json()["reference_hidden"]) == ("Akte", True)
        assert browser.patch(f"/api/v1/vaults/{mine}", json={"reference_name": ""}).json()["reference_name"] == ""
        too_long = browser.patch(f"/api/v1/vaults/{practice}", json={"reference_name": "x" * 41})
        assert too_long.status_code == 422 and too_long.json()["detail"]["code"] == "invalid_reference_name"
        assert browser.patch(f"/api/v1/vaults/{practice}", json={"reference_name": "a\u200bb"}).status_code == 422
    with new_client(editor) as browser:
        # Every member reads it; only a manager changes it.
        listed = {v["id"]: v for v in browser.get("/api/v1/vaults").json()}
        assert listed[practice]["reference_name"] == "Patientenakte"
        assert browser.patch(f"/api/v1/vaults/{practice}", json={"reference_hidden": True}).status_code == 403


def _rule(browser: TestClient, vault_id: int, when: list[dict[str, Any]], then: list[dict[str, Any]]) -> Any:
    return browser.post("/api/v1/rules", json={"vault_id": vault_id, "when": when, "then": then})


def test_what_a_rule_on_the_reference_may_hold(client: TestClient, operator: Account) -> None:
    vault = own_vault(operator)
    text = {"field": "text", "op": "contains", "values": ["x"]}
    tag = [{"field": "tag", "value": "akte"}]
    for wrong_when in ([{"field": "reference", "op": "over", "value": 3}],
                       [{"field": "reference", "op": "is", "values": []}],
                       [{"field": "reference", "op": "contains"}]):
        assert _rule(client, vault, wrong_when, tag).status_code == 422, wrong_when
    for wrong_then in ([{"field": "reference", "value": ""}], [{"field": "reference", "value": "a\u0001"}],
                       [{"field": "reference", "value": "x" * 101}], [{"field": "reference", "value": 3}],
                       [{"field": "title", "value": "{refx}"}]):
        assert _rule(client, vault, [text], wrong_then).status_code == 422, wrong_then
    made = _rule(client, vault, [{"field": "reference", "op": "empty", "values": ["ignored"]},
                                 {"field": "reference", "op": "contains", "values": ["N° 1"]}],
                 [{"field": "reference", "value": " P  1 "}, {"field": "title", "value": "Akte {ref} {az}"}])
    assert made.status_code == 201, made.text
    assert made.json()["when"][0] == {"field": "reference", "op": "empty"}
    assert made.json()["then"][0] == {"field": "reference", "value": "P 1"}


def test_a_rule_sets_the_reference_and_the_title_names_it(client: TestClient, operator: Account) -> None:
    vault = own_vault(operator)
    assert _rule(client, vault, [{"field": "text", "op": "contains", "values": ["Patient 4711"]},
                                 {"field": "reference", "op": "empty"}],
                 [{"field": "reference", "value": "PAT-4711"},
                  {"field": "title", "value": "PATIENT{ref} - {sender}"},
                  {"field": "sender", "value": "Praxis Lindenau"}]).status_code == 201
    found = upload_and_read(client, "befund.pdf", make_pdf(["Befundbericht Patient 4711"]))
    assert found["reference"] == "PAT-4711"
    assert found["title"] == "PATIENTPAT-4711 - Praxis Lindenau"
    assert found["suggest"]["reference"] == "rule"
    # Another letter does not match.
    other = upload_and_read(client, "brief.pdf", make_pdf(["Ein anderer Brief"]))
    assert other["reference"] == "" and "reference" not in other["suggest"]


def test_what_a_person_set_stays_and_the_rules_see_it(client: TestClient, operator: Account) -> None:
    vault = own_vault(operator)
    waiting = upload_and_read(client, "akte.pdf", make_pdf(["Kontrolltermin Zahnreinigung"]))
    assert waiting["status"] == "inbox"
    client.patch(f"/api/v1/documents/{waiting['id']}", json={"reference": "N° 17"})
    # A rule for documents still without a reference, and one for this reference.
    assert _rule(client, vault, [{"field": "reference", "op": "empty"}],
                 [{"field": "reference", "value": "OHNE"}, {"field": "tag", "value": "fehlt"}]).status_code == 201
    assert _rule(client, vault, [{"field": "reference", "op": "is", "values": ["n° 17"]}],
                 [{"field": "tag", "value": "patient-17"}]).status_code == 201
    done = client.post("/api/v1/inbox/sort-again", json={"ids": [waiting["id"]]})
    assert done.status_code == 200, done.text
    after = client.get(f"/api/v1/documents/{waiting['id']}").json()
    assert after["reference"] == "N° 17" and after["suggest"]["reference"] == "person"
    assert after["tags"] == ["patient-17"]


def test_the_search_finds_a_reference_with_az_and_ref(client: TestClient, operator: Account) -> None:
    vault = own_vault(operator)
    wanted, other = add_document(vault, operator, "Befund"), add_document(vault, operator, "Rechnung")
    client.patch(f"/api/v1/documents/{wanted}", json={"reference": "Akte 4711_b"})
    client.patch(f"/api/v1/documents/{other}", json={"reference": "Akte 4711xb"})
    for query in ("az:4711_b", "ref:akte", 'aktenzeichen:"AKTE 4711_"'):
        answer = client.get("/api/v1/search", params={"q": query})
        assert answer.status_code == 200, answer.text
        found = {item["document"]["id"] for item in answer.json()["items"]}
        assert found == ({wanted, other} if query == "ref:akte" else {wanted}), query
    assert client.get("/api/v1/search", params={"q": "az:4711"}).json()["understood"]["references"] == ["4711"]


@pytest.fixture
def mcp_open() -> None:
    from app.db import SessionLocal
    from app.services import settings_service

    BRAKE.forget()
    with SessionLocal() as db:
        settings_service.save(db, {"mcp_enabled": True})


def test_the_tools_for_ai_read_and_set_it(mcp_open: None) -> None:
    from .test_mcp_tools import call, data, key

    owner = make_account("owen")
    made = add_document(own_vault(owner), owner, "Befund")
    with new_client(owner) as browser:
        secret = key(browser, right="write")
    assert data(call(secret, "read_document", {"document_id": made}))["reference"] is None
    changed = data(call(secret, "set_document_fields", {"document_id": made, "reference": "N° 12"}))
    assert changed["reference"] == "N° 12" and document(made).reference == "N° 12"
    assert data(call(secret, "set_document_fields", {"document_id": made, "reference": ""}))["reference"] is None
    tool = next(t for t in mcp_store.MCP.tools if t.name == "set_document_fields")
    assert "reference" in tool.input_schema["properties"]
