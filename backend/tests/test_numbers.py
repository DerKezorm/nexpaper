"""Reading numbers from a document (``services/numbers.py``): the words in front of them, the ways a scan writes them,
IBANs with valid check digits only, the e-invoice first, and hostile text that costs nothing."""

from __future__ import annotations

import logging
import time

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Document, DocumentNumber, EInvoice, NumbersRead, Version
from app.services import changes, numbers, processing

from .conftest import make_account
from .papers import add_document, own_vault


def found(text: str, **given: str) -> list[tuple[str, str]]:
    return [(n.kind, n.compare) for n in numbers.read(text, **given)]


@pytest.mark.parametrize(("text", "kind", "compare"), [
    ("Rechnungsnummer: R-2026-00017", "invoice", "R202600017"),
    ("Rechnungs-Nr. R-2026-00017", "invoice", "R202600017"),
    ("Rechnung Nr. 2026/00017", "invoice", "202600017"),
    ("Re.-Nr.: RE20261234", "invoice", "RE20261234"),
    ("Rechnungsnr.20261234", "invoice", "20261234"),
    ("Zur Rechnung R-2026-00017 schreiben wir Ihnen gut", "invoice", "R202600017"),
    ("Invoice No. INV-123456", "invoice", "1NV123456"),
    ("Invoice #INV-123456", "invoice", "1NV123456"),
    ("Invoice number: 2026-0099", "invoice", "20260099"),
    ("Bestellnummer: B-1234567", "order", "B1234567"),
    ("Ihre Bestellung 4711-22 vom 01.10.2026", "order", "471122"),
    ("Bestell-Nr. B-1234567", "order", "B1234567"),
    ("Auftragsnummer: AB 2026/0815", "order", "AB20260815"),
    ("Auftragsbestätigung Nr. AB-99812", "order", "AB99812"),
    ("Auftrag: 2026-4711", "order", "20264711"),
    ("AB-Nr. 2026/0815", "order", "20260815"),
    ("Order No. SO123456", "order", "S0123456"),
    ("PO number: PO-55123", "order", "P055123"),
    ("Purchase Order 55123-7", "order", "551237"),
    ("Lieferschein-Nr. LS-004711", "delivery", "1S004711"),
    ("Lieferscheinnummer: 88123456", "delivery", "88123456"),
    ("LS-Nr. 88123456", "delivery", "88123456"),
    ("Delivery note No. DN 88123", "delivery", "DN88123"),
    ("Packing slip PS-77812", "delivery", "PS77812"),
    ("Kundennummer: 100 2345", "customer", "1002345"),
    ("Kd.-Nr. 100-2345", "customer", "1002345"),
    ("Customer ID C-99812", "customer", "C99812"),
    ("Vertragsnummer: V-2026-17", "contract", "V202617"),
    ("Vertragskonto 2000123456", "contract", "2000123456"),
    ("Policy number PL-445566", "contract", "P1445566"),
])
def test_the_ways_the_words_are_written(text: str, kind: str, compare: str) -> None:
    assert (kind, compare) in found(text)


@pytest.mark.parametrize(("scanned", "clean"), [
    # A zero read as the letter O, a one as l or I.
    ("Rechnungsnummer R-2O26-OOO17", "Rechnungsnummer R-2026-00017"),
    ("Rechnungsnummer R-2026-000l7", "Rechnungsnummer R-2026-00017"),
    ("Rechnungsnummer R-2026-000I7", "Rechnungsnummer R-2026-00017"),
    # Blanks and dashes in the number.
    ("Rechnungsnummer R-2026 - 00017", "Rechnungsnummer R-2026-00017"),
    ("Rechnungsnummer R 2026 00017", "Rechnungsnummer R-2026-00017"),
    ("Rechnungsnummer R2026/00017", "Rechnungsnummer R-2026-00017"),
    ("Rechnungsnummer r-2026-00017", "Rechnungsnummer R-2026-00017"),
    # The number on the line after its word.
    ("Rechnungsnummer\nR-2026-00017", "Rechnungsnummer R-2026-00017"),
    ("Lieferschein:\n  LS-004711", "Lieferschein LS-004711"),
])
def test_what_a_scan_does_to_a_number_does_not_change_it(scanned: str, clean: str) -> None:
    assert found(scanned) and found(scanned) == found(clean)


