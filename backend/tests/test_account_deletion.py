"""Deleting an account whose own vault holds documents: the operator chooses where they go (another person, a shared
vault, or away for good), types the account's name, and everything happens in one write."""

from __future__ import annotations

import threading
import time
from datetime import date

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.db import SessionLocal
from app.models import Account, Document, DocumentTag, Job, Link, Sender, Share, Tag, Vault, VaultMember
from app.services import documents, jobs, storage, vaults

from .conftest import PASSWORD, make_account, new_client
from .papers import add_document, own_vault, shared_vault


def delete(client: TestClient, account: Account, **body: object) -> object:
    payload = {"current_password": PASSWORD, "confirm_name": account.name, **body}
    return client.request("DELETE", f"/api/v1/accounts/{account.id}", json=payload)


def vault_of(document_id: int) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(Document.vault_id).where(Document.id == document_id)) or 0)


def exists(account: Account) -> bool:
    with SessionLocal() as db:
        return db.get(Account, account.id) is not None


@pytest.fixture
def leaver(client: TestClient, operator: Account) -> dict[str, object]:
    """A person with two documents in their own vault (one in the trash), a link they made, a share to them, and a
    heir."""
    jule, tom, lea = make_account("jule"), make_account("tom"), make_account("lea")
    mine = own_vault(jule)
    filed = add_document(mine, jule, "Strom", sender="Stadtwerke Lindenau", tags=["Haus", "Energie"],
                         date=date(2026, 3, 14))
    trashed = add_document(mine, jule, "Alt", sender="Stadtwerke Lindenau")
    with new_client(jule) as as_jule:
        assert as_jule.delete(f"/api/v1/documents/{trashed}").status_code == 200
        link = as_jule.post(f"/api/v1/documents/{filed}/links",
                            json={"recipient": "Steuerbüro", "days": 7, "allow_download": True})
        assert link.status_code == 201
        # Tom already had one document shared with him, Lea another one.
        assert as_jule.put(f"/api/v1/documents/{filed}/shares/{tom.id}", json={"right": "read"}).status_code == 200
        assert as_jule.put(f"/api/v1/documents/{filed}/shares/{lea.id}", json={"right": "edit"}).status_code == 200
    household = shared_vault("Haushalt", operator, (jule, "edit"))
    given = add_document(household, operator, "Haushalt Vertrag")
    with new_client(operator) as as_operator:
        assert as_operator.put(f"/api/v1/documents/{given}/shares/{make_account('anna').id}",
                               json={"right": "read"}).status_code == 200
    return {"jule": jule, "tom": tom, "lea": lea, "mine": mine, "filed": filed, "trashed": trashed,
            "token": link.json()["token"], "household": household}


def test_without_a_choice_the_number_of_documents_comes_back_and_nothing_changes(
    client: TestClient, leaver: dict[str, object],
) -> None:
    jule = leaver["jule"]
    answer = delete(client, jule)  # type: ignore[arg-type]
    assert answer.status_code == 409  # type: ignore[attr-defined]
    detail = answer.json()["detail"]  # type: ignore[attr-defined]
    assert detail["code"] == "personal_vault_not_empty" and detail["documents"] == 2
    assert exists(jule)  # type: ignore[arg-type]
    assert vault_of(leaver["filed"]) == leaver["mine"]  # type: ignore[arg-type]
    # The operator learns the number beforehand, never what the documents are.
    preview = client.get(f"/api/v1/accounts/{jule.id}/leaving").json()  # type: ignore[attr-defined]
    assert preview["documents"] == 2 and preview["sole_manager_of"] == []
    assert [v["name"] for v in preview["shared_vaults"]] == ["Haushalt"]
    assert set(preview) == {"documents", "sole_manager_of", "shared_vaults", "heirs_you_see"}


def test_the_name_has_to_be_typed_as_it_is(client: TestClient, leaver: dict[str, object]) -> None:
    jule = leaver["jule"]
    for wrong in ("", "Jule", "tom", "jule2"):
        answer = delete(client, jule, confirm_name=wrong, documents="delete_documents")  # type: ignore[arg-type]
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "name_mismatch"  # type: ignore[attr-defined]
    assert exists(jule)  # type: ignore[arg-type]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 3


def test_an_empty_vault_goes_with_its_person(client: TestClient, operator: Account) -> None:
    empty = make_account("empty")
    vault = own_vault(empty)
    assert delete(client, empty).status_code == 204  # type: ignore[attr-defined]
    with SessionLocal() as db:
        assert db.get(Vault, vault) is None and db.get(Account, empty.id) is None


