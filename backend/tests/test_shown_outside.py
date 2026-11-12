"""Whoever may change a document sees that a link to the outside shows it (N2b, ``shown_outside``).

The finding of the review of N2: Jule shares an invoice by a link and shows the delivery note with it. Lea may only
change things in the vault, not share. Before, she could not tell that the delivery note was open to the outside
(``link_count`` and the notice of the other link are only for who may share), and pages she put into it went out at
once. Now every answer about a document tells whoever may change it ``shown_outside``: yes or no, nothing more. Somebody
who may only read learns nothing new; whoever may share sees everything as before.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import clock
from app.db import SessionLocal
from app.main import app
from app.models import Account
from app.services import settings_service

from .conftest import make_account, new_client
from .intake import device_token, upload_and_read, upload_key
from .papers import add_document, own_vault, shared_vault
from .test_link_also import items_of, make_link, pdf, public, relate, rows_of

RECIPIENT = "Steuerbüro"


def outside_of(who: TestClient, document: int) -> bool:
    answer = who.get(f"/api/v1/documents/{document}")
    assert answer.status_code == 200, answer.text
    return answer.json()["shown_outside"]  # type: ignore[no-any-return]


@pytest.fixture
def house(client: TestClient, operator: Account) -> dict[str, Any]:
    """Jule (the operator) manages the vault "Haushalt"; Lea may change things there, Tom may only read. "Rechnung" has
    the link, "Lieferschein" is shown with it, "Mahnung" goes with it and was not chosen, "Kaufvertrag" has nothing."""
    lea, tom = make_account("lea"), make_account("tom")
    vault = shared_vault("Haushalt", operator, (lea, "edit"), (tom, "read"))
    main = add_document(vault, operator, "Rechnung")
    shown = add_document(vault, operator, "Lieferschein")
    unchosen = add_document(vault, operator, "Mahnung")
    alone = add_document(vault, operator, "Kaufvertrag")
    relate(client, main, shown)
    relate(client, main, unchosen)
    link = make_link(client, main, also=[shown], recipient=RECIPIENT)
    return {"operator": operator, "lea": lea, "tom": tom, "vault": vault, "main": main, "shown": shown,
            "unchosen": unchosen, "alone": alone, "link": link, "item": items_of(link["id"])[shown],
            "row": rows_of(link["id"])[shown]}


# --- Who sees it ------------------------------------------------------------------------------------------------------


def test_the_probe_of_the_review_lea_sees_it_before_she_puts_her_pages_in(client: TestClient, operator: Account) -> None:
    """``test_p4`` of the review of N2, now with what Lea sees: the document shown with the link says so to her (only
    yes), so the interface asks her before the merge; the merge itself still works for an app that does not ask."""
    lea = make_account("lea")
    vault = shared_vault("Haushalt", operator, (lea, "edit"))
    main = upload_and_read(client, "Haupt.pdf", pdf("Haupt"))["id"]
    shown = upload_and_read(client, "Neben.pdf", pdf("Neben"))["id"]
    assert client.post(f"/api/v1/documents/{shown}/move", json={"vault_id": vault}).status_code == 200
    relate(client, main, shown)
    link = make_link(client, main, also=[shown])
    with new_client(lea) as browser:
        seen = browser.get(f"/api/v1/documents/{shown}").json()
        assert seen["shown_outside"] is True
        assert seen["can_share"] is False and seen["link_count"] is None and seen["share_count"] is None
        private = upload_and_read(browser, "Lea privat.pdf", pdf("LeaGeheim"))["id"]
        assert outside_of(browser, private) is False
        merged = browser.post(f"/api/v1/documents/{shown}/merge", json={
            "base_version": seen["current_version"],
            "others": [{"id": private, "base_version": browser.get(f"/api/v1/documents/{private}").json()[
                "current_version"]}]})
        # No new required field at an endpoint there is: old clients keep working.
        assert merged.status_code == 200, merged.text
        assert merged.json()["shown_outside"] is True
    with public() as outside:
        assert outside.get(f"/api/v1/l/{link['token']}").json()["also"][0]["pages"] == 2


def test_who_may_change_it_sees_it_who_may_only_read_does_not(house: dict, client: TestClient) -> None:
    for document in (house["main"], house["shown"]):
        assert outside_of(client, document) is True
        with new_client(house["lea"]) as editor:
            assert outside_of(editor, document) is True
        with new_client(house["tom"]) as reader:
            assert outside_of(reader, document) is False
    # Only what the link shows: not the document that goes with it and was not chosen, not one without a link.
    with new_client(house["lea"]) as editor:
        assert outside_of(editor, house["unchosen"]) is False
        assert outside_of(editor, house["alone"]) is False


@pytest.mark.parametrize(("right", "expected"), [("edit", True), ("read", False)])
def test_a_share_of_its_own_counts_like_the_vault(house: dict, client: TestClient, right: str, expected: bool) -> None:
    max_ = make_account("max")
    for document in (house["main"], house["shown"]):
        assert client.put(f"/api/v1/documents/{document}/shares/{max_.id}", json={"right": right}).status_code == 200
    with new_client(max_) as somebody:
        assert outside_of(somebody, house["main"]) is expected
        assert outside_of(somebody, house["shown"]) is expected


def test_the_rights_one_by_one(house: dict, client: TestClient) -> None:
    """The field for every kind of caller, at the shown document: who may change it (in the vault, by a share, as its
    manager, through their device or a read key) sees it; who may only read, and a stranger, do not (404 for him)."""
    manager = make_account("mia")
    with SessionLocal() as db:
        from app.services import vaults

        vaults.set_member(db, house["operator"].id, house["vault"], manager.id, "manage")
    stranger = make_account("fremd")
    shown = house["shown"]
    expected = {"operator": True, "lea": True, "tom": False, "mia": True}
    people = {"operator": house["operator"], "lea": house["lea"], "tom": house["tom"], "mia": manager}
    for name, account in people.items():
        with new_client(account) as browser:
            assert outside_of(browser, shown) is expected[name], name
            token = device_token(browser)
        with TestClient(app, base_url="http://testserver") as program:
            seen = program.get(f"/api/v1/documents/{shown}", headers={"Authorization": f"Bearer {token}"})
            assert seen.status_code == 200 and seen.json()["shown_outside"] is expected[name], name
    with new_client(house["lea"]) as browser:
        with SessionLocal() as db:
            settings_service.save(db, {"api_keys_allowed": True})
        secret = browser.post("/api/v1/api-keys", json={"name": "k", "scope": "read"}).json()["secret"]
    with TestClient(app, base_url="http://testserver") as program:
        seen = program.get(f"/api/v1/documents/{shown}", headers={"Authorization": f"Bearer {secret}"})
        assert seen.status_code == 200 and seen.json()["shown_outside"] is True
        # An upload key reads no document at all.
        upload = upload_key(house["lea"])
        assert program.get(f"/api/v1/documents/{shown}",
                           headers={"Authorization": f"Bearer {upload}"}).status_code in (401, 403)
    with new_client(stranger) as browser:
        assert browser.get(f"/api/v1/documents/{shown}").status_code == 404


def test_the_lists_say_it_too(house: dict) -> None:
    """The archive's list, the search, the pinned ones and the inbox carry the same field as the document itself."""
    wanted = {house["main"]: True, house["shown"]: True, house["unchosen"]: False, house["alone"]: False}
    for account, editor in ((house["lea"], True), (house["tom"], False)):
        with new_client(account) as browser:
            listed = browser.get("/api/v1/documents", params={"vault_id": house["vault"]}).json()["items"]
            assert {d["id"]: d["shown_outside"] for d in listed} == {k: v and editor for k, v in wanted.items()}
            found = browser.get("/api/v1/search", params={"q": "", "vault_id": house["vault"]}).json()["items"]
            assert {h["document"]["id"]: h["document"]["shown_outside"] for h in found} == {
                k: v and editor for k, v in wanted.items()}
            for document in wanted:
                assert browser.put(f"/api/v1/documents/{document}/pin").status_code in (200, 201)
            pinned = browser.get("/api/v1/pins").json()["items"]
            assert {d["id"]: d["shown_outside"] for d in pinned} == {k: v and editor for k, v in wanted.items()}
    with SessionLocal() as db:
        from app.models import Document

        found = db.get(Document, house["shown"])
        assert found is not None
        found.status = "inbox"
        db.commit()
    with new_client(house["lea"]) as browser:
        inbox = browser.get("/api/v1/inbox").json()["items"]
        assert [(d["id"], d["shown_outside"]) for d in inbox] == [(house["shown"], True)]


