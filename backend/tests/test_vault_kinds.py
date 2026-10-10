"""The kinds of a vault: made by whoever may edit the vault, shown to its members only, taken along by name when a
document moves, merged by name in the archive and the search, never a way to learn what another vault holds."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, Kind
from app.services import jobs, vaults

from .conftest import make_account, new_client
from .files import make_pdf
from .intake import device_token, upload_and_read, upload_key
from .papers import add_document, own_vault, shared_vault


def make(client: TestClient, vault: int, name: str, hue: int = 30) -> dict[str, Any]:
    answer = client.post("/api/v1/kinds", json={"name": name, "hue": hue, "vault_id": vault})
    assert answer.status_code in (200, 201), answer.text
    return answer.json()  # type: ignore[no-any-return]


def names(listing: list[dict[str, Any]]) -> list[str]:
    return [item["name"] for item in listing]


def found_ids(answer: Any) -> set[int]:
    assert answer.status_code == 200, answer.text
    return {hit["document"]["id"] for hit in answer.json()["items"]}


def with_kind(client: TestClient, vault: int, owner: Account, title: str, kind: dict[str, Any]) -> int:
    document = add_document(vault, owner, title, content=None)
    assert client.patch(f"/api/v1/documents/{document}", json={"kind_id": kind["id"]}).status_code == 200
    return document


def test_a_vault_makes_kinds_of_its_own_that_only_its_members_see(client: TestClient, operator: Account) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    home = shared_vault("Haushalt", operator, (jule, "edit"))
    with new_client(jule) as browser:
        made = make(browser, home, "Mietvertrag", 120)
        assert made["vault_id"] == home and made["key"] == "" and made["hue"] == 120
        mine = browser.get("/api/v1/kinds", params={"vault_id": home}).json()
        assert "Mietvertrag" in names(mine) and "Rechnung" in names(mine)
        assert [k["vault_id"] for k in mine if k["name"] == "Rechnung"] == [None]
        assert "Mietvertrag" in names(browser.get("/api/v1/kinds").json())
    # The operator is a member through the vault; tom is a member of nothing that has it.
    assert "Mietvertrag" in names(client.get("/api/v1/kinds", params={"vault_id": home}).json())
    with new_client(tom) as browser:
        assert "Mietvertrag" not in names(browser.get("/api/v1/kinds").json())
        assert browser.get("/api/v1/kinds", params={"vault_id": home}).status_code == 404
        assert len(browser.get("/api/v1/kinds").json()) == 10, "only the kinds that come with nexpaper"


def test_who_may_make_change_and_delete_a_kind_of_a_vault(client: TestClient, operator: Account) -> None:
    editor, reader, stranger, manager = (make_account(n) for n in ("editor", "reader", "stranger", "manager"))
    home = shared_vault("Haushalt", manager, (editor, "edit"), (reader, "read"), (manager, "manage"))
    with new_client(editor) as browser:
        kind = make(browser, home, "Garantie")
    body = {"name": "Neu", "vault_id": home}
    with new_client(stranger) as browser:
        assert browser.post("/api/v1/kinds", json=body).status_code == 404
        assert browser.patch(f"/api/v1/kinds/{kind['id']}", json={"name": "x"}).status_code == 404
        assert browser.delete(f"/api/v1/kinds/{kind['id']}").status_code == 404
    with new_client(reader) as browser:
        assert browser.post("/api/v1/kinds", json=body).status_code == 403
        assert browser.patch(f"/api/v1/kinds/{kind['id']}", json={"name": "x"}).status_code == 403
        assert browser.delete(f"/api/v1/kinds/{kind['id']}").status_code == 403
    # Nobody but the operator in a browser changes the kinds of the whole server.
    server_kind = next(k for k in client.get("/api/v1/kinds").json() if k["key"] == "invoice")
    with new_client(editor) as browser:
        assert browser.post("/api/v1/kinds", json={"name": "Server"}).status_code == 403
        assert browser.patch(f"/api/v1/kinds/{server_kind['id']}", json={"name": "x"}).status_code == 403
        assert browser.delete(f"/api/v1/kinds/{server_kind['id']}").status_code == 403
        renamed = browser.patch(f"/api/v1/kinds/{kind['id']}", json={"name": "Garantiebrief", "hue": 200})
        assert renamed.status_code == 200 and renamed.json()["name"] == "Garantiebrief"
    # A device acts for its person in the vault, but never for the server's kinds.
    with new_client(editor) as browser:
        token = device_token(browser)
    with new_client() as program:
        auth = {"Authorization": f"Bearer {token}"}
        assert program.post("/api/v1/kinds", json={"name": "Vom Geraet", "vault_id": home}, headers=auth).status_code == 201
        assert program.post("/api/v1/kinds", json={"name": "Server"}, headers=auth).status_code == 403
        assert program.patch(f"/api/v1/kinds/{server_kind['id']}", json={"name": "x"}, headers=auth).status_code == 403
    # A key for reading never changes anything.
    secret = upload_key(editor, "read")
    with new_client() as program:
        auth = {"Authorization": f"Bearer {secret}"}
        assert program.post("/api/v1/kinds", json=body, headers=auth).status_code in (401, 403)
        assert program.delete(f"/api/v1/kinds/{kind['id']}", headers=auth).status_code in (401, 403)
        assert program.get("/api/v1/kinds", headers=auth).status_code == 200


def test_a_name_the_vault_can_already_choose_answers_with_that_kind(client: TestClient, operator: Account) -> None:
    jule = make_account("jule")
    home = shared_vault("Haushalt", operator, (jule, "edit"))
    with new_client(jule) as browser:
        first = browser.post("/api/v1/kinds", json={"name": "Mietvertrag", "vault_id": home})
        again = browser.post("/api/v1/kinds", json={"name": "  mietvertrag ", "vault_id": home})
        assert first.status_code == 201 and again.status_code == 200 and again.json()["id"] == first.json()["id"]
        # A kind of the server's: that one is taken, not a second one beside it.
        server = browser.post("/api/v1/kinds", json={"name": "BEHÖRDE", "vault_id": home})
        assert server.status_code == 200 and server.json()["vault_id"] is None and server.json()["key"] == "authority"
        # Odd names are refused as everywhere.
        assert browser.post("/api/v1/kinds", json={"name": "a\x00b", "vault_id": home}).status_code == 422
        assert browser.post("/api/v1/kinds", json={"name": " ", "vault_id": home}).status_code == 422
    with SessionLocal() as db:
        assert len(list(db.scalars(select(Kind).where(Kind.vault_id == home)))) == 1


def test_a_kind_of_another_vault_cannot_be_felt_out(client: TestClient, operator: Account) -> None:
    """Nothing about the kinds of a vault shows in another: the answers are those for a name nobody has."""
    jule, tom = make_account("jule"), make_account("tom")
    with new_client(jule) as hers:
        secret = make(hers, own_vault(jule), "Diagnose")
        hers_doc = add_document(own_vault(jule), jule, "Befund", content=None)
        assert hers.patch(f"/api/v1/documents/{hers_doc}", json={"kind_id": secret["id"]}).status_code == 200
    with new_client(tom) as his:
        nobody = his.post("/api/v1/kinds", json={"name": "Niemandsart", "vault_id": own_vault(tom)})
        same = his.post("/api/v1/kinds", json={"name": "Diagnose", "vault_id": own_vault(tom)})
        assert nobody.status_code == same.status_code == 201
        assert set(nobody.json()) == set(same.json()) and same.json()["id"] != secret["id"]
        assert same.json()["vault_id"] == own_vault(tom)
        # Her kind answers like an id that does not exist: to read, rename, delete, use on a document, filter by.
        gone = 999_999
        mine = add_document(own_vault(tom), tom, "Mein", content=None)
        for who, path in ((secret["id"], "x"), (gone, "x")):
            assert his.patch(f"/api/v1/kinds/{who}", json={"name": path}).status_code == 404
            assert his.delete(f"/api/v1/kinds/{who}").status_code == 404
        used = his.patch(f"/api/v1/documents/{mine}", json={"kind_id": secret["id"]})
        missing = his.patch(f"/api/v1/documents/{mine}", json={"kind_id": gone})
        assert used.status_code == missing.status_code == 422 and used.json() == missing.json()
        assert "Diagnose" not in names([k for k in his.get("/api/v1/kinds").json() if k["vault_id"] != own_vault(tom)])
        # A filter by her kind finds nothing of hers, and the same name of his own is no help either.
        found = his.get("/api/v1/search", params={"kind_id": secret["id"]}).json()
        assert found["items"] == []
        # Not even with a document of his own that has a kind of the same name: whose number that is stays unsaid.
        own = add_document(own_vault(tom), tom, "Eigener Befund", content=None)
        assert his.patch(f"/api/v1/documents/{own}", json={"kind_id": same.json()["id"]}).status_code == 200
        assert his.get("/api/v1/search", params={"kind_id": secret["id"]}).json()["items"] == []
        assert found_ids(his.get("/api/v1/search", params={"kind_id": same.json()["id"]})) == {own}
        # A rule of his vault cannot name it, and cannot learn that it exists.
        rule = {"vault_id": own_vault(tom), "when": [{"field": "kind", "op": "is", "value": secret["id"]}],
                "then": [{"field": "tag", "value": "x"}]}
        asked = his.post("/api/v1/rules", json=rule)
        rule["when"][0]["value"] = gone
        none = his.post("/api/v1/rules", json=rule)
        assert asked.status_code == none.status_code == 422 and asked.json() == none.json()


def test_the_documents_of_a_vault_have_its_kinds_and_the_servers(client: TestClient, operator: Account) -> None:
    jule = make_account("jule")
    home = shared_vault("Haushalt", operator, (jule, "edit"))
    work = shared_vault("Firma", operator, (jule, "edit"))
    with new_client(jule) as browser:
        mine = make(browser, home, "Mietvertrag")
        document = add_document(home, jule, "Vertrag", content=None)
        assert browser.patch(f"/api/v1/documents/{document}", json={"kind_id": mine["id"]}).status_code == 200
        shown = browser.get(f"/api/v1/documents/{document}").json()["kind"]
        assert shown["id"] == mine["id"] and shown["vault_id"] == home
        # Not for a document of the other vault.
        elsewhere = add_document(work, jule, "Anderes", content=None)
        assert browser.patch(f"/api/v1/documents/{elsewhere}", json={"kind_id": mine["id"]}).status_code == 422
        # A kind of the server's is for every document.
        invoice = next(k for k in browser.get("/api/v1/kinds").json() if k["key"] == "invoice")
        assert browser.patch(f"/api/v1/documents/{elsewhere}", json={"kind_id": invoice["id"]}).status_code == 200
        # Uploading with a kind of the vault, and with one of another vault.
        assert browser.post("/api/v1/documents", files=[("file", ("a.pdf", make_pdf(["Vertrag"]), "application/pdf"))],
                            params={"vault_id": home}).status_code == 201


def test_a_document_that_moves_takes_its_kind_along_by_name(client: TestClient, operator: Account) -> None:
    jule = make_account("jule")
    home = shared_vault("Haushalt", operator, (jule, "manage"))
    work = shared_vault("Firma", operator, (jule, "edit"))
    with new_client(jule) as browser:
        mine = make(browser, home, "Mietvertrag", 77)
        document = with_kind(browser, home, jule, "Vertrag", mine)
        assert browser.post(f"/api/v1/documents/{document}/move", json={"vault_id": work}).status_code == 200
        moved = browser.get(f"/api/v1/documents/{document}").json()["kind"]
        assert moved["name"] == "Mietvertrag" and moved["vault_id"] == work and moved["id"] != mine["id"]
        assert moved["hue"] == 77
        # The old vault keeps its kind; the new one has it from now on.
        assert "Mietvertrag" in names(browser.get("/api/v1/kinds", params={"vault_id": home}).json())
        assert "Mietvertrag" in names(browser.get("/api/v1/kinds", params={"vault_id": work}).json())
        # Another document of the same kind comes: the kind of that name is taken, none is made twice.
        second = with_kind(browser, home, jule, "Vertrag zwei", mine)
        assert browser.post(f"/api/v1/documents/{second}/move", json={"vault_id": work}).status_code == 200
        assert browser.get(f"/api/v1/documents/{second}").json()["kind"]["id"] == moved["id"]
        # A kind of the server's stays the server's.
        invoice = next(k for k in browser.get("/api/v1/kinds").json() if k["key"] == "invoice")
        third = add_document(home, jule, "Rechnung", content=None, kind_id=invoice["id"])
        assert browser.post(f"/api/v1/documents/{third}/move", json={"vault_id": work}).status_code == 200
        assert browser.get(f"/api/v1/documents/{third}").json()["kind"]["id"] == invoice["id"]
    with SessionLocal() as db:
        assert len(list(db.scalars(select(Kind).where(Kind.vault_id == work)))) == 1


def test_a_move_takes_the_name_of_a_kind_the_target_has_already(client: TestClient, operator: Account) -> None:
    jule = make_account("jule")
    home = shared_vault("Haushalt", operator, (jule, "manage"))
    work = shared_vault("Firma", operator, (jule, "edit"))
    with new_client(jule) as browser:
        there = make(browser, work, "Mietvertrag")
        mine = make(browser, home, "Mietvertrag")
        document = with_kind(browser, home, jule, "Vertrag", mine)
        browser.post(f"/api/v1/documents/{document}/move", json={"vault_id": work})
        assert browser.get(f"/api/v1/documents/{document}").json()["kind"]["id"] == there["id"]


def test_the_archive_and_the_search_gather_the_kinds_of_one_name(client: TestClient, operator: Account) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    home = shared_vault("Haushalt", operator, (jule, "edit"))
    work = shared_vault("Firma", operator, (jule, "edit"))
    with new_client(jule) as browser:
        a, b = make(browser, home, "Mietvertrag"), make(browser, work, "Mietvertrag")
        one = with_kind(browser, home, jule, "Wohnung", a)
        two = with_kind(browser, work, jule, "Buero", b)
        listed = browser.get("/api/v1/search", params={"kind_id": a["id"]})
        assert listed.status_code == 200
        assert found_ids(listed) == {one, two}, "the kind and its namesake in the other vault"
        assert found_ids(browser.get("/api/v1/search", params={"q": "art:Mietvertrag"})) == {one, two}
    # Somebody who is in the second vault only gets that vault's document, whichever of the two ids they ask with.
    with SessionLocal() as db:
        vaults.set_member(db, operator.id, work, tom.id, "read")
    with new_client(tom) as browser:
        for kind_id in (a["id"], b["id"]):
            assert found_ids(browser.get("/api/v1/search", params={"kind_id": kind_id})) <= {two}
        assert found_ids(browser.get("/api/v1/search", params={"kind_id": b["id"]})) == {two}


def test_a_name_may_repeat_in_two_vaults_and_not_within_one(client: TestClient, operator: Account) -> None:
    jule = make_account("jule")
    home = shared_vault("Haushalt", operator, (jule, "edit"))
    work = shared_vault("Firma", operator, (jule, "edit"))
    with new_client(jule) as browser:
        a, b = make(browser, home, "Mietvertrag"), make(browser, work, "Mietvertrag")
        assert a["id"] != b["id"]
        other = make(browser, home, "Nebenkosten")
        taken = browser.patch(f"/api/v1/kinds/{other['id']}", json={"name": "mietvertrag"})
        assert taken.status_code == 409
        # A name of the server's is taken too.
        assert browser.patch(f"/api/v1/kinds/{other['id']}", json={"name": "Rechnung"}).status_code == 409
        # Renaming to the same name in another case is the same kind.
        assert browser.patch(f"/api/v1/kinds/{a['id']}", json={"name": "MIETVERTRAG"}).status_code == 200


def test_the_operator_renaming_a_server_kind_tells_nothing_about_the_vaults(client: TestClient,
                                                                            operator: Account) -> None:
    jule = make_account("jule")
    with new_client(jule) as browser:
        mine = make(browser, own_vault(jule), "Diagnose")
    server = next(k for k in client.get("/api/v1/kinds").json() if k["key"] == "health")
    # The operator may call a kind of the server by the name a vault of somebody else uses, and is not told.
    assert client.patch(f"/api/v1/kinds/{server['id']}", json={"name": "Diagnose"}).status_code == 200
    with new_client(jule) as browser:
        listed = browser.get("/api/v1/kinds", params={"vault_id": own_vault(jule)}).json()
        assert names(listed).count("Diagnose") == 1, "one entry per name: the server's"
        assert next(k for k in listed if k["name"] == "Diagnose")["vault_id"] is None
        assert mine["id"] in {k["id"] for k in browser.get("/api/v1/kinds").json()}


def test_deleting_a_kind_of_a_vault_asks_when_documents_use_it(client: TestClient, operator: Account) -> None:
    manager, editor = make_account("manager"), make_account("editor")
    home = shared_vault("Haushalt", manager, (editor, "edit"), (manager, "manage"))
    with new_client(editor) as ed:
        kind = make(ed, home, "Garantie")
        used = with_kind(ed, home, editor, "Waschmaschine", kind)
        busy = ed.delete(f"/api/v1/kinds/{kind['id']}")
        assert busy.status_code == 409 and busy.json()["detail"]["code"] == "in_use"
        assert busy.json()["detail"]["documents"] == 1
        assert ed.get(f"/api/v1/documents/{used}").json()["kind"]["id"] == kind["id"]
        assert ed.delete(f"/api/v1/kinds/{kind['id']}", params={"force": "true"}).status_code == 204
        assert ed.get(f"/api/v1/documents/{used}").json()["kind"] is None
        again = make(ed, home, "Garantie")
        with_kind(ed, home, editor, "Fernseher", again)
    with new_client(manager) as boss:
        assert boss.delete(f"/api/v1/kinds/{again['id']}").status_code == 204
    with SessionLocal() as db:
        assert not list(db.scalars(select(Kind).where(Kind.vault_id == home)))


def test_a_vault_that_goes_takes_its_kinds_and_leaves_the_documents_a_kind(client: TestClient,
                                                                           operator: Account) -> None:
    jule = make_account("jule")
    home = shared_vault("Haushalt", operator, (jule, "manage"))
    with new_client(jule) as browser:
        mine = make(browser, home, "Mietvertrag")
        document = with_kind(browser, home, jule, "Vertrag", mine)
    with SessionLocal() as db:
        vaults.delete_vault(db, operator.id, home, move_to=own_vault(operator))
    shown = client.get(f"/api/v1/documents/{document}").json()
    assert shown["vault_id"] == own_vault(operator) and shown["kind"]["name"] == "Mietvertrag"
    assert shown["kind"]["vault_id"] == own_vault(operator)
    with SessionLocal() as db:
        assert not list(db.scalars(select(Kind).where(Kind.vault_id == home)))


def test_the_rules_of_a_vault_use_its_kinds_and_a_rule_for_the_server_the_servers(client: TestClient,
                                                                                  operator: Account) -> None:
    jule = make_account("jule")
    home = shared_vault("Haushalt", operator, (jule, "manage"))
    work = shared_vault("Firma", operator, (jule, "manage"))
    with new_client(jule) as browser:
        mine, other = make(browser, home, "Mietvertrag"), make(browser, work, "Dienstvertrag")
        ok = browser.post("/api/v1/rules", json={"vault_id": home, "when": [
            {"field": "text", "op": "contains", "values": ["Mietvertrag"]}], "then": [{"field": "kind", "value": mine["id"]}]})
        assert ok.status_code == 201, ok.text
        wrong = browser.post("/api/v1/rules", json={"vault_id": home, "when": [
            {"field": "text", "op": "contains", "values": ["x"]}], "then": [{"field": "kind", "value": other["id"]}]})
        assert wrong.status_code == 422
        document = upload_and_read(browser, "m.pdf", make_pdf(["Mietvertrag Wohnung Lindenau"]), home)
        assert document["kind"]["id"] == mine["id"]
        # In the other vault the rule of the first does nothing.
        elsewhere = upload_and_read(browser, "n.pdf", make_pdf(["Mietvertrag Buero Lindenau"]), work)
        assert elsewhere["kind"] is None
    # The operator's rule for the whole server names the server's kinds only.
    bad = client.post("/api/v1/settings/rules", json={"when": [{"field": "text", "op": "contains", "values": ["x"]}],
                                                     "then": [{"field": "kind", "value": mine["id"]}]})
    assert bad.status_code == 422
    server = next(k for k in client.get("/api/v1/kinds").json() if k["key"] == "invoice")
    good = client.post("/api/v1/settings/rules", json={"when": [{"field": "text", "op": "contains", "values": ["Strom"]}],
                                                      "then": [{"field": "kind", "value": server["id"]}]})
    assert good.status_code == 201, good.text


def test_a_rule_that_moves_a_document_takes_the_kind_along_by_name(client: TestClient, operator: Account) -> None:
    jule = make_account("jule")
    home = shared_vault("Haushalt", operator, (jule, "manage"))
    work = shared_vault("Firma", operator, (jule, "edit"))
    with new_client(jule) as browser:
        mine = make(browser, home, "Mietvertrag")
        made = browser.post("/api/v1/rules", json={"vault_id": home, "when": [
            {"field": "text", "op": "contains", "values": ["Buero"]}], "then": [
            {"field": "vault", "value": work}, {"field": "kind", "value": mine["id"]}]})
        assert made.status_code == 201, made.text
        document = upload_and_read(browser, "m.pdf", make_pdf(["Mietvertrag Buero Lindenau"]), home)
        assert document["vault_id"] == work
        assert document["kind"]["name"] == "Mietvertrag" and document["kind"]["vault_id"] == work


def test_the_kinds_the_ai_may_choose_are_the_servers_and_those_of_the_documents_vault(client: TestClient,
                                                                                      operator: Account) -> None:
    import json

    import httpx

    from app.services import ai

    from .test_ai import Model, set_up

    stand_in = Model()
    stand_in.text = json.dumps({"title": "Vertrag", "sender": "Hausverwaltung Lindenau", "kind": "Mietvertrag"})
    ai.transport = httpx.MockTransport(stand_in.handle)
    original = ai.resolver
    ai.resolver = lambda host, port: ["93.184.216.34"]
    try:
        set_up(client)
        jule = make_account("jule")
        home = shared_vault("Haushalt", operator, (jule, "edit"))
        work = shared_vault("Firma", operator, (jule, "edit"))
        with new_client(jule) as browser:
            make(browser, home, "Mietvertrag")
            make(browser, work, "Dienstvertrag")
        first = upload_and_read(client, "m.pdf", make_pdf(["Vertrag Lindenau"]), home)
        sent = json.dumps(stand_in.body(-1), ensure_ascii=False)
        assert "Mietvertrag" in sent and "Rechnung" in sent and "Dienstvertrag" not in sent
        assert first["kind"]["name"] == "Mietvertrag" and first["kind"]["vault_id"] == home
        # In the other vault the same answer names a kind that vault does not have: none is set, nothing is made.
        second = upload_and_read(client, "n.pdf", make_pdf(["Vertrag Lindenau zwei"]), work)
        assert "Mietvertrag" not in json.dumps(stand_in.body(-1), ensure_ascii=False)
        assert second["kind"] is None
    finally:
        ai.transport = None
        ai.resolver = original
    assert jobs  # the job runner is the one the tests use


@pytest.mark.parametrize("name", ["Rechnung", "rechnung", "RECHNUNG"])
def test_the_server_names_cannot_be_made_again_in_a_vault(client: TestClient, operator: Account, name: str) -> None:
    home = shared_vault("Haushalt", operator)
    made = client.post("/api/v1/kinds", json={"name": name, "vault_id": home})
    assert made.status_code == 200 and made.json()["vault_id"] is None


def test_a_rule_that_names_a_kind_of_another_vault_sets_nothing_even_when_it_got_there_by_other_ways(
    client: TestClient, operator: Account,
) -> None:
    """The rules are checked when they are made; applying them looks again (a row put there by hand, or by an older
    version, must not set a kind its vault does not have)."""
    from app import clock
    from app.models import Rule

    jule = make_account("jule")
    home = shared_vault("Haushalt", operator, (jule, "manage"))
    work = shared_vault("Firma", operator, (jule, "manage"))
    with new_client(jule) as browser:
        elsewhere = make(browser, work, "Dienstvertrag")
    with SessionLocal() as db:
        db.add(Rule(vault_id=home, created_by=jule.id, position=1, on=True, hits=0,
                    when=[{"field": "text", "op": "contains", "values": ["Lindenau"]}],
                    then=[{"field": "kind", "value": elsewhere["id"]}], created_at=clock.now()))
        db.commit()
    with new_client(jule) as browser:
        document = upload_and_read(browser, "x.pdf", make_pdf(["Vertrag Lindenau"]), home)
    assert document["kind"] is None
