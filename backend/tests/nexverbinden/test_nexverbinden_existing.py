"""Older connections and keys notice nothing (Bauplan Einstellungen, "Bestehendes läuft weiter"): the module comes
beside the app's own tables, shows a connection typed in by hand as it is, and an older API key works on, until after
"Neu verbinden" it ends itself. Since 0.2.0 (B9, V56) a connection by click with the same partner takes the place of
the older one, and "Trennen" or a no on the consent page end it too. Copied unchanged into every app."""

from __future__ import annotations

from typing import Any


def _legacy_partners(world: Any, role: str = "owner") -> list[str]:
    return [row.partner for row in world.app.store.legacy(world.app.account_id(role))]


def test_the_apps_own_tables_stay_as_the_older_version_left_them(older: Any) -> None:
    before = older.app.own_tables()
    older.app.client("owner").get(f"{older.pkg.PREFIX}/partners")
    started = older.start("app")
    assert started.status_code == 200, started.text
    older.partner.client("owner").get(f"{older.pkg.PREFIX}/consent", params=older.consent_params(started.json()["go"]))
    assert older.app.own_tables() == before
    if not older.app.older_link:
        assert older.connect("app").status_code == 200
        assert older.app.own_tables() == before


def test_an_older_api_key_works_on(older: Any) -> None:
    assert older.app.older_key and older.app.older_key_path
    found = older.program().get(older.app.older_key_path, headers={"Authorization": f"Bearer {older.app.older_key}"})
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
    unknown = older.program().post(f"{older.pkg.PREFIX}/retire", headers={"Authorization": "Bearer nothing"})
    assert unknown.status_code == 200 and unknown.json() == {"retired": False}
    # The partner had typed in the app's older key; after its new connection that key ends itself in the app.
    older.partner.old_key_for[older.app.config().app_name] = older.app.older_key
    assert older.connect("partner").status_code == 200
    found = older.program().get(older.app.older_key_path, headers={"Authorization": f"Bearer {older.app.older_key}"})
    assert found.status_code == 401, found.text


# --- B9 (0.2.0, V56): the connection by click takes the place of the older one ----------------------------------------


def test_the_store_forgets_an_older_connection(world: Any) -> None:
    """B9 (V56): every app's ``Store`` has ``forget_legacy(account_id, partner)``, also one that never had a connection
    typed in by hand (then it finds nothing to drop)."""
    forget = getattr(world.app.store, "forget_legacy", None)
    assert callable(forget), "APP: Store.forget_legacy(account_id, partner), see NACHZIEHEN in verbinden 0.2.0"
    forget(world.app.account_id("owner"), world.partner.name)
    world.app.store.commit()
    assert world.card("app")["state"] == "none"


def test_a_connection_by_click_replaces_the_older_one_and_trennen_leaves_nothing(older: Any) -> None:
    if not older.app.older_link:
        return
    assert older.partner.name in _legacy_partners(older)
    assert older.card("app")["legacy"]["can_end"] is True
    assert older.connect("app").status_code == 200
    card = older.card("app")
    assert card["state"] == "connected" and card["legacy"] is None
    assert older.partner.name not in _legacy_partners(older)
    gone = older.app.client("owner").delete(f"{older.pkg.PREFIX}/partners/{older.partner.name}")
    assert gone.status_code == 200
    card = older.card("app")
    assert card["state"] == "none" and card["legacy"] is None


def test_made_from_the_partner_it_replaces_the_older_one_too(older: Any) -> None:
    if not older.app.older_link:
        return
    assert older.connect("partner").status_code == 200
    assert older.partner.name not in _legacy_partners(older)
    assert older.card("app")["legacy"] is None


def test_trennen_ends_an_older_connection_alone(older: Any) -> None:
    if not older.app.older_link:
        return
    gone = older.app.client("owner").delete(f"{older.pkg.PREFIX}/partners/{older.partner.name}")
    assert gone.status_code == 200 and gone.json()["state"] == "none" and gone.json()["legacy"] is None
    assert older.partner.name not in _legacy_partners(older)
    again = older.app.client("owner").delete(f"{older.pkg.PREFIX}/partners/{older.partner.name}")
    assert again.status_code == 404


def test_a_no_on_the_consent_page_leaves_nothing_connected(older: Any) -> None:
    """B9 (V56): a no ends the older connection with the partner as well; nothing shows "Verbunden" afterwards."""
    if not older.app.older_link:
        return
    returned = older.connect("app", allow=False)
    assert returned.status_code == 409 and returned.json()["detail"]["code"] == "declined"
    card = older.card("app")
    assert card["state"] == "none" and card["legacy"] is None
