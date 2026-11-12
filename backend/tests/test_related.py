"""Goes with ("Gehört zu"): setting and removing pairs, the proposals, the rights at every route, what may never leak,
and the life of a pair (trash, restore, deleted for good, moved, joined, split, an account deleted)."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Account, Document, Event, Related, RelatedDismissed
from app.services import related, settings_service

from .conftest import PASSWORD, make_account, new_client
from .intake import upload_key
from .papers import add_document, own_vault, shared_vault
from .test_numbers import give_text


def paper(vault: int, owner: Account, title: str, text: str = "", sender: str | None = None) -> int:
    document = add_document(vault, owner, title, **({"sender": sender} if sender else {}))
    if text:
        give_text(document, text)
    return document


def pairs() -> set[tuple[int, int]]:
    with SessionLocal() as db:
        return {(low, high) for low, high in db.execute(select(Related.low_id, Related.high_id))}


def history(document_id: int, action: str) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        return [e.detail for e in db.scalars(select(Event).where(Event.document_id == document_id,
                                                                  Event.action == action).order_by(Event.id))]


def seq(document_id: int) -> int:
    with SessionLocal() as db:
        found = db.get(Document, document_id)
        assert found is not None
        return found.change_seq


def listed(client: TestClient, document_id: int) -> list[int]:
    answer = client.get(f"/api/v1/documents/{document_id}/related")
    assert answer.status_code == 200, answer.text
    return [item["id"] for item in answer.json()]


def proposed(client: TestClient, document_id: int) -> list[int]:
    answer = client.get(f"/api/v1/documents/{document_id}/related/suggestions")
    assert answer.status_code == 200, answer.text
    return [item["id"] for item in answer.json()]


@pytest.fixture
def jule() -> Account:
    return make_account("jule")


# --- Setting and removing ------------------------------------------------------------------------------------------


def test_setting_and_removing_a_pair_writes_the_history_of_both_and_gives_both_a_new_number(jule: Account) -> None:
    vault = own_vault(jule)
    invoice = paper(vault, jule, "Rechnung", sender="Stadtwerke Lindenau")
    delivery = paper(vault, jule, "Lieferschein")
    before = seq(invoice), seq(delivery)
    with new_client(jule) as browser:
        answer = browser.put(f"/api/v1/documents/{invoice}/related/{delivery}")
        assert answer.status_code == 200
        item = answer.json()[0]
        assert item["id"] == delivery and item["title"] == "Lieferschein" and item["can_unlink"] is True
        assert listed(browser, delivery) == [invoice]
        shown = browser.get(f"/api/v1/documents/{delivery}/related").json()[0]
        assert shown["sender"]["name"] == "Stadtwerke Lindenau"
        assert browser.get(f"/api/v1/documents/{invoice}").json()["has_related"] is True
    assert pairs() == {(min(invoice, delivery), max(invoice, delivery))}
    assert seq(invoice) > before[0] and seq(delivery) > before[1]
    # The detail is the number of the other document, never its title.
    assert history(invoice, related.SET) == [{"document": delivery}]
    assert history(delivery, related.SET) == [{"document": invoice}]
    after_set = seq(invoice), seq(delivery)
    with new_client(jule) as browser:
        assert browser.delete(f"/api/v1/documents/{delivery}/related/{invoice}").json() == []
        assert listed(browser, invoice) == []
        assert browser.get(f"/api/v1/documents/{invoice}").json()["has_related"] is False
    assert pairs() == set()
    assert history(invoice, related.UNSET) == [{"document": delivery}]
    assert history(delivery, related.UNSET) == [{"document": invoice}]
    assert seq(invoice) > after_set[0] and seq(delivery) > after_set[1]


def test_setting_twice_or_removing_what_is_not_there_is_no_error_and_writes_nothing(jule: Account) -> None:
    vault = own_vault(jule)
    one, two = paper(vault, jule, "Eins"), paper(vault, jule, "Zwei")
    with new_client(jule) as browser:
        assert browser.put(f"/api/v1/documents/{one}/related/{two}").status_code == 200
        number = seq(one)
        assert browser.put(f"/api/v1/documents/{two}/related/{one}").status_code == 200
        assert seq(one) == number
        assert browser.delete(f"/api/v1/documents/{one}/related/{two}").status_code == 200
        number = seq(one)
        assert browser.delete(f"/api/v1/documents/{one}/related/{two}").status_code == 200
        assert seq(one) == number
    assert len(history(one, related.SET)) == 1 and len(history(one, related.UNSET)) == 1


def test_a_document_cannot_go_with_itself_and_nothing_in_the_trash_is_set(jule: Account) -> None:
    vault = own_vault(jule)
    one, two = paper(vault, jule, "Eins"), paper(vault, jule, "Zwei")
    with new_client(jule) as browser:
        answer = browser.put(f"/api/v1/documents/{one}/related/{one}")
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "invalid_related"
        assert browser.delete(f"/api/v1/documents/{two}").status_code == 200
        answer = browser.put(f"/api/v1/documents/{one}/related/{two}")
        assert answer.status_code == 409 and answer.json()["detail"]["code"] == "in_trash"
    assert pairs() == set()


def test_two_people_setting_the_same_pair_at_once_make_one_pair_and_one_line_each(jule: Account) -> None:
    tom = make_account("tom")
    household = shared_vault("Haushalt", jule, (tom, "edit"))
    one, two = paper(household, jule, "Eins"), paper(household, jule, "Zwei")
    start = threading.Barrier(2, timeout=10)
    codes: list[int] = []

    def put(who: Account, a: int, b: int) -> None:
        with new_client(who) as browser:
            start.wait()
            codes.append(browser.put(f"/api/v1/documents/{a}/related/{b}").status_code)

    threads = [threading.Thread(target=put, args=(jule, one, two)), threading.Thread(target=put, args=(tom, two, one))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert codes == [200, 200]
    assert pairs() == {(min(one, two), max(one, two))}
    assert len(history(one, related.SET)) == 1 and len(history(two, related.SET)) == 1


# --- Rights --------------------------------------------------------------------------------------------------------


@pytest.fixture
def world(jule: Account) -> dict[str, Any]:
    """jule's own vault, a household where tom may change and lea only read, and one document of each."""
    tom, lea, anna = make_account("tom"), make_account("lea"), make_account("anna")
    household = shared_vault("Haushalt", jule, (tom, "edit"), (lea, "read"))
    other = shared_vault("Garten", jule, (tom, "edit"), (lea, "edit"))
    return {
        "tom": tom, "lea": lea, "anna": anna, "household": household, "garden": other,
        "private": paper(own_vault(jule), jule, "Privat"),
        "h1": paper(household, jule, "Haushalt eins"), "h2": paper(household, jule, "Haushalt zwei"),
        "g1": paper(other, jule, "Garten eins"),
    }


