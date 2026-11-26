"""Ending a connection: from either side, both directions at once (V3); the other side hears it, and while it cannot
be reached the revocation waits. Copied unchanged into every app."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def test_ending_it_in_the_app_ends_both_directions_at_the_partner(world: Any) -> None:
    assert world.connect("partner").status_code == 200
    gone = world.app.client("owner").delete(f"{world.pkg.PREFIX}/partners/{world.partner.name}")
    assert gone.status_code == 200 and gone.json()["state"] == "none"
    assert world.partner_connection() is None
    assert world.card("partner")["state"] == "none"


def test_ending_it_at_the_partner_reaches_the_app(world: Any) -> None:
    assert world.connect("app").status_code == 200
    gone = world.partner.client("owner").delete(f"{world.pkg.PREFIX}/partners/{world.app.config().app_name}")
    assert gone.status_code == 200
    assert world.card("app")["state"] == "none"
    again = world.app.client("owner").delete(f"{world.pkg.PREFIX}/partners/{world.partner.name}")
    assert again.status_code == 404


def test_a_partner_out_of_reach_hears_the_end_later(world: Any) -> None:
    assert world.connect("partner").status_code == 200
    world.down.add(world.host(world.partner.base))
    assert world.app.client("owner").delete(f"{world.pkg.PREFIX}/partners/{world.partner.name}").status_code == 200
    assert world.card("app")["state"] == "none"
    assert world.partner_connection() is not None
    store = _app_store(world)
    assert world.pkg.retry_waiting(store, world.app.config(), datetime.now(UTC)) == 0
    world.down.clear()
    assert world.pkg.retry_waiting(store, world.app.config(), datetime.now(UTC)) == 1
    assert world.partner_connection() is None


def _app_store(world: Any) -> Any:
    """The app's ``Store`` (an app passes it to ``retry_waiting`` from its clock)."""
    assert world.app.store is not None, "APP: the adapter names the app's Store as .store"
    return world.app.store


def test_connecting_again_replaces_the_connection_on_both_sides(world: Any) -> None:
    assert world.connect("app").status_code == 200
    first = world.partner_connection().id
    assert world.connect("partner").status_code == 200
    assert world.partner_connection().id != first
    assert world.card("app")["state"] == "connected" and world.card("partner")["state"] == "connected"
    assert world.partner_calls_app(f"{world.pkg.PREFIX}/hello").status == 200
