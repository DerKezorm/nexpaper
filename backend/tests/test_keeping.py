"""Keeping documents: the keeping time of a kind, ``keep_until`` worked out from it or set by hand, "may go", many
documents into the trash, the search word, the list of the export.

The rules that matter: the time counts from the end of the year of the document's date; what a person set stays; the
numbers of the question count only what the person may see; nothing goes by itself; "may go" looks only at vaults
where the person may change things.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, DocumentDate, Event, Job
from app.services import jobs, keeping

from .conftest import make_account, new_client
from .intake import device_token, upload_key
from .papers import add_document, document, freeze, own_vault, shared_vault

NOW = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def today(monkeypatch: pytest.MonkeyPatch) -> None:
    freeze(monkeypatch, NOW)


def kind_id(client: TestClient, key: str) -> int:
    return int(next(k["id"] for k in client.get("/api/v1/kinds").json() if k["key"] == key))


def keep_of(document_id: int) -> tuple[date, bool] | None:
    with SessionLocal() as db:
        row = db.scalar(select(DocumentDate).where(DocumentDate.document_id == document_id,
                                                   DocumentDate.kind == "keep_until"))
        return (row.date, row.manual) if row is not None else None


def set_keep(session: TestClient, kind: int, years: int | None, existing: bool = True) -> dict[str, Any]:
    answer = session.put(f"/api/v1/kinds/{kind}/keeping", json={"years": years, "existing": existing})
    assert answer.status_code == 200, answer.text
    return answer.json()  # type: ignore[no-any-return]


def keep_entry(session: TestClient, document_id: int) -> dict[str, Any] | None:
    """The ``keep_until`` of the document as the interface says it (the terms of deadlines are left out)."""
    shown = session.get(f"/api/v1/documents/{document_id}").json()
    found = next((d for d in shown["dates"] if d["kind"] == "keep_until"), None)
    return None if found is None else {k: found[k] for k in ("kind", "date", "manual") if k in found}


# --- Working it out ---------------------------------------------------------------------------------------------------


def test_the_time_counts_from_the_end_of_the_year_of_the_date() -> None:
    assert keeping.until(10, date(2026, 3, 14), None) == date(2036, 12, 31)
    assert keeping.until(2, date(2026, 12, 31), None) == date(2028, 12, 31)
    assert keeping.until(1, date(2026, 1, 1), None) == date(2027, 12, 31)
    # Without a date, the day it came in.
    assert keeping.until(6, None, datetime(2025, 7, 1, tzinfo=UTC)) == date(2031, 12, 31)


def test_setting_a_time_for_the_documents_there_works_each_out(client: TestClient, operator: Account) -> None:
    mine = own_vault(operator)
    invoice = kind_id(client, "invoice")
    dated = add_document(mine, operator, "Strom", kind_id=invoice, date=date(2026, 3, 14), content=None)
    undated = add_document(mine, operator, "Ohne Datum", kind_id=invoice, content=None)
    other = add_document(mine, operator, "Vertrag", kind_id=kind_id(client, "contract"), date=date(2026, 3, 14),
                         content=None)
    assert keep_of(dated) is None, "the kinds that come with nexpaper keep nothing"
    before = document(dated).change_seq
    done = set_keep(client, invoice, 10)
    assert (done["changed"], done["queued"], done["kind"]["keep_years"]) == (2, False, 10)
    assert keep_of(dated) == (date(2036, 12, 31), False)
    assert keep_of(undated) == (date(2036, 12, 31), False), "counted from the day it came (2026)"
    assert keep_of(other) is None
    assert document(dated).change_seq > before
    events = client.get(f"/api/v1/documents/{dated}/events").json()
    assert events[0]["detail"] == {"fields": ["keep_until"], "by": "catalog"}
    assert keep_entry(client, dated) == {"kind": "keep_until", "date": "2036-12-31", "manual": False}
    order = next(k for k in client.get("/api/v1/order/kinds").json()["items"] if k["id"] == invoice)
    assert (order["keep_years"], order["keep_new_only"]) == (10, False)


def test_only_for_new_ones_leaves_the_documents_there_alone(client: TestClient, operator: Account) -> None:
    mine = own_vault(operator)
    invoice = kind_id(client, "invoice")
    old = add_document(mine, operator, "Alt", kind_id=invoice, date=date(2020, 5, 1), content=None)
    done = set_keep(client, invoice, 8, existing=False)
    assert (done["changed"], done["kind"]["keep_years"]) == (0, 8)
    assert keep_of(old) is None
    order = next(k for k in client.get("/api/v1/order/kinds").json()["items"] if k["id"] == invoice)
    assert order["keep_new_only"] is True
    new = add_document(mine, operator, "Neu", kind_id=invoice, date=date(2026, 1, 5), content=None)
    assert keep_of(new) == (date(2034, 12, 31), False)
    # A change to an old one works it out too.
    assert client.patch(f"/api/v1/documents/{old}", json={"date": "2021-05-01"}).status_code == 200
    assert keep_of(old) == (date(2029, 12, 31), False)


def test_a_change_of_kind_date_or_vault_works_it_out_again(client: TestClient, operator: Account) -> None:
    mine = own_vault(operator)
    household = shared_vault("Haushalt", operator)
    invoice, contract = kind_id(client, "invoice"), kind_id(client, "contract")
    set_keep(client, invoice, 10)
    set_keep(client, contract, 3)
    doc = add_document(mine, operator, "Strom", kind_id=invoice, date=date(2026, 3, 14), content=None)
    assert keep_of(doc) == (date(2036, 12, 31), False)
    assert client.patch(f"/api/v1/documents/{doc}", json={"date": "2024-02-01"}).status_code == 200
    assert keep_of(doc) == (date(2034, 12, 31), False)
    events = client.get(f"/api/v1/documents/{doc}/events").json()
    assert events[0]["detail"]["fields"] == ["date", "keep_until"]
    assert client.patch(f"/api/v1/documents/{doc}", json={"kind_id": contract}).status_code == 200
    assert keep_of(doc) == (date(2027, 12, 31), False)
    # A kind of a vault with the same name as one there: another vault, another kind, another time.
    own_kind = client.post("/api/v1/kinds", json={"name": "Quittung", "vault_id": mine}).json()["id"]
    there = client.post("/api/v1/kinds", json={"name": "Quittung", "vault_id": household}).json()["id"]
    set_keep(client, own_kind, 2)
    set_keep(client, there, 5)
    assert client.patch(f"/api/v1/documents/{doc}", json={"kind_id": own_kind}).status_code == 200
    assert keep_of(doc) == (date(2026, 12, 31), False)
    assert client.post(f"/api/v1/documents/{doc}/move", json={"vault_id": household}).status_code == 200
    assert document(doc).kind_id == there
    assert keep_of(doc) == (date(2029, 12, 31), False)
    # No kind: no time.
    assert client.patch(f"/api/v1/documents/{doc}", json={"kind_id": None}).status_code == 200
    assert keep_of(doc) is None


def test_set_by_hand_stays_until_it_is_taken_back(client: TestClient, operator: Account) -> None:
    mine = own_vault(operator)
    invoice, contract = kind_id(client, "invoice"), kind_id(client, "contract")
    set_keep(client, invoice, 10)
    doc = add_document(mine, operator, "Strom", kind_id=invoice, date=date(2026, 3, 14), content=None)
    # The worked-out date sent back as it is (a page that sends all terms) stays worked out.
    same = client.patch(f"/api/v1/documents/{doc}", json={"dates": [{"kind": "keep_until", "date": "2036-12-31"}]})
    assert same.status_code == 200 and keep_of(doc) == (date(2036, 12, 31), False)
    # Another date is set by hand.
    hand = client.patch(f"/api/v1/documents/{doc}", json={"dates": [{"kind": "keep_until", "date": "2040-06-30"}]})
    assert hand.status_code == 200
    assert keep_of(doc) == (date(2040, 6, 30), True)
    assert keep_entry(client, doc) == {"kind": "keep_until", "date": "2040-06-30", "manual": True}
    # Neither the kind, nor the date, nor a new time of the kind touches it.
    client.patch(f"/api/v1/documents/{doc}", json={"kind_id": contract, "date": "2025-01-01"})
    set_keep(client, contract, 3)
    assert keep_of(doc) == (date(2040, 6, 30), True)
    # Taking the time away keeps what a person set, too.
    set_keep(client, contract, None)
    assert keep_of(doc) == (date(2040, 6, 30), True)
    # "Wieder aus der Art rechnen": left out of the terms, it is worked out again.
    set_keep(client, contract, 3)
    back = client.patch(f"/api/v1/documents/{doc}", json={"dates": []})
    assert back.status_code == 200
    assert keep_of(doc) == (date(2028, 12, 31), False)
    # Said outright: by hand with the date it has, or from the kind whatever date is sent.
    client.patch(f"/api/v1/documents/{doc}", json={"dates": [{"kind": "keep_until", "date": "2028-12-31",
                                                              "manual": True}]})
    assert keep_of(doc) == (date(2028, 12, 31), True)
    client.patch(f"/api/v1/documents/{doc}", json={"dates": [{"kind": "keep_until", "date": "2099-01-01",
                                                              "manual": False}]})
    assert keep_of(doc) == (date(2028, 12, 31), False)


def test_the_single_terms_of_the_patch_follow_the_same_rules(client: TestClient, operator: Account) -> None:
    """``set_dates`` and ``remove_dates`` (what the web app sends: only the terms that changed) set it by hand, keep the
    worked-out one when the day comes back unchanged, and give it back to the kind."""
    mine = own_vault(operator)
    invoice, contract = kind_id(client, "invoice"), kind_id(client, "contract")
    set_keep(client, invoice, 10)
    set_keep(client, contract, 3)
    doc = add_document(mine, operator, "Strom", kind_id=invoice, date=date(2026, 3, 14), content=None)
    assert keep_of(doc) == (date(2036, 12, 31), False)

    def patch(**body: Any) -> None:
        answer = client.patch(f"/api/v1/documents/{doc}", json=body)
        assert answer.status_code == 200, answer.text

    # Another term only: the worked-out date is left alone, and the term it names is added.
    patch(set_dates=[{"kind": "due", "date": "2026-11-01"}])
    assert keep_of(doc) == (date(2036, 12, 31), False)
    # The same day back is still the worked-out one.
    patch(set_dates=[{"kind": "keep_until", "date": "2036-12-31"}])
    assert keep_of(doc) == (date(2036, 12, 31), False)
    # Another day is set by hand; a new kind, date or time of the kind leaves it.
    patch(set_dates=[{"kind": "keep_until", "date": "2040-06-30"}])
    assert keep_of(doc) == (date(2040, 6, 30), True)
    patch(kind_id=contract, date="2025-01-01")
    set_keep(client, contract, 5)
    assert keep_of(doc) == (date(2040, 6, 30), True)
    # Given back to the kind without a day (or with the word): it is worked out again, from the year of the date.
    patch(set_dates=[{"kind": "keep_until", "manual": False}])
    assert keep_of(doc) == (date(2030, 12, 31), False)
    # By hand with the day it has: no day needed.
    patch(set_dates=[{"kind": "keep_until", "manual": True}])
    assert keep_of(doc) == (date(2030, 12, 31), True)
    # Taken away (a term set by hand): the kind works it out again; one worked out is not one to take away.
    patch(remove_dates=["keep_until"])
    assert keep_of(doc) == (date(2030, 12, 31), False)
    with SessionLocal() as db:
        before = db.scalar(select(Event.id).where(Event.document_id == doc).order_by(Event.id.desc()))
    patch(remove_dates=["keep_until"])
    assert keep_of(doc) == (date(2030, 12, 31), False)
    with SessionLocal() as db:
        assert db.scalar(select(Event.id).where(Event.document_id == doc).order_by(Event.id.desc())) == before
    # A kind without a time: by hand stays, taking it away leaves nothing.
    set_keep(client, contract, None, existing=False)
    patch(set_dates=[{"kind": "keep_until", "date": "2041-01-01"}])
    assert keep_of(doc) == (date(2041, 1, 1), True)
    patch(remove_dates=["keep_until"])
    assert keep_of(doc) is None
    # No day for a term that is not there is refused, and says which one.
    refused = client.patch(f"/api/v1/documents/{doc}", json={"set_dates": [{"kind": "keep_until", "manual": True}]})
    assert refused.status_code == 422 and refused.json()["detail"]["field"] == "set_dates[0]"


def test_a_kind_without_time_takes_only_the_worked_out_ones_away(client: TestClient, operator: Account) -> None:
    mine = own_vault(operator)
    invoice = kind_id(client, "invoice")
    set_keep(client, invoice, 10)
    worked = add_document(mine, operator, "A", kind_id=invoice, date=date(2026, 3, 14), content=None)
    hand = add_document(mine, operator, "B", kind_id=invoice, date=date(2026, 3, 14), content=None,
                        dates=[("keep_until", date(2030, 1, 1))])
    assert keep_of(hand) == (date(2030, 1, 1), True)
    asked = client.post(f"/api/v1/kinds/{invoice}/keeping/preview", json={"years": None})
    assert asked.json() == {"documents": 2, "by_hand": 1, "expired": 0}
    done = set_keep(client, invoice, None, existing=True)
    assert done["changed"] == 1
    assert keep_of(worked) is None
    assert keep_of(hand) == (date(2030, 1, 1), True)


def test_taking_a_time_away_for_new_ones_only_leaves_the_dates_as_set_by_hand(client: TestClient,
                                                                             operator: Account) -> None:
    mine = own_vault(operator)
    invoice = kind_id(client, "invoice")
    set_keep(client, invoice, 10)
    worked = add_document(mine, operator, "A", kind_id=invoice, date=date(2026, 3, 14), content=None)
    before = document(worked).change_seq
    done = set_keep(client, invoice, None, existing=False)
    assert (done["changed"], done["kind"]["keep_years"]) == (1, None)
    assert keep_of(worked) == (date(2036, 12, 31), True)
    assert document(worked).change_seq > before
    # A new one gets no date, and a change of the old one leaves its date.
    new = add_document(mine, operator, "B", kind_id=invoice, date=date(2026, 3, 14), content=None)
    assert keep_of(new) is None
    client.patch(f"/api/v1/documents/{worked}", json={"date": "2020-01-01"})
    assert keep_of(worked) == (date(2036, 12, 31), True)


def test_merging_into_a_kind_with_a_time_works_it_out_and_into_one_without_keeps_the_date(
        client: TestClient, operator: Account) -> None:
    mine = own_vault(operator)
    kept = client.post("/api/v1/kinds", json={"name": "Beleg", "vault_id": mine}).json()["id"]
    other = client.post("/api/v1/kinds", json={"name": "Quittung", "vault_id": mine}).json()["id"]
    plain = client.post("/api/v1/kinds", json={"name": "Zettel", "vault_id": mine}).json()["id"]
    set_keep(client, kept, 6)
    set_keep(client, other, 2)
    doc = add_document(mine, operator, "A", kind_id=kept, date=date(2026, 3, 14), content=None)
    assert keep_of(doc) == (date(2032, 12, 31), False)
    assert client.post(f"/api/v1/kinds/{kept}/merge", json={"into": other}).status_code == 200
    assert keep_of(doc) == (date(2028, 12, 31), False)
    assert client.post(f"/api/v1/kinds/{other}/merge", json={"into": plain}).status_code == 200
    assert keep_of(doc) == (date(2028, 12, 31), True)


def test_deleting_a_kind_never_takes_its_times_away(client: TestClient, operator: Account) -> None:
    editor = make_account("editor")
    household = shared_vault("Haushalt", operator, (editor, "edit"))
    kind = client.post("/api/v1/kinds", json={"name": "Beleg", "vault_id": household}).json()["id"]
    set_keep(client, kind, 6)
    worked = add_document(household, operator, "A", kind_id=kind, date=date(2026, 3, 14), content=None)
    hand = add_document(household, operator, "B", kind_id=kind, date=date(2026, 3, 14), content=None,
                        dates=[("keep_until", date(2040, 1, 1))])
    # The editor may not set the time, and deleting the kind (which they may, with force) does not take it away.
    with new_client(editor) as session:
        assert session.put(f"/api/v1/kinds/{kind}/keeping", json={"years": None, "existing": True}).status_code == 403
        assert session.delete(f"/api/v1/kinds/{kind}").status_code == 409
        assert session.delete(f"/api/v1/kinds/{kind}", params={"force": "true"}).status_code == 204
    assert document(worked).kind_id is None
    assert keep_of(worked) == (date(2032, 12, 31), True)
    assert keep_of(hand) == (date(2040, 1, 1), True)


def test_a_document_in_the_inbox_gets_it_and_filing_keeps_it(client: TestClient, operator: Account) -> None:
    mine = own_vault(operator)
    invoice = kind_id(client, "invoice")
    set_keep(client, invoice, 2)
    doc = add_document(mine, operator, "Neu", status="inbox", content=None)
    assert keep_of(doc) is None
    filed = client.patch(f"/api/v1/documents/{doc}", json={"kind_id": invoice, "status": "filed", "date": "2026-02-01"})
    assert filed.status_code == 200
    assert keep_of(doc) == (date(2028, 12, 31), False)
    # Many at once from the inbox, with a kind for all of them.
    other = add_document(mine, operator, "Neu 2", status="inbox", date=date(2025, 1, 1), content=None)
    assert client.post("/api/v1/inbox/file", json={"ids": [other], "kind_id": invoice}).json()["filed"] == [other]
    assert keep_of(other) == (date(2027, 12, 31), False)


# --- The question before setting it ---------------------------------------------------------------------------------


def test_the_question_counts_only_what_the_person_may_see(client: TestClient, operator: Account) -> None:
    invoice = kind_id(client, "invoice")
    mine = own_vault(operator)
    lea = make_account("lea")
    leas = own_vault(lea)
    add_document(mine, operator, "Alt", kind_id=invoice, date=date(2015, 1, 1), content=None)
    add_document(mine, operator, "Neu", kind_id=invoice, date=date(2026, 1, 1), content=None)
    add_document(mine, operator, "Hand", kind_id=invoice, date=date(2010, 1, 1), content=None,
                 dates=[("keep_until", date(2040, 1, 1))])
    add_document(mine, operator, "Wird gelesen", kind_id=invoice, status="processing", content=None)
    gone = add_document(mine, operator, "Weg", kind_id=invoice, date=date(2010, 1, 1), content=None)
    assert client.delete(f"/api/v1/documents/{gone}").status_code == 200
    # Lea's own: not seen by the operator, not counted, but changed all the same (the kind is the whole server's).
    hers = add_document(leas, lea, "Ihres", kind_id=invoice, date=date(2001, 1, 1), content=None)
    asked = client.post(f"/api/v1/kinds/{invoice}/keeping/preview", json={"years": 10})
    assert asked.status_code == 200, asked.text
    # 2015 + 10 < 2026: over; 2026 + 10: not; the one set by hand keeps it and is not counted as over.
    assert asked.json() == {"documents": 3, "by_hand": 1, "expired": 1}
    assert client.post(f"/api/v1/kinds/{invoice}/keeping/preview", json={"years": 1}).json()["expired"] == 1
    assert client.post(f"/api/v1/kinds/{invoice}/keeping/preview", json={"years": 31}).status_code == 422
    assert client.post(f"/api/v1/kinds/{invoice}/keeping/preview", json={"years": 0}).status_code == 422
    # Nothing changed by asking.
    assert keep_of(hers) is None
    set_keep(client, invoice, 10)
    assert keep_of(hers) == (date(2011, 12, 31), False)


def test_many_documents_are_worked_out_in_the_background(client: TestClient, operator: Account,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keeping, "AT_ONCE", 2)
    monkeypatch.setattr(keeping, "BATCH", 2)
    mine = own_vault(operator)
    invoice = kind_id(client, "invoice")
    ids = [add_document(mine, operator, f"D{i}", kind_id=invoice, date=date(2020 + i, 1, 1), content=None)
           for i in range(5)]
    done = set_keep(client, invoice, 3)
    assert (done["changed"], done["queued"]) == (0, True)
    assert all(keep_of(i) is None for i in ids)
    # Asked twice: one job waits.
    set_keep(client, invoice, 3)
    with SessionLocal() as db:
        assert len(db.scalars(select(Job).where(Job.kind == jobs.KEEP, Job.state == "queued")).all()) == 1
    jobs.run_pending(kinds=(jobs.KEEP,))
    assert [keep_of(i) for i in ids] == [(date(2023 + i, 12, 31), False) for i in range(5)]
    with SessionLocal() as db:
        lines = db.scalars(select(Event).where(Event.document_id.in_(ids), Event.action == "changed")).all()
        assert len(lines) == 5 and all(e.user_id == operator.id for e in lines)
    # Run again: nothing more to do, no more lines.
    with SessionLocal() as db:
        jobs.enqueue(db, jobs.KEEP, invoice, {"by": operator.id})
        db.commit()
    jobs.run_pending(kinds=(jobs.KEEP,))
    with SessionLocal() as db:
        assert len(db.scalars(select(Event).where(Event.document_id.in_(ids), Event.action == "changed")).all()) == 5


# --- Who sets it ------------------------------------------------------------------------------------------------------


def test_the_servers_kinds_are_the_operators(client: TestClient, operator: Account) -> None:
    invoice = kind_id(client, "invoice")
    member = make_account("jule")
    with new_client(member) as jule:
        assert jule.put(f"/api/v1/kinds/{invoice}/keeping", json={"years": 2}).status_code == 403
        assert jule.post(f"/api/v1/kinds/{invoice}/keeping/preview", json={"years": 2}).status_code == 403
    # The operator, but through a device: only a browser.
    token = device_token(client)
    with TestClient(client.app, base_url="http://testserver") as device:
        headers = {"Authorization": f"Bearer {token}"}
        assert device.put(f"/api/v1/kinds/{invoice}/keeping", json={"years": 2}, headers=headers).status_code == 403
    assert set_keep(client, invoice, 2)["kind"]["keep_years"] == 2


def test_a_vaults_kinds_need_manage_there(client: TestClient, operator: Account) -> None:
    editor, reader, stranger = make_account("editor"), make_account("reader"), make_account("stranger")
    vault = shared_vault("Haushalt", operator, (editor, "edit"), (reader, "read"))
    kind = client.post("/api/v1/kinds", json={"name": "Beleg", "vault_id": vault}).json()["id"]
    body = {"years": 6, "existing": True}
    with new_client(stranger) as session:
        assert session.put(f"/api/v1/kinds/{kind}/keeping", json=body).status_code == 404
        assert session.post(f"/api/v1/kinds/{kind}/keeping/preview", json={"years": 6}).status_code == 404
    for who in (reader, editor):
        with new_client(who) as session:
            assert session.put(f"/api/v1/kinds/{kind}/keeping", json=body).status_code == 403
            assert session.post(f"/api/v1/kinds/{kind}/keeping/preview", json={"years": 6}).status_code == 403
    # A manager, also from a device; a key never.
    manager = make_account("manager")
    with SessionLocal() as db:
        from app.services import vaults

        vaults.set_member(db, operator.id, vault, manager.id, "manage")
    with new_client(manager) as session:
        token = device_token(session)
    with TestClient(client.app, base_url="http://testserver") as program:
        for secret in (upload_key(manager, "read"), upload_key(manager, "upload")):
            headers = {"Authorization": f"Bearer {secret}"}
            assert program.put(f"/api/v1/kinds/{kind}/keeping", json=body, headers=headers).status_code in (401, 403)
            assert program.post(f"/api/v1/kinds/{kind}/keeping/preview", json={"years": 6},
                                headers=headers).status_code in (401, 403)
        answer = program.put(f"/api/v1/kinds/{kind}/keeping", json=body, headers={"Authorization": f"Bearer {token}"})
        assert answer.status_code == 200 and answer.json()["kind"]["keep_years"] == 6
    assert client.put(f"/api/v1/kinds/{2**31 - 1}/keeping", json=body).status_code == 404
    assert client.put(f"/api/v1/kinds/{kind}/keeping", json={"years": 31}).status_code == 422
    assert client.put(f"/api/v1/kinds/{kind}/keeping", json={"years": "6"}).status_code == 422


# --- May go -----------------------------------------------------------------------------------------------------------


def may_go(session: TestClient, **params: Any) -> dict[str, Any]:
    answer = session.get("/api/v1/keeping", params=params)
    assert answer.status_code == 200, answer.text
    return answer.json()  # type: ignore[no-any-return]


def test_may_go_lists_what_is_over_where_the_person_may_change_things(client: TestClient, operator: Account) -> None:
    reader, lea = make_account("reader"), make_account("lea")
    mine = own_vault(operator)
    household = shared_vault("Haushalt", operator, (reader, "read"))
    over = date(2024, 12, 31)
    older = add_document(mine, operator, "Kontoauszüge", dates=[("keep_until", date(2023, 12, 31))], content=None)
    first = add_document(household, operator, "Dachrinne", date=date(2022, 5, 10), dates=[("keep_until", over)],
                         content=None)
    add_document(mine, operator, "Läuft noch", dates=[("keep_until", date(2026, 10, 14))], content=None)
    add_document(mine, operator, "Im Eingang", status="inbox", dates=[("keep_until", over)], content=None)
    gone = add_document(mine, operator, "Im Papierkorb", dates=[("keep_until", over)], content=None)
    client.delete(f"/api/v1/documents/{gone}")
    add_document(mine, operator, "Ohne Frist", content=None)
    leas = add_document(own_vault(lea), lea, "Leas", dates=[("keep_until", over)], content=None)
    page = may_go(client)
    assert page["total"] == 2
    assert [d["id"] for d in page["items"]] == [older, first]
    assert may_go(client, vault_id=household)["total"] == 1
    assert may_go(client, limit=1)["items"][0]["id"] == older
    assert may_go(client, offset=1)["items"][0]["id"] == first
    with SessionLocal() as db:
        assert keeping.may_go_count(db, operator.id) == 2
    # Only reading in the vault: nothing to clear out there.
    with new_client(reader) as session:
        assert may_go(session) == {"items": [], "total": 0}
        assert may_go(session, vault_id=household)["total"] == 0
    # Shared on its own, even with edit: not a place to clear out.
    with new_client(lea) as session:
        assert session.put(f"/api/v1/documents/{leas}/shares/{operator.id}", json={"right": "edit"}).status_code == 200
    assert may_go(client)["total"] == 2
    with SessionLocal() as db:
        assert keeping.may_go_count(db, reader.id) == 0
        assert keeping.may_go_count(db, lea.id) == 1


def test_may_go_from_a_device_and_with_a_key(client: TestClient, operator: Account) -> None:
    add_document(own_vault(operator), operator, "Alt", dates=[("keep_until", date(2020, 12, 31))], content=None)
    token = device_token(client)
    with TestClient(client.app, base_url="http://testserver") as program:
        assert program.get("/api/v1/keeping", headers={"Authorization": f"Bearer {token}"}).json()["total"] == 1
        read = program.get("/api/v1/keeping", headers={"Authorization": f"Bearer {upload_key(operator, 'read')}"})
        assert read.status_code == 200 and read.json()["total"] == 1
        upload = program.get("/api/v1/keeping", headers={"Authorization": f"Bearer {upload_key(operator)}"})
        assert upload.status_code == 403
    with TestClient(client.app, base_url="http://testserver") as nobody:
        assert nobody.get("/api/v1/keeping").status_code == 401


def test_many_documents_into_the_trash_each_checked_on_its_own(client: TestClient, operator: Account) -> None:
    reader, lea = make_account("reader"), make_account("lea")
    household = shared_vault("Haushalt", operator, (reader, "read"))
    mine = add_document(own_vault(operator), operator, "Mein", content=None)
    ours = add_document(household, operator, "Unser", content=None)
    leas = add_document(own_vault(lea), lea, "Leas", content=None)
    with new_client(reader) as session:
        answer = session.post("/api/v1/documents/trash", json={"ids": [ours, mine]}).json()
        assert answer == {"trashed": [], "failed": [{"id": ours, "code": "forbidden"}, {"id": mine, "code": "not_found"}]}
    answer = client.post("/api/v1/documents/trash", json={"ids": [mine, ours, leas, mine, 0]}).json()
    assert answer["trashed"] == [mine, ours]
    assert answer["failed"] == [{"id": leas, "code": "not_found"}, {"id": 0, "code": "not_found"}]
    assert document(mine).status == "trash" and document(ours).status == "trash" and document(leas).status == "filed"
    assert client.post("/api/v1/documents/trash", json={"ids": []}).status_code == 422
    assert client.post("/api/v1/documents/trash", json={"ids": list(range(1, 502))}).status_code == 422
    with TestClient(client.app, base_url="http://testserver") as program:
        key = upload_key(operator, "read")
        refused = program.post("/api/v1/documents/trash", json={"ids": [mine]}, headers={"Authorization": f"Bearer {key}"})
        assert refused.status_code in (401, 403)


# --- The search, the export, the schema -------------------------------------------------------------------------------


def test_the_search_finds_what_may_go(client: TestClient, operator: Account) -> None:
    mine = own_vault(operator)
    over = add_document(mine, operator, "Alt", dates=[("keep_until", date(2025, 12, 31))], content=None)
    running = add_document(mine, operator, "Neu", dates=[("keep_until", date(2026, 10, 14))], content=None)
    add_document(mine, operator, "Ohne", content=None)

    def found(q: str) -> list[int]:
        answer = client.get("/api/v1/search", params={"q": q})
        assert answer.status_code == 200, answer.text
        return sorted(item["document"]["id"] for item in answer.json()["items"])

    assert found("aufbewahren:abgelaufen") == [over]
    assert found("keep:expired") == [over]
    assert found("aufbewahren:läuft") == [running]
    assert found("keep:running") == [running]
    assert found("aufbewahren:irgendwann") == []


def test_the_list_of_the_export_names_until_when_to_keep(client: TestClient, operator: Account) -> None:
    from app.services import exports

    rows = [("2026-03-14", "Strom", "", "", "84,00", "EUR", "", "jule", "a.pdf", "2036-12-31")]
    text = exports._csv(rows, "de").decode("utf-8-sig")
    table = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert table[0][-1] == "Aufbewahren bis" and table[1][-1] == "2036-12-31"
    assert exports.CSV_HEADINGS["en"][-1] == "Keep until"


def test_the_list_of_a_packed_export_has_the_date_of_each(client: TestClient, operator: Account) -> None:
    import shutil
    import zipfile

    from .conftest import DATA_DIR

    shutil.rmtree(f"{DATA_DIR}/exports", ignore_errors=True)
    mine = own_vault(operator)
    invoice = kind_id(client, "invoice")
    set_keep(client, invoice, 10)
    add_document(mine, operator, "Strom", kind_id=invoice, date=date(2026, 3, 14), amount=8400)
    add_document(mine, operator, "Brief", date=date(2026, 4, 1), dates=[("keep_until", date(2040, 1, 1))])
    add_document(mine, operator, "Ohne", date=date(2026, 5, 1))
    made = client.post("/api/v1/exports", headers={"X-Nexpaper-Language": "de"}, json={
        "date_from": "2026-01-01", "date_to": "2026-12-31", "vault_ids": [mine],
        "content": {"pdf": True, "original": False, "csv": True, "xml": False}})
    assert made.status_code == 201, made.text
    jobs.run_pending(kinds=(jobs.EXPORT,))
    answer = client.get(f"/api/v1/exports/{made.json()['id']}/file")
    assert answer.status_code == 200, answer.text
    listing = zipfile.ZipFile(io.BytesIO(answer.content)).read("liste.csv").decode("utf-8-sig")
    rows = {row[1]: row[-1] for row in csv.reader(io.StringIO(listing), delimiter=";")}
    assert rows == {"Titel": "Aufbewahren bis", "Strom": "2036-12-31", "Brief": "2040-01-01", "Ohne": ""}


def _old_database(tmp_path: Any, monkeypatch: Any, version: int) -> Any:
    """A database as schema ``version`` made it (the recorded schema), with a kind, a vault and a document that has a
    keep_until, a due date and (from 11 on) a contract; the start has brought it up when this returns."""
    import sqlite3
    from contextlib import closing
    from pathlib import Path

    from sqlalchemy import create_engine

    from app import db as database
    from app.services import backups

    path = tmp_path / "nexpaper.db"
    records = Path(__file__).parent / "schema"
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript((records / f"v{version}.sql").read_text(encoding="utf-8"))
        connection.execute(f"PRAGMA user_version = {version}")
        connection.execute("INSERT INTO kinds (id, key, name, name_key, hue, position) VALUES (1, 'x', 'X', 'x', 0, 0)")
        connection.execute("INSERT INTO vaults (id, name, icon, folder, created_at) VALUES (1, 'V', 'folder', 'v', "
                           "'2026-01-01 00:00:00')")
        connection.execute(
            "INSERT INTO documents (id, vault_id, title, status, source, added_at, pages, current_version, "
            "change_seq, currency, trashed_status, duplicate_kind, process_error, files_state) "
            "VALUES (1, 1, 'T', 'filed', 'upload', '2026-01-01 00:00:00', 0, 1, 1, 'EUR', '', '', '', '')")
        connection.execute("INSERT INTO document_dates (id, document_id, kind, date) VALUES (1, 1, 'keep_until', "
                           "'2030-12-31'), (2, 1, 'due', '2026-02-01'), (3, 1, 'contract_end', '2027-06-30')")
        connection.commit()
    engine = create_engine(f"sqlite:///{path}")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(backups, "create", lambda **_kwargs: path)
    try:
        database.init_db()
    finally:
        engine.dispose()
    return path


def _brought_up(path: Any, anchors: list[tuple[Any]]) -> None:
    import sqlite3
    from contextlib import closing

    from app import db as database

    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
        # What a person set before keeping existed counts as set by hand; nothing else does.
        assert connection.execute("SELECT kind, manual FROM document_dates ORDER BY id").fetchall() == [
            ("keep_until", 1), ("due", 0), ("contract_end", 0)]
        assert connection.execute("SELECT keep_years, keep_new_only FROM kinds").fetchall() == [(None, 0)]
        # The step of the deadlines is there as well (from 10 a contract counts its terms from the end it has).
        assert connection.execute("SELECT renew_anchor FROM document_dates ORDER BY id").fetchall() == anchors
        assert connection.execute("SELECT count(*) FROM deadline_snoozes").fetchone() == (0,)
        # And the one after it, the reminders (a database of today is brought up in the one start).
        assert connection.execute("SELECT count(*) FROM reminder_settings").fetchone() == (0,)


def test_a_database_before_keeping_is_brought_up_and_its_terms_count_as_set_by_hand(tmp_path: Any,
                                                                                    monkeypatch: Any) -> None:
    """One start from schema 10 (the release before 1.4) runs the step of the deadlines and the one of keeping."""
    _brought_up(_old_database(tmp_path, monkeypatch, 10), [(None,), (None,), ("2027-06-30",)])


def test_a_database_with_the_deadlines_only_gets_the_step_of_keeping(tmp_path: Any, monkeypatch: Any) -> None:
    """Schema 11 (the deadlines, without keeping) needs the one step after it, and the deadlines stay as they were."""
    _brought_up(_old_database(tmp_path, monkeypatch, 11), [(None,), (None,), (None,)])


def test_what_may_go_is_no_deadline_and_no_number_at_the_menu(client: TestClient, operator: Account) -> None:
    """A keeping time that is over is on its own page filter: the deadlines, the number at the menu and the search of
    deadlines do not know it."""
    mine = own_vault(operator)
    invoice = kind_id(client, "invoice")
    set_keep(client, invoice, 1)
    doc = add_document(mine, operator, "Alt", kind_id=invoice, date=date(2020, 5, 1), content=None)
    assert keep_of(doc) == (date(2021, 12, 31), False)
    assert [item["id"] for item in may_go(client)["items"]] == [doc]
    assert client.get("/api/v1/deadlines").json()["counts"] == {}
    counts = client.get("/api/v1/counts").json()
    assert counts["deadlines"] == 0 and counts["deadlines_overdue"] == 0
    for word in ("offen", "überfällig", "erledigt", "<30"):
        found = client.get("/api/v1/search", params={"q": f"frist:{word}"}).json()
        assert found["total"] == 0, word


def test_a_backup_keeps_the_times_and_the_marks(client: TestClient, operator: Account, tmp_path: Any) -> None:
    import sqlite3
    import zipfile
    from contextlib import closing

    from app.services import backups

    invoice = kind_id(client, "invoice")
    set_keep(client, invoice, 10)
    doc = add_document(own_vault(operator), operator, "Strom", kind_id=invoice, date=date(2026, 3, 14), content=None,
                       dates=[("keep_until", date(2040, 1, 1))])
    made = backups.create(note="test")
    with zipfile.ZipFile(made) as archive:
        (tmp_path / "copy.db").write_bytes(archive.read(backups.DATABASE_ENTRY))
    with closing(sqlite3.connect(tmp_path / "copy.db")) as connection:
        assert connection.execute("SELECT keep_years FROM kinds WHERE id = ?", (invoice,)).fetchone() == (10,)
        assert connection.execute("SELECT date, manual FROM document_dates WHERE document_id = ? AND kind = "
                                  "'keep_until'", (doc,)).fetchone() == ("2040-01-01", 1)
    # The trial run of a restore takes it.
    assert backups.check(made.name).database_ok


def test_a_document_that_was_just_read_gets_the_time_of_its_kind(client: TestClient, operator: Account) -> None:
    from app.models import Document

    from . import files
    from .intake import process_all, upload_one

    invoice = kind_id(client, "invoice")
    set_keep(client, invoice, 6)
    made = upload_one(client, "Strom.pdf", files.make_pdf(["Seite eins mit genug Text, um als Text zu gelten"]))
    with SessionLocal() as db:
        row = db.get(Document, made["id"])
        assert row is not None and row.status == "processing"
        # As a rule or the import would have set them while it is being read.
        row.kind_id, row.date = invoice, date(2025, 4, 1)
        db.commit()
    assert keep_of(made["id"]) is None, "nothing is worked out while it is being read"
    process_all()
    assert document(made["id"]).status == "inbox"
    assert keep_of(made["id"]) == (date(2031, 12, 31), False)


# --- After the review -------------------------------------------------------------------------------------------------


def test_the_answers_count_only_what_the_person_may_see_but_every_document_changes(client: TestClient,
                                                                                   operator: Account) -> None:
    invoice = kind_id(client, "invoice")
    lea = make_account("lea")
    leas = [add_document(own_vault(lea), lea, f"Leas {i}", kind_id=invoice, date=date(2010, 1, 1), content=None)
            for i in range(3)]
    mine = add_document(own_vault(operator), operator, "Mein", kind_id=invoice, date=date(2026, 1, 1), content=None)
    asked = client.post(f"/api/v1/kinds/{invoice}/keeping/preview", json={"years": 10}).json()
    assert asked == {"documents": 1, "by_hand": 0, "expired": 0}
    done = set_keep(client, invoice, 10)
    assert (done["changed"], done["queued"]) == (1, False), "the personal vault of Lea is not told by the number"
    assert keep_of(mine) == (date(2036, 12, 31), False)
    assert all(keep_of(i) == (date(2020, 12, 31), False) for i in leas), "her documents are changed all the same"
    done = set_keep(client, invoice, None)
    assert (done["changed"], done["queued"]) == (1, False)
    assert all(keep_of(i) is None for i in leas)


def test_the_background_starts_above_the_limit_seen_and_unseen_ones_go_there_quietly(
        client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keeping, "AT_ONCE", 3)
    invoice = kind_id(client, "invoice")
    lea = make_account("lea")
    mine = own_vault(operator)
    seen = [add_document(mine, operator, f"D{i}", kind_id=invoice, date=date(2026, 1, 1), content=None)
            for i in range(3)]
    # Three the caller sees: done at once.
    done = set_keep(client, invoice, 2)
    assert (done["changed"], done["queued"]) == (3, False)
    # And two of Lea on top: still three seen, done at once; hers in the background, without a word in the answer.
    leas = [add_document(own_vault(lea), lea, f"L{i}", kind_id=invoice, date=date(2026, 1, 1), content=None)
            for i in range(2)]
    done = set_keep(client, invoice, 5)
    assert (done["changed"], done["queued"]) == (3, False)
    assert all(keep_of(i) == (date(2031, 12, 31), False) for i in seen)
    jobs.run_pending(kinds=(jobs.KEEP,))
    assert all(keep_of(i) == (date(2031, 12, 31), False) for i in leas)
    # Four seen: the background.
    seen.append(add_document(mine, operator, "D3", kind_id=invoice, date=date(2026, 1, 1), content=None))
    done = set_keep(client, invoice, 8)
    assert (done["changed"], done["queued"]) == (0, True)
    jobs.run_pending(kinds=(jobs.KEEP,))
    assert all(keep_of(i) == (date(2034, 12, 31), False) for i in seen + leas)


def test_a_waiting_job_does_what_was_decided_last(client: TestClient, operator: Account,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keeping, "AT_ONCE", 2)
    invoice = kind_id(client, "invoice")
    mine = own_vault(operator)
    ids = [add_document(mine, operator, f"D{i}", kind_id=invoice, date=date(2026, 1, 1), content=None)
           for i in range(4)]
    assert set_keep(client, invoice, 3)["queued"] is True
    # Then "only for new ones" with another number: the documents there keep what they had (none), the job goes.
    assert set_keep(client, invoice, 8, existing=False)["changed"] == 0
    with SessionLocal() as db:
        assert db.scalars(select(Job).where(Job.kind == jobs.KEEP, Job.state == "queued")).all() == []
        # A job that still turns up (left from before) reads the decision and does nothing.
        jobs.enqueue(db, jobs.KEEP, invoice, {"by": operator.id})
        db.commit()
    jobs.run_pending(kinds=(jobs.KEEP,))
    assert all(keep_of(i) is None for i in ids)
    # "For all" again, twice: one job, the newest decision.
    assert set_keep(client, invoice, 8)["queued"] is True
    assert set_keep(client, invoice, 6)["queued"] is True
    with SessionLocal() as db:
        assert len(db.scalars(select(Job).where(Job.kind == jobs.KEEP, Job.state == "queued")).all()) == 1
    jobs.run_pending(kinds=(jobs.KEEP,))
    assert all(keep_of(i) == (date(2032, 12, 31), False) for i in ids)


def test_moving_takes_the_time_of_the_kind_along_or_the_one_the_other_vault_has(client: TestClient,
                                                                               operator: Account) -> None:
    mine = own_vault(operator)
    household = shared_vault("Haushalt", operator)
    beleg = client.post("/api/v1/kinds", json={"name": "Beleg", "vault_id": mine}).json()["id"]
    set_keep(client, beleg, 4)
    doc = add_document(mine, operator, "A", kind_id=beleg, date=date(2026, 3, 14), content=None)
    assert keep_of(doc) == (date(2030, 12, 31), False)
    # The household has no "Beleg": it is made there with the same time.
    assert client.post(f"/api/v1/documents/{doc}/move", json={"vault_id": household}).status_code == 200
    made = client.get("/api/v1/kinds", params={"vault_id": household}).json()
    there = next(k for k in made if k["name"] == "Beleg")
    assert there["vault_id"] == household and there["keep_years"] == 4
    assert keep_of(doc) == (date(2030, 12, 31), False)
    # Back to the own vault, whose "Beleg" has another time now (2 years): that one counts; by hand stays by hand.
    set_keep(client, beleg, 2)
    hand = add_document(household, operator, "B", kind_id=there["id"], date=date(2026, 3, 14), content=None,
                        dates=[("keep_until", date(2040, 1, 1))])
    for document_id in (doc, hand):
        assert client.post(f"/api/v1/documents/{document_id}/move", json={"vault_id": mine}).status_code == 200
    assert document(doc).kind_id == beleg
    assert keep_of(doc) == (date(2028, 12, 31), False)
    assert keep_of(hand) == (date(2040, 1, 1), True)


def test_a_document_in_the_trash_is_worked_out_too_one_being_read_is_not(client: TestClient,
                                                                        operator: Account) -> None:
    invoice = kind_id(client, "invoice")
    doc = add_document(own_vault(operator), operator, "A", kind_id=invoice, date=date(2026, 3, 14), content=None)
    reading = add_document(own_vault(operator), operator, "Wird gelesen", kind_id=invoice, status="processing",
                           content=None)
    assert client.delete(f"/api/v1/documents/{doc}").status_code == 200
    set_keep(client, invoice, 10)
    assert keep_of(doc) == (date(2036, 12, 31), False)
    assert keep_of(reading) is None


def test_manual_is_said_only_on_keep_until(client: TestClient, operator: Account) -> None:
    doc = add_document(own_vault(operator), operator, "A", content=None,
                       dates=[("due", date(2026, 10, 20)), ("keep_until", date(2030, 1, 1))])
    shown = client.get(f"/api/v1/documents/{doc}").json()["dates"]
    assert [(d["kind"], d["date"], d.get("manual", "none")) for d in shown] == [
        ("due", "2026-10-20", "none"), ("keep_until", "2030-01-01", True)]


def test_may_go_is_ordered_by_when_the_time_ended_then_the_date_then_the_id(client: TestClient,
                                                                            operator: Account) -> None:
    mine = own_vault(operator)
    late = add_document(mine, operator, "Spaet", date=date(2020, 1, 1), dates=[("keep_until", date(2025, 6, 30))],
                        content=None)
    tie_b = add_document(mine, operator, "Gleich B", date=date(2019, 1, 1),
                         dates=[("keep_until", date(2024, 12, 31))], content=None)
    tie_a = add_document(mine, operator, "Gleich A", date=date(2018, 1, 1),
                         dates=[("keep_until", date(2024, 12, 31))], content=None)
    same = add_document(mine, operator, "Gleich 1", date=date(2018, 1, 1),
                        dates=[("keep_until", date(2024, 12, 31))], content=None)
    assert [d["id"] for d in may_go(client)["items"]] == [tie_a, same, tie_b, late]


def test_may_go_shows_an_editor_what_is_over_and_a_reader_nothing(client: TestClient, operator: Account) -> None:
    editor, reader = make_account("editor"), make_account("reader")
    household = shared_vault("Haushalt", operator, (editor, "edit"), (reader, "read"))
    doc = add_document(household, operator, "Alt", dates=[("keep_until", date(2020, 12, 31))], content=None)
    with new_client(editor) as session:
        assert [d["id"] for d in may_go(session)["items"]] == [doc]
        assert session.post("/api/v1/documents/trash", json={"ids": [doc]}).json()["trashed"] == [doc]
    assert client.post(f"/api/v1/documents/{doc}/restore").status_code == 200
    with new_client(reader) as session:
        assert may_go(session)["total"] == 0


def test_today_is_the_day_where_the_person_is(client: TestClient, operator: Account,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    add_document(own_vault(operator), operator, "Alt", dates=[("keep_until", date(2026, 12, 31))], content=None)
    # 31.12.2026 23:30 UTC: already 1 January in Auckland and in Berlin, still the 31st in New York.
    freeze(monkeypatch, datetime(2026, 12, 31, 23, 30, tzinfo=UTC))
    for zone, today, over in (("Pacific/Auckland", date(2027, 1, 1), 1), ("Europe/Berlin", date(2027, 1, 1), 1),
                              ("America/New_York", date(2026, 12, 31), 0)):
        with SessionLocal() as db:
            row = db.get(Account, operator.id)
            assert row is not None
            row.profile = {**(row.profile or {}), "timezone": zone}
            db.commit()
            assert keeping.today_of(row) == today, zone
            assert keeping.may_go_count(db, operator.id) == over, zone
            assert keeping.expired(db, operator.id, keeping.today_of(row))[1] == over, zone


def test_a_proposal_of_the_ai_in_the_inbox_brings_the_time_of_its_kind(client: TestClient, operator: Account,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    import httpx

    from app.services import ai

    from .files import make_pdf
    from .intake import upload_and_read
    from .test_ai import Model, set_up

    stand_in = Model()
    stand_in.text = json.dumps({"title": "Wartung Heizung", "sender": "Elektro Brandt GmbH", "kind": "Rechnung",
                                "date": "2025-10-06", "amount": 224.91})
    ai.transport = httpx.MockTransport(stand_in.handle)
    monkeypatch.setattr(ai, "resolver", lambda host, port: ["93.184.216.34"])
    try:
        set_up(client)
        set_keep(client, kind_id(client, "invoice"), 2)
        found = upload_and_read(client, "scan.pdf", make_pdf([
            "Elektro Brandt GmbH, Werkstrasse 3, 12345 Lindenau\nWartung der Heizung in der Ferienwohnung"]),
            shared_vault("Haushalt", operator))
    finally:
        ai.transport = None
    assert found["kind"]["key"] == "invoice" and found["suggest"]["kind"] == "ai"
    assert keep_of(found["id"]) == (date(2027, 12, 31), False)


def test_the_parts_of_a_split_keep_the_time_of_the_kind(client: TestClient, operator: Account) -> None:
    from .test_pagetools import made

    invoice = kind_id(client, "invoice")
    set_keep(client, invoice, 3)
    whole = made(client, "stapel.pdf", "Alpha", "Beta")
    changed = client.patch(f"/api/v1/documents/{whole['id']}", json={"kind_id": invoice, "date": "2026-02-01",
                                                                      "status": "filed"})
    assert changed.status_code == 200, changed.text
    answer = client.post(f"/api/v1/documents/{whole['id']}/split", json={
        "base_version": 1, "parts": [{"pages": [{"page": 1}]}, {"pages": [{"page": 2}]}]})
    assert answer.status_code == 201, answer.text
    assert [keep_of(p["id"]) for p in answer.json()["items"]] == [(date(2029, 12, 31), False)] * 2


# --- The archive's filter "may go" (D4) -------------------------------------------------------------------------------


def found_ids(session: TestClient, **params: Any) -> list[int]:
    answer = session.get("/api/v1/search", params={"q": "", "status": "filed", "limit": 100, **params})
    assert answer.status_code == 200, answer.text
    return sorted(item["document"]["id"] for item in answer.json()["items"])


def test_the_search_filter_keep_expired_is_the_list_of_may_go(client: TestClient, operator: Account) -> None:
    reader, lea = make_account("reader"), make_account("lea")
    mine = own_vault(operator)
    household = shared_vault("Haushalt", operator, (reader, "read"))
    over = date(2024, 12, 31)
    a = add_document(mine, operator, "Alt eins", dates=[("keep_until", over)], content=None)
    b = add_document(household, operator, "Alt zwei", dates=[("keep_until", date(2023, 12, 31))], content=None)
    add_document(mine, operator, "Läuft noch", dates=[("keep_until", date(2026, 10, 14))], content=None)
    add_document(mine, operator, "Im Eingang", status="inbox", dates=[("keep_until", over)], content=None)
    gone = add_document(mine, operator, "Im Papierkorb", dates=[("keep_until", over)], content=None)
    client.delete(f"/api/v1/documents/{gone}")
    add_document(mine, operator, "Ohne Frist", content=None)
    leas = add_document(own_vault(lea), lea, "Leas", dates=[("keep_until", over)], content=None)
    # Shared on its own, even with edit: not a place to clear out, so not "may go" either.
    with new_client(lea) as session:
        assert session.put(f"/api/v1/documents/{leas}/shares/{operator.id}", json={"right": "edit"}).status_code == 200
    assert found_ids(client, keep="expired") == [a, b]
    assert found_ids(client, keep="expired") == sorted(d["id"] for d in may_go(client)["items"])
    # With the other filters, the numbered pages and the order of the archive's table.
    assert found_ids(client, keep="expired", vault_id=household) == [b]
    assert found_ids(client, keep="expired", q="eins") == [a]
    page = client.get("/api/v1/search", params={"q": "", "status": "filed", "keep": "expired", "limit": 1, "page": 2,
                                                  "sort": "date"})
    assert page.status_code == 200 and page.json()["total"] == 2 and len(page.json()["items"]) == 1
    # Everything the person sees is the filter's "all", too: the filter only narrows.
    assert leas in found_ids(client) and leas not in found_ids(client, keep="expired")
    # Only reading in the vault: nothing to clear out there, though the person sees the document.
    with new_client(reader) as session:
        assert b in found_ids(session)
        assert found_ids(session, keep="expired") == []
    assert client.get("/api/v1/search", params={"keep": "running"}).status_code == 422


def test_the_search_filter_and_the_keyword_count_the_day_of_the_person(client: TestClient, operator: Account,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """A term is over on the day after its date, wherever the person is: late in the evening at the server it is already
    tomorrow in Auckland."""
    freeze(monkeypatch, datetime(2026, 10, 14, 20, 0, tzinfo=UTC))
    mine = own_vault(operator)
    doc = add_document(mine, operator, "Heute zu Ende", dates=[("keep_until", date(2026, 10, 14))], content=None)
    assert found_ids(client, keep="expired") == []
    assert client.get("/api/v1/search", params={"q": "aufbewahren:abgelaufen"}).json()["total"] == 0
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None
        row.profile = {"timezone": "Pacific/Auckland"}
        db.commit()
    assert found_ids(client, keep="expired") == [doc]
    assert client.get("/api/v1/search", params={"q": "aufbewahren:abgelaufen"}).json()["total"] == 1


def test_a_key_that_reads_filters_by_may_go_too_and_an_upload_key_does_not(client: TestClient, operator: Account) -> None:
    add_document(own_vault(operator), operator, "Alt", dates=[("keep_until", date(2020, 12, 31))], content=None)
    with TestClient(client.app, base_url="http://testserver") as program:
        read = program.get("/api/v1/search", params={"keep": "expired", "q": ""},
                           headers={"Authorization": f"Bearer {upload_key(operator, 'read')}"})
        assert read.status_code == 200 and read.json()["total"] == 1
        upload = program.get("/api/v1/search", params={"keep": "expired", "q": ""},
                             headers={"Authorization": f"Bearer {upload_key(operator)}"})
        assert upload.status_code == 403
