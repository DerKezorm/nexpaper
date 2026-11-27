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
