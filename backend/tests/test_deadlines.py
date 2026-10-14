"""Deadlines (F1): the last day to cancel, the sections of the page, done and later, the renewal by itself, the rights,
the search words, the dashboard, the export, the step from schema 10 and the backup.

The clock stands still in every test (``freeze``); the people here live in UTC, so "today" is the 8th of October 2026,
the mock's today.
"""

from __future__ import annotations

import csv
import io
import sqlite3
import threading
import zipfile
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from app import db as database
from app.db import SessionLocal
from app.models import Account, DeadlineSnooze, Document, DocumentDate, Event
from app.services import apikeys, backups, deadlines, documents, exports, settings_service

from .conftest import make_account, new_client
from .papers import Date, add_document, freeze, own_vault, shared_vault

NOON = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
TODAY = Date(2026, 10, 8)
DAY = timedelta(days=1)
RECORDS = Path(__file__).parent / "schema"


# --- The calendar -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("end", "n", "unit", "last"), [
    (Date(2026, 12, 31), 3, "months", Date(2026, 9, 30)),
    (Date(2027, 5, 31), 3, "months", Date(2027, 2, 28)),
    (Date(2028, 5, 31), 3, "months", Date(2028, 2, 29)),
    (Date(2026, 6, 30), 3, "months", Date(2026, 3, 31)),
    (Date(2027, 1, 31), 3, "months", Date(2026, 10, 31)),
    (Date(2026, 3, 15), 1, "months", Date(2026, 2, 15)),
    (Date(2026, 1, 15), 2, "months", Date(2025, 11, 15)),
    (Date(2026, 11, 15), 4, "weeks", Date(2026, 10, 18)),
    (Date(2026, 1, 5), 1, "weeks", Date(2025, 12, 29)),
    (Date(2026, 12, 31), 24, "months", Date(2024, 12, 31)),
])
def test_the_last_day_to_cancel_is_counted_on_the_calendar(end: Date, n: int, unit: str, last: Date) -> None:
    assert deadlines.last_to_cancel(end, n, unit) == last


def test_months_ahead_keep_the_last_day_of_a_month() -> None:
    assert deadlines.add_months(Date(2026, 2, 28), 1) == Date(2026, 3, 31)
    assert deadlines.add_months(Date(2026, 1, 30), 1) == Date(2026, 2, 28)
    assert deadlines.add_months(Date(2027, 2, 28), 12) == Date(2028, 2, 29)
    assert deadlines.add_months(Date(2026, 11, 15), 12) == Date(2027, 11, 15)


def test_what_a_deadline_asks_for() -> None:
    work = deadlines.work_out
    assert work("due", TODAY, notice_date=None, renew_months=None, done=False, today=TODAY).what == "pay"
    assert work("warranty_end", TODAY, notice_date=None, renew_months=None, done=False, today=TODAY).what == "warranty"
    cancel = work("contract_end", Date(2026, 12, 31), notice_date=Date(2026, 9, 30), renew_months=12, done=False,
                  today=Date(2026, 9, 30))
    assert (cancel.what, cancel.date, cancel.renews_to) == ("cancel", Date(2026, 9, 30), Date(2027, 12, 31))
    ends = work("contract_end", Date(2026, 12, 31), notice_date=Date(2026, 9, 30), renew_months=12, done=False,
                today=TODAY)
    assert (ends.what, ends.date, ends.missed) == ("ends", Date(2026, 12, 31), Date(2026, 9, 30))
    # Cancelled: the last day to cancel stays the day, however late it is now.
    done = work("contract_end", Date(2026, 12, 31), notice_date=Date(2026, 9, 30), renew_months=12, done=True,
                today=TODAY)
    assert (done.what, done.date) == ("cancel", Date(2026, 9, 30))
    plain = work("contract_end", Date(2026, 12, 31), notice_date=None, renew_months=None, done=False, today=TODAY)
    assert (plain.what, plain.renews_to) == ("ends", None)


# --- A household ------------------------------------------------------------------------------------------------------


def set_zone(account: Account, name: str = "UTC") -> None:
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None
        row.profile = {"timezone": name}
        db.commit()


def contract(document_id: int, uid: int, end: Date, n: int | None = 3, unit: str = "months",
             renew: int | None = 12) -> None:
    with SessionLocal() as db:
        documents.update_fields(db, uid, document_id, {"dates": [
            {"kind": "contract_end", "date": end, "notice": {"n": n, "unit": unit} if n else None,
             "renew_months": renew}]})


