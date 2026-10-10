"""Deleting a document in the trash for good, before its 30 days are over: who may, what goes, and what is left."""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Account, Document, Event, Version
from app.services import jobs, storage

from .conftest import make_account, new_client
from .papers import add_document, shared_vault


@pytest.fixture
def household(client: TestClient, operator: Account) -> dict[str, object]:
    tom, lea, ben = make_account("tom"), make_account("lea"), make_account("ben")
    vault = shared_vault("Household", operator, (tom, "edit"), (lea, "read"), (ben, "edit"))
    return {"vault": vault, "operator": operator, "tom": tom, "lea": lea, "ben": ben}


def path_of(document_id: int) -> object:
    with SessionLocal() as db:
        return storage.safe_path(db.scalar(select(Version.original_path).where(Version.document_id == document_id)))


def test_the_owner_deletes_their_document_in_the_trash_for_good_with_its_files(
        client: TestClient, household: dict[str, object]) -> None:
    tom = household["tom"]
    doc = add_document(household["vault"], tom, "Old bill", sender="Anbieter")  # type: ignore[arg-type]
    path = path_of(doc)
    with new_client(tom) as session:  # type: ignore[arg-type]
        assert session.delete(f"/api/v1/documents/{doc}").status_code == 200
        assert session.post(f"/api/v1/documents/{doc}/purge").status_code == 204
        assert session.get(f"/api/v1/documents/{doc}").status_code == 404
        assert session.get("/api/v1/documents?status=trash").json()["items"] == []
        # Asked again: as for any document that does not exist.
        assert session.post(f"/api/v1/documents/{doc}/purge").status_code == 404
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Document).where(Document.id == doc)) == 0
        assert db.scalar(select(func.count()).select_from(Event).where(Event.document_id == doc)) == 0
    assert path.is_file()  # type: ignore[attr-defined]
    jobs.run_pending()
    assert not path.exists()  # type: ignore[attr-defined]


def test_a_manager_of_the_vault_may_delete_anybodys_but_an_editor_only_their_own(
        client: TestClient, household: dict[str, object]) -> None:
    toms = add_document(household["vault"], household["tom"], "Tom's")  # type: ignore[arg-type]
    bens = add_document(household["vault"], household["ben"], "Ben's")  # type: ignore[arg-type]
    for doc in (toms, bens):
        assert client.delete(f"/api/v1/documents/{doc}").status_code == 200
    with new_client(household["tom"]) as tom:  # type: ignore[arg-type]
        refused = tom.post(f"/api/v1/documents/{bens}/purge")
        assert refused.status_code == 403 and refused.json()["detail"]["code"] == "forbidden"
    with new_client(household["lea"]) as lea:  # type: ignore[arg-type]
        assert lea.post(f"/api/v1/documents/{toms}/purge").status_code == 403
    assert client.get(f"/api/v1/documents/{bens}").json()["status"] == "trash"
    # The operator manages the vault.
    assert client.post(f"/api/v1/documents/{bens}/purge").status_code == 204
    assert client.get(f"/api/v1/documents/{bens}").status_code == 404


def test_only_what_is_in_the_trash_is_deleted_for_good(client: TestClient, household: dict[str, object]) -> None:
    doc = add_document(household["vault"], household["operator"], "Kept")  # type: ignore[arg-type]
    answer = client.post(f"/api/v1/documents/{doc}/purge")
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "not_in_trash"
    assert client.get(f"/api/v1/documents/{doc}").json()["status"] == "filed"


def test_an_owner_who_only_reads_now_may_not_delete_for_good(client: TestClient, household: dict[str, object]) -> None:
    lea = household["lea"]
    doc = add_document(household["vault"], lea, "Lea's")  # type: ignore[arg-type]
    assert client.delete(f"/api/v1/documents/{doc}").status_code == 200
    with new_client(lea) as session:  # type: ignore[arg-type]
        assert session.post(f"/api/v1/documents/{doc}/purge").status_code == 403
    assert client.get(f"/api/v1/documents/{doc}").json()["status"] == "trash"


def test_a_stranger_and_a_key_cannot_delete_for_good(client: TestClient, household: dict[str, object]) -> None:
    doc = add_document(household["vault"], household["operator"], "Private")  # type: ignore[arg-type]
    client.delete(f"/api/v1/documents/{doc}")
    with new_client(make_account("stranger")) as stranger:
        assert stranger.post(f"/api/v1/documents/{doc}/purge").status_code == 404


def test_two_requests_at_once_delete_it_once(client: TestClient, household: dict[str, object]) -> None:
    doc = add_document(household["vault"], household["operator"], "Twice")  # type: ignore[arg-type]
    client.delete(f"/api/v1/documents/{doc}")
    answers: list[int] = []
    gate = threading.Barrier(2)

    def go() -> None:
        with new_client(household["operator"]) as session:  # type: ignore[arg-type]
            gate.wait()
            answers.append(session.post(f"/api/v1/documents/{doc}/purge").status_code)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(answers) == [204, 404]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Document).where(Document.id == doc)) == 0
