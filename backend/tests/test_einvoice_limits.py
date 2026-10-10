"""The limits of the XML reader: many attributes, many namespaces, many siblings, a short time for the XML in a PDF.

libxml2 checks the attributes and the namespace declarations of one element against each other: forty thousand of them
keep the one worker busy for seconds, a few hundred thousand for minutes. The marks are counted in the bytes before the
parser runs; each case here fails in well under a second, and a test that finds the parser slow is red, never hanging.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import einvoice_reader
from app.models import Account

from . import einvoices as samples
from .intake import upload_and_read

HOSTILE = {
    "attributes": samples.with_attributes(40_000),
    "attributes-in-utf16": samples.with_attributes(40_000).decode().replace(
        '<?xml version="1.0"?>', '<?xml version="1.0" encoding="UTF-16"?>').encode("utf-16"),
    "namespaces": samples.with_namespaces(5_000),
    "tags": samples.wide(einvoice_reader.MAX_TAGS),
}


@pytest.mark.parametrize("name", list(HOSTILE))
def test_an_xml_with_too_many_marks_is_refused_before_the_parser(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def never() -> None:
        raise AssertionError("parsed")

    monkeypatch.setattr(einvoice_reader, "_parser", never)
    started = time.monotonic()
    with pytest.raises(einvoice_reader.InvoiceRefused) as refused:
        einvoice_reader.read_invoice(HOSTILE[name])
    assert refused.value.code == "too_complex"
    assert time.monotonic() - started < 1.0


def test_an_invoice_with_a_few_hundred_attributes_and_dozens_of_namespaces_is_read() -> None:
    assert einvoice_reader.read_invoice(samples.ubl())["number"] == "RE-26-0912"
    assert einvoice_reader.read_invoice(samples.with_attributes(500))["number"] == "1"
    assert einvoice_reader.read_invoice(samples.with_namespaces(150))["number"] == "1"


def test_wide_siblings_are_read_in_a_blink() -> None:
    started = time.monotonic()
    found = einvoice_reader.read_invoice(samples.wide(90_000))  # an invoice without lines and 90,000 strangers
    assert found["number"] == "1" and time.monotonic() - started < 2.0


def test_the_largest_xml_is_a_megabyte() -> None:
    assert einvoice_reader.MAX_XML == 1024 * 1024
    with pytest.raises(einvoice_reader.InvoiceRefused) as refused:
        einvoice_reader.read_invoice(b"<Invoice>" + b" " * einvoice_reader.MAX_XML + b"</Invoice>")
    assert refused.value.code == "too_large"


@pytest.mark.parametrize("name", ["attributes", "namespaces"])
def test_a_hostile_xml_in_a_readable_pdf_costs_only_the_invoice(client: TestClient, operator: Account,
                                                                name: str) -> None:
    started = time.monotonic()
    document = upload_and_read(client, "r.pdf", samples.zugferd_pdf(HOSTILE[name]))
    assert time.monotonic() - started < 20
    assert document["status"] == "inbox" and document["process_error"] == "" and document["einvoice"] == ""
    assert document["pages"] == 1
    assert client.get(f"/api/v1/documents/{document['id']}/einvoice").status_code == 404


def test_a_hostile_xml_as_a_file_is_kept_unread(client: TestClient, operator: Account) -> None:
    document = upload_and_read(client, "many.xml", HOSTILE["attributes"])
    assert document["einvoice"] == "" and document["process_error"] in ("broken", "too_large")


def test_the_xml_inside_a_pdf_is_read_by_a_child_with_a_time_limit() -> None:
    data = samples.cii()
    assert einvoice_reader.read_within(data, 60.0) == einvoice_reader.read_invoice(data)
    # Too short a time for even starting the child: the answer is "nothing", not a wait and not a failure.
    started = time.monotonic()
    assert einvoice_reader.read_within(data, 0.001) is None
    assert time.monotonic() - started < 5.0
    # What is plainly refused is refused in the same words.
    with pytest.raises(einvoice_reader.InvoiceRefused) as refused:
        einvoice_reader.read_within(samples.ENTITIES, 60.0)
    assert refused.value.code == "xml_doctype"
    with pytest.raises(einvoice_reader.InvoiceRefused) as broken:
        einvoice_reader.read_within(b"not xml at all", 60.0)
    assert broken.value.code == "broken"


def test_the_worker_reads_the_xml_of_a_pdf_in_a_child_and_a_slow_one_costs_only_the_invoice(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_embedded_invoice`` of the worker never parses the XML itself: the parser of the worker process itself is made to
    fail here, and the invoice still comes (from the child); and a child that is out of time leaves the PDF without one."""
    import types

    from app import worker

    pdf = tmp_path / "rechnung.pdf"
    pdf.write_bytes(samples.zugferd_pdf())

    def never(*args, **kwargs):
        raise AssertionError("parsed in the worker itself")

    real = worker._sibling

    def sibling(name: str):
        module = real(name)
        return types.SimpleNamespace(**{key: getattr(module, key) for key in dir(module) if not key.startswith("__")}
                                     | {"read_invoice": never})

    monkeypatch.setattr(worker, "_sibling", sibling)
    found = worker._embedded_invoice(pdf)
    assert found and found["number"] == "2026-0473" and found["xml"]
    # Out of time: no invoice, and no exception that would take the PDF with it.

    def slow(name: str):
        module = real(name)
        return types.SimpleNamespace(**{key: getattr(module, key) for key in dir(module) if not key.startswith("__")}
                                     | {"read_within": lambda data: None})

    monkeypatch.setattr(worker, "_sibling", slow)
    assert worker._embedded_invoice(pdf) == {}