def test_edit_on_both_is_needed_and_a_refusal_writes_nothing(world: dict[str, Any]) -> None:
    lea, tom, anna = world["lea"], world["tom"], world["anna"]
    h1, h2, g1 = world["h1"], world["h2"], world["g1"]
    # Lea reads the household and changes the garden: one of the two only read.
    with new_client(lea) as browser:
        for method, path in (("PUT", f"{g1}/related/{h1}"), ("PUT", f"{h1}/related/{g1}"),
                             ("DELETE", f"{g1}/related/{h1}"), ("POST", f"{g1}/related/{h1}/dismiss")):
            assert browser.request(method, f"/api/v1/documents/{path}").status_code == 403, path
        # Read on both.
        assert browser.put(f"/api/v1/documents/{h1}/related/{h2}").status_code == 403
        assert browser.get(f"/api/v1/documents/{h1}/related").status_code == 200
    # A stranger: neither is there for them.
    with new_client(anna) as browser:
        assert browser.put(f"/api/v1/documents/{h1}/related/{h2}").status_code == 404
        assert browser.get(f"/api/v1/documents/{h1}/related").status_code == 404
        assert browser.get(f"/api/v1/documents/{h1}/related/suggestions").status_code == 404
    # Tom may change both, across two vaults.
    with new_client(tom) as browser:
        # One he cannot see answers as one that does not exist, whichever side it is on.
        assert browser.put(f"/api/v1/documents/{h1}/related/{world['private']}").status_code == 404
        assert browser.put(f"/api/v1/documents/{world['private']}/related/{h1}").status_code == 404
        assert pairs() == set()
        assert browser.put(f"/api/v1/documents/{h1}/related/{g1}").status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(RelatedDismissed)) == 0
    assert pairs() == {(min(h1, g1), max(h1, g1))}


