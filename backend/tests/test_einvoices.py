"""E-invoices: a ZUGFeRD PDF, an XRechnung in UBL and one in CII go through the worker; their fields come exactly from
the data, an XML-only invoice gets a readable page, the XML is read like the file, the export carries it, and hostile
XML (entities, an external DTD, a bomb, a very deep tree, in UTF-8 and UTF-16) is refused without being expanded."""

from __future__ import annotations

import csv
import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import einvoice_reader
from app.db import SessionLocal
from app.models import Account, EInvoice
from app.services import jobs, settings_service

from . import einvoices as samples
from .conftest import DATA_DIR, make_account, new_client
from .intake import upload_and_read, version_of
from .papers import shared_vault


def test_a_zugferd_pdf_brings_its_data(client: TestClient, operator: Account) -> None:
    document = upload_and_read(client, "rechnung.pdf", samples.zugferd_pdf())
    assert document["status"] == "inbox" and document["process_error"] == ""
    assert document["einvoice"] == "Factur-X (EN 16931)"
    # Exactly from the data: the page says 999,99 EUR, the invoice 224,91.
    assert document["amount"] == 22491 and document["date"] == "2026-10-06"
    assert document["sender"]["name"] == "Elektro Brandt GmbH" and document["kind"]["key"] == "invoice"
    assert document["title"] == "Rechnung 2026-0473"
    assert {"kind": "due", "date": "2026-10-20"} in [{"kind": d["kind"], "date": d["date"]} for d in document["dates"]]
    for field in ("title", "sender", "kind", "date", "amount", "dates"):
        assert document["suggest"][field] == "einvoice", field
    data = client.get(f"/api/v1/documents/{document['id']}/einvoice").json()
    assert data["number"] == "2026-0473" and data["iban"] == samples.SELLER_IBAN and data["net"] == 18900
    assert data["tax"] == 3591 and data["gross"] == 22491 and data["seller_vat"] == "DE987654321"
    assert data["buyer_ref"] == "LINDENHOF-12" and data["xml_only"] is False and data["version"] == 1
    assert [line["text"] for line in data["lines"]] == ["Wartung Gasbrennwerttherme", "Anfahrt"]
    xml = client.get(f"/api/v1/documents/{document['id']}/versions/1/einvoice")
    assert xml.status_code == 200 and xml.content == samples.cii()
    assert xml.headers["content-type"].startswith("application/xml")
    assert xml.headers["content-disposition"].startswith("attachment")
    assert client.get(f"/api/v1/documents/{document['id']}/versions/1/einvoice",
                      headers={"If-None-Match": xml.headers["etag"]}).status_code == 304


def test_an_xrechnung_as_xml_gets_a_readable_page(client: TestClient, operator: Account) -> None:
    document = upload_and_read(client, "rechnung.xml", samples.ubl())
    assert document["status"] == "inbox" and document["process_error"] == "" and document["pages"] == 1
    assert document["einvoice"] == "XRechnung (UBL)" and document["amount"] == 33320
    assert document["sender"]["name"] == "Glanzwerk Reinigungsservice"
    version = version_of(document["id"])
    assert version.archive_path.endswith(".pdf")
    page = client.get(f"/api/v1/documents/{document['id']}/versions/1/archive")
    assert page.status_code == 200 and page.content.startswith(b"%PDF-")
    assert client.get(f"/api/v1/documents/{document['id']}/versions/1/preview").status_code == 200
    # The text of the readable page is searchable; the XML stays the original.
    text = client.get(f"/api/v1/documents/{document['id']}/versions/1/text").json()
    assert "RE-26-0912" in text["pages"][0] and "Leitweg-ID" in text["pages"][0]
    assert client.get("/api/v1/search", params={"q": "Endreinigung"}).json()["total"] == 1
    assert client.get(f"/api/v1/documents/{document['id']}/versions/1/file").content == samples.ubl()
    data = client.get(f"/api/v1/documents/{document['id']}/einvoice").json()
    assert data["xml_only"] is True and data["buyer_ref"] == "04011000-12345-67" and data["due"] == "2026-10-14"
    assert client.get(f"/api/v1/documents/{document['id']}/versions/1/einvoice").content == samples.ubl()