class House:
    """jule and tom share "Haushalt" (jule manages, tom edits, lea reads); bob has his own vault."""

    def __init__(self, operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch
        freeze(monkeypatch, NOON)
        self.jule, self.tom, self.lea, self.bob = (make_account(n) for n in ("jule", "tom", "lea", "bob"))
        for person in (self.jule, self.tom, self.lea, self.bob):
            set_zone(person)
        self.house = shared_vault("Haushalt", operator, (self.jule, "manage"), (self.tom, "edit"), (self.lea, "read"))
        self.mine = own_vault(self.jule)
        self.bobs = own_vault(self.bob)
        self.ids: dict[str, int] = {}

    def add(self, name: str, vault: int, owner: Account, **fields: Any) -> int:
        fields.setdefault("content", None)
        fields.setdefault("status", "filed")
        self.ids[name] = add_document(vault, owner, name, **fields)
        return self.ids[name]

    def stock(self) -> dict[str, int]:
        """The mock's deadlines: overdue, soon, later, a contract whose last day passed, one done, one in the inbox."""
        self.add("Kurtaxe", self.house, self.tom, dates=[("due", Date(2026, 10, 5))], amount=21200)
        self.add("Prophylaxe", self.house, self.jule, dates=[("due", TODAY)], amount=9640)
        self.add("Kaffeevollautomat", self.house, self.tom, dates=[("warranty_end", Date(2026, 10, 19))])
        fitness = self.add("Fitnessstudio", self.mine, self.jule)
        contract(fitness, self.jule.id, Date(2026, 11, 15), 4, "weeks")
        mobile = self.add("Mobilfunk", self.mine, self.jule)
        contract(mobile, self.jule.id, Date(2026, 12, 31))
        heating = self.add("Wartung Heizung", self.house, self.jule)
        contract(heating, self.jule.id, Date(2027, 1, 31))
        water = self.add("Abschlag Wasser", self.house, self.tom, dates=[("due", Date(2026, 10, 1))])
        with SessionLocal() as db:
            deadlines.set_done(db, self.tom.id, water, "due", True)
        self.add("Neue Rechnung", self.house, self.tom, status="inbox", dates=[("due", Date(2026, 10, 12))])
        self.add("Wird gelesen", self.house, self.tom, status="processing", dates=[("due", Date(2026, 10, 9))])
        self.add("Aufbewahren", self.house, self.tom, dates=[("keep_until", Date(2026, 10, 9))])
        thrown = self.add("Weggeworfen", self.house, self.tom, dates=[("due", Date(2026, 10, 9))])
        with SessionLocal() as db:
            documents.trash(db, self.tom.id, thrown)
        self.add("Bobs Frist", self.bobs, self.bob, dates=[("due", Date(2026, 10, 9))])
        return self.ids


@pytest.fixture
def house(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> House:
    return House(operator, monkeypatch)


def listing(who: TestClient, **params: Any) -> dict[str, Any]:
    answer = who.get("/api/v1/deadlines", params=params)
    assert answer.status_code == 200, answer.text
    return dict(answer.json())


def titles(section: dict[str, Any]) -> list[str]:
    return [item["title"] for item in section["items"]]


def test_the_sections_of_the_page_as_in_the_mock(house: House) -> None:
    house.stock()
    with new_client(house.jule) as jule:
        found = listing(jule)
    assert found["today"] == "2026-10-08" and found["soon_days"] == 14
    assert titles(found["overdue"]) == ["Kurtaxe"]
    assert titles(found["soon"]) == ["Prophylaxe", "Neue Rechnung", "Fitnessstudio", "Kaffeevollautomat"]
    assert titles(found["later"]) == ["Wartung Heizung", "Mobilfunk"]
    assert found["done"] is None
    first = found["soon"]["items"]
    assert [(i["what"], i["date"], i["days"]) for i in first] == [
        ("pay", "2026-10-08", 0), ("pay", "2026-10-12", 4), ("cancel", "2026-10-18", 10),
        ("warranty", "2026-10-19", 11)]
    # The inbox counts too, and says so.
    assert first[1]["status"] == "inbox"
    fitness = first[2]
    assert fitness["notice"] == {"n": 4, "unit": "weeks"} and fitness["end"] == "2026-11-15"
    assert fitness["renews_to"] == "2027-11-15"
    # The mobile contract: its last day to cancel (30.09.) passed, the end is the deadline now, with where it renews.
    mobile = found["later"]["items"][1]
    assert (mobile["what"], mobile["date"], mobile["missed"], mobile["renews_to"]) == (
        "ends", "2026-12-31", "2026-09-30", "2027-12-31")
    assert mobile["days"] == 84
    heating = found["later"]["items"][0]
    assert (heating["what"], heating["date"], heating["end"]) == ("cancel", "2026-10-31", "2027-01-31")
    assert found["overdue"]["items"][0]["amount"] == 21200
    assert found["counts"] == {str(house.house): 5, str(house.mine): 2} and found["shared"] == 0


def test_done_is_left_out_unless_asked_for_and_says_who_and_when(house: House) -> None:
    house.stock()
    with new_client(house.jule) as jule:
        found = listing(jule, done=True)
    assert titles(found["done"]) == ["Abschlag Wasser"]
    done = found["done"]["items"][0]["done"]
    assert done["by"]["name"] == "tom" and done["at"].startswith("2026-10-08T12:00")
    assert "Abschlag Wasser" not in titles(found["overdue"])


def test_a_cancelled_contract_keeps_its_last_day_to_cancel_as_its_day(house: House) -> None:
    """Cancelled in time: the day it stands on (and is sorted by) stays the last day to cancel, not the end."""
    cancelled = house.add("Gekündigter Vertrag", house.mine, house.jule)
    contract(cancelled, house.jule.id, Date(2026, 12, 31))
    paid = house.add("Bezahlte Rechnung", house.mine, house.jule, dates=[("due", Date(2026, 10, 5))])
    with SessionLocal() as db:
        deadlines.set_done(db, house.jule.id, cancelled, "contract_end", True)
        deadlines.set_done(db, house.jule.id, paid, "due", True)
    with new_client(house.jule) as jule:
        done = listing(jule, done=True)["done"]["items"]
    assert [(d["title"], d["what"], d["date"]) for d in done] == [
        ("Gekündigter Vertrag", "cancel", "2026-09-30"), ("Bezahlte Rechnung", "pay", "2026-10-05")]


def test_filters_by_what_and_by_vault(house: House) -> None:
    house.stock()
    with new_client(house.jule) as jule:
        assert titles(listing(jule, what="pay")["soon"]) == ["Prophylaxe", "Neue Rechnung"]
        cancel = listing(jule, what="cancel")
        assert titles(cancel["soon"]) == ["Fitnessstudio"]
        assert titles(cancel["later"]) == ["Wartung Heizung", "Mobilfunk"]
        assert titles(listing(jule, what="warranty")["soon"]) == ["Kaffeevollautomat"]
        mine = listing(jule, vault_id=house.mine)
        assert titles(mine["later"]) == ["Mobilfunk"] and titles(mine["soon"]) == ["Fitnessstudio"]
        # A vault the caller is not in answers like an empty one.
        bobs = listing(jule, vault_id=house.bobs)
        assert bobs["overdue"]["total"] == bobs["soon"]["total"] == bobs["later"]["total"] == 0


def test_a_limit_cuts_each_section_and_the_total_stays(house: House) -> None:
    for day in range(5):
        house.add(f"Rechnung {day}", house.mine, house.jule, dates=[("due", TODAY + day * DAY)])
    with new_client(house.jule) as jule:
        found = listing(jule, limit=2)
    assert found["soon"]["total"] == 5 and titles(found["soon"]) == ["Rechnung 0", "Rechnung 1"]


# --- Who sees which ---------------------------------------------------------------------------------------------------


def test_a_reader_gets_no_deadlines_and_a_stranger_none_of_another_vault(house: House) -> None:
    house.stock()
    with new_client(house.lea) as lea:
        found = listing(lea, done=True)
        assert all(found[s]["total"] == 0 for s in ("overdue", "soon", "later", "done"))
        assert found["counts"] == {} and found["shared"] == 0
        counts = lea.get("/api/v1/counts").json()
        assert counts["deadlines"] == 0 and counts["deadlines_overdue"] == 0
    with new_client(house.bob) as bob:
        found = listing(bob)
        assert titles(found["soon"]) == ["Bobs Frist"] and found["overdue"]["total"] == 0
        assert bob.get("/api/v1/counts").json()["deadlines"] == 1


def test_a_share_with_edit_brings_its_deadline_and_one_to_read_does_not(house: House) -> None:
    lent = house.add("Geteilt bearbeiten", house.bobs, house.bob, dates=[("due", TODAY + DAY)])
    read = house.add("Geteilt lesen", house.bobs, house.bob, dates=[("due", TODAY + DAY)])
    with new_client(house.bob) as bob:
        assert bob.put(f"/api/v1/documents/{lent}/shares/{house.lea.id}", json={"right": "edit"}).status_code == 200
        assert bob.put(f"/api/v1/documents/{read}/shares/{house.lea.id}", json={"right": "read"}).status_code == 200
    with new_client(house.lea) as lea:
        found = listing(lea)
        assert titles(found["soon"]) == ["Geteilt bearbeiten"]
        assert found["soon"]["items"][0]["via_share"] is True
        assert found["counts"] == {} and found["shared"] == 1
        assert titles(listing(lea, shared=True)["soon"]) == ["Geteilt bearbeiten"]
        assert lea.post(f"/api/v1/documents/{read}/dates/due/done").status_code == 403
        assert lea.post(f"/api/v1/documents/{lent}/dates/due/done").status_code == 200


def test_the_number_of_the_menu_is_overdue_and_the_next_fourteen_days(house: House) -> None:
    house.stock()
    with new_client(house.jule) as jule:
        counts = jule.get("/api/v1/counts").json()
    # Kurtaxe (overdue), Prophylaxe, Neue Rechnung, Fitnessstudio, Kaffeevollautomat; not the heating and the mobile
    # contract (later), not what is done, being read, in the trash, kept, or bob's.
    assert counts["deadlines"] == 5 and counts["deadlines_overdue"] == 1
    with new_client(house.tom) as tom:
        assert tom.get("/api/v1/counts").json()["deadlines"] == 4


def test_today_is_the_day_of_the_person(house: House) -> None:
    house.add("Heute dort", house.mine, house.jule, dates=[("due", Date(2026, 10, 9))])
    set_zone(house.jule, "Pacific/Kiritimati")  # UTC+14: already the 9th there at noon UTC
    with new_client(house.jule) as jule:
        item = listing(jule)["soon"]["items"][0]
    assert item["days"] == 0


# --- Changing the terms -----------------------------------------------------------------------------------------------


def test_the_terms_of_a_contract_are_set_kept_and_taken_away_through_the_document(house: House) -> None:
    doc = house.add("Vertrag", house.mine, house.jule)
    with new_client(house.jule) as jule:
        before = jule.get(f"/api/v1/documents/{doc}").json()["change_seq"]
        answer = jule.patch(f"/api/v1/documents/{doc}", json={"dates": [
            {"kind": "contract_end", "date": "2026-12-31", "notice": {"n": 3, "unit": "months"}, "renew_months": 12}]})
        assert answer.status_code == 200, answer.text
        term = answer.json()["dates"][0]
        assert term["notice"] == {"n": 3, "unit": "months"} and term["renew_months"] == 12
        assert term["last_to_cancel"] == "2026-09-30" and answer.json()["change_seq"] > before
        # The date alone moves: the period stays and the last day follows.
        term = jule.patch(f"/api/v1/documents/{doc}", json={"dates": [{"kind": "contract_end", "date": "2027-05-31"}]}
                          ).json()["dates"][0]
        assert term["notice"] == {"n": 3, "unit": "months"} and term["last_to_cancel"] == "2027-02-28"
        # The period alone changes: that is a change too, and the history names the field, not the values.
        seq = jule.get(f"/api/v1/documents/{doc}").json()["change_seq"]
        changed = jule.patch(f"/api/v1/documents/{doc}", json={"dates": [
            {"kind": "contract_end", "date": "2027-05-31", "notice": {"n": 6, "unit": "weeks"}}]}).json()
        assert changed["change_seq"] > seq and changed["dates"][0]["last_to_cancel"] == "2027-04-19"
        events = jule.get(f"/api/v1/documents/{doc}/events").json()
        assert {"action": "changed", "detail": {"fields": ["dates"]}} in [
            {"action": e["action"], "detail": e["detail"]} for e in events]
        # null takes them away.
        term = jule.patch(f"/api/v1/documents/{doc}", json={"dates": [
            {"kind": "contract_end", "date": "2027-05-31", "notice": None, "renew_months": None}]}).json()["dates"][0]
        assert term["notice"] is None and term["renew_months"] is None and term["last_to_cancel"] is None


@pytest.mark.parametrize("entry", [
    {"kind": "due", "date": "2026-12-31", "notice": {"n": 3, "unit": "months"}},
    {"kind": "warranty_end", "date": "2026-12-31", "renew_months": 12},
])
def test_only_a_contract_has_a_notice_period_and_a_renewal(house: House, entry: dict[str, Any]) -> None:
    doc = house.add("Rechnung", house.mine, house.jule)
    with new_client(house.jule) as jule:
        answer = jule.patch(f"/api/v1/documents/{doc}", json={"dates": [entry]})
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "invalid_terms"
    assert answer.json()["detail"]["field"] == "dates[0]"


@pytest.mark.parametrize("entry", [
    {"kind": "contract_end", "date": "2026-12-31", "notice": {"n": 0, "unit": "months"}},
    {"kind": "contract_end", "date": "2026-12-31", "notice": {"n": 25, "unit": "months"}},
    {"kind": "contract_end", "date": "2026-12-31", "notice": {"n": 3, "unit": "days"}},
    {"kind": "contract_end", "date": "2026-12-31", "renew_months": 0},
    {"kind": "contract_end", "date": "2026-12-31", "renew_months": 121},
])
def test_terms_out_of_bounds_are_refused(house: House, entry: dict[str, Any]) -> None:
    doc = house.add("Vertrag", house.mine, house.jule)
    with new_client(house.jule) as jule:
        assert jule.patch(f"/api/v1/documents/{doc}", json={"dates": [entry]}).status_code == 422


def test_terms_are_set_in_the_inbox_too(house: House) -> None:
    doc = house.add("Neuer Vertrag", house.house, house.tom, status="inbox")
    with new_client(house.tom) as tom:
        answer = tom.patch(f"/api/v1/documents/{doc}", json={"status": "filed", "dates": [
            {"kind": "contract_end", "date": "2027-03-31", "notice": {"n": 1, "unit": "months"}, "renew_months": 12}]})
    assert answer.status_code == 200 and answer.json()["dates"][0]["last_to_cancel"] == "2027-02-28"


# --- Done and later ---------------------------------------------------------------------------------------------------


def test_done_and_open_again_take_a_number_and_a_line_in_the_history(house: House) -> None:
    doc = house.add("Rechnung", house.house, house.tom, dates=[("due", TODAY + DAY)])
    with new_client(house.tom) as tom:
        seq = tom.get(f"/api/v1/documents/{doc}").json()["change_seq"]
        done = tom.post(f"/api/v1/documents/{doc}/dates/due/done")
        assert done.status_code == 200
        term = done.json()["dates"][0]
        assert term["done"]["by"]["name"] == "tom" and done.json()["change_seq"] > seq
        # Twice is once.
        again = tom.post(f"/api/v1/documents/{doc}/dates/due/done").json()
        assert again["change_seq"] == done.json()["change_seq"]
        assert tom.get("/api/v1/counts").json()["deadlines"] == 0
        opened = tom.delete(f"/api/v1/documents/{doc}/dates/due/done")
        assert opened.status_code == 200 and opened.json()["dates"][0]["done"] is None
        assert opened.json()["change_seq"] > done.json()["change_seq"]
        actions = [(e["action"], e["detail"], (e["by"] or {}).get("name")) for e in
                   tom.get(f"/api/v1/documents/{doc}/events").json()]
    assert ("deadline_done", {"kind": "due"}, "tom") in actions
    assert ("deadline_reopened", {"kind": "due"}, "tom") in actions
    with new_client(house.jule) as jule:
        # For everybody: jule sees it done too while it is.
        jule.post(f"/api/v1/documents/{doc}/dates/due/done")
        assert listing(jule)["soon"]["total"] == 0


def test_done_needs_the_date_the_right_and_a_document_out_of_the_trash(house: House) -> None:
    doc = house.add("Rechnung", house.house, house.tom, dates=[("due", TODAY + DAY), ("keep_until", TODAY)])
    with new_client(house.tom) as tom:
        assert tom.post(f"/api/v1/documents/{doc}/dates/warranty_end/done").json()["detail"]["code"] == "no_such_date"
        assert tom.post(f"/api/v1/documents/{doc}/dates/keep_until/done").status_code == 422
    with new_client(house.lea) as lea:
        assert lea.post(f"/api/v1/documents/{doc}/dates/due/done").status_code == 403
        assert lea.put(f"/api/v1/documents/{doc}/dates/due/snooze", json={"days": 1}).status_code == 403
    with new_client(house.bob) as bob:
        assert bob.post(f"/api/v1/documents/{doc}/dates/due/done").status_code == 404
        assert bob.put(f"/api/v1/documents/{doc}/dates/due/snooze", json={"days": 1}).status_code == 404
        assert bob.delete(f"/api/v1/documents/{doc}/dates/due/snooze").status_code == 404
    with SessionLocal() as db:
        documents.trash(db, house.tom.id, doc)
    with new_client(house.tom) as tom:
        assert tom.post(f"/api/v1/documents/{doc}/dates/due/done").json()["detail"]["code"] == "in_trash"
    with SessionLocal() as db:
        assert db.scalar(select(DocumentDate.done_at).where(DocumentDate.document_id == doc,
                                                           DocumentDate.kind == "due")) is None


def test_later_is_for_oneself_and_ends_when_asked(house: House) -> None:
    doc = house.add("Rechnung", house.house, house.tom, dates=[("due", TODAY + 2 * DAY)])
    with new_client(house.tom) as tom:
        seq = tom.get(f"/api/v1/documents/{doc}").json()["change_seq"]
        answer = tom.put(f"/api/v1/documents/{doc}/dates/due/snooze", json={"days": 3})
        assert answer.status_code == 200 and answer.json() == {"until": "2026-10-11"}
        item = listing(tom)["soon"]["items"][0]
        assert item["snoozed_until"] == "2026-10-11"
        shown = tom.get(f"/api/v1/documents/{doc}").json()
        assert shown["dates"][0]["snoozed_until"] == "2026-10-11"
        # Not a change of the document.
        assert shown["change_seq"] == seq
        # Again with 7 days: one row, the new day.
        assert tom.put(f"/api/v1/documents/{doc}/dates/due/snooze", json={"days": 7}).json() == {"until": "2026-10-15"}
        assert tom.put(f"/api/v1/documents/{doc}/dates/due/snooze", json={"days": 2}).status_code == 422
    with new_client(house.jule) as jule:
        assert listing(jule)["soon"]["items"][0]["snoozed_until"] is None
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DeadlineSnooze)) == 1
    with new_client(house.tom) as tom:
        assert tom.delete(f"/api/v1/documents/{doc}/dates/due/snooze").status_code == 204
        assert listing(tom)["soon"]["items"][0]["snoozed_until"] is None
        # A done deadline is not put off; marking it done ends every later on it.
        tom.put(f"/api/v1/documents/{doc}/dates/due/snooze", json={"days": 1})
        tom.post(f"/api/v1/documents/{doc}/dates/due/done")
        assert tom.put(f"/api/v1/documents/{doc}/dates/due/snooze", json={"days": 1}).json()["detail"]["code"] == (
            "deadline_done")
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DeadlineSnooze)) == 0


