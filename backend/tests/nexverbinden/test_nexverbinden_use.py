"""Using a connection: what it opens (only its purposes, only the areas given), tokens that refresh on their own and
end when copied, the state the card shows when the other side cannot be reached, refuses or rests. Copied unchanged
into every app."""

from __future__ import annotations

from typing import Any


def _grants(world: Any) -> tuple[str, ...]:
    """What the partner may do in the app."""
    return world.pkg.CATALOG.uses(world.partner.name, world.app.config().app_name)


def _hosted(world: Any) -> list[str]:
    return list(world.pkg.PURPOSES[world.app.config().app_name])


def test_a_connection_opens_only_what_the_catalog_names(world: Any) -> None:
    assert world.connect("partner").status_code == 200
    hosted = _hosted(world)
    if not hosted:
        # An app that grants nothing: its routes are not the module's matter; the partner reaches only hello.
        assert world.app.probe("anything") is None
        return
    for purpose in hosted:
        path = world.app.probe(purpose)
        assert path, purpose
        answer = world.partner_calls_app(path)
        status = getattr(answer, "status", None)
        if purpose in _grants(world):
            # Opened: whatever the route answers, never a refusal of the connection (a write may say 404 or 422).
            assert status is not None and status not in (401, 403), (purpose, answer)
        else:
            assert status == 403, (purpose, answer)


def test_the_partner_reaches_only_the_areas_given(world: Any) -> None:
    granted = [
        purpose for purpose in _grants(world) if world.pkg.CATALOG.purpose(world.app.config().app_name, purpose).areas
    ]
    params = world.consent_params(world.start("partner").json()["go"])
    owner = world.app.client("owner")
    info = owner.get(f"{world.pkg.PREFIX}/consent", params=params).json()
    if not granted:
        assert info["areas"] == []
        return
    assert len(info["areas"]) >= 1
    first = info["areas"][0]["id"]
    agreed = owner.post(f"{world.pkg.PREFIX}/consent", json={**params, "allow": True, "areas": [first]})
    back = world.consent_params(agreed.json()["redirect"])
    assert world.partner.client("owner").post(f"{world.pkg.PREFIX}/return", json=back).status_code == 200
    card = world.card("app")
    assert [area["id"] for area in card["areas_granted"]] == [first]
    assert [area["id"] for area in world.card("partner")["areas_used"]] == [first]


def test_the_app_calls_the_partner_with_the_connection(world: Any) -> None:
    assert world.connect("app").status_code == 200
    for purpose in world.pkg.CATALOG.uses(world.app.config().app_name, world.partner.name):
        # The partner's own check: what the app may there.
        answer = world.partner.client(None).get(
            f"/api/v1/purpose/{purpose}", headers={"Authorization": f"Bearer {_app_access(world)}"}
        )
        assert answer.status_code == 200, (purpose, answer.text)
    not_given = set(world.pkg.PURPOSES[world.partner.name]) - set(
        world.pkg.CATALOG.uses(world.app.config().app_name, world.partner.name)
    )
    for purpose in not_given:
        answer = world.partner.client(None).get(
            f"/api/v1/purpose/{purpose}", headers={"Authorization": f"Bearer {_app_access(world)}"}
        )
        assert answer.status_code == 403, purpose


def _app_access(world: Any) -> str:
    """The access token the app holds of the partner, taken from what went between them."""
    found = [token for token in world.tokens if token.startswith(world.partner.config.access_prefix)]
    assert found, "the app holds no token of the partner"
    return found[-1]


def test_tokens_refresh_on_their_own_and_a_copied_one_ends_the_connection(world: Any) -> None:
    assert world.connect("partner").status_code == 200
    spent = [token for token in world.tokens if token.startswith(world.app.config().refresh_prefix)]
    assert len(spent) == 1
    world.expire_partner_access()
    assert world.partner_calls_app(f"{world.pkg.PREFIX}/hello").status == 200
    world.expire_partner_access()
    assert world.partner_calls_app(f"{world.pkg.PREFIX}/hello").status == 200
    # A refresh token spent before, brought again: somebody holds a copy, the app ends the connection.
    for token in spent:
        found = world.program().post(
            f"{world.pkg.PREFIX}/token",
            data={"grant_type": "refresh_token", "refresh_token": token, "client_id": world.partner.base},
        )
        assert found.status_code == 400 and found.json()["error"] == "invalid_grant"
    assert world.card("app")["state"] == "none"
    refused = world.partner_calls_app(f"{world.pkg.PREFIX}/hello")
    assert getattr(refused, "code", None) == "refused" and world.card("partner")["state"] == "refused"


