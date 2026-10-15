"""Reminders (F2): each one exactly once (also with two runs at the same moment), the lead per kind, the day itself,
missed ones up to two days late, "later", the limit per day with one message for the rest, the person's time zone,
muted vaults, readers, lost rights, what is done, the weekly mail, what a message says (never an amount or contents),
the routes of the own account, the step of the schema and the backup.

The clock is given to every run (``reminders.run_once(now)``); the push service and the mail server are stand-ins that
keep what came, so a test reads what was sent.
"""

from __future__ import annotations

import sqlite3
import threading
import zipfile
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from app import db as database
from app.db import SessionLocal
from app.models import Account, Document, ReminderSent, VaultMember
from app.services import (
    apikeys,
    backups,
    brakes,
    deadlines,
    devices,
    documents,
    mailer,
    push,
    reminders,
    settings_service,
)

from .conftest import make_account, new_client
from .fake_push import FakePushService
from .papers import Date, add_document, freeze, own_vault, shared_vault

#: Thursday, the 8th of October 2026 (the mock's today); 8 o'clock in Berlin is 6 o'clock UTC.
TODAY = Date(2026, 10, 8)
DAY = timedelta(days=1)
RECORDS = Path(__file__).parent / "schema"


def at(day: Date, hour: int, minute: int = 0) -> datetime:
    """``hour`` o'clock in Berlin on ``day`` (summer time until the 25th of October), as the UTC the clock gives."""
    offset = 2 if day < Date(2026, 10, 25) else 1
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC) - timedelta(hours=offset)


def set_profile(account: Account, zone: str = "Europe/Berlin", *, mail: str = "", language: str = "de") -> None:
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None
        row.profile = {"timezone": zone}
        row.language = language
        if mail:
            row.email = mail
            row.email_confirmed_at = datetime(2026, 10, 1, tzinfo=UTC)
        db.commit()


def contract(document_id: int, uid: int, end: Date, n: int = 3, renew: int | None = 12) -> None:
    with SessionLocal() as db:
        documents.update_fields(db, uid, document_id, {"dates": [
            {"kind": "contract_end", "date": end, "notice": {"n": n, "unit": "months"}, "renew_months": renew}]})


def choose(account: Account, **change: Any) -> None:
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None
        reminders.save(db, row, change)


class Town:
    """jule (Berlin) manages "Haushalt", tom edits, lea reads; bob has his own vault. Each of jule, tom, lea and bob
    has a phone signed up for pushes."""

    def __init__(self, operator: Account, fake: FakePushService, monkeypatch: pytest.MonkeyPatch) -> None:
        freeze(monkeypatch, at(TODAY, 7))
        self.fake = fake
        self.jule, self.tom, self.lea, self.bob = (make_account(n) for n in ("jule", "tom", "lea", "bob"))
        self.whose: dict[str, str] = {}
        for person in (self.jule, self.tom, self.lea, self.bob):
            set_profile(person, mail=f"{person.name}@example.com")
            self.phone(person)
        self.house = shared_vault("Haushalt", operator, (self.jule, "manage"), (self.tom, "edit"), (self.lea, "read"))
        self.mine = own_vault(self.jule)
        self.bobs = own_vault(self.bob)

    def phone(self, person: Account, lang: str = "de") -> None:
        device = self.fake.device()
        with SessionLocal() as db:
            push.add_device(db, person.id, endpoint=device.endpoint, p256dh=device.p256dh, auth=device.auth,
                            name="Telefon", lang=lang)
        self.whose[device.endpoint.rsplit("/", 1)[-1]] = person.name

    def add(self, title: str, vault: int, owner: Account, **fields: Any) -> int:
        fields.setdefault("content", None)
        fields.setdefault("status", "filed")
        return add_document(vault, owner, title, **fields)

    def got(self) -> list[tuple[str, str]]:
        """(person, title) of every push so far, and forget them."""
        out = [(self.whose[entry.device], entry.message["title"]) for entry in self.fake.received]
        self.fake.received.clear()
        return out

    def messages(self) -> list[dict[str, Any]]:
        out = [entry.message for entry in self.fake.received]
        self.fake.received.clear()
        return out


@pytest.fixture
def town(operator: Account, push_service: FakePushService, monkeypatch: pytest.MonkeyPatch) -> Town:
    return Town(operator, push_service, monkeypatch)


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[EmailMessage]]:
    sent: list[EmailMessage] = []
    monkeypatch.setattr(mailer, "send_message", lambda _db, message: sent.append(message))
    with SessionLocal() as db:
        settings_service.save(db, {"smtp_host": "mail.example.com", "smtp_from": "paper@example.com",
                                   "public_url": "https://paper.example.com"})
    yield sent


def run(moment: datetime) -> reminders.Summary:
    return reminders.run_once(moment)


def sent_rows(uid: int | None = None) -> int:
    with SessionLocal() as db:
        query = select(func.count()).select_from(ReminderSent)
        if uid is not None:
            query = query.where(ReminderSent.user_id == uid)
        return int(db.scalar(query) or 0)


# --- Once, and when ---------------------------------------------------------------------------------------------------


def test_a_bill_is_reminded_ahead_and_on_its_day_each_once(town: Town) -> None:
    doc = town.add("Kurtaxe", town.house, town.tom, dates=[("due", TODAY + 3 * DAY)], amount=21200)
    run(at(TODAY, 7, 59))
    assert town.got() == [], "not before 8 o'clock in the person's zone"
    run(at(TODAY, 8))
    assert sorted(town.got()) == [("jule", "Zahlen bis So, 11.10.: Kurtaxe"), ("tom", "Zahlen bis So, 11.10.: Kurtaxe")]
    run(at(TODAY, 8, 15))
    run(at(TODAY, 20))
    run(at(TODAY + DAY, 8))
    assert town.got() == [], "the lead goes once"
    run(at(TODAY + 3 * DAY, 8))
    messages = town.messages()
    assert [m["body"] for m in messages] == ["Heute.", "Heute."]
    assert {m["url"] for m in messages} == {f"/dokument/{doc}"}
    run(at(TODAY + 3 * DAY, 9))
    run(at(TODAY + 4 * DAY, 8))
    assert town.got() == []


