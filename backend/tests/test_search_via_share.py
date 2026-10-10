"""The archive's chip "Shared with me": the search narrowed to what the caller sees through a share alone, or to what
lies in their vaults, with the rights and the count following it."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models import Account

from .conftest import make_account, new_client
from .papers import add_document, own_vault, shared_vault
from .searching import give_text, search, titles


def test_via_share_narrows_the_search_to_what_was_shared_one_by_one(client: TestClient, operator: Account) -> None:
    jule, tom, lea = make_account("jule"), make_account("tom"), make_account("lea")
    house = shared_vault("Haushalt", jule, (tom, "edit"))
    mine = add_document(own_vault(jule), jule, "Eigene Rechnung")
    ours = add_document(house, tom, "Gemeinsame Rechnung")
    leas = add_document(own_vault(lea), lea, "Rechnung von Lea")
    hidden = add_document(own_vault(lea), lea, "Andere Rechnung von Lea")
    for doc in (mine, ours, leas, hidden):
        give_text(doc, "Eine Rechnung mit genug Text")
    with new_client(lea) as session:
        assert session.put(f"/api/v1/documents/{leas}/shares/{jule.id}", json={"right": "read"}).status_code == 200
    with new_client(jule) as session:
        assert titles(session, "rechnung", via_share="true") == ["Rechnung von Lea"]
        assert search(session, "rechnung", via_share="true")["total"] == 1
        assert sorted(titles(session, "rechnung", via_share="false")) == ["Eigene Rechnung", "Gemeinsame Rechnung"]
        assert search(session, "rechnung", via_share="false")["total"] == 2
        assert len(titles(session, "rechnung")) == 3
        # Without words too: the archive's list is a search with filters only.
        assert titles(session, "", via_share="true") == ["Rechnung von Lea"]
    # Somebody without shares finds nothing there, and never Lea's other document.
    with new_client(tom) as session:
        assert titles(session, "rechnung", via_share="true") == []
        assert titles(session, "", via_share="false") == ["Gemeinsame Rechnung"]
