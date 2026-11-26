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
