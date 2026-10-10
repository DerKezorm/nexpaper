"""A date the server refuses names the field it came in, so the page can mark that field."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.models import Account

from .papers import add_document, document, own_vault


@pytest.fixture
def mine(client: TestClient, operator: Account) -> int:
    return add_document(own_vault(operator), operator, "Keep", content=None)


@pytest.mark.parametrize(("patch", "field"), [
    ({"date": "0027-02-28"}, "date"),
    ({"date": "1899-12-31"}, "date"),
    ({"date": "2201-01-01"}, "date"),
    ({"dates": [{"kind": "due", "date": "2026-10-20"}, {"kind": "contract_end", "date": "0027-02-28"}]}, "dates[1]"),
    ({"dates": [{"kind": "due", "date": "1800-01-01"}]}, "dates[0]"),
    # No date at all (a year past 9999, a 30th of February): the same answer, the same field.
    ({"date": "275760-09-13"}, "date"),
    ({"date": "2026-02-30"}, "date"),
    ({"dates": [{"kind": "due", "date": "2026-10-20"}, {"kind": "keep_until", "date": "2026-02-30"}]}, "dates[1]"),
])
def test_a_refused_date_names_its_field(client: TestClient, mine: int, patch: dict, field: str) -> None:
    before = document(mine)
    answer = client.patch(f"/api/v1/documents/{mine}", json=patch)
    assert answer.status_code == 422, answer.text
    body = answer.json()["detail"]
    assert body["code"] == "invalid_date" and body["field"] == field, body
    after = document(mine)
    assert (after.date, after.change_seq) == (before.date, before.change_seq), "a refused change changes nothing"


def test_a_refused_date_changes_nothing_of_the_other_fields_sent_with_it(client: TestClient, mine: int) -> None:
    answer = client.patch(f"/api/v1/documents/{mine}", json={"title": "Other", "date": "0027-02-28"})
    assert answer.status_code == 422
    assert document(mine).title == "Keep"


def test_the_edges_are_taken(client: TestClient, mine: int) -> None:
    for day in ("1900-01-01", "2200-12-31"):
        assert client.patch(f"/api/v1/documents/{mine}", json={"date": day}).json()["date"] == day


def test_other_wrong_input_keeps_the_general_answer(client: TestClient, mine: int) -> None:
    answer = client.patch(f"/api/v1/documents/{mine}", json={"date": "not a date", "amount": "x"})
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "invalid_input"
    answer = client.patch(f"/api/v1/documents/{mine}", json={"amount": "12"})
    assert answer.json()["detail"]["code"] == "invalid_input"


def test_the_description_says_which_field(client: TestClient) -> None:
    text = client.get("/api/v1/openapi.json").json()["paths"]["/api/v1/documents/{document_id}"]["patch"]
    assert "dates[n]" in text["responses"]["422"]["description"]
