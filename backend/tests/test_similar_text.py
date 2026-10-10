""""Looks like a document you have": the picture and the text must both say so.

The thresholds of ``services/similar.py`` are set by these cases: ten monthly invoices of one form (the case that
fools a picture hash: the reviewer of B2 measured 32 of 45 pairs within 16 bits) must not be called alike; the same
invoice read twice must. The numbers measured are printed (``pytest -s``) and kept in ``docs/search.md``.
"""

from __future__ import annotations

import itertools
import random
import re

import pytest
from fastapi.testclient import TestClient

from app.models import Account
from app.services import ocr, similar

from .files import make_pdf
from .intake import process_all, row_of, upload_one
from .invoices import monthly_invoice, picture_bytes, scan_pdf, sheet

_SWAPS = [("l", "1"), ("O", "0"), ("rn", "m"), ("e", "c"), ("ü", "u"), ("i", "l"), (",", "."), ("5", "S")]


def misread(text: str, rate: float, seed: int) -> str:
    """The text as a recognition might read it: here and there a letter of a word taken for another."""
    rng = random.Random(seed)
    out = []
    for word in re.split(r"(\s+)", text):
        # Numbers stay: a misread invoice number or date is a reason never to call two texts alike (``distinct``).
        if word.strip() and not any(c.isdigit() for c in word) and rng.random() < rate:
            old, new = rng.choice(_SWAPS)
            word = word.replace(old, new, 1) if old in word else word[:-1] + ("." if word[-1:].isalnum() else "")
        out.append(word)
    return "".join(out)


def test_monthly_invoices_of_one_form_are_not_alike_and_the_same_one_read_twice_is() -> None:
    texts = ["\n".join(monthly_invoice(month)) for month in range(1, 11)]
    others = [similar.text_likeness(a, b) for a, b in itertools.combinations(texts, 2)]
    again = [similar.text_likeness(text, misread(text, 0.04, seed)) for seed, text in enumerate(texts)]
    print(f"\nmonthly pairs: words {min(o[0] for o in others):.2f}..{max(o[0] for o in others):.2f}, numbers "
          f"{min(o[1] for o in others):.2f}..{max(o[1] for o in others):.2f} ({len(others)} pairs)")
    print(f"read twice (4 % of words misread): words {min(a[0] for a in again):.2f}.., numbers "
          f"{min(a[1] for a in again):.2f}..")
    assert not any(similar.text_alike(a, b) for a, b in itertools.combinations(texts, 2))
    assert all(similar.text_alike(text, misread(text, 0.04, seed)) for seed, text in enumerate(texts))
    # The words alone would not tell them apart: that is why the numbers count.
    assert min(o[0] for o in others) >= similar.WORDS_ALIKE
    assert max(o[1] for o in others) < similar.NUMBERS_ALIKE
    # Nothing to compare: never alike.
    assert not similar.text_alike("", texts[0]) and not similar.text_alike(" \n", " ")


def test_a_letter_without_numbers_needs_nearly_all_its_words() -> None:
    letter = "Liebe Eltern, am Montag ist der Wandertag. Bitte denkt an Regenjacke, Brotdose und feste Schuhe."
    assert similar.text_alike(letter, letter.replace("Regenjacke", "Regenjackc"))
    assert not similar.text_alike(letter, letter.replace("Montag", "Freitag").replace("Regenjacke", "Sonnenhut")
                                  .replace("feste", "leichte"))


def _duplicate(client: TestClient, document: dict) -> dict | None:
    return client.get(f"/api/v1/documents/{document['id']}").json()["duplicate"]


def test_the_next_months_invoice_is_not_called_alike_and_the_same_invoice_again_is(client: TestClient,
                                                                                     operator: Account) -> None:
    march = upload_one(client, "Maerz.pdf", make_pdf(["\n".join(monthly_invoice(3))]))
    april = upload_one(client, "April.pdf", make_pdf(["\n".join(monthly_invoice(4))]))
    # The same invoice made again (other bytes, so not the same file).
    again = upload_one(client, "Maerz nochmal.pdf", make_pdf(["\n".join(monthly_invoice(3))], padding=64))
    process_all()
    assert _duplicate(client, march) is None
    assert _duplicate(client, april) is None, "a monthly invoice of the same form is not a copy"
    assert _duplicate(client, again) == {"document_id": march["id"], "title": "Maerz", "kind": "similar"}


