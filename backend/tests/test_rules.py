"""Rules: who may make which, their order, their hits, what they set when a document arrives, and that their words are
plain text, never a pattern. "Als Regel merken" makes one from a document in the inbox."""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, Rule
from app.services import rules

from .conftest import make_account, new_client
from .files import make_pdf
from .intake import upload_and_read
from .papers import own_vault, shared_vault


def sender_is(name: str) -> list[dict[str, Any]]:
    return [{"field": "sender", "op": "is", "values": [name]}]


def text_has(*words: str) -> list[dict[str, Any]]:
    return [{"field": "text", "op": "contains", "values": list(words)}]


def kind_id(client: TestClient, key: str) -> int:
    return next(k["id"] for k in client.get("/api/v1/kinds").json() if k["key"] == key)


def test_who_may_make_which_rule(client: TestClient, operator: Account) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    household = shared_vault("Haushalt", operator, (jule, "manage"), (tom, "edit"))
    then = [{"field": "tag", "value": "strom"}]
    with new_client(jule) as browser:
        mine = browser.post("/api/v1/rules", json={"vault_id": own_vault(jule), "when": text_has("Strom"),
                                                   "then": then})
        assert mine.status_code == 201
        assert browser.post("/api/v1/rules", json={"vault_id": household, "when": text_has("x"),
                                                   "then": then}).status_code == 201
        # Not somebody else's vault, and not the whole server.
        assert browser.post("/api/v1/rules", json={"vault_id": own_vault(tom), "when": text_has("x"),
                                                   "then": then}).status_code == 404
        assert browser.get("/api/v1/settings/rules").status_code == 403
        assert browser.post("/api/v1/settings/rules", json={"when": text_has("x"), "then": then}).status_code == 403
        # Moving only into a vault the maker may add to.
        moving = browser.post("/api/v1/rules", json={"vault_id": own_vault(jule), "when": text_has("x"),
                                                     "then": [{"field": "vault", "value": own_vault(tom)}]})
        assert moving.status_code == 404
    with new_client(tom) as browser:
        # Edit is not enough to make the rules of a vault; the rules of others are not even seen.
        assert browser.post("/api/v1/rules", json={"vault_id": household, "when": text_has("x"),
                                                   "then": then}).status_code == 403
        assert browser.get("/api/v1/rules").json() == []
        assert browser.patch(f"/api/v1/rules/{mine.json()['id']}", json={"on": False}).status_code == 404
        assert browser.delete(f"/api/v1/rules/{mine.json()['id']}").status_code == 404
    server = client.post("/api/v1/settings/rules", json={"when": text_has("Steuerbescheid"), "then": then})
    assert server.status_code == 201 and server.json()["vault_id"] is None
    # The operator's rules are not reached through /rules, and the vault's not through /settings/rules.
    assert client.patch(f"/api/v1/rules/{server.json()['id']}", json={"on": False}).status_code == 404
    assert client.delete(f"/api/v1/settings/rules/{mine.json()['id']}").status_code == 404
    with new_client(jule) as browser:
        token = browser.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with TestClient(client.app, base_url="http://testserver") as device:
        bearer = {"Authorization": f"Bearer {token}"}
        assert len(device.get("/api/v1/rules", headers=bearer).json()) == 2
        assert device.get("/api/v1/settings/rules", headers=bearer).status_code == 403


