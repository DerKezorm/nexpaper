"""Connecting: from either side with one consent, the checks on the way, both directions in one connection (V3).
Copied unchanged into every app."""

from __future__ import annotations

from typing import Any


def test_the_description_names_the_app_and_says_whether_it_connects(world: Any) -> None:
    found = world.program().get(world.pkg.WELL_KNOWN)
    assert found.status_code == 200
    data = found.json()
    assert data["app"] == world.app.config().app_name and data["protocol"] == world.pkg.PROTOCOL
    assert data["connect"] is True and data["consent"] == world.pkg.CONSENT_PAGE
    switched = world.app.client("operator").put(f"{world.pkg.PREFIX}/admin", json={"connections": False})
    assert switched.status_code == 200 and switched.json()["connections"] is False
    assert world.program().get(world.pkg.WELL_KNOWN).json()["connect"] is False


def test_the_partner_of_the_test_is_one_of_the_catalog(world: Any) -> None:
    assert world.app.partner in world.app.config().partners
    cards = world.app.client("owner").get(f"{world.pkg.PREFIX}/partners").json()
    assert [card["partner"] for card in cards] == world.app.config().partners
    assert all(card["state"] == "none" for card in cards)


def test_connecting_from_the_app_gives_both_sides_one_connection(world: Any) -> None:
    done = world.connect("app")
    assert done.status_code == 200, done.text
    view = done.json()
    pair = world.pkg.CATALOG.pair(world.app.config().app_name, world.partner.name)
    assert view["state"] == "connected" and view["account"] == "kim"
    assert view["uses"] == list(pair.uses[world.app.config().app_name])
    assert view["grants"] == list(pair.uses[world.partner.name])
    theirs = world.card("partner")
    assert theirs["state"] == "connected" and theirs["uses"] == view["grants"] and theirs["grants"] == view["uses"]
    # One connection, the same on both sides.
    assert world.partner_connection() is not None and theirs["account"] == world.app.names["owner"]


def test_connecting_from_the_partner_works_the_same(world: Any) -> None:
    done = world.connect("partner")
    assert done.status_code == 200, done.text
    assert world.card("app")["state"] == "connected" and world.card("partner")["state"] == "connected"
    # Both directions are open at once, without a second click.
    assert world.partner_calls_app(f"{world.pkg.PREFIX}/hello").status == 200


def test_the_consent_page_needs_a_session_and_shows_both_directions(world: Any) -> None:
    started = world.start("partner")
    params = world.consent_params(started.json()["go"])
    assert world.app.client(None).get(f"{world.pkg.PREFIX}/consent", params=params).status_code in (401, 403)
    info = world.app.client("owner").get(f"{world.pkg.PREFIX}/consent", params=params).json()
    assert info["partner"] == world.partner.name and info["app"] == world.app.config().app_name
    assert info["account"] == world.app.names["owner"] and info["partner_host"] == world.host(world.partner.base)
    assert [entry["id"] for entry in info["partner_may"]] == list(
        world.pkg.CATALOG.uses(world.partner.name, world.app.config().app_name)
    )
    assert [entry["id"] for entry in info["app_may"]] == list(
        world.pkg.CATALOG.uses(world.app.config().app_name, world.partner.name)
    )


def test_a_no_on_the_consent_page_goes_back_with_access_denied(world: Any) -> None:
    started = world.start("app")
    params = world.consent_params(started.json()["go"])
    answer = world.partner.client("owner").post(f"{world.pkg.PREFIX}/consent", json={**params, "allow": False})
    back = world.consent_params(answer.json()["redirect"])
    assert back["error"] == "access_denied" and back["state"] == params["state"] and "code" not in back
    assert answer.json()["redirect"].startswith(world.app.base + world.pkg.RETURN_PAGE)
    assert world.app.client("owner").post(f"{world.pkg.PREFIX}/return", json=back).status_code == 409
    assert world.card("app")["state"] == "none"


def test_a_return_address_of_another_app_is_refused(world: Any) -> None:
    params = world.consent_params(world.start("partner").json()["go"])
    for wrong in (
        "https://evil.example.com/connect/return",
        world.partner.base + "/elsewhere",
        world.partner.base + world.pkg.RETURN_PAGE + "#x",
    ):
        found = world.app.client("owner").get(f"{world.pkg.PREFIX}/consent", params={**params, "redirect_uri": wrong})
        assert found.status_code == 400 and found.json()["detail"]["code"] == "redirect_invalid", wrong


