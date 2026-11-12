"""A link that shows further documents (N2): only those chosen when it was made, each reachable only through its own
link, gone from it when the pair is undone, the document is in the trash or deleted, somebody takes it out, the link is
revoked, runs out or the operator switches links off."""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import clock
from app.db import SessionLocal
from app.main import app
from app.models import Account, Document, Link, LinkDocument, Related
from app.security import brake
from app.services import documents, settings_service, sharing

from . import files
from .conftest import new_client
from .intake import upload_and_read
from .papers import add_document, own_vault, shared_vault

PATHS = ("file", "preview", "pages/1", "text")


def pdf(text: str) -> bytes:
    """A PDF whose one page carries text of its own (no recognition needed)."""
    return files.make_pdf([f"{text} mit Text, der lang genug ist"])


def public() -> TestClient:
    """Somebody without an account: no cookie, no header."""
    return TestClient(app, base_url="http://testserver")


def relate(client: TestClient, one: int, other: int) -> None:
    assert client.put(f"/api/v1/documents/{one}/related/{other}").status_code == 200


def make_link(client: TestClient, document: int, **body: Any) -> dict[str, Any]:
    answer = client.post(f"/api/v1/documents/{document}/links",
                         json={"recipient": "Steuerbüro", "days": 7, "allow_download": True, **body})
    assert answer.status_code == 201, answer.text
    return answer.json()  # type: ignore[no-any-return]


def items_of(link_id: int) -> dict[int, int]:
    """The further documents of a link as stored: document -> number within the link."""
    with SessionLocal() as db:
        return {d: i for i, d in db.execute(select(LinkDocument.id, LinkDocument.document_id)
                                            .where(LinkDocument.link_id == link_id))}


def reachable(outside: TestClient, token: str, item: int) -> list[int]:
    return [outside.get(f"/api/v1/l/{token}/also/{item}/{path}").status_code for path in PATHS]


def history(document_id: int, action: str) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        from app.models import Event

        return [e.detail for e in db.scalars(select(Event).where(Event.document_id == document_id,
                                                                 Event.action == action).order_by(Event.id))]


@pytest.fixture
def world(client: TestClient, operator: Account) -> dict[str, Any]:
    """Four documents of the operator, read: the one the link is for, one chosen with it, one that goes with it and
    was not chosen, and one that comes to go with it only after the link was made."""
    made = {name: upload_and_read(client, f"{name}.pdf", pdf(name))["id"]
            for name in ("Rechnung", "Lieferschein", "Mahnung", "Später")}
    main, chosen, unchosen, later = made["Rechnung"], made["Lieferschein"], made["Mahnung"], made["Später"]
    relate(client, main, chosen)
    relate(client, main, unchosen)
    link = make_link(client, main, also=[chosen])
    relate(client, main, later)
    return {"operator": operator, "main": main, "chosen": chosen, "unchosen": unchosen, "later": later,
            "link": link, "token": link["token"], "item": items_of(link["id"])[chosen]}


# --- What a link shows ------------------------------------------------------------------------------------------------


def test_the_link_lists_and_shows_the_chosen_document_and_nothing_else(client: TestClient, world: dict) -> None:
    token, item = world["token"], world["item"]
    with public() as outside:
        page = outside.get(f"/api/v1/l/{token}")
        assert page.status_code == 200
        also = page.json()["also"]
        assert [(a["id"], a["title"]) for a in also] == [(item, "Lieferschein")]
        assert set(also[0]) == {"id", "title", "kind", "date", "pages", "has_file", "viewable", "has_pages"}
        assert also[0]["has_file"] and also[0]["viewable"] and also[0]["has_pages"]
        # Nothing of the documents that were not chosen, and never a document's own number.
        assert "Mahnung" not in page.text and "Später" not in page.text
        assert reachable(outside, token, item) == [200, 200, 200, 200]
        assert outside.get(f"/api/v1/l/{token}/also/{item}/text").json()["pages"][0].startswith("Lieferschein")
        assert outside.get(f"/api/v1/l/{token}/also/{item}/file").content[:4] == b"%PDF"
    listed = client.get(f"/api/v1/documents/{world['main']}/links").json()
    assert [entry["also_count"] for entry in listed] == [1]