# --- Nothing more than yes or no --------------------------------------------------------------------------------------


def test_no_recipient_no_date_no_number_for_who_may_not_share(house: dict) -> None:
    """Lea learns that it is open, never to whom, until when, how many links or through which document: not at the
    document, not in the lists, not in the history, and the routes of the links stay closed to her."""
    until = house["link"]["until"][:10]
    with new_client(house["lea"]) as browser:
        answers = [
            browser.get(f"/api/v1/documents/{house['main']}"),
            browser.get(f"/api/v1/documents/{house['shown']}"),
            browser.get("/api/v1/documents", params={"vault_id": house["vault"]}),
            browser.get("/api/v1/search", params={"q": ""}),
            browser.get(f"/api/v1/documents/{house['main']}/related"),
            browser.get(f"/api/v1/documents/{house['shown']}/related"),
            browser.get(f"/api/v1/documents/{house['main']}/events"),
            browser.get(f"/api/v1/documents/{house['shown']}/events"),
            browser.get("/api/v1/changes", params={"since": 0}),
        ]
        for answer in answers:
            assert answer.status_code == 200, answer.url
            assert RECIPIENT not in answer.text and until not in answer.text.replace(
                house["link"]["created_at"][:10], ""), answer.url
        for document in (house["main"], house["shown"]):
            seen = browser.get(f"/api/v1/documents/{document}").json()
            assert seen["link_count"] is None and seen["share_count"] is None and seen["can_share"] is False
            assert browser.get(f"/api/v1/documents/{document}/links").status_code == 403
            assert browser.get(f"/api/v1/documents/{document}/shares").status_code == 403
            assert browser.get(f"/api/v1/documents/{document}/shown-through").status_code == 403


