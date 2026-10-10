"""The search: its language (German and English), parts of words, case, accents and ``ß``, phrases, filters, hostile
input, the excerpt and its marks, the order and the cursor, the trash, and the rights (nothing leaks)."""

from __future__ import annotations

import statistics
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, Kind
from app.services import catalog, searchtext

from .conftest import make_account, new_client
from .papers import add_document, own_vault, shared_vault
from .searching import found, give_text, marked, search, titles


def kind_id(key: str) -> int:
    with SessionLocal() as db:
        catalog.ensure_kinds(db)
        return int(db.scalar(select(Kind.id).where(Kind.key == key)) or 0)


@pytest.fixture
def jule() -> Account:
    return make_account("jule")


@pytest.fixture
def shelf(jule: Account) -> dict[str, int]:
    """Jule's own vault with a few made-up documents."""
    vault = own_vault(jule)
    made = {
        "strom": add_document(vault, jule, "Abschlag Strom Oktober", sender="Stadtwerke Lindenau", kind_id=kind_id("invoice"),
                              amount=8400, date=date(2026, 10, 1), tags=["haus", "strom"]),
        "auto": add_document(vault, jule, "Kfz-Versicherung 2026", sender="Hansa Versicherung", kind_id=kind_id("insurance"),
                             amount=41250, date=date(2026, 1, 15), tags=["auto"]),
        "brief": add_document(vault, jule, "Brief der Schule", sender="Grundschule am Weiher", kind_id=kind_id("school"),
                              date=date(2025, 9, 3)),
        "quittung": add_document(vault, jule, "Quittung Fahrrad", sender="Fahrradladen Speiche",
                                 kind_id=kind_id("receipt"), amount=1230, date=date(2025, 5, 20), tags=["garantie"]),
    }
    give_text(made["strom"], "Stadtwerke Lindenau\nIhr Stromabschlag für Oktober.\nBitte überweisen Sie 84,00 EUR.",
              "Seite zwei: Zählerstand 12345, Lindenallee 4, Straße der Einheit")
    give_text(made["auto"], "Beitragsrechnung. Der Beitrag wird abgebucht. Überweisen Sie bitte nichts.")
    give_text(made["brief"], "Liebe Eltern, am Montag ist der Wandertag. Müller, Klasse 3b.")
    give_text(made["quittung"], "Kassenbon Fahrradladen, Garantie zwei Jahre, 12,30 EUR bar.")
    with new_client(jule) as client:
        client.post(f"/api/v1/documents/{made['brief']}/notes", json={"text": "Turnbeutel nicht vergessen"})
    return made


@pytest.fixture
def browser(jule: Account, shelf: dict[str, int]) -> TestClient:
    with new_client(jule) as client:
        yield client


# --- The language -----------------------------------------------------------------------------------------------------


def test_every_word_must_be_found_in_one_of_the_fields(browser: TestClient) -> None:
    assert found(browser, "strom") == {"Abschlag Strom Oktober"}  # title and text
    assert found(browser, "hansa") == {"Kfz-Versicherung 2026"}  # sender
    assert found(browser, "turnbeutel") == {"Brief der Schule"}  # note
    assert found(browser, "garantie") == {"Quittung Fahrrad"}  # tag and text
    assert found(browser, "wandertag") == {"Brief der Schule"}  # text only
    # Two words: both, each anywhere.
    assert found(browser, "lindenau oktober") == {"Abschlag Strom Oktober"}
    assert found(browser, "lindenau wandertag") == set()


def test_a_part_of_a_word_is_found_in_the_middle_too(browser: TestClient) -> None:
    assert found(browser, "werke") == {"Abschlag Strom Oktober"}  # "Stadtwerke" (the mock's own example)
    assert found(browser, "abschlag") == {"Abschlag Strom Oktober"}  # title, and "Stromabschlag" in the text
    assert found(browser, "rechnung") == {"Kfz-Versicherung 2026"}  # only inside "Beitragsrechnung"
    assert found(browser, "versich") == {"Kfz-Versicherung 2026"}
    # Two letters count at the start of a word only, one letter as a whole word.
    assert found(browser, "zä") == {"Abschlag Strom Oktober"}
    assert "Abschlag Strom Oktober" not in found(browser, "hl")
    assert found(browser, "3b") == {"Brief der Schule"}


