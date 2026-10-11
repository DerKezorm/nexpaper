"""Vaults: one of their own for every person, shared ones from the operator, who is in them with which right."""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.main import app
from app.models import MANAGE, OPERATOR, Account, Vault, VaultMember
from app.security import hash_password

from .conftest import PASSWORD, TAB, make_account, new_client, person, require_second_factor
from .papers import add_document, own_vault


def vault_count(owner: Account) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(Vault).where(Vault.personal_of == owner.id)) or 0)


# --- A vault of one's own -----------------------------------------------------------------------------------------------


def test_every_account_has_exactly_one_vault_of_its_own_whichever_way_it_was_made(client: TestClient) -> None:
    require_second_factor(False)
    # The first account, through the setup.
    setup = client.post("/api/v1/setup", json={"name": "first", "password": PASSWORD, "code": "test-setup-code"})
    assert setup.status_code in (200, 201), setup.text
    # By invitation.
    invite = client.post("/api/v1/invites", json={"days": 7})
    assert invite.status_code == 201, invite.text
    token = invite.json()["link"].rsplit("/", 1)[1]
    with TestClient(app, base_url="http://testserver", headers=TAB) as stranger:
        joined = stranger.post(f"/api/v1/invite/{token}", json={"name": "guest", "password": PASSWORD})
        assert joined.status_code in (200, 201), joined.text
    # Through the provider.
    from app.services.oidc_store import SqlStore

    with SessionLocal() as db:
        SqlStore(db).create_account("provider-person", invite=None, email="p@example.com")
        db.commit()
    # Straight into the database (as the tests of other parts do).
    direct = make_account("direct")
    with SessionLocal() as db:
        for account in db.scalars(select(Account)):
            personal = db.scalars(select(Vault).where(Vault.personal_of == account.id)).all()
            assert len(personal) == 1, account.name
            member = db.get(VaultMember, (personal[0].id, account.id))
            assert member is not None and member.right == MANAGE
        assert db.scalar(select(func.count()).select_from(Account)) == 4
    assert direct.id


def test_the_vault_of_a_person_is_named_after_them_and_its_folder_is_safe_and_unique() -> None:
    first = make_account("anna")
    with SessionLocal() as db:
        db.add(Account(name="con", password_hash=hash_password(PASSWORD)))
        db.add(Account(name="anna.2", display_name="ANNA", password_hash=hash_password(PASSWORD)))
        db.commit()
        folders = {v.personal_of: v.folder for v in db.scalars(select(Vault))}
    assert folders[first.id] == "anna"
    assert sorted(folders.values()) == ["ANNA 2", "_con", "anna"]


def test_two_accounts_made_at_the_same_moment_each_get_one_vault() -> None:
    names = [f"racer{i}" for i in range(8)]
    errors: list[BaseException] = []
    barrier = threading.Barrier(len(names))

    def make(name: str) -> None:
        try:
            barrier.wait(timeout=10)
            with SessionLocal() as db:
                db.add(Account(name=name, password_hash="x"))
                db.commit()
        except BaseException as exc:  # noqa: BLE001 - the test reports whatever went wrong
            errors.append(exc)

    threads = [threading.Thread(target=make, args=(n,)) for n in names]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    with SessionLocal() as db:
        accounts = list(db.scalars(select(Account)))
        assert len(accounts) == 8
        for account in accounts:
            assert db.scalar(select(func.count()).select_from(Vault).where(Vault.personal_of == account.id)) == 1
        folders = [v.folder.lower() for v in db.scalars(select(Vault))]
        assert len(folders) == len(set(folders))


def test_the_database_itself_refuses_a_second_personal_vault() -> None:
    account = make_account("solo")
    with SessionLocal() as db:
        db.add(Vault(name="another", folder="another", personal_of=account.id))
        with pytest.raises(IntegrityError):
            db.commit()


