"""Sorting again (issue #11): a rule made while documents already wait in the inbox. First a look that changes nothing,
then the change for the documents ticked; what a person set stays, and only the inbox the caller may change is touched."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models import Account
from app.services import sort_again

from .conftest import make_account, new_client
from .files import make_pdf
from .intake import upload_and_read
from .papers import own_vault, shared_vault

LOOK = "/api/v1/inbox/sort-again/preview"
APPLY = "/api/v1/inbox/sort-again"


def text_has(*words: str) -> list[dict[str, Any]]:
    return [{"field": "text", "op": "contains", "values": list(words)}]


def document(client: TestClient, document_id: int) -> dict[str, Any]:
    answer = client.get(f"/api/v1/documents/{document_id}")
    assert answer.status_code == 200
    return answer.json()  # type: ignore[no-any-return]


def hits(client: TestClient) -> dict[int, int]:
    return {r["id"]: r["hits"] for r in client.get("/api/v1/rules").json()}


def test_the_look_changes_nothing_and_the_change_only_what_was_ticked(client: TestClient, operator: Account) -> None:
    garage = shared_vault("Chrysler 300", operator)
    first = upload_and_read(client, "a.pdf", make_pdf(["Autohaus Brandt\nInspektion Chrysler 300C"]))
    second = upload_and_read(client, "b.pdf", make_pdf(["Autohaus Brandt\nReifenwechsel Chrysler"]))
    other = upload_and_read(client, "c.pdf", make_pdf(["Stadtwerke Lindenau\nAbschlag Strom"]))
    rule = client.post("/api/v1/rules", json={"vault_id": own_vault(operator), "when": text_has("Chrysler"), "then": [
        {"field": "vault", "value": garage}, {"field": "tag", "value": "auto"}]})
    assert rule.status_code == 201, rule.text
    events_before = len(client.get(f"/api/v1/documents/{first['id']}/events").json())

    look = client.post(LOOK, json={})
    assert look.status_code == 200, look.text
    body = look.json()
    assert body["looked_at"] == 3 and body["total"] == 3 and body["next"] is None
    items = {i["before"]["id"]: i for i in body["items"]}
    assert set(items) == {first["id"], second["id"]}
    seen = items[first["id"]]
    assert seen["fields"] == ["tags", "vault"] and seen["origins"] == {"tags": "rule", "vault": "rule"}
    assert seen["before"]["vault_id"] == own_vault(operator) and seen["before"]["tags"] == []
    assert seen["after"]["vault_id"] == garage and seen["after"]["tags"] == ["auto"]
    # Nothing of it stayed: not the move, not the tag, not a line in the history, not a hit.
    for item in (first, second, other):
        now = document(client, item["id"])
        assert now["vault_id"] == own_vault(operator) and now["tags"] == []
    assert len(client.get(f"/api/v1/documents/{first['id']}/events").json()) == events_before
    assert hits(client) == {rule.json()["id"]: 0}

    done = client.post(APPLY, json={"ids": [first["id"], other["id"]]})
    assert done.status_code == 200, done.text
    assert done.json() == {"changed": [first["id"]], "moved": 1, "unchanged": 1, "skipped": 0, "failed": 0}
    moved = document(client, first["id"])
    assert moved["vault_id"] == garage and moved["tags"] == ["auto"] and moved["status"] == "inbox"
    assert moved["suggest"]["vault"] == "rule"
    assert document(client, second["id"])["vault_id"] == own_vault(operator)
    assert hits(client) == {rule.json()["id"]: 1}
    events = client.get(f"/api/v1/documents/{first['id']}/events").json()
    assert any(e["action"] == "moved" and e["detail"]["by"] == "rule" for e in events)
    # Again: nothing new for the one that moved.
    assert [i["before"]["id"] for i in client.post(LOOK, json={}).json()["items"]] == [second["id"]]
    assert client.post(APPLY, json={"ids": [first["id"]]}).json()["unchanged"] == 1
    assert hits(client) == {rule.json()["id"]: 1}


def test_what_a_person_set_stays_and_counts_for_the_rules(client: TestClient, operator: Account) -> None:
    """The sender the person gave the document is what a rule made with "Als Regel merken" looks for; the title the
    person wrote is not overwritten by a rule's pattern."""
    garage = shared_vault("Chrysler 300", operator)
    letter = upload_and_read(client, "brief.pdf", make_pdf(["Ein Brief ohne Briefkopf\nTermin bestaetigt"]))
    assert client.patch(f"/api/v1/documents/{letter['id']}",
                        json={"sender": "Autohaus Brandt", "title": "Mein Titel"}).status_code == 200
    made = client.post("/api/v1/rules", json={"vault_id": own_vault(operator), "when": [
        {"field": "sender", "op": "is", "values": ["Autohaus Brandt"]}], "then": [
        {"field": "vault", "value": garage}, {"field": "title", "value": "Werkstatt {jahr}"}]})
    assert made.status_code == 201, made.text
    look = client.post(LOOK, json={"ids": [letter["id"]]}).json()
    assert [i["fields"] for i in look["items"]] == [["vault"]]
    client.post(APPLY, json={"ids": [letter["id"]]})
    now = document(client, letter["id"])
    assert now["vault_id"] == garage and now["title"] == "Mein Titel" and now["sender"]["name"] == "Autohaus Brandt"
    assert now["suggest"]["title"] == "person" and now["suggest"]["sender"] == "person"