def test_case_accents_and_sharp_s_do_not_count(browser: TestClient) -> None:
    for query in ("STRASSE", "strasse", "Straße", "STRAẞE", "strase der"):
        assert ("Abschlag Strom Oktober" in found(browser, query)) is (query != "strase der"), query
    assert found(browser, "uberweisen") == {"Abschlag Strom Oktober", "Kfz-Versicherung 2026"}
    assert found(browser, "ÜBERWEISEN") == {"Abschlag Strom Oktober", "Kfz-Versicherung 2026"}
    assert found(browser, "muller") == {"Brief der Schule"}
    assert found(browser, "zahlerstand") == {"Abschlag Strom Oktober"}


def test_a_phrase_is_its_words_in_this_order(browser: TestClient) -> None:
    assert found(browser, '"bitte überweisen"') == {"Abschlag Strom Oktober"}
    # The same words the other way round, in the other document.
    assert found(browser, '"überweisen sie bitte"') == {"Kfz-Versicherung 2026"}
    assert found(browser, "bitte überweisen") == {"Abschlag Strom Oktober", "Kfz-Versicherung 2026"}
    # An unclosed quote runs to the end.
    assert found(browser, '"liebe eltern') == {"Brief der Schule"}


@pytest.mark.parametrize("query, expected", [
    ("art:rechnung", {"Abschlag Strom Oktober"}),
    ("kind:invoice", {"Abschlag Strom Oktober"}),
    ("art:Versich", {"Kfz-Versicherung 2026"}),
    ("absender:hansa", {"Kfz-Versicherung 2026"}),
    ("sender:LINDENAU", {"Abschlag Strom Oktober"}),
    ('absender:"am weiher"', {"Brief der Schule"}),
    ("tag:gar", {"Quittung Fahrrad"}),
    ("tag:strom", {"Abschlag Strom Oktober"}),
    ("betrag:>100", {"Kfz-Versicherung 2026"}),
    ("betrag:<84", {"Quittung Fahrrad"}),
    ("amount:=12.30", {"Quittung Fahrrad"}),
    ("betrag:12,3", {"Quittung Fahrrad"}),
    ("betrag:>1.000,00", set()),
    ("amount:>12.29 amount:<84.01", {"Quittung Fahrrad", "Abschlag Strom Oktober"}),
    ("strom art:rechnung absender:stadtwerke betrag:>80", {"Abschlag Strom Oktober"}),
    ("art:rechnung absender:hansa", set()),
])
def test_the_filters_of_the_language(browser: TestClient, query: str, expected: set[str]) -> None:
    assert found(browser, query) == expected


def test_filters_as_parameters(browser: TestClient, jule: Account, shelf: dict[str, int]) -> None:
    assert found(browser, kind_id=kind_id("insurance")) == {"Kfz-Versicherung 2026"}
    assert found(browser, sender="Stadtwerke Lindenau") == {"Abschlag Strom Oktober"}
    assert found(browser, sender="Stadtwerke") == set()  # a sender's name, exactly
    assert found(browser, tag="auto") == {"Kfz-Versicherung 2026"}
    assert found(browser, date_from="2026-01-01") == {"Abschlag Strom Oktober", "Kfz-Versicherung 2026"}
    assert found(browser, date_to="2025-12-31", date_from="2025-06-01") == {"Brief der Schule"}
    assert found(browser, owner_id=jule.id) == set(found(browser))
    assert found(browser, vault_id=own_vault(jule)) == set(found(browser))
    assert found(browser, status="inbox") == set()
    assert found(browser, "strom", status="filed") == {"Abschlag Strom Oktober"}


