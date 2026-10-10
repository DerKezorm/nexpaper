"""Senders, tags and kinds. Senders and tags belong to a vault: the lists gather a name across the vaults a person
reaches, a change acts on one vault, and nothing done in one vault tells anything about another."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Account, Sender, Tag
from app.names import name_key
from app.services import jobs

from .conftest import make_account, new_client
from .papers import add_document, document, own_vault, shared_vault


def names(listing: list[dict]) -> list[str]:
    return [item["name"] for item in listing]


def row_ids(listing: list[dict], name: str) -> list[int]:
    return [item["id"] for group in listing if group["name"] == name for item in group["items"]]


def test_a_person_sees_only_the_senders_and_tags_of_their_vaults_and_shared_documents(
    client: TestClient, operator: Account,
) -> None:
    other = make_account("other")
    add_document(own_vault(operator), operator, "Mine", sender="My Bank", tags=["taxes"], content=None)
    add_document(own_vault(other), other, "Theirs", sender="Their Doctor", tags=["health", "taxes"], content=None)
    assert names(client.get("/api/v1/senders").json()) == ["My Bank"]
    assert names(client.get("/api/v1/tags").json()) == ["taxes"]
    with new_client(other) as session:
        assert names(session.get("/api/v1/senders").json()) == ["Their Doctor"]
        assert names(session.get("/api/v1/tags").json()) == ["health", "taxes"]
    # A document shared with the operator brings its sender and its tags into their lists, and no more.
    doc = add_document(own_vault(other), other, "Shared", sender="Shared Sender", tags=["only-shared"], content=None)
    with new_client(other) as session:
        session.put(f"/api/v1/documents/{doc}/shares/{operator.id}", json={"right": "read"})
    assert "Shared Sender" in names(client.get("/api/v1/senders").json())
    assert "Their Doctor" not in names(client.get("/api/v1/senders").json())
    assert "only-shared" in names(client.get("/api/v1/tags").json())
    assert names(client.get("/api/v1/tags").json()).count("taxes") == 1


def test_the_same_name_in_two_vaults_is_one_entry_and_one_filter(client: TestClient, operator: Account) -> None:
    household = shared_vault("Household", operator)
    mine = own_vault(operator)
    a = add_document(mine, operator, "Mine", sender="Stadtwerke Lindenau", tags=["Haus"], content=None)
    b = add_document(household, operator, "Ours", sender="STADTWERKE lindenau", tags=["haus"], content=None)
    add_document(household, operator, "Else", sender="Other", content=None)
    listed = client.get("/api/v1/senders").json()
    group = next(g for g in listed if g["name"].casefold() == "stadtwerke lindenau")
    assert sorted(i["vault_id"] for i in group["items"]) == sorted([mine, household])
    assert names(listed).count(group["name"]) == 1
    assert [g["name"] for g in client.get(f"/api/v1/senders?vault_id={household}").json()] == ["Other",
                                                                                              "STADTWERKE lindenau"]
    found = client.get("/api/v1/documents", params={"sender": "stadtwerke LINDENAU"}).json()["items"]
    assert sorted(d["id"] for d in found) == sorted([a, b])
    assert sorted(d["id"] for d in client.get("/api/v1/documents", params={"tag": "HAUS"}).json()["items"]) == sorted(
        [a, b])


def test_a_name_made_on_a_document_is_found_again_whatever_the_case_and_unicode(
    client: TestClient, operator: Account,
) -> None:
    vault = own_vault(operator)
    doc = add_document(vault, operator, "One", content=None)
    for spelling in ("Müller & Söhne", "müller & söhne", "  MÜLLER   & SÖHNE ", "Müller & Söhne"):
        assert client.patch(f"/api/v1/documents/{doc}", json={"sender": spelling}).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Sender)) == 1
    assert names(client.get("/api/v1/senders").json()) == ["Müller & Söhne"]
    with SessionLocal() as db:
        assert db.scalar(select(Sender.key)) == "müller & söhne"
    # Case folded as Unicode means it, not only lower case: "ß" and "SS" are one.
    for spelling in ("Großhandel Lindenau", "GROSSHANDEL LINDENAU"):
        assert client.patch(f"/api/v1/documents/{doc}", json={"sender": spelling}).status_code == 200
    assert names(client.get("/api/v1/senders").json()) == ["Großhandel Lindenau"]


def test_the_key_of_a_name_is_composed_and_folded() -> None:
    assert name_key("Mu\u0308ller") == name_key("MÜLLER") == name_key("müller") == "müller"
    assert name_key("Straße") == name_key("STRASSE")
    assert name_key("Ǆ") == name_key("ǆ")


def test_a_sender_is_renamed_for_all_its_documents_and_their_files_follow(client: TestClient, operator: Account) -> None:
    vault = own_vault(operator)
    docs = [add_document(vault, operator, f"Bill {i}", sender="Old Name", date=date(2026, 1, i + 1)) for i in range(3)]
    sender_id = row_ids(client.get("/api/v1/senders").json(), "Old Name")[0]
    before = document(docs[0]).change_seq
    renamed = client.patch(f"/api/v1/senders/{sender_id}", json={"name": "New Name"})
    assert renamed.status_code == 200 and renamed.json() == {"id": sender_id, "name": "New Name"}
    assert all(client.get(f"/api/v1/documents/{d}").json()["sender"]["name"] == "New Name" for d in docs)
    assert document(docs[0]).change_seq > before, "the programs that follow the feed learn of it"
    history = client.get(f"/api/v1/documents/{docs[0]}/events").json()
    assert history[0]["action"] == "changed" and history[0]["detail"] == {"fields": ["sender"], "by": "catalog"}
    assert jobs.run_pending() == 3
    # Renaming to a name the vault has makes the two one.
    other = add_document(vault, operator, "Other", sender="Existing", content=None)
    merged = client.patch(f"/api/v1/senders/{sender_id}", json={"name": "existing"})
    assert merged.status_code == 200 and merged.json()["name"] == "Existing"
    assert {client.get(f"/api/v1/documents/{d}").json()["sender"]["name"] for d in [*docs, other]} == {"Existing"}
    assert names(client.get("/api/v1/senders").json()) == ["Existing"]


def test_a_name_from_a_vault_one_cannot_see_answers_like_a_name_nobody_uses(client: TestClient, operator: Account) -> None:
    """The oracle the prüfer found: renaming to a name that exists only in somebody else's personal vault must look
    exactly like renaming to a fresh one (same id, same answer), and it must not merge anything."""
    bob = make_account("bob")
    add_document(own_vault(bob), bob, "Befund", sender="Dr. Secret", tags=["Anwalt"], content=None)
    mine = own_vault(operator)
    first = add_document(mine, operator, "A", sender="Alpha", tags=["one"], content=None)
    second = add_document(mine, operator, "B", sender="Beta", tags=["two"], content=None)
    alpha = row_ids(client.get("/api/v1/senders").json(), "Alpha")[0]
    beta = row_ids(client.get("/api/v1/senders").json(), "Beta")[0]
    secret = client.patch(f"/api/v1/senders/{alpha}", json={"name": "dr. secret"})
    fresh = client.patch(f"/api/v1/senders/{beta}", json={"name": "dr. fresh"})
    assert (secret.status_code, fresh.status_code) == (200, 200)
    assert secret.json() == {"id": alpha, "name": "dr. secret"} and fresh.json() == {"id": beta, "name": "dr. fresh"}
    one = {t["name"]: t["items"][0]["id"] for t in client.get("/api/v1/tags").json()}
    tag_secret = client.patch(f"/api/v1/tags/{one['one']}", json={"name": "ANWALT"})
    tag_fresh = client.patch(f"/api/v1/tags/{one['two']}", json={"name": "NOTAR"})
    assert tag_secret.json() == {"id": one["one"], "name": "ANWALT"}
    assert tag_fresh.json() == {"id": one["two"], "name": "NOTAR"}
    # Errors alike, too: a wrong name, a row in somebody else's vault.
    bobs = {s.name: s.id for s in _rows(Sender)}["Dr. Secret"]
    assert client.patch(f"/api/v1/senders/{bobs}", json={"name": "x"}).json() == client.patch(
        "/api/v1/senders/999999", json={"name": "x"}).json()
    # Bob's vault saw nothing of it.
    with new_client(bob) as as_bob:
        assert names(as_bob.get("/api/v1/senders").json()) == ["Dr. Secret"]
        assert names(as_bob.get("/api/v1/tags").json()) == ["Anwalt"]
    assert client.get(f"/api/v1/documents/{first}").json()["sender"]["name"] == "dr. secret"
    assert client.get(f"/api/v1/documents/{second}").json()["tags"] == ["NOTAR"]


def _rows(table: type) -> list:
    with SessionLocal() as db:
        found = list(db.scalars(select(table)))
        for row in found:
            db.expunge(row)
        return found


def test_renaming_needs_edit_in_the_vault_of_the_row(client: TestClient, operator: Account) -> None:
    reader, editor = make_account("reader"), make_account("editor")
    vault = shared_vault("Household", operator, (reader, "read"), (editor, "edit"))
    add_document(vault, operator, "Shared bill", sender="Common Sender", tags=["bills"], content=None)
    # The same name in the reader's own vault: their row, theirs to rename; the household's is not.
    add_document(own_vault(reader), reader, "Own bill", sender="Common Sender", content=None)
    household_row = next(i["id"] for g in client.get("/api/v1/senders").json() for i in g["items"]
                         if i["vault_id"] == vault)
    tag_row = client.get("/api/v1/tags").json()[0]["items"][0]["id"]
    with new_client(reader) as session:
        group = session.get("/api/v1/senders").json()
        assert names(group) == ["Common Sender"] and len(group[0]["items"]) == 2
        answer = session.patch(f"/api/v1/senders/{household_row}", json={"name": "Hijacked"})
        assert answer.status_code == 403 and answer.json()["detail"]["code"] == "forbidden"
        assert session.delete(f"/api/v1/senders/{household_row}").status_code == 403
        assert session.patch(f"/api/v1/tags/{tag_row}", json={"name": "x"}).status_code == 403
        own_row = next(i["id"] for i in group[0]["items"] if i["vault_id"] == own_vault(reader))
        assert session.patch(f"/api/v1/senders/{own_row}", json={"name": "Mine now"}).status_code == 200
    with new_client(editor) as session:
        assert session.patch(f"/api/v1/senders/{household_row}", json={"name": "Renamed"}).status_code == 200
    stranger = make_account("stranger")
    with new_client(stranger) as session:
        assert session.patch(f"/api/v1/senders/{household_row}", json={"name": "Hijacked"}).status_code == 404
        assert session.delete(f"/api/v1/senders/{household_row}").status_code == 404
        assert session.delete(f"/api/v1/tags/{tag_row}").status_code == 404
    assert names(client.get("/api/v1/senders").json()) == ["Renamed"]


def test_deleting_a_sender_leaves_its_documents_without_one(client: TestClient, operator: Account) -> None:
    doc = add_document(own_vault(operator), operator, "Bill", sender="In use", date=date(2026, 2, 1))
    sender_id = row_ids(client.get("/api/v1/senders").json(), "In use")[0]
    assert client.delete(f"/api/v1/senders/{sender_id}").status_code == 204
    assert client.get(f"/api/v1/documents/{doc}").json()["sender"] is None
    assert client.get("/api/v1/senders").json() == []
    assert jobs.run_pending() == 1


def test_a_sender_or_tag_nobody_uses_any_more_goes(client: TestClient, operator: Account) -> None:
    doc = add_document(own_vault(operator), operator, "Bill", sender="First", tags=["a", "b"], content=None)
    client.patch(f"/api/v1/documents/{doc}", json={"sender": "Second", "tags": ["b"]})
    assert names(client.get("/api/v1/senders").json()) == ["Second"]
    assert names(client.get("/api/v1/tags").json()) == ["b"]
    assert [s.name for s in _rows(Sender)] == ["Second"] and [t.name for t in _rows(Tag)] == ["b"]


def test_a_document_that_moves_takes_its_sender_and_tags_to_the_other_vault(client: TestClient, operator: Account) -> None:
    household = shared_vault("Household", operator)
    mine = own_vault(operator)
    doc = add_document(mine, operator, "Bill", sender="Hansa", tags=["car", "Tax"], date=date(2026, 3, 1))
    add_document(household, operator, "Old", sender="HANSA", tags=["tax"], content=None)
    assert client.post(f"/api/v1/documents/{doc}/move", json={"vault_id": household}).status_code == 200
    moved = client.get(f"/api/v1/documents/{doc}").json()
    # The household's own row of that name (spelled as there), and the tags of the household.
    assert moved["sender"]["name"] == "HANSA" and moved["tags"] == ["car", "tax"]
    with SessionLocal() as db:
        assert {s.vault_id for s in db.scalars(select(Sender))} == {household}
        assert {t.vault_id for t in db.scalars(select(Tag))} == {household}
    jobs.run_pending()


def test_a_tag_is_renamed_merged_and_deleted_from_all_documents(client: TestClient, operator: Account) -> None:
    vault = own_vault(operator)
    a = add_document(vault, operator, "A", tags=["car", "tax"], content=None)
    b = add_document(vault, operator, "B", tags=["auto"], content=None)
    tags = {t["name"]: t["items"][0]["id"] for t in client.get("/api/v1/tags").json()}
    assert client.patch(f"/api/v1/tags/{tags['auto']}", json={"name": "CAR"}).json()["name"] == "car"
    assert client.get(f"/api/v1/documents/{b}").json()["tags"] == ["car"]
    assert client.get(f"/api/v1/documents/{a}").json()["tags"] == ["car", "tax"]
    assert client.patch(f"/api/v1/tags/{tags['tax']}", json={"name": "taxes"}).json()["name"] == "taxes"
    assert client.get(f"/api/v1/documents/{a}").json()["tags"] == ["car", "taxes"]
    assert client.delete(f"/api/v1/tags/{tags['car']}").status_code == 204
    assert client.get(f"/api/v1/documents/{a}").json()["tags"] == ["taxes"]
    assert client.get(f"/api/v1/documents/{b}").json()["tags"] == []
    with SessionLocal() as db:
        assert [t.name for t in db.scalars(select(Tag))] == ["taxes"]
    for wrong in ("", "x" * 41, "a\u0000b"):
        assert client.patch(f"/api/v1/tags/{tags['tax']}", json={"name": wrong}).status_code == 422


def test_only_the_operator_changes_kinds_and_the_files_and_documents_follow(client: TestClient, operator: Account) -> None:
    kinds = client.get("/api/v1/kinds").json()
    assert [k["position"] for k in kinds] == list(range(10)) and all(0 <= k["hue"] < 360 for k in kinds)
    invoice = next(k for k in kinds if k["key"] == "invoice")
    doc = add_document(own_vault(operator), operator, "Bill", kind_id=invoice["id"], sender="S", date=date(2026, 1, 1))
    member = make_account("member")
    with new_client(member) as session:
        assert session.post("/api/v1/kinds", json={"name": "Mine"}).status_code == 403
        assert session.patch(f"/api/v1/kinds/{invoice['id']}", json={"name": "Mine"}).status_code == 403
        assert session.delete(f"/api/v1/kinds/{invoice['id']}").status_code == 403
    made = client.post("/api/v1/kinds", json={"name": "Warranty", "hue": 400})
    assert made.status_code == 422
    made = client.post("/api/v1/kinds", json={"name": "Warranty", "hue": 120})
    assert made.status_code == 201 and made.json()["key"] == "" and made.json()["position"] == 10
    assert client.post("/api/v1/kinds", json={"name": "warranty"}).status_code == 409
    # Unicode and case alike: "Behörde" and "BEHÖRDE" are one kind.
    assert client.post("/api/v1/kinds", json={"name": "BEHÖRDE"}).status_code == 409
    assert client.patch(f"/api/v1/kinds/{invoice['id']}", json={"name": "Warranty"}).status_code == 409
    assert client.patch(f"/api/v1/kinds/{invoice['id']}", json={"name": "Bill"}).status_code == 200
    history = client.get(f"/api/v1/documents/{doc}/events").json()
    assert history[0]["detail"] == {"fields": ["kind"], "by": "catalog"}
    assert client.patch(f"/api/v1/kinds/{invoice['id']}", json={"hue": 200, "position": 3}).json()["hue"] == 200
    assert client.delete(f"/api/v1/kinds/{invoice['id']}").status_code == 204
    assert client.get(f"/api/v1/documents/{doc}").json()["kind"] is None, "the document stays, without a kind"
    assert client.delete("/api/v1/kinds/999999").status_code == 404
    assert client.patch("/api/v1/kinds/999999", json={"name": "x"}).status_code == 404
    jobs.run_pending()


def test_a_sender_in_use_goes_only_for_a_manager_and_force_is_no_way_round(client: TestClient, operator: Account) -> None:
    editor = make_account("editor")
    vault = shared_vault("Household", operator, (editor, "edit"))
    docs = [add_document(vault, operator, f"Bill {n}", sender="Hansa", content=None) for n in range(3)]
    row = row_ids(client.get("/api/v1/senders").json(), "Hansa")[0]
    with new_client(editor) as as_editor:
        refused = as_editor.delete(f"/api/v1/senders/{row}")
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "in_use" and refused.json()["detail"]["documents"] == 3
        assert client.get(f"/api/v1/documents/{docs[0]}").json()["sender"]["name"] == "Hansa"
        forced = as_editor.delete(f"/api/v1/senders/{row}?force=true")
        assert forced.status_code == 403 and forced.json()["detail"]["code"] == "forbidden"
    assert all(client.get(f"/api/v1/documents/{d}").json()["sender"]["name"] == "Hansa" for d in docs)
    assert client.delete(f"/api/v1/senders/{row}").status_code == 204
    assert all(client.get(f"/api/v1/documents/{d}").json()["sender"] is None for d in docs)
    # A manager needs no flag.
    add_document(vault, operator, "Bill", sender="Other", content=None)
    other = row_ids(client.get("/api/v1/senders").json(), "Other")[0]
    assert client.delete(f"/api/v1/senders/{other}").status_code == 204


def test_renaming_onto_a_name_the_vault_has_joins_the_two_only_for_a_manager(client: TestClient, operator: Account) -> None:
    editor = make_account("editor")
    vault = shared_vault("Household", operator, (operator, "manage"), (editor, "edit"))
    a = add_document(vault, operator, "A", sender="Hansa", tags=["bills"], content=None)
    b = add_document(vault, operator, "B", sender="Hansa AG", tags=["invoices"], content=None)
    senders = {i["name"]: i["items"][0]["id"] for i in client.get("/api/v1/senders").json()}
    tags = {i["name"]: i["items"][0]["id"] for i in client.get("/api/v1/tags").json()}
    with new_client(editor) as as_editor:
        for url, name in ((f"/api/v1/senders/{senders['Hansa']}", "hansa ag"), (f"/api/v1/tags/{tags['bills']}", "Invoices")):
            taken = as_editor.patch(url, json={"name": name})
            assert taken.status_code == 409 and taken.json()["detail"]["code"] == "name_taken", url
        # A name nobody has stays a plain rename for the editor.
        assert as_editor.patch(f"/api/v1/senders/{senders['Hansa']}", json={"name": "Hansa Nord"}).status_code == 200
        assert as_editor.patch(f"/api/v1/tags/{tags['bills']}", json={"name": "Rechnungen"}).status_code == 200
        assert as_editor.patch(f"/api/v1/senders/{senders['Hansa']}", json={"name": "Hansa NORD"}).status_code == 200
    assert client.get(f"/api/v1/documents/{a}").json()["sender"]["name"] == "Hansa NORD"
    assert client.get(f"/api/v1/documents/{b}").json()["sender"]["name"] == "Hansa AG"
    # The manager may join them.
    joined = client.patch(f"/api/v1/senders/{senders['Hansa']}", json={"name": "Hansa AG"})
    assert joined.status_code == 200 and joined.json()["id"] == senders["Hansa AG"]
    assert client.get(f"/api/v1/documents/{a}").json()["sender"]["name"] == "Hansa AG"
    assert client.patch(f"/api/v1/tags/{tags['bills']}", json={"name": "invoices"}).status_code == 200
    assert client.get(f"/api/v1/documents/{a}").json()["tags"] == ["invoices"]