def test_a_share_with_edit_is_enough_and_one_with_read_is_not(jule: Account, world: dict[str, Any]) -> None:
    anna = world["anna"]
    mine = paper(own_vault(anna), anna, "Annas Brief")
    with new_client(jule) as browser:
        assert browser.put(f"/api/v1/documents/{world['private']}/shares/{anna.id}", json={"right": "read"}).status_code == 200
    with new_client(anna) as browser:
        assert browser.put(f"/api/v1/documents/{mine}/related/{world['private']}").status_code == 403
    with new_client(jule) as browser:
        assert browser.put(f"/api/v1/documents/{world['private']}/shares/{anna.id}", json={"right": "edit"}).status_code == 200
    with new_client(anna) as browser:
        assert browser.put(f"/api/v1/documents/{mine}/related/{world['private']}").status_code == 200


def test_a_device_acts_as_its_person_a_read_key_only_reads_an_upload_key_nothing(
    client: TestClient, operator: Account, jule: Account,
) -> None:
    vault = own_vault(jule)
    one, two = paper(vault, jule, "Eins"), paper(vault, jule, "Zwei")
    with new_client(jule) as browser:
        token = browser.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": True})
    with new_client(jule) as browser:
        secret = browser.post("/api/v1/api-keys", json={"name": "k", "scope": "read"}).json()["secret"]
    upload = upload_key(jule)
    with TestClient(client.app, base_url="http://testserver") as program:
        device = {"Authorization": f"Bearer {token}"}
        assert program.put(f"/api/v1/documents/{one}/related/{two}", headers=device).status_code == 200
        reader = {"Authorization": f"Bearer {secret}"}
        assert program.get(f"/api/v1/documents/{one}/related", headers=reader).status_code == 200
        assert program.get(f"/api/v1/documents/{one}/related/suggestions", headers=reader).status_code == 200
        for method in ("PUT", "DELETE"):
            assert program.request(method, f"/api/v1/documents/{one}/related/{two}", headers=reader).status_code in (401, 403)
        assert program.post(f"/api/v1/documents/{one}/related/{two}/dismiss", headers=reader).status_code in (401, 403)
        uploader = {"Authorization": f"Bearer {upload}"}
        for method, path in (("GET", f"{one}/related"), ("GET", f"{one}/related/suggestions"),
                             ("PUT", f"{one}/related/{two}"), ("DELETE", f"{one}/related/{two}")):
            assert program.request(method, f"/api/v1/documents/{path}", headers=uploader).status_code in (401, 403)
    assert pairs() == {(min(one, two), max(one, two))}


def test_a_link_to_the_outside_shows_nothing_of_what_goes_with_its_document(jule: Account) -> None:
    vault = own_vault(jule)
    one, two = paper(vault, jule, "Eins"), paper(vault, jule, "Geheim zwei")
    with new_client(jule) as browser:
        assert browser.put(f"/api/v1/documents/{one}/related/{two}").status_code == 200
        token = browser.post(f"/api/v1/documents/{one}/links", json={"recipient": "x", "days": 1}).json()["token"]
    with TestClient(new_client().app, base_url="http://testserver") as outside:
        page = outside.get(f"/api/v1/l/{token}")
        assert page.status_code == 200
        assert "Geheim" not in page.text and "related" not in page.text
        # The routes of the documents do not take the link's token.
        assert outside.get(f"/api/v1/documents/{one}/related",
                           headers={"Authorization": f"Bearer {token}"}).status_code == 401


# --- Nothing leaks -------------------------------------------------------------------------------------------------


