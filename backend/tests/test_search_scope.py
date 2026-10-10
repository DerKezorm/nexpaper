"""The search reads only the entries in the caller's scope (their vaults, what is shared with them), the scope follows
shares and moves, the search is braked per person, the excerpts have a time budget, and documents read before there was
text get their text by a job."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import Account, Event, Job, VersionText
from app.services import brakes, jobs, processing, search, search_index

from .conftest import make_account, new_client
from .files import make_pdf
from .intake import process_all, upload_one
from .papers import add_document, own_vault, shared_vault
from .searching import found, give_text
from .searching import search as run_search


def entries(scope: list[str], word: str) -> set[int]:
    """What the word index gives for ``word`` among the entries of ``scope`` (the lookup the search makes)."""
    expression = search.scoped(scope, f'"{word}"')
    with SessionLocal() as db:
        return set(db.scalars(text("SELECT rowid FROM doc_fts WHERE doc_fts MATCH :q"), {"q": expression}))


def scope(uid: int) -> list[str]:
    with SessionLocal() as db:
        return search.scope_of(db, uid)


def test_the_index_gives_only_entries_in_the_scope_and_the_scope_follows_shares_and_moves(operator: Account) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    household = shared_vault("Haushalt", operator, (jule, "edit"), (tom, "edit"))
    hers = add_document(own_vault(jule), jule, "Kowalczyk Brief")
    his = add_document(own_vault(tom), tom, "Kowalczyk Antwort")
    # Each sees only their own entry, already in the index lookup (not only in the SQL after it).
    assert entries(scope(jule.id), "kowalczyk") == {hers}
    assert entries(scope(tom.id), "kowalczyk") == {his}
    # A share: the entry gets the token of the person.
    with new_client(tom) as browser:
        assert browser.put(f"/api/v1/documents/{his}/shares/{jule.id}", json={"right": "read"}).status_code == 200
    assert entries(scope(jule.id), "kowalczyk") == {hers, his}
    with new_client(jule) as browser:
        assert found(browser, "kowalczyk") == {"Kowalczyk Brief", "Kowalczyk Antwort"}
    with new_client(tom) as browser:
        assert browser.delete(f"/api/v1/documents/{his}/shares/{jule.id}").status_code == 204
        # Moved into the shared vault: the entry takes the vault's token.
        assert browser.post(f"/api/v1/documents/{his}/move", json={"vault_id": household}).status_code == 200
    assert entries([search_index.vault_token(household)], "kowalczyk") == {his}
    assert entries(scope(jule.id), "kowalczyk") == {hers, his}
    # A member who leaves loses the vault's entries at once: nothing in the index changes, the scope does.
    with new_client(operator) as browser:
        assert browser.delete(f"/api/v1/vaults/{household}/members/{jule.id}").status_code in (200, 204)
    assert entries(scope(jule.id), "kowalczyk") == {hers}
    # A word typed like a scope token finds no scope: the words are looked for in the content only.
    with new_client(tom) as browser:
        assert found(browser, search_index.vault_token(household)) == set()


def test_the_search_is_braked_per_person_from_every_way_in(client: TestClient, operator: Account,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    assert brakes.LIMITS["search"] == 120
    monkeypatch.setitem(brakes.LIMITS, "search", 5)
    jule = make_account("jule")
    with new_client(jule) as browser:
        token = browser.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
        for _ in range(3):
            assert browser.get("/api/v1/search", params={"q": "a"}).status_code == 200
        with TestClient(browser.app, base_url="http://testserver") as device:
            bearer = {"Authorization": f"Bearer {token}"}
            for _ in range(2):
                assert device.get("/api/v1/search", params={"q": "a"}, headers=bearer).status_code == 200
            # The sixth in the minute, by device or browser: 429 with the seconds to wait.
            answer = device.get("/api/v1/search", params={"q": "a"}, headers=bearer)
            assert answer.status_code == 429 and answer.json()["detail"]["code"] == "search_too_often"
            assert 1 <= int(answer.headers["Retry-After"]) <= 61
        assert browser.get("/api/v1/search", params={"q": "a"}).status_code == 429
    # Somebody else searches on.
    assert client.get("/api/v1/search", params={"q": "a"}).status_code == 200


def test_the_excerpts_of_an_answer_have_a_time_budget(operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    jule = make_account("jule")
    for number in range(3):
        made = add_document(own_vault(jule), jule, f"Brief {number}")
        give_text(made, f"Am Anfang steht etwas. Weiter hinten steht Wandertag {number}.")
    monkeypatch.setattr(search, "EXCERPT_SECONDS", -1.0)
    with new_client(jule) as browser:
        hits = run_search(browser, "wandertag")["items"]
    # Found as before; the excerpt is the start of the text, unmarked.
    assert len(hits) == 3
    assert all(hit["excerpt"]["text"].startswith("Am Anfang") and hit["excerpt"]["marks"] == [] for hit in hits)


def test_a_document_read_before_there_was_text_gets_it_by_a_job(client: TestClient, operator: Account) -> None:
    made = upload_one(client, "Alt.pdf", make_pdf(["Ein alter Brief mit dem Wort Zaehlerablesung darin"]))
    process_all()
    assert client.patch(f"/api/v1/documents/{made['id']}", json={"status": "filed"}).status_code == 200
    # As a database from before the text: the document has no text.
    with SessionLocal() as db:
        db.execute(VersionText.__table__.delete())
        db.commit()
        assert processing.queue_text_reading(db) == 1
        assert db.scalars(select(Job.kind).where(Job.state == "queued")).all() == [jobs.TEXT]
    jobs.run_pending()
    document = client.get(f"/api/v1/documents/{made['id']}").json()
    assert document["status"] == "filed"  # the job reads the text, nothing else changes
    assert "Zaehlerablesung" in client.get(f"/api/v1/documents/{made['id']}/versions/1/text").json()["pages"][0]
    assert found(client, "zaehlerablesung") == {"Alt"}
    with SessionLocal() as db:
        assert db.scalars(select(Event.action).where(Event.document_id == made["id"]).order_by(Event.id.desc())
                          ).first() == processing.TEXT_READ
        # Read once: nothing more to do.
        assert processing.queue_text_reading(db) == 0


def test_an_answer_leaves_at_the_next_step_of_time(operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    """What is left of the time a search takes (whether a word exists on the server at all) disappears in the step."""
    import time

    from app.routers import search as route

    monkeypatch.setattr(route, "TIME_STEP", 0.2)
    jule = make_account("jule")
    with new_client(jule) as browser:
        for query in ("kowalczyk", "nichts"):
            began = time.perf_counter()
            assert browser.get("/api/v1/search", params={"q": query}).status_code == 200
            assert time.perf_counter() - began >= 0.2
        # A refused one waits the same (an error tells nothing either).
        began = time.perf_counter()
        assert browser.get("/api/v1/search", params={"q": "betrag:>viel"}).status_code == 422
        assert time.perf_counter() - began >= 0.2


def test_the_limits_of_a_search_stand_where_the_documentation_says() -> None:
    from app.routers import search as route
    from app.services import searchtext

    assert search.MAX_SECONDS == 10.0 and search.EXCERPT_SECONDS == 1.0 and route.TIME_STEP == 0.025
    # The excerpt looks no further than 200,000 characters into a text.
    assert searchtext.SNIPPET_SCAN == 200_000
    patterns = searchtext.parse("wandertag").patterns()
    near = "Wort " * 1000 + "Wandertag"
    far = "Wort " * 50_000 + "Wandertag"
    assert searchtext.snippet(near, patterns)[1] != []
    excerpt, marks = searchtext.snippet(far, patterns)
    assert marks == [] and excerpt.startswith("Wort Wort")


def test_the_ceiling_of_the_operator_reaches_the_worker(client: TestClient, operator: Account,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[str, int]] = []
    real = processing.spawn

    def spying(request: dict, timeout: int) -> processing.Outcome:
        asked.append((request["op"], timeout))
        return real(request, timeout)

    monkeypatch.setattr(processing, "spawn", spying)
    assert client.put("/api/v1/settings/ocr", json={"max_seconds": 60}).status_code == 200
    long_text = ["Seite mit genug Text, um nicht erkannt werden zu muessen"] * 12
    upload_one(client, "Zwoelf.pdf", make_pdf(long_text))
    process_all()
    # Twelve pages at 30 seconds would be 360; the ceiling is 60.
    assert ("recognize", 60) in asked


def test_the_wait_is_the_rest_of_the_step_and_a_random_bit_more_also_for_an_error(
        operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.routers import search as route

    moments = iter([100.0, 100.010, 200.0, 200.031, 300.0, 300.002])
    waits: list[float] = []
    chances = iter([0.007, 0.0, 0.025])
    monkeypatch.setattr(route, "clock", lambda: next(moments))
    monkeypatch.setattr(route, "sleep", waits.append)
    monkeypatch.setattr(route, "jitter", lambda: next(chances))
    jule = make_account("jule")
    with new_client(jule) as browser:
        assert browser.get("/api/v1/search", params={"q": "brief"}).status_code == 200
        assert browser.get("/api/v1/search", params={"q": "brief"}).status_code == 200
        assert browser.get("/api/v1/search", params={"q": "betrag:>viel"}).status_code == 422
    # 10 ms taken: 15 ms to the step, then 7 ms of chance; 31 ms: 19 ms to the next step; an error waits as well.
    assert [round(w, 6) for w in waits] == [0.022, 0.019, 0.048]


def test_the_chance_comes_from_secrets_within_the_bound() -> None:
    from app.routers import search as route

    drawn = [route._jitter() for _ in range(300)]
    assert all(0 <= value <= route.JITTER for value in drawn)
    assert len(set(drawn)) > 200  # not a constant
    assert route.jitter is route._jitter and route.JITTER == 0.025