def test_a_later_that_ran_out_is_not_shown(house: House) -> None:
    doc = house.add("Rechnung", house.house, house.tom, dates=[("due", TODAY + 5 * DAY)])
    with new_client(house.tom) as tom:
        tom.put(f"/api/v1/documents/{doc}/dates/due/snooze", json={"days": 1})
        freeze(house.monkeypatch, NOON + 2 * DAY)
        assert listing(tom)["soon"]["items"][0]["snoozed_until"] is None


def test_a_later_ends_on_its_day_and_counts_the_day_of_the_person(house: House) -> None:
    """Later until tomorrow: tomorrow it is over (the person is reminded that day again), on the list and on the
    document, and the day is the person's own, not the server's."""
    doc = house.add("Rechnung", house.house, house.tom, dates=[("due", TODAY + 5 * DAY)])
    with new_client(house.tom) as tom:
        assert tom.put(f"/api/v1/documents/{doc}/dates/due/snooze", json={"days": 1}).json() == {"until": "2026-10-09"}
        assert tom.get(f"/api/v1/documents/{doc}").json()["dates"][0]["snoozed_until"] == "2026-10-09"
        freeze(house.monkeypatch, NOON + DAY)
        assert listing(tom)["soon"]["items"][0]["snoozed_until"] is None
        assert tom.get(f"/api/v1/documents/{doc}").json()["dates"][0]["snoozed_until"] is None
        # Back to the 8th at noon UTC; in a zone 14 hours ahead it is the 9th already, and the later is over there.
        freeze(house.monkeypatch, NOON)
        set_zone(house.tom, "Pacific/Kiritimati")
        assert listing(tom)["soon"]["items"][0]["snoozed_until"] is None
        assert tom.get(f"/api/v1/documents/{doc}").json()["dates"][0]["snoozed_until"] is None