@pytest.mark.parametrize("query", [
    'NEAR(strom oktober)', 'strom*', '-strom', '(strom', 'strom)', '^strom', 'strom OR hansa', 'strom AND', 'NOT strom',
    '"', '""', '"strom', 'title:strom', '{title}: strom', 'strom:', ':strom', 'a"b"c', "str'om", '\\', '%', '_', '*',
    'betrag:', 'art:', 'tag:"', 'x' * 200, 'ünïcödé ✓ 🧾', 'drop table documents;--',
])
def test_hostile_input_is_only_characters(browser: TestClient, query: str) -> None:
    answer = browser.get("/api/v1/search", params={"q": query})
    assert answer.status_code == 200, (query, answer.text)
    body = answer.json()
    assert body["total"] == len(body["items"])
    # FTS5's operators mean nothing: the words in them are words.
    if query in ('strom*', '-strom', '(strom', 'strom)', '^strom'):
        assert "Abschlag Strom Oktober" in {hit["document"]["title"] for hit in body["items"]}, query
    # An operator of FTS5 is a word like any other: NEAR, OR and a column name must be found as words.
    if query in ('NEAR(strom oktober)', 'title:strom', 'strom OR hansa', 'NOT strom'):
        assert body["total"] == 0, query


def test_limits_on_a_search(browser: TestClient) -> None:
    assert browser.get("/api/v1/search", params={"q": "x" * 501}).status_code == 422
    answer = browser.get("/api/v1/search", params={"q": " ".join(f"w{n}" for n in range(13))})
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "too_many_terms"
    assert answer.json()["detail"]["max"] == searchtext.MAX_TERMS
    assert search(browser, " ".join(f"strom{n}" for n in range(12)))["total"] == 0
    answer = browser.get("/api/v1/search", params={"q": "betrag:>viel"})
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "invalid_amount"
    for cursor in ("x", "AAAA", "MjAyNi0xMC0wMXwtMQ", "bm90LWEtZGF0ZXwx"):
        answer = browser.get("/api/v1/search", params={"q": "", "cursor": cursor})
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "invalid_cursor", cursor
    assert browser.get("/api/v1/search", params={"limit": 101}).status_code == 422


def test_an_empty_search_is_everything_the_person_sees_newest_first(browser: TestClient) -> None:
    body = search(browser)
    assert [hit["document"]["title"] for hit in body["items"]] == [
        "Abschlag Strom Oktober", "Kfz-Versicherung 2026", "Brief der Schule", "Quittung Fahrrad"]
    assert body["total"] == 4 and body["next"] is None
    assert all(hit["excerpt"] is None and hit["title_marks"] == [] for hit in body["items"])
    assert body["understood"] == {"words": [], "phrases": [], "kinds": [], "senders": [], "tags": [], "amounts": []}


def test_what_the_search_understood(browser: TestClient) -> None:
    body = search(browser, 'Straße "Bitte Überweisen" art:rechnung tag:Haus betrag:>1,5 R-2026-17')
    assert body["understood"] == {
        "words": ["strasse"], "phrases": ["bitte uberweisen", "r 2026 17"], "kinds": ["rechnung"], "senders": [],
        "tags": ["Haus"], "amounts": [{"op": ">", "cents": 150}],
    }


# --- Excerpt and marks ------------------------------------------------------------------------------------------------


def test_a_hit_carries_its_marks_and_an_excerpt_as_ranges(browser: TestClient) -> None:
    hit = search(browser, "werke abschlag")["items"][0]
    document = hit["document"]
    assert marked(document["title"], hit["title_marks"]) == ["Abschlag"]
    assert marked(document["sender"]["name"], hit["sender_marks"]) == ["werke"]
    excerpt = hit["excerpt"]
    assert excerpt["source"] == "text" and "Stromabschlag" in excerpt["text"] and "<" not in excerpt["text"]
    assert sorted(marked(excerpt["text"], excerpt["marks"])) == ["abschlag", "werke"]
    # A phrase is marked as one piece, whatever stands between its words.
    hit = search(browser, '"bitte überweisen"')["items"][0]
    assert marked(hit["excerpt"]["text"], hit["excerpt"]["marks"]) == ["Bitte überweisen"]