def test_a_vault_the_person_chose_stays(client: TestClient, operator: Account) -> None:
    garage = shared_vault("Chrysler 300", operator)
    household = shared_vault("Haushalt", operator)
    kept = upload_and_read(client, "k.pdf", make_pdf(["Chrysler Rechnung"]))
    assert client.post(f"/api/v1/documents/{kept['id']}/move", json={"vault_id": household}).status_code == 200
    assert document(client, kept["id"])["suggest"]["vault"] == "person"
    client.post("/api/v1/rules", json={"vault_id": own_vault(operator), "when": text_has("Chrysler"),
                                       "then": [{"field": "vault", "value": garage}, {"field": "tag", "value": "auto"}]})
    assert [i["fields"] for i in client.post(LOOK, json={}).json()["items"]] == [["tags"]]
    client.post(APPLY, json={"ids": [kept["id"]]})
    now = document(client, kept["id"])
    assert now["vault_id"] == household and now["tags"] == ["auto"]


def test_only_the_inbox_the_caller_may_change(client: TestClient, operator: Account) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    household = shared_vault("Haushalt", operator, (jule, "edit"), (tom, "read"))
    with new_client(jule) as browser:
        private = upload_and_read(browser, "p.pdf", make_pdf(["Chrysler privat"]))
        common = upload_and_read(browser, "c.pdf", make_pdf(["Chrysler gemeinsam"]), household)
        filed = upload_and_read(browser, "f.pdf", make_pdf(["Chrysler abgelegt"]), household)
        assert browser.post("/api/v1/inbox/file", json={"ids": [filed["id"]]}).json()["filed"] == [filed["id"]]
        assert browser.post("/api/v1/rules", json={"vault_id": own_vault(jule), "when": text_has("Chrysler"),
                                                   "then": [{"field": "tag", "value": "auto"}]}).status_code == 201
        assert browser.post("/api/v1/rules", json={"vault_id": household, "when": text_has("Chrysler"),
                                                   "then": [{"field": "tag", "value": "auto"}]}).status_code == 403
    ids = [private["id"], common["id"], filed["id"]]
    with new_client(tom) as browser:
        # tom only reads the household: nothing of jule's inbox is looked at or changed, not even counted.
        assert browser.post(LOOK, json={"ids": ids}).json() == {"items": [], "looked_at": 0, "total": 0,
                                                                "next": None}
        assert browser.post(APPLY, json={"ids": ids}).json() == {"changed": [], "moved": 0, "unchanged": 0,
                                                                 "skipped": 3, "failed": 0}
    with new_client(jule) as browser:
        look = browser.post(LOOK, json={"ids": ids}).json()
        # The filed one is no longer in the inbox; the rule of jule's own vault reaches only what arrived there.
        assert look["looked_at"] == 2 and [i["before"]["id"] for i in look["items"]] == [private["id"]]
        done = browser.post(APPLY, json={"ids": ids}).json()
        assert done["changed"] == [private["id"]] and done["skipped"] == 1
        assert document(browser, filed["id"])["tags"] == []


