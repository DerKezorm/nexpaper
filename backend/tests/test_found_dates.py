"""The dates written in the text of a document, offered in the inbox to choose the date from (issue #9): read like the
text (a person who may not see the document gets 404 like for one that is not there), ``pending`` until it is read."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models import Account

from .conftest import make_account, new_client
from .files import make_pdf
from .intake import upload_and_read, upload_one

LETTER = ("Stadtwerke Lindenau GmbH\nLindenau, 02.10.2026\nRechnungsdatum 01.10.2026\n"
          "Abrechnungszeitraum 01.09.2026 bis 30.09.2026\nZahlbar bis 15.10.2026\nGesamtbetrag 86,40 EUR")


def test_the_inbox_gets_every_date_of_the_text_with_what_names_it(client: TestClient, operator: Account) -> None:
    document = upload_and_read(client, "letter.pdf", make_pdf([LETTER]))
    assert document["date"] == "2026-10-01"
    answer = client.get(f"/api/v1/documents/{document['id']}/versions/1/dates")
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"version": 1, "state": "done", "dates": [
        {"date": "2026-10-02", "role": ""}, {"date": "2026-10-01", "role": "date"},
        {"date": "2026-09-01", "role": "period"}, {"date": "2026-09-30", "role": "period"},
        {"date": "2026-10-15", "role": "due"}]}


def test_not_read_yet_says_so_and_a_version_that_is_not_there_is_404(client: TestClient, operator: Account) -> None:
    document = upload_one(client, "letter.pdf", make_pdf([LETTER]))
    answer = client.get(f"/api/v1/documents/{document['id']}/versions/1/dates")
    assert answer.json() == {"version": 1, "state": "pending", "dates": []}
    assert client.get(f"/api/v1/documents/{document['id']}/versions/2/dates").status_code == 404


def test_somebody_who_may_not_see_it_learns_nothing(client: TestClient, operator: Account) -> None:
    document = upload_and_read(client, "letter.pdf", make_pdf([LETTER]))
    with new_client(make_account("lea")) as stranger:
        for number in (1, 2):
            answer = stranger.get(f"/api/v1/documents/{document['id']}/versions/{number}/dates")
            assert answer.status_code == 404 and "dates" not in answer.json()
