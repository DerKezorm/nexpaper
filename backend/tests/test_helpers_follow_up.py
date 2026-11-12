"""The follow-up ("Wiedervorlage", K1): a fifth kind of date with a sentence of what to do. It is set like the other
terms, stands on the deadlines page with its sentence, counts in the menu, in ``frist:offen`` and the filter, is
reminded once on its own day at 8 (no lead, whatever "the day itself" says), with catching up; a reminder and the
weekly mail name kind, day and title, never the sentence. Somebody who switched deadlines off hears nothing of it, and
the dashboard card names it ``follow_up``."""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account
from app.services import reminders

from .conftest import make_account, new_client
from .test_reminders import DAY, TODAY, Town, at, choose, mails, run, town  # noqa: F401 - fixtures by name

SENTENCE = "nachfragen, ob die Kasse erstattet hat"


def follow_up(day: Any, note: str | None = SENTENCE) -> tuple[Any, ...]:
    return ("follow_up", day, {"note": note} if note is not None else {})


def patch(client: TestClient, document_id: int, **body: Any) -> Any:
    return client.patch(f"/api/v1/documents/{document_id}", json=body)


# --- Setting it -------------------------------------------------------------------------------------------------------


def test_set_changed_and_taken_away_like_the_other_terms(town: Town) -> None:  # noqa: F811
    doc = town.add("Arztrechnung", town.house, town.tom, dates=[("due", TODAY + 3 * DAY)])
    with new_client(town.tom) as tom:
        answer = patch(tom, doc, set_dates=[{"kind": "follow_up", "date": str(TODAY + 30 * DAY),
                                             "note": "  nachfragen,\n ob  erstattet  "}])
        assert answer.status_code == 200, answer.text
        dates = {d["kind"]: d for d in answer.json()["dates"]}
        assert dates["follow_up"]["note"] == "nachfragen, ob erstattet"
        assert "note" not in dates["due"], "only a follow-up has a sentence"
        # Only what is sent changes: another day keeps the sentence, an empty sentence takes it away.
        again = patch(tom, doc, set_dates=[{"kind": "follow_up", "date": str(TODAY + 31 * DAY)}]).json()
        assert {d["kind"]: d.get("note") for d in again["dates"]}["follow_up"] == "nachfragen, ob erstattet"
        cleared = patch(tom, doc, set_dates=[{"kind": "follow_up", "note": None}]).json()
        assert {d["kind"]: d.get("note") for d in cleared["dates"]}["follow_up"] == ""
        gone = patch(tom, doc, remove_dates=["follow_up"]).json()
        assert [d["kind"] for d in gone["dates"]] == ["due"]
        # All five at once.
        every = patch(tom, doc, set_dates=[{"kind": k, "date": str(TODAY + n * DAY)} for n, k in enumerate(
            ("due", "contract_end", "warranty_end", "keep_until", "follow_up"), start=1)])
        assert every.status_code == 200, every.text
        history = tom.get(f"/api/v1/documents/{doc}/events").json()
        assert all("nachfragen" not in str(event) for event in history), "the history names fields, never contents"


@pytest.mark.parametrize(("entry", "code"), [
    ({"kind": "follow_up", "date": "2026-11-01", "note": "x" * 201}, "invalid_terms"),
    ({"kind": "due", "date": "2026-11-01", "note": "Satz"}, "invalid_terms"),
    ({"kind": "follow_up", "date": "2026-11-01", "notice": {"n": 3, "unit": "months"}}, "invalid_terms"),
])
def test_what_does_not_fit_is_refused(town: Town, entry: dict[str, Any], code: str) -> None:  # noqa: F811
    doc = town.add("Brief", town.house, town.tom)
    with new_client(town.tom) as tom:
        answer = patch(tom, doc, set_dates=[entry])
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == code, answer.text


def test_a_reader_cannot_set_it(town: Town) -> None:  # noqa: F811
    doc = town.add("Brief", town.house, town.tom)
    with new_client(town.lea) as lea:
        assert patch(lea, doc, set_dates=[{"kind": "follow_up", "date": "2026-11-01"}]).status_code == 403


# --- The deadlines page, the menu, the search ----------------------------------------------------------------------


def test_it_stands_on_the_deadlines_page_with_its_sentence_and_counts(town: Town) -> None:  # noqa: F811
    doc = town.add("Physiotherapie", town.house, town.tom, dates=[follow_up(TODAY + 2 * DAY)])
    town.add("Strom", town.house, town.tom, dates=[("due", TODAY + 40 * DAY)])
    with new_client(town.tom) as tom:
        page = tom.get("/api/v1/deadlines").json()
        soon = page["soon"]["items"]
        assert [(d["document_id"], d["kind"], d["what"], d["note"]) for d in soon] == [
            (doc, "follow_up", "follow_up", SENTENCE)]
        assert page["later"]["items"][0]["note"] is None
        only = tom.get("/api/v1/deadlines", params={"what": "follow_up"}).json()
        assert [d["document_id"] for d in only["soon"]["items"]] == [doc] and only["later"]["total"] == 0
        assert tom.get("/api/v1/counts").json()["deadlines"] == 1
        found = {h["document"]["title"] for h in tom.get("/api/v1/search", params={"q": "frist:offen"}).json()["items"]}
        assert found == {"Physiotherapie", "Strom"}
        assert {h["document"]["title"] for h in tom.get("/api/v1/search", params={"deadline": "14"}).json()["items"]} \
            == {"Physiotherapie"}
        # Done and later as with the others.
        assert tom.put(f"/api/v1/documents/{doc}/dates/follow_up/snooze", json={"days": 3}).status_code == 200
        assert tom.post(f"/api/v1/documents/{doc}/dates/follow_up/done").status_code == 200
        assert tom.get("/api/v1/deadlines").json()["soon"]["total"] == 0
        assert {h["document"]["title"] for h in tom.get("/api/v1/search", params={"q": "frist:erledigt"}).json()[
            "items"]} == {"Physiotherapie"}
    with new_client(town.lea) as lea:
        assert lea.get("/api/v1/deadlines").json()["soon"]["total"] == 0, "a reader has no deadlines"


