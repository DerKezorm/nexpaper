"""``GET /api/v1/dashboard``: the numbers for a dashboard card, for a key of scope ``read`` and no one else.

What matters: the figures are the ones of the account behind the key (a vault it is not in counts for nothing and is
named nowhere), the trash counts for nothing, a deadline is a date somebody has to act on within fourteen days, and
nothing of a document's contents leaves.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import __version__
from app.db import SessionLocal
from app.models import Account, Note, Version, VersionText
from app.services import apikeys, documents, search_index, settings_service

from .conftest import make_account, new_client
from .papers import Date, add_document, freeze, own_vault, shared_vault

#: Noon, UTC: the account below has UTC as its time zone, so "today" is the 10th for it.
NOON = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
TODAY = Date(2026, 10, 10)
DAY = timedelta(days=1)
HIDDEN_WORDS = "Kontonummer-Geheimwort-4711"


@pytest.fixture(autouse=True)
def fresh_brake() -> Iterator[None]:
    apikeys.forget()
    yield
    apikeys.forget()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def key_of(client: TestClient, scope: str = "read") -> str:
    answer = client.post("/api/v1/api-keys", json={"name": "nexdeck", "scope": scope})
    assert answer.status_code == 201, answer.text
    return str(answer.json()["secret"])


def set_zone(account: Account, name: str) -> None:
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None
        row.profile = {"timezone": name}
        db.commit()


class World:
    """Rita reads through her key; the operator shares a vault with her; Bob has a vault she is not in."""

    def __init__(self, client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch
        assert client.put("/api/v1/settings", json={"api_keys_allowed": True}).status_code == 200
        self.rita = make_account("rita")
        self.bob = make_account("bob")
        set_zone(self.rita, "UTC")
        self.home = own_vault(self.rita)
        self.house = shared_vault("Household", operator, (operator, "manage"), (self.rita, "edit"))
        self.bobs = own_vault(self.bob)
        with new_client(self.rita) as browser:
            self.token = key_of(browser)
            self.upload_token = key_of(browser, "upload")

    def add(self, when: datetime, vault: int, owner: Account | None, title: str, **fields: Any) -> int:
        freeze(self.monkeypatch, when)
        fields.setdefault("content", None)
        return add_document(vault, owner, title, **fields)

    def card(self, client: TestClient, token: str | None = None) -> dict[str, Any]:
        freeze(self.monkeypatch, NOON)
        answer = client.get("/api/v1/dashboard", headers=bearer(token or self.token))
        assert answer.status_code == 200, answer.text
        return dict(answer.json())


@pytest.fixture
def world(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(client, operator, monkeypatch)


def mixed(world: World) -> dict[str, int]:
    """A mixed stock. Returns the ids by name."""
    ids: dict[str, int] = {}
    # The inbox of rita: three waiting (the oldest first in the card), one being read.
    ids["old"] = world.add(NOON - 30 * DAY, world.home, world.rita, "Oldest bill", status="inbox")
    ids["second"] = world.add(NOON - 20 * DAY, world.house, world.rita, "Second letter", status="inbox")
    ids["new"] = world.add(NOON - 2 * DAY, world.home, world.rita, "Newest letter", status="inbox")
    ids["reading"] = world.add(NOON - 1 * DAY, world.home, world.rita, "Being read", status="processing")
    # Filed: two old (one just over a week, one long ago), two in the last week.
    ids["filed_old"] = world.add(NOON - 100 * DAY, world.home, world.rita, "Old contract", status="filed")
    ids["filed_last_week"] = world.add(NOON - 10 * DAY, world.home, world.rita, "Filed last week", status="filed")
    ids["filed_a"] = world.add(NOON - 6 * DAY, world.house, world.rita, "Filed this week", status="filed")
    ids["filed_b"] = world.add(NOON - 3 * DAY, world.house, world.rita, "Filed too", status="filed")
    # Not hers: Bob's own vault, with an inbox, a deadline and a document of this week.
    ids["bobs"] = world.add(NOON - 40 * DAY, world.bobs, world.bob, "Bob's secret", status="inbox",
                            dates=[("due", TODAY + DAY)])
    ids["bobs_recent"] = world.add(NOON - DAY, world.bobs, world.bob, "Bob's new one", status="filed")
    # In the trash.
    ids["trashed"] = world.add(NOON - 50 * DAY, world.home, world.rita, "Thrown away", status="inbox",
                               dates=[("due", TODAY + DAY)])
    with SessionLocal() as db:
        documents.trash(db, world.rita.id, ids["trashed"])
    return ids


def test_the_numbers_of_a_mixed_stock(client: TestClient, world: World) -> None:
    ids = mixed(world)
    card = world.card(client)
    assert card["version"] == __version__
    assert card["inbox"] == 3
    assert [item["title"] for item in card["inbox_oldest"]] == ["Oldest bill", "Second letter", "Newest letter"]
    assert [item["id"] for item in card["inbox_oldest"]] == [ids["old"], ids["second"], ids["new"]]
    assert card["inbox_oldest"][0]["added_at"] == "2026-09-10T12:00:00+00:00"
    assert card["inbox_oldest_at"] == "2026-09-10T12:00:00+00:00"
    assert card["filed"] == 4
    assert card["processing"] == 1
    # Everything not in the trash: 3 waiting + 1 being read + 4 filed.
    assert card["total"] == 8
    # The last seven days: the newest letter (2 days), the one being read (1), two filed (6 and 3 days).
    assert card["added_week"] == 4
    assert card["deadlines"] == []


def test_five_oldest_at_most_and_the_oldest_comes_first(client: TestClient, world: World) -> None:
    for number in range(7):
        world.add(NOON - (10 - number) * DAY, world.home, world.rita, f"Letter {number}", status="inbox")
    card = world.card(client)
    assert card["inbox"] == 7
    assert [item["title"] for item in card["inbox_oldest"]] == [f"Letter {n}" for n in range(5)]
    assert card["inbox_oldest_at"] == card["inbox_oldest"][0]["added_at"]


def test_an_empty_stock_says_zero_and_no_oldest(client: TestClient, world: World) -> None:
    assert world.card(client) == {
        "version": __version__, "inbox": 0, "inbox_oldest": [], "inbox_oldest_at": None, "filed": 0, "total": 0,
        "added_week": 0, "processing": 0, "deadlines": []}


def test_another_vault_counts_for_nothing_and_is_named_nowhere(client: TestClient, world: World) -> None:
    mixed(world)
    seen = world.card(client)
    assert "Bob" not in str(seen) and "secret" not in str(seen)
    # The same stock seen by Bob's own key: his numbers, none of Rita's.
    with new_client(world.bob) as browser:
        bobs_token = key_of(browser)
    card = world.card(client, bobs_token)
    assert (card["inbox"], card["total"], card["filed"], card["added_week"]) == (1, 2, 1, 1)
    assert [item["title"] for item in card["inbox_oldest"]] == ["Bob's secret"]
    assert [item["title"] for item in card["deadlines"]] == ["Bob's secret"]
    assert "Oldest bill" not in str(card)


def test_a_document_shared_by_hand_counts_for_the_one_it_is_shared_with(client: TestClient, world: World) -> None:
    mixed(world)
    shared = world.add(NOON - 3 * DAY, world.bobs, world.bob, "Shared with rita", status="filed")
    with new_client(world.bob) as browser:
        answer = browser.put(f"/api/v1/documents/{shared}/shares/{world.rita.id}", json={"right": "read"})
        assert answer.status_code in (200, 201), answer.text
    card = world.card(client)
    assert (card["total"], card["filed"], card["added_week"]) == (9, 5, 5)


def test_a_vault_with_the_right_to_read_only_has_no_inbox_but_counts_the_rest(client: TestClient,
                                                                              world: World) -> None:
    """As in the menu: an inbox is for who may file; somebody who may only read sees the archive."""
    readers = shared_vault("Library", make_account("anna"), (world.rita, "read"))
    world.add(NOON - 2 * DAY, readers, None, "Waiting there", status="inbox")
    world.add(NOON - 2 * DAY, readers, None, "Filed there", status="filed")
    card = world.card(client)
    assert card["inbox"] == 0 and card["inbox_oldest"] == []
    assert (card["total"], card["filed"], card["added_week"]) == (2, 1, 2)


def test_deadlines_are_the_dated_terms_of_the_next_fourteen_days_by_day(client: TestClient, world: World) -> None:
    ids = {
        "later": world.add(NOON, world.home, world.rita, "Later", status="filed", dates=[("due", TODAY + 14 * DAY)]),
        "today": world.add(NOON, world.house, world.rita, "Today", status="filed", dates=[("contract_end", TODAY)]),
        "soon": world.add(NOON, world.home, world.rita, "Soon", status="filed",
                          dates=[("warranty_end", TODAY + 3 * DAY)]),
        # Out: yesterday, fifteen days ahead, and a day nobody has to act on.
        "past": world.add(NOON, world.home, world.rita, "Past", status="filed", dates=[("due", TODAY - DAY)]),
        "far": world.add(NOON, world.home, world.rita, "Far", status="filed", dates=[("due", TODAY + 15 * DAY)]),
        "keep": world.add(NOON, world.home, world.rita, "Keep", status="filed", dates=[("keep_until", TODAY + DAY)]),
        # A document with a date on it (the receipt's) and no term.
        "dated": world.add(NOON, world.home, world.rita, "Dated", status="filed", date=TODAY + DAY),
        # Three terms of one document: two are deadlines, so two lines.
        "both": world.add(NOON, world.home, world.rita, "Both", status="inbox",
                          dates=[("due", TODAY + 5 * DAY), ("keep_until", TODAY + 6 * DAY),
                                 ("contract_end", TODAY + 7 * DAY)]),
    }
    card = world.card(client)
    assert [(d["title"], d["date"], d["kind"]) for d in card["deadlines"]] == [
        ("Today", "2026-10-10", "contract_end"), ("Soon", "2026-10-13", "warranty_end"),
        ("Both", "2026-10-15", "due"), ("Both", "2026-10-17", "contract_end"), ("Later", "2026-10-24", "due")]
    assert [d["id"] for d in card["deadlines"]] == [ids["today"], ids["soon"], ids["both"], ids["both"], ids["later"]]


def test_at_most_twenty_deadlines_and_none_of_the_trash(client: TestClient, world: World) -> None:
    for number in range(25):
        world.add(NOON, world.home, world.rita, f"Bill {number:02d}", status="filed",
                  dates=[("due", TODAY + (number % 14) * DAY)])
    gone = world.add(NOON, world.home, world.rita, "Bin", status="filed", dates=[("due", TODAY)])
    with SessionLocal() as db:
        documents.trash(db, world.rita.id, gone)
    card = world.card(client)
    assert len(card["deadlines"]) == 20
    days = [d["date"] for d in card["deadlines"]]
    assert days == sorted(days) and "Bin" not in str(card)


def test_today_is_the_day_of_the_account_not_of_the_server(client: TestClient, world: World) -> None:
    """At noon UTC on the 9th it is already the 10th in Auckland: a term of the 10th is today there, one of the 9th
    is gone."""
    set_zone(world.rita, "Pacific/Auckland")
    world.add(NOON, world.home, world.rita, "Gone", status="filed", dates=[("due", Date(2026, 10, 9))])
    world.add(NOON, world.home, world.rita, "Today there", status="filed", dates=[("due", Date(2026, 10, 10))])
    freeze(world.monkeypatch, datetime(2026, 10, 9, 12, 0, tzinfo=UTC))
    answer = client.get("/api/v1/dashboard", headers=bearer(world.token))
    assert [d["title"] for d in answer.json()["deadlines"]] == ["Today there"]


def test_links_use_the_public_address_else_the_one_asked(client: TestClient, world: World) -> None:
    waiting = world.add(NOON - DAY, world.home, world.rita, "Waiting", status="inbox")
    filed = world.add(NOON, world.home, world.rita, "Filed", status="filed", dates=[("due", TODAY + DAY)])
    card = world.card(client)
    assert card["inbox_oldest"][0]["url"] == f"http://testserver/eingang/{waiting}"
    assert card["deadlines"][0]["url"] == f"http://testserver/dokument/{filed}"
    with SessionLocal() as db:
        settings_service.save(db, {"public_url": "https://paper.example.com/"})
    card = world.card(client)
    assert card["inbox_oldest"][0]["url"] == f"https://paper.example.com/eingang/{waiting}"
    assert card["deadlines"][0]["url"] == f"https://paper.example.com/dokument/{filed}"


def test_nothing_of_the_contents_leaves(client: TestClient, world: World) -> None:
    made = world.add(NOON - DAY, world.home, world.rita, "Plain title", status="inbox", content=b"%PDF-1.4\n%%EOF\n",
                     sender="Stadtwerke Example", amount=12345, tags=["steuer"], dates=[("due", TODAY + 2 * DAY)])
    with SessionLocal() as db:
        version = db.scalar(select(Version).where(Version.document_id == made))
        assert version is not None
        db.add(VersionText(version_id=version.id, document_id=made, text=HIDDEN_WORDS, pages=1,
                           digest=search_index.text_digest(HIDDEN_WORDS)))
        db.add(Note(document_id=made, user_id=world.rita.id, text=HIDDEN_WORDS + " note"))
        db.commit()
    card = world.card(client)
    text = str(card)
    assert card["inbox"] == 1 and len(card["deadlines"]) == 1
    assert HIDDEN_WORDS not in text
    for word in ("Stadtwerke", "12345", "steuer", "amount", "sender", "tags"):
        assert word not in text, word
    assert set(card) == {"version", "inbox", "inbox_oldest", "inbox_oldest_at", "filed", "total", "added_week",
                         "processing", "deadlines"}
    assert set(card["inbox_oldest"][0]) == {"id", "title", "added_at", "url"}
    assert set(card["deadlines"][0]) == {"id", "title", "date", "kind", "url"}


# --- The walls ----------------------------------------------------------------------------------------------------------


def test_a_web_page_is_refused(client: TestClient, world: World) -> None:
    answer = client.get("/api/v1/dashboard", headers={**bearer(world.token), "Origin": "https://example.com"})
    assert answer.status_code == 403 and answer.json()["detail"]["code"] == "origin_refused"


def test_no_key_and_a_wrong_key_are_refused(client: TestClient, world: World) -> None:
    for headers in ({}, bearer("npk_" + "x" * 43), bearer("not-a-token")):
        with new_client() as program:
            answer = program.get("/api/v1/dashboard", headers=headers)
            assert answer.status_code == 401 and answer.json()["detail"]["code"] == "key_invalid", headers
    # A session is no key either.
    assert client.get("/api/v1/dashboard").status_code == 401


def test_a_device_token_is_not_a_key(client: TestClient, world: World) -> None:
    device = client.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with new_client() as program:
        answer = program.get("/api/v1/dashboard", headers=bearer(device))
    assert answer.status_code == 401 and answer.json()["detail"]["code"] == "token_wrong_kind"


def test_a_key_that_uploads_reads_no_card(client: TestClient, world: World) -> None:
    answer = client.get("/api/v1/dashboard", headers=bearer(world.upload_token))
    assert answer.status_code == 403 and answer.json()["detail"]["code"] == "key_scope"


def test_closed_while_the_operator_has_not_switched_keys_on(client: TestClient, world: World) -> None:
    assert client.put("/api/v1/settings", json={"api_keys_allowed": False}).status_code == 200
    answer = client.get("/api/v1/dashboard", headers=bearer(world.token))
    assert answer.status_code == 401 and answer.json()["detail"]["code"] == "api_off"


def test_the_key_slows_down_at_its_rate(client: TestClient, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(apikeys, "PER_MINUTE", 2)
    assert client.get("/api/v1/dashboard", headers=bearer(world.token)).status_code == 200
    assert client.get("/api/v1/dashboard", headers=bearer(world.token)).status_code == 200
    slow = client.get("/api/v1/dashboard", headers=bearer(world.token))
    assert slow.status_code == 429 and slow.headers["retry-after"] == "60"
    assert slow.json()["detail"]["code"] == "slow_down"
