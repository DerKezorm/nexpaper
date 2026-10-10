"""The list of tags a field offers (``/tags?vault_id=``) holds the tags of that vault and nothing of a vault the caller is
not in: asking for a foreign vault answers exactly like asking for one that does not exist."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models import Account

from .conftest import make_account, new_client
from .papers import add_document, own_vault, shared_vault


def names(listing: list[dict]) -> list[str]:
    return [item["name"] for item in listing]


def test_the_tags_of_a_vault_are_those_of_that_vault_alone(client: TestClient, operator: Account) -> None:
    household = shared_vault("Household", operator)
    mine = own_vault(operator)
    add_document(mine, operator, "Mine", tags=["Private"], content=None)
    add_document(household, operator, "Ours", tags=["Strom", "Haus"], content=None)
    assert names(client.get(f"/api/v1/tags?vault_id={household}").json()) == ["Haus", "Strom"]
    assert names(client.get(f"/api/v1/tags?vault_id={mine}").json()) == ["Private"]
    assert set(names(client.get("/api/v1/tags").json())) == {"Haus", "Private", "Strom"}


def test_a_foreign_vault_answers_like_one_that_is_not_there(client: TestClient, operator: Account) -> None:
    other = make_account("other")
    secret = own_vault(other)
    add_document(secret, other, "Theirs", tags=["Geheim-Mandat"], content=None)
    foreign = client.get(f"/api/v1/tags?vault_id={secret}")
    missing = client.get("/api/v1/tags?vault_id=987654")
    assert foreign.status_code == missing.status_code == 200
    assert foreign.json() == missing.json() == []
    assert "Geheim-Mandat" not in client.get("/api/v1/tags").text
    # The same for the senders of that vault: nothing tells a name from a vault one is not in.
    add_document(secret, other, "Theirs 2", sender="Geheime Kanzlei", content=None)
    assert client.get(f"/api/v1/senders?vault_id={secret}").json() == client.get("/api/v1/senders?vault_id=987654").json() == []


def test_a_member_who_only_reads_still_sees_the_tags_of_the_vault_and_a_stranger_does_not(
    client: TestClient, operator: Account,
) -> None:
    reader, stranger = make_account("reader"), make_account("stranger")
    household = shared_vault("Household", operator, (reader, "read"))
    add_document(household, operator, "Ours", tags=["Strom"], content=None)
    with new_client(reader) as session:
        assert names(session.get(f"/api/v1/tags?vault_id={household}").json()) == ["Strom"]
    with new_client(stranger) as session:
        assert session.get(f"/api/v1/tags?vault_id={household}").json() == []


def test_a_tag_seen_through_one_shared_document_does_not_open_the_rest_of_its_vault(
    client: TestClient, operator: Account,
) -> None:
    other = make_account("other")
    secret = own_vault(other)
    shown = add_document(secret, other, "Shared", tags=["Sichtbar"], content=None)
    add_document(secret, other, "Not shared", tags=["Verborgen"], content=None)
    with new_client(other) as session:
        session.put(f"/api/v1/documents/{shown}/shares/{operator.id}", json={"right": "read"})
    assert names(client.get(f"/api/v1/tags?vault_id={secret}").json()) == ["Sichtbar"]