def test_ending_later_ends_only_the_own(house: House) -> None:
    doc = house.add("Rechnung", house.house, house.tom, dates=[("due", TODAY + 5 * DAY)])
    with new_client(house.tom) as tom, new_client(house.jule) as jule:
        tom.put(f"/api/v1/documents/{doc}/dates/due/snooze", json={"days": 3})
        jule.put(f"/api/v1/documents/{doc}/dates/due/snooze", json={"days": 7})
        assert jule.delete(f"/api/v1/documents/{doc}/dates/due/snooze").status_code == 204
        assert listing(tom)["soon"]["items"][0]["snoozed_until"] == "2026-10-11"
        assert listing(jule)["soon"]["items"][0]["snoozed_until"] is None


# --- Device, key, upload key ------------------------------------------------------------------------------------------


@pytest.fixture
def keys(house: House) -> dict[str, str]:
    apikeys.forget()
    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": True})
    with new_client(house.tom) as tom:
        device = tom.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
        read = tom.post("/api/v1/api-keys", json={"name": "deck", "scope": "read"}).json()["secret"]
        upload = tom.post("/api/v1/api-keys", json={"name": "scan", "scope": "upload"}).json()["secret"]
    return {"device": device, "read": read, "upload": upload}


def test_a_device_does_what_the_browser_does_and_keys_only_read(house: House, keys: dict[str, str]) -> None:
    doc = house.add("Rechnung", house.house, house.tom, dates=[("due", TODAY + DAY)])
    with TestClient(new_client().app, base_url="http://testserver") as program:
        def as_(token: str) -> dict[str, str]:
            return {"Authorization": f"Bearer {token}"}

        assert program.get("/api/v1/deadlines", headers=as_(keys["device"])).json()["soon"]["total"] == 1
        # A key marks nothing done, whatever its scope.
        for scope in ("read", "upload"):
            answer = program.post(f"/api/v1/documents/{doc}/dates/due/done", headers=as_(keys[scope]))
            assert answer.status_code == 401, (scope, answer.status_code)
        with SessionLocal() as db:
            assert db.scalar(select(DocumentDate.done_at).where(DocumentDate.document_id == doc)) is None
        assert program.put(f"/api/v1/documents/{doc}/dates/due/snooze", json={"days": 1},
                           headers=as_(keys["device"])).status_code == 200
        assert program.post(f"/api/v1/documents/{doc}/dates/due/done", headers=as_(keys["device"])).status_code == 200
        read = program.get("/api/v1/deadlines", params={"done": True}, headers=as_(keys["read"]))
        assert read.status_code == 200 and read.json()["done"]["total"] == 1
        for method, path in (("DELETE", f"/api/v1/documents/{doc}/dates/due/done"),
                             ("PUT", f"/api/v1/documents/{doc}/dates/due/snooze"),
                             ("DELETE", f"/api/v1/documents/{doc}/dates/due/snooze")):
            for scope in ("read", "upload"):
                answer = program.request(method, path, headers=as_(keys[scope]),
                                         json={"days": 1} if method == "PUT" else None)
                assert answer.status_code == 401, (method, path, scope, answer.status_code)
        assert program.get("/api/v1/deadlines", headers=as_(keys["upload"])).status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(DocumentDate.done_at).where(DocumentDate.document_id == doc)) is not None


