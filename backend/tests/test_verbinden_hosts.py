"""nexpaper as the host of other nex apps (verbinden 0.1.1, AUFTRAG Runde 2): nextime reads the deadlines
(``deadlines.read``, Teil A), nexmail adds documents (``documents.add``, Teil B). Each purpose opens its routes and
nothing else (403 ``purpose_missing``), only in the vaults given at the consent. Through the module's contract world
(the partner a reference app of the catalog), with each partner in turn."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent / "nexverbinden"))

import verbinden_contract as contract

from .nexverbinden_adapter import Adapter


def _world(partner: str, tmp_path: Path) -> Iterator[Any]:
    adapter = Adapter()
    adapter.partner = partner
    yield from contract.world(contract.package(adapter), adapter, tmp_path)


@pytest.fixture
def nextime(tmp_path: Path) -> Iterator[Any]:
    yield from _world("nextime", tmp_path)


@pytest.fixture
def nexmail(tmp_path: Path) -> Iterator[Any]:
    yield from _world("nexmail", tmp_path)


def _status(answer: Any) -> Any:
    return getattr(answer, "status", None), getattr(answer, "code", None)


def test_nextime_reads_the_deadlines_and_nothing_else(nextime: Any) -> None:
    assert nextime.connect("partner").status_code == 200
    found = nextime.partner_calls_app("/api/v1/deadlines")
    assert _status(found)[0] == 200
    assert {"Electricity", "Rent"} <= {item["title"] for item in found.data["soon"]["items"]}
    assert _status(nextime.partner_calls_app("/api/v1/vaults")) == (403, "purpose_missing")
    assert _status(nextime.partner_calls_app("/api/v1/documents")) == (403, "purpose_missing")


def test_nexmail_learns_the_vaults_to_add_to_and_reads_no_deadline(nexmail: Any) -> None:
    assert nexmail.connect("partner").status_code == 200
    found = nexmail.partner_calls_app("/api/v1/vaults")
    assert _status(found)[0] == 200 and len(found.data) == 2
    assert _status(nexmail.partner_calls_app("/api/v1/deadlines")) == (403, "purpose_missing")


def test_a_vault_not_given_stays_out(nextime: Any) -> None:
    params = nextime.consent_params(nextime.start("partner").json()["go"])
    owner = nextime.app.client("owner")
    first = owner.get(f"{nextime.pkg.PREFIX}/consent", params=params).json()["areas"][0]["id"]
    agreed = owner.post(f"{nextime.pkg.PREFIX}/consent", json={**params, "allow": True, "areas": [first]})
    back = nextime.consent_params(agreed.json()["redirect"])
    assert nextime.partner.client("owner").post(f"{nextime.pkg.PREFIX}/return", json=back).status_code == 200
    found = nextime.partner_calls_app("/api/v1/deadlines")
    assert {str(item["vault_id"]) for item in found.data["soon"]["items"]} == {str(first)}


@pytest.fixture
def nexfolk(tmp_path: Path) -> Iterator[Any]:
    yield from _world("nexfolk", tmp_path)


def _calls(dependant: Any) -> Iterator[Any]:
    for inner in dependant.dependencies:
        yield inner.call
        yield from _calls(inner)


def test_nexfolk_asks_about_a_person_and_opens_nothing_in_the_api(nexfolk: Any) -> None:
    """verbinden 0.1.13: a connection with nothing but ``documents.about`` (read) opens no route of ``/api/v1``: every
    route that reads asks for its own purpose (``deps.CONNECTION_READS``, uploads ``documents.add``), so the token gets
    403 ``purpose_missing`` there and 401 on routes for people and devices; only the module's fixed place answers."""
    from fastapi.routing import APIRoute
    from verbinden_partner import ROLES

    from app.deps import require_reader, require_uploader

    from .test_routes import concrete, every_route

    w = nexfolk
    assert w.connect("partner").status_code == 200
    connection = w.app.store.connection(w.app.account_id("owner"), "nexfolk")
    assert connection.grants == ("documents.about",)
    token = w.pkg.access(w.partner.store, w.partner.config, ROLES["owner"][0], "nexpaper", _now()).token
    program = w.program()
    asked = {"Authorization": f"Bearer {token}"}
    assert program.get("/api/connect/about/documents.about", params={"name": "Pat"}, headers=asked).status_code == 200
    checked = 0
    for route in every_route():
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1/"):
            continue
        path = concrete(route.path)
        calls = set(_calls(route.dependant))
        for method in sorted(route.methods & {"GET", "POST"}):
            if method == "POST" and require_uploader not in calls:
                continue
            found = program.request(method, path, headers=asked)
            if require_reader in calls or require_uploader in calls:
                assert found.status_code == 403, (method, path, found.status_code)
                assert found.json()["detail"]["code"] == "purpose_missing", (method, path)
                checked += 1
            elif 200 <= found.status_code < 300:
                # Only what anybody reaches without any sign-in (the health, the ways to sign in).
                assert program.request(method, path).status_code == found.status_code, (method, path)
    # The reading routes of the API are many; a handful would mean the walk lost them.
    assert checked >= 20, checked