def test_what_a_rule_may_hold(client: TestClient, operator: Account) -> None:
    vault = own_vault(operator)
    bad = [
        [{"field": "sender", "op": "over", "values": ["x"]}],
        [{"field": "text", "op": "contains", "values": []}],
        [{"field": "text", "op": "contains", "values": ["x" * (rules.VALUE_MAX + 1)]}],
        [{"field": "text", "op": "contains", "values": ["a\u0000b"]}],
        [{"field": "text", "op": "contains", "values": ["x"] * (rules.MAX_VALUES + 1)}],
        [{"field": "amount", "op": "over", "value": "10"}],
        [{"field": "source", "op": "is", "value": "telepathy"}],
        [{"field": "kind", "op": "is", "value": 99999}],
        text_has("x") * (rules.MAX_CONDITIONS + 1),
    ]
    for when in bad:
        answer = client.post("/api/v1/rules", json={"vault_id": vault, "when": when,
                                                    "then": [{"field": "tag", "value": "x"}]})
        assert answer.status_code in (404, 422), (when, answer.status_code)
    for then in ([{"field": "title", "value": "{secret}"}], [{"field": "kind", "value": 1}, {"field": "kind",
                                                                                            "value": 1}],
                 [{"field": "colour", "value": "red"}]):
        answer = client.post("/api/v1/rules", json={"vault_id": vault, "when": text_has("x"), "then": then})
        assert answer.status_code == 422, then


def test_the_number_of_rules_is_limited(client: TestClient, operator: Account, monkeypatch: Any) -> None:
    monkeypatch.setattr(rules, "MAX_PER_VAULT", 2)
    body = {"vault_id": own_vault(operator), "when": text_has("x"), "then": [{"field": "tag", "value": "x"}]}
    assert [client.post("/api/v1/rules", json=body).status_code for _ in range(3)] == [201, 201, 409]


def test_a_rule_fills_in_a_new_document_and_counts_its_hit(client: TestClient, operator: Account) -> None:
    household = shared_vault("Haushalt", operator)
    invoice = kind_id(client, "invoice")
    rule = client.post("/api/v1/rules", json={"vault_id": own_vault(operator), "when": text_has("Stadtwerke"), "then": [
        {"field": "vault", "value": household}, {"field": "kind", "value": invoice}, {"field": "tag", "value": "strom"},
        {"field": "sender", "value": "Stadtwerke Lindenau"},
        {"field": "title", "value": "Strom {monat} {jahr}"}]}).json()
    document = upload_and_read(client, "scan.pdf", make_pdf([("Stadtwerke Lindenau\nRechnungsdatum 01.10.2026\n"
                                                              "Gesamtbetrag 86,40 EUR")]))
    assert document["vault_id"] == household and document["kind"]["id"] == invoice and document["tags"] == ["strom"]
    assert document["sender"]["name"] == "Stadtwerke Lindenau" and document["title"] == "Strom Oktober 2026"
    assert document["date"] == "2026-10-01" and document["amount"] == 8640
    assert {k: document["suggest"][k] for k in ("vault", "kind", "tags", "sender", "title", "date", "amount")} == {
        "vault": "rule", "kind": "rule", "tags": "rule", "sender": "rule", "title": "rule", "date": "text",
        "amount": "text"}
    shown = client.get("/api/v1/rules").json()
    assert shown[0]["id"] == rule["id"] and shown[0]["hits"] == 1 and shown[0]["last_hit_at"]
    # The history says that and from where, never the values.
    events = client.get(f"/api/v1/documents/{document['id']}/events").json()
    proposed = [e for e in events if e["action"] == "proposed"]
    assert proposed and "Stadtwerke" not in str(proposed)
    moved = [e for e in events if e["action"] == "moved"]
    assert moved and moved[0]["detail"]["by"] == "rule"