# --- Renewing by itself -----------------------------------------------------------------------------------------------


def end_of(document_id: int) -> Date:
    with SessionLocal() as db:
        return db.scalar(select(DocumentDate.date).where(DocumentDate.document_id == document_id,
                                                         DocumentDate.kind == "contract_end"))


def renewals(document_id: int) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        return [e.detail for e in db.scalars(select(Event).where(Event.document_id == document_id,
                                                                  Event.action == "renewed"))]


def test_a_contract_renews_once_its_end_has_passed_and_only_once(house: House) -> None:
    doc = house.add("Mobilfunk", house.mine, house.jule)
    contract(doc, house.jule.id, Date(2026, 10, 7))
    with SessionLocal() as db:
        seq = db.get(Document, doc).change_seq  # type: ignore[union-attr]
        snoozed = deadlines.snooze  # a later on it goes with the term it was for
        snoozed(db, house.jule.id, doc, "contract_end", 7, TODAY)
        assert deadlines.renew_due(db, Date(2026, 10, 7)) == 0, "on its last day it still runs"
        assert deadlines.renew_due(db, TODAY) == 1
        assert deadlines.renew_due(db, TODAY) == 0
        assert deadlines.renew_due(db, TODAY + DAY) == 0
        row = db.scalar(select(DocumentDate).where(DocumentDate.document_id == doc))
        assert row is not None and row.renewed_from == Date(2026, 10, 7)
        assert row.notice_date == Date(2027, 7, 7)
        assert db.get(Document, doc).change_seq > seq  # type: ignore[union-attr]
        assert db.scalar(select(func.count()).select_from(DeadlineSnooze)) == 0
    assert end_of(doc) == Date(2027, 10, 7)
    assert renewals(doc) == [{"kind": "contract_end", "from": "2026-10-07", "to": "2027-10-07"}]


def test_a_contract_long_over_moves_straight_to_its_next_end(house: House) -> None:
    doc = house.add("Alt", house.mine, house.jule)
    contract(doc, house.jule.id, Date(2019, 12, 31), renew=12)
    other = house.add("Quartal", house.mine, house.jule)
    contract(other, house.jule.id, Date(2026, 1, 31), renew=3)
    with SessionLocal() as db:
        assert deadlines.renew_due(db, TODAY) == 2
    assert end_of(doc) == Date(2026, 12, 31) and len(renewals(doc)) == 1
    # 31.01. plus 3, 6, 9 months: the last day of the month each time (31.10.).
    assert end_of(other) == Date(2026, 10, 31)