def test_the_consent_needs_pkce_with_s256(world: Any) -> None:
    params = world.consent_params(world.start("partner").json()["go"])
    for changed in ({"code_challenge_method": "plain"}, {"code_challenge": "short"}):
        found = world.app.client("owner").get(f"{world.pkg.PREFIX}/consent", params={**params, **changed})
        assert found.status_code == 400 and found.json()["detail"]["code"] == "pkce_required"


def test_an_asking_app_with_a_host_of_odd_letters_is_refused(world: Any) -> None:
    """mcp 1.1.1 (M-8): the address of the app that asks names a plain host."""
    params = world.consent_params(world.start("partner").json()["go"])
    for host in ("https://*.example.com", "https://\u0430pple.example.com"):
        odd = {"client_id": host, "redirect_uri": host + world.pkg.RETURN_PAGE}
        found = world.app.client("owner").get(f"{world.pkg.PREFIX}/consent", params={**params, **odd})
        assert found.status_code == 400 and found.json()["detail"]["code"] in ("client_invalid", "redirect_invalid")


def test_only_an_app_of_the_catalog_may_ask(world: Any) -> None:
    params = world.consent_params(world.start("partner").json()["go"])
    # The address answers, but as an app this one does not connect with (the app itself).
    itself = {"client_id": world.app.base, "redirect_uri": world.app.base + world.pkg.RETURN_PAGE}
    found = world.app.client("owner").get(f"{world.pkg.PREFIX}/consent", params={**params, **itself})
    assert found.status_code == 400 and found.json()["detail"]["code"] == "client_invalid"


def test_starting_checks_the_address_and_the_app_there(world: Any) -> None:
    owner = world.app.client("owner")
    url = f"{world.pkg.PREFIX}/partners/{world.partner.name}/start"
    for address, code in (
        ("ftp://x.example.com", "address_invalid"),
        ("https://user:pw@x.example.com", "address_invalid"),
        ("https://x.example.com:22", "address_port"),
        ("http://localhost:8000", "address_refused"),
        # mcp 1.1.1 (M-8): no wildcard, no letter of another script that looks Latin.
        ("https://*.example.com", "address_invalid"),
        ("https://\u0430pple.example.com", "address_invalid"),
    ):
        found = owner.post(url, json={"address": address})
        assert found.status_code == 422 and found.json()["detail"]["code"] == code, address
    # Another app answers there (the app itself).
    found = owner.post(url, json={"address": world.app.base})
    assert found.status_code == 409 and found.json()["detail"]["code"] == "wrong_app"
    # Nothing answers there.
    world.down.add(world.host(world.partner.base))
    found = owner.post(url, json={"address": world.partner.base})
    assert found.status_code == 502 and found.json()["detail"]["code"] == "unreachable"
    assert (
        owner.post(f"{world.pkg.PREFIX}/partners/nobody/start", json={"address": world.partner.base}).status_code == 404
    )


def test_an_app_in_the_own_network_is_asked_only_with_the_operators_switch(world: Any) -> None:
    owner = world.app.client("owner")
    url = f"{world.pkg.PREFIX}/partners/{world.partner.name}/start"
    found = owner.post(url, json={"address": "https://home.example.com"})
    # The page says only "cannot be reached": where a name points stays in the log.
    assert found.status_code == 502 and found.json()["detail"]["code"] == "unreachable"


def test_a_return_is_good_once_for_its_own_account_and_its_partner(world: Any) -> None:
    started = world.start("app")
    params = world.consent_params(started.json()["go"])
    agreed = world.partner.client("owner").post(f"{world.pkg.PREFIX}/consent", json={**params, "allow": True})
    back = world.consent_params(agreed.json()["redirect"])
    assert back["iss"] == world.partner.base
    # Another account cannot finish it, and it is gone afterwards.
    other = world.app.client("other").post(f"{world.pkg.PREFIX}/return", json=back)
    assert other.status_code == 400 and other.json()["detail"]["code"] == "return_invalid"
    assert world.app.client("owner").post(f"{world.pkg.PREFIX}/return", json=back).status_code == 400
    # A wrong state, a wrong issuer.
    params = world.consent_params(world.start("app").json()["go"])
    agreed = world.partner.client("owner").post(f"{world.pkg.PREFIX}/consent", json={**params, "allow": True})
    back = world.consent_params(agreed.json()["redirect"])
    for changed in ({"state": "x" * 43}, {"iss": "https://evil.example.com"}):
        found = world.app.client("owner").post(f"{world.pkg.PREFIX}/return", json={**back, **changed})
        assert found.status_code == 400 and found.json()["detail"]["code"] == "return_invalid"


