"""Exports with the documents that go with them (N2): directly, only what the person sees in a vault of theirs, never
from the trash, each once, also outside the period; a column of the list names their files; the limits hold for all."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date
from typing import Any

import pytest

from app import clock
from app.db import SessionLocal
from app.models import Account, Related
from app.services import exports

from .conftest import new_client
from .papers import PDF, add_document, own_vault
from .test_exports import DE, World, body, clean_folders, pack, zip_of  # noqa: F401 - the fixture is used by name


def pair(one: int, other: int) -> None:
    """Two documents that go with each other, straight into the database (also where nobody may set it: the test of
    what the person must never get)."""
    with SessionLocal() as db:
        db.add(Related(low_id=min(one, other), high_id=max(one, other), created_at=clock.now()))
        db.commit()


@pytest.fixture
def world(client: Any, operator: Account) -> World:
    built = World(operator)
    # Outside the period, goes with both documents of the period: comes along once.
    pair(built.strom, built.old)
    pair(built.rechnung, built.old)
    # Goes only with ``old``: no chains.
    built.chain = add_document(built.mine, built.jule, "Kette", date=date(2024, 2, 2))  # type: ignore[attr-defined]
    pair(built.old, built.chain)  # type: ignore[attr-defined]
    # Tom's own, never seen by jule.
    pair(built.strom, built.foreign)
    # Tom's, shared with jule to read: seen, but through a share only (the export takes vaults): stays out.
    built.lent = add_document(own_vault(built.tom), built.tom, "Toms Leihgabe", date=date(2026, 7, 7))  # type: ignore[attr-defined]
    with new_client(built.tom) as tom:
        assert tom.put(f"/api/v1/documents/{built.lent}/shares/{built.jule.id}",  # type: ignore[attr-defined]
                       json={"right": "read"}).status_code == 200
    pair(built.strom, built.lent)  # type: ignore[attr-defined]
    # In the trash: stays out.
    built.binned = add_document(built.firma, built.jule, "Weggeworfen", date=date(2023, 1, 1))  # type: ignore[attr-defined]
    pair(built.rechnung, built.binned)  # type: ignore[attr-defined]
    with new_client(built.jule) as jule:
        assert jule.delete(f"/api/v1/documents/{built.binned}").status_code in (200, 204)  # type: ignore[attr-defined]
    return built


def preview(jule: Any, world: World, **extra: Any) -> dict[str, Any]:
    params = {"vault_ids": [world.mine, world.firma], "date_from": "2026-01-01", "date_to": "2026-12-31", **extra}
    answer = jule.get("/api/v1/exports/preview", params=params, headers=DE)
    assert answer.status_code == 200, answer.text
    return answer.json()  # type: ignore[no-any-return]


def test_the_preview_counts_what_comes_along(world: World) -> None:
    with new_client(world.jule) as jule:
        without = preview(jule, world)
        assert without["documents"] == 2
        found = preview(jule, world, related="true")
        assert found["documents"] == 3 and found["total"] == 8400 + 41250 + 100
        assert found["size"] == 3 * len(PDF)


def test_the_zip_takes_what_goes_with_them_and_never_what_the_person_may_not_see(world: World) -> None:
    with new_client(world.jule) as jule:
        made = jule.post("/api/v1/exports", json=body(world, related=True), headers=DE)
        assert made.status_code == 201 and made.json()["related"] is True
        pack()
        shown = jule.get(f"/api/v1/exports/{made.json()['id']}").json()
        assert shown["state"] == "ready" and shown["documents"] == 3
        archive = zip_of(jule, made.json()["id"])
        alt = "jule/2025/ohne Absender/2025-05-01 Alt.pdf"
        strom = "jule/2026/Stadtwerke Lindenau/2026-03-14 Strom März.pdf"
        rechnung = "Firma/2026/Elektro Brandt GmbH/2026-10-06 Rechnung Heizungswartung.pdf"
        assert sorted(archive.namelist()) == sorted([alt, strom, rechnung, "liste.csv"])
        listing = archive.read("liste.csv").decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(listing), delimiter=";"))
    assert rows[0][-1] == "Gehört zu" and len(rows[0]) == 16
    by_title = {row[1]: row for row in rows[1:]}
    assert set(by_title) == {"Strom März", "Rechnung Heizungswartung", "Alt"}
    assert by_title["Strom März"][-1] == alt
    assert by_title["Rechnung Heizungswartung"][-1] == alt
    assert by_title["Alt"][-1] == ", ".join(sorted([rechnung, strom]))
    # Nothing of what jule may not see or what was left out, not even as a name.
    for word in ("Geheim", "Leihgabe", "Kette", "Weggeworfen"):
        assert word not in listing and not any(word in name for name in archive.namelist())


def test_without_the_choice_nothing_comes_along_and_the_list_keeps_its_columns(world: World) -> None:
    with new_client(world.jule) as jule:
        made = jule.post("/api/v1/exports", json=body(world), headers=DE).json()
        assert made["related"] is False
        pack()
        archive = zip_of(jule, made["id"])
        assert len(archive.namelist()) == 3
        rows = list(csv.reader(io.StringIO(archive.read("liste.csv").decode("utf-8-sig")), delimiter=";"))
    assert len(rows[0]) == 15 and "Gehört zu" not in rows[0]


def test_the_limits_hold_for_the_whole(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(exports, "MAX_DOCUMENTS", 2)
    with new_client(world.jule) as jule:
        assert preview(jule, world)["too_many"] is False
        assert preview(jule, world, related="true")["too_many"] is True
        made = jule.post("/api/v1/exports", json=body(world, related=True), headers=DE).json()
        pack()
        shown = jule.get(f"/api/v1/exports/{made['id']}").json()
    assert shown["state"] == "failed" and shown["error"] == "too_many_documents"


def test_a_vault_of_a_document_that_came_along_counts_for_the_link(world: World) -> None:
    """The ZIP records every vault its documents came from: a person who leaves the vault of one that only came along
    no longer hands the ZIP out (``exports.sees_all``)."""
    extra = add_document(world.firma, world.jule, "Firmenbeleg", date=date(2020, 1, 1))
    pair(world.strom, extra)
    with new_client(world.jule) as jule:
        made = jule.post("/api/v1/exports", json=body(world, vault_ids=[world.mine], related=True), headers=DE).json()
        pack()
        shown = jule.get(f"/api/v1/exports/{made['id']}").json()
        # Strom, and what goes with it: Alt (outside the period) and the one of the other vault.
        assert shown["documents"] == 3
    with SessionLocal() as db:
        from app.models import Export

        row = db.get(Export, made["id"])
        assert row is not None and sorted(row.vault_ids) == sorted([world.mine, world.firma])


def test_zip_names_of_the_list_are_safe_for_a_spreadsheet(world: World) -> None:
    formula = add_document(world.mine, world.jule, "=SUMME(A1)", date=None)
    pair(world.strom, formula)
    with new_client(world.jule) as jule:
        made = jule.post("/api/v1/exports", json=body(world, related=True), headers=DE).json()
        pack()
        listing = zip_of(jule, made["id"]).read("liste.csv").decode("utf-8-sig")
    rows = {row[1]: row for row in csv.reader(io.StringIO(listing), delimiter=";")}
    # The title starts with a formula sign; the names in the last column start with a folder, a quote stays out of them.
    assert rows["'=SUMME(A1)"][1].startswith("'")
    assert "ohne Datum =SUMME(A1)" in rows["Strom März"][-1]


__all__ = ["zipfile"]