def test_no_document_that_does_not_hang_on_the_link_is_reachable_by_any_number(client: TestClient, world: dict) -> None:
    """Every other number, on every path: the ones of another link (to the document that was not chosen), the
    documents' own numbers, numbers that do not exist. All answer like a wrong token."""
    other = make_link(client, world["main"], also=[world["unchosen"], world["later"]])
    theirs = set(items_of(other["id"]).values())
    assert len(theirs) == 2
    token, item = world["token"], world["item"]
    with public() as outside:
        wrong = outside.get("/api/v1/l/lnk_" + "x" * 43 + "/file")
        for number in range(1, 40):
            if number == item:
                continue
            # Every wrong number counts on the brake of links (``test_the_wrong_numbers_count_on_the_brake_of_links``):
            # cleared here, so that each one is asked.
            brake.forget()
            for path in PATHS:
                answer = outside.get(f"/api/v1/l/{token}/also/{number}/{path}")
                assert answer.status_code == 404, (number, path)
                assert answer.json() == wrong.json()
        # The other link shows its own and not the one of the first.
        assert reachable(outside, other["token"], item) == [404] * 4
        for number in theirs:
            assert reachable(outside, other["token"], number) == [200] * 4


def test_a_document_linked_later_never_comes_into_an_open_link(client: TestClient, world: dict) -> None:
    with public() as outside:
        assert [a["title"] for a in outside.get(f"/api/v1/l/{world['token']}").json()["also"]] == ["Lieferschein"]
    assert set(items_of(world["link"]["id"])) == {world["chosen"]}


def test_opening_counts_once_per_opening_of_the_link_not_per_document(client: TestClient, world: dict) -> None:
    token, item = world["token"], world["item"]
    with public() as outside:
        outside.get(f"/api/v1/l/{token}")
        for path in PATHS:
            outside.get(f"/api/v1/l/{token}/also/{item}/{path}")
    with SessionLocal() as db:
        link = db.get(Link, world["link"]["id"])
        assert link is not None and link.opened_count == 1 and link.last_opened_at is not None
    # The history of the further document says it was shown, with a link of the other one (by its number).
    assert history(world["chosen"], sharing.ALSO_SHOWN) == [{"document": world["main"], "days": 7}]
    assert history(world["unchosen"], sharing.ALSO_SHOWN) == []


def test_without_downloading_the_further_documents_show_pages_but_no_file_and_no_text(
    client: TestClient, world: dict,
) -> None:
    link = make_link(client, world["main"], allow_download=False, also=[world["chosen"]])
    item = items_of(link["id"])[world["chosen"]]
    with public() as outside:
        shown = outside.get(f"/api/v1/l/{link['token']}").json()["also"][0]
        assert shown["viewable"] is False and shown["has_pages"] is True
        assert reachable(outside, link["token"], item) == [403, 200, 200, 403]