def test_an_xrechnung_in_cii_and_the_english_page(client: TestClient, operator: Account) -> None:
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None
        row.language = "en"
        db.commit()
    xml = samples.cii(guideline="urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0")
    document = upload_and_read(client, "x.xml", xml)
    assert document["einvoice"] == "XRechnung (CII)" and document["title"] == "Invoice 2026-0473"
    text = client.get(f"/api/v1/documents/{document['id']}/versions/1/text").json()["pages"][0]
    assert "Invoice number" in text and "EUR 224.91" in text


def test_the_xml_is_read_like_the_file(client: TestClient, operator: Account) -> None:
    reader, stranger = make_account("reader"), make_account("stranger")
    vault = shared_vault("Firma", operator, (reader, "read"))
    document = upload_and_read(client, "rechnung.pdf", samples.zugferd_pdf(), vault_id=vault)
    paths = (f"/api/v1/documents/{document['id']}/einvoice", f"/api/v1/documents/{document['id']}/versions/1/einvoice")
    with new_client(reader) as browser:
        assert [browser.get(p).status_code for p in paths] == [200, 200]
    with new_client(stranger) as browser:
        assert [browser.get(p).status_code for p in paths] == [404, 404]
    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": True})
    secret = client.post("/api/v1/api-keys", json={"name": "k", "scope": "read"}).json()["secret"]
    with TestClient(client.app, base_url="http://testserver") as program:
        assert [program.get(p, headers={"Authorization": f"Bearer {secret}"}).status_code for p in paths] == [200, 200]
    # A version that carries none.
    assert client.get(f"/api/v1/documents/{document['id']}/versions/2/einvoice").status_code == 404


def test_a_pdf_without_an_invoice_has_none(client: TestClient, operator: Account) -> None:
    from .files import make_pdf

    document = upload_and_read(client, "brief.pdf", make_pdf(["Liebe Jule, viele Grüße aus Lindenau"]))
    assert document["einvoice"] == ""
    assert client.get(f"/api/v1/documents/{document['id']}/einvoice").status_code == 404


@pytest.mark.parametrize("hostile", [samples.ENTITIES, samples.EXTERNAL_DTD, samples.BOMB, samples.deep(60),
                                     samples.deep(400)], ids=["entities", "external-dtd", "bomb", "deep", "deeper"])
def test_hostile_xml_is_refused_by_the_reader(hostile: bytes) -> None:
    for data in (hostile, hostile.decode().replace('<?xml version="1.0"?>', '<?xml version="1.0" encoding="UTF-16"?>')
                 .encode("utf-16")):
        started = time.monotonic()
        with pytest.raises(einvoice_reader.InvoiceRefused):
            einvoice_reader.read_invoice(data)
        assert time.monotonic() - started < 1.0


def test_hostile_xml_inside_a_pdf_leaves_a_pdf_without_an_invoice(client: TestClient, operator: Account) -> None:
    for hostile in (samples.ENTITIES, samples.BOMB, samples.deep(60)):
        document = upload_and_read(client, "r.pdf", samples.zugferd_pdf(hostile))
        assert document["status"] == "inbox" and document["process_error"] == "" and document["einvoice"] == ""
        assert client.get(f"/api/v1/documents/{document['id']}/einvoice").status_code == 404
        client.delete(f"/api/v1/documents/{document['id']}")


def test_hostile_xml_as_a_file(client: TestClient, operator: Account) -> None:
    from .intake import post_files

    # A document type is refused when the file comes in.
    answer = post_files(client, ("r.xml", samples.ENTITIES))
    assert answer.status_code == 415 and answer.json()["detail"]["code"] == "xml_doctype"
    # Too deep for the reader: kept, with the reason, never read.
    document = upload_and_read(client, "deep.xml", samples.deep(60))
    assert document["process_error"] == "broken" and document["einvoice"] == ""


def test_an_xml_too_large_is_not_read() -> None:
    with pytest.raises(einvoice_reader.InvoiceRefused) as refused:
        einvoice_reader.read_invoice(b"<Invoice>" + b" " * (einvoice_reader.MAX_XML + 1) + b"</Invoice>")
    assert refused.value.code == "too_large"