def test_cancelled_holds_the_renewal_and_without_a_renewal_nothing_moves(house: House) -> None:
    cancelled = house.add("Gekündigt", house.mine, house.jule)
    contract(cancelled, house.jule.id, Date(2026, 9, 30))
    plain = house.add("Endet", house.mine, house.jule)
    contract(plain, house.jule.id, Date(2026, 9, 30), renew=None)
    thrown = house.add("Papierkorb", house.mine, house.jule)
    contract(thrown, house.jule.id, Date(2026, 9, 30))
    with SessionLocal() as db:
        deadlines.set_done(db, house.jule.id, cancelled, "contract_end", True)
        documents.trash(db, house.jule.id, thrown)
        assert deadlines.renew_due(db, TODAY) == 0
    assert end_of(cancelled) == end_of(plain) == end_of(thrown) == Date(2026, 9, 30)


def test_a_page_that_is_behind_does_not_undo_a_renewal(house: House) -> None:
    """The page was opened before the contract renewed and sends its old end back with a changed notice period: the
    new end stays, the notice period changes, and the contract goes on renewing. Another day is taken as meant."""
    doc = house.add("Vertrag", house.mine, house.jule)
    contract(doc, house.jule.id, Date(2026, 10, 7))
    with SessionLocal() as db:
        assert deadlines.renew_due(db, TODAY) == 1
    assert end_of(doc) == Date(2027, 10, 7)
    with new_client(house.jule) as jule:
        answer = jule.patch(f"/api/v1/documents/{doc}", json={"dates": [
            {"kind": "contract_end", "date": "2026-10-07", "notice": {"n": 6, "unit": "weeks"}, "renew_months": 12}]})
        assert answer.status_code == 200, answer.text
        term = answer.json()["dates"][0]
        assert term["date"] == "2027-10-07" and term["notice"] == {"n": 6, "unit": "weeks"}
    with SessionLocal() as db:
        assert deadlines.renew_due(db, TODAY + 40 * DAY) == 0
    assert end_of(doc) == Date(2027, 10, 7) and len(renewals(doc)) == 1
    # The year after, it renews again.
    with SessionLocal() as db:
        assert deadlines.renew_due(db, Date(2027, 10, 8)) == 1
    assert end_of(doc) == Date(2028, 10, 7)
    # A person who means another end sets another day.
    contract(doc, house.jule.id, Date(2026, 10, 6))
    assert end_of(doc) == Date(2026, 10, 6)


def test_never_twice_from_the_same_end(house: House) -> None:
    doc = house.add("Vertrag", house.mine, house.jule)
    contract(doc, house.jule.id, Date(2026, 10, 1))
    with SessionLocal() as db:
        assert deadlines.renew_due(db, TODAY) == 1
        assert deadlines.renew_due(db, TODAY) == 0
        # The clock jumps back: the end is in the future for it, nothing to do.
        assert deadlines.renew_due(db, Date(2026, 9, 1)) == 0
    assert end_of(doc) == Date(2027, 10, 1) and len(renewals(doc)) == 1


def test_the_day_does_not_drift_to_the_end_of_the_month(house: House) -> None:
    """Counted from the end a person set: 30.01. plus one month is 28.02., then 30.03. and 30.04., not 31.03.; a
    quarter from 30.08. is 30.11., 28.02., then 30.05. (an end that is a month's last day, 30.11., stays a last day)."""
    monthly = house.add("Monatlich", house.mine, house.jule)
    contract(monthly, house.jule.id, Date(2026, 1, 30), renew=1)
    quarterly = house.add("Vierteljährlich", house.mine, house.jule)
    contract(quarterly, house.jule.id, Date(2025, 8, 30), renew=3)
    ends = []
    for day in (Date(2026, 2, 1), Date(2026, 3, 1), Date(2026, 3, 31)):
        with SessionLocal() as db:
            deadlines.renew_due(db, day)
        ends.append((end_of(monthly), end_of(quarterly)))
    assert ends[0] == (Date(2026, 2, 28), Date(2026, 2, 28))
    assert ends[1] == (Date(2026, 3, 30), Date(2026, 5, 30))
    assert ends[2] == (Date(2026, 4, 30), Date(2026, 5, 30))
    # The last day to cancel follows the end that was reached.
    with SessionLocal() as db:
        notice = db.scalar(select(DocumentDate.notice_date).where(DocumentDate.document_id == monthly))
    assert notice == Date(2026, 1, 31)


def test_the_count_starts_again_where_a_person_sets_the_end(house: House) -> None:
    doc = house.add("Vertrag", house.mine, house.jule)
    contract(doc, house.jule.id, Date(2026, 1, 30), renew=1)
    with SessionLocal() as db:
        deadlines.renew_due(db, Date(2026, 2, 1))
    assert end_of(doc) == Date(2026, 2, 28)
    contract(doc, house.jule.id, Date(2026, 4, 15), renew=1)
    with SessionLocal() as db:
        deadlines.renew_due(db, Date(2026, 4, 16))
        deadlines.renew_due(db, Date(2026, 5, 16))
    assert end_of(doc) == Date(2026, 6, 15)
    # A new term of renewal counts from the end it has then.
    with new_client(house.jule) as jule:
        jule.patch(f"/api/v1/documents/{doc}", json={"set_dates": [{"kind": "contract_end", "renew_months": 3}]})
    with SessionLocal() as db:
        deadlines.renew_due(db, Date(2026, 6, 16))
    assert end_of(doc) == Date(2026, 9, 15)


def test_an_end_exactly_today_is_where_it_stops(house: House) -> None:
    doc = house.add("Vertrag", house.mine, house.jule)
    contract(doc, house.jule.id, Date(2025, 10, 8))
    with SessionLocal() as db:
        assert deadlines.renew_due(db, TODAY) == 1
    assert end_of(doc) == TODAY
    assert deadlines.next_end(Date(2025, 10, 8), 12, TODAY) == TODAY
    assert deadlines.next_end(Date(2025, 10, 8), 12, TODAY, after=TODAY) == Date(2027, 10, 8)


def test_on_its_last_day_to_cancel_a_contract_is_due_that_day(house: House) -> None:
    """The SQL of the list, the menu and the search agrees with the reckoning on the day itself."""
    doc = house.add("Vertrag", house.mine, house.jule)
    contract(doc, house.jule.id, Date(2027, 1, 8))
    with new_client(house.jule) as jule:
        item = listing(jule)["soon"]["items"][0]
        assert (item["what"], item["date"], item["days"]) == ("cancel", "2026-10-08", 0)
        assert jule.get("/api/v1/counts").json()["deadlines"] == 1
        assert found(jule, "frist:<0") == ["Vertrag"]
    freeze(house.monkeypatch, NOON + DAY)
    with new_client(house.jule) as jule:
        item = listing(jule)["later"]["items"][0]
        assert (item["what"], item["date"], item["missed"]) == ("ends", "2027-01-08", "2026-10-08")
        assert jule.get("/api/v1/counts").json()["deadlines"] == 0