def test_the_first_rule_wins_and_tags_add_up(client: TestClient, operator: Account) -> None:
    vault = own_vault(operator)
    first = client.post("/api/v1/rules", json={"vault_id": vault, "when": text_has("Lindenhof"), "then": [
        {"field": "sender", "value": "Erste"}, {"field": "tag", "value": "eins"}]}).json()
    second = client.post("/api/v1/rules", json={"vault_id": vault, "when": text_has("lindenhof"), "then": [
        {"field": "sender", "value": "Zweite"}, {"field": "tag", "value": "zwei"}]}).json()
    off = client.post("/api/v1/rules", json={"vault_id": vault, "when": text_has("Lindenhof"), "on": False, "then": [
        {"field": "tag", "value": "aus"}]}).json()
    document = upload_and_read(client, "a.pdf", make_pdf(["Ferienwohnung Lindenhof 12a"]))
    assert document["sender"]["name"] == "Erste" and document["tags"] == ["eins", "zwei"]
    # The order changed: the second rule first.
    assert client.patch(f"/api/v1/rules/{second['id']}", json={"position": 1}).status_code == 200
    assert [r["id"] for r in client.get("/api/v1/rules").json()] == [second["id"], first["id"], off["id"]]
    document = upload_and_read(client, "b.pdf", make_pdf(["Ferienwohnung LINDENHOF 12a, zweiter Brief"]))
    assert document["sender"]["name"] == "Zweite"
    hits = {r["id"]: r["hits"] for r in client.get("/api/v1/rules").json()}
    assert hits == {first["id"]: 2, second["id"]: 2, off["id"]: 0}


def test_conditions_on_sender_kind_source_and_amount() -> None:
    subject = rules.Subject(sender="Stadtwerke Lindenau GmbH", text="Rechnung über Strom", kind_id=3, source="mail",
                            amount=8640)

    def holds(**condition: Any) -> bool:
        return rules.holds(condition, subject)

    assert holds(field="sender", op="contains", values=["stadtwerke"])
    assert not holds(field="sender", op="is", values=["Stadtwerke Lindenau"])
    assert holds(field="sender", op="is", values=["STADTWERKE LINDENAU GMBH"])
    assert holds(field="text", op="contains", values=["nichts", "UBER STROM"])  # accents and case aside
    assert holds(field="kind", op="is", value=3) and not holds(field="kind", op="is", value=4)
    assert holds(field="source", op="is", value="mail") and not holds(field="source", op="is", value="upload")
    assert holds(field="amount", op="over", value=5000) and not holds(field="amount", op="under", value=5000)
    assert not rules.holds({"field": "amount", "op": "over", "value": 1}, rules.Subject("", "", None, "upload", None))


def test_the_words_of_a_rule_are_no_pattern() -> None:
    hostile = "(a+)+$" + "[" + "\\"
    subject = rules.Subject(sender="", text="a" * 50_000 + "!", kind_id=None, source="upload", amount=None)
    started = time.monotonic()
    assert not rules.holds({"field": "text", "op": "contains", "values": [hostile, ".*", "a+"]}, subject)
    assert rules.holds({"field": "text", "op": "contains", "values": ["aaa!"]}, subject)
    assert time.monotonic() - started < 1.0


def test_a_title_pattern_takes_only_its_placeholders() -> None:
    from datetime import date

    made = rules.render_title("{art} {monat} {year} {betrag} {nope} {sender.__class__}", sender="X", kind="Rechnung",
                              day=date(2026, 3, 14), amount=123456, currency="EUR", language="de")
    assert made == "Rechnung März 2026 1.234,56 EUR {nope} {sender.__class__}"


def test_the_operators_rules_leave_the_vaults_of_others(client: TestClient, operator: Account) -> None:
    jule = make_account("jule")
    shared = shared_vault("Firma", operator, (jule, "edit"))
    client.post("/api/v1/settings/rules", json={"when": text_has("Gehalt"), "then": [
        {"field": "vault", "value": shared}, {"field": "tag", "value": "gehalt"}]})
    with new_client(jule) as browser:
        document = upload_and_read(browser, "lohn.pdf", make_pdf(["Gehaltsabrechnung Oktober"]))
    # The operator's rule for the whole server does nothing in jule's own vault: it takes nothing out of it and sets
    # nothing in it; its counter does not tell the operator that a document of jule's matched.
    assert document["vault_id"] == own_vault(jule) and document["tags"] == []
    assert client.get("/api/v1/settings/rules").json()[0]["hits"] == 0


