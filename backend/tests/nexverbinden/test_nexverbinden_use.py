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
        if purpose in _grants(world):
            assert getattr(answer, "status", None) == 200, (purpose, answer)
        else:
            assert getattr(answer, "status", None) == 403 and answer.code == "purpose_missing", (purpose, answer)


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
        found = world.app.client(None).post(
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
    """Decision V16 (F1 = a): the partner reads areas of the app; starting in the app, the card asks for them first."""
    app_name = world.app.config().app_name
    reading = [
        purpose
        for purpose in world.pkg.CATALOG.uses(world.partner.name, app_name)
        if world.pkg.CATALOG.purpose(app_name, purpose).areas
    ]
    card = world.card("app")
    if not reading:
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
