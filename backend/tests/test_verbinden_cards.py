"""Bauplan V20: nexpaper shows a card only for a partner it has a use with (nextime, nexmail as their host); none for
nextasks while nexpaper as its guest is not built (``verbinden_store.CONFIG.in_use``)."""

from __future__ import annotations

from .conftest import person


def test_cards_only_for_partners_in_use() -> None:
    with person("anna") as browser:
        partners = {view["partner"] for view in browser.get("/api/connect/partners").json()}
    assert partners == {"nextime", "nexmail"}
