"""Where each proposal comes from, and which wins: the e-invoice before a rule before "as last time" before the text.
"As last time" looks only at documents the person may see. A field the person changed is theirs."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models import Account

from . import einvoices as samples
from .conftest import make_account, new_client
from .files import make_pdf
from .intake import process_all, upload_and_read, upload_one
from .papers import own_vault, shared_vault

LETTER = ("Stadtwerke Lindenau GmbH\nKundennummer 4471-0923\nIBAN {iban}\nAbschlag Oktober\nRechnungsdatum 01.10.2026\n"
          "Gesamtbetrag 86,40 EUR")


def filed(client: TestClient, name: str, text: str, vault_id: int | None = None, **fields: object) -> dict:
    document = upload_and_read(client, name, make_pdf([text]), vault_id)
    answer = client.patch(f"/api/v1/documents/{document['id']}", json={**fields, "status": "filed"})
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_as_last_time_by_iban_customer_number_and_letterhead(client: TestClient, operator: Account) -> None:
    invoice = next(k["id"] for k in client.get("/api/v1/kinds").json() if k["key"] == "invoice")
    filed(client, "sep.pdf", LETTER.format(iban=samples.SELLER_IBAN), sender="Stadtwerke Lindenau", kind_id=invoice,
          tags=["strom", "haus"])
    for text in (LETTER.format(iban=samples.SELLER_IBAN).replace("Kundennummer 4471-0923", ""),
                 "Brief\nKundennummer 4471-0923\nNeue Abschläge",
                 "Stadtwerke Lindenau GmbH\nEin Brief ohne Nummern"):
        document = upload_and_read(client, "new.pdf", make_pdf([text]))
        assert document["sender"]["name"] == "Stadtwerke Lindenau", text
        assert document["kind"]["id"] == invoice and document["tags"] == ["haus", "strom"]
        assert (document["suggest"]["sender"], document["suggest"]["kind"], document["suggest"]["tags"]) == (
            "last_time", "last_time", "last_time")
    nothing = upload_and_read(client, "other.pdf", make_pdf(["Ein ganz anderer Brief\nIBAN " + samples.OTHER_IBAN]))
    assert nothing["sender"] is None and "sender" not in nothing["suggest"]


def test_as_last_time_sees_only_what_the_person_may_see(client: TestClient, operator: Account) -> None:
    tom = make_account("tom")
    with new_client(tom) as browser:
        filed(browser, "geheim.pdf", LETTER.format(iban=samples.SELLER_IBAN), sender="Toms Geheimnis")
    document = upload_and_read(client, "mine.pdf", make_pdf([LETTER.format(iban=samples.SELLER_IBAN)]))
    assert document["sender"] is None and "sender" not in document["suggest"]
    # Shared with the operator later, it counts.
    with new_client(tom) as browser:
        mine = browser.get("/api/v1/documents", params={"status": "filed"}).json()["items"][0]["id"]
        assert browser.put(f"/api/v1/documents/{mine}/shares/{operator.id}", json={"right": "read"}).status_code == 200
    document = upload_and_read(client, "again.pdf", make_pdf([LETTER.format(iban=samples.SELLER_IBAN)]))
    assert document["sender"]["name"] == "Toms Geheimnis"


def test_the_einvoice_wins_over_a_rule_and_a_rule_over_last_time(client: TestClient, operator: Account) -> None:
    vault = own_vault(operator)
    client.post("/api/v1/rules", json={"vault_id": vault, "when": [{"field": "text", "op": "contains",
                                                                    "values": ["Elektro Brandt"]}],
                                       "then": [{"field": "sender", "value": "Regel-Absender"},
                                                {"field": "tag", "value": "handwerker"}]})
    document = upload_and_read(client, "z.pdf", samples.zugferd_pdf())
    assert document["sender"]["name"] == "Elektro Brandt GmbH" and document["suggest"]["sender"] == "einvoice"
    assert document["tags"] == ["handwerker"] and document["suggest"]["tags"] == "rule"
    # Without the e-invoice the rule wins over last time.
    filed(client, "old.pdf", "Elektro Brandt GmbH\nIBAN " + samples.SELLER_IBAN, sender="Brandt alt")
    document = upload_and_read(client, "scan.pdf", make_pdf(["Elektro Brandt GmbH\nIBAN " + samples.SELLER_IBAN +
                                                             "\nSumme 224,91 EUR"]))
    assert document["sender"]["name"] == "Regel-Absender" and document["suggest"]["sender"] == "rule"
    assert document["amount"] == 22491 and document["suggest"]["amount"] == "text"


def test_a_field_the_person_changed_is_theirs(client: TestClient, operator: Account) -> None:
    shared = shared_vault("Haushalt", operator)
    client.post("/api/v1/rules", json={"vault_id": own_vault(operator), "when": [
        {"field": "text", "op": "contains", "values": ["Lindenau"]}], "then": [
        {"field": "vault", "value": shared}, {"field": "sender", "value": "Regel"}]})
    made = upload_one(client, "scan.pdf", make_pdf(["Stadtwerke Lindenau\nRechnungsdatum 01.10.2026"]))
    # While it is still being read, the person names it and its sender.
    assert client.patch(f"/api/v1/documents/{made['id']}", json={"title": "Mein Titel",
                                                                 "sender": "Meine Wahl"}).status_code == 200
    process_all()
    document = client.get(f"/api/v1/documents/{made['id']}").json()
    assert document["title"] == "Mein Titel" and document["sender"]["name"] == "Meine Wahl"
    assert document["suggest"]["title"] == "person" and document["suggest"]["sender"] == "person"
    assert document["vault_id"] == shared and document["suggest"]["vault"] == "rule"
    assert document["date"] == "2026-10-01" and document["suggest"]["date"] == "text"
    # Changed in the inbox: theirs too.
    client.patch(f"/api/v1/documents/{made['id']}", json={"date": "2026-09-30"})
    assert client.get(f"/api/v1/documents/{made['id']}").json()["suggest"]["date"] == "person"


def test_the_default_vault_is_said(client: TestClient, operator: Account) -> None:
    document = upload_and_read(client, "a.pdf", make_pdf(["Ein Brief"]))
    assert document["suggest"].get("vault") == "default"
    shared = shared_vault("Haushalt", operator)
    elsewhere = upload_and_read(client, "b.pdf", make_pdf(["Ein Brief"]), shared)
    assert "vault" not in elsewhere["suggest"]


def test_paperless_and_new_versions_get_no_proposals(client: TestClient, operator: Account) -> None:
    from app.db import SessionLocal
    from app.models import Document, Version
    from app.services import jobs

    made = upload_one(client, "p.pdf", make_pdf(["Rechnungsdatum 01.10.2026\nSumme 12,00 EUR"]))
    with SessionLocal() as db:
        version = db.query(Version).filter_by(document_id=made["id"]).one()
        version.note = "paperless"
        db.commit()
    jobs.run_pending(kinds=(jobs.PROCESS,))
    with SessionLocal() as db:
        document = db.get(Document, made["id"])
        assert document is not None and document.date is None and document.amount is None and not document.suggest