def test_the_excerpt_comes_from_the_notes_when_the_text_does_not_hold_the_word(browser: TestClient) -> None:
    hit = search(browser, "turnbeutel")["items"][0]
    assert hit["excerpt"]["source"] == "notes"
    assert marked(hit["excerpt"]["text"], hit["excerpt"]["marks"]) == ["Turnbeutel"]


def test_marks_count_in_utf16_units_and_long_texts_are_cut_around_the_place(jule: Account) -> None:
    document = add_document(own_vault(jule), jule, "Bon 🧾 Café")
    give_text(document, "🧾🧾 " + "Wort " * 400 + "Café Sonnenschein Rechnung " + "Ende " * 400)
    with new_client(jule) as client:
        hit = search(client, "sonnenschein café")["items"][0]
    assert marked(hit["document"]["title"], hit["title_marks"]) == ["Café"]
    excerpt = hit["excerpt"]
    assert excerpt["text"].startswith("… ") and excerpt["text"].endswith(" …") and len(excerpt["text"]) < 260
    assert marked(excerpt["text"], excerpt["marks"]) == ["Café", "Sonnenschein"]


# --- Order, cursor, total ---------------------------------------------------------------------------------------------


def test_pages_follow_one_another_without_gaps_or_twice(jule: Account) -> None:
    vault = own_vault(jule)
    made = []
    for number in range(23):
        day = date(2026, 1, 1 + number % 5)  # many on the same day: the id decides among them
        made.append(add_document(vault, jule, f"Gleich {number}", date=day))
    add_document(vault, jule, "Ohne Datum")  # the day it came in counts
    with new_client(jule) as client:
        seen: list[str] = []
        cursor = None
        while True:
            params = {"limit": 5, **({"cursor": cursor} if cursor else {})}
            body = search(client, "gleich", **params)
            assert body["total"] == 23
            seen += [hit["document"]["title"] for hit in body["items"]]
            cursor = body["next"]
            if cursor is None:
                break
        assert len(seen) == 23 and len(set(seen)) == 23
        assert titles(client, limit=1) == ["Ohne Datum"]
    # Newest first, then the higher id.
    expected = sorted(range(23), key=lambda n: (date(2026, 1, 1 + n % 5), made[n]), reverse=True)
    assert seen == [f"Gleich {n}" for n in expected]


# --- The trash, the rights --------------------------------------------------------------------------------------------


def test_the_trash_is_searched_only_when_asked_and_only_the_own(jule: Account, operator: Account) -> None:
    tom = make_account("tom")
    household = shared_vault("Haushalt", operator, (jule, "edit"), (tom, "edit"))
    mine = add_document(household, jule, "Altpapier von Jule")
    his = add_document(household, tom, "Altpapier von Tom")
    with new_client(jule) as client:
        assert client.delete(f"/api/v1/documents/{mine}").status_code == 200
        assert client.delete(f"/api/v1/documents/{his}").status_code == 200
        assert found(client, "altpapier") == set()
        assert found(client, "altpapier", trash=True) == {"Altpapier von Jule"}
    with new_client(tom) as client:
        assert found(client, "altpapier", trash=True) == {"Altpapier von Tom"}
        assert client.post(f"/api/v1/documents/{his}/restore").status_code == 200
    with new_client(jule) as client:
        assert found(client, "altpapier") == {"Altpapier von Tom"}