# --- Reminders --------------------------------------------------------------------------------------------------------


def test_reminded_once_on_its_day_at_eight_never_ahead_and_never_the_sentence(
        town: Town, mails: list[EmailMessage]) -> None:  # noqa: F811
    choose(town.jule, mail=True)
    doc = town.add("Physiotherapie", town.mine, town.jule, dates=[follow_up(TODAY + 3 * DAY)])
    for day in range(3):
        run(at(TODAY + day * DAY, 9))
    assert town.got() == [] and mails == [], "no lead"
    run(at(TODAY + 3 * DAY, 7, 59))
    assert town.got() == []
    run(at(TODAY + 3 * DAY, 8))
    messages = town.messages()
    assert [(m["title"], m["body"], m["url"]) for m in messages] == [
        ("Wiedervorlage So, 11.10.: Physiotherapie", "Heute.", f"/dokument/{doc}")]
    run(at(TODAY + 3 * DAY, 20))
    run(at(TODAY + 4 * DAY, 8))
    assert town.got() == [], "once"
    assert len(mails) == 1
    for text in [repr(m) for m in messages] + [m.as_string() for m in mails]:
        assert "nachfragen" not in text and "Kasse" not in text


def test_on_its_day_also_when_the_day_itself_is_switched_off(town: Town) -> None:  # noqa: F811
    choose(town.jule, same_day=False)
    town.add("Bescheid", town.mine, town.jule, dates=[follow_up(TODAY + DAY), ("due", TODAY + DAY)])
    run(at(TODAY + DAY, 8))
    titles = sorted(title for _person, title in town.got())
    assert titles == ["Wiedervorlage Fr, 09.10.: Bescheid"], "the bill's day is off, the follow-up's is not"


def test_missed_it_comes_up_to_two_days_late_and_not_later(town: Town) -> None:  # noqa: F811
    town.add("Spät", town.mine, town.jule, dates=[follow_up(TODAY - 2 * DAY)])
    town.add("Zu spät", town.mine, town.jule, dates=[follow_up(TODAY - 3 * DAY)])
    run(at(TODAY, 8))
    assert [title for _person, title in town.got()] == ["Wiedervorlage Di, 06.10.: Spät"]


def test_in_english(town: Town) -> None:  # noqa: F811
    from .test_reminders import set_profile

    set_profile(town.jule, language="en", mail="jule@example.com")
    town.add("Refund", town.mine, town.jule, dates=[follow_up(TODAY)])
    run(at(TODAY, 8))
    assert [title for _person, title in town.got()] == ["Follow up Thu, Oct 8: Refund"]


def test_the_weekly_mail_names_it_without_the_sentence(town: Town, mails: list[EmailMessage]) -> None:  # noqa: F811
    from datetime import date

    choose(town.jule, rhythm="weekly")
    monday = date(2026, 10, 12)
    town.add("Kasse", town.mine, town.jule, dates=[follow_up(monday + 2 * DAY)])
    run(at(monday, 9))
    assert len(mails) == 1
    plain = mails[0].get_body(("plain",)).get_content()  # type: ignore[union-attr]
    assert "Mi, 14.10. · Wiedervorlage: Kasse" in plain and "nachfragen" not in mails[0].as_string()


def test_switched_off_deadlines_hear_nothing_of_it(town: Town) -> None:  # noqa: F811
    with SessionLocal() as db:
        row = db.get(Account, town.jule.id)
        assert row is not None
        row.profile = {**(row.profile or {}), "deadlines": False}
        db.commit()
    town.add("Still", town.mine, town.jule, dates=[follow_up(TODAY)])
    run(at(TODAY, 8))
    assert town.got() == []


def test_a_reader_is_not_reminded(town: Town) -> None:  # noqa: F811
    town.add("Haus", town.house, town.jule, dates=[follow_up(TODAY)])
    run(at(TODAY, 8))
    assert sorted(person for person, _title in town.got()) == ["jule", "tom"]


def test_the_words() -> None:
    assert reminders.WORDS["de"]["follow_up"] == "Wiedervorlage {day}"
    assert reminders.WORDS["en"]["short_follow_up"] == "Follow up"


# --- The dashboard card ------------------------------------------------------------------------------------------


def test_the_dashboard_names_it_follow_up_without_the_sentence(client: TestClient, operator: Account) -> None:
    from .papers import add_document, own_vault

    assert client.put("/api/v1/settings", json={"api_keys_allowed": True}).status_code == 200
    rita = make_account("rita")
    doc = add_document(own_vault(rita), rita, "Rückfrage", content=None, status="filed",
                       dates=[follow_up(reminders.deadlines.server_today() + DAY)])
    with new_client(rita) as browser:
        token = browser.post("/api/v1/api-keys", json={"name": "deck", "scope": "read"}).json()["secret"]
    card = client.get("/api/v1/dashboard", headers={"Authorization": f"Bearer {token}"}).json()
    assert [(d["id"], d["kind"]) for d in card["deadlines"]] == [(doc, "follow_up")]
    assert "nachfragen" not in str(card)