# --- Single terms (a page that may be behind) -------------------------------------------------------------------------


def test_single_terms_change_only_what_they_name(house: House) -> None:
    doc = house.add("Rechnung", house.mine, house.jule, dates=[("due", Date(2026, 10, 20)),
                                                              ("warranty_end", Date(2028, 10, 1))])
    with new_client(house.jule) as jule:
        seq = jule.get(f"/api/v1/documents/{doc}").json()["change_seq"]
        answer = jule.patch(f"/api/v1/documents/{doc}", json={"set_dates": [
            {"kind": "due", "date": "2026-10-25"},
            {"kind": "contract_end", "date": "2027-03-31", "notice": {"n": 1, "unit": "months"}, "renew_months": 12}]})
        assert answer.status_code == 200, answer.text
        shown = {d["kind"]: d for d in answer.json()["dates"]}
        assert shown["due"]["date"] == "2026-10-25" and shown["warranty_end"]["date"] == "2028-10-01"
        assert shown["contract_end"]["last_to_cancel"] == "2027-02-28" and answer.json()["change_seq"] > seq
        # Only the notice period: the day stays.
        term = jule.patch(f"/api/v1/documents/{doc}", json={"set_dates": [
            {"kind": "contract_end", "notice": {"n": 2, "unit": "weeks"}}]}).json()
        shown = {d["kind"]: d for d in term["dates"]}
        assert shown["contract_end"]["date"] == "2027-03-31" and shown["contract_end"]["notice"]["unit"] == "weeks"
        removed = jule.patch(f"/api/v1/documents/{doc}", json={"remove_dates": ["warranty_end"]}).json()
        assert sorted(d["kind"] for d in removed["dates"]) == ["contract_end", "due"]
        events = jule.get(f"/api/v1/documents/{doc}/events").json()
        assert [e["detail"] for e in events if e["action"] == "changed"].count({"fields": ["dates"]}) == 3
        # Nothing to change is no change.
        same = jule.patch(f"/api/v1/documents/{doc}", json={"set_dates": [{"kind": "due", "date": "2026-10-25"}]})
        assert same.json()["change_seq"] == removed["change_seq"]


@pytest.mark.parametrize(("body", "code", "field"), [
    ({"set_dates": [{"kind": "contract_end", "renew_months": 12}]}, "invalid_date", "set_dates[0]"),
    ({"set_dates": [{"kind": "due", "date": "1800-01-01"}]}, "invalid_date", "set_dates[0]"),
    ({"set_dates": [{"kind": "due", "date": "2026-10-20", "renew_months": 12}]}, "invalid_terms", "set_dates[0]"),
    ({"dates": [], "set_dates": [{"kind": "due", "date": "2026-10-20"}]}, "invalid_input", None),
    ({"dates": [], "remove_dates": ["due"]}, "invalid_input", None),
])
def test_single_terms_that_cannot_be_taken(house: House, body: dict[str, Any], code: str, field: str | None) -> None:
    doc = house.add("Rechnung", house.mine, house.jule, dates=[("due", Date(2026, 10, 20))])
    with new_client(house.jule) as jule:
        answer = jule.patch(f"/api/v1/documents/{doc}", json=body)
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == code, answer.text
    if field:
        assert answer.json()["detail"]["field"] == field
    with SessionLocal() as db:
        assert [r.date for r in db.scalars(select(DocumentDate).where(DocumentDate.document_id == doc))] == [
            Date(2026, 10, 20)]


def test_two_runs_at_once_renew_once(house: House) -> None:
    ids = []
    for n in range(6):
        doc = house.add(f"Vertrag {n}", house.mine, house.jule)
        contract(doc, house.jule.id, Date(2026, 9, 30) - n * DAY)
        ids.append(doc)
    barrier = threading.Barrier(2)
    counted: list[int] = []
    problems: list[BaseException] = []

    def run() -> None:
        try:
            barrier.wait(5)
            with SessionLocal() as db:
                counted.append(deadlines.renew_due(db, TODAY))
        except BaseException as exc:  # noqa: BLE001 - reported below
            problems.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert problems == []
    assert sorted(counted) == [0, 6] or sum(counted) == 6
    for doc in ids:
        assert len(renewals(doc)) == 1
    assert end_of(ids[0]) == Date(2027, 9, 30)


