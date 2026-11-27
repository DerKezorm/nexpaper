"""The operator's card "Andere nex-Apps" since 0.2.0: one change for the whole card (B18, V60), every address asked
what answers there and kept with what was found (B11, V57), and addresses another nex app passed on as suggestions,
never kept on their own (B16, V58). Copied unchanged into every app."""

from __future__ import annotations

from typing import Any


def _admin(world: Any) -> str:
    return f"{world.pkg.PREFIX}/admin"


def test_one_change_keeps_switches_and_addresses_and_says_what(world: Any) -> None:
    """B18 (V60): one "Speichern" for the card; the answer names what it kept, nothing where nothing changed."""
    operator = world.app.client("operator")
    world.set_address("app", None)
    found = operator.put(
        _admin(world),
        json={"connections": True, "local": True, "addresses": {world.partner.name: world.partner.base + "/"}},
    )
    assert found.status_code == 200, found.text
    data = found.json()
    assert data["saved"] == ["local", world.partner.name]
    assert data["local"] is True and data["addresses"][world.partner.name] == world.partner.base
    again = operator.put(_admin(world), json={"connections": True, "local": True, "addresses": data["addresses"]})
    assert again.status_code == 200 and again.json()["saved"] == [] and again.json()["checks"] == {}


def test_a_wrong_field_keeps_nothing_and_names_every_field(world: Any) -> None:
    """B18 (V60): an address that is none stops the whole change; the refusal names each wrong field."""
    operator = world.app.client("operator")
    before = operator.get(_admin(world)).json()
    found = operator.put(_admin(world), json={"local": True, "addresses": {world.partner.name: "ftp://x.example.com"}})
    assert found.status_code == 422
    detail = found.json()["detail"]
    assert detail["code"] == "address_invalid" and detail["partner"] == world.partner.name
    assert detail["fields"] == {world.partner.name: "address_invalid"}
    after = operator.get(_admin(world)).json()
    assert after["local"] == before["local"] and after["addresses"] == before["addresses"]


def test_each_address_is_asked_what_answers_there_and_kept_anyway(world: Any) -> None:
    """B11 (V57): the operator learns at the field what answers at the address; it is kept either way."""
    operator = world.app.client("operator")
    name = world.partner.name

    def keep(address: str) -> dict[str, Any]:
        found = operator.put(_admin(world), json={"addresses": {name: address}})
        assert found.status_code == 200, found.text
        assert found.json()["addresses"][name] == address and name in found.json()["saved"]
        return found.json()["checks"][name]

    world.set_address("app", None)
    found = keep(world.partner.base)
    assert found == {"ok": True, "code": "found", "app": name, "version": "2.0.0"}
    other = keep(world.app.base)
    assert other["ok"] is False and other["code"] == "wrong_app" and other["app"] == world.app.config().app_name
    world.down.add("down.example.com")
    assert keep("https://down.example.com")["code"] == "unreachable"
    world.no_name.add("nowhere.example.com")
    assert keep("https://nowhere.example.com")["code"] == "name_unknown"
    assert keep("https://home.example.com")["code"] == "local_off"
    world.partner.store.set_setting("connections", False)
    world.partner.store.commit()
    off = keep(world.partner.base)
    assert off["ok"] is True and off["code"] == "partner_off"


def _third(world: Any) -> str | None:
    """An app both the app and the partner connect with, to pass on (``None`` where the pair shares none)."""
    app = world.app.config().app_name
    mine = set(world.pkg.CATALOG.partners(app))
    return next((name for name in world.pkg.CATALOG.partners(world.partner.name) if name in mine and name != app), None)


def test_addresses_another_app_passes_on_are_only_suggestions(world: Any) -> None:
    """B16 (V58): the partner connects and passes on its own address and the ones its operator set; here they wait for
    the operator, never kept on their own, each asked before it is kept, and only operators see them."""
    third = _third(world)
    known = {third: "https://third.example.com"} if third else {}
    world.partner.store.set_setting("addresses", {world.app.config().app_name: world.app.base, **known})
    world.partner.store.commit()
    world.set_address("app", None)
    assert world.connect("partner").status_code == 200
    operator = world.app.client("operator")
    data = operator.get(_admin(world)).json()
    assert data["addresses"][world.partner.name] == ""
    shown = {entry["partner"]: entry for entry in data["suggestions"]}
    assert shown[world.partner.name] == {
        "partner": world.partner.name,
        "address": world.partner.base,
        "from": world.partner.name,
    }
    if third:
        assert shown[third]["address"] == "https://third.example.com"
    assert world.app.client("owner").get(_admin(world)).status_code in (401, 403)
    assert world.app.client("owner").post(f"{_admin(world)}/suggestions/{world.partner.name}").status_code in (401, 403)
    # Taken with one click: asked first, kept where the right app answers.
    taken = operator.post(f"{_admin(world)}/suggestions/{world.partner.name}")
    assert taken.status_code == 200, taken.text
    assert taken.json()["saved"] == [world.partner.name]
    assert taken.json()["addresses"][world.partner.name] == world.partner.base
    assert taken.json()["checks"][world.partner.name]["code"] == "found"
    assert world.partner.name not in {entry["partner"] for entry in taken.json()["suggestions"]}
    if third:
        # Nothing answers there: not kept, the suggestion stays until the operator turns it down.
        tried = operator.post(f"{_admin(world)}/suggestions/{third}")
        assert tried.status_code == 200 and tried.json()["saved"] == [] and tried.json()["addresses"][third] == ""
        assert tried.json()["checks"][third]["code"] == "unreachable"
        assert third in {entry["partner"] for entry in tried.json()["suggestions"]}
        dropped = operator.delete(f"{_admin(world)}/suggestions/{third}")
        assert dropped.status_code == 200 and dropped.json()["suggestions"] == []
    assert operator.delete(f"{_admin(world)}/suggestions/{world.partner.name}").status_code == 404


def test_an_app_passes_on_what_its_operator_set_up(world: Any) -> None:
    """B16 (V58): the other way round, the app passes its own address and its operator's on to the partner."""
    world.partner.store.set_setting("addresses", {})
    world.partner.store.commit()
    assert world.connect("app").status_code == 200
    kept = world.partner.store.setting("suggestions") or {}
    assert kept[world.app.config().app_name] == {"address": world.app.base, "from": world.app.config().app_name}
    # Where the partner's operator has an address of the app, nothing is suggested for it.
    world.set_address("partner", world.app.base)
    world.partner.store.set_setting("suggestions", None)
    world.partner.store.commit()
    assert world.connect("app").status_code == 200
    assert world.app.config().app_name not in (world.partner.store.setting("suggestions") or {})