def test_the_wrong_numbers_count_on_the_brake_of_links(client: TestClient, world: dict,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    failed: list[int] = []
    import app.routers.public as public_routes

    monkeypatch.setattr(public_routes, "link_failed", lambda request: failed.append(1))
    with public() as outside:
        assert outside.get(f"/api/v1/l/{world['token']}/also/99999/file").status_code == 404
        assert outside.get(f"/api/v1/l/{world['token']}/also/99999/pages/1").status_code == 404
    assert len(failed) == 2


# --- Making one -------------------------------------------------------------------------------------------------------


def test_every_document_that_may_not_come_along_refuses_the_whole_link_alike(
    client: TestClient, world: dict, operator: Account,
) -> None:
    """Not to share by the maker, not seen, not going with it, in the trash, not there: one answer for all five."""
    from .conftest import make_account

    lea = make_account("lea")
    main = world["main"]
    # Lea's document, shared with the operator for editing: seen and going with it, but only lea may share it.
    shared = add_document(own_vault(lea), lea, "Lea geteilt")
    with new_client(lea) as browser:
        assert browser.put(f"/api/v1/documents/{shared}/shares/{operator.id}", json={"right": "edit"}).status_code == 200
    relate(client, main, shared)
    # Lea's own, never seen by the operator, set to go with it behind everybody's back.
    hidden = add_document(own_vault(lea), lea, "Lea privat")
    with SessionLocal() as db:
        db.add(Related(low_id=min(main, hidden), high_id=max(main, hidden), created_at=clock.now()))
        db.commit()
    alone = add_document(own_vault(operator), operator, "Allein")
    trashed = add_document(own_vault(operator), operator, "Weg")
    relate(client, main, trashed)
    assert client.delete(f"/api/v1/documents/{trashed}").status_code in (200, 204)
    with SessionLocal() as db:
        before = (db.scalar(select(func.count()).select_from(Link)),
                  db.scalar(select(func.count()).select_from(LinkDocument)))
    answers = []
    for refused in (shared, hidden, alone, trashed, 999999):
        answer = client.post(f"/api/v1/documents/{main}/links",
                             json={"recipient": "x", "days": 3, "also": [world["chosen"], refused]})
        answers.append((answer.status_code, answer.json()))
    assert answers[0][0] == 422 and answers[0][1]["detail"]["code"] == "invalid_also"
    assert all(answer == answers[0] for answer in answers), answers
    with SessionLocal() as db:
        after = (db.scalar(select(func.count()).select_from(Link)),
                 db.scalar(select(func.count()).select_from(LinkDocument)))
    assert after == before
    # The document itself among them, and more than ten, are refused too.
    assert client.post(f"/api/v1/documents/{main}/links",
                       json={"recipient": "x", "days": 3, "also": [main]}).status_code == 422
    assert client.post(f"/api/v1/documents/{main}/links",
                       json={"recipient": "x", "days": 3, "also": list(range(1, 12))}).status_code == 422


def test_a_reader_makes_no_such_link_and_takes_nothing_out(client: TestClient, operator: Account) -> None:
    from .conftest import make_account

    lea = make_account("lea")
    vault = shared_vault("Haushalt", operator, (lea, "read"))
    main = add_document(vault, operator, "Haupt")
    other = add_document(vault, operator, "Neben")
    relate(client, main, other)
    link = make_link(client, main, also=[other])
    item = items_of(link["id"])[other]
    with new_client(lea) as reader:
        assert reader.post(f"/api/v1/documents/{main}/links",
                           json={"recipient": "x", "days": 3, "also": [other]}).status_code == 403
        assert reader.get(f"/api/v1/documents/{other}/shown-through").status_code == 403
        assert reader.delete(f"/api/v1/documents/{other}/shown-through/{item}").status_code == 403
    assert items_of(link["id"]) == {other: item}


def test_a_device_does_what_its_person_may_a_read_key_only_reads(client: TestClient, world: dict) -> None:
    from .intake import device_token, upload_key

    token = device_token(client)
    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": True})
    secret = client.post("/api/v1/api-keys", json={"name": "k", "scope": "read"}).json()["secret"]
    upload = upload_key(world["operator"])
    with TestClient(app, base_url="http://testserver") as program:
        device = {"Authorization": f"Bearer {token}"}
        made = program.post(f"/api/v1/documents/{world['main']}/links", headers=device,
                            json={"recipient": "x", "days": 3, "also": [world["unchosen"]]})
        assert made.status_code == 201 and made.json()["also_count"] == 1
        reader = {"Authorization": f"Bearer {secret}"}
        assert program.get(f"/api/v1/documents/{world['chosen']}/shown-through", headers=reader).status_code == 200
        assert program.post(f"/api/v1/documents/{world['main']}/links", headers=reader,
                            json={"recipient": "x", "days": 3, "also": [world["unchosen"]]}).status_code in (401, 403)
        assert program.delete(f"/api/v1/documents/{world['chosen']}/shown-through/{world['item']}",
                              headers=reader).status_code in (401, 403)
        uploader = {"Authorization": f"Bearer {upload}"}
        assert program.get(f"/api/v1/documents/{world['chosen']}/shown-through", headers=uploader).status_code in (401, 403)
        assert program.delete(f"/api/v1/documents/{world['chosen']}/shown-through/{world['item']}",
                              headers=device).status_code == 204
    assert items_of(world["link"]["id"]) == {}


# --- Leaving a link ---------------------------------------------------------------------------------------------------


def _gone(world: dict) -> None:
    with public() as outside:
        assert reachable(outside, world["token"], world["item"]) == [404] * 4
        page = outside.get(f"/api/v1/l/{world['token']}")
        assert page.status_code != 200 or page.json()["also"] == []


def test_undoing_the_pair_takes_it_out_both_ways(client: TestClient, world: dict) -> None:
    # A link of the further document that shows the main one goes too.
    back = make_link(client, world["chosen"], also=[world["main"]])
    assert client.delete(f"/api/v1/documents/{world['chosen']}/related/{world['main']}").status_code == 200
    _gone(world)
    assert items_of(world["link"]["id"]) == {} and items_of(back["id"]) == {}
    with public() as outside:
        assert outside.get(f"/api/v1/l/{world['token']}").status_code == 200, "the link itself stays"
    assert history(world["chosen"], sharing.ALSO_LEFT)[0] == {"document": world["main"], "reason": "unlinked"}
    assert {"document": world["chosen"], "reason": "unlinked"} in history(world["main"], sharing.ALSO_GONE)
    # Set again, it does not come back by itself.
    relate(client, world["main"], world["chosen"])
    _gone(world)


def test_the_trash_hides_it_and_restoring_shows_it_again(client: TestClient, world: dict) -> None:
    assert client.delete(f"/api/v1/documents/{world['chosen']}").status_code in (200, 204)
    _gone(world)
    assert client.post(f"/api/v1/documents/{world['chosen']}/restore").status_code == 200
    with public() as outside:
        assert reachable(outside, world["token"], world["item"]) == [200] * 4


def test_deleted_for_good_it_is_gone(client: TestClient, world: dict) -> None:
    assert client.delete(f"/api/v1/documents/{world['chosen']}").status_code in (200, 204)
    assert client.post(f"/api/v1/documents/{world['chosen']}/purge").status_code in (200, 204)
    _gone(world)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(LinkDocument)) == 0
    assert history(world["main"], sharing.ALSO_GONE) == [{"document": world["chosen"], "reason": "purged"}]