def test_the_owner_is_always_a_manager_of_their_vault_and_nobody_can_change_that() -> None:
    with person("owner") as owner, person("friend") as friend:
        mine = owner.get("/api/v1/vaults").json()
        assert len(mine) == 1 and mine[0]["my_right"] == "manage" and mine[0]["personal_of"] is not None
        vault_id = mine[0]["id"]
        owner_id = mine[0]["personal_of"]
        friend_id = friend.get("/api/v1/auth/me").json()["id"]
        given = owner.put(f"/api/v1/vaults/{vault_id}/members/{friend_id}", json={"right": "manage"})
        assert given.status_code == 200
        # Even a second manager cannot demote or remove the owner.
        assert friend.put(f"/api/v1/vaults/{vault_id}/members/{owner_id}", json={"right": "read"}).status_code == 409
        assert friend.delete(f"/api/v1/vaults/{vault_id}/members/{owner_id}").status_code == 409
        assert owner.put(f"/api/v1/vaults/{vault_id}/members/{owner_id}", json={"right": "edit"}).status_code == 409
        assert owner.delete(f"/api/v1/vaults/{vault_id}").status_code == 409
        assert owner.post(f"/api/v1/vaults/{vault_id}/leave").status_code == 409


def test_nobody_sees_the_personal_vault_of_another_person_not_even_the_operator(client: TestClient) -> None:
    operator = make_account("boss", OPERATOR)
    other = make_account("other")
    secret = own_vault(other)
    add_document(secret, other, "Private letter")
    with new_client(operator) as boss:
        assert [v["personal_of"] for v in boss.get("/api/v1/vaults").json()] == [operator.id]
        assert boss.get(f"/api/v1/vaults/{secret}").status_code == 404
        assert boss.get("/api/v1/documents").json()["items"] == []
        assert boss.get(f"/api/v1/documents?vault_id={secret}").json()["items"] == []
        assert boss.put(f"/api/v1/vaults/{secret}/members/{operator.id}", json={"right": "read"}).status_code == 404
        assert boss.delete(f"/api/v1/vaults/{secret}").status_code == 404
        assert boss.patch(f"/api/v1/vaults/{secret}", json={"name": "mine now"}).status_code == 404


# --- Shared vaults ----------------------------------------------------------------------------------------------------------


def test_only_the_operator_makes_a_shared_vault_and_only_in_a_browser(client: TestClient, operator: Account) -> None:
    made = client.post("/api/v1/vaults", json={"name": "  Household  ", "icon": "home"})
    assert made.status_code == 201
    body = made.json()
    assert body["name"] == "Household" and body["personal_of"] is None and body["my_right"] == "manage"
    assert [m["user_id"] for m in body["members"]] == [operator.id]
    with person("member") as member:
        assert member.post("/api/v1/vaults", json={"name": "Mine"}).status_code == 403
    token = client.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with TestClient(app, base_url="http://testserver") as device:
        answer = device.post("/api/v1/vaults", json={"name": "From a phone"}, headers={"Authorization": f"Bearer {token}"})
        assert answer.status_code == 403 and answer.json()["detail"]["code"] == "browser_only"
    for wrong in ({"name": ""}, {"name": "x" * 81}, {"name": "a\u0000b"}, {"name": "ok", "icon": "skull"}):
        assert client.post("/api/v1/vaults", json=wrong).status_code == 422, wrong


