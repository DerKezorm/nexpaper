"""Keys made through the module: the app's prefix, shown once, working on the app's own routes, with the rules every
app keeps (name, right, areas, lifetime, limit), changed and revoked by their owner only."""

from __future__ import annotations

from typing import Any

import pytest
from schluessel_contract import kinds_made_by_hand, ok


def _kinds(config: Any) -> list[Any]:
    found = kinds_made_by_hand(config)
    if not found:
        pytest.skip("this app makes no keys by hand")
    return found


def _make(app: Any, kind: Any, **body: Any) -> Any:
    return app.client("owner").post(
        f"{app.prefix}/keys", json={"kind": kind.id, "name": "Probe", **app.defaults(kind), **body}
    )


def test_a_new_key_carries_the_apps_prefix_is_shown_once_and_works(app: Any, config: Any) -> None:
    for kind in _kinds(config):
        made = _make(app, kind)
        assert made.status_code == 201, made.text
        body = made.json()
        secret = body["secret"]
        assert secret.startswith(kind.prefix) and len(secret) == len(kind.prefix) + 43
        assert body["key"]["prefix"] == secret[: len(kind.prefix) + kind.shown_extra]
        assert made.headers.get("cache-control") == "no-store"
        assert ok(app.probe(kind.id, secret))
        assert secret not in app.client("owner").get(f"{app.prefix}/keys").text


def test_the_form_learns_what_the_app_offers(app: Any, config: Any) -> None:
    listed = app.client("owner").get(f"{app.prefix}/keys").json()
    assert listed["app"] == config.app_name and listed["api"] in (True, False)
    for kind in config.kinds:
        offered = next(found for found in listed["kinds"] if found["id"] == kind.id)
        assert offered["prefix"] == kind.prefix and offered["rights"] == list(kind.rights)
        assert offered["options"] == list(kind.options)
        assert (offered["expiry_days"] is None) == (kind.expiry_days is None)
        assert (offered["areas"] is None) == (not kind.areas)


def test_a_name_is_needed_and_has_a_limit(app: Any, config: Any) -> None:
    for kind in _kinds(config):
        assert app.refusal(_make(app, kind, name="   "))["code"] == config.public_code("name_missing")
        assert _make(app, kind, name="x" * (kind.name_max + 1)).status_code == 422
        assert _make(app, kind, name="a\n  b").json()["key"]["name"] == "a b"


def test_only_the_apps_rights_extras_and_lifetimes(app: Any, config: Any) -> None:
    for kind in _kinds(config):
        assert _make(app, kind, right="everything").status_code == 422
        assert _make(app, kind, options={"no_such_extra": True}).status_code == 422
        if kind.expiry_days is not None:
            assert _make(app, kind, days=17).status_code == 422
            days = next(day for day in kind.expiry_days if day is not None)
            assert _make(app, kind, days=days).json()["key"]["expires_at"] is not None
            if None in kind.expiry_days:
                assert _make(app, kind, days=None).json()["key"]["expires_at"] is None


def test_a_key_reaches_only_areas_of_its_own_account(app: Any, config: Any) -> None:
    kinds = [kind for kind in _kinds(config) if kind.areas]
    if not kinds:
        pytest.skip("this app does not limit keys to areas")
    for kind in kinds:
        offered = next(
            found for found in app.client("owner").get(f"{app.prefix}/keys").json()["kinds"] if found["id"] == kind.id
        )
        assert offered["areas"], "the owner needs an area of its own for this test"
        assert _make(app, kind, areas=[app.foreign_area()]).status_code == 422
        assert _make(app, kind, areas=[]).status_code == 422
        mine = offered["areas"][0]["id"]
        made = _make(app, kind, areas=[mine])
        assert made.status_code == 201 and [area["id"] for area in made.json()["key"]["areas"]] == [mine]
        if kind.areas_required:
            assert _make(app, kind, areas="all").status_code == 422
        else:
            assert _make(app, kind, areas="all").json()["key"]["areas"] is None