def test_the_trash_emptied_in_one_portion_with_the_links_own_document(client: TestClient, world: dict,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    for document in (world["main"], world["chosen"]):
        assert client.delete(f"/api/v1/documents/{document}").status_code in (200, 204)
    later = clock.now() + timedelta(days=40)
    monkeypatch.setattr(clock, "now", lambda: later)
    with SessionLocal() as db:
        assert documents.purge_expired(db) == 2
        assert db.scalar(select(func.count()).select_from(LinkDocument)) == 0
        assert db.scalar(select(func.count()).select_from(Document).where(
            Document.id.in_([world["main"], world["chosen"]]))) == 0


def test_taken_out_at_the_document_it_is_gone_and_the_link_stays(client: TestClient, world: dict) -> None:
    shown = client.get(f"/api/v1/documents/{world['chosen']}/shown-through").json()
    assert [(s["id"], s["recipient"], s["document_id"], s["document_title"]) for s in shown] == [
        (world["item"], "Steuerbüro", world["main"], "Rechnung")]
    assert client.delete(f"/api/v1/documents/{world['chosen']}/shown-through/{world['item']}").status_code == 204
    _gone(world)
    assert client.get(f"/api/v1/documents/{world['chosen']}/shown-through").json() == []
    assert client.delete(f"/api/v1/documents/{world['chosen']}/shown-through/{world['item']}").status_code == 404
    # Another document's number does not take anything out of a link.
    other = make_link(client, world["main"], also=[world["unchosen"]])
    theirs = items_of(other["id"])[world["unchosen"]]
    assert client.delete(f"/api/v1/documents/{world['chosen']}/shown-through/{theirs}").status_code == 404
    assert items_of(other["id"]) == {world["unchosen"]: theirs}
    with public() as outside:
        assert outside.get(f"/api/v1/l/{world['token']}").status_code == 200
    assert history(world["chosen"], sharing.ALSO_LEFT) == [{"document": world["main"], "reason": "taken_out"}]
    assert history(world["main"], sharing.ALSO_GONE) == [{"document": world["chosen"], "reason": "taken_out"}]


def test_revoked_it_is_gone_for_all(client: TestClient, world: dict) -> None:
    assert client.delete(f"/api/v1/documents/{world['main']}/links/{world['link']['id']}").status_code == 204
    _gone(world)
    assert history(world["chosen"], sharing.ALSO_LEFT) == [{"document": world["main"], "reason": "revoked"}]


def test_run_out_it_is_gone(client: TestClient, world: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    later = clock.now() + timedelta(days=8)
    monkeypatch.setattr(clock, "now", lambda: later)
    _gone(world)


def test_the_operators_switch_ends_it(client: TestClient, world: dict) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"links_allowed": False})
    _gone(world)
    assert client.get(f"/api/v1/documents/{world['chosen']}").json()["link_count"] == 0