def test_a_partner_out_of_reach_keeps_the_last_state_and_says_since_when(world: Any) -> None:
    assert world.connect("app").status_code == 200
    owner = world.app.client("owner")
    assert owner.post(f"{world.pkg.PREFIX}/partners/{world.partner.name}/check").json()["state"] == "connected"
    ok_at = world.card("app")["ok_at"]
    world.down.add(world.host(world.partner.base))
    first = owner.post(f"{world.pkg.PREFIX}/partners/{world.partner.name}/check").json()
    assert first["state"] == "unreachable" and first["stale_since"] and first["ok_at"] == ok_at
    world.pkg.connect.BRAKE.forget()
    second = owner.post(f"{world.pkg.PREFIX}/partners/{world.partner.name}/check").json()
    assert second["stale_since"] == first["stale_since"]
    world.down.clear()
    world.pkg.connect.BRAKE.forget()
    back = owner.post(f"{world.pkg.PREFIX}/partners/{world.partner.name}/check").json()
    assert back["state"] == "connected" and back["stale_since"] is None


def test_an_account_blocked_on_one_side_lets_the_connection_rest(world: Any) -> None:
    assert world.connect("partner").status_code == 200
    world.app.block("owner")
    rested = world.partner_calls_app(f"{world.pkg.PREFIX}/hello")
    assert getattr(rested, "code", None) == "resting" and world.card("partner")["state"] == "resting"
    world.app.block("owner", False)
    assert world.partner_calls_app(f"{world.pkg.PREFIX}/hello").status == 200
    assert world.card("partner")["state"] == "connected"
    # The partner's side blocked: the app's card says it rests there.
    world.partner.block("owner")
    world.expire_partner_issued()
    world.pkg.connect.BRAKE.forget()
    assert (
        world.app.client("owner").post(f"{world.pkg.PREFIX}/partners/{world.partner.name}/check").json()["state"]
        == "resting"
    )


def test_a_connection_unused_for_half_a_year_rests(world: Any) -> None:
    assert world.connect("app").status_code == 200
    world.expire_partner_issued(idle_days=world.app.config().idle_days + 1)
    found = world.app.client("owner").post(f"{world.pkg.PREFIX}/partners/{world.partner.name}/check").json()
    assert found["state"] == "resting" and found["problem"] == "connection_resting"


def test_starting_in_the_app_with_the_data_gives_only_the_areas_chosen_in_the_card(world: Any) -> None:
    """Decision V16 (F1 = a), V41 (since 0.1.7): where a purpose the partner uses here has areas, reading or writing,
    the card asks for them before the click; the partner reaches only the areas chosen, a write into another is
    refused."""
    app_name = world.app.config().app_name
    with_areas = [
        purpose
        for purpose in world.pkg.CATALOG.uses(world.partner.name, app_name)
        if world.pkg.CATALOG.purpose(app_name, purpose).areas
    ]
    reading = [purpose for purpose in with_areas if world.pkg.CATALOG.purpose(app_name, purpose).level == "read"]
    writing = [purpose for purpose in with_areas if purpose not in reading]
    card = world.card("app")
    if not with_areas:
        assert card["areas_choice"] == []
        return
    choice = card["areas_choice"]
    assert len(choice) >= 2, "APP: owner needs two areas for this test"
    first, second = str(choice[0]["id"]), str(choice[1]["id"])
    wrong = world.start("app", areas=["999999"])
    assert wrong.status_code == 422 and wrong.json()["detail"]["code"] == "areas_invalid"
    world.pkg.connect.BRAKE.forget()
    started = world.start("app", areas=[choice[0]["id"]])
    assert started.status_code == 200, started.text
    params = world.consent_params(started.json()["go"])
    agreed = world.partner.client("owner").post(f"{world.pkg.PREFIX}/consent", json={**params, "allow": True})
    back = world.consent_params(agreed.json()["redirect"])
    assert world.app.client("owner").post(f"{world.pkg.PREFIX}/return", json=back).status_code == 200
    # In the app (it keeps what it gave) and at the partner (it knows what it reaches): only the area chosen.
    assert [str(area["id"]) for area in world.card("app")["areas_granted"]] == [first]
    assert [str(area["id"]) for area in world.card("partner")["areas_used"]] == [first]
    for purpose in reading:
        answer = world.partner_calls_app(world.app.probe(purpose))
        assert getattr(answer, "status", None) == 200, (purpose, answer)
        seen = world.app.areas_seen(purpose, answer.data)
        assert first in seen and second not in seen, (purpose, seen)
    # V41: "nie mehr als nötig" holds for writing too: into the area chosen it goes, into the other one it does not.
    for purpose in writing:
        given = world.partner_calls_app(world.app.write_into(purpose, choice[0]["id"]))
        assert 200 <= getattr(given, "status", 0) < 300, (purpose, given)
        refused = world.partner_calls_app(world.app.write_into(purpose, choice[1]["id"]))
        assert getattr(refused, "status", None) in (403, 404), (purpose, refused)