@pytest.mark.parametrize("text", [
    "Rechnungsdatum 01.10.2026",
    "Rechnungsbetrag 123,45 EUR",
    "Rechnung vom 01.10.2026",
    "Rechnung folgt separat.",
    "Ihre Bestellung vom 03.10.2026 ist eingegangen.",
    "Auftraggeber: Stadtwerke Lindenau",
    "Order date: 2026-10-01",
    "In order to help you",
    "Rechnungsnummer   Datum   Kundennummer",
    "Bestellnummer 12,50",
    "Art.-Nr. 4711 Muster",
])
def test_no_number_where_none_follows_its_word(text: str) -> None:
    assert [kind for kind, _ in found(text) if kind != "iban"] == []


def test_a_number_runs_to_the_end_of_the_number_not_into_the_sentence() -> None:
    assert found("Rechnungsnummer R-2026-00017. Bitte überweisen") == [("invoice", "R202600017")]
    assert found("Rechnung Nr. 12345 vom 01.10.2026") == [("invoice", "12345")]
    assert found("Lieferschein LS-4711, Kunde 99") == [("delivery", "1S4711")]


def test_an_iban_counts_only_with_valid_check_digits() -> None:
    good = "DE89 3704 0044 0532 0130 00"
    assert found(f"IBAN {good}") == [("iban", "DE89370400440532013000")]
    assert found("IBAN DE89370400440532013000 BIC COBADEFFXXX") == [("iban", "DE89370400440532013000")]
    # One digit off: the check digits do not fit.
    assert found("IBAN DE89 3704 0044 0532 0130 01") == []
    assert found("IBAN DE00 3704 0044 0532 0130 00") == []
    # Of another country, length taken from its rule.
    assert found("IBAN AT61 1904 3002 3457 3201") == [("iban", "AT611904300234573201")]
    # Two in one letter: both, in their order.
    two = numbers.read(f"IBAN {good}\nOder: AT61 1904 3002 3457 3201")
    assert [n.value for n in two if n.kind == "iban"] == ["DE89370400440532013000", "AT611904300234573201"]


def test_the_e_invoice_goes_first_for_its_number_and_iban() -> None:
    text = "Rechnungsnummer R-2026-00017\nIBAN DE89 3704 0044 0532 0130 00\nBestellnummer B-1234567"
    read = numbers.read(text, invoice_number="INV-2026-1", invoice_iban="AT611904300234573201")
    assert [(n.kind, n.value, n.origin) for n in read] == [
        ("invoice", "INV-2026-1", "einvoice"), ("iban", "AT611904300234573201", "einvoice"),
        ("order", "B-1234567", "text")]
    # An e-invoice without these leaves them to the text.
    assert {(n.kind, n.origin) for n in numbers.read(text, invoice_number="", invoice_iban="")} == {
        ("invoice", "text"), ("iban", "text"), ("order", "text")}
    # An IBAN in the data with wrong check digits is no IBAN: the text is asked.
    assert [n.origin for n in numbers.read(text, invoice_iban="DE00370400440532013000") if n.kind == "iban"] == ["text"]


def test_every_kind_and_number_once_and_not_too_many() -> None:
    text = "\n".join(f"Bestellnummer B-{index:07d}" for index in range(30)) + "\nBestellnummer B-0000001"
    read = numbers.read(text)
    assert len(read) == numbers.PER_KIND and len({n.compare for n in read}) == numbers.PER_KIND