def test_two_links_are_no_more_than_one(house: dict, client: TestClient) -> None:
    """Yes or no: a second link changes nothing Lea can see."""
    with new_client(house["lea"]) as browser:
        before = browser.get(f"/api/v1/documents/{house['shown']}").json()
    make_link(client, house["main"], also=[house["shown"]], recipient="Versicherung")
    with new_client(house["lea"]) as browser:
        after = browser.get(f"/api/v1/documents/{house['shown']}").json()
    assert {k: v for k, v in after.items() if k != "change_seq"} == {k: v for k, v in before.items() if k != "change_seq"}


def test_whoever_may_share_sees_everything_as_before(house: dict, client: TestClient) -> None:
    seen = client.get(f"/api/v1/documents/{house['shown']}").json()
    assert seen["shown_outside"] is True and seen["link_count"] == 1
    assert [s["recipient"] for s in client.get(f"/api/v1/documents/{house['shown']}/shown-through").json()] == [RECIPIENT]


# --- Only links that work ---------------------------------------------------------------------------------------------


def _both(house: dict) -> tuple[bool, bool]:
    with new_client(house["lea"]) as browser:
        return outside_of(browser, house["main"]), outside_of(browser, house["shown"])


def test_revoked_it_is_closed(house: dict, client: TestClient) -> None:
    assert _both(house) == (True, True)
    assert client.delete(f"/api/v1/documents/{house['main']}/links/{house['link']['id']}").status_code == 204
    assert _both(house) == (False, False)


def test_run_out_it_is_closed(house: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    later = clock.now() + timedelta(days=8)
    monkeypatch.setattr(clock, "now", lambda: later)
    assert _both(house) == (False, False)


def test_a_lowered_limit_of_the_operator_closes_it(house: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"link_max_days": 7})
    later = clock.now() + timedelta(days=7, hours=1)
    monkeypatch.setattr(clock, "now", lambda: later)
    assert _both(house) == (False, False)


def test_the_operators_switch_closes_it(house: dict) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"links_allowed": False})
    assert _both(house) == (False, False)
    with SessionLocal() as db:
        settings_service.save(db, {"links_allowed": True})
    assert _both(house) == (True, True)


def test_the_links_document_in_the_trash_closes_both(house: dict, client: TestClient) -> None:
    assert client.delete(f"/api/v1/documents/{house['main']}").status_code in (200, 204)
    assert _both(house) == (False, False)
    assert client.post(f"/api/v1/documents/{house['main']}/restore").status_code == 200
    assert _both(house) == (True, True)


def test_the_shown_document_in_the_trash_is_closed(house: dict, client: TestClient) -> None:
    assert client.delete(f"/api/v1/documents/{house['shown']}").status_code in (200, 204)
    assert _both(house) == (True, False)


def test_undoing_the_pair_closes_the_shown_one(house: dict, client: TestClient) -> None:
    assert client.delete(f"/api/v1/documents/{house['main']}/related/{house['shown']}").status_code == 200
    assert _both(house) == (True, False)


def test_taken_out_it_is_closed(house: dict, client: TestClient) -> None:
    assert client.delete(f"/api/v1/documents/{house['shown']}/shown-through/{house['row']}").status_code == 204
    assert _both(house) == (True, False)


def test_a_maker_who_may_no_longer_share_closes_it(client: TestClient, operator: Account) -> None:
    """Tom made the link as a manager of the vault and is an editor now: his link shows nothing any more."""
    tom, lea = make_account("tom"), make_account("lea")
    vault = shared_vault("Haushalt", operator, (tom, "manage"), (lea, "edit"))
    main = add_document(vault, operator, "Rechnung")
    shown = add_document(vault, operator, "Lieferschein")
    with new_client(tom) as browser:
        relate(browser, main, shown)
        make_link(browser, main, also=[shown])
    with new_client(lea) as browser:
        assert (outside_of(browser, main), outside_of(browser, shown)) == (True, True)
    assert client.put(f"/api/v1/vaults/{vault}/members/{tom.id}", json={"right": "edit"}).status_code == 200
    with new_client(lea) as browser:
        assert (outside_of(browser, main), outside_of(browser, shown)) == (False, False)


def test_a_document_of_ones_own_vault_shown_through_a_link_of_another(client: TestClient, operator: Account) -> None:
    """The link's own document in a vault Lea does not see: she still learns that hers is open (not through which)."""
    lea = make_account("lea")
    vault = shared_vault("Haushalt", operator, (lea, "edit"))
    main = add_document(own_vault(operator), operator, "Privat")
    shown = add_document(vault, operator, "Gemeinsam")
    relate(client, main, shown)
    make_link(client, main, also=[shown])
    with new_client(lea) as browser:
        seen = browser.get(f"/api/v1/documents/{shown}")
        assert seen.json()["shown_outside"] is True
        assert "Privat" not in seen.text
        assert browser.get(f"/api/v1/documents/{main}").status_code == 404