def test_the_folder_of_a_shared_vault_is_cleaned_and_a_rename_moves_nothing(client: TestClient, operator: Account) -> None:
    for name in ("../../etc", "CON", "a/b\\c", "x" * 80):
        made = client.post("/api/v1/vaults", json={"name": name})
        assert made.status_code == 201
        with SessionLocal() as db:
            folder = db.scalar(select(Vault.folder).where(Vault.id == made.json()["id"]))
        assert folder and "/" not in folder and "\\" not in folder and ".." not in folder and len(folder) <= 48
        assert folder.upper() != "CON"
    first = client.post("/api/v1/vaults", json={"name": "Same"}).json()["id"]
    second = client.post("/api/v1/vaults", json={"name": "SAME"}).json()["id"]
    with SessionLocal() as db:
        assert db.scalar(select(Vault.folder).where(Vault.id == first)) != db.scalar(select(Vault.folder).where(Vault.id == second))
    before = client.get(f"/api/v1/vaults/{first}").json()
    renamed = client.patch(f"/api/v1/vaults/{first}", json={"name": "Renamed"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Renamed"
    with SessionLocal() as db:
        assert db.scalar(select(Vault.folder).where(Vault.id == first)) == "Same"
    assert before["name"] == "Same"


def test_members_are_given_rights_by_managers_only(client: TestClient, operator: Account) -> None:
    tom, lea = make_account("tom"), make_account("lea")
    vault = client.post("/api/v1/vaults", json={"name": "Household"}).json()["id"]
    assert client.put(f"/api/v1/vaults/{vault}/members/{tom.id}", json={"right": "edit"}).status_code == 200
    assert client.put(f"/api/v1/vaults/{vault}/members/{lea.id}", json={"right": "read"}).status_code == 200
    with new_client(tom) as editor, new_client(lea) as reader:
        # Seeing the vault is not managing it.
        for who in (editor, reader):
            assert who.get(f"/api/v1/vaults/{vault}").status_code == 200
            assert who.put(f"/api/v1/vaults/{vault}/members/{lea.id}", json={"right": "manage"}).status_code == 403
            assert who.delete(f"/api/v1/vaults/{vault}/members/{tom.id}").status_code == 403
            assert who.patch(f"/api/v1/vaults/{vault}", json={"name": "Mine"}).status_code == 403
            assert who.delete(f"/api/v1/vaults/{vault}").status_code == 403
    with person("stranger") as stranger:
        assert stranger.get(f"/api/v1/vaults/{vault}").status_code == 404
        assert stranger.put(f"/api/v1/vaults/{vault}/members/{lea.id}", json={"right": "manage"}).status_code == 404
    shown = client.get(f"/api/v1/vaults/{vault}").json()["members"]
    assert {(m["name"], m["right"]) for m in shown} == {("tester", "manage"), ("tom", "edit"), ("lea", "read")}
    for wrong in ({"right": "owner"}, {"right": ""}, {}):
        assert client.put(f"/api/v1/vaults/{vault}/members/{lea.id}", json=wrong).status_code == 422
    assert client.put(f"/api/v1/vaults/{vault}/members/999999", json={"right": "read"}).status_code == 404


def test_a_vault_keeps_a_manager(client: TestClient, operator: Account) -> None:
    tom = make_account("tom")
    vault = client.post("/api/v1/vaults", json={"name": "Household"}).json()["id"]
    assert client.put(f"/api/v1/vaults/{vault}/members/{tom.id}", json={"right": "manage"}).status_code == 200
    assert client.put(f"/api/v1/vaults/{vault}/members/{operator.id}", json={"right": "read"}).status_code == 200
    with new_client(tom) as manager:
        # Tom is the last manager now.
        assert manager.put(f"/api/v1/vaults/{vault}/members/{tom.id}", json={"right": "edit"}).status_code == 409
        assert manager.delete(f"/api/v1/vaults/{vault}/members/{tom.id}").status_code == 409
        assert manager.post(f"/api/v1/vaults/{vault}/leave").status_code == 409
    assert client.post(f"/api/v1/vaults/{vault}/leave").status_code == 204
    assert client.get(f"/api/v1/vaults/{vault}").status_code == 404


def test_two_managers_changing_the_same_member_at_the_same_moment_leave_one_row(
    client: TestClient, operator: Account,
) -> None:
    tom, lea = make_account("tom"), make_account("lea")
    vault = client.post("/api/v1/vaults", json={"name": "Household"}).json()["id"]
    client.put(f"/api/v1/vaults/{vault}/members/{tom.id}", json={"right": "manage"})
    statuses: list[int] = []
    barrier = threading.Barrier(2)

    def give(who: Account, right: str) -> None:
        with new_client(who) as session:
            barrier.wait(timeout=10)
            statuses.append(session.put(f"/api/v1/vaults/{vault}/members/{lea.id}", json={"right": right}).status_code)

    threads = [threading.Thread(target=give, args=(operator, "read")), threading.Thread(target=give, args=(tom, "edit"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert statuses == [200, 200]
    with SessionLocal() as db:
        rows = list(db.scalars(select(VaultMember).where(VaultMember.vault_id == vault, VaultMember.user_id == lea.id)))
        assert len(rows) == 1 and rows[0].right in ("read", "edit")


def test_deleting_a_shared_vault_needs_it_empty_or_a_place_for_the_documents(client: TestClient, operator: Account) -> None:
    lea = make_account("lea")
    old = client.post("/api/v1/vaults", json={"name": "Old"}).json()["id"]
    new = client.post("/api/v1/vaults", json={"name": "New"}).json()["id"]
    client.put(f"/api/v1/vaults/{old}/members/{lea.id}", json={"right": "read"})
    doc = add_document(old, operator, "Contract")
    assert client.delete(f"/api/v1/vaults/{old}").status_code == 409
    assert client.delete(f"/api/v1/vaults/{old}?move_to={old}").status_code == 422
    assert client.delete(f"/api/v1/vaults/{old}?move_to=999999").status_code == 404
    with new_client(lea) as reader:
        # A reader of the target cannot take documents in.
        client.put(f"/api/v1/vaults/{new}/members/{lea.id}", json={"right": "read"})
        assert reader.delete(f"/api/v1/vaults/{old}?move_to={new}").status_code == 403
    assert client.delete(f"/api/v1/vaults/{old}?move_to={new}").status_code == 204
    assert client.get(f"/api/v1/vaults/{old}").status_code == 404
    assert client.get(f"/api/v1/documents/{doc}").json()["vault_id"] == new
    empty = client.post("/api/v1/vaults", json={"name": "Empty"}).json()["id"]
    assert client.delete(f"/api/v1/vaults/{empty}").status_code == 204


def test_the_people_list_shows_names_only(client: TestClient, operator: Account) -> None:
    make_account("tom")
    blocked = make_account("gone")
    with SessionLocal() as db:
        from app.clock import now

        row = db.get(Account, blocked.id)
        assert row is not None
        row.blocked_at = now()
        db.commit()
    listed = client.get("/api/v1/people").json()
    assert {p["name"] for p in listed} == {"tester", "tom"}
    assert all(set(p) == {"id", "name", "display_name"} for p in listed)


def test_a_vault_lists_what_it_holds(client: TestClient, operator: Account) -> None:
    vault = own_vault(operator)
    add_document(vault, operator, "One")
    add_document(vault, operator, "Two", content=None)
    listed = client.get(f"/api/v1/vaults/{vault}").json()
    assert listed["documents"] == 2 and listed["size"] > 0
    trashed = add_document(vault, operator, "Three")
    client.delete(f"/api/v1/documents/{trashed}")
    assert client.get(f"/api/v1/vaults/{vault}").json()["documents"] == 2


def test_a_personal_vault_is_named_as_its_person_is_called_now(client: TestClient, operator: Account) -> None:
    mine = client.get("/api/v1/vaults").json()[0]
    assert mine["name"] == "tester"
    assert client.put("/api/v1/me/profile", json={"display_name": "Tess Ter"}).status_code == 200
    renamed = client.get(f"/api/v1/vaults/{mine['id']}").json()
    assert renamed["name"] == "Tess Ter" and renamed["personal_of"] == operator.id
    with person("other") as other:
        client.put(f"/api/v1/vaults/{mine['id']}/members/{other.get('/api/v1/auth/me').json()['id']}", json={"right": "read"})
        assert [v["name"] for v in other.get("/api/v1/vaults").json()] == ["other", "Tess Ter"]


def test_a_personal_vault_keeps_the_name_of_its_person(client: TestClient, operator: Account) -> None:
    """Mutation M15: renaming a personal vault is refused, its icon may change."""
    mine = own_vault(operator)
    answer = client.patch(f"/api/v1/vaults/{mine}", json={"name": "Something else"})
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "personal_vault"
    assert client.get(f"/api/v1/vaults/{mine}").json()["name"] == "tester"
    assert client.patch(f"/api/v1/vaults/{mine}", json={"icon": "home"}).json()["icon"] == "home"


def test_the_members_are_set_in_one_write_and_a_refusal_changes_nothing(client: TestClient, operator: Account) -> None:
    tom, lea, ben = make_account("tom"), make_account("lea"), make_account("ben")
    vault = client.post("/api/v1/vaults", json={"name": "Household"}).json()["id"]
    client.put(f"/api/v1/vaults/{vault}/members/{tom.id}", json={"right": "read"})
    wanted = [{"user_id": operator.id, "right": "manage"}, {"user_id": tom.id, "right": "edit"},
              {"user_id": lea.id, "right": "read"}]
    answer = client.put(f"/api/v1/vaults/{vault}/members", json={"members": wanted})
    assert answer.status_code == 200
    assert [(m["name"], m["right"]) for m in answer.json()["members"]] == [
        ("tester", "manage"), ("tom", "edit"), ("lea", "read")]
    before = client.get(f"/api/v1/vaults/{vault}").json()["members"]
    # A list that would leave no manager, a person twice, somebody unknown: refused whole.
    for refused, status in (
        ([{"user_id": tom.id, "right": "edit"}, {"user_id": ben.id, "right": "read"}], 409),
        ([{"user_id": operator.id, "right": "manage"}, {"user_id": ben.id, "right": "read"},
          {"user_id": ben.id, "right": "edit"}], 422),
        ([{"user_id": operator.id, "right": "manage"}, {"user_id": ben.id, "right": "read"},
          {"user_id": 999_999, "right": "read"}], 404),
    ):
        assert client.put(f"/api/v1/vaults/{vault}/members", json={"members": refused}).status_code == status
        assert client.get(f"/api/v1/vaults/{vault}").json()["members"] == before
    # The owner of a personal vault stays in it as a manager.
    mine = own_vault(tom)
    with new_client(tom) as as_tom:
        assert as_tom.put(f"/api/v1/vaults/{mine}/members",
                          json={"members": [{"user_id": lea.id, "right": "manage"}]}).status_code == 409
        assert as_tom.put(f"/api/v1/vaults/{mine}/members", json={"members": [
            {"user_id": tom.id, "right": "manage"}, {"user_id": lea.id, "right": "read"}]}).status_code == 200
    # Out of the list is out of the vault.
    answer = client.put(f"/api/v1/vaults/{vault}/members",
                        json={"members": [{"user_id": operator.id, "right": "manage"}]})
    assert [m["name"] for m in answer.json()["members"]] == ["tester"]


def test_the_vaults_come_in_the_order_of_the_mock(client: TestClient, operator: Account) -> None:
    """The own vault first, then the personal vaults of others, then the shared ones as they were made; in each the
    owner first, then by right."""
    tom, lea = make_account("tom"), make_account("lea")
    household = client.post("/api/v1/vaults", json={"name": "Haushalt"}).json()["id"]
    holiday = client.post("/api/v1/vaults", json={"name": "Ferienwohnung"}).json()["id"]
    client.put(f"/api/v1/vaults/{household}/members",
               json={"members": [{"user_id": lea.id, "right": "read"}, {"user_id": tom.id, "right": "edit"},
                                 {"user_id": operator.id, "right": "manage"}]})
    with new_client(tom) as as_tom:
        as_tom.put(f"/api/v1/vaults/{own_vault(tom)}/members/{operator.id}", json={"right": "read"})
    listed = client.get("/api/v1/vaults").json()
    assert [v["name"] for v in listed] == ["tester", "tom", "Haushalt", "Ferienwohnung"]
    assert [v["id"] for v in listed[2:]] == [household, holiday]
    assert [m["name"] for m in listed[1]["members"]] == ["tom", "tester"]
    assert [m["name"] for m in listed[2]["members"]] == ["tester", "tom", "lea"]
