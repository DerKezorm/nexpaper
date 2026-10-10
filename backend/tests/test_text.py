"""The text of a version page by page (rights of reading; through a link only with downloading), and the operator's
settings of the text recognition."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Account
from app.services import settings_service

from .conftest import make_account, new_client
from .files import invoice_xml, make_pdf
from .intake import process_all, upload_one
from .papers import add_document, shared_vault
from .searching import give_text


def public() -> TestClient:
    return TestClient(app, base_url="http://testserver")


def test_the_text_of_a_version_page_by_page_with_the_rights_of_reading(client: TestClient, operator: Account) -> None:
    lea, out = make_account("lea"), make_account("outsider")
    vault = shared_vault("Haushalt", operator, (lea, "read"))
    made = add_document(vault, operator, "Vertrag")
    # Not read yet.
    answer = client.get(f"/api/v1/documents/{made}/versions/1/text").json()
    assert answer == {"version": 1, "state": "pending", "pages": [], "ocr_pages": 0, "languages": "",
                      "long_document_pages": 300}
    give_text(made, "Seite eins", "", "Seite drei", ocr_pages=1)
    with new_client(lea) as reader:
        answer = reader.get(f"/api/v1/documents/{made}/versions/1/text").json()
        assert answer == {"version": 1, "state": "done", "pages": ["Seite eins", "", "Seite drei"], "ocr_pages": 1,
                          "languages": "deu", "long_document_pages": 300}
        assert reader.get(f"/api/v1/documents/{made}/versions/2/text").status_code == 404
    with new_client(out) as stranger:
        assert stranger.get(f"/api/v1/documents/{made}/versions/1/text").status_code == 404


def test_the_text_of_a_read_pdf_and_of_an_xml_invoice(client: TestClient, operator: Account) -> None:
    pdf = upload_one(client, "Brief.pdf", make_pdf(["Liebe Jule,\nder Zählerstand ist 4711.", "Viele Grüße aus Lindenau, bis bald und alles Gute"]))
    xml = upload_one(client, "Rechnung.xml", invoice_xml())
    process_all()
    pages = client.get(f"/api/v1/documents/{pdf['id']}/versions/1/text").json()
    assert pages["state"] == "done" and pages["ocr_pages"] == 0
    assert "Zählerstand ist 4711" in pages["pages"][0] and "Grüße aus Lindenau" in pages["pages"][1]
    # Found by the search right away, with what the PDF carried.
    assert client.get("/api/v1/search", params={"q": "zählerstand 4711"}).json()["total"] == 1
    # An e-invoice as XML: the text of the readable page set from it (B6).
    xml_text = client.get(f"/api/v1/documents/{xml['id']}/versions/1/text").json()
    assert xml_text["state"] == "done" and "2026-1001" in xml_text["pages"][0]


def test_a_link_hands_out_the_text_only_when_it_allows_downloading(client: TestClient, operator: Account) -> None:
    made = add_document(shared_vault("Haushalt", operator), operator, "Vertrag")
    give_text(made, "Kündigungsfrist drei Monate")
    open_link = client.post(f"/api/v1/documents/{made}/links",
                            json={"recipient": "Steuerbüro", "days": 7, "allow_download": True}).json()
    closed = client.post(f"/api/v1/documents/{made}/links",
                         json={"recipient": "Nachbar", "days": 7, "allow_download": False}).json()
    with public() as guest:
        answer = guest.get(f"/api/v1/l/{open_link['token']}/text")
        assert answer.status_code == 200 and answer.json()["pages"] == ["Kündigungsfrist drei Monate"]
        answer = guest.get(f"/api/v1/l/{closed['token']}/text")
        assert answer.status_code == 403 and answer.json()["detail"]["code"] == "download_not_allowed"
        assert guest.get("/api/v1/l/lnk_" + "x" * 40 + "/text").status_code == 404
    assert client.delete(f"/api/v1/documents/{made}/links/{open_link['id']}").status_code == 204
    with public() as guest:
        assert guest.get(f"/api/v1/l/{open_link['token']}/text").status_code == 404


# --- The settings -----------------------------------------------------------------------------------------------------


def test_the_operator_chooses_languages_and_switches(client: TestClient, operator: Account) -> None:
    answer = client.get("/api/v1/settings/ocr").json()
    assert answer["languages"] == ["deu", "eng"] and answer["offered"] == ["deu", "eng", "fra", "nld", "pol", "tur"]
    assert answer["straighten"] is True and answer["blank_pages"] is True and answer["jobs"] == 1
    assert answer["running"] == 0 and answer["waiting"] == 0 and answer["seconds_per_page"] is None
    assert isinstance(answer["available"], bool)
    # In the order of the offer, each once.
    answer = client.put("/api/v1/settings/ocr", json={"languages": ["tur", "deu", "tur"], "straighten": False}).json()
    assert answer["languages"] == ["deu", "tur"] and answer["straighten"] is False
    with SessionLocal() as db:
        assert settings_service.get(db, "ocr_languages") == ["deu", "tur"]
    answer = client.put("/api/v1/settings/ocr", json={"blank_pages": False, "jobs": 2}).json()
    assert answer["blank_pages"] is False and answer["jobs"] == 2 and answer["languages"] == ["deu", "tur"]
    for wrong in ({"languages": []}, {"languages": ["deu", "spa"]}, {"jobs": 0}, {"jobs": 5}, {"straighten": "yes"},
                  {"other": 1}, {"languages": "deu"}):
        assert client.put("/api/v1/settings/ocr", json=wrong).status_code == 422, wrong
    assert client.get("/api/v1/settings/ocr").json()["languages"] == ["deu", "tur"]


def test_only_the_operator_in_a_browser_reaches_the_settings(client: TestClient, operator: Account) -> None:
    with new_client(make_account("jule")) as member:
        assert member.get("/api/v1/settings/ocr").status_code == 403
        assert member.put("/api/v1/settings/ocr", json={"jobs": 2}).status_code == 403
    token = client.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with TestClient(app, base_url="http://testserver") as device:
        assert device.get("/api/v1/settings/ocr", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get("/api/v1/settings/ocr").json()["jobs"] == 1


def test_the_card_tells_how_long_a_page_took(client: TestClient, operator: Account) -> None:
    upload_one(client, "Zwei.pdf", make_pdf(["eins", "zwei"]))
    process_all()
    pace = client.get("/api/v1/settings/ocr").json()["seconds_per_page"]
    assert isinstance(pace, float) and 0 <= pace < 120


# --- When only the text cannot be read --------------------------------------------------------------------------------


def test_a_text_that_takes_too_long_leaves_the_document_with_its_pages_and_the_reason(
        client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.services import jobs, processing

    from .test_processing import fast_limits, jobs_of, script

    stub = script(tmp_path, """
        import json, sys, time
        request = json.loads(sys.stdin.read())
        if request['op'] == 'recognize':
            time.sleep(60)
        print(json.dumps({'ok': True, 'pages': 3, 'phash': '', 'derived': False}))
    """)
    monkeypatch.setattr(processing, "WORKER", stub)
    fast_limits(monkeypatch)
    # One second for the whole document, not the ten seconds a page gets at least.
    from app.services import ocr

    monkeypatch.setattr(ocr, "PAGE_BUDGET", (0, 120))
    made = upload_one(client, "Lang.pdf", make_pdf(["eins", "zwei", "drei"]))
    process_all()
    document = client.get(f"/api/v1/documents/{made['id']}").json()
    assert document["status"] == "inbox" and document["pages"] == 3 and document["process_error"] == "ocr_timeout"
    assert jobs_of(jobs.PROCESS) == [(made["id"], "done", 3, "")]
    events = client.get(f"/api/v1/documents/{made['id']}/events").json()
    assert events[0]["action"] == "processed" and events[0]["detail"] == {"pages": 3, "error": "ocr_timeout"}
    assert client.get(f"/api/v1/documents/{made['id']}/versions/1/text").json()["state"] == "pending"
    # Tried again with a worker that reads: the reason goes, the text comes.
    monkeypatch.undo()
    assert client.post(f"/api/v1/documents/{made['id']}/retry").status_code == 200
    process_all()
    document = client.get(f"/api/v1/documents/{made['id']}").json()
    assert document["process_error"] == "" and document["pages"] == 3
    assert client.get(f"/api/v1/documents/{made['id']}/versions/1/text").json()["pages"][1].strip() == "zwei"


def test_a_text_that_cannot_be_read_for_good_is_not_tried_again(
        client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.services import jobs, processing

    from .test_processing import jobs_of, script

    stub = script(tmp_path, """
        import json, sys
        request = json.loads(sys.stdin.read())
        if request['op'] == 'recognize':
            print(json.dumps({'ok': False, 'error': 'broken', 'retry': False}))
        else:
            print(json.dumps({'ok': True, 'pages': 1, 'phash': '', 'derived': False}))
    """)
    monkeypatch.setattr(processing, "WORKER", stub)
    made = upload_one(client, "Kaputt.pdf", make_pdf(["eins"]))
    process_all()
    document = client.get(f"/api/v1/documents/{made['id']}").json()
    assert document["status"] == "inbox" and document["pages"] == 1 and document["process_error"] == "ocr_failed"
    assert jobs_of(jobs.PROCESS) == [(made["id"], "done", 1, "")]