def test_a_search_reaches_what_a_person_may_read_and_nothing_else(operator: Account) -> None:
    jule, tom, lea = make_account("jule"), make_account("tom"), make_account("lea")
    household = shared_vault("Haushalt", operator, (jule, "read"))
    add_document(household, operator, "Gemeinsam Wasser")
    secret = add_document(own_vault(tom), tom, "Toms Wasser")
    lent = add_document(own_vault(lea), lea, "Leas Wasser")
    with new_client(lea) as client:
        assert client.put(f"/api/v1/documents/{lent}/shares/{jule.id}", json={"right": "read"}).status_code == 200
    with new_client(jule) as client:
        assert found(client, "wasser") == {"Gemeinsam Wasser", "Leas Wasser"}
        assert search(client, "wasser")["total"] == 2
        # The text of somebody else's document: as if there were none.
        assert client.get(f"/api/v1/documents/{secret}/versions/1/text").status_code == 404
    with new_client(tom) as client:
        assert found(client, "wasser") == {"Toms Wasser"}
    # A device and a read key reach the same; a wrong token nothing.
    with new_client(jule) as client:
        token = client.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with TestClient(client.app, base_url="http://testserver") as device:
        answer = device.get("/api/v1/search", params={"q": "wasser"}, headers={"Authorization": f"Bearer {token}"})
        assert {hit["document"]["title"] for hit in answer.json()["items"]} == {"Gemeinsam Wasser", "Leas Wasser"}
        assert device.get("/api/v1/search", headers={"Authorization": "Bearer npd_" + "w" * 43}).status_code == 401
        assert device.get("/api/v1/search").status_code == 401


def _answer(client: TestClient, query: str) -> dict:
    body = search(client, query)
    for hit in body["items"]:
        # The numbers that every change moves are not what is compared.
        hit["document"].pop("change_seq")
    return body


def test_nothing_of_what_the_person_cannot_see_changes_the_answer(jule: Account, operator: Account) -> None:
    vault = own_vault(jule)
    for number in range(6):
        made = add_document(vault, jule, f"Stromrechnung {number}", sender="Stadtwerke Lindenau", amount=5000 + number,
                            date=date(2026, 3, 1 + number))
        give_text(made, f"Abschlag Strom Lindenau Nummer {number}. Bitte überweisen.")
    queries = ["strom", "werke lindenau", '"bitte überweisen"', "absender:stadtwerke betrag:>50", "", "abschlag"]
    with new_client(jule) as client:
        before = {query: _answer(client, query) for query in queries}
        quiet = [_timed(client, "strom") for _ in range(9)]
    # Somebody else's vault fills with documents that match every one of these searches, better than hers do.
    tom = make_account("tom")
    for number in range(300):
        other = add_document(own_vault(tom), tom, f"Stromrechnung {number} Strom Strom", sender="Stadtwerke Lindenau",
                             amount=9000, date=date(2026, 12, 1))
        give_text(other, "Abschlag Strom Lindenau, bitte überweisen. Strom strom strom.")
    with new_client(jule) as client:
        after = {query: _answer(client, query) for query in queries}
        busy = [_timed(client, "strom") for _ in range(9)]
    assert after == before
    # Nor the time it takes: what the index reads for 300 more matches does not show beside the rest of the answer.
    assert statistics.median(busy) - statistics.median(quiet) < max(0.025, statistics.median(quiet) * 0.5)


def _timed(client: TestClient, query: str) -> float:
    began = time.perf_counter()
    search(client, query)
    return time.perf_counter() - began


def test_a_search_that_takes_too_long_is_stopped(browser: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import search as search_service

    monkeypatch.setattr(search_service, "MAX_SECONDS", -1.0)
    monkeypatch.setattr(search_service, "PROGRESS_STEPS", 1)
    answer = browser.get("/api/v1/search", params={"q": "strom"})
    assert answer.status_code == 503 and answer.json()["detail"]["code"] == "search_too_slow"
    monkeypatch.undo()
    # The connection is not left with the handler: the next search works.
    assert found(browser, "strom") == {"Abschlag Strom Oktober"}