def test_a_rule_for_the_whole_server_never_reaches_a_personal_vault_of_somebody_else(client: TestClient,
                                                                                      operator: Account) -> None:
    """Whatever the rule would set (kind, tag, sender, title, vault) stays undone in the personal vault of another
    person, and the rule counts nothing there; in a shared vault the same rule works, and in the operator's own
    personal vault too."""
    jule = make_account("jule")
    shared = shared_vault("Haushalt", operator, (jule, "edit"))
    invoice = kind_id(client, "invoice")
    made = client.post("/api/v1/settings/rules", json={"when": text_has("Diagnose"), "then": [
        {"field": "kind", "value": invoice}, {"field": "tag", "value": "orakel"}, {"field": "sender", "value": "Orakel"},
        {"field": "title", "value": "Befund {sender}"}, {"field": "vault", "value": shared}]})
    assert made.status_code == 201, made.text
    with new_client(jule) as browser:
        private = upload_and_read(browser, "befund.pdf", make_pdf(["Geheimer Befund Diagnose"]), own_vault(jule))
        common = upload_and_read(browser, "befund2.pdf", make_pdf(["Geheimer Befund Diagnose"]), shared)
    assert private["vault_id"] == own_vault(jule) and private["tags"] == [] and private["kind"] is None
    assert private["sender"] is None and private["title"] == "befund"
    assert all(origin != "rule" for origin in private["suggest"].values())
    assert client.get("/api/v1/settings/rules").json()[0]["hits"] == 1  # the one in the shared vault
    assert common["tags"] == ["orakel"] and common["sender"]["name"] == "Orakel" and common["kind"]["key"] == "invoice"
    mine = upload_and_read(client, "eigen.pdf", make_pdf(["Eigene Diagnose"]), own_vault(operator))
    assert mine["tags"] == ["orakel"] and mine["vault_id"] == shared  # the operator's own vault: the rule's maker


def test_a_rule_never_moves_where_the_person_may_not_add(client: TestClient, operator: Account) -> None:
    jule = make_account("jule")
    shared = shared_vault("Firma", operator, (jule, "read"))
    with new_client(jule) as browser:
        # jule's own rule names a vault jule may add to when made; then jule's right there is taken down to read.
        shared_edit = shared_vault("Familie", operator, (jule, "edit"))
        rule = browser.post("/api/v1/rules", json={"vault_id": own_vault(jule), "when": text_has("Brief"), "then": [
            {"field": "vault", "value": shared_edit}]})
        assert rule.status_code == 201
        assert browser.post("/api/v1/rules", json={"vault_id": own_vault(jule), "when": text_has("Brief"), "then": [
            {"field": "vault", "value": shared}]}).status_code == 403
    client.put(f"/api/v1/vaults/{shared_edit}/members/{jule.id}", json={"right": "read"})
    with new_client(jule) as browser:
        document = upload_and_read(browser, "brief.pdf", make_pdf(["Ein Brief an jule"]))
    assert document["vault_id"] == own_vault(jule)


def test_remember_as_a_rule(client: TestClient, operator: Account) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    household = shared_vault("Haushalt", operator, (jule, "edit"), (tom, "edit"))
    with new_client(jule) as browser:
        document = upload_and_read(browser, "a.pdf", make_pdf(["Stadtwerke Lindenau, Abschlag"]))
        path = f"/api/v1/documents/{document['id']}/rule"
        # Without a sender there is nothing to say "always" about.
        assert browser.post(path, json={"vault_id": household}).json()["detail"]["code"] == "rule_needs_sender"
        browser.patch(f"/api/v1/documents/{document['id']}", json={"sender": "Stadtwerke Lindenau"})
        assert browser.post(path, json={}).status_code == 422
        made = browser.post(path, json={"vault_id": household, "kind_id": kind_id(browser, "invoice"),
                                        "tags": ["strom"]})
        assert made.status_code == 201
        rule = made.json()
        assert rule["vault_id"] == own_vault(jule) and rule["when"] == sender_is("Stadtwerke Lindenau")
        assert [a["field"] for a in rule["then"]] == ["vault", "kind", "tag"]
    with new_client(tom) as browser:
        # tom may change the document (it is moved to the household later) but does not manage jule's vault.
        assert browser.post(f"/api/v1/documents/{document['id']}/rule", json={"tags": ["x"]}).status_code == 404
    with SessionLocal() as db:
        assert len(db.scalars(select(Rule)).all()) == 1