def test_what_the_caller_may_not_see_leaves_no_trace_anywhere(world: dict[str, Any], jule: Account) -> None:
    """jule sets a pair between a household document and her own; tom sees the household only. Everything tom asks
    about answers exactly as if the pair did not exist."""
    tom = world["tom"]
    h1, private = world["h1"], world["private"]

    def what_tom_sees() -> dict[str, Any]:
        with new_client(tom) as browser:
            document = browser.get(f"/api/v1/documents/{h1}").json()
            return {
                "list": browser.get(f"/api/v1/documents/{h1}/related").json(),
                "has": document["has_related"],
                "listing": [d["has_related"] for d in browser.get("/api/v1/documents").json()["items"]],
                "search_yes": browser.get("/api/v1/search", params={"q": "verknüpft:ja"}).json()["total"],
                "search_no": browser.get("/api/v1/search", params={"q": "linked:no"}).json()["total"],
                "proposals": browser.get(f"/api/v1/documents/{h1}/related/suggestions").json(),
            }

    before = what_tom_sees()
    with new_client(jule) as browser:
        assert browser.put(f"/api/v1/documents/{h1}/related/{private}").status_code == 200
        assert browser.get(f"/api/v1/documents/{h1}").json()["has_related"] is True
    assert what_tom_sees() == before
    assert before["list"] == [] and before["has"] is False
    # The history of the household document: a line tom may see, without the number or the title of the other.
    with new_client(tom) as browser:
        lines = [e for e in browser.get(f"/api/v1/documents/{h1}/events").json() if e["action"] == related.SET]
        assert lines and lines[0]["detail"] == {"document": None}
    with new_client(jule) as browser:
        lines = [e for e in browser.get(f"/api/v1/documents/{h1}/events").json() if e["action"] == related.SET]
        assert lines[0]["detail"] == {"document": private, "title": "Privat"}


def test_proposals_never_name_count_or_depend_on_what_the_caller_may_not_see(world: dict[str, Any], jule: Account) -> None:
    tom = world["tom"]
    household = world["household"]
    number = "Rechnungsnummer R-2026-00017"
    invoice = paper(household, jule, "Rechnung", number)
    reminder = paper(household, jule, "Mahnung", number)
    with new_client(tom) as browser:
        alone = browser.get(f"/api/v1/documents/{invoice}/related/suggestions").json()
    assert [item["id"] for item in alone] == [reminder]
    # Eleven documents of jule's own with the same number: tom does not see them, they change nothing for him.
    private = [paper(own_vault(jule), jule, f"Kopie {index}", number) for index in range(11)]
    with new_client(tom) as browser:
        assert browser.get(f"/api/v1/documents/{invoice}/related/suggestions").json() == alone
        inbox = browser.get("/api/v1/inbox").json()
        assert all(int(key) not in private for key in inbox["related"])
    # For jule, who sees all thirteen, the number is on too many documents to say anything.
    with new_client(jule) as browser:
        assert proposed(browser, invoice) == []
    assert private


# --- Proposals -----------------------------------------------------------------------------------------------------


def test_the_same_invoice_order_or_delivery_number_is_proposed_with_its_reason(jule: Account) -> None:
    vault = own_vault(jule)
    invoice = paper(vault, jule, "Rechnung", "Rechnungsnummer R-2026-00017\nBestellnummer B-1234567\n"
                                            "Lieferschein-Nr. LS-004711")
    confirmation = paper(vault, jule, "Auftragsbestätigung", "Ihre Bestellung B 1234567")
    delivery = paper(vault, jule, "Lieferschein", "Lieferschein\nLS-OO4711\nBestellnummer B-1234567")
    reminder = paper(vault, jule, "Mahnung", "Rechnung Nr. R-2026-00017")
    paper(vault, jule, "Anderes", "Rechnungsnummer R-2026-00018")
    with new_client(jule) as browser:
        found = browser.get(f"/api/v1/documents/{invoice}/related/suggestions").json()
    # Two numbers in common first, then by the surest kind.
    assert [(item["id"], item["via"]) for item in found] == [(delivery, "order"), (reminder, "invoice"),
                                                             (confirmation, "order")]


def test_a_customer_number_or_an_iban_is_never_a_reason(jule: Account) -> None:
    vault = own_vault(jule)
    text = "Kundennummer 100 2345\nVertragsnummer V-2026-0017\nIBAN DE89 3704 0044 0532 0130 00"
    one, two = paper(vault, jule, "Strom Mai", text), paper(vault, jule, "Strom Juni", text)
    with new_client(jule) as browser:
        assert proposed(browser, one) == [] and proposed(browser, two) == []