def test_a_deadline_in_the_inbox_opens_the_inbox(town: Town) -> None:
    doc = town.add("Neue Rechnung", town.mine, town.jule, status="inbox", dates=[("due", TODAY + DAY)])
    run(at(TODAY, 8))
    message = town.messages()[0]
    assert message["url"] == f"/eingang/{doc}" and message["body"] == "Morgen."


def at_once(moment: datetime, runs: int = 2) -> None:
    """``runs`` runs started at the same moment, as two processes or a restart in the middle would."""
    start = threading.Barrier(runs)
    failures: list[BaseException] = []

    def one() -> None:
        try:
            start.wait(5)
            run(moment)
        except BaseException as exc:  # noqa: BLE001 (the test reports it)
            failures.append(exc)

    threads = [threading.Thread(target=one) for _ in range(runs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert not failures


def test_two_runs_at_the_same_moment_send_each_reminder_once(town: Town) -> None:
    for n in range(6):
        town.add(f"Rechnung {n}", town.house, town.tom, dates=[("due", TODAY + (n % 3) * DAY)])
    at_once(at(TODAY, 8))
    got = town.got()
    assert len(got) == 12, got  # six deadlines, jule and tom
    assert len(set(got)) == 12, "nobody got the same reminder twice"


def test_two_runs_at_the_same_moment_keep_the_limit_of_the_day(town: Town) -> None:
    """The limit is counted under the write lock: the second run sees what the first one wrote."""
    for n in range(26):
        town.add(f"Viele {n:02d}", town.mine, town.jule, dates=[("due", TODAY + (n % 3) * DAY)])
    at_once(at(TODAY, 8), runs=3)
    titles = [title for person, title in town.got() if person == "jule"]
    assert len(titles) == 21 and titles.count("Und 6 weitere Fristen") == 1, titles


def test_what_was_missed_on_its_day_comes_up_to_two_days_late_and_not_later(town: Town) -> None:
    town.add("Zwei Tage her", town.house, town.tom, dates=[("due", TODAY - 2 * DAY)])
    town.add("Drei Tage her", town.house, town.tom, dates=[("due", TODAY - 3 * DAY)])
    run(at(TODAY, 8))
    got = town.messages()
    assert {m["title"] for m in got} == {"Zahlen bis Di, 06.10.: Zwei Tage her"}
    assert {m["body"] for m in got} == {"Seit 2 Tagen."}


def test_a_deadline_entered_late_is_reminded_at_once(town: Town) -> None:
    """A warranty that ends in 10 days, entered today, is reminded today (lead 30), not never."""
    town.add("Kaffeevollautomat", town.mine, town.jule, dates=[("warranty_end", TODAY + 10 * DAY)])
    run(at(TODAY, 8))
    assert town.got() == [("jule", "Garantie bis So, 18.10.: Kaffeevollautomat")]


@pytest.mark.parametrize(("kind", "lead", "inside", "outside"), [
    ("due", 3, 3, 4),
    ("warranty_end", 30, 30, 31),
])
def test_the_lead_is_per_kind(town: Town, kind: str, lead: int, inside: int, outside: int) -> None:
    town.add("Drin", town.mine, town.jule, dates=[(kind, TODAY + inside * DAY)])
    town.add("Draußen", town.mine, town.jule, dates=[(kind, TODAY + outside * DAY)])
    run(at(TODAY, 8))
    assert [title.split(": ")[1] for _person, title in town.got()] == ["Drin"]


def test_the_lead_of_a_contract_is_its_last_day_to_cancel_and_says_how_it_renews(town: Town) -> None:
    doc = town.add("Handyvertrag", town.mine, town.jule)
    contract(doc, town.jule.id, Date(2027, 1, 22))  # last day to cancel: 22.10.2026, 14 days ahead
    other = town.add("Fernab", town.mine, town.jule)
    contract(other, town.jule.id, Date(2027, 1, 23))  # 15 days ahead
    run(at(TODAY, 8))
    messages = town.messages()
    assert [(m["title"], m["body"]) for m in messages] == [
        ("Kündigen bis Do, 22.10.: Handyvertrag", "Noch 14 Tage. Danach verlängert sich der Vertrag bis 22.01.2028.")]


def test_a_contract_whose_last_day_to_cancel_passed_is_not_reminded_again(town: Town) -> None:
    doc = town.add("Verpasst", town.mine, town.jule)
    contract(doc, town.jule.id, TODAY + 5 * DAY, n=1)
    run(at(TODAY, 8))
    run(at(TODAY + 5 * DAY, 8))
    assert town.got() == []


def test_a_person_chooses_the_lead_and_the_day_itself(town: Town) -> None:
    choose(town.jule, lead={"due": 7}, same_day=False)
    town.add("Sieben", town.mine, town.jule, dates=[("due", TODAY + 7 * DAY)])
    town.add("Heute", town.mine, town.jule, dates=[("due", TODAY)])
    run(at(TODAY, 8))
    assert town.got() == [("jule", "Zahlen bis Do, 15.10.: Sieben")]


def test_eight_o_clock_is_the_persons_own(town: Town) -> None:
    set_profile(town.tom, "America/New_York", mail="tom@example.com")
    town.add("Rechnung", town.house, town.tom, dates=[("due", TODAY + DAY)])
    run(datetime(2026, 10, 8, 6, 0, tzinfo=UTC))  # 8:00 in Berlin, 2:00 in New York
    assert town.got() == [("jule", "Zahlen bis Fr, 09.10.: Rechnung")]
    run(datetime(2026, 10, 8, 11, 59, tzinfo=UTC))
    assert town.got() == []
    run(datetime(2026, 10, 8, 12, 0, tzinfo=UTC))  # 8:00 in New York
    assert town.got() == [("tom", "Zahlen bis Fr, 09.10.: Rechnung")]


# --- Who ---------------------------------------------------------------------------------------------------------------


def test_a_reader_and_a_stranger_get_nothing(town: Town) -> None:
    town.add("Kurtaxe", town.house, town.tom, dates=[("due", TODAY + DAY)])
    run(at(TODAY, 8))
    assert {person for person, _title in town.got()} == {"jule", "tom"}
    assert sent_rows(town.lea.id) == 0 and sent_rows(town.bob.id) == 0


def test_a_lost_right_ends_the_reminders(town: Town) -> None:
    town.add("Kurtaxe", town.house, town.tom, dates=[("due", TODAY + 3 * DAY)])
    with SessionLocal() as db:
        member = db.get(VaultMember, (town.house, town.tom.id))
        assert member is not None
        member.right = "read"
        db.commit()
    run(at(TODAY, 8))
    assert town.got() == [("jule", "Zahlen bis So, 11.10.: Kurtaxe")]


def test_a_share_with_edit_reminds_and_can_be_muted(town: Town) -> None:
    lent = town.add("Geteilt", town.bobs, town.bob, dates=[("due", TODAY + DAY)])
    read = town.add("Nur lesen", town.bobs, town.bob, dates=[("due", TODAY + DAY)])
    with new_client(town.bob) as bob:
        assert bob.put(f"/api/v1/documents/{lent}/shares/{town.lea.id}", json={"right": "edit"}).status_code == 200
        assert bob.put(f"/api/v1/documents/{read}/shares/{town.lea.id}", json={"right": "read"}).status_code == 200
    run(at(TODAY, 8))
    assert sorted(town.got()) == [("bob", "Zahlen bis Fr, 09.10.: Geteilt"), ("bob", "Zahlen bis Fr, 09.10.: Nur lesen"),
                                  ("lea", "Zahlen bis Fr, 09.10.: Geteilt")]
    town.add("Morgen geteilt", town.bobs, town.bob, dates=[("due", TODAY + 2 * DAY)])
    choose(town.lea, muted_shared=True)
    with new_client(town.bob) as bob:
        later = town.add("Noch eins", town.bobs, town.bob, dates=[("due", TODAY + 2 * DAY)])
        bob.put(f"/api/v1/documents/{later}/shares/{town.lea.id}", json={"right": "edit"})
    run(at(TODAY + DAY, 8))
    assert "lea" not in {person for person, _title in town.got()}


def test_a_muted_vault_is_quiet_and_the_own_one_is_not(town: Town, mails: list[EmailMessage]) -> None:
    town.add("Kurtaxe", town.house, town.tom, dates=[("due", TODAY + DAY)])
    town.add("Eigenes", town.mine, town.jule, dates=[("due", TODAY + DAY)])
    choose(town.jule, muted=[town.house], rhythm="both")
    run(at(TODAY, 8))
    assert sorted(town.got()) == [("jule", "Zahlen bis Fr, 09.10.: Eigenes"), ("tom", "Zahlen bis Fr, 09.10.: Kurtaxe")]
    run(at(Date(2026, 10, 12), 8))  # Monday: the weekly mail leaves the muted vault out, too
    week = [m for m in mails if m["To"] == "jule@example.com"]
    assert len(week) == 1
    text = week[0].get_body(("plain",)).get_content()  # type: ignore[union-attr]
    assert "Eigenes" in text and "Kurtaxe" not in text


def test_what_is_done_or_put_off_is_not_reminded_and_later_comes_back(town: Town) -> None:
    paid = town.add("Bezahlt", town.mine, town.jule, dates=[("due", TODAY + DAY)])
    later = town.add("Später", town.mine, town.jule, dates=[("due", TODAY + 2 * DAY)])
    with SessionLocal() as db:
        deadlines.set_done(db, town.jule.id, paid, "due", True)
        deadlines.snooze(db, town.jule.id, later, "due", 3, TODAY)
    run(at(TODAY, 8))
    run(at(TODAY + 2 * DAY, 8))
    assert town.got() == [], "done, and put off over its day"
    run(at(TODAY + 3 * DAY, 8))
    messages = town.messages()
    assert [(m["title"], m["body"]) for m in messages] == [("Zahlen bis Sa, 10.10.: Später", "Seit gestern.")]
    run(at(TODAY + 3 * DAY, 12))
    run(at(TODAY + 4 * DAY, 8))
    assert town.got() == []


def test_later_comes_back_on_its_day_also_far_ahead_of_the_deadline(town: Town) -> None:
    """Put off before its lead began: the day "later" ends reminds, though neither the lead nor the day itself would."""
    doc = town.add("Fern", town.mine, town.jule, dates=[("due", TODAY + 10 * DAY)])
    with SessionLocal() as db:
        deadlines.snooze(db, town.jule.id, doc, "due", 1, TODAY)
    run(at(TODAY + DAY, 8))
    assert [(m["title"], m["body"]) for m in town.messages()] == [("Zahlen bis So, 18.10.: Fern", "Noch 9 Tage.")]
    run(at(TODAY + 2 * DAY, 8))
    assert town.got() == []


def test_a_blocked_account_hears_nothing(town: Town) -> None:
    with SessionLocal() as db:
        row = db.get(Account, town.tom.id)
        assert row is not None
        row.blocked_at = datetime(2026, 10, 1, tzinfo=UTC)
        db.commit()
    town.add("Kurtaxe", town.house, town.jule, dates=[("due", TODAY + DAY)])
    run(at(TODAY, 8))
    assert {person for person, _title in town.got()} == {"jule"}


# --- The brake --------------------------------------------------------------------------------------------------------


def test_at_most_twenty_a_day_and_one_message_for_the_rest(town: Town) -> None:
    choose(town.jule, same_day=False)
    for n in range(26):
        town.add(f"Import {n:02d}", town.mine, town.jule, dates=[("due", TODAY + (n % 3 + 1) * DAY)])
    summary = run(at(TODAY, 8))
    titles = [title for person, title in town.got() if person == "jule"]
    assert len(titles) == 21
    assert titles[-1] == "Und 6 weitere Fristen"
    assert summary.messages == 20 and summary.gathered == 6
    run(at(TODAY, 9))
    assert town.got() == [], "what went into the gathering message is done with"
    town.add("Neu dazu", town.mine, town.jule, dates=[("due", TODAY + 2 * DAY)])
    run(at(TODAY, 10))
    assert town.got() == [], "over the limit after the gathering message: waits for the next day"
    run(at(TODAY + DAY, 8))
    assert town.got() == [("jule", "Zahlen bis Sa, 10.10.: Neu dazu")]


# --- What a message says ----------------------------------------------------------------------------------------------


def test_a_message_names_kind_day_and_title_never_amount_text_notes_or_tags(town: Town,
                                                                           mails: list[EmailMessage]) -> None:
    choose(town.jule, mail=True, rhythm="both")
    # Two days ahead: the sentence counts the days ("Noch 2 Tage."), the place an amount would most likely slip into.
    doc = town.add("Zahnarzt", town.mine, town.jule, dates=[("due", TODAY + 2 * DAY)], amount=987654,
                   tags=["Geheimtag"])
    with SessionLocal() as db:
        documents.add_note(db, town.jule.id, doc, "Geheimnotiz")
        # The interface refuses control characters in a title; one that came in another way still stays one line.
        found = db.get(Document, doc)
        assert found is not None
        found.title = "Zahnarzt\r\nBcc: x@example.com"
        db.commit()
    run(at(Date(2026, 10, 12), 8) - 4 * DAY)  # Thursday the 8th
    run(at(Date(2026, 10, 12), 8))  # Monday: the weekly mail
    messages = town.messages()
    assert messages and all("Zahnarzt Bcc: x@example.com" in m["title"] for m in messages)
    assert len(mails) == 3  # ahead on Thursday, on Monday the missed day itself (two days late) and the week
    single, late, week = mails
    assert late["Subject"] == single["Subject"] and "Seit 2 Tagen." in late.get_content()
    assert single["Subject"] == "Zahlen bis Sa, 10.10.: Zahnarzt Bcc: x@example.com" and single["Bcc"] is None
    assert "Noch 2 Tage." in single.get_content()
    for text in [repr(m) for m in messages] + [m.as_string() for m in mails]:
        for secret in ("987654", "9.876,54", "9876", "Geheimnotiz", "Geheimtag"):
            assert secret not in text
    assert "https://paper.example.com/dokument/" in single.get_content()
    plain = week.get_body(("plain",)).get_content()  # type: ignore[union-attr]
    markup = week.get_body(("html",)).get_content()  # type: ignore[union-attr]
    assert week["Subject"] == "Diese Woche: keine Fristen, 1 überfällig"
    assert "ÜBERFÄLLIG" in plain and "Sa, 10.10. · Zahlen: Zahnarzt Bcc: x@example.com" in plain
    assert "https://paper.example.com/fristen" in plain and "Wochenübersicht eingeschaltet" in plain
    assert "<script" not in markup and "Alle Fristen in nexpaper öffnen" in markup


def test_an_english_person_gets_english_words(town: Town) -> None:
    set_profile(town.jule, language="en", mail="jule@example.com")
    doc = town.add("Mobile", town.mine, town.jule)
    contract(doc, town.jule.id, Date(2027, 1, 22))
    run(at(TODAY, 8))
    message = town.messages()[0]
    assert message["title"] == "Cancel by Thu, Oct 22: Mobile"
    assert message["body"] == "14 days to go. After that the contract renews until Jan 22, 2028."


def test_the_weekly_mail_goes_on_monday_only_when_something_comes_up(town: Town, mails: list[EmailMessage]) -> None:
    choose(town.jule, rhythm="weekly")
    monday = Date(2026, 10, 12)
    run(at(monday, 8))
    assert mails == [], "nothing comes up: no mail"
    town.add("Nächste", town.mine, town.jule, dates=[("due", monday + 8 * DAY)])
    run(at(monday + DAY, 8))
    assert mails == [], "the week was looked at on Monday"
    for n in range(5):
        town.add(f"Alt {n}", town.mine, town.jule, dates=[("keep_until", monday - 30 * DAY)])
    run(at(monday + 7 * DAY, 7, 59))
    assert mails == []
    run(at(monday + 7 * DAY, 9))
    assert town.got() == [], "only weekly: no single pushes"
    assert len(mails) == 1
    assert mails[0]["Subject"] == "Diese Woche: 1 Frist"
    plain = mails[0].get_body(("plain",)).get_content()  # type: ignore[union-attr]
    assert "Di, 20.10. · Zahlen: Nächste" in plain and "Bei 5 Dokumenten ist die Aufbewahrungszeit um." in plain
    assert "Guten Morgen jule" in plain
    run(at(monday + 8 * DAY, 8))
    assert len(mails) == 1


def test_a_muted_vault_does_not_count_in_the_documents_that_may_go(town: Town, mails: list[EmailMessage]) -> None:
    choose(town.jule, rhythm="weekly")
    monday = Date(2026, 10, 12)
    for n in range(2):
        town.add(f"Alt {n}", town.mine, town.jule, dates=[("keep_until", monday - 30 * DAY)])
    for n in range(3):
        town.add(f"Haus {n}", town.house, town.jule, dates=[("keep_until", monday - 30 * DAY)])
    # A document of somebody else in the shared vault counts as well; somebody who may only read has none to clear.
    town.add("Lea", town.house, town.lea, dates=[("keep_until", monday - 30 * DAY)])
    with SessionLocal() as db:
        assert reminders.may_go_count(db, town.jule.id, reminders.preferences_of(db, town.jule.id), monday) == 6
        assert reminders.may_go_count(db, town.lea.id, reminders.preferences_of(db, town.lea.id), monday) == 0
    choose(town.jule, muted=[town.house])
    with SessionLocal() as db:
        assert reminders.may_go_count(db, town.jule.id, reminders.preferences_of(db, town.jule.id), monday) == 2
    run(at(monday, 9))
    assert len(mails) == 1
    plain = mails[0].get_body(("plain",)).get_content()  # type: ignore[union-attr]
    assert "Bei 2 Dokumenten ist die Aufbewahrungszeit um." in plain
    assert "Bei 3 " not in plain and "Bei 6 " not in plain and "Bei 5 " not in plain


def test_the_preview_counts_what_may_go_like_the_weekly_mail(town: Town, mails: list[EmailMessage],
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """``may_go`` of the own choices is the number the mail would say: the muted vaults left out, nothing for somebody
    who may only read, nothing of what is not over yet."""
    monday = Date(2026, 10, 12)
    freeze(monkeypatch, at(monday, 9))
    for n in range(2):
        town.add(f"Alt {n}", town.mine, town.jule, dates=[("keep_until", monday - 30 * DAY)])
    for n in range(3):
        town.add(f"Haus {n}", town.house, town.jule, dates=[("keep_until", monday - 30 * DAY)])
    town.add("Noch nicht", town.house, town.jule, dates=[("keep_until", monday + 30 * DAY)])
    with new_client(town.jule) as jule, new_client(town.lea) as lea:
        assert jule.get("/api/v1/me/reminders").json()["may_go"] == 5
        assert lea.get("/api/v1/me/reminders").json()["may_go"] == 0
        assert jule.put("/api/v1/me/reminders", json={"muted": [town.house]}).json()["may_go"] == 2
        assert jule.get("/api/v1/me/reminders").json()["may_go"] == 2
        assert jule.put("/api/v1/me/reminders", json={"muted": [town.house, town.mine]}).json()["may_go"] == 0


def test_with_every_vault_muted_the_weekly_mail_does_not_mention_what_may_go(town: Town, mails: list[EmailMessage]) -> None:
    choose(town.jule, rhythm="weekly", muted=[town.house, town.mine])
    monday = Date(2026, 10, 12)
    town.add("Alt", town.house, town.jule, dates=[("keep_until", monday - 30 * DAY)])
    town.add("Alt zwei", town.mine, town.jule, dates=[("keep_until", monday - 30 * DAY)])
    run(at(monday, 9))
    assert mails == []


def test_the_weekly_mail_missed_on_monday_comes_until_wednesday(town: Town, mails: list[EmailMessage]) -> None:
    choose(town.jule, rhythm="weekly")
    town.add("Offen", town.mine, town.jule, dates=[("due", TODAY + 6 * DAY)])
    run(at(Date(2026, 10, 15), 8))  # Thursday: three days after Monday
    assert mails == []
    run(at(Date(2026, 10, 21), 8))  # Wednesday of the next week: two days after Monday, "Offen" is overdue
    assert len(mails) == 1 and mails[0]["Subject"] == "Diese Woche: keine Fristen, 1 überfällig"


def test_without_a_confirmed_address_nothing_goes_by_mail(town: Town, mails: list[EmailMessage]) -> None:
    choose(town.jule, mail=True, rhythm="both")
    with SessionLocal() as db:
        row = db.get(Account, town.jule.id)
        assert row is not None
        row.email_confirmed_at = None
        db.commit()
    town.add("Rechnung", town.mine, town.jule, dates=[("due", TODAY + DAY)])
    run(at(Date(2026, 10, 12), 8) - 4 * DAY)
    assert mails == [] and town.got() == [("jule", "Zahlen bis Fr, 09.10.: Rechnung")]


# --- The routes -------------------------------------------------------------------------------------------------------


def test_the_own_choices_are_read_and_changed_only_by_their_owner(town: Town, mails: list[EmailMessage]) -> None:
    with new_client(town.lea) as lea:
        found = lea.get("/api/v1/me/reminders").json()
        assert found["rhythm"] == "single" and found["push"] is True and found["mail"] is False
        assert found["lead"] == {"due": 3, "cancel": 14, "warranty": 30} and found["same_day"] is True
        assert [v["name"] for v in found["vaults"]] == ["lea"] and found["vaults"][0]["personal"] is True
        assert [v["name"] for v in found["read_only"]] == ["Haushalt"]
        assert found["push_devices"] == 1 and found["mail_problem"] is None and found["time_zone"] == "Europe/Berlin"
        # Muting a vault one may only read, or somebody else's: the same answer as one that does not exist.
        for vault in (town.house, town.bobs, 999999):
            answer = lea.put("/api/v1/me/reminders", json={"muted": [vault]})
            assert answer.status_code == 422 and answer.json()["detail"]["code"] == "bad_reminder"
        assert lea.put("/api/v1/me/reminders", json={"lead": {"due": 5}}).status_code == 422
        assert lea.put("/api/v1/me/reminders", json={"rhythm": "daily"}).status_code == 422
        assert lea.put("/api/v1/me/reminders", json={"unknown": 1}).status_code == 422
        changed = lea.put("/api/v1/me/reminders", json={"lead": {"warranty": 60}, "muted": [own_vault(town.lea)]})
        assert changed.status_code == 200
        assert changed.json()["lead"]["warranty"] == 60 and changed.json()["muted"] == [own_vault(town.lea)]
        assert changed.json()["vaults"][0]["muted"] is True
    with new_client(town.jule) as jule:
        assert jule.get("/api/v1/me/reminders").json()["muted"] == []
        mine = jule.get("/api/v1/me/reminders").json()["vaults"]
        assert {v["name"]: v["others"] for v in mine} == {"jule": 0, "Haushalt": 2}  # tom and the operator


def test_mail_is_switched_on_only_when_it_can_go(town: Town) -> None:
    with new_client(town.jule) as jule:
        found = jule.get("/api/v1/me/reminders").json()
        assert found["mail_problem"] == "no_server"
        for change in ({"mail": True}, {"rhythm": "weekly"}, {"rhythm": "both"}):
            answer = jule.put("/api/v1/me/reminders", json=change)
            assert answer.status_code == 409 and answer.json()["detail"]["code"] == "mail_unavailable"
        assert jule.put("/api/v1/me/reminders", json={"push": False}).status_code == 200


def test_a_device_reaches_the_own_choices_and_a_key_does_not(town: Town) -> None:
    apikeys.forget()
    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": True})
        row = db.get(Account, town.jule.id)
        assert row is not None
        _device, token = devices.make(db, row, "App")
    with new_client(town.jule) as jule:
        secret = jule.post("/api/v1/api-keys", json={"name": "deck", "scope": "read"}).json()["secret"]
    with TestClient(new_client().app, base_url="http://testserver") as program:
        assert program.get("/api/v1/me/reminders").status_code == 401
        by_device = program.get("/api/v1/me/reminders", headers={"Authorization": f"Bearer {token}"})
        assert by_device.status_code == 200 and by_device.json()["vaults"][0]["name"] == "jule"
        assert program.put("/api/v1/me/reminders", json={"same_day": False},
                           headers={"Authorization": f"Bearer {token}"}).status_code == 200
        for method in ("get", "put"):
            answer = getattr(program, method)("/api/v1/me/reminders", headers={"Authorization": f"Bearer {secret}"},
                                              **({"json": {}} if method == "put" else {}))
            assert answer.status_code == 401
        assert program.post("/api/v1/me/reminders/test",
                            headers={"Authorization": f"Bearer {secret}"}).status_code == 401
    apikeys.forget()


def test_the_test_message_goes_where_the_reminders_go(town: Town, mails: list[EmailMessage]) -> None:
    with new_client(town.jule) as jule:
        answer = jule.post("/api/v1/me/reminders/test")
        assert answer.status_code == 200 and answer.json()["push"]["sent"] == 1 and answer.json()["mail"] is False
        assert town.messages()[0]["title"] == "Testnachricht von nexpaper"
        jule.put("/api/v1/me/reminders", json={"mail": True})
        assert jule.post("/api/v1/me/reminders/test").json()["mail"] is True
        assert mails[-1]["Subject"] == "Testnachricht von nexpaper"
        jule.put("/api/v1/me/reminders", json={"mail": False, "push": False})
        answer = jule.post("/api/v1/me/reminders/test")
        assert answer.status_code == 409 and answer.json()["detail"]["code"] == "reminders_no_way"


def test_a_mute_whose_right_is_gone_blocks_nothing(town: Town) -> None:
    """tom muted "Haushalt", then lost the right to change things in it: the mute is no choice any more. It is not
    listed, saving the tab (which sends what it got) works, and the row is cleaned up."""
    choose(town.tom, muted=[town.house])
    with SessionLocal() as db:
        member = db.get(VaultMember, (town.house, town.tom.id))
        assert member is not None
        member.right = "read"
        db.commit()
    mine = own_vault(town.tom)
    with new_client(town.tom) as tom:
        found = tom.get("/api/v1/me/reminders").json()
        assert found["muted"] == [] and [v["id"] for v in found["vaults"]] == [mine]
        assert [v["id"] for v in found["read_only"]] == [town.house]
        # What the page does: sends the list it was given, plus the vault the person muted now.
        answer = tom.put("/api/v1/me/reminders", json={"muted": [*found["muted"], mine]})
        assert answer.status_code == 200 and answer.json()["muted"] == [mine]
        with SessionLocal() as db:
            assert reminders.muted_of(db, town.tom.id) == [mine], "the row of the lost vault is gone"
    # A page that was open before the right went still names the lost vault: saved all the same, it is dropped.
    choose(town.jule, muted=[town.house])
    with SessionLocal() as db:
        member = db.get(VaultMember, (town.house, town.jule.id))
        assert member is not None
        member.right = "read"
        db.commit()
    with new_client(town.jule) as jule:
        answer = jule.put("/api/v1/me/reminders", json={"muted": [town.house, own_vault(town.jule)]})
        assert answer.status_code == 200 and answer.json()["muted"] == [own_vault(town.jule)]
    with SessionLocal() as db:
        assert reminders.muted_of(db, town.jule.id) == [own_vault(town.jule)], "the row of the lost vault is gone"


def test_a_lost_mute_is_cleaned_by_any_save_and_does_not_come_back(town: Town) -> None:
    choose(town.tom, muted=[town.house])
    with SessionLocal() as db:
        member = db.get(VaultMember, (town.house, town.tom.id))
        assert member is not None
        member.right = "read"
        db.commit()
    with new_client(town.tom) as tom:
        assert tom.put("/api/v1/me/reminders", json={"same_day": False}).status_code == 200
    with SessionLocal() as db:
        assert reminders.muted_of(db, town.tom.id) == []
        member = db.get(VaultMember, (town.house, town.tom.id))
        assert member is not None
        member.right = "edit"
        db.commit()
    with new_client(town.tom) as tom:
        assert tom.get("/api/v1/me/reminders").json()["muted"] == []


def test_a_vault_never_muted_and_not_to_be_changed_is_still_refused(town: Town) -> None:
    """The lost mute is dropped without a word; a vault the person never had muted is the same 422 as before."""
    choose(town.tom, muted=[town.house])
    with SessionLocal() as db:
        member = db.get(VaultMember, (town.house, town.tom.id))
        assert member is not None
        member.right = "read"
        db.commit()
    with new_client(town.tom) as tom:
        for vault in (town.bobs, 999999):
            answer = tom.put("/api/v1/me/reminders", json={"muted": [vault]})
            assert answer.status_code == 422 and answer.json()["detail"]["code"] == "bad_reminder"
        assert tom.put("/api/v1/me/reminders", json={"muted": [town.house]}).status_code == 200


def test_nothing_sent_for_a_field_changes_nothing_and_numbers_are_whole_numbers(town: Town) -> None:
    choose(town.jule, muted=[town.house], lead={"due": 7}, push=False)
    with new_client(town.jule) as jule:
        before = jule.get("/api/v1/me/reminders").json()
        answer = jule.put("/api/v1/me/reminders", json={"muted": None, "rhythm": None, "push": None, "lead": None})
        assert answer.status_code == 200 and answer.json() == before
        assert answer.json()["muted"] == [town.house] and answer.json()["push"] is False
        assert jule.put("/api/v1/me/reminders", json={"lead": {"due": None}}).json() == before
        for body in ({"lead": {"due": True}}, {"lead": {"cancel": False}}, {"lead": {"warranty": 30.0}},
                     {"lead": {"due": "3"}}, {"muted": [True]}, {"muted": [town.house, 1.5]}):
            answer = jule.put("/api/v1/me/reminders", json=body)
            assert answer.status_code == 422, body
        assert jule.get("/api/v1/me/reminders").json() == before


def test_the_numbers_of_a_choice_are_checked_as_whole_numbers_before_anything_else() -> None:
    """``true`` is not a 1, in the lead and in the list of vaults (a vault 1 may well exist and be the caller's)."""
    from pydantic import ValidationError

    from app.routers.reminders import RemindersIn

    assert RemindersIn.model_validate({"lead": {"due": 7}, "muted": [4]}).lead is not None
    for body in ({"lead": {"due": True}}, {"lead": {"cancel": True}}, {"lead": {"warranty": True}},
                 {"muted": [True]}, {"muted": [1.0]}, {"muted": ["1"]}):
        with pytest.raises(ValidationError):
            RemindersIn.model_validate(body)


def test_the_zone_of_the_server_is_named_by_its_iana_name(town: Town, monkeypatch: pytest.MonkeyPatch) -> None:
    with SessionLocal() as db:
        row = db.get(Account, town.jule.id)
        assert row is not None
        row.profile = {}
        db.commit()
    monkeypatch.setenv("TZ", "Europe/Berlin")
    with new_client(town.jule) as jule:
        assert jule.get("/api/v1/me/reminders").json()["time_zone"] == "Europe/Berlin"
        monkeypatch.setenv("TZ", "Not/AZone")
        assert jule.get("/api/v1/me/reminders").json()["time_zone"] not in ("", "Not/AZone")
    # The zone the browser reported wins over the server's.
    set_profile(town.jule, "America/New_York")
    with new_client(town.jule) as jule:
        assert jule.get("/api/v1/me/reminders").json()["time_zone"] == "America/New_York"


# --- The first look after the update ----------------------------------------------------------------------------------


def undo_last_step_and_redo_it() -> None:
    """The database as the update finds it: the step runs on the tables of today (here with documents already in)."""
    with database.engine.begin() as connection:
        for table in ("reminders_sent", "reminder_mutes", "reminder_settings"):
            connection.exec_driver_sql(f"DROP TABLE {table}")
        database._step_reminders(connection)


def seed_marks(stage: str) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(ReminderSent).where(ReminderSent.stage == stage)) or 0)


def test_the_update_brings_no_flood_for_deadlines_that_were_there(town: Town) -> None:
    for n in range(30):
        town.add(f"Frist {n}", town.mine, town.jule, dates=[("due", TODAY + (1 + n % 3) * DAY)])
    town.add("Heute", town.mine, town.jule, dates=[("due", TODAY)])
    undo_last_step_and_redo_it()
    assert seed_marks("seed") == 5, "one mark per person that existed"
    assert run(at(TODAY, 7)).messages == 0  # the first look, before the hour: marks, sends nothing
    assert seed_marks("seed") == 0 and seed_marks("lead") == 30
    run(at(TODAY, 8))
    assert town.got() == [("jule", "Zahlen bis Do, 08.10.: Heute")], "the day itself goes on"
    for n, day in enumerate((TODAY + DAY, TODAY + 2 * DAY, TODAY + 3 * DAY)):
        run(at(day, 8))
        assert len(town.got()) == 10, f"day {n + 1}: one for each, on its day"
    run(at(TODAY + 4 * DAY, 8))
    assert town.got() == []


def test_a_deadline_entered_after_the_update_is_reminded_ahead_as_ever(town: Town) -> None:
    undo_last_step_and_redo_it()
    run(at(TODAY, 7))
    town.add("Neu", town.mine, town.jule, dates=[("due", TODAY + 2 * DAY)])
    run(at(TODAY, 8))
    assert town.got() == [("jule", "Zahlen bis Sa, 10.10.: Neu")]


def test_without_a_mark_nothing_is_held_back(town: Town) -> None:
    """A person who came after the update has no mark: the lead goes."""
    town.add("Bald", town.mine, town.jule, dates=[("due", TODAY + 2 * DAY)])
    run(at(TODAY, 8))
    assert town.got() == [("jule", "Zahlen bis Sa, 10.10.: Bald")]


# --- Gaps the check found ---------------------------------------------------------------------------------------------


def test_the_weekly_mail_shows_a_title_and_a_name_as_text_not_as_markup(town: Town, mails: list[EmailMessage]) -> None:
    choose(town.jule, rhythm="weekly")
    with SessionLocal() as db:
        row = db.get(Account, town.jule.id)
        assert row is not None
        row.display_name = "<i>Jule</i> & Co"
        db.commit()
    monday = Date(2026, 10, 12)
    for title in ('<img src=x onerror="alert(1)">', '<b>fett</b> & "quote"'):
        town.add(title, town.mine, town.jule, dates=[("due", monday + 2 * DAY)])
    run(at(monday, 8))
    assert len(mails) == 1
    markup = mails[0].get_body(("html",)).get_content()  # type: ignore[union-attr]
    assert "<img" not in markup and "<b>" not in markup and "<i>" not in markup
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in markup
    assert "&lt;b&gt;fett&lt;/b&gt; &amp; &quot;quote&quot;" in markup
    assert "&lt;i&gt;Jule&lt;/i&gt; &amp; Co" in markup
    plain = mails[0].get_body(("plain",)).get_content()  # type: ignore[union-attr]
    assert "<img src=x" in plain, "the plain text is plain text"


@pytest.mark.parametrize(("zone", "offset"), [("Pacific/Auckland", 13), ("Pacific/Kiritimati", 14)])
def test_eight_o_clock_in_a_zone_ahead_of_utc_is_already_the_next_day_there(town: Town, zone: str,
                                                                            offset: int) -> None:
    """At 8 o'clock in Auckland on the 9th it is still the 8th in UTC: the day is the person's, not the server's."""
    set_profile(town.jule, zone, mail="jule@example.com")
    town.add("Hier", town.mine, town.jule, dates=[("due", Date(2026, 10, 9))])
    moment = datetime(2026, 10, 9, 8, 0, tzinfo=UTC) - timedelta(hours=offset)
    assert moment.date() == Date(2026, 10, 8)
    run(moment - timedelta(minutes=1))
    assert town.got() == [], "7:59 there"
    run(moment)
    assert town.messages()[0]["body"] == "Heute."


def test_the_test_message_has_a_brake(town: Town) -> None:
    brakes.forget()
    try:
        with new_client(town.jule) as jule:
            for _ in range(brakes.LIMITS["push_test"]):
                assert jule.post("/api/v1/me/reminders/test").status_code == 200
            answer = jule.post("/api/v1/me/reminders/test")
            assert answer.status_code == 429 and "retry-after" in answer.headers
            assert answer.json()["detail"]["code"] == "push_too_often"
            assert len(town.messages()) == brakes.LIMITS["push_test"], "the message over the limit was not sent"
        with new_client(town.tom) as tom:
            assert tom.post("/api/v1/me/reminders/test").status_code == 200, "the brake is per person"
    finally:
        brakes.forget()


@pytest.mark.parametrize("scope", ["read", "upload"])
def test_no_api_key_of_any_scope_reaches_the_reminders(town: Town, scope: str) -> None:
    apikeys.forget()
    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": True})
    with new_client(town.jule) as jule:
        secret = jule.post("/api/v1/api-keys", json={"name": "program", "scope": scope}).json()["secret"]
    header = {"Authorization": f"Bearer {secret}"}
    with TestClient(new_client().app, base_url="http://testserver") as program:
        assert program.get("/api/v1/me/reminders", headers=header).status_code == 401
        assert program.put("/api/v1/me/reminders", json={"same_day": False}, headers=header).status_code == 401
        assert program.post("/api/v1/me/reminders/test", headers=header).status_code == 401
    assert town.messages() == []
    with SessionLocal() as db:
        assert reminders.preferences_of(db, town.jule.id).same_day is True
    apikeys.forget()


# --- The schema and the backup ----------------------------------------------------------------------------------------


@pytest.fixture
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "nexpaper.db"
    engine = create_engine(f"sqlite:///{path}")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(backups, "create", lambda **_kwargs: path)
    return path


def test_a_database_of_schema_11_comes_up_with_the_reminder_tables(scratch: Path) -> None:
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v11.sql").read_text(encoding="utf-8"))
        connection.execute("INSERT INTO vaults (id, name, folder, icon, created_at) VALUES (1, 'Haushalt', 'Haushalt', "
                           "'folder', '2026-10-01 08:00:00')")
        connection.execute("INSERT INTO users (id, name, display_name, whats_new_seen, role, sign_in, password_hash, "
                           "email, oidc_subject, language, created_at, failed_logins, totp_secret_enc, totp_recovery, "
                           "totp_last_step) VALUES (1, 'jule', 'Jule', '', 'member', 'password', '', '', '', 'de', "
                           "'2026-10-01 08:00:00', 0, '', '', 0)")
        connection.execute("PRAGMA user_version = 11")
        connection.commit()
    database.init_db()
    with closing(sqlite3.connect(scratch)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
        for statement in ("SELECT count(*) FROM reminder_settings", "SELECT count(*) FROM reminder_mutes",
                          "SELECT count(*) FROM reminders_sent WHERE stage <> 'seed'"):
            assert connection.execute(statement).fetchone()[0] == 0
        assert connection.execute("SELECT name FROM vaults").fetchall() == [("Haushalt",)]
        # The one mark of the person that existed: their first look after the update marks the open leads.
        assert connection.execute("SELECT user_id, stage, date_id FROM reminders_sent").fetchall() == [
            (1, "seed", None)]


def test_a_database_of_schema_12_comes_up_with_the_reminder_tables(scratch: Path) -> None:
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v12.sql").read_text(encoding="utf-8"))
        connection.execute("INSERT INTO users (id, name, display_name, whats_new_seen, role, sign_in, password_hash, "
                           "email, oidc_subject, language, created_at, failed_logins, totp_secret_enc, totp_recovery, "
                           "totp_last_step) VALUES (1, 'jule', 'Jule', '', 'member', 'password', '', '', '', 'de', "
                           "'2026-10-01 08:00:00', 0, '', '', 0)")
        connection.execute("PRAGMA user_version = 12")
        connection.commit()
    database.init_db()
    with closing(sqlite3.connect(scratch)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION == 13
        for statement in ("SELECT count(*) FROM reminder_settings", "SELECT count(*) FROM reminder_mutes",
                          "SELECT count(*) FROM reminders_sent WHERE stage <> 'seed'"):
            assert connection.execute(statement).fetchone()[0] == 0
        assert connection.execute("SELECT user_id, stage, date_id FROM reminders_sent").fetchall() == [
            (1, "seed", None)]


def test_the_backup_holds_the_reminders(town: Town, tmp_path: Path) -> None:
    choose(town.jule, lead={"due": 7}, muted=[town.house])
    town.add("Rechnung", town.mine, town.jule, dates=[("due", TODAY + DAY)])
    run(at(TODAY, 8))
    path = backups.create(kind=backups.MANUAL)
    try:
        with zipfile.ZipFile(path) as archive:
            copy = tmp_path / "copy.db"
            copy.write_bytes(archive.read(backups.DATABASE_ENTRY))
        with closing(sqlite3.connect(copy)) as connection:
            assert connection.execute("SELECT lead_due FROM reminder_settings").fetchall() == [(7,)]
            assert connection.execute("SELECT vault_id FROM reminder_mutes").fetchall() == [(town.house,)]
            assert connection.execute("SELECT stage, day FROM reminders_sent").fetchall() == [("lead", "2026-10-09")]
        brief = backups.check(path.name)
        assert brief.usable and brief.schema == database.SCHEMA_VERSION
    finally:
        path.unlink(missing_ok=True)