def test_the_loop_runs_the_renewal_on_the_server_day(house: House, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = house.add("Vertrag", house.mine, house.jule)
    contract(doc, house.jule.id, Date(2026, 10, 1))
    monkeypatch.setattr(deadlines, "server_today", lambda: TODAY)
    assert deadlines.run_once() == 1
    assert end_of(doc) == Date(2027, 10, 1)


# --- The search -------------------------------------------------------------------------------------------------------


def found(who: TestClient, q: str = "", **params: Any) -> list[str]:
    answer = who.get("/api/v1/search", params={"q": q, "limit": 100, **params})
    assert answer.status_code == 200, answer.text
    return sorted(hit["document"]["title"] for hit in answer.json()["items"])


def test_the_words_of_the_search_for_deadlines(house: House) -> None:
    house.stock()
    with new_client(house.jule) as jule:
        open_ = ["Fitnessstudio", "Kaffeevollautomat", "Kurtaxe", "Mobilfunk", "Neue Rechnung", "Prophylaxe",
                 "Wartung Heizung"]
        assert found(jule, "frist:offen") == open_ == found(jule, "deadline:open")
        assert found(jule, "frist:überfällig") == ["Kurtaxe"] == found(jule, "deadline:overdue")
        assert found(jule, "frist:ueberfaellig") == ["Kurtaxe"]
        assert found(jule, "frist:erledigt") == ["Abschlag Wasser"] == found(jule, "deadline:done")
        # Within 30 days, overdue included: the heating's last day to cancel is in 23 days, the mobile contract ends
        # in 84.
        assert found(jule, "frist:<30") == [title for title in open_ if title != "Mobilfunk"]
        assert found(jule, "frist:<5") == ["Kurtaxe", "Neue Rechnung", "Prophylaxe"]
        assert found(jule, "frist:<0") == ["Kurtaxe", "Prophylaxe"]
        # The filter of the archive is the same.
        assert found(jule, deadline="overdue") == ["Kurtaxe"]
        assert found(jule, deadline="5") == found(jule, "frist:<5")
        assert found(jule, "frist:offen kurtaxe") == ["Kurtaxe"]
        bad = jule.get("/api/v1/search", params={"q": "frist:morgen"})
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_deadline"
        assert jule.get("/api/v1/search", params={"deadline": "soon"}).status_code == 422
        understood = jule.get("/api/v1/search", params={"q": "frist:<30 frist:offen"}).json()["understood"]
        assert understood["deadlines"] == [30, "open"]
    with new_client(house.bob) as bob:
        assert found(bob, "frist:offen") == ["Bobs Frist"]


def test_the_search_finds_deadlines_of_what_a_reader_sees(house: House) -> None:
    """The search looks at the documents a person may see: a reader finds the deadline of a document by its words
    (the deadlines page and the menu leave it out: nobody reminds a reader)."""
    house.stock()
    with new_client(house.lea) as lea:
        assert found(lea, "frist:überfällig") == ["Kurtaxe"]


# --- The dashboard ----------------------------------------------------------------------------------------------------


def test_the_dashboard_names_the_last_day_to_cancel_and_leaves_out_what_is_done(house: House) -> None:
    house.stock()
    apikeys.forget()
    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": True})
    with new_client(house.jule) as jule:
        secret = jule.post("/api/v1/api-keys", json={"name": "deck", "scope": "read"}).json()["secret"]
        done = house.add("Bezahlt bald", house.mine, house.jule, dates=[("due", TODAY + DAY)])
        jule.post(f"/api/v1/documents/{done}/dates/due/done")
    with TestClient(new_client().app, base_url="http://testserver") as program:
        card = program.get("/api/v1/dashboard", headers={"Authorization": f"Bearer {secret}"}).json()
    assert [(d["title"], d["date"], d["kind"]) for d in card["deadlines"]] == [
        ("Prophylaxe", "2026-10-08", "due"),
        ("Wird gelesen", "2026-10-09", "due"),
        ("Neue Rechnung", "2026-10-12", "due"),
        ("Fitnessstudio", "2026-10-18", "notice"),
        ("Kaffeevollautomat", "2026-10-19", "warranty_end"),
    ]


# --- The export -------------------------------------------------------------------------------------------------------


def test_the_list_for_the_tax_adviser_has_the_deadlines(house: House) -> None:
    mobile = house.add("Mobilfunk", house.mine, house.jule, date=Date(2026, 1, 2))
    contract(mobile, house.jule.id, Date(2026, 12, 31))
    paid = house.add("Rechnung", house.mine, house.jule, date=Date(2026, 1, 3),
                     dates=[("due", Date(2026, 1, 20)), ("warranty_end", Date(2028, 1, 3))])
    with SessionLocal() as db:
        deadlines.set_done(db, house.jule.id, paid, "due", True)
    with SessionLocal() as db:
        cells = exports._terms(db, [mobile, paid], "de")
    assert cells[mobile] == ("", "2026-12-31", "2026-09-30", "", "")
    assert cells[paid] == ("2026-01-20", "", "", "2028-01-03", "bezahlt 2026-10-08")
    with SessionLocal() as db:
        assert exports._terms(db, [paid], "en")[paid][-1] == "paid 2026-10-08"
    # After the nine columns of the document come these five, then "Keep until" (F3).
    rows = list(csv.reader(io.StringIO(exports._csv([("x",) * 9 + cells[mobile] + ("2036-12-31",)], "de")
                                       .decode("utf-8-sig")), delimiter=";"))
    assert rows[0][9:] == ["Fällig am", "Vertrag bis", "Kündigen bis", "Garantie bis", "Erledigt", "Aufbewahren bis"]
    assert rows[1][10:13] == ["2026-12-31", "2026-09-30", ""] and rows[1][-1] == "2036-12-31"


# --- Schema 10 to 11, the backup --------------------------------------------------------------------------------------


@pytest.fixture
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "nexpaper.db"
    engine = create_engine(f"sqlite:///{path}")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(backups, "create", lambda **_kwargs: path)
    return path


def test_a_database_of_schema_10_with_dates_comes_up_with_open_deadlines(scratch: Path) -> None:
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v10.sql").read_text(encoding="utf-8"))
        connection.execute("INSERT INTO vaults (id, name, folder, icon, created_at) VALUES (1, 'Haushalt', 'Haushalt', "
                           "'folder', '2026-10-01 08:00:00')")
        connection.execute(
            "INSERT INTO documents (id, vault_id, title, currency, status, source, added_at, pages, current_version, "
            "trashed_status, change_seq, duplicate_kind, process_error, files_state) VALUES (1, 1, 'Vertrag', 'EUR', "
            "'filed', 'upload', '2026-10-01 08:00:00', 1, 1, '', 1, '', '', '')")
        connection.execute("INSERT INTO document_dates (id, document_id, kind, date) VALUES (1, 1, 'contract_end', "
                           "'2026-12-31')")
        connection.execute("PRAGMA user_version = 10")
        connection.commit()
    database.init_db()
    with closing(sqlite3.connect(scratch)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
        row = connection.execute("SELECT kind, date, notice_n, renew_months, notice_date, done_at, renewed_from, "
                                 "renew_anchor FROM document_dates").fetchone()
        # A contract that was there counts its terms from the end it has.
        assert row == ("contract_end", "2026-12-31", None, None, None, None, None, "2026-12-31")
        assert connection.execute("SELECT count(*) FROM deadline_snoozes").fetchone()[0] == 0


def test_the_backup_holds_the_deadlines_and_its_trial_run_passes(house: House, tmp_path: Path) -> None:
    doc = house.add("Rechnung", house.house, house.tom, dates=[("due", TODAY + DAY)])
    with SessionLocal() as db:
        deadlines.snooze(db, house.tom.id, doc, "due", 3, TODAY)
    mobile = house.add("Mobilfunk", house.house, house.tom)
    contract(mobile, house.tom.id, Date(2026, 12, 31))
    path = backups.create(kind=backups.MANUAL)
    try:
        with zipfile.ZipFile(path) as archive:
            copy = tmp_path / "copy.db"
            copy.write_bytes(archive.read(backups.DATABASE_ENTRY))
        with closing(sqlite3.connect(copy)) as connection:
            assert connection.execute("SELECT until FROM deadline_snoozes").fetchall() == [("2026-10-11",)]
            assert connection.execute("SELECT notice_date FROM document_dates WHERE kind = 'contract_end'"
                                      ).fetchall() == [("2026-09-30",)]
        brief = backups.check(path.name)
        assert brief.usable and brief.schema == database.SCHEMA_VERSION
    finally:
        path.unlink(missing_ok=True)
