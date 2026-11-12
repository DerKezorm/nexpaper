"""Pinned documents ("Angeheftet", K1): for each person alone, at most 20 they can see, the newest first, only what they
may see now and nothing in the trash; a pin whose right went is not shown and comes back with the right. Reading is
enough; no key pins. Not a change of the document: no number, no history. The account takes its pins along."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import clock
from app.db import SessionLocal
from app.models import Account, Document, Pin
from app.services import pins, settings_service, vaults

from .conftest import PASSWORD, make_account, new_client
from .papers import add_document, own_vault, shared_vault


def listed(client: TestClient) -> list[str]:
    answer = client.get("/api/v1/pins")
    assert answer.status_code == 200, answer.text
    assert answer.json()["max"] == 20
    return [d["title"] for d in answer.json()["items"]]


def pin(client: TestClient, document_id: int) -> Any:
    return client.put(f"/api/v1/documents/{document_id}/pin")


def seq_and_events(document_id: int) -> tuple[int, int]:
    with SessionLocal() as db:
        from app.models import Event

        row = db.get(Document, document_id)
        assert row is not None
        return row.change_seq, int(db.scalar(select(func.count()).select_from(Event)
                                             .where(Event.document_id == document_id)) or 0)


@pytest.fixture
def house(client: TestClient, operator: Account) -> dict[str, Any]:
    jule, tom, lea = make_account("jule"), make_account("tom"), make_account("lea")
    vault = shared_vault("Haushalt", operator, (jule, "manage"), (tom, "edit"), (lea, "read"))
    return {"jule": jule, "tom": tom, "lea": lea, "vault": vault, "operator": operator}


def test_pinning_is_for_oneself_newest_first_and_changes_nothing_at_the_document(house: dict[str, Any],
                                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime, timedelta

    first = add_document(house["vault"], house["jule"], "Erstes")
    second = add_document(house["vault"], house["jule"], "Zweites")
    before = seq_and_events(first)
    moment = datetime(2026, 11, 12, 8, tzinfo=UTC)
    with new_client(house["lea"]) as lea:
        monkeypatch.setattr(clock, "now", lambda: moment)
        answer = pin(lea, first)
        assert answer.status_code == 200 and answer.json() == {"pinned": True, "count": 1, "max": 20}
        monkeypatch.setattr(clock, "now", lambda: moment + timedelta(minutes=1))
        pin(lea, second)
        assert pin(lea, second).status_code == 200, "twice is no error"
        assert listed(lea) == ["Zweites", "Erstes"]
        assert lea.get(f"/api/v1/documents/{first}").json()["pinned"] is True
        hits = {h["document"]["title"]: h["document"]["pinned"] for h in lea.get("/api/v1/search").json()["items"]}
        assert hits == {"Erstes": True, "Zweites": True}
    with new_client(house["jule"]) as jule:
        assert listed(jule) == [] and jule.get(f"/api/v1/documents/{first}").json()["pinned"] is False
    assert seq_and_events(first) == before, "no change number, no history"
    with new_client(house["lea"]) as lea:
        assert lea.delete(f"/api/v1/documents/{first}/pin").status_code == 204
        assert lea.delete(f"/api/v1/documents/{first}/pin").status_code == 204
        assert listed(lea) == ["Zweites"]
    assert seq_and_events(first) == before


def test_twenty_and_the_twenty_first_is_told_kindly(house: dict[str, Any]) -> None:
    ids = [add_document(house["vault"], house["jule"], f"Dok {n}") for n in range(21)]
    with new_client(house["tom"]) as tom:
        for document_id in ids[:20]:
            assert pin(tom, document_id).status_code == 200
        answer = pin(tom, ids[20])
        assert answer.status_code == 409
        assert answer.json()["detail"]["code"] == "too_many_pins" and answer.json()["detail"]["max"] == 20
        assert len(listed(tom)) == 20
        # One off, and the 21st goes on.
        tom.delete(f"/api/v1/documents/{ids[0]}/pin")
        assert pin(tom, ids[20]).status_code == 200


def test_two_pins_at_the_same_moment_never_make_twenty_one(house: dict[str, Any]) -> None:
    ids = [add_document(house["vault"], house["jule"], f"Dok {n}") for n in range(21)]
    with SessionLocal() as db:
        for document_id in ids[:19]:
            pins.pin(db, house["tom"].id, document_id)
    start = threading.Barrier(2)
    results: list[Any] = []

    def one(document_id: int) -> None:
        start.wait(5)
        with SessionLocal() as db:
            try:
                results.append(pins.pin(db, house["tom"].id, document_id))
            except Exception as exc:  # noqa: BLE001 (the test looks at what came back)
                results.append(getattr(exc, "detail", exc))

    threads = [threading.Thread(target=one, args=(i,)) for i in ids[19:21]]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert sorted(map(str, results)) == sorted([str(True), str({"code": "too_many_pins", "message":
                                                "At most 20 documents can be pinned. Take one off first.", "max": 20})])
    with SessionLocal() as db:
        assert pins.count(db, house["tom"].id) == 20


def test_a_lost_right_hides_the_pin_and_it_comes_back_with_the_right(house: dict[str, Any]) -> None:
    doc = add_document(house["vault"], house["jule"], "Vertrag")
    with new_client(house["tom"]) as tom:
        pin(tom, doc)
    with SessionLocal() as db:
        vaults.remove_member(db, house["operator"].id, house["vault"], house["tom"].id)
    with new_client(house["tom"]) as tom:
        assert listed(tom) == []
        assert "Vertrag" not in tom.get("/api/v1/search", params={"q": "angeheftet:ja"}).text
        assert pin(tom, doc).status_code == 404 and tom.delete(f"/api/v1/documents/{doc}/pin").status_code == 404
    with SessionLocal() as db:
        vaults.set_member(db, house["operator"].id, house["vault"], house["tom"].id, "read")
    with new_client(house["tom"]) as tom:
        assert listed(tom) == ["Vertrag"]


def test_the_trash_hides_it_and_restoring_brings_it_back(house: dict[str, Any]) -> None:
    doc = add_document(house["vault"], house["jule"], "Rechnung")
    with new_client(house["tom"]) as tom:
        pin(tom, doc)
        assert tom.delete(f"/api/v1/documents/{doc}").status_code == 200
        assert listed(tom) == []
        assert pin(tom, doc).json()["detail"]["code"] == "in_trash"
        assert tom.post(f"/api/v1/documents/{doc}/restore").status_code == 200
        assert listed(tom) == ["Rechnung"]


def test_a_hidden_pin_does_not_count_against_the_twenty(house: dict[str, Any]) -> None:
    ids = [add_document(house["vault"], house["jule"], f"Dok {n}") for n in range(21)]
    with new_client(house["tom"]) as tom:
        for document_id in ids[:20]:
            pin(tom, document_id)
        tom.delete(f"/api/v1/documents/{ids[0]}")
        assert pin(tom, ids[20]).status_code == 200 and len(listed(tom)) == 20


@pytest.mark.parametrize(("q", "wanted"), [("angeheftet:ja", {"Gepinnt"}), ("pinned:yes", {"Gepinnt"}),
                                           ("angeheftet:nein", {"Frei"}), ("pinned:no", {"Frei"}),
                                           ("angeheftet:vielleicht", set()), ("ANGEHEFTET:JA", {"Gepinnt"})])
def test_the_search_word(house: dict[str, Any], q: str, wanted: set[str]) -> None:
    doc = add_document(house["vault"], house["jule"], "Gepinnt")
    add_document(house["vault"], house["jule"], "Frei")
    with new_client(house["lea"]) as lea:
        pin(lea, doc)
        found = {h["document"]["title"] for h in lea.get("/api/v1/search", params={"q": q}).json()["items"]}
        assert found == wanted
    with new_client(house["tom"]) as tom:
        found = {h["document"]["title"] for h in tom.get("/api/v1/search", params={"q": q}).json()["items"]}
        nothing_pinned = {"Gepinnt", "Frei"} if wanted == {"Frei"} else set()
        assert found == nothing_pinned, "lea's pin is lea's"


def test_a_share_is_enough_and_the_list_never_shows_a_document_without_a_right(client: TestClient,
                                                                              operator: Account) -> None:
    jule, bob = make_account("jule"), make_account("bob")
    own = add_document(own_vault(jule), jule, "Privat")
    with new_client(jule) as owner:
        owner.put(f"/api/v1/documents/{own}/shares/{bob.id}", json={"right": "read"})
    with new_client(bob) as shared:
        assert pin(shared, own).status_code == 200 and listed(shared) == ["Privat"]
    with new_client(jule) as owner:
        owner.delete(f"/api/v1/documents/{own}/shares/{bob.id}")
    with new_client(bob) as shared:
        assert listed(shared) == []
        assert shared.get("/api/v1/pins").json()["items"] == []
    stranger = make_account("stranger")
    with new_client(stranger) as nobody:
        assert pin(nobody, own).status_code == 404 and listed(nobody) == []


def test_a_device_pins_and_a_key_only_reads_the_list(house: dict[str, Any]) -> None:
    doc = add_document(house["vault"], house["jule"], "Telefon")
    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": True})
    with new_client(house["lea"]) as lea:
        token = lea.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
        keys = {scope: lea.post("/api/v1/api-keys", json={"name": scope, "scope": scope}).json()["secret"]
                for scope in ("read", "upload")}
    with TestClient(lea.app, base_url="http://testserver") as other:
        assert other.put(f"/api/v1/documents/{doc}/pin", headers={"Authorization": f"Bearer {token}"}).status_code == 200
        for scope, secret in keys.items():
            headers = {"Authorization": f"Bearer {secret}"}
            assert other.put(f"/api/v1/documents/{doc}/pin", headers=headers).status_code == 401
            assert other.delete(f"/api/v1/documents/{doc}/pin", headers=headers).status_code == 401
            listing = other.get("/api/v1/pins", headers=headers)
            assert listing.status_code == (200 if scope == "read" else 403)
            if scope == "read":
                assert [d["title"] for d in listing.json()["items"]] == ["Telefon"]


def test_the_list_takes_a_limit_for_the_phone(house: dict[str, Any]) -> None:
    ids = [add_document(house["vault"], house["jule"], f"Dok {n}") for n in range(8)]
    with new_client(house["tom"]) as tom:
        for document_id in ids:
            pin(tom, document_id)
        assert len(tom.get("/api/v1/pins", params={"limit": 6}).json()["items"]) == 6
        assert tom.get("/api/v1/pins", params={"limit": 21}).status_code == 422


def test_the_pins_go_with_the_account(client: TestClient, house: dict[str, Any]) -> None:
    doc = add_document(house["vault"], house["jule"], "Weg")
    with new_client(house["tom"]) as tom:
        pin(tom, doc)
    answer = client.request("DELETE", f"/api/v1/accounts/{house['tom'].id}",
                            json={"current_password": PASSWORD, "confirm_name": "tom", "documents": "delete_documents"})
    assert answer.status_code == 204, answer.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Pin)) == 0


def test_purging_a_document_takes_its_pins_along(house: dict[str, Any]) -> None:
    doc = add_document(house["vault"], house["jule"], "Ganz weg")
    with new_client(house["tom"]) as tom:
        pin(tom, doc)
    with new_client(house["jule"]) as jule:
        jule.delete(f"/api/v1/documents/{doc}")
        assert jule.post(f"/api/v1/documents/{doc}/purge").status_code == 204
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Pin)) == 0