@pytest.mark.parametrize("hostile", [
    "Rechnungsnummer " * 4000,
    "Rechnung" + " " * 39_000 + "1",
    "Rechnungsnummer " + "1-" * 20_000,
    "Rechnungsnummer " + "A1 " * 13_000,
    "DE89 " * 9000,
    "DE" + "1" * 39_000,
    "Rechnungsnummer\n" * 2500 + "\n\n\n",
    "re.-nr. " * 5000,
], ids=lambda value: f"{value[:12]!r}x{len(value)}")
def test_hostile_text_is_read_in_bounded_time(hostile: str) -> None:
    started = time.perf_counter()
    numbers.read(hostile * 3)
    assert time.perf_counter() - started < 1.0


# --- Kept with the document ----------------------------------------------------------------------------------------


def give_text(document_id: int, text: str) -> None:
    """The text of the document's current version, as the worker keeps it, in a transaction that takes a change
    number (as reading a document does)."""
    with SessionLocal() as db:
        changes.write_lock(db)
        document = db.get(Document, document_id)
        assert document is not None
        version = db.scalar(select(Version).where(Version.document_id == document_id,
                                                  Version.n == document.current_version))
        assert version is not None
        processing._keep_text(db, version, [text], 0, "deu")
        document.change_seq = changes.next_seq(db)
        db.commit()


def kept(document_id: int) -> list[tuple[str, str, str]]:
    with SessionLocal() as db:
        return [(n.kind, n.value, n.origin) for n in db.scalars(
            select(DocumentNumber).where(DocumentNumber.document_id == document_id).order_by(DocumentNumber.id))]


def test_the_numbers_follow_the_text_in_the_same_transaction(client: object, caplog: pytest.LogCaptureFixture) -> None:
    jule = make_account("jule")
    document = add_document(own_vault(jule), jule, "Strom")
    assert kept(document) == []
    with caplog.at_level(logging.DEBUG):
        give_text(document, "Rechnungsnummer R-2026-00017\nKundennummer 100 2345")
    assert kept(document) == [("invoice", "R-2026-00017", "text"), ("customer", "100 2345", "text")]
    # A new text, new numbers; the old ones are gone.
    give_text(document, "Lieferschein LS-004711")
    assert kept(document) == [("delivery", "LS-004711", "text")]
    # Numbers never go to the log.
    assert "R-2026" not in caplog.text and "004711" not in caplog.text and "2345" not in caplog.text


def test_numbers_are_read_again_only_when_what_they_come_from_changes(
    client: object, monkeypatch: pytest.MonkeyPatch,
) -> None:
    jule = make_account("jule")
    document = add_document(own_vault(jule), jule, "Strom")
    give_text(document, "Rechnungsnummer R-2026-00017")
    calls: list[str] = []
    original = numbers.read
    monkeypatch.setattr(numbers, "read", lambda text, **kw: calls.append(text) or original(text, **kw))
    # A change of a field takes a change number but leaves the text as it was: nothing is read.
    with SessionLocal() as db:
        changes.write_lock(db)
        row = db.get(Document, document)
        assert row is not None
        row.title = "Strom Oktober"
        row.change_seq = changes.next_seq(db)
        db.commit()
    assert calls == []
    give_text(document, "Rechnungsnummer R-2026-00018")
    assert len(calls) == 1


def test_the_e_invoice_of_a_document_gives_its_number_and_iban_not_the_buyer_reference(client: object) -> None:
    jule = make_account("jule")
    document = add_document(own_vault(jule), jule, "Rechnung")
    with SessionLocal() as db:
        changes.write_lock(db)
        row = db.get(Document, document)
        assert row is not None
        version = db.scalar(select(Version).where(Version.document_id == document))
        assert version is not None
        db.add(EInvoice(version_id=version.id, document_id=document, format="XRechnung (UBL)", number="R-2026-00017",
                        seller="Stadtwerke Lindenau", seller_vat="", buyer="", buyer_ref="991-12345-67",
                        iban="DE89370400440532013000", currency="EUR", credit_note=False))
        row.change_seq = changes.next_seq(db)
        db.commit()
    assert kept(document) == [("invoice", "R-2026-00017", "einvoice"), ("iban", "DE89370400440532013000", "einvoice")]
    payment = numbers.for_payment(SessionLocal(), document)
    assert payment.ibans == [("DE89370400440532013000", "einvoice")]
    assert payment.invoice_number == ("R-2026-00017", "einvoice")


