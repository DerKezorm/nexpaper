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
    shown = session.get(f"/api/v1/documents/{document_id}").json()
    return next((d for d in shown["dates"] if d["kind"] == "keep_until"), None)


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


def test_a_kind_without_time_takes_only_the_worked_out_ones_away(client: TestClient, operator: Account) -> None:
    mine = own_vault(operator)
    invoice = kind_id(client, "invoice")
    set_keep(client, invoice, 10)
    worked = add_document(mine, operator, "A", kind_id=invoice, date=date(2026, 3, 14), content=None)
    hand = add_document(mine, operator, "B", kind_id=invoice, date=date(2026, 3, 14), content=None,
                        dates=[("keep_until", date(2030, 1, 1))])
    assert keep_of(hand) == (date(2030, 1, 1), True)
    done = set_keep(client, invoice, None, existing=False)
    assert done["changed"] == 1, "taking the time away always reaches the documents there"
    assert keep_of(worked) is None
    assert keep_of(hand) == (date(2030, 1, 1), True)


def test_deleting_or_merging_a_kind_works_the_time_out_again(client: TestClient, operator: Account) -> None:
    mine = own_vault(operator)
    kept = client.post("/api/v1/kinds", json={"name": "Beleg", "vault_id": mine}).json()["id"]
    other = client.post("/api/v1/kinds", json={"name": "Quittung", "vault_id": mine}).json()["id"]
    set_keep(client, kept, 6)
    set_keep(client, other, 2)
    doc = add_document(mine, operator, "A", kind_id=kept, date=date(2026, 3, 14), content=None)
    assert keep_of(doc) == (date(2032, 12, 31), False)
    assert client.post(f"/api/v1/kinds/{kept}/merge", json={"into": other}).status_code == 200
    assert keep_of(doc) == (date(2028, 12, 31), False)
    assert client.delete(f"/api/v1/kinds/{other}").status_code == 204
    assert keep_of(doc) is None


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


def test_a_database_before_keeping_is_brought_up_and_its_terms_count_as_set_by_hand(tmp_path: Any,
                                                                                    monkeypatch: Any) -> None:
    import sqlite3
    from contextlib import closing
    from pathlib import Path

    from sqlalchemy import create_engine

    from app import db as database
    from app.services import backups

    path = tmp_path / "nexpaper.db"
    records = Path(__file__).parent / "schema"
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript((records / "v10.sql").read_text(encoding="utf-8"))
        connection.execute("PRAGMA user_version = 10")
        connection.execute("INSERT INTO kinds (id, key, name, name_key, hue, position) VALUES (1, 'x', 'X', 'x', 0, 0)")
        connection.execute("INSERT INTO vaults (id, name, icon, folder, created_at) VALUES (1, 'V', 'folder', 'v', "
                           "'2026-01-01 00:00:00')")
        connection.execute(
            "INSERT INTO documents (id, vault_id, title, status, source, added_at, pages, current_version, "
            "change_seq, currency, trashed_status, duplicate_kind, process_error, files_state) "
            "VALUES (1, 1, 'T', 'filed', 'upload', '2026-01-01 00:00:00', 0, 1, 1, 'EUR', '', '', '', '')")
        connection.execute("INSERT INTO document_dates (id, document_id, kind, date) VALUES (1, 1, 'keep_until', "
                           "'2030-12-31'), (2, 1, 'due', '2026-02-01')")
        connection.commit()
    engine = create_engine(f"sqlite:///{path}")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(backups, "create", lambda **_kwargs: path)
    try:
        database.init_db()
    finally:
        engine.dispose()
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
        assert connection.execute("SELECT kind, manual FROM document_dates ORDER BY id").fetchall() == [
            ("keep_until", 1), ("due", 0)]
        assert connection.execute("SELECT keep_years, keep_new_only FROM kinds").fetchall() == [(None, 0)]


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