def test_documents_go_to_another_person_who_becomes_their_owner(client: TestClient, leaver: dict[str, object]) -> None:
    jule, tom = leaver["jule"], leaver["tom"]
    heir_vault = own_vault(tom)  # type: ignore[arg-type]
    with new_client(tom) as as_tom:  # type: ignore[arg-type]
        since = as_tom.get("/api/v1/changes").json()["next"]
    answer = delete(client, jule, documents="transfer_to_user", target_user_id=tom.id)  # type: ignore[arg-type,attr-defined]
    assert answer.status_code == 204, answer.text  # type: ignore[attr-defined]
    with SessionLocal() as db:
        moved = list(db.scalars(select(Document).where(Document.id.in_([leaver["filed"], leaver["trashed"]]))))
        assert {d.vault_id for d in moved} == {heir_vault}
        assert {d.owner_id for d in moved} == {tom.id}  # type: ignore[attr-defined]
        assert {d.status for d in moved} == {"filed", "trash"}
        # Sender and tags are the heir's vault's own now; the old vault and its rows are gone.
        sender = db.get(Sender, moved[0].sender_id)
        assert sender is not None and sender.vault_id == heir_vault and sender.name == "Stadtwerke Lindenau"
        tags = db.scalars(select(Tag).join(DocumentTag, DocumentTag.tag_id == Tag.id)
                          .where(DocumentTag.document_id == leaver["filed"])).all()
        assert {t.vault_id for t in tags} == {heir_vault} and {t.name for t in tags} == {"Haus", "Energie"}
        assert db.get(Vault, leaver["mine"]) is None
        assert db.scalar(select(func.count()).select_from(Sender).where(Sender.vault_id == leaver["mine"])) == 0
        # The share to the heir says nothing any more; Lea's stays. The link Jule made ended.
        assert db.get(Share, (leaver["filed"], tom.id)) is None  # type: ignore[attr-defined]
        assert db.get(Share, (leaver["filed"], leaver["lea"].id)) is not None  # type: ignore[attr-defined]
        assert db.scalar(select(Link.revoked_at)) is not None
        # The files follow their new place.
        assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "rename")) >= 2
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    jobs.run_pending()
    with SessionLocal() as db:
        path = db.scalar(select(documents.Version.original_path).where(documents.Version.document_id == leaver["filed"]))
        assert path is not None and path.startswith("tom/") and storage.safe_path(path).is_file()
    with new_client(tom) as as_tom:  # type: ignore[arg-type]
        mine = as_tom.get(f"/api/v1/documents/{leaver['filed']}").json()
        assert mine["owner"]["name"] == "tom" and mine["my_right"] == "manage" and mine["via_share"] is False
        feed = as_tom.get(f"/api/v1/changes?since={since}").json()["items"]
        assert {i["document"]["id"] for i in feed if i["type"] == "document"} >= {leaver["filed"], leaver["trashed"]}
        events = as_tom.get(f"/api/v1/documents/{leaver['filed']}/events").json()
        # The history says it was taken over when the account was deleted, and who did it.
        assert events[0]["action"] == "taken_over" and events[0]["detail"]["account"] == "jule"
        assert events[0]["by"]["name"] == "tester"
    assert TestClient(client.app).get(f"/api/v1/l/{leaver['token']}").status_code == 404


def test_documents_go_to_a_shared_vault(client: TestClient, leaver: dict[str, object]) -> None:
    jule, household = leaver["jule"], leaver["household"]
    # A personal vault is not a place to choose, nor is a vault that does not exist.
    for target in (own_vault(leaver["tom"]), 999_999):  # type: ignore[arg-type]
        answer = delete(client, jule, documents="transfer_to_vault", target_vault_id=target)  # type: ignore[arg-type]
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "invalid_target"  # type: ignore[attr-defined]
        assert exists(jule)  # type: ignore[arg-type]
    for nobody in (jule.id, 999_999):  # type: ignore[attr-defined]
        answer = delete(client, jule, documents="transfer_to_user", target_user_id=nobody)  # type: ignore[arg-type]
        assert answer.status_code == 422  # type: ignore[attr-defined]
    # A blocked person is no heir (mutation N15 of the second review).
    from app import clock

    with SessionLocal() as db:
        blocked = db.get(Account, leaver["lea"].id)  # type: ignore[attr-defined]
        assert blocked is not None
        blocked.blocked_at = clock.now()
        db.commit()
    answer = delete(client, jule, documents="transfer_to_user", target_user_id=leaver["lea"].id)  # type: ignore[arg-type,attr-defined]
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "invalid_target"  # type: ignore[attr-defined]
    assert exists(jule)  # type: ignore[arg-type]
    answer = delete(client, jule, documents="transfer_to_vault", target_vault_id=household)  # type: ignore[arg-type]
    assert answer.status_code == 204  # type: ignore[attr-defined]
    assert vault_of(leaver["filed"]) == household == vault_of(leaver["trashed"])  # type: ignore[arg-type]
    with SessionLocal() as db:
        assert db.scalar(select(Document.owner_id).where(Document.id == leaver["filed"])) is None
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []


def test_documents_can_go_for_good(client: TestClient, leaver: dict[str, object]) -> None:
    jule, lea = leaver["jule"], leaver["lea"]
    with SessionLocal() as db:
        files = [v.original_path for v in db.scalars(select(documents.Version).where(
            documents.Version.document_id.in_([leaver["filed"], leaver["trashed"]])))]
    assert all(storage.safe_path(p).is_file() for p in files)
    with new_client(lea) as as_lea:  # type: ignore[arg-type]
        since = as_lea.get("/api/v1/changes").json()["next"]
    assert delete(client, jule, documents="delete_documents").status_code == 204  # type: ignore[arg-type,attr-defined]
    with SessionLocal() as db:
        assert db.get(Document, leaver["filed"]) is None and db.get(Document, leaver["trashed"]) is None
        assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "delete_files")) == 2
    # The files go in the background.
    jobs.run_pending()
    assert not any(storage.safe_path(p).exists() for p in files)
    with new_client(lea) as as_lea:  # type: ignore[arg-type]
        feed = as_lea.get(f"/api/v1/changes?since={since}").json()["items"]
        assert any(i["type"] == "gone" and i["document_id"] == leaver["filed"] for i in feed)
    # The household's document and its share are untouched.
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 1


def test_a_person_who_manages_a_shared_vault_alone_is_kept(client: TestClient, operator: Account) -> None:
    solo = make_account("solo")
    vault = shared_vault("Werkstatt", operator, (solo, "manage"))
    with SessionLocal() as db:
        vaults.remove_member(db, operator.id, vault, operator.id)
    preview = client.get(f"/api/v1/accounts/{solo.id}/leaving").json()
    assert preview["sole_manager_of"] == [{"id": vault, "name": "Werkstatt"}]
    answer = delete(client, solo, documents="delete_documents")
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "last_manager"  # type: ignore[attr-defined]
    assert exists(solo)


def test_others_in_the_vault_lose_it_and_keep_what_comes_back(client: TestClient, operator: Account) -> None:
    """Somebody who had been let into the person's own vault gets the marker; the documents they still see later (in
    the heir's vault) come after it."""
    jule, tom = make_account("jule"), make_account("tom")
    doc = add_document(own_vault(jule), jule, "Kontoauszug")
    with SessionLocal() as db:
        vaults.set_member(db, jule.id, own_vault(jule), tom.id, "read")
    with new_client(tom) as as_tom:
        since = as_tom.get("/api/v1/changes").json()["next"]
        assert delete(client, jule, documents="transfer_to_user", target_user_id=tom.id).status_code == 204
        items = as_tom.get(f"/api/v1/changes?since={since}").json()["items"]
    kinds = [(i["type"], i.get("vault_id") or (i.get("document") or {}).get("id")) for i in items]
    lost = kinds.index(("vault_lost", own_vault_id_of(items)))
    assert ("document", doc) in kinds[lost + 1:]


def own_vault_id_of(items: list[dict]) -> int:
    return next(i["vault_id"] for i in items if i["type"] == "vault_lost")


def test_the_operator_alone_asks_and_deletes(client: TestClient, leaver: dict[str, object]) -> None:
    jule = leaver["jule"]
    with new_client(leaver["tom"]) as as_tom:  # type: ignore[arg-type]
        assert as_tom.get(f"/api/v1/accounts/{jule.id}/leaving").status_code == 403  # type: ignore[attr-defined]
        answer = as_tom.request("DELETE", f"/api/v1/accounts/{jule.id}",  # type: ignore[attr-defined]
                                json={"current_password": PASSWORD, "confirm_name": "jule",
                                      "documents": "delete_documents"})
        assert answer.status_code == 403
    assert exists(jule)  # type: ignore[arg-type]