def test_the_payment_facts_name_where_each_comes_from(client: object) -> None:
    jule = make_account("jule")
    document = add_document(own_vault(jule), jule, "Rechnung")
    give_text(document, "Rechnung Nr. R-2026-00017\nIBAN DE89 3704 0044 0532 0130 00\nOder AT61 1904 3002 3457 3201")
    with SessionLocal() as db:
        payment = numbers.for_payment(db, document)
        assert payment.ibans == [("DE89370400440532013000", "text"), ("AT611904300234573201", "text")]
        assert payment.invoice_number == ("R-2026-00017", "text")
        nothing = numbers.for_payment(db, add_document(own_vault(jule), jule, "Leer"))
        assert nothing.ibans == [] and nothing.invoice_number is None


def test_a_document_read_by_the_worker_gets_its_numbers(client, operator: object) -> None:  # type: ignore[no-untyped-def]
    from . import files
    from .intake import upload_and_read

    content = files.make_pdf([("Stadtwerke Lindenau Rechnung\nmit genug Text, damit die Seite\nals Text gilt.\n"
                               "Rechnungsnummer R-2026-00017\nBestellnummer B-1234567")])
    document = upload_and_read(client, "Rechnung.pdf", content)
    assert ("invoice", "R-2026-00017", "text") in kept(document["id"])
    assert ("order", "B-1234567", "text") in kept(document["id"])


def test_the_job_reads_every_document_there_was_once_in_portions_and_survives_a_stop(
    client: object, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models import Job
    from app.services import jobs

    jule = make_account("jule")
    vault = own_vault(jule)
    made = [add_document(vault, jule, f"Brief {index}") for index in range(7)]
    with SessionLocal() as db:
        for document_id in made:
            version = db.scalar(select(Version).where(Version.document_id == document_id))
            assert version is not None
            processing._keep_text(db, version, [f"Rechnungsnummer R-2026-{document_id:05d}"], 0, "deu")
        db.commit()
        # Kept straight in, as a database of before the numbers has them: nothing read yet.
        db.execute(DocumentNumber.__table__.delete())
        db.execute(NumbersRead.__table__.delete())
        db.commit()
    monkeypatch.setattr(numbers, "BATCH", 3)
    monkeypatch.setattr(numbers, "PAUSE_SECONDS", 0)
    with SessionLocal() as db:
        jobs.enqueue(db, numbers.JOB, 0, {"after": 0})
        db.commit()
    # One portion, then the server stops: the job that ran is done, the next one waits with the place it got to.
    assert jobs.run_pending(limit=1, kinds=(numbers.JOB,)) == 1
    with SessionLocal() as db:
        waiting = db.scalars(select(Job).where(Job.kind == numbers.JOB, Job.state == "queued")).all()
        assert len(waiting) == 1 and waiting[0].payload == {"after": made[2]}
        db.execute(Job.__table__.update().where(Job.id == waiting[0].id).values(state="running"))
        db.commit()
        jobs.recover(db)
    assert jobs.run_pending(kinds=(numbers.JOB,)) == 3
    for document_id in made:
        assert kept(document_id) == [("invoice", f"R-2026-{document_id:05d}", "text")]
    with SessionLocal() as db:
        assert db.scalars(select(Job).where(Job.kind == numbers.JOB, Job.state == "queued")).all() == []
    # Once: nothing is waiting, and running it again reads nothing anew.
    calls: list[str] = []
    original = numbers.read
    monkeypatch.setattr(numbers, "read", lambda text, **kw: calls.append(text) or original(text, **kw))
    with SessionLocal() as db:
        jobs.enqueue(db, numbers.JOB, 0, {"after": 0})
        db.commit()
    jobs.run_pending(kinds=(numbers.JOB,))
    assert calls == []
