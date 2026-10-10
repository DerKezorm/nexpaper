"""Texts read from a document or an answer come from outside: no pattern may take longer on a long run of one character
than on any other text. Each case is a size at which a pattern with nested or consecutive open-ended parts needs
a fraction of a second to seconds; the patterns now in use need a few milliseconds. The reading of the first pages
runs under the write lock, so a slow pattern keeps every writer waiting."""

from __future__ import annotations

import time
from datetime import date

import pytest

from app.services import ai_proposals, sorting, textfacts

LIMIT = 0.25


def timed(call, *args):
    """The call, and a check that it took no longer than ``LIMIT`` even when it ends in an exception."""
    started = time.monotonic()
    try:
        return call(*args)
    finally:
        assert time.monotonic() - started < LIMIT


def customers(signs: list[sorting.Sign]) -> list[str]:
    return [sign.value for sign in signs if sign.kind == "customer"]


@pytest.mark.parametrize("space", [" ", "\n", "\t"])
def test_a_long_run_of_blanks_after_a_keyword_costs_nothing(space: str) -> None:
    for word in ("Kundennummer", "Customer number", "Kd.-Nr."):
        assert customers(timed(sorting.signs_of, word + space * 6_000 + "!")) == []
    assert customers(sorting.signs_of("Kundennummer:  K-4711-A\nSumme")) == ["K-4711-A"]
    assert customers(sorting.signs_of("Kundennummer\nK-4711-A")) == ["K-4711-A"]


@pytest.mark.parametrize("piece", ["111 ", "111.", "111\u00a0", "1,111 "])
def test_a_long_run_of_number_groups_costs_nothing(piece: str) -> None:
    today = date(2026, 10, 10)
    text = piece * 3_000
    for body in (text, "Summe " + text, text + "EUR", "EUR " + text):
        timed(textfacts.read, body, today)
    assert textfacts.read("Gesamtbetrag 1.234.567,89 EUR", today).amount == 123456789
    assert textfacts.read("Summe 1 234,56 EUR", today).amount == 123456


def test_a_long_run_of_spaces_in_a_fenced_answer_costs_nothing() -> None:
    kinds = ["Rechnung"]
    today = date(2026, 10, 10)
    for raw in ("```json" + " " * 1_500 + "x", "```json" + " \n" * 600, "```" + " " * 1_500 + "```x"):
        with pytest.raises(ValueError):
            timed(ai_proposals.check, raw, kinds, today)
    assert ai_proposals.check('```json\n{"title": "Wartung"}\n```', kinds, today) == {"title": "Wartung"}
    assert ai_proposals.check('```\n{"title": "Wartung"}```', kinds, today) == {"title": "Wartung"}
    assert ai_proposals.check('  {"title": "Wartung"}  ', kinds, today) == {"title": "Wartung"}