def _now() -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _limited_to_own_vault(w: Any) -> tuple[dict[str, str], int, int]:
    """nexmail connected with the owner's own vault only: the token's header, the vault given and one not given."""
    from verbinden_partner import ROLES

    from app.db import SessionLocal
    from app.models import Account, Document

    from .papers import own_vault

    params = w.consent_params(w.start("partner").json()["go"])
    owner = w.app.client("owner")
    with SessionLocal() as db:
        given = own_vault(db.get(Account, w.app.account_id("owner")))
        other = next(row.vault_id for row in db.query(Document).all() if row.vault_id != given)
    agreed = owner.post(f"{w.pkg.PREFIX}/consent", json={**params, "allow": True, "areas": [given]})
    back = w.consent_params(agreed.json()["redirect"])
    assert w.partner.client("owner").post(f"{w.pkg.PREFIX}/return", json=back).status_code == 200
    token = w.pkg.access(w.partner.store, w.partner.config, ROLES["owner"][0], "nexpaper", _now()).token
    return {"Authorization": f"Bearer {token}"}, given, other


def test_a_connection_does_not_upload_in_pieces(nexmail: Any) -> None:
    """The upload in pieces could put a file into a vault not given, make a new version of any document the account
    may change, tell the title of a document with the same file, and list every open upload of the account: a
    connection's token gets 403 ``purpose_missing`` on each of its routes (Befundsuche 28.11.2026)."""
    from app.db import SessionLocal
    from app.models import Document

    from .intake import sha
    from .papers import PDF

    asked, given, other = _limited_to_own_vault(nexmail)
    with SessionLocal() as db:
        foreign = next(row.id for row in db.query(Document).all() if row.vault_id == other)
    program = nexmail.program()
    announced = {"filename": "a.pdf", "size": len(PDF), "sha256": sha(PDF)}
    for body in ({**announced, "vault_id": other}, {**announced, "document_id": foreign}, {**announced, "vault_id": given},
                 announced):
        found = program.post("/api/v1/uploads", json=body, headers=asked)
        assert found.status_code == 403, (body, found.text)
        assert found.json()["detail"]["code"] == "purpose_missing"
    some = "0" * 32
    for method, path in (("GET", "/api/v1/uploads"), ("GET", f"/api/v1/uploads/{some}"),
                         ("PUT", f"/api/v1/uploads/{some}?offset=0"), ("POST", f"/api/v1/uploads/{some}/finish"),
                         ("DELETE", f"/api/v1/uploads/{some}")):
        found = program.request(method, path, headers=asked)
        assert found.status_code == 403, (method, path, found.text)
        assert found.json()["detail"]["code"] == "purpose_missing"
    with SessionLocal() as db:
        assert db.query(Document).filter(Document.vault_id == other).count() == 1


def test_a_connection_adds_whole_files_to_its_vault_and_hears_of_no_other_document(nexmail: Any) -> None:
    """``POST /documents`` stays the connection's way in (nexmail), in the vaults given; like a key it hears nothing of a
    document of the account with the same file (a title from a vault not given)."""
    from app.db import SessionLocal
    from app.models import Account

    from .papers import PDF, add_document

    asked, given, other = _limited_to_own_vault(nexmail)
    secret = PDF + b"% only in the vault not given" + bytes([10])
    with SessionLocal() as db:
        add_document(other, db.get(Account, nexmail.app.account_id("owner")), "Secret contract", content=secret)
    program = nexmail.program()
    refused = program.post("/api/v1/documents", params={"vault_id": other}, headers=asked,
                           files={"file": ("a.pdf", PDF, "application/pdf")})
    assert refused.status_code == 404
    taken = program.post("/api/v1/documents", params={"vault_id": given}, headers=asked,
                         files={"file": ("a.pdf", secret, "application/pdf")})
    assert taken.status_code == 201, taken.text
    item = taken.json()["items"][0]
    assert item["status"] == "accepted"
    assert item["duplicate"] is None and item["document"]["duplicate"] is None
    assert "Secret contract" not in taken.text
