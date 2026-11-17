"""The date, the due date and the amount read from the text of made-up invoices, German and English, with the reason
for the choice when there are several."""

from __future__ import annotations

import time
from datetime import date as Date

import pytest

from app.services import textfacts

from .invoices import monthly_invoice

TODAY = Date(2026, 10, 10)


def read(text: str) -> textfacts.Facts:
    return textfacts.read(text, TODAY)


@pytest.mark.parametrize(("text", "day"), [
    ("Rechnungsdatum: 01.10.2026", Date(2026, 10, 1)),
    ("Lindenau, den 1. Oktober 2026", Date(2026, 10, 1)),
    ("Lindenau, 3. März 2026", Date(2026, 3, 3)),
    ("Datum 2026-10-01", Date(2026, 10, 1)),
    ("Invoice date: October 1, 2026", Date(2026, 10, 1)),
    ("Date 1 October 2026", Date(2026, 10, 1)),
    ("Datum: 05.09.26", Date(2026, 9, 5)),
    ("Date: 30/09/2026", Date(2026, 9, 30)),
])
def test_dates_in_the_forms_people_write(text: str, day: Date) -> None:
    assert read(text).date == day


def test_the_named_date_wins_over_the_first_one() -> None:
    text = "Elektro Brandt GmbH\nAngebot vom 12.08.2026 angenommen\nRechnungsdatum 06.10.2026\nSumme 224,91 EUR"
    facts = read(text)
    assert facts.date == Date(2026, 10, 6) and facts.date_reason == "labelled"


def test_without_a_name_the_first_plausible_date_is_taken() -> None:
    facts = read("Lindenau, 14.09.2026\nIhre Bestellung\nLieferung am 20.09.2026")
    assert facts.date == Date(2026, 9, 14) and facts.date_reason == "first"


def test_a_due_date_is_never_the_date_of_the_document() -> None:
    facts = read("Bitte überweisen Sie den Betrag bis zum 30.10.2026.\nRechnung vom 15.10.2026")
    assert facts.due == Date(2026, 10, 30) and facts.date == Date(2026, 10, 15)
    for text, due in (("fällig am 15.10.2026", Date(2026, 10, 15)), ("zu zahlen bis 20.10.2026", Date(2026, 10, 20)),
                      ("zahlbar bis 1. November 2026", Date(2026, 11, 1)), ("Due date: 2026-11-05", Date(2026, 11, 5)),
                      ("Payable by November 3, 2026", Date(2026, 11, 3))):
        assert read(text).due == due, text


def test_the_start_of_a_period_and_dates_far_off_are_no_document_date() -> None:
    facts = read("Abrechnungszeitraum 01.09.2026 bis 30.09.2026\nGeburtsdatum 03.04.1961\nVertrag bis 31.12.2031\n"
                 "Leistung 01.08.2026 - 31.08.2026\nLindenau, 05.10.2026")
    # Both ends of a span, a birthday 65 years ago and a date years ahead are not the letter's date.
    assert facts.date == Date(2026, 10, 5) and facts.date_reason == "first"


@pytest.mark.parametrize(("text", "cents"), [
    ("Gesamtbetrag 1.234,56 €", 123456),
    ("Summe: 142,80 €", 14280),
    ("Rechnungsbetrag EUR 86,40", 8640),
    ("Total EUR 1,234.56", 123456),
    ("Amount due: $1,234.56", 123456),
    ("Summe 142,80", 14280),
    ("zu zahlen 612,00 Euro", 61200),
])
def test_amounts_in_german_and_english(text: str, cents: int) -> None:
    facts = read(text)
    assert facts.amount == cents and facts.amount_reason == "total"


def test_the_total_wins_over_the_net_and_the_tax() -> None:
    text = "Wartung 189,00 €\nNetto 189,00 €\nUSt 19 % 35,91 €\nGesamt 224,91 €\nAnzahlung bereits 500,00 €"
    facts = read(text)
    # "Gesamt" names the total; the larger 500,00 is no total, the net and the tax are parts.
    assert facts.amount == 22491 and facts.amount_reason == "total" and facts.currency == "EUR"