def test_a_number_on_more_than_ten_documents_is_no_reason(jule: Account) -> None:
    vault = own_vault(jule)
    made = [paper(vault, jule, f"Monat {index}", "Auftrag Nr. RA-2026-0042") for index in range(11)]
    with new_client(jule) as browser:
        assert proposed(browser, made[0]) == []
        # Ten are still a reason (one gone to the trash leaves ten).
        assert browser.delete(f"/api/v1/documents/{made[10]}").status_code == 200
        assert len(proposed(browser, made[0])) == related.MAX_SUGGESTIONS


def test_short_numbers_and_different_senders_are_no_reason(jule: Account) -> None:
    vault = own_vault(jule)
    one = paper(vault, jule, "Eins", "Rechnung Nr. 1234", sender="Stadtwerke Lindenau")
    paper(vault, jule, "Zwei", "Rechnung Nr. 1234", sender="Stadtwerke Lindenau")
    three = paper(vault, jule, "Drei", "Rechnung Nr. 10231", sender="Stadtwerke Lindenau")
    paper(vault, jule, "Vier", "Rechnung Nr. 10231", sender="Möbelhaus Brandt")
    five = paper(vault, jule, "Fünf", "Rechnung Nr. 10231")
    with new_client(jule) as browser:
        assert proposed(browser, one) == []
        # One sender unknown: proposed; both known and different: not.
        assert proposed(browser, three) == [five]


def test_turned_down_or_set_is_not_proposed_again_to_anybody(world: dict[str, Any], jule: Account) -> None:
    tom = world["tom"]
    household = world["household"]
    text = "Lieferschein-Nr. LS-004711"
    one, two, three = (paper(household, jule, name, text) for name in ("Eins", "Zwei", "Drei"))
    with new_client(tom) as browser:
        assert proposed(browser, one) == [three, two]
        answer = browser.post(f"/api/v1/documents/{one}/related/{two}/dismiss")
        assert answer.status_code == 200 and [item["id"] for item in answer.json()] == [three]
        # Twice is no error.
        assert browser.post(f"/api/v1/documents/{two}/related/{one}/dismiss").status_code == 200
        assert browser.put(f"/api/v1/documents/{one}/related/{three}").status_code == 200
        assert proposed(browser, one) == []
        assert proposed(browser, two) == [three]
    with new_client(jule) as browser:
        assert proposed(browser, two) == [three] and proposed(browser, one) == []
    # Turning down changes nothing at the documents.
    assert history(one, related.SET) == [{"document": three}] and history(two, related.SET) == []


def test_only_who_may_change_both_gets_proposals_and_at_most_five(world: dict[str, Any], jule: Account) -> None:
    lea = world["lea"]
    household = world["household"]
    made = [paper(household, jule, f"Teil {index}", "Bestellnummer B-7654321") for index in range(7)]
    with new_client(lea) as browser:
        assert proposed(browser, made[0]) == []
    with new_client(jule) as browser:
        assert len(proposed(browser, made[0])) == related.MAX_SUGGESTIONS
        inbox = browser.get("/api/v1/inbox").json()
    # Filed documents are not in the inbox; put two there and look at their cards.
    assert inbox["related"] == {}
    with new_client(jule) as browser:
        for document_id in made[:2]:
            assert browser.patch(f"/api/v1/documents/{document_id}", json={"status": "inbox"}).status_code == 200
        cards = browser.get("/api/v1/inbox").json()
    assert set(cards["related"]) == {str(made[0]), str(made[1])}
    assert all(len(found) == related.INBOX_SUGGESTIONS for found in cards["related"].values())
    first = cards["related"][str(made[0])][0]
    assert set(first) == {"id", "title", "kind", "sender", "date", "status", "via"} and first["via"] == "order"


# --- Life of a pair ------------------------------------------------------------------------------------------------


