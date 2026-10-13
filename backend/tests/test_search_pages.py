"""The archive's table and its start: numbered pages in every order (empty senders and amounts last, the newest first
among equals), what does not go with a cursor, and the overview's numbers by sender, kind, year and tag, counted only
over what the caller may see."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, Kind
from app.services import catalog

from .conftest import make_account, new_client
from .papers import add_document, own_vault, shared_vault
from .searching import search, titles


@pytest.fixture(autouse=True)
def no_brake(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests search more often than a person can; the brake is tested in ``test_search.py``."""
    from app.services import brakes

    monkeypatch.setitem(brakes.LIMITS, "search", 100_000)


def kind_id(key: str) -> int:
    with SessionLocal() as db:
        catalog.ensure_kinds(db)
        return int(db.scalar(select(Kind.id).where(Kind.key == key)) or 0)


@pytest.fixture
def jule() -> Account:
    return make_account("jule")


@pytest.fixture
def table(jule: Account) -> TestClient:
    vault = own_vault(jule)
    add_document(vault, jule, "berta", sender="Zahnarzt", amount=500, date=date(2026, 3, 1))
    add_document(vault, jule, "Anton", sender="apotheke", amount=None, date=date(2026, 1, 1))
    add_document(vault, jule, "Cäsar", sender=None, amount=12000, date=date(2025, 7, 1))
    add_document(vault, jule, "Dora", sender="Bäcker", amount=500, date=date(2026, 5, 1))
    with new_client(jule) as client:
        yield client


# --- Numbered pages ---------------------------------------------------------------------------------------------------


def test_numbered_pages_cover_everything_once_with_the_total(jule: Account) -> None:
    vault = own_vault(jule)
    for number in range(23):
        add_document(vault, jule, f"Gleich {number}", date=date(2026, 1, 1 + number % 5))
    with new_client(jule) as client:
        newest = titles(client, "gleich", limit=100)
        seen: list[str] = []
        for page in range(1, 6):
            body = search(client, "gleich", limit=5, page=page)
            assert body["total"] == 23
            assert body["next"] is None  # a numbered page has no cursor
            seen += [hit["document"]["title"] for hit in body["items"]]
        assert seen == newest  # the same order as the cursor's, no gaps, nothing twice
        beyond = search(client, "gleich", limit=5, page=6)
        assert beyond["items"] == [] and beyond["total"] == 23


@pytest.mark.parametrize(("order", "expected"), [
    ("title", ["Anton", "berta", "Cäsar", "Dora"]),  # case aside
    ("-title", ["Dora", "Cäsar", "berta", "Anton"]),
    ("-date", ["Dora", "berta", "Anton", "Cäsar"]),
    ("date", ["Cäsar", "Anton", "berta", "Dora"]),
    # Without a sender last both ways.
    ("sender", ["Anton", "Dora", "berta", "Cäsar"]),
    ("-sender", ["berta", "Dora", "Anton", "Cäsar"]),
    # Without an amount last both ways; the same amount: the newest first.
    ("amount", ["Dora", "berta", "Cäsar", "Anton"]),
    ("-amount", ["Cäsar", "Dora", "berta", "Anton"]),
])
def test_every_order_of_the_table(table: TestClient, order: str, expected: list[str]) -> None:
    assert titles(table, sort=order, page=1) == expected


def test_an_order_other_than_the_newest_first_works_without_a_page_too(table: TestClient) -> None:
    body = search(table, sort="title", limit=2)
    assert [hit["document"]["title"] for hit in body["items"]] == ["Anton", "berta"]
    assert body["next"] is None and body["total"] == 4


def test_what_does_not_go_with_a_cursor(table: TestClient) -> None:
    cursor = search(table, limit=1)["next"]
    assert cursor
    for params in ({"page": 2}, {"sort": "title"}):
        answer = table.get("/api/v1/search", params={"q": "", "cursor": cursor, **params})
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "cursor_and_page", params
    for params in ({"sort": "colour"}, {"page": 0}, {"page": 100_001}):
        assert table.get("/api/v1/search", params={"q": "", **params}).status_code == 422, params


def test_a_page_of_a_search_with_words(table: TestClient) -> None:
    # A word of two letters is looked for at the start of words, a single letter only as a whole word.
    assert titles(table, "b", sort="title", page=1) == []
    assert titles(table, "be", sort="-title", page=1, limit=1) == ["berta"]
    assert titles(table, "dora", sort="-amount", page=1) == ["Dora"]