def test_a_code_is_good_once_and_brought_again_ends_the_connection(world: Any) -> None:
    started = world.start("app")
    params = world.consent_params(started.json()["go"])
    agreed = world.partner.client("owner").post(f"{world.pkg.PREFIX}/consent", json={**params, "allow": True})
    back = world.consent_params(agreed.json()["redirect"])
    code = back["code"]
    assert world.app.client("owner").post(f"{world.pkg.PREFIX}/return", json=back).status_code == 200
    assert world.partner_connection() is not None
    again = world.partner.client(None).post(
        f"{world.pkg.PREFIX}/token",
        data={"grant_type": "authorization_code", "code": code, "client_id": world.app.base},
    )
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"
    assert world.partner_connection() is None


def test_the_areas_given_are_the_accounts_own(world: Any) -> None:
    params = world.consent_params(world.start("partner").json()["go"])
    owner = world.app.client("owner")
    found = owner.post(f"{world.pkg.PREFIX}/consent", json={**params, "allow": True, "areas": ["999999"]})
    assert found.status_code == 422 and found.json()["detail"]["code"] == "areas_invalid"
    found = owner.post(f"{world.pkg.PREFIX}/consent", json={**params, "allow": True, "areas": []})
    assert found.status_code == 422


def test_nothing_between_the_apps_is_for_web_pages(world: Any) -> None:
    client = world.program()
    for path in ("/token", "/revoke", "/retire"):
        found = client.post(f"{world.pkg.PREFIX}{path}", headers={"Origin": "https://evil.example.com"}, data={})
        assert found.status_code == 403 and found.json()["detail"]["code"] == "origin_refused", path
    found = client.get(f"{world.pkg.PREFIX}/hello", headers={"Origin": "https://evil.example.com"})
    assert found.status_code == 403


def test_the_operators_switch_closes_the_way_and_keeps_the_connections(world: Any) -> None:
    assert world.connect("partner").status_code == 200
    operator = world.app.client("operator")
    assert world.app.client("owner").put(f"{world.pkg.PREFIX}/admin", json={"connections": False}).status_code in (
        401,
        403,
    )
    assert operator.put(f"{world.pkg.PREFIX}/admin", json={"connections": False}).status_code == 200
    refused = world.partner_calls_app(f"{world.pkg.PREFIX}/hello")
    assert getattr(refused, "code", None) == "partner_off" and world.card("partner")["state"] == "off"
    started = world.start("app")
    assert started.status_code == 403 and started.json()["detail"]["code"] == "connections_off"
    assert operator.put(f"{world.pkg.PREFIX}/admin", json={"connections": True}).status_code == 200
    assert world.partner_calls_app(f"{world.pkg.PREFIX}/hello").status == 200
    assert world.card("partner")["state"] == "connected"


def test_the_operator_names_the_addresses_of_the_other_apps(world: Any) -> None:
    operator = world.app.client("operator")
    found = operator.put(
        f"{world.pkg.PREFIX}/admin", json={"addresses": {world.partner.name: world.partner.base + "/"}}
    )
    assert found.status_code == 200 and found.json()["addresses"][world.partner.name] == world.partner.base
    card = world.card("app")
    assert card["address"] == world.partner.base and card["address_from_operator"] is True
    found = operator.put(f"{world.pkg.PREFIX}/admin", json={"addresses": {world.partner.name: "ftp://x"}})
    assert found.status_code == 422
    assert (
        operator.put(f"{world.pkg.PREFIX}/admin", json={"addresses": {"nobody": "https://x.example.com"}}).status_code
        == 404
    )


def test_a_code_needs_the_verifier_the_return_address_and_the_asking_app(world: Any) -> None:
    params = world.consent_params(world.start("partner").json()["go"])
    agreed = world.app.client("owner").post(f"{world.pkg.PREFIX}/consent", json={**params, "allow": True})
    code = world.consent_params(agreed.json()["redirect"])["code"]
    right = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": world.partner.base,
        "redirect_uri": world.partner.base + world.pkg.RETURN_PAGE,
        "code_verifier": "v" * 43,
        "reverse_access": "x" * 30,
        "reverse_refresh": "y" * 30,
        "reverse_expires_in": "3600",
    }
    found = world.program().post(f"{world.pkg.PREFIX}/token", data=right)
    assert found.status_code == 400 and found.json()["error"] == "invalid_grant"
    assert world.card("app")["state"] == "none"