def test_alike_only_among_what_the_owner_may_see(client: TestClient, operator: Account) -> None:
    from .conftest import make_account, new_client

    jule = make_account("jule")
    upload_one(client, "Maerz.pdf", make_pdf(["\n".join(monthly_invoice(3))]))
    process_all()
    with new_client(jule) as browser:
        hers = upload_one(browser, "Maerz.pdf", make_pdf(["\n".join(monthly_invoice(3))], padding=32))
        process_all()
        assert browser.get(f"/api/v1/documents/{hers['id']}").json()["duplicate"] is None
    # Not only hidden in the answer: never looked at.
    assert row_of(hers["id"]).duplicate_of is None


@pytest.mark.skipif(not ocr.available(), reason="needs ocrmypdf and Tesseract (they are in the image; run there)")
def test_scans_the_same_sheet_scanned_again_is_alike_and_the_next_month_is_not(client: TestClient,
                                                                               operator: Account) -> None:
    from app.services import pages as page_service  # noqa: F401 - the worker draws the fingerprint

    first = upload_one(client, "Scan Maerz.pdf", scan_pdf(sheet(monthly_invoice(3), angle=0.3, noise=3000, seed=1)))
    rescan = upload_one(client, "Scan Maerz 2.jpg", picture_bytes(
        sheet(monthly_invoice(3), angle=-0.4, noise=5000, brightness=238, seed=2), "jpeg", 70))
    april = upload_one(client, "Scan April.pdf", scan_pdf(sheet(monthly_invoice(4), angle=0.2, noise=3000, seed=3)))
    process_all()
    texts = {name: client.get(f"/api/v1/documents/{doc['id']}/versions/1/text").json()
             for name, doc in (("first", first), ("rescan", rescan), ("april", april))}
    assert all(t["ocr_pages"] == 1 for t in texts.values()), texts
    first_text, rescan_text, april_text = ("\n".join(texts[k]["pages"]) for k in ("first", "rescan", "april"))
    print("\nscans: same sheet", similar.text_likeness(first_text, rescan_text), "next month",
          similar.text_likeness(first_text, april_text))
    assert _duplicate(client, rescan) == {"document_id": first["id"], "title": "Scan Maerz", "kind": "similar"}
    assert _duplicate(client, april) is None


def _fingerprint(pdf: bytes) -> str:
    import pypdfium2

    from app import worker

    document = pypdfium2.PdfDocument(pdf)
    try:
        return worker.fingerprint(worker._drawn(document[0], worker.HASH_SOURCE_WIDTH, 16_000_000))
    finally:
        document.close()


def test_the_picture_of_a_rescan_moves_far_and_only_rules_out_what_does_not_look_alike() -> None:
    import statistics

    variants = [{"angle": 0.3, "noise": 3000, "seed": 1}, {"angle": -0.4, "noise": 5000, "brightness": 238, "seed": 2},
                {"angle": 0.9, "noise": 2000, "seed": 3}, {"angle": -1.0, "noise": 6000, "brightness": 225, "seed": 4},
                {"angle": 0.0, "noise": 0, "seed": 5}]
    rescans = [_fingerprint(scan_pdf(sheet(monthly_invoice(3), **v))) for v in variants]  # type: ignore[arg-type]
    same = [similar.distance(a, b) for a, b in itertools.combinations(rescans, 2)]
    monthly = [_fingerprint(scan_pdf(sheet(monthly_invoice(m), angle=0.2, noise=2000, seed=m))) for m in range(1, 7)]
    months = [similar.distance(a, b) for a, b in itertools.combinations(monthly, 2)]
    print(f"\nsame sheet rescanned: {min(same)}..{max(same)} bits (median {statistics.median(same)}); monthly invoices "
          f"{min(months)}..{max(months)}")
    # A rescan is far past the 16 bits of a file drawn again, and still within the picture's gate.
    assert max(same) <= similar.PICTURE_BITS < 1024 // 2
    assert min(same) > similar.THRESHOLD_BITS
    # A blank page has no fingerprint, and nothing is alike to it.
    blank = _fingerprint(scan_pdf(sheet([])))
    assert blank == "" and similar.distance(blank, rescans[0]) > similar.PICTURE_BITS