# --- The overview -----------------------------------------------------------------------------------------------------


def overview(client: TestClient, **params: object) -> dict:
    answer = client.get("/api/v1/search/overview", params=params)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_the_overview_counts_by_sender_kind_year_and_tag(jule: Account, operator: Account) -> None:
    mine = own_vault(jule)
    household = shared_vault("Haushalt", operator, (jule, "edit"))
    invoice, insurance = kind_id("invoice"), kind_id("insurance")
    add_document(mine, jule, "a", sender="Stadtwerke", kind_id=invoice, date=date(2026, 1, 1), tags=["strom"])
    # The same sender and tag in another vault: one name, counted together.
    add_document(household, jule, "b", sender="stadtwerke", kind_id=invoice, date=date(2025, 1, 1), tags=["Strom"])
    add_document(household, jule, "c", sender="Hansa", kind_id=insurance, date=date(2025, 6, 1), tags=["auto", "strom"])
    add_document(mine, jule, "d")  # no sender, kind, date or tag: only in the total
    with new_client(jule) as client:
        body = overview(client)
        assert body["total"] == 4
        assert [(s["name"].lower(), s["count"]) for s in body["senders"]] == [("stadtwerke", 2), ("hansa", 1)]
        assert [(k["kind"]["id"], k["count"]) for k in body["kinds"]] == [(invoice, 2), (insurance, 1)]
        assert body["years"] == [{"year": 2026, "count": 1}, {"year": 2025, "count": 2}]
        assert [(t["name"].lower(), t["count"]) for t in body["tags"]] == [("strom", 3), ("auto", 1)]
        # One vault.
        one = overview(client, vault_id=mine)
        assert one["total"] == 2 and [(s["name"], s["count"]) for s in one["senders"]] == [("Stadtwerke", 1)]
        # What a kind of the overview finds in the search is what it counted.
        assert search(client, kind_id=invoice)["total"] == 2


def test_the_overview_counts_only_what_the_caller_may_see(jule: Account, operator: Account) -> None:
    tom, lea, out = make_account("tom"), make_account("lea"), make_account("outsider")
    household = shared_vault("Haushalt", operator, (jule, "manage"), (lea, "read"))
    toms = own_vault(tom)
    add_document(household, jule, "Haus", sender="Hansa", date=date(2026, 1, 2), tags=["haus"])
    # Tom's own, with the same sender and tag: Jule and Lea must not count it, nor learn of his year.
    private = add_document(toms, tom, "Geheim", sender="Hansa", date=date(2019, 1, 2), tags=["haus", "geheim"])
    trashed = add_document(household, jule, "Weg", sender="Hansa", date=date(2026, 1, 3))
    with new_client(jule) as client:
        assert client.delete(f"/api/v1/documents/{trashed}").status_code == 200
    for account in (jule, lea):
        with new_client(account) as client:
            body = overview(client)
            assert body["total"] == 1, account.username
            assert body["senders"] == [{"name": "Hansa", "count": 1}]
            assert body["years"] == [{"year": 2026, "count": 1}]
            assert body["tags"] == [{"name": "haus", "count": 1}]
            # Asking for Tom's vault by its number shows nothing of it.
            assert overview(client, vault_id=toms)["total"] == 0
    with new_client(out) as client:
        assert overview(client) == {"total": 0, "senders": [], "kinds": [], "years": [], "tags": []}
    # Shared one by one: counted for the person it is shared with, and only that one.
    with new_client(tom) as client:
        assert client.put(f"/api/v1/documents/{private}/shares/{out.id}", json={"right": "read"}).status_code == 200
    with new_client(out) as client:
        body = overview(client)
        assert body["total"] == 1 and body["years"] == [{"year": 2019, "count": 1}]
        assert overview(client, via_share=True)["total"] == 1
        assert overview(client, via_share=False)["total"] == 0


def test_the_overview_follows_the_status(jule: Account) -> None:
    vault = own_vault(jule)
    add_document(vault, jule, "abgelegt", sender="A")
    add_document(vault, jule, "wartet", sender="B", status="inbox")
    with new_client(jule) as client:
        assert [s["name"] for s in overview(client, status="filed")["senders"]] == ["A"]
        assert [s["name"] for s in overview(client, status="inbox")["senders"]] == ["B"]
        assert overview(client)["total"] == 2


def test_the_overview_needs_a_sign_in() -> None:
    from app.main import app

    with TestClient(app, base_url="http://testserver") as anonymous:
        assert anonymous.get("/api/v1/search/overview").status_code == 401
