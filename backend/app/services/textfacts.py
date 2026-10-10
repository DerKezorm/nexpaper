"""The date, the due date and the amount of a document, read from its text (German and English).

nexpaper proposes them in the inbox ("aus dem Text"); a person confirms. Nothing here guesses wildly: a date or an
amount is taken only in a form people write (``01.10.2026``, ``1. Oktober 2026``, ``2026-10-01``, ``October 1, 2026``;
``1.234,56 €``, ``EUR 1,234.56``), and when there are several, the choice has a reason that can be told:

* **The date of the document**: the one after a word that names it (``Rechnungsdatum``, ``Datum``, ``Invoice date``),
  else the first date in the text that is no due date, no later than ``today`` and not long ago (``labelled`` or
  ``first``).
* **The due date**: only one after a word that names it (``fällig``, ``zu zahlen bis``, ``zahlbar bis``, ``due``).
* **The amount**: the one after a word that names a total (``Gesamtbetrag``, ``Rechnungsbetrag``, ``Summe``,
  ``Total``), the largest of them when several are named; else the largest amount with a currency (``total`` or
  ``largest``). Lines that name a part (``Netto``, ``USt``, ``Zwischensumme``) never give the amount.

The patterns are plain and bounded (no nested repetition), and only the first ``MAX_TEXT`` characters are read: a
hostile text costs time in proportion to its length, never more.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as Date
from datetime import timedelta

#: The characters of a text that are looked at (the first pages of nearly every invoice).
MAX_TEXT = 40_000
#: A document date further back than this many years is no proposal.
OLDEST_YEARS = 30

MONTHS = {
    "januar": 1, "jänner": 1, "jan": 1, "january": 1, "februar": 2, "feb": 2, "february": 2, "märz": 3, "maerz": 3,
    "mär": 3, "mrz": 3, "march": 3, "mar": 3, "april": 4, "apr": 4, "mai": 5, "may": 5, "juni": 6, "jun": 6,
    "june": 6, "juli": 7, "jul": 7, "july": 7, "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "oktober": 10, "okt": 10, "october": 10, "oct": 10, "november": 11, "nov": 11, "dezember": 12, "dez": 12,
    "december": 12, "dec": 12,
}
_MONTH = "|".join(sorted((re.escape(name) for name in MONTHS), key=len, reverse=True))

_NUMERIC = re.compile(r"(?<![\d.])(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4}|\d{2})(?![\d.]\d)")
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_SLASH = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4})(?![\d/])")
_DAY_MONTH = re.compile(rf"(?<!\d)(\d{{1,2}})\.?\s(?:de\s)?({_MONTH})\.?\s(\d{{4}})(?!\d)", re.IGNORECASE)
_MONTH_DAY = re.compile(rf"(?<![A-Za-z])({_MONTH})\.?\s(\d{{1,2}})(?:st|nd|rd|th)?,?\s(\d{{4}})(?!\d)", re.IGNORECASE)

DATE_WORDS = re.compile(
    r"(rechnungsdatum|belegdatum|ausstellungsdatum|datum|invoice\s+date|date\s+of\s+issue|issue\s+date|date)\b",
    re.IGNORECASE)
DUE_WORDS = re.compile(
    r"(fällig(?:\s+(?:am|zum|bis))?|faellig|zu\s+zahlen\s+bis|zahlbar\s+bis|zahlungsziel|bis\s+zum|due(?:\s+date)?|"
    r"payable\s+by|pay\s+by|payment\s+due)\b", re.IGNORECASE)
#: Words that name a span of time: a date right after them is the start of a period, not the date of the document.
PERIOD_WORDS = re.compile(r"(zeitraum|period|from|von)\s*:?\s*$", re.IGNORECASE)
#: What follows the first date of a span ("01.09.2026 bis 30.09.2026").
PERIOD_AFTER = re.compile(r"\s*(?:bis|-|" + chr(0x2013) + r"|to|until)\s*\d", re.IGNORECASE)
#: What stands before the second date of a span.
PERIOD_BEFORE = re.compile(r"\d\s*(?:bis|-|" + chr(0x2013) + r"|to|until)\s*$", re.IGNORECASE)

_CURRENCY = r"(?:€|EUR|Euro|USD|\$|CHF|GBP|£)"
_NUMBER = r"\d{1,3}(?:[.,'\u202f\u00a0 ]\d{3}){0,6}(?:[.,]\d{2})|\d+(?:[.,]\d{2})"
_AMOUNT_AFTER = re.compile(rf"(?<![\d.,])({_NUMBER})\s?({_CURRENCY})(?![A-Za-z])", re.IGNORECASE)
_AMOUNT_BEFORE = re.compile(rf"(?<![A-Za-z])({_CURRENCY})\s?(-?{_NUMBER})(?![\d])", re.IGNORECASE)
_AMOUNT_BARE = re.compile(rf"(?<![\d.,])({_NUMBER})(?![\d.,]?\d)")
TOTAL_WORDS = re.compile(
    r"(gesamtbetrag|rechnungsbetrag|endbetrag|bruttobetrag|zahlbetrag|gesamtsumme|summe|gesamt|zu\s+zahlen|"
    r"betrag|grand\s+total|total\s+due|amount\s+due|balance\s+due|total)\b", re.IGNORECASE)
PART_WORDS = re.compile(
    r"(netto|nettobetrag|zwischensumme|ust|mwst|umsatzsteuer|mehrwertsteuer|steuer|rabatt|skonto|abschlag\s+bereits|"
    r"subtotal|net\b|vat|tax|discount)", re.IGNORECASE)
#: The strongest words first: a total named so beats one named only "Summe".
STRONG_TOTAL = re.compile(
    r"(gesamtbetrag|rechnungsbetrag|endbetrag|zahlbetrag|zu\s+zahlen|grand\s+total|total\s+due|amount\s+due|"
    r"balance\s+due)", re.IGNORECASE)
CURRENCIES = {"€": "EUR", "eur": "EUR", "euro": "EUR", "usd": "USD", "$": "USD", "chf": "CHF", "gbp": "GBP", "£": "GBP"}


@dataclass(frozen=True)
class Facts:
    date: Date | None = None
    #: ``labelled`` (after a word that names it) or ``first`` (the first plausible date).
    date_reason: str = ""
    due: Date | None = None
    #: In cents.
    amount: int | None = None
    #: ``total`` (after a word that names a total) or ``largest`` (the largest amount with a currency).
    amount_reason: str = ""
    currency: str = ""


@dataclass(frozen=True)
class _Found:
    at: int
    value: Date
    end: int = 0


def _year(value: str) -> int:
    year = int(value)
    return year + 2000 if len(value) == 2 else year


def _make(year: int, month: int, day: int) -> Date | None:
    try:
        return Date(year, month, day)
    except ValueError:
        return None


def dates_in(text: str) -> list[_Found]:
    """Every date written in a known form, in the order of the text."""
    found: list[_Found] = []
    for match in _NUMERIC.finditer(text):
        made = _make(_year(match.group(3)), int(match.group(2)), int(match.group(1)))
        if made:
            found.append(_Found(match.start(), made, match.end()))
    for match in _ISO.finditer(text):
        made = _make(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if made:
            found.append(_Found(match.start(), made, match.end()))
    for match in _SLASH.finditer(text):
        # Day first, as in Germany and the United Kingdom; when the first is no day of a month, it was a month.
        first, second = int(match.group(1)), int(match.group(2))
        made = _make(int(match.group(3)), second, first) or _make(int(match.group(3)), first, second)
        if made:
            found.append(_Found(match.start(), made, match.end()))
    for match in _DAY_MONTH.finditer(text):
        made = _make(int(match.group(3)), MONTHS[match.group(2).lower()], int(match.group(1)))
        if made:
            found.append(_Found(match.start(), made, match.end()))
    for match in _MONTH_DAY.finditer(text):
        made = _make(int(match.group(3)), MONTHS[match.group(1).lower()], int(match.group(2)))
        if made:
            found.append(_Found(match.start(), made, match.end()))
    found.sort(key=lambda item: item.at)
    return found


def _before(text: str, at: int, room: int = 40) -> str:
    """What stands on the same line just before position ``at``."""
    start = max(0, at - room)
    line_start = text.rfind("\n", start, at)
    return text[(line_start + 1) if line_start >= 0 else start: at]


def parse_amount(value: str) -> int | None:
    """``1.234,56``, ``1,234.56``, ``1 234,56``, ``86,40``, ``86.40`` as cents."""
    value = value.replace("\u202f", "").replace("\u00a0", "").replace(" ", "").replace("'", "")
    negative = value.startswith("-")
    value = value.lstrip("-")
    if len(value) < 4 or value[-3] not in ".,":
        return None
    whole, part = value[:-3], value[-2:]
    whole = whole.replace(".", "").replace(",", "")
    if not whole.isdigit() or not part.isdigit() or len(whole) > 12:
        return None
    cents = int(whole) * 100 + int(part)
    return -cents if negative else cents


def _amounts(text: str) -> list[tuple[int, int, str]]:
    """``(position, cents, currency)`` of every amount written with a currency."""
    found: list[tuple[int, int, str]] = []
    for match in _AMOUNT_AFTER.finditer(text):
        cents = parse_amount(match.group(1))
        if cents is not None:
            found.append((match.start(), cents, CURRENCIES.get(match.group(2).lower(), "")))
    for match in _AMOUNT_BEFORE.finditer(text):
        cents = parse_amount(match.group(2))
        if cents is not None:
            found.append((match.start(), cents, CURRENCIES.get(match.group(1).lower(), "")))
    return found


def read(text: str, today: Date) -> Facts:
    """The date, due date and amount of a text, with their reasons."""
    text = (text or "")[:MAX_TEXT].replace("\r", "\n").replace("\f", "\n")
    oldest = today - timedelta(days=365 * OLDEST_YEARS)
    latest = today + timedelta(days=31)
    date: Date | None = None
    reason = ""
    due: Date | None = None
    first: Date | None = None
    for item in dates_in(text):
        before = _before(text, item.at)
        if DUE_WORDS.search(before):
            if due is None and oldest <= item.value <= today + timedelta(days=3650):
                due = item.value
            continue
        span = PERIOD_AFTER.match(text, item.end)
        if PERIOD_WORDS.search(before) or span or PERIOD_BEFORE.search(before) or not (oldest <= item.value <= latest):
            continue
        if date is None and DATE_WORDS.search(before):
            date, reason = item.value, "labelled"
        if first is None:
            first = item.value
    if date is None and first is not None:
        date, reason = first, "first"
    amount, amount_reason, currency = _amount(text)
    return Facts(date=date, date_reason=reason, due=due, amount=amount, amount_reason=amount_reason, currency=currency)


def _amount(text: str) -> tuple[int | None, str, str]:
    labelled: list[tuple[int, int, str]] = []  # (strength, cents, currency)
    largest: tuple[int, str] | None = None
    for at, cents, currency in _amounts(text):
        before = _before(text, at, 60)
        if cents <= 0:
            continue
        if largest is None or cents > largest[0]:
            largest = (cents, currency)
        if PART_WORDS.search(before):
            continue
        if TOTAL_WORDS.search(before):
            labelled.append((2 if STRONG_TOTAL.search(before) else 1, cents, currency))
    if not labelled:
        # A total named without a currency sign ("Summe 142,80").
        for line in text.split("\n"):
            words = TOTAL_WORDS.search(line)
            if not words or PART_WORDS.search(line[: words.start()] + line[words.end():words.end() + 3]):
                continue
            for match in _AMOUNT_BARE.finditer(line, words.end()):
                cents = parse_amount(match.group(1))
                if cents and cents > 0:
                    labelled.append((2 if STRONG_TOTAL.search(line) else 1, cents, ""))
                    break
    if labelled:
        strongest = max(strength for strength, _cents, _currency in labelled)
        best = max((item for item in labelled if item[0] == strongest), key=lambda item: item[1])
        return best[1], "total", best[2]
    if largest is not None:
        return largest[0], "largest", largest[1]
    return None, "", ""


__all__ = ["Facts", "dates_in", "parse_amount", "read"]