def test_the_worker_answer_is_checked_again() -> None:
    kept = einvoice_reader.summary({"format": "UBL", "number": "1\x00\u202e2", "net": True, "gross": 10**20,
                                    "iban": "DE00 0000 0000 0000 0000 00", "issued": "2026-02-30",
                                    "lines": [{"text": 5, "price": "1"}, "x"], "evil": "yes"})
    assert kept["number"] == "1 2" and kept["net"] is None and kept["gross"] is None and kept["iban"] == ""
    assert kept["issued"] == "" and kept["lines"] == [{"text": "", "quantity": "", "unit": "", "price": None,
                                                       "total": None}]
    assert "evil" not in kept


def test_the_export_carries_the_xml_and_the_invoice_number(client: TestClient, operator: Account) -> None:
    vault = shared_vault("Firma", operator)
    zugferd = upload_and_read(client, "rechnung.pdf", samples.zugferd_pdf(), vault_id=vault)
    xrechnung = upload_and_read(client, "x.xml", samples.ubl(), vault_id=vault)
    for document in (zugferd, xrechnung):
        assert client.patch(f"/api/v1/documents/{document['id']}", json={"status": "filed"}).status_code == 200
    made = client.post("/api/v1/exports", headers={"X-Nexpaper-Language": "de"}, json={
        "date_from": "2026-01-01", "date_to": "2026-12-31", "vault_ids": [vault],
        "content": {"pdf": True, "original": False, "csv": True, "xml": True}}).json()
    jobs.run_pending(kinds=(jobs.EXPORT,))
    archive = zipfile.ZipFile(io.BytesIO(client.get(f"/api/v1/exports/{made['id']}/file").content))
    xmls = sorted(name for name in archive.namelist() if name.endswith(".xml"))
    assert len(xmls) == 2
    assert {archive.read(name) for name in xmls} == {samples.cii(), samples.ubl()}
    rows = list(csv.reader(io.StringIO(archive.read("liste.csv").decode("utf-8-sig")), delimiter=";"))
    assert {row[6] for row in rows[1:]} == {"2026-0473", "RE-26-0912"}


def test_the_data_stay_with_the_version_that_carried_them(client: TestClient, operator: Account) -> None:
    document = upload_and_read(client, "rechnung.pdf", samples.zugferd_pdf())
    with SessionLocal() as db:
        rows = list(db.scalars(select(EInvoice).where(EInvoice.document_id == document["id"])))
        assert len(rows) == 1 and rows[0].xml == samples.cii()
    # Deleted for good: the data go with the document.
    client.delete(f"/api/v1/documents/{document['id']}")
    assert client.post(f"/api/v1/documents/{document['id']}/purge").status_code == 204
    with SessionLocal() as db:
        assert db.scalars(select(EInvoice)).first() is None
    assert not list(Path(DATA_DIR, "dokumente").rglob("*.xml"))


def test_a_document_type_is_refused_before_the_parser_sees_it(monkeypatch: pytest.MonkeyPatch) -> None:
    def never() -> None:
        raise AssertionError("parsed")

    monkeypatch.setattr(einvoice_reader, "_parser", never)
    for hostile in (samples.ENTITIES, samples.EXTERNAL_DTD, samples.BOMB):
        with pytest.raises(einvoice_reader.InvoiceRefused) as refused:
            einvoice_reader.read_invoice(hostile)
        assert refused.value.code == "xml_doctype"



@pytest.mark.parametrize("number", ["=1+1", "@SUM(A1)", "+49 17", "-2+3"])
def test_an_invoice_number_that_a_spreadsheet_would_take_for_a_formula_is_defused(client: TestClient,
                                                                                 operator: Account,
                                                                                 number: str) -> None:
    vault = shared_vault("Firma", operator)
    made = upload_and_read(client, "x.xml", samples.ubl(number=number), vault_id=vault)
    assert made["einvoice"] and client.patch(f"/api/v1/documents/{made['id']}", json={"status": "filed"}).status_code == 200
    export = client.post("/api/v1/exports", headers={"X-Nexpaper-Language": "de"}, json={
        "date_from": "2026-01-01", "date_to": "2026-12-31", "vault_ids": [vault],
        "content": {"pdf": False, "original": False, "csv": True, "xml": False}}).json()
    jobs.run_pending(kinds=(jobs.EXPORT,))
    archive = zipfile.ZipFile(io.BytesIO(client.get(f"/api/v1/exports/{export['id']}/file").content))
    rows = list(csv.reader(io.StringIO(archive.read("liste.csv").decode("utf-8-sig")), delimiter=";"))
    assert [row[6] for row in rows[1:]] == ["'" + number]
