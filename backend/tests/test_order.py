"""Order: the lists of senders, tags and kinds with the number of documents behind each, and merging.

The rules that matter: only the vaults a person is in are looked at (no count, no name from anywhere else, and a vault
they are not in answers like one that does not exist), changing needs `manage` in the vault, the kinds of the server are
the operator's, and a merge never reaches over to another vault.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Account, DocumentTag, Job, Sender, Tag
from app.services import changes, jobs

from .conftest import make_account, new_client
from .papers import add_document, document, own_vault, shared_vault


def listed(session: TestClient, what: str, **params: object) -> dict:
    answer = session.get(f"/api/v1/order/{what}", params=params)
    assert answer.status_code == 200, answer.text
    return answer.json()


def by_name(page: dict) -> dict[str, dict]:
    return {item["name"]: item for item in page["items"]}


def world(operator: Account) -> tuple[Account, Account, Account, int]:
    """A shared vault with a manager (the operator), an editor and a reader."""
    editor = make_account("editor")
    reader = make_account("reader")
    vault = shared_vault("Household", operator, (operator, "manage"), (editor, "edit"), (reader, "read"))
    return operator, editor, reader, vault


# --- The lists ----------------------------------------------------------------------------------------------------------


def test_senders_are_listed_with_their_documents_and_what_is_in_the_trash(client: TestClient, operator: Account) -> None:
    _, _, _, vault = world(operator)
    mine = own_vault(operator)
    add_document(vault, operator, "One", sender="Stadtwerke Lindenau", content=None)
    add_document(vault, operator, "Two", sender="Stadtwerke Lindenau", content=None)
    gone = add_document(vault, operator, "Three", sender="Stadtwerke Lindenau", content=None)
    add_document(mine, operator, "Four", sender="Hansa", content=None)
    assert client.delete(f"/api/v1/documents/{gone}").status_code == 200
    page = listed(client, "senders")
    assert page["total"] == 2
    stadtwerke = by_name(page)["Stadtwerke Lindenau"]
    assert (stadtwerke["documents"], stadtwerke["in_trash"], stadtwerke["vault_id"]) == (2, 1, vault)
    assert (stadtwerke["right"], stadtwerke["can_change"]) == ("manage", True)
    assert by_name(page)["Hansa"]["vault_id"] == mine
    # One vault, a part of the name, the most used first, and by pages.
    assert list(by_name(listed(client, "senders", vault_id=mine))) == ["Hansa"]
    assert list(by_name(listed(client, "senders", q="LINDEN"))) == ["Stadtwerke Lindenau"]
    assert [i["name"] for i in listed(client, "senders", order="documents")["items"]] == ["Stadtwerke Lindenau", "Hansa"]
    second = listed(client, "senders", limit=1, offset=1)
    assert (second["total"], [i["name"] for i in second["items"]]) == (2, ["Stadtwerke Lindenau"])
    assert client.get("/api/v1/order/senders", params={"limit": 501}).status_code == 422
    # A percent sign or an underscore in the search is no wildcard.
    assert listed(client, "senders", q="%")["total"] == 0
    assert listed(client, "senders", q="_")["total"] == 0


def test_tags_and_kinds_are_listed_the_same_way(client: TestClient, operator: Account) -> None:
    _, _, _, vault = world(operator)
    invoice = next(k for k in client.get("/api/v1/kinds").json() if k["key"] == "invoice")
    add_document(vault, operator, "A", tags=["strom", "haus"], kind_id=invoice["id"], content=None)
    add_document(vault, operator, "B", tags=["strom"], content=None)
    tags = by_name(listed(client, "tags"))
    assert (tags["strom"]["documents"], tags["haus"]["documents"]) == (2, 1)
    kinds = listed(client, "kinds")
    assert [k["key"] for k in kinds["items"]][:3] == ["invoice", "contract", "insurance"], "the server's order"
    row = next(k for k in kinds["items"] if k["key"] == "invoice")
    assert (row["documents"], row["vault_id"], row["right"]) == (1, None, None)
    # The operator may change a kind of the server; a vault's own kind follows the right in its vault.
    assert row["can_change"] is True
    assert client.post("/api/v1/kinds", json={"name": "Garantie", "vault_id": vault}).status_code == 201
    own = next(k for k in listed(client, "kinds")["items"] if k["name"] == "Garantie")
    assert (own["vault_id"], own["can_change"], own["right"], own["documents"]) == (vault, True, "manage", 0)


def test_a_member_may_not_change_a_kind_of_the_server_and_sees_the_flag(client: TestClient, operator: Account) -> None:
    _, editor, _, _ = world(operator)
    with new_client(editor) as session:
        flags = {k["can_change"] for k in listed(session, "kinds")["items"] if k["vault_id"] is None}
    assert flags == {False}


def test_what_a_person_may_change_follows_their_right(client: TestClient, operator: Account) -> None:
    _, editor, reader, vault = world(operator)
    add_document(vault, operator, "Doc", sender="Hansa", tags=["x"], content=None)
    for who, expected in ((editor, False), (reader, False), (operator, True)):
        with new_client(who) as session:
            assert [i["can_change"] for i in listed(session, "senders")["items"]] == [expected]
            assert [i["can_change"] for i in listed(session, "tags")["items"]] == [expected]


# --- No oracle ----------------------------------------------------------------------------------------------------------


def test_nothing_of_another_vault_is_listed_counted_or_told(client: TestClient, operator: Account) -> None:
    other = make_account("other")
    their = own_vault(other)
    add_document(their, other, "Secret", sender="Their Doctor", tags=["private"], content=None)
    add_document(own_vault(operator), operator, "Mine", sender="My Bank", content=None)
    page = listed(client, "senders")
    assert list(by_name(page)) == ["My Bank"] and page["total"] == 1
    # Looking for it by name, or by the vault, answers exactly like looking for a name nobody has.
    absent = {"items": [], "total": 0}
    assert listed(client, "senders", q="Their Doctor") == absent
    assert listed(client, "senders", q="Nobody At All") == absent
    assert listed(client, "senders", vault_id=their) == absent
    assert listed(client, "senders", vault_id=2**31 - 5) == absent
    assert listed(client, "tags", vault_id=their) == absent
    assert listed(client, "tags", q="private") == absent
    assert all(k["vault_id"] != their for k in listed(client, "kinds", vault_id=their)["items"])
    assert listed(client, "kinds", vault_id=their) == listed(client, "kinds", vault_id=2**31 - 5)


def test_a_kind_of_the_server_counts_only_the_documents_the_caller_can_see(client: TestClient, operator: Account) -> None:
    other = make_account("other")
    invoice = next(k for k in client.get("/api/v1/kinds").json() if k["key"] == "invoice")
    add_document(own_vault(other), other, "Theirs", kind_id=invoice["id"], content=None)
    add_document(own_vault(operator), operator, "Mine", kind_id=invoice["id"], content=None)
    row = next(k for k in listed(client, "kinds")["items"] if k["key"] == "invoice")
    assert row["documents"] == 1, "the operator does not learn what is in a personal vault of somebody else"
    with new_client(other) as session:
        row = next(k for k in listed(session, "kinds")["items"] if k["key"] == "invoice")
        assert row["documents"] == 1


# --- Merging senders ----------------------------------------------------------------------------------------------------


def ids_of(session: TestClient, what: str, name: str) -> int:
    return by_name(listed(session, what))[name]["id"]


def test_a_manager_merges_a_sender_into_another_of_the_same_vault(client: TestClient, operator: Account) -> None:
    _, _, _, vault = world(operator)
    a = add_document(vault, operator, "A", sender="Stadtwerke", date=date(2026, 3, 1), content=None)
    b = add_document(vault, operator, "B", sender="Stadtwerke Lindenau", content=None)
    c = add_document(vault, operator, "C", sender="Stadtwerke", content=None)
    source = ids_of(client, "senders", "Stadtwerke")
    target = ids_of(client, "senders", "Stadtwerke Lindenau")
    with SessionLocal() as db:
        db.query(Job).delete()
        db.commit()
    answer = client.post(f"/api/v1/senders/{source}/merge", json={"into": target})
    assert answer.status_code == 200 and answer.json() == {"id": target, "name": "Stadtwerke Lindenau"}
    page = listed(client, "senders")
    assert list(by_name(page)) == ["Stadtwerke Lindenau"] and page["items"][0]["documents"] == 3
    for doc in (a, b, c):
        assert document(doc).sender_id == target
    # The documents are announced to the feed, their files follow the new name, and the history says so.
    assert client.get(f"/api/v1/documents/{a}/events").json()[0]["detail"] == {"fields": ["sender"], "by": "catalog"}
    with SessionLocal() as db:
        assert {j.ref for j in db.scalars(select(Job).where(Job.kind == jobs.RENAME))} == {a, c}
        assert db.scalar(select(func.count()).select_from(Sender)) == 1


def test_a_merge_stays_in_the_vault_and_does_not_touch_the_same_name_elsewhere(client: TestClient, operator: Account) -> None:
    _, _, _, vault = world(operator)
    mine = own_vault(operator)
    add_document(vault, operator, "A", sender="Hansa", content=None)
    add_document(vault, operator, "B", sender="Hansa AG", content=None)
    elsewhere = add_document(mine, operator, "C", sender="Hansa", content=None)
    source = next(i["id"] for i in listed(client, "senders", vault_id=vault)["items"] if i["name"] == "Hansa")
    keep = ids_of(client, "senders", "Hansa AG")
    mine_row = next(i["id"] for i in listed(client, "senders", vault_id=mine)["items"])
    # Into an entry of another vault: refused, nothing moved.
    assert client.post(f"/api/v1/senders/{source}/merge", json={"into": mine_row}).json()["detail"]["code"] == "merge_other_vault"
    assert client.post(f"/api/v1/senders/{source}/merge", json={"into": source}).json()["detail"]["code"] == "merge_same"
    assert client.post(f"/api/v1/senders/{source}/merge", json={"into": keep}).status_code == 200
    assert document(elsewhere).sender_id == mine_row


def test_merging_needs_manage_and_a_target_the_caller_can_see(client: TestClient, operator: Account) -> None:
    _, editor, reader, vault = world(operator)
    other = make_account("other")
    add_document(vault, operator, "A", sender="One", content=None)
    add_document(vault, operator, "B", sender="Two", content=None)
    foreign = add_document(own_vault(other), other, "F", sender="Foreign", content=None)
    one, two = ids_of(client, "senders", "One"), ids_of(client, "senders", "Two")
    with SessionLocal() as db:
        foreign_row = db.scalar(select(Sender.id).where(Sender.name == "Foreign"))
    for who in (editor, reader):
        with new_client(who) as session:
            assert session.post(f"/api/v1/senders/{one}/merge", json={"into": two}).status_code == 403
    with new_client(other) as session:
        assert session.post(f"/api/v1/senders/{one}/merge", json={"into": two}).status_code == 404
    # A target in somebody else's vault answers like a target that is not there.
    missing = client.post(f"/api/v1/senders/{one}/merge", json={"into": 2**31 - 5})
    hidden = client.post(f"/api/v1/senders/{one}/merge", json={"into": foreign_row})
    assert (missing.status_code, hidden.status_code) == (404, 404)
    assert missing.json() == hidden.json()
    assert document(foreign).sender_id == foreign_row
    assert listed(client, "senders")["total"] == 2, "nothing was merged"


# --- Merging tags ---------------------------------------------------------------------------------------------------------


def test_merging_tags_keeps_a_document_that_had_both_once(client: TestClient, operator: Account) -> None:
    _, editor, _, vault = world(operator)
    both = add_document(vault, operator, "Both", tags=["strom", "energie"], content=None)
    only = add_document(vault, operator, "Only", tags=["strom"], content=None)
    source, target = ids_of(client, "tags", "strom"), ids_of(client, "tags", "energie")
    with new_client(editor) as session:
        assert session.post(f"/api/v1/tags/{source}/merge", json={"into": target}).status_code == 403
    assert client.post(f"/api/v1/tags/{source}/merge", json={"into": target}).json() == {"id": target, "name": "energie"}
    assert client.get(f"/api/v1/documents/{both}").json()["tags"] == ["energie"]
    assert client.get(f"/api/v1/documents/{only}").json()["tags"] == ["energie"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Tag)) == 1
        assert db.scalar(select(func.count()).select_from(DocumentTag)) == 2


# --- Merging kinds ----------------------------------------------------------------------------------------------------------


def test_a_kind_of_a_vault_merges_into_one_of_the_server_and_the_rules_follow(client: TestClient, operator: Account) -> None:
    _, editor, _, vault = world(operator)
    server_kind = next(k for k in client.get("/api/v1/kinds").json() if k["key"] == "invoice")
    own = client.post("/api/v1/kinds", json={"name": "Rechnungen", "vault_id": vault}).json()
    doc = add_document(vault, operator, "Bill", kind_id=own["id"], content=None)
    rule = client.post("/api/v1/rules", json={"vault_id": vault, "when": [{"field": "kind", "op": "is", "value": own["id"]}],
                                             "then": [{"field": "kind", "value": own["id"]}]})
    assert rule.status_code == 201, rule.text
    with new_client(editor) as session:
        assert session.post(f"/api/v1/kinds/{own['id']}/merge", json={"into": server_kind["id"]}).status_code == 403
    answer = client.post(f"/api/v1/kinds/{own['id']}/merge", json={"into": server_kind["id"]})
    assert answer.status_code == 200 and answer.json()["id"] == server_kind["id"]
    assert document(doc).kind_id == server_kind["id"]
    kept = client.get("/api/v1/rules").json()[0]
    assert kept["when"][0]["value"] == server_kind["id"] and kept["then"][0]["value"] == server_kind["id"]
    assert all(k["id"] != own["id"] for k in listed(client, "kinds")["items"])


def test_only_the_operator_merges_kinds_of_the_server_and_only_into_another_of_the_server(
    client: TestClient, operator: Account,
) -> None:
    _, editor, _, vault = world(operator)
    kinds = {k["key"]: k for k in client.get("/api/v1/kinds").json()}
    own = client.post("/api/v1/kinds", json={"name": "Eigen", "vault_id": vault}).json()
    doc = add_document(vault, operator, "Bill", kind_id=kinds["bank"]["id"], content=None)
    with new_client(editor) as session:
        assert session.post(f"/api/v1/kinds/{kinds['bank']['id']}/merge", json={"into": kinds["tax"]["id"]}).status_code == 403
    # Into a kind that belongs to one vault: refused, a kind of the server serves every vault.
    refused = client.post(f"/api/v1/kinds/{kinds['bank']['id']}/merge", json={"into": own["id"]})
    assert refused.json()["detail"]["code"] == "merge_other_vault"
    assert document(doc).kind_id == kinds["bank"]["id"]
    assert client.post(f"/api/v1/kinds/{kinds['bank']['id']}/merge", json={"into": kinds["tax"]["id"]}).status_code == 200
    assert document(doc).kind_id == kinds["tax"]["id"]
    assert not any(k["key"] == "bank" for k in client.get("/api/v1/kinds").json())


def test_a_kind_of_another_vault_cannot_be_merged_into_and_tells_nothing(client: TestClient, operator: Account) -> None:
    _, _, _, vault = world(operator)
    other = make_account("other")
    theirs = shared_vault("Theirs", other, (other, "manage"))
    with new_client(other) as session:
        foreign = session.post("/api/v1/kinds", json={"name": "Hidden", "vault_id": theirs}).json()
    mine = client.post("/api/v1/kinds", json={"name": "Visible", "vault_id": vault}).json()
    missing = client.post(f"/api/v1/kinds/{mine['id']}/merge", json={"into": 2**31 - 5})
    hidden = client.post(f"/api/v1/kinds/{mine['id']}/merge", json={"into": foreign["id"]})
    assert (missing.status_code, hidden.status_code) == (404, 404) and missing.json() == hidden.json()
    with new_client(other) as session:
        assert session.post(f"/api/v1/kinds/{mine['id']}/merge", json={"into": foreign["id"]}).status_code == 404


def test_the_kinds_without_a_vault_named_hide_the_kinds_of_other_vaults(client: TestClient, operator: Account) -> None:
    other = make_account("other")
    theirs = shared_vault("Theirs", other, (other, "manage"))
    with new_client(other) as session:
        assert session.post("/api/v1/kinds", json={"name": "Hidden kind", "vault_id": theirs}).status_code == 201
    names = [item["name"] for item in listed(client, "kinds")["items"]]
    assert "Hidden kind" not in names
    assert listed(client, "kinds", q="Hidden")["total"] == 0


def test_a_merge_takes_the_write_lock_before_it_looks_at_anything(
        client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without it two merges at once, or a merge and a delete, would each decide on what the other is about to change."""
    _, _, _, vault = world(operator)
    add_document(vault, operator, "A", sender="One", tags=["a"], content=None)
    add_document(vault, operator, "B", sender="Two", tags=["b"], content=None)
    own = client.post("/api/v1/kinds", json={"name": "Mine", "vault_id": vault}).json()
    other = client.post("/api/v1/kinds", json={"name": "Yours", "vault_id": vault}).json()
    calls: list[str] = []
    real = changes.write_lock

    def spy(db: object) -> None:
        calls.append("lock")
        real(db)  # type: ignore[arg-type]

    monkeypatch.setattr(changes, "write_lock", spy)
    for what, source, target in (("senders", ids_of(client, "senders", "One"), ids_of(client, "senders", "Two")),
                                 ("tags", ids_of(client, "tags", "a"), ids_of(client, "tags", "b")),
                                 ("kinds", own["id"], other["id"])):
        calls.clear()
        route = what if what != "kinds" else "kinds"
        assert client.post(f"/api/v1/{route}/{source}/merge", json={"into": target}).status_code == 200, what
        assert calls, f"merging {what} took no write lock"


def test_a_merge_of_kinds_renames_the_files_of_the_documents_it_reached(client: TestClient, operator: Account) -> None:
    _, _, _, vault = world(operator)
    own = client.post("/api/v1/kinds", json={"name": "Mine", "vault_id": vault}).json()
    other = client.post("/api/v1/kinds", json={"name": "Yours", "vault_id": vault}).json()
    docs = [add_document(vault, operator, f"D{n}", kind_id=own["id"], content=None) for n in range(2)]
    with SessionLocal() as db:
        db.query(Job).delete()
        db.commit()
    assert client.post(f"/api/v1/kinds/{own['id']}/merge", json={"into": other["id"]}).status_code == 200
    with SessionLocal() as db:
        assert {j.ref for j in db.scalars(select(Job).where(Job.kind == jobs.RENAME))} == set(docs)