def test_the_strongest_name_of_a_total_wins() -> None:
    text = "Summe Positionen 300,00 €\nRechnungsbetrag 357,00 €\nSumme Rabatt 10,00 €"
    assert read(text).amount == 35700


def test_without_a_total_the_largest_amount_with_a_currency() -> None:
    facts = read("Kassenbon\nWaschmaschine WM 8 Eco 649,00 €\nVersand 0,00 €\nTasche 4,90 €")
    assert facts.amount == 64900 and facts.amount_reason == "largest"


def test_a_monthly_invoice_of_the_tests() -> None:
    facts = read("\n".join(monthly_invoice(9)))
    assert facts.date is not None and facts.date.month == 9 and facts.date_reason == "labelled"
    assert facts.due == Date(2026, 9, 15) and facts.amount is not None and facts.amount_reason == "total"


def test_numbers_that_are_no_dates_or_amounts() -> None:
    facts = read("Kundennummer 4471 0923\nZählerstand 31.12 kWh\nTelefon 01234 56789\nIBAN DE00 1234 5678 9012")
    assert facts.date is None and facts.amount is None and facts.due is None


def test_a_hostile_text_takes_no_long() -> None:
    hostile = ("1.1.1.1.1.1.1." * 2000 + "1,234,567,890," * 2000 + "Summe " * 3000)[: textfacts.MAX_TEXT * 2]
    started = time.monotonic()
    read(hostile)
    assert time.monotonic() - started < 2.0


# --- All the dates of a text, to choose from (issue #9) ---------------------------------------------------------------

def test_found_dates_are_every_distinct_date_in_the_order_of_the_text_with_what_names_them() -> None:
    text = ("Lindenau, 03.10.2026\nAngebot vom 12.08.2026\nRechnungsdatum 06.10.2026\n"
            "Leistungszeitraum 01.09.2026 bis 30.09.2026\nZahlbar bis 20.10.2026\n"
            "Wie besprochen am 06.10.2026\nTermin 2026-11-05")
    assert textfacts.found_dates(text, TODAY) == [
        (Date(2026, 10, 3), ""), (Date(2026, 8, 12), ""), (Date(2026, 10, 6), "date"), (Date(2026, 9, 1), "period"),
        (Date(2026, 9, 30), "period"), (Date(2026, 10, 20), "due"), (Date(2026, 11, 5), "")]


def test_a_date_that_stands_again_keeps_the_first_word_that_names_it() -> None:
    text = "Brief vom 01.10.2026\nRechnungsdatum 01.10.2026\nFällig am 01.10.2026"
    assert textfacts.found_dates(text, TODAY) == [(Date(2026, 10, 1), "date")]


def test_found_dates_leave_out_what_is_no_date_of_a_paper_and_stop_at_the_most() -> None:
    old = TODAY.replace(year=TODAY.year - textfacts.OLDEST_YEARS - 1)
    far = TODAY.replace(year=TODAY.year + textfacts.FURTHEST_YEARS + 1)
    text = f"Geboren {old:%d.%m.%Y}\nGültig bis {far:%d.%m.%Y}\nDatum 01.10.2026"
    assert textfacts.found_dates(text, TODAY) == [(Date(2026, 10, 1), "date")]
    many = "\n".join(f"Am {day:02d}.10.2026" for day in range(1, 29))
    found = textfacts.found_dates(many, TODAY)
    assert len(found) == textfacts.MOST_FOUND and found[0][0] == Date(2026, 10, 1)
    assert found[-1][0] == Date(2026, 10, textfacts.MOST_FOUND)
    assert textfacts.found_dates("", TODAY) == [] and textfacts.found_dates("keine Zahl", TODAY) == []


def test_found_dates_cost_time_in_proportion_to_the_text() -> None:
    hostile = "1.1." * 50_000 + "01.10.2026"
    began = time.perf_counter()
    textfacts.found_dates(hostile, TODAY)
    assert time.perf_counter() - began < 2.0