def test_a_move_out_of_sight_is_said(client: TestClient, operator: Account) -> None:
    """jule may change the household but not the operator's archive; the operator's rule moves a document of the
    operator's there. jule's look says so without showing the document afterwards."""
    jule = make_account("jule")
    household = shared_vault("Haushalt", operator, (jule, "edit"))
    archive = shared_vault("Archiv", operator)
    mine = upload_and_read(client, "m.pdf", make_pdf(["Lieferschein 4711"]), household)
    assert client.post("/api/v1/rules", json={"vault_id": household, "when": text_has("Lieferschein"),
                                              "then": [{"field": "vault", "value": archive}]}).status_code == 201
    with new_client(jule) as browser:
        items = browser.post(LOOK, json={}).json()["items"]
        assert [(i["before"]["id"], i["fields"], i["after"]) for i in items] == [(mine["id"], ["vault"], None)]


def test_what_is_asked_is_checked(client: TestClient, operator: Account) -> None:
    assert client.post(APPLY, json={}).status_code == 422
    assert client.post(APPLY, json={"ids": []}).status_code == 422
    assert client.post(LOOK, json={"ids": list(range(1, 1002))}).status_code == 422
    assert client.post(LOOK, json={"ids": ["1"]}).status_code == 422
    assert client.post(LOOK, json={"all": True}).status_code == 422
    assert client.post(APPLY, json={"ids": [999_999]}).json()["skipped"] == 1


def test_the_look_goes_a_step_at_a_time(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hundreds of documents are not looked at in one answer: ``next`` says where the next one goes on, until all were
    looked at once."""
    monkeypatch.setattr(sort_again, "STEP", 2)
    made = [upload_and_read(client, f"{n}.pdf", make_pdf([f"Chrysler Brief {n}"]))["id"] for n in range(5)]
    client.post("/api/v1/rules", json={"vault_id": own_vault(operator), "when": text_has("Chrysler"),
                                       "then": [{"field": "tag", "value": "auto"}]})
    seen: list[int] = []
    after = 0
    answers = 0
    while True:
        body = client.post(LOOK, json={"after": after}).json()
        answers += 1
        assert body["total"] == 5 and body["looked_at"] <= 2
        seen += [i["before"]["id"] for i in body["items"]]
        if body["next"] is None:
            break
        after = body["next"]
    assert seen == sorted(made) and answers == 3
    # With ids named, the same steps among those only.
    first = client.post(LOOK, json={"ids": made[1:4]}).json()
    assert first["total"] == 3 and [i["before"]["id"] for i in first["items"]] == made[1:3]
    rest = client.post(LOOK, json={"ids": made[1:4], "after": first["next"]}).json()
    assert [i["before"]["id"] for i in rest["items"]] == [made[3]] and rest["next"] is None


def test_a_title_pattern_takes_what_the_person_set(client: TestClient, operator: Account) -> None:
    """The date and the amount a person entered fill the placeholders of a rule's title, as they stand."""
    letter = upload_and_read(client, "s.pdf", make_pdf(["Abschlag Strom ohne Datum"]))
    assert client.patch(f"/api/v1/documents/{letter['id']}",
                        json={"date": "2026-03-14", "amount": 1234, "kind_id": None}).status_code == 200
    client.post("/api/v1/rules", json={"vault_id": own_vault(operator), "when": text_has("Abschlag"),
                                       "then": [{"field": "title", "value": "Strom {monat} {jahr} {betrag}"}]})
    items = client.post(LOOK, json={}).json()["items"]
    assert [i["after"]["title"] for i in items] == ["Strom März 2026 12,34 EUR"]