def test_trash_hides_restore_brings_back_deleting_for_good_removes(jule: Account) -> None:
    vault = own_vault(jule)
    one, two = paper(vault, jule, "Eins"), paper(vault, jule, "Zwei")
    with new_client(jule) as browser:
        assert browser.put(f"/api/v1/documents/{one}/related/{two}").status_code == 200
        assert browser.delete(f"/api/v1/documents/{two}").status_code == 200
        assert listed(browser, one) == [] and listed(browser, two) == []
        assert browser.get(f"/api/v1/documents/{one}").json()["has_related"] is False
        assert browser.get(f"/api/v1/documents/{two}").json()["has_related"] is False
        assert pairs(), "the pair stays while the document is in the trash"
        assert browser.post(f"/api/v1/documents/{two}/restore").status_code == 200
        assert listed(browser, one) == [two] and listed(browser, two) == [one]
        assert browser.delete(f"/api/v1/documents/{two}").status_code == 200
        assert browser.post(f"/api/v1/documents/{two}/purge").status_code == 204
    assert pairs() == set()
    with new_client(jule) as browser:
        assert listed(browser, one) == []


def test_moving_a_document_keeps_the_pair_and_the_list_follows_the_rights(world: dict[str, Any], jule: Account) -> None:
    tom = world["tom"]
    h1, h2 = world["h1"], world["h2"]
    with new_client(jule) as browser:
        assert browser.put(f"/api/v1/documents/{h1}/related/{h2}").status_code == 200
        assert browser.post(f"/api/v1/documents/{h2}/move", json={"vault_id": own_vault(jule)}).status_code == 200
        assert listed(browser, h1) == [h2]
    with new_client(tom) as browser:
        assert listed(browser, h1) == []
    with new_client(jule) as browser:
        assert browser.post(f"/api/v1/documents/{h2}/move", json={"vault_id": world["household"]}).status_code == 200
    with new_client(tom) as browser:
        assert listed(browser, h1) == [h2]


def test_an_account_that_goes_leaves_its_pairs_without_a_name(client: TestClient, operator: Account,
                                                              world: dict[str, Any]) -> None:
    tom = world["tom"]
    h1, h2 = world["h1"], world["h2"]
    with new_client(tom) as browser:
        assert browser.put(f"/api/v1/documents/{h1}/related/{h2}").status_code == 200
    answer = client.request("DELETE", f"/api/v1/accounts/{tom.id}",
                            json={"current_password": PASSWORD, "confirm_name": tom.name})
    assert answer.status_code == 204, answer.text
    with SessionLocal() as db:
        assert db.execute(select(Related.low_id, Related.high_id, Related.created_by)).all() == [
            (min(h1, h2), max(h1, h2), None)]


def test_joining_takes_over_the_pairs_of_the_joined_ones_never_one_with_itself(client: TestClient,
                                                                             operator: Account) -> None:
    from . import files
    from .intake import upload_and_read

    def made(name: str) -> int:
        lines = f"{name}\nmit genug Text, damit die Seite\nals Text gilt und nichts erkannt wird"
        return int(upload_and_read(client, f"{name}.pdf", files.make_pdf([lines]))["id"])

    first, joined, partner, second_partner = made("Erste"), made("Zweite"), made("Partner"), made("Noch einer")
    for a, b in ((first, joined), (joined, partner), (first, second_partner), (joined, second_partner)):
        assert client.put(f"/api/v1/documents/{a}/related/{b}").status_code == 200
    answer = client.post(f"/api/v1/documents/{first}/merge",
                         json={"base_version": 1, "others": [{"id": joined, "base_version": 1}]})
    assert answer.status_code == 200, answer.text
    assert sorted(listed(client, first)) == sorted([partner, second_partner])
    assert (first, first) not in pairs()
    assert history(partner, related.SET)[-1] == {"document": first, "by": "merge"}


def test_splitting_leaves_the_pairs_with_the_document_split(client: TestClient, operator: Account) -> None:
    from . import files
    from .intake import upload_and_read

    lines = "mit genug Text, damit die Seite\nals Text gilt und nichts erkannt wird"
    stack = int(upload_and_read(client, "Stapel.pdf", files.make_pdf([f"Eins\n{lines}", f"Zwei\n{lines}"]))["id"])
    partner = int(upload_and_read(client, "Partner.pdf", files.make_pdf([f"Partner\n{lines}"]))["id"])
    assert client.put(f"/api/v1/documents/{stack}/related/{partner}").status_code == 200
    answer = client.post(f"/api/v1/documents/{stack}/split", json={
        "base_version": 1, "parts": [{"pages": [{"page": 1}]}, {"pages": [{"page": 2}]}]})
    assert answer.status_code == 201, answer.text
    parts = [item["id"] for item in answer.json()["items"]]
    assert pairs() == {(min(stack, partner), max(stack, partner))}
    for part in parts:
        assert listed(client, part) == []
    # The document split is in the trash: nothing shows at the partner until it is restored.
    assert listed(client, partner) == []