def test_an_account_has_at_most_its_limit(app: Any, config: Any) -> None:
    kind = _kinds(config)[0]
    listed = next(
        found for found in app.client("owner").get(f"{app.prefix}/keys").json()["kinds"] if found["id"] == kind.id
    )
    for number in range(kind.max_keys - listed["count"]):
        assert _make(app, kind, name=f"Key {number}").status_code == 201
    refused = _make(app, kind, name="One too many")
    assert refused.status_code == 409 and app.refusal(refused)["max"] == kind.max_keys


def test_making_waits_for_the_operators_switch(app: Any, config: Any) -> None:
    kind = _kinds(config)[0]
    app.client("operator").put(f"{app.prefix}/interfaces", json={kind.switch: False})
    refused = _make(app, kind)
    assert refused.status_code in (401, 403)
    assert app.refusal(refused)["code"] == config.public_code(f"{kind.switch}_off")


def test_an_account_whose_keys_rest_still_makes_them_and_is_told(app: Any, config: Any) -> None:
    kind = _kinds(config)[0]
    app.owe_factor()
    made = _make(app, kind)
    assert made.status_code == 201, "making a key stays possible (decided 24.11.2026)"
    assert not ok(app.probe(kind.id, made.json()["secret"]))
    assert app.client("owner").get(f"{app.prefix}/keys").json()["keys_wait"] is True


def test_the_owner_changes_name_right_and_extras_and_nobody_else(app: Any, config: Any) -> None:
    for kind in [kind for kind in _kinds(config) if kind.editable]:
        made = _make(app, kind).json()
        key = made["key"]["id"]
        assert app.client("other").patch(f"{app.prefix}/keys/{key}", json={"name": "Not mine"}).status_code == 404
        other_right = kind.rights[-1]
        changed = app.client("owner").patch(f"{app.prefix}/keys/{key}", json={"name": "Renamed", "right": other_right})
        assert changed.status_code == 200, changed.text
        assert changed.json()["name"] == "Renamed" and changed.json()["right"] == other_right
        assert ok(app.probe(kind.id, made["secret"])), "a change keeps the key"


def test_revoking_a_new_key_ends_it(app: Any, config: Any) -> None:
    for kind in _kinds(config):
        made = _make(app, kind).json()
        assert app.client("owner").delete(f"{app.prefix}/keys/{made['key']['id']}").status_code == 204
        assert not ok(app.probe(kind.id, made["secret"]))
        assert app.client("owner").delete(f"{app.prefix}/keys/{made['key']['id']}").status_code == 404


def test_a_presented_key_of_the_wrong_shape_or_unknown_is_refused(app: Any, config: Any) -> None:
    for kind in config.kinds:
        assert not ok(app.probe(kind.id, kind.prefix + "x" * 43))
        assert not ok(app.probe(kind.id, kind.prefix + "y" * 400))
        assert not ok(app.probe(kind.id, "nothing"))


def test_the_operator_never_sees_the_start_of_a_key_its_owner_does(app: Any, config: Any) -> None:
    """Since E36 (nexnotes showed it to nobody but the owner): the operator's list and the answers of locking and
    unlocking carry no ``prefix``, no part of the secret; the owner's own list keeps it."""
    for kind in _kinds(config):
        made = _make(app, kind).json()
        start = made["key"]["prefix"]
        assert start and start in app.client("owner").get(f"{app.prefix}/keys").text
        operator = app.client("operator")
        listing = operator.get(f"{app.prefix}/admin/keys")
        row = next(found for found in listing.json()["keys"] if str(found["id"]) == str(made["key"]["id"]))
        assert "prefix" not in row and isinstance(row["extra"], dict)
        locked = operator.post(f"{app.prefix}/admin/keys/{made['key']['id']}/block")
        unlocked = operator.post(f"{app.prefix}/admin/keys/{made['key']['id']}/unblock")
        for answer in (listing, locked, unlocked):
            assert answer.status_code == 200 and start not in answer.text and made["secret"] not in answer.text
        assert "prefix" not in locked.json() and "prefix" not in unlocked.json()