def test_an_upload_or_a_change_at_the_same_moment_comes_before_or_after_never_in_between(
    client: TestClient, leaver: dict[str, object], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While the deletion holds the write lock, a new document for the person's vault and a change to one of its
    documents wait; afterwards the new one finds no vault (404) and the change lands on the document in its new place.
    Nothing is left in a vault that is gone."""
    jule, tom, lea = leaver["jule"], leaver["tom"], leaver["lea"]
    outcome: dict[str, object] = {}
    started = threading.Event()

    def upload() -> None:
        started.set()
        try:
            with SessionLocal() as db:
                outcome["upload"] = documents.create(db, vault_id=leaver["mine"], owner_id=jule.id,  # type: ignore[arg-type,attr-defined]
                                                     title="Late", content=b"%PDF-1.4 late").id
        except HTTPException as exc:
            outcome["upload"] = exc.status_code

    def change() -> None:
        with SessionLocal() as db:
            outcome["change"] = documents.update_fields(db, lea.id, leaver["filed"], {"title": "Changed"}).vault_id  # type: ignore[arg-type,attr-defined]

    real = vaults._sole_manager_of
    others: list[threading.Thread] = []

    def slow_check(db: object, account_id: int, own: int | None) -> list:
        # The deletion has counted the documents and holds the lock: the two writers start here and have to wait.
        others.extend([threading.Thread(target=upload, daemon=True), threading.Thread(target=change, daemon=True)])
        for thread in others:
            thread.start()
        started.wait(5)
        time.sleep(0.4)
        assert "upload" not in outcome and "change" not in outcome, "a writer got in while the deletion was deciding"
        return real(db, account_id, own)  # type: ignore[arg-type]

    monkeypatch.setattr(vaults, "_sole_manager_of", slow_check)
    answer = delete(client, jule, documents="transfer_to_user", target_user_id=tom.id)  # type: ignore[arg-type,attr-defined]
    for thread in others:
        thread.join(20)
    assert answer.status_code == 204  # type: ignore[attr-defined]
    assert outcome["upload"] == 404
    assert outcome["change"] == own_vault(tom)  # type: ignore[arg-type]
    with SessionLocal() as db:
        assert db.scalar(select(Document.title).where(Document.id == leaver["filed"])) == "Changed"
        assert db.scalar(select(func.count()).select_from(Document).where(
            Document.vault_id.not_in(select(Vault.id)))) == 0
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
        assert db.scalar(select(func.count()).select_from(VaultMember).where(
            VaultMember.vault_id == leaver["mine"])) == 0


def test_many_uploads_while_deleting_leave_nothing_behind(client: TestClient, operator: Account) -> None:
    """Writers that keep adding to the vault while it is deleted: every document they made is with the heir afterwards,
    every later one was refused."""
    jule, tom = make_account("jule"), make_account("tom")
    mine = own_vault(jule)
    add_document(mine, jule, "First")
    made: list[int] = []
    refused: list[int] = []
    stop = threading.Event()

    def writer() -> None:
        while not stop.is_set():
            try:
                with SessionLocal() as db:
                    made.append(documents.create(db, vault_id=mine, owner_id=jule.id, title="More").id)
            except HTTPException as exc:
                refused.append(exc.status_code)
                return

    threads = [threading.Thread(target=writer, daemon=True) for _ in range(3)]
    for thread in threads:
        thread.start()
    time.sleep(0.2)
    try:
        answer = delete(client, jule, documents="transfer_to_user", target_user_id=tom.id)
    finally:
        stop.set()
        for thread in threads:
            thread.join(20)
    assert answer.status_code == 204
    assert made and set(refused) <= {404}
    with SessionLocal() as db:
        places = set(db.scalars(select(Document.vault_id).where(Document.id.in_(made))))
        assert places == {own_vault(tom)}
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []


def test_the_operator_may_take_the_documents_but_it_is_said_and_written_down(
    client: TestClient, operator: Account,
) -> None:
    """By decision of the project, the operator may choose themselves or a vault they are in. The dialog is told so beforehand,
    and the history of every document says it was taken over, when which account was deleted, by whom."""
    lea, tom = make_account("lea"), make_account("tom")
    private = add_document(own_vault(lea), lea, "Befund", content=None)
    assert client.get(f"/api/v1/documents/{private}").status_code == 404, "before, the operator does not see it"
    household = shared_vault("Haushalt", operator)
    elsewhere = shared_vault("Werkstatt", tom)
    with SessionLocal() as db:
        vaults.set_member(db, tom.id, own_vault(tom), operator.id, "read")
    preview = client.get(f"/api/v1/accounts/{lea.id}/leaving").json()
    assert sorted(preview["heirs_you_see"]) == sorted([operator.id, tom.id])
    assert {v["id"]: v["you_see"] for v in preview["shared_vaults"]} == {household: True, elsewhere: False}
    answer = delete(client, lea, documents="transfer_to_user", target_user_id=operator.id)
    assert answer.status_code == 204
    shown = client.get(f"/api/v1/documents/{private}").json()
    assert shown["owner"]["name"] == "tester"
    taken = client.get(f"/api/v1/documents/{private}/events").json()[0]
    assert taken["action"] == "taken_over" and taken["detail"]["account"] == "lea" and taken["by"]["name"] == "tester"
