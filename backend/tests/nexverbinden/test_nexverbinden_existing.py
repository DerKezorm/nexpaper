"""Older connections and keys notice nothing (Bauplan Einstellungen, "Bestehendes läuft weiter"): the module comes
beside the app's own tables, shows a connection typed in by hand as it is, and an older API key works on, until after
"Neu verbinden" it ends itself. Copied unchanged into every app."""

from __future__ import annotations

from typing import Any


def test_the_apps_own_tables_stay_as_the_older_version_left_them(older: Any) -> None:
    before = older.app.own_tables()
    assert older.connect("app").status_code == 200
    older.app.client("owner").get(f"{older.pkg.PREFIX}/partners")
    assert older.app.own_tables() == before


def test_an_older_api_key_works_on(older: Any) -> None:
    assert older.app.older_key and older.app.older_key_path
    found = older.app.client(None).get(
        older.app.older_key_path, headers={"Authorization": f"Bearer {older.app.older_key}"}
    )
    assert found.status_code == 200, found.text


def test_a_connection_typed_in_by_hand_is_shown_with_its_end(older: Any) -> None:
    card = older.card("app")
    if not older.app.older_link:
        assert card["legacy"] is None
        return
    assert card["state"] in ("legacy", "expiring") and card["legacy"]["shown"]
    # Decision V1 (4a): a week before its key ends, the card says so.
    if card["legacy"]["expires_at"]:
        assert card["state"] == "expiring"
    # Connecting anew takes its place.
    assert older.connect("app").status_code == 200
    assert older.card("app")["state"] == "connected"


def test_after_connecting_anew_an_older_key_ends_itself(older: Any) -> None:
    unknown = older.app.client(None).post(f"{older.pkg.PREFIX}/retire", headers={"Authorization": "Bearer nothing"})
    assert unknown.status_code == 200 and unknown.json() == {"retired": False}
    # The partner had typed in the app's older key; after its new connection that key ends itself in the app.
    older.partner.old_key_for[older.app.config().app_name] = older.app.older_key
    assert older.connect("partner").status_code == 200
    found = older.app.client(None).get(
        older.app.older_key_path, headers={"Authorization": f"Bearer {older.app.older_key}"}
    )
    assert found.status_code == 401, found.text
