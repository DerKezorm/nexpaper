"""The sums of the archive's table (A1, ``GET /api/v1/search/sum``): over the whole result of a search or a filter, per
currency, with the number of documents without an amount; the same words, filters and rights as the list, so that no
document the caller may not see is ever counted."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Account, Document, DocumentDate
from app.services import brakes

from .conftest import make_account, new_client
from .papers import add_document, own_vault, shared_vault
from .searching import give_text
from .test_search_rights import raw_key

PATH = "/api/v1/search/sum"
WORD = "wartungsvertrag"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def currency(document_id: int, code: str) -> None:
    with SessionLocal() as db:
        row = db.get(Document, document_id)
        assert row is not None
        row.currency = code
        db.commit()


def summed(client: TestClient, **params: Any) -> dict[str, Any]:
    answer = client.get(PATH, params={"status": "filed", **params})
    assert answer.status_code == 200, answer.text
    return answer.json()  # type: ignore[no-any-return]


@pytest.fixture(autouse=True)
def plenty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(brakes.LIMITS, "search", 100_000)


@pytest.fixture
def town(client: TestClient, operator: Account) -> dict[str, Any]:
    jule, tom = make_account("jule"), make_account("tom")
    house = shared_vault("Haushalt", operator, (jule, "manage"), (tom, "edit"))
    day = date(2026, 3, 14)
    ids = {
        "strom": add_document(house, jule, "Strom März", amount=12_345, date=day),
        "gas": add_document(house, jule, "Gas März", amount=5_000, date=day),
        "hotel": add_document(house, jule, "Hotel Zürich", amount=20_000, date=day),
        "dollar": add_document(house, jule, "Kabel aus Übersee", amount=999, date=day),
        "zettel": add_document(house, jule, "Zettel ohne Betrag", date=day),
        # jule's own vault, same month: never tom's.
        "privat": add_document(own_vault(jule), jule, "Privat März", amount=70_000, date=day),
    }
    currency(ids["hotel"], "CHF")
    currency(ids["dollar"], "USD")
    give_text(ids["strom"], f"Ihr {WORD} Strom")
    give_text(ids["privat"], f"Mein {WORD} privat")
    return {"jule": jule, "tom": tom, "house": house, **ids}


def test_per_currency_and_without_an_amount(town: dict[str, Any]) -> None:
    with new_client(town["tom"]) as c:
        found = summed(c)
        listed = c.get("/api/v1/search", params={"status": "filed", "limit": 1}).json()["total"]
    assert found == {"total": 5, "without": 1, "sums": [
        {"currency": "CHF", "cents": 20_000}, {"currency": "EUR", "cents": 17_345}, {"currency": "USD", "cents": 999}]}
    assert found["total"] == listed


def test_never_a_document_the_caller_may_not_see(town: dict[str, Any]) -> None:
    with new_client(town["jule"]) as c:
        assert summed(c)["sums"][1] == {"currency": "EUR", "cents": 87_345}
        assert summed(c, q=WORD) == {"total": 2, "without": 0, "sums": [{"currency": "EUR", "cents": 82_345}]}
    with new_client(town["tom"]) as c:
        # The same month, the same word: jule's own document is not his.
        assert summed(c, q=WORD) == {"total": 1, "without": 0, "sums": [{"currency": "EUR", "cents": 12_345}]}
        assert summed(c, date_from="2026-03-01", date_to="2026-03-31")["total"] == 5
    out = make_account("outsider")
    with new_client(out) as c:
        assert summed(c) == {"total": 0, "without": 0, "sums": []}
        assert summed(c, vault_id=town["house"]) == {"total": 0, "without": 0, "sums": []}


def test_a_share_counts_and_the_trash_does_not(town: dict[str, Any]) -> None:
    with new_client(town["jule"]) as c:
        assert c.put(f"/api/v1/documents/{town['privat']}/shares/{town['tom'].id}", json={"right": "read"}).status_code == 200
        assert c.delete(f"/api/v1/documents/{town['gas']}").status_code == 200
    with new_client(town["tom"]) as c:
        found = summed(c)
        assert found["total"] == 5 and found["sums"][1] == {"currency": "EUR", "cents": 82_345}
        assert summed(c, via_share=True) == {"total": 1, "without": 0, "sums": [{"currency": "EUR", "cents": 70_000}]}


def test_only_counts_without_amounts(town: dict[str, Any]) -> None:
    with new_client(town["tom"]) as c:
        assert summed(c, q="zettel") == {"total": 1, "without": 1, "sums": []}
        assert summed(c, q="nichtsdergleichen") == {"total": 0, "without": 0, "sums": []}


def test_with_the_filter_may_go(town: dict[str, Any]) -> None:
    with SessionLocal() as db:
        db.add(DocumentDate(document_id=town["gas"], kind="keep_until", date=date(2020, 12, 31), manual=True))
        db.add(DocumentDate(document_id=town["privat"], kind="keep_until", date=date(2020, 12, 31), manual=True))
        db.commit()
    with new_client(town["tom"]) as c:
        assert summed(c, keep="expired") == {"total": 1, "without": 0, "sums": [{"currency": "EUR", "cents": 5_000}]}
        assert c.get("/api/v1/search", params={"status": "filed", "keep": "expired"}).json()["total"] == 1
    with new_client(town["jule"]) as c:
        assert summed(c, keep="expired")["sums"] == [{"currency": "EUR", "cents": 75_000}]


def test_devices_keys_and_strangers(client: TestClient, town: dict[str, Any]) -> None:
    assert client.put("/api/v1/settings", json={"api_keys_allowed": True}).status_code == 200
    with new_client(town["tom"]) as c:
        token = c.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with TestClient(app, base_url="http://testserver") as program:
        assert program.get(PATH, params={"q": WORD}, headers=bearer(token)).json()["total"] == 1
        assert program.get(PATH, params={"q": WORD}, headers=bearer(raw_key(town["tom"], "read"))).json()["total"] == 1
        assert program.get(PATH, params={"q": WORD}, headers=bearer(raw_key(town["tom"], "upload"))).status_code == 403
    with TestClient(app, base_url="http://testserver", headers={"X-Nexpaper-Client": "tab-tests000"}) as anonymous:
        assert anonymous.get(PATH).status_code == 401


def test_the_brake_and_hostile_searches(town: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    with new_client(town["tom"]) as c:
        assert c.get(PATH, params={"q": "betrag:>abc"}).json()["detail"]["code"] == "invalid_amount"
        assert c.get(PATH, params={"q": "x" * 501}).status_code == 422
        monkeypatch.setitem(brakes.LIMITS, "search", 1)
        brakes.forget()
        assert c.get(PATH).status_code == 200
        answer = c.get(PATH)
        assert answer.status_code == 429 and answer.json()["detail"]["code"] == "search_too_often"


def test_a_link_opens_none_of_the_new_ways(client: TestClient, town: dict[str, Any]) -> None:
    """A link to a document is for that document's page: its token reaches neither the sums, nor many at once, nor
    the saved searches (as a bearer, in the path or as a query)."""
    with new_client(town["jule"]) as c:
        made = c.post(f"/api/v1/documents/{town['strom']}/links", json={"recipient": "x", "days": 7,
                                                                       "allow_download": True})
        assert made.status_code in (200, 201), made.text
        token = made.json()["token"]
    with TestClient(app, base_url="http://testserver", headers={"X-Nexpaper-Client": "tab-tests000"}) as stranger:
        for method, path, body in (("GET", PATH, None), ("GET", "/api/v1/saved-searches", None),
                                   ("POST", "/api/v1/documents/bulk", {"ids": [town["strom"]], "action": "trash"})):
            assert stranger.request(method, path, json=body, headers=bearer(token)).status_code == 401
            assert stranger.request(method, path, json=body, params={"token": token}).status_code == 401
        assert stranger.get(f"/api/v1/l/{token}/search/sum").status_code == 404
    with SessionLocal() as db:
        row = db.get(Document, town["strom"])
        assert row is not None and row.status == "filed"