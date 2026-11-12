"""The note on a sender ("Merkzettel", K1): the vault's, seen by its members at the document and under Ordnung, changed
with ``edit`` there; never through a share alone, a link, the AI or the log. A sender with a note is not tidied away;
merging two senders puts both notes one under the other; moving a document does not take the note along."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, Sender
from app.services import catalog, settings_service

from .conftest import make_account, new_client
from .papers import add_document, own_vault, shared_vault

NOTE = "Kundennummer 4711-0815\nTelefon 0000 123456"


def sender_of(client: TestClient, document_id: int) -> dict[str, Any]:
    found = client.get(f"/api/v1/documents/{document_id}").json()
    return {"id": found["sender"]["id"] if found["sender"] else None, "memo": found["sender_memo"]}


def set_note(client: TestClient, sender_id: int, memo: str) -> Any:
    return client.put(f"/api/v1/senders/{sender_id}/memo", json={"memo": memo})


class House:
    """jule manages "Haushalt", tom edits, lea reads; bob has nothing to do with it."""

    def __init__(self, operator: Account) -> None:
        self.jule, self.tom, self.lea, self.bob = (make_account(n) for n in ("jule", "tom", "lea", "bob"))
        self.vault = shared_vault("Haushalt", operator, (self.jule, "manage"), (self.tom, "edit"), (self.lea, "read"))
        self.doc = add_document(self.vault, self.jule, "Strom Oktober", sender="Stadtwerke Lindenau")
        with SessionLocal() as db:
            self.sender = int(db.scalar(select(Sender.id).where(Sender.vault_id == self.vault)) or 0)


@pytest.fixture
def house(client: TestClient, operator: Account) -> House:
    return House(operator)


# --- Reading and changing -----------------------------------------------------------------------------------------


def test_an_editor_writes_it_and_every_member_reads_it_at_the_document(house: House) -> None:
    with new_client(house.tom) as tom:
        assert sender_of(tom, house.doc)["memo"] == ""
        answer = set_note(tom, house.sender, NOTE + "  \r\n\n")
        assert answer.status_code == 200 and answer.json()["memo"] == NOTE
    for who in (house.jule, house.lea):
        with new_client(who) as member:
            assert sender_of(member, house.doc) == {"id": house.sender, "memo": NOTE}
            listed = member.get("/api/v1/order/senders").json()["items"]
            assert [(e["id"], e["memo"], e["can_edit_memo"]) for e in listed] == [
                (house.sender, NOTE, who is house.jule)]


def test_a_reader_and_a_stranger_cannot_change_it(house: House) -> None:
    with new_client(house.lea) as lea:
        assert set_note(lea, house.sender, "Lesend").status_code == 403
    with new_client(house.bob) as bob:
        assert set_note(bob, house.sender, "Fremd").status_code == 404
        assert set_note(bob, 2**31 - 1, "Fremd").status_code == 404
    with SessionLocal() as db:
        assert db.get(Sender, house.sender).memo == ""  # type: ignore[union-attr]


@pytest.mark.parametrize("memo", ["x" * 501, "\n".join(["y" * 100] * 6)])
def test_at_most_500_characters(house: House, memo: str) -> None:
    with new_client(house.tom) as tom:
        answer = set_note(tom, house.sender, memo)
    assert answer.status_code == 422 and answer.json()["detail"]["code"] in ("invalid_memo",), answer.text


def test_control_characters_go_and_line_breaks_stay(house: House) -> None:
    with new_client(house.tom) as tom:
        answer = set_note(tom, house.sender, "Zeile\x00 eins\t\u202e\r\nZeile\x1b zwei\n")
    assert answer.json()["memo"] == "Zeile eins \nZeile zwei".replace(" \n", "\n")


@pytest.mark.parametrize("right", ["read", "edit"])
def test_a_share_alone_never_shows_it(house: House, right: str) -> None:
    with new_client(house.jule) as jule:
        set_note(jule, house.sender, NOTE)
        assert jule.put(f"/api/v1/documents/{house.doc}/shares/{house.bob.id}", json={"right": right}).status_code == 200
    with new_client(house.bob) as bob:
        shown = bob.get(f"/api/v1/documents/{house.doc}")
        assert shown.status_code == 200 and shown.json()["sender"]["name"] == "Stadtwerke Lindenau"
        assert shown.json()["sender_memo"] is None and "4711" not in shown.text
        assert "4711" not in bob.get("/api/v1/search", params={"q": "Strom"}).text
        assert "4711" not in bob.get("/api/v1/order/senders").text
        assert set_note(bob, house.sender, "Über die Freigabe").status_code == 404


def test_never_on_the_link_page(house: House) -> None:
    with new_client(house.jule) as jule:
        set_note(jule, house.sender, NOTE)
        made = jule.post(f"/api/v1/documents/{house.doc}/links", json={"recipient": "Steuerbüro", "days": 3}).json()
    with TestClient(jule.app, base_url="http://testserver") as outsider:
        page = outsider.get(f"/api/v1/l/{made['token']}")
        assert page.status_code == 200 and "Stadtwerke" in page.text and "4711" not in page.text


def test_a_device_changes_it_and_no_key_does(house: House) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": True})
    with new_client(house.tom) as tom:
        token = tom.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
        keys = {scope: tom.post("/api/v1/api-keys", json={"name": scope, "scope": scope}).json()["secret"]
                for scope in ("read", "upload")}
    with TestClient(tom.app, base_url="http://testserver") as other:
        assert other.put(f"/api/v1/senders/{house.sender}/memo", json={"memo": "Vom Telefon"},
                         headers={"Authorization": f"Bearer {token}"}).status_code == 200
        for secret in keys.values():
            assert other.put(f"/api/v1/senders/{house.sender}/memo", json={"memo": "Programm"},
                             headers={"Authorization": f"Bearer {secret}"}).status_code == 401
        read = other.get(f"/api/v1/documents/{house.doc}", headers={"Authorization": f"Bearer {keys['read']}"})
        assert read.json()["sender_memo"] == "Vom Telefon"


def test_never_in_the_log(house: House, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    with new_client(house.tom) as tom:
        set_note(tom, house.sender, NOTE)
        set_note(tom, house.sender, "x" * 600)
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "4711" not in logged and "Telefon" not in logged and "Note on a sender changed" in logged


# --- Tidying, merging, moving ---------------------------------------------------------------------------------------


def test_a_sender_with_a_note_is_not_tidied_away_and_can_be_deleted_under_ordnung(house: House) -> None:
    with new_client(house.tom) as tom:
        set_note(tom, house.sender, NOTE)
        assert tom.patch(f"/api/v1/documents/{house.doc}", json={"sender": "Andere Werke"}).status_code == 200
        listed = {e["id"]: e for e in tom.get("/api/v1/order/senders").json()["items"]}
        assert listed[house.sender]["documents"] == 0 and listed[house.sender]["memo"] == NOTE
        # Without a note a sender goes with its last document, as ever.
        other = listed[next(i for i in listed if i != house.sender)]["id"]
        assert tom.patch(f"/api/v1/documents/{house.doc}", json={"sender": "Stadtwerke Lindenau"}).status_code == 200
        assert other not in {e["id"] for e in tom.get("/api/v1/order/senders").json()["items"]}
        # The document took the sender with the note again (same name in the vault).
        assert sender_of(tom, house.doc) == {"id": house.sender, "memo": NOTE}
        tom.patch(f"/api/v1/documents/{house.doc}", json={"sender": None})
        assert tom.delete(f"/api/v1/senders/{house.sender}").status_code == 204
        assert tom.get("/api/v1/order/senders").json()["items"] == []


def test_merging_puts_both_notes_one_under_the_other_cut_to_500(house: House) -> None:
    second = add_document(house.vault, house.jule, "Gas", sender="SW Lindenau")
    with new_client(house.jule) as jule:
        other = sender_of(jule, second)["id"]
        set_note(jule, house.sender, "A" * 300)
        set_note(jule, other, "B" * 300)
        assert jule.post(f"/api/v1/senders/{other}/merge", json={"into": house.sender}).status_code == 200
        merged = sender_of(jule, second)
        assert merged["id"] == house.sender and merged["memo"] == ("A" * 300 + "\n" + "B" * 300)[:500]
        third = add_document(house.vault, house.jule, "Wasser", sender="Wasserwerk")
        water = sender_of(jule, third)["id"]
        set_note(jule, water, "Zählernummer 99")
        # Renaming onto a name the vault has is a merge too.
        set_note(jule, house.sender, "Kunde 1")
        assert jule.patch(f"/api/v1/senders/{water}", json={"name": "Stadtwerke Lindenau"}).status_code == 200
        assert sender_of(jule, third)["memo"] == "Kunde 1\nZählernummer 99"


def test_moving_a_document_does_not_take_the_note_along(house: House) -> None:
    mine = own_vault(house.jule)
    with new_client(house.jule) as jule:
        set_note(jule, house.sender, NOTE)
        moved = jule.post(f"/api/v1/documents/{house.doc}/move", json={"vault_id": mine})
        assert moved.status_code == 200 and moved.json()["sender"]["name"] == "Stadtwerke Lindenau"
        assert moved.json()["sender_memo"] == "" and moved.json()["sender"]["id"] != house.sender
        # The note stays with the vault's sender, which stays without documents.
        listed = {e["id"]: e for e in jule.get("/api/v1/order/senders", params={"vault_id": house.vault}).json()["items"]}
        assert listed[house.sender]["memo"] == NOTE and listed[house.sender]["documents"] == 0


def test_joined_notes() -> None:
    assert catalog.joined_memo("", "b") == "b" and catalog.joined_memo("a", "") == "a"
    assert catalog.joined_memo("a", "a") == "a" and catalog.joined_memo("a ", " b") == "a\nb"
    assert len(catalog.joined_memo("x" * 400, "y" * 400)) == 500


def test_never_to_the_ai(client: TestClient, operator: Account) -> None:
    import httpx

    from app.services import ai

    from .files import make_pdf
    from .intake import upload_and_read
    from .test_ai import Model, set_up

    model = Model()
    model.text = json.dumps({"title": "Wartung", "sender": "Elektro Brandt GmbH", "kind": None, "date": None,
                             "amount": None})
    ai.transport = httpx.MockTransport(model.handle)
    try:
        import pytest as _pytest

        with _pytest.MonkeyPatch.context() as patch:
            patch.setattr(ai, "resolver", lambda host, port: ["93.184.216.34"])
            set_up(client)
            vault = shared_vault("Haushalt", operator)
            first = add_document(vault, operator, "Alt", sender="Elektro Brandt GmbH")
            sender = client.get(f"/api/v1/documents/{first}").json()["sender"]["id"]
            assert set_note(client, sender, "GEHEIMZETTEL 31337").status_code == 200
            upload_and_read(client, "scan.pdf", make_pdf(["Elektro Brandt GmbH\nWartung der Heizung"]), vault)
    finally:
        ai.transport = None
    sent = [json.dumps(model.body(i), ensure_ascii=False) for i in range(len(model.requests))
            if model.requests[i].url.path.endswith(("chat/completions", "messages"))]
    assert sent and all("GEHEIMZETTEL" not in body and "31337" not in body for body in sent)
