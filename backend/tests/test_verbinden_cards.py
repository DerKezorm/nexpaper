"""Bauplan V20: nexpaper shows a card only for a partner it has a use with (nextime, nexmail as their host; nextasks as
its guest since "Aufgabe in nextasks", ``test_nextasks_guest.py``; nexfolk as its host since verbinden 0.1.13,
``documents.about``), from ``verbinden_store.CONFIG.in_use``."""

from __future__ import annotations

from .conftest import person


def test_cards_only_for_partners_in_use() -> None:
    with person("anna") as browser:
        partners = {view["partner"] for view in browser.get("/api/connect/partners").json()}
    assert partners == {"nextime", "nexmail", "nextasks", "nexfolk"}



def test_the_consent_page_names_the_account_as_its_profile_does() -> None:
    """verbinden 0.1.8 (B1): ``Store.account_card`` gives the display name, the name to sign in with and the own picture
    at the address the app loads it from (``avatarUrl``: ``/api/v1/avatars/<id>?v=<stamp>``); nexpaper has no colour."""
    from urllib.parse import quote

    from app.db import SessionLocal
    from app.models import Account
    from app.services.verbinden_store import VerbindenStore
    from app.vendor.nexverbinden import connect

    from .test_avatars import photo

    with person("anna") as browser:
        mine = browser.get("/api/v1/auth/me").json()
        with SessionLocal() as db:
            plain = connect.account_card(VerbindenStore(db), mine["id"])
        assert plain == {"name": "", "username": "anna", "picture": None, "color": None}
        stamp = browser.put("/api/v1/auth/avatar", content=photo()).json()["avatar"]
        with SessionLocal() as db:
            row = db.get(Account, mine["id"])
            assert row is not None
            row.display_name = "Anna Example"
            db.commit()
            card = connect.account_card(VerbindenStore(db), mine["id"])
        assert card["name"] == "Anna Example" and card["username"] == "anna" and card["color"] is None
        assert card["picture"] == f"/api/v1/avatars/{mine['id']}?v={quote(stamp, safe='')}"
        shown = browser.get(card["picture"])
        assert shown.status_code == 200 and shown.headers["content-type"] == "image/webp"
    with SessionLocal() as db:
        assert VerbindenStore(db).account_card(10_000) is None