def test_the_main_document_in_the_trash_ends_it(client: TestClient, world: dict) -> None:
    assert client.delete(f"/api/v1/documents/{world['main']}").status_code in (200, 204)
    _gone(world)


def test_a_maker_who_may_no_longer_share_the_further_document_shows_it_no_more(
    client: TestClient, operator: Account,
) -> None:
    from .conftest import make_account

    tom = make_account("tom")
    vault = shared_vault("Haushalt", operator, (tom, "manage"))
    main = add_document(own_vault(tom), tom, "Toms")
    other = add_document(vault, operator, "Haushalt")
    with new_client(tom) as browser:
        relate(browser, main, other)
        link = make_link(browser, main, also=[other])
    item = items_of(link["id"])[other]
    with public() as outside:
        assert outside.get(f"/api/v1/l/{link['token']}/also/{item}/file").status_code == 200
    with new_client(operator) as manager:
        assert manager.put(f"/api/v1/vaults/{vault}/members/{tom.id}", json={"right": "edit"}).status_code == 200
    with public() as outside:
        assert outside.get(f"/api/v1/l/{link['token']}/also/{item}/file").status_code == 404
        assert outside.get(f"/api/v1/l/{link['token']}").json()["also"] == []


# --- Seen at the document -----------------------------------------------------------------------------------------


def test_the_further_document_counts_the_link_and_names_the_other_only_to_who_sees_it(
    client: TestClient, operator: Account,
) -> None:
    from .conftest import make_account

    lea = make_account("lea")
    vault = shared_vault("Haushalt", operator, (lea, "manage"))
    main = add_document(own_vault(operator), operator, "Privat")
    other = add_document(vault, operator, "Gemeinsam")
    relate(client, main, other)
    make_link(client, main, also=[other])
    assert client.get(f"/api/v1/documents/{other}").json()["link_count"] == 1
    with new_client(lea) as manager:
        assert manager.get(f"/api/v1/documents/{other}").json()["link_count"] == 1
        shown = manager.get(f"/api/v1/documents/{other}/shown-through").json()
        assert [(s["document_id"], s["document_title"], s["recipient"]) for s in shown] == [(None, None, "Steuerbüro")]
        events = manager.get(f"/api/v1/documents/{other}/events").json()
        line = next(e for e in events if e["action"] == sharing.ALSO_SHOWN)
        assert line["detail"]["document"] is None and "title" not in line["detail"]
        assert "Privat" not in str(events)


# --- Races ------------------------------------------------------------------------------------------------------------


def _race(world: dict, barrier: threading.Barrier, answers: dict[str, int], what: str) -> None:
    with new_client(world["operator"]) as browser:
        barrier.wait(timeout=10)
        if what == "make":
            answers[what] = browser.post(f"/api/v1/documents/{world['main']}/links", json={
                "recipient": "x", "days": 3, "also": [world["unchosen"]]}).status_code
        else:
            answers[what] = browser.delete(
                f"/api/v1/documents/{world['main']}/related/{world['unchosen']}").status_code


def test_a_link_made_while_the_pair_is_undone_never_shows_it(client: TestClient, world: dict) -> None:
    for _round in range(3):
        relate(client, world["main"], world["unchosen"])
        barrier = threading.Barrier(2)
        answers: dict[str, int] = {}
        threads = [threading.Thread(target=_race, args=(world, barrier, answers, what)) for what in ("make", "undo")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert answers["undo"] == 200 and answers["make"] in (201, 422)
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(LinkDocument).where(
                LinkDocument.document_id == world["unchosen"])) == 0


def test_taken_out_twice_at_once_is_taken_out_once(client: TestClient, world: dict) -> None:
    barrier = threading.Barrier(2)
    codes: list[int] = []

    def take() -> None:
        with new_client(world["operator"]) as browser:
            barrier.wait(timeout=10)
            codes.append(browser.delete(
                f"/api/v1/documents/{world['chosen']}/shown-through/{world['item']}").status_code)

    threads = [threading.Thread(target=take) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(codes) == [204, 404]
    assert len(history(world["chosen"], sharing.ALSO_LEFT)) == 1
