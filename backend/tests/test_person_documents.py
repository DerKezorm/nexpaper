"""verbinden 0.1.13 (``documents.about``): what nexpaper tells nexfolk about a contact (``services/person_documents.py``).
A document counts when its sender's name is the person's name, or the mail it came in with was sent from one of the
person's addresses; only in the vaults given, only what the account sees, never the trash; the newest one first."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

from app.db import SessionLocal
from app.models import EDIT, IntakeItem
from app.services import documents, person_documents
from app.services.verbinden_store import VerbindenStore
from app.vendor.nexverbinden import Person

from .conftest import make_account
from .papers import add_document, own_vault, shared_vault

PAT = Person(name="Pat Example", mails=("pat@example.com",))


def _ask(account: Any, person: Person = PAT, areas: list[int] | None = None) -> dict[str, Any]:
    caller = SimpleNamespace(account_id=account.id, areas=None if areas is None else [str(a) for a in areas])
    with SessionLocal() as db:
        return person_documents.about(VerbindenStore(db), caller, "documents.about", person)


def _came_by_mail(document_id: int, sender: str) -> None:
    with SessionLocal() as db:
        db.add(IntakeItem(document_id=document_id, source="mail", key=f"1:{document_id}:0",
                          detail={"from": sender, "subject": "Invoice", "file": "invoice.pdf"}))
        db.commit()


def test_a_document_counts_by_the_name_of_its_sender() -> None:
    kim = make_account("kim")
    add_document(own_vault(kim), kim, "Offer", sender="PAT example", date=date(2026, 3, 1))
    add_document(own_vault(kim), kim, "Other", sender="Sam Example", date=date(2026, 4, 1))
    found = _ask(kim)
    assert found["count"] == 1
    assert found["last"] == {"title": "Offer", "at": "2026-03-01"}
    assert found["next"] is None
    # One sender for all of them: the archive with that sender, a path in nexpaper only.
    assert found["open"] == "/?sender=PAT%20example"
    # Without a name, a sender of that name is nobody.
    assert _ask(kim, Person(mails=("nobody@example.org",)))["count"] == 0


def test_a_document_counts_by_the_address_its_mail_came_from() -> None:
    kim = make_account("kim")
    by_mail = add_document(own_vault(kim), kim, "Invoice 12", date=date(2026, 5, 2))
    _came_by_mail(by_mail, "Pat@Example.com")
    other = add_document(own_vault(kim), kim, "Newsletter", date=date(2026, 5, 3))
    _came_by_mail(other, "news@example.org")
    found = _ask(kim, Person(mails=("pat@example.com",)))
    assert found["count"] == 1 and found["last"]["title"] == "Invoice 12"
    # No sender to filter the archive by: the document itself.
    assert found["open"] == f"/dokument/{by_mail}"
    # The name alone does not reach a document that has no sender.
    assert _ask(kim, Person(name="Pat Example"))["count"] == 0


def test_only_the_vaults_given_count() -> None:
    kim = make_account("kim")
    op = make_account("op")
    office = shared_vault("Office", op, (kim, EDIT))
    add_document(own_vault(kim), kim, "Mine", sender="Pat Example", date=date(2026, 1, 1))
    add_document(office, kim, "Office", sender="Pat Example", date=date(2026, 2, 1))
    assert _ask(kim)["count"] == 2
    assert _ask(kim, areas=[own_vault(kim)])["count"] == 1
    assert _ask(kim, areas=[office])["last"]["title"] == "Office"
    assert _ask(kim, areas=[])["count"] == 0


def test_only_what_the_account_sees_counts() -> None:
    kim = make_account("kim")
    sam = make_account("sam")
    add_document(own_vault(sam), sam, "Sam's", sender="Pat Example", date=date(2026, 1, 1))
    # Even a vault named by the connection that the account is no member of shows nothing.
    assert _ask(kim)["count"] == 0
    assert _ask(kim, areas=[own_vault(sam)])["count"] == 0


def test_the_trash_does_not_count() -> None:
    kim = make_account("kim")
    kept = add_document(own_vault(kim), kim, "Kept", sender="Pat Example", date=date(2026, 1, 1))
    gone = add_document(own_vault(kim), kim, "Gone", sender="Pat Example", date=date(2026, 6, 1))
    with SessionLocal() as db:
        documents.trash(db, kim.id, gone)
        db.commit()
    found = _ask(kim)
    assert found["count"] == 1 and found["last"]["title"] == "Kept"
    assert kept


def test_the_newest_comes_first() -> None:
    kim = make_account("kim")
    add_document(own_vault(kim), kim, "Old", sender="Pat Example", date=date(2025, 12, 31))
    add_document(own_vault(kim), kim, "Undated", sender="Pat Example")
    add_document(own_vault(kim), kim, "New", sender="Pat Example", date=date(2026, 7, 14))
    add_document(own_vault(kim), kim, "Middle", sender="Pat Example", date=date(2026, 2, 1))
    found = _ask(kim)
    assert found["count"] == 4
    assert found["last"] == {"title": "New", "at": "2026-07-14"}


def test_the_route_answers_in_the_small_form() -> None:
    """Through the module: the route cuts the answer to its form (the contract cases go further)."""
    from app.vendor.nexverbinden import persons
    from app.vendor.nexverbinden.catalog import CATALOG

    kim = make_account("kim")
    add_document(own_vault(kim), kim, "Offer", sender="Pat Example", date=date(2026, 3, 1))
    purpose = CATALOG.purpose("nexpaper", "documents.about")
    assert purpose.person and purpose.level == "read"
    assert persons.cleaned(_ask(kim), purpose) == _ask(kim)