def test_the_app_uses_a_connection_with_its_own_requests(world: Any) -> None:
    """Decision V18: an app asks its partner with its own ``request()`` and the connection's address and token
    (``access``); a token run out is refreshed, an old one no longer opens anything, and the card follows."""
    from datetime import UTC, datetime, timedelta

    assert world.connect("app").status_code == 200
    store, config, owner = world.app.store, world.app.config(), world.app.account_id("owner")
    first = world.pkg.access(store, config, owner, world.partner.name, datetime.now(UTC))
    assert first.base == world.partner.base and first.expires_at > datetime.now(UTC)
    asked = world.partner.client(None).get(
        f"{world.pkg.PREFIX}/hello", headers={"Authorization": f"Bearer {first.token}"}
    )
    assert asked.status_code == 200 and asked.json()["app"] == world.partner.name
    # An hour later: the module refreshes on its own, the old token is done.
    later = datetime.now(UTC) + timedelta(hours=2)
    second = world.pkg.access(store, config, owner, world.partner.name, later)
    assert second.token != first.token
    for token, status in ((first.token, 401), (second.token, 200)):
        found = world.partner.client(None).get(
            f"{world.pkg.PREFIX}/hello", headers={"Authorization": f"Bearer {token}"}
        )
        assert found.status_code == status
    # What the app's own request met goes onto the card.
    world.pkg.reached(store, owner, world.partner.name, datetime.now(UTC), problem="unreachable")
    assert world.card("app")["state"] == "unreachable" and world.card("app")["stale_since"]
    world.pkg.reached(store, owner, world.partner.name, datetime.now(UTC))
    assert world.card("app")["state"] == "connected"
    world.pkg.reached(store, owner, world.partner.name, datetime.now(UTC), problem="account_resting")
    assert world.card("app")["state"] == "resting"
    # Ended at the partner: a forced refresh is turned down and the card says so.
    world.partner.client("owner").delete(f"{world.pkg.PREFIX}/partners/{config.app_name}")
    try:
        world.pkg.access(store, config, owner, world.partner.name, later, force=True)
    except world.pkg.Refused as refusal:
        assert refusal.code in ("not_connected", "refused")
    else:
        raise AssertionError("a connection ended at the partner gave a token")


def test_only_partners_in_use_get_a_card_and_a_start(world: Any) -> None:
    """Decision V20: a partner the app has no use for yet (``AppConfig.in_use``) shows no card and cannot be started."""
    config = world.app.config()
    cards = [card["partner"] for card in world.app.client("owner").get(f"{world.pkg.PREFIX}/partners").json()]
    assert cards == config.usable
    assert world.partner.name in config.usable, "APP: the partner of the test must be one the app uses"
    for other in set(config.partners) - set(config.usable):
        found = world.app.client("owner").post(
            f"{world.pkg.PREFIX}/partners/{other}/start", json={"address": world.partner.base}
        )
        assert found.status_code == 404, other


def test_people_for_an_entry_or_an_event_show_only_id_name_and_mail_addresses(world: Any) -> None:
    """V29 (since 0.1.3): the narrow purpose ``people.read`` (nexfolk for nextime and nexdiary) gives a person's id,
    name and mail addresses, never telephone, address or notes; ``contacts.read`` stays for nexmail."""
    app_name = world.app.config().app_name
    catalog = world.pkg.CATALOG
    for reader in ("nextime", "nexdiary"):
        uses = catalog.uses(reader, "nexfolk")
        assert "people.read" in uses and "contacts.read" not in uses, reader
    if "people.read" not in world.pkg.PURPOSES[app_name]:
        return
    assert "people.read" in catalog.uses(world.partner.name, app_name), "APP: the partner of the test reads people"
    assert world.connect("partner").status_code == 200
    answer = world.partner_calls_app(world.app.probe("people.read"))
    assert getattr(answer, "status", None) == 200, answer
    persons = world.app.people(answer.data)
    assert persons, "APP: the owner has at least one person"
    for person in persons:
        assert set(person) <= {"id", "name", "emails"} and {"id", "name"} <= set(person), person
