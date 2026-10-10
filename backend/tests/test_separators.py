"""Blank separator pages: how a page is judged (made-up scans with noise, dust, a slant, the other side shining through,
and nearly empty pages with only a page number), where a stack would be cut (also scanned on both sides), and the
proposal in the inbox."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import worker
from app.db import SessionLocal
from app.services import separators, settings_service

from . import scans
from .conftest import make_account, new_client
from .intake import process_all, upload_and_read
from .papers import shared_vault


def ink(tmp_path: Path, sheet: scans.Sheet) -> int:
    path = tmp_path / f"s{sheet.seed}.pdf"
    path.write_bytes(scans.pdf_of([sheet]))
    return int(worker.blanks({"pdf": str(path)})["ink"][0])


# --- How a page is judged -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("sheet", scans.EMPTY, ids=lambda s: f"empty-{s.seed}")
def test_an_empty_sheet_as_scanners_give_it_counts_as_empty(tmp_path: Path, sheet: scans.Sheet) -> None:
    assert ink(tmp_path, sheet) <= separators.BLANK_PPM


@pytest.mark.parametrize("sheet", scans.NEARLY_EMPTY, ids=lambda s: f"nearly-{s.seed}")
def test_a_back_with_only_its_page_number_is_no_separator(tmp_path: Path, sheet: scans.Sheet) -> None:
    assert ink(tmp_path, sheet) > separators.BLANK_PPM


def test_the_threshold_leaves_room_on_both_sides(tmp_path: Path) -> None:
    """The measurement the threshold rests on (``services/separators.py``): the emptiest page that is no separator has
    clearly more ink than the threshold, every empty sheet clearly less."""
    empty = max(ink(tmp_path, sheet) for sheet in scans.EMPTY)
    nearly = min(ink(tmp_path, sheet) for sheet in scans.NEARLY_EMPTY)
    assert empty <= separators.BLANK_PPM // 2
    assert nearly >= separators.BLANK_PPM * 1.5
    assert ink(tmp_path, scans.LETTER) > 10_000


def test_a_digital_pdf_with_an_empty_page_has_no_ink_there(tmp_path: Path) -> None:
    from . import files

    path = tmp_path / "digital.pdf"
    path.write_bytes(files.make_pdf(["Seite eins mit Text", "", "Seite drei"]))
    found = worker.blanks({"pdf": str(path)})["ink"]
    assert found[1] == 0 and found[0] > separators.BLANK_PPM and found[2] > separators.BLANK_PPM


# --- Where a stack is cut ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("pages, blanks, parts", [
    (5, [3], [[1, 2], [4, 5]]),
    (6, [1, 3, 6], [[2], [4, 5]]),
    (7, [3, 4], [[1, 2], [5, 6, 7]]),
    (4, [4], []),
    (2, [1], []),
    (5, [], []),
    (3, [1, 2, 3], []),
    # Letters of one page with a separator between each, scanned on one side: an odd count is never duplex.
    (5, [2, 4], [[1], [3], [5]]),
    (7, [2, 4, 6], [[1], [3], [5], [7]]),
    (9, [2, 4, 6, 8], [[1], [3], [5], [7], [9]]),
    # Four pages, second and fourth empty: both readings fit, nothing is proposed.
    (4, [2, 4], []),
])
def test_where_a_stack_is_cut(pages: int, blanks: list[int], parts: list[list[int]]) -> None:
    found = separators.proposal(pages, blanks)
    assert found.parts == parts and found.separators == sorted(blanks)


def test_a_stack_scanned_on_both_sides_is_not_cut_at_every_empty_back() -> None:
    # Three one-sided letters, scanned on both sides: every back is empty, nothing to cut.
    assert separators.proposal(6, [2, 4, 6]).parts == []
    assert separators.proposal(6, [2, 4, 6]).duplex
    # Two letters, a separator sheet between them (both of its sides empty): one cut, all empty pages go.
    found = separators.proposal(8, [2, 3, 4, 6, 8])
    assert found.duplex and found.parts == [[1], [5, 7]]


# --- The proposal in the inbox ---------------------------------------------------------------------------------------

STACK = [scans.LETTER, scans.Sheet(seed=31), scans.Sheet(content="letter", seed=32),
         scans.Sheet(content="number", text="- 2 -", seed=33), scans.Sheet(slant=2.0, noise=12, seed=34),
         scans.Sheet(content="letter", seed=35)]


def test_a_batch_scan_is_offered_for_splitting_and_the_offer_can_be_put_away(client: TestClient, operator: object) -> None:
    document = upload_and_read(client, "Stapelscan.pdf", scans.pdf_of(STACK))
    assert document["status"] == "inbox" and document["pages"] == 6 and document["split_suggested"]
    found = client.get(f"/api/v1/documents/{document['id']}/separators").json()
    assert found == {"version": 1, "checked": True, "blank_pages": [2, 5], "parts": [[1], [3, 4], [6]],
                     "duplex": False, "dismissed": False, "suggested": True}
    listed = client.get("/api/v1/documents?status=inbox").json()["items"]
    assert [d["split_suggested"] for d in listed] == [True]
    assert client.delete(f"/api/v1/documents/{document['id']}/separators").status_code == 204
    found = client.get(f"/api/v1/documents/{document['id']}/separators").json()
    assert found["dismissed"] and not found["suggested"] and found["parts"] == [[1], [3, 4], [6]]
    assert not client.get(f"/api/v1/documents/{document['id']}").json()["split_suggested"]


def test_splitting_by_the_proposal_drops_the_separators(client: TestClient, operator: object) -> None:
    document = upload_and_read(client, "Stapelscan.pdf", scans.pdf_of(STACK))
    proposal = client.get(f"/api/v1/documents/{document['id']}/separators").json()
    body = {"base_version": 1, "parts": [{"pages": [{"page": p} for p in part]} for part in proposal["parts"]]}
    answer = client.post(f"/api/v1/documents/{document['id']}/split", json=body)
    assert answer.status_code == 201, answer.text
    assert [d["pages"] for d in answer.json()["items"]] == [1, 2, 1]
    assert not any(d["split_suggested"] for d in answer.json()["items"])


def test_the_switch_off_looks_for_no_separators(client: TestClient, operator: object) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"ocr_blank_pages": False})
    document = upload_and_read(client, "Stapelscan.pdf", scans.pdf_of(STACK))
    found = client.get(f"/api/v1/documents/{document['id']}/separators").json()
    assert not found["checked"] and not found["suggested"] and not document["split_suggested"]


def test_a_stranger_sees_no_separators_and_a_reader_may_not_dismiss(client: TestClient, operator: object) -> None:
    jule, tom, lea = make_account("jule"), make_account("tom"), make_account("lea")
    vault = shared_vault("Haushalt", jule, (tom, "read"))
    with new_client(jule) as owner:
        document = upload_and_read(owner, "Stapelscan.pdf", scans.pdf_of(STACK[:3]), vault)
    with new_client(tom) as reader:
        assert reader.get(f"/api/v1/documents/{document['id']}/separators").status_code == 200
        assert reader.delete(f"/api/v1/documents/{document['id']}/separators").status_code == 403
    with new_client(lea) as stranger:
        assert stranger.get(f"/api/v1/documents/{document['id']}/separators").status_code == 404
        assert stranger.delete(f"/api/v1/documents/{document['id']}/separators").status_code == 404


def test_edited_pages_take_their_blank_marks_along(client: TestClient, operator: object) -> None:
    document = upload_and_read(client, "Stapelscan.pdf", scans.pdf_of(STACK))
    answer = client.post(f"/api/v1/documents/{document['id']}/pages", json={
        "base_version": 1, "pages": [{"page": p} for p in (6, 5, 4, 3, 2, 1)]})
    assert answer.status_code == 200
    found = client.get(f"/api/v1/documents/{document['id']}/separators").json()
    assert found["version"] == 2 and found["blank_pages"] == [2, 5]
    process_all()


def test_a_bar_across_the_sheet_and_ruled_lines_are_ink_not_the_scanner(tmp_path: Path) -> None:
    """Ink that reaches the edge in a long run is on the sheet: it counts in full, not only its frayed ends."""
    bar = scans.Sheet(content="bar", ink=40, seed=20)
    ruled = scans.Sheet(content="ruled", ink=150, seed=22)
    assert ink(tmp_path, bar) > 10_000 and ink(tmp_path, ruled) > 10_000