def test_a_deleted_vault_or_kind_leaves_the_rest_of_a_rule(client: TestClient, operator: Account) -> None:
    vault = own_vault(operator)
    kind = client.post("/api/v1/kinds", json={"name": "Wegwerf"}).json()["id"]
    client.post("/api/v1/rules", json={"vault_id": vault, "when": text_has("Wegwerf"), "then": [
        {"field": "kind", "value": kind}, {"field": "tag", "value": "bleibt"}]})
    client.delete(f"/api/v1/kinds/{kind}")
    document = upload_and_read(client, "w.pdf", make_pdf(["Wegwerf Brief"]))
    assert document["kind"] is None and document["tags"] == ["bleibt"]


def test_a_rule_moves_only_where_the_person_of_the_document_may_add(client: TestClient, operator: Account) -> None:
    tom = make_account("tom")
    firma = shared_vault("Firma", operator, (tom, "edit"))
    archive = shared_vault("Archiv", operator)
    assert client.post("/api/v1/rules", json={"vault_id": firma, "when": text_has("Lieferschein"), "then": [
        {"field": "vault", "value": archive}, {"field": "tag", "value": "lager"}]}).status_code == 201
    with new_client(tom) as browser:
        document = upload_and_read(browser, "l.pdf", make_pdf(["Lieferschein 4711"]), firma)
    # The operator may add to the archive, tom may not: the document stays where tom put it, the tag comes.
    assert document["vault_id"] == firma and document["tags"] == ["lager"]
    mine = upload_and_read(client, "m.pdf", make_pdf(["Lieferschein 4712"]), firma)
    assert mine["vault_id"] == archive


def test_remember_asks_for_manage_before_anything_else(client: TestClient, operator: Account) -> None:
    tom = make_account("tom")
    firma = shared_vault("Firma", operator, (tom, "edit"))
    with new_client(tom) as browser:
        document = upload_and_read(browser, "x.pdf", make_pdf(["Ein Brief ohne Absender"]), firma)
        answer = browser.post(f"/api/v1/documents/{document['id']}/rule", json={"tags": ["x"]})
    # Not "give it a sender first": tom may not make rules here at all.
    assert answer.status_code == 403


def test_a_rule_stops_moving_when_its_maker_may_no_longer_add_to_the_target(client: TestClient,
                                                                           operator: Account) -> None:
    """The maker's right is looked at when a document arrives, not only when the rule was made."""
    from app.services import vaults

    jule, tom = make_account("jule"), make_account("tom")
    source = shared_vault("Quelle", operator, (jule, "manage"), (tom, "edit"))
    target = shared_vault("Ziel", operator, (jule, "edit"), (tom, "edit"))
    with new_client(jule) as browser:
        made = browser.post("/api/v1/rules", json={"vault_id": source, "when": text_has("Gasrechnung"),
                                                   "then": [{"field": "vault", "value": target}]})
        assert made.status_code == 201, made.text
    with new_client(tom) as browser:
        moved = upload_and_read(browser, "gas1.pdf", make_pdf(["Gasrechnung Oktober"]), source)
    assert moved["vault_id"] == target
    with SessionLocal() as db:
        vaults.set_member(db, operator.id, target, jule.id, "read")
    with new_client(tom) as browser:
        kept = upload_and_read(browser, "gas2.pdf", make_pdf(["Gasrechnung November"]), source)
    assert kept["vault_id"] == source