def test_a_backup_keeps_the_pairs_the_proposals_turned_down_and_the_numbers(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import db as database
    from app.models import DocumentNumber
    from app.services import backups

    vault = own_vault(operator)
    text = "Bestellnummer B-1234567"
    one, two, three = (paper(vault, operator, name, text) for name in ("Eins", "Zwei", "Drei"))
    assert client.put(f"/api/v1/documents/{one}/related/{two}").status_code == 200
    assert client.post(f"/api/v1/documents/{one}/related/{three}/dismiss").status_code == 200
    name = backups.create().name
    brief = client.post(f"/api/v1/backups/{name}/check").json()
    assert brief["usable"] is True
    # After the backup: the pair removed, another set.
    assert client.delete(f"/api/v1/documents/{one}/related/{two}").status_code == 200
    assert client.put(f"/api/v1/documents/{two}/related/{three}").status_code == 200
    monkeypatch.setattr(backups, "restart_soon", lambda: None)
    assert client.post(f"/api/v1/backups/{name}/restore", json={"password": PASSWORD}).status_code == 202
    assert backups.apply_pending() is True
    database.init_db()
    assert pairs() == {(min(one, two), max(one, two))}
    with SessionLocal() as db:
        assert db.execute(select(RelatedDismissed.low_id, RelatedDismissed.high_id)).all() == [
            (min(one, three), max(one, three))]
        assert db.scalar(select(func.count()).select_from(DocumentNumber)) == 3
    # The restore ended the sessions of the time before: a new one.
    with new_client(operator) as browser:
        assert proposed(browser, two) == [three] and listed(browser, one) == [two]


# --- Search --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("words", "wanted"), [
    ("verknüpft:ja", "linked"), ("Verknüpft:Ja", "linked"), ("verknuepft:ja", "linked"), ("linked:yes", "linked"),
    ("verknüpft:nein", "alone"), ("linked:no", "alone"), ("verknüpft:vielleicht", "none"),
])
def test_the_search_words_for_goes_with(jule: Account, words: str, wanted: str) -> None:
    vault = own_vault(jule)
    one, two, alone = paper(vault, jule, "Eins"), paper(vault, jule, "Zwei"), paper(vault, jule, "Allein")
    with new_client(jule) as browser:
        assert browser.put(f"/api/v1/documents/{one}/related/{two}").status_code == 200
        found = {item["document"]["id"] for item in browser.get("/api/v1/search", params={"q": words}).json()["items"]}
    assert found == {"linked": {one, two}, "alone": {alone}, "none": set()}[wanted]


# --- Many at once ---------------------------------------------------------------------------------------------------


def test_linking_many_together_sets_every_pair_and_counts_honestly(world: dict[str, Any], jule: Account) -> None:
    lea = world["lea"]
    garden = world["garden"]
    g1, h1, private = world["g1"], world["h1"], world["private"]
    g2, g3 = paper(garden, jule, "Garten zwei"), paper(garden, jule, "Garten drei")
    with new_client(jule) as browser:
        assert browser.put(f"/api/v1/documents/{g1}/related/{g2}").status_code == 200
    with SessionLocal() as db:
        done = related.link_all(db, lea.id, [g1, g2, g3, h1, private, g3])
    # Lea may change the garden, only read the household, not see jule's own.
    assert (done.linked, done.already) == (2, 1)
    assert sorted(done.refused) == sorted([(h1, "forbidden"), (private, "not_found")])
    with SessionLocal() as db:
        for ids in ([g1], [g1, g1], list(range(1, 13))):
            with pytest.raises(HTTPException) as refused:
                related.link_all(db, lea.id, ids)
            assert refused.value.status_code == 422