def phone_invoice(month: int) -> str:
    """A made-up phone invoice whose prices and contract lines stay the same every month (the reviewer's case)."""
    return "\n".join([
        "Mobilfunk Welle GmbH, Wellenweg 9, 12345 Lindenau",
        f"Rechnung Nr. MW-{month:02d}7{month * 37 % 100:02d}41",
        f"Rechnungsdatum 02.{month:02d}.2026, Zeitraum 01.{month:02d}.2026 bis 28.{month:02d}.2026",
        "Kundennummer 88 1234 5678, Tarif Welle M, Tarifnummer 4711-22",
        "Vertragsbeginn 01.04.2024, Hotline 0800 123 456",
        "Grundgebuehr 19,99 EUR, Datenpaket 5,00 EUR, Rufnummer 2,50 EUR, Versicherung 4,99 EUR",
        "Summe 32,48 EUR, darin Umsatzsteuer 5,19 EUR",
        "Der Betrag wird von IBAN DE00 1234 5678 9012 3456 78 abgebucht.",
    ])


def rent(month: int) -> str:
    """A made-up rent statement: the same amount every month, only the month and the date change."""
    names = ["Januar", "Februar", "Maerz", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober"]
    return "\n".join([
        "Hausverwaltung Ziegel, Am Markt 1, 12345 Lindenau",
        f"Mietzahlung {names[month - 1]} 2026, faellig am 03.{month:02d}.2026",
        "Kaltmiete 850,00 EUR, Nebenkosten 150,00 EUR, Heizung 90,00 EUR, zusammen 1090,00 EUR",
        "Wohnung 3. OG links, Lindenallee 12, Mietvertrag vom 15.08.2021",
        "Bitte ueberweisen Sie auf IBAN DE00 9876 5432 1098 7654 32.",
    ])


def test_invoices_with_fixed_lines_and_a_rent_are_never_called_alike_and_their_rescan_is() -> None:
    """The reviewer's cases: a phone invoice with fixed prices and contract lines (numbers in common: 0.80 before) and
    a rent with the same amount every month. What tells one month from the next is the invoice number and the dates."""
    for make in (phone_invoice, rent):
        months = [make(m) for m in range(1, 7)]
        for a, b in itertools.combinations(months, 2):
            assert not similar.text_alike(a, b), (make.__name__, similar.text_likeness(a, b))
            assert similar.distinct(a, b)
        # The same month read again with a few words misread (numbers intact): alike.
        for seed, text in enumerate(months):
            again = misread(text, 0.0, seed).replace("Rechnung", "Rcchnung").replace("Hausverwaltung", "Hausverwa1tung")
            assert similar.text_alike(text, again), make.__name__
    # The numbers measured.
    shares = [similar.text_likeness(phone_invoice(1), phone_invoice(m))[1] for m in range(2, 7)]
    print(f"\nphone invoice, numbers in common: {min(shares):.2f}..{max(shares):.2f}")


def test_the_same_numbers_do_not_make_different_words_alike() -> None:
    """Two letters with the same numbers and dates (a date, an amount, a number) but other words are not the same sheet:
    the words must agree too (``WORDS_ALIKE``)."""
    numbers = "am 03.10.2026, Betrag 1234,56 EUR, Vorgang 2026-778811, Konto 600 123 456"
    a = f"Liebe Jule, die Heizung wird gewartet {numbers}. Bitte den Keller freiraeumen, danke und viele Gruesse."
    b = f"Sehr geehrte Frau, Ihr Antrag auf Erstattung ist eingegangen {numbers}. Wir melden uns schriftlich bei Ihnen."
    words, figures, _ = similar.text_likeness(a, b)
    assert figures == 1.0 and words < 0.5
    assert not similar.text_alike(a, b)
    # Half the words the same is still not enough.
    c = a.replace("Heizung wird gewartet", "Treppe wird geputzt").replace("Keller freiraeumen", "Fahrrad wegstellen")
    assert similar.text_likeness(a, c)[0] < similar.WORDS_ALIKE and not similar.text_alike(a, c)


def test_another_invoice_number_alone_makes_two_texts_different() -> None:
    """Everything the same but the invoice number (the longest number): never alike, whatever the shares say."""
    a = phone_invoice(3)
    b = a.replace("MW-03", "MW-93")
    words, numbers, _ = similar.text_likeness(a, b)
    assert words == 1.0 and numbers >= similar.NUMBERS_ALIKE
    assert similar.distinct(a, b) and not similar.text_alike(a, b)
