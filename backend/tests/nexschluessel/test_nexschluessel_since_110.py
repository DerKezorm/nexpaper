"""Since schluessel 1.1.0 (MCP decisions 6, 10, 11, 12): an extra the page no longer offers (nexnotes and nextime
``mcp`` on an API key) stays on the keys that have it, can only be switched off on the page, and the app's older route
still sets it, so scripts notice nothing; where the operator takes AI from an account, it makes no MCP key and its MCP
keys rest until AI is allowed again."""

from __future__ import annotations

from typing import Any

import pytest
from schluessel_contract import ok


def _retired(config: Any) -> list[tuple[Any, str]]:
    found = [(kind, name) for kind in config.kinds for name in kind.retired_options]
    if not found:
        pytest.skip("this app has no retired extra")
    return found


def _code(app: Any, answer: Any) -> str:
    body = app.refusal(answer)
    return str(body.get("key_code") or body["code"])


def test_a_retired_extra_is_not_offered_and_the_page_never_switches_it_on(app: Any, config: Any) -> None:
    owner = app.client("owner")
    for kind, name in _retired(config):
        listed = next(found for found in owner.get(f"{app.prefix}/keys").json()["kinds"] if found["id"] == kind.id)
        assert name not in listed["options"] and name in listed["retired_options"]
        made = owner.post(
            f"{app.prefix}/keys", json={"kind": kind.id, "name": "Probe", "options": {name: True}, **app.defaults(kind)}
        )
        assert made.status_code == 422 and _code(app, made) == "option_retired", made.text


def test_the_apps_older_route_still_sets_a_retired_extra(app: Any, config: Any) -> None:
    """Decision 12: a script that makes a key over the older route with the extra gets it as before."""
    for kind, name in _retired(config):
        secret = app.old_route_key({name: True})
        assert ok(app.probe("mcp" if name == "mcp" else kind.id, secret))
        listed = app.client("owner").get(f"{app.prefix}/keys").json()["keys"]
        assert any(key["options"].get(name) for key in listed if key["kind"] == kind.id)


def test_a_key_that_has_a_retired_extra_may_only_switch_it_off_on_the_page(app: Any, config: Any) -> None:
    """Decision 11: renaming keeps it, switching it off works (the key no longer opens MCP), switching it on again
    does not."""
    owner = app.client("owner")
    for kind, name in _retired(config):
        secret = app.old_route_key({name: True})
        listed = owner.get(f"{app.prefix}/keys").json()["keys"]
        key = next(
            found
            for found in listed
            if found["kind"] == kind.id and found["options"].get(name) and secret.startswith(found["prefix"])
        )
        path = f"{app.prefix}/keys/{key['id']}"
        renamed = owner.patch(path, json={"name": "Renamed", "options": {name: True}})
        assert renamed.status_code == 200 and renamed.json()["options"][name] is True, renamed.text
        off = owner.patch(path, json={"options": {name: False}})
        assert off.status_code == 200 and off.json()["options"][name] is False
        if name == "mcp":
            assert not ok(app.probe("mcp", secret))
        again = owner.patch(path, json={"options": {name: True}})
        assert again.status_code == 422 and _code(app, again) == "option_retired"


def test_without_ai_an_account_makes_no_mcp_key_and_its_mcp_keys_rest(app: Any, config: Any) -> None:
    """Decision 10: the operator takes AI from the account; it makes no MCP key, its MCP keys answer 401 at MCP and
    work again once AI is allowed (nothing was deleted)."""
    kind = config.kind("mcp")
    if not app.has_ai or kind is None or not kind.creatable:
        pytest.skip("this app has no 'AI allowed' per account, or makes no MCP keys")
    owner = app.client("owner")
    made = owner.post(f"{app.prefix}/keys", json={"kind": "mcp", "name": "Notebook", **app.defaults(kind)})
    assert made.status_code == 201, made.text
    secret = made.json()["secret"]
    assert ok(app.probe("mcp", secret))
    app.take_ai("owner")
    assert owner.get(f"{app.prefix}/keys").json()["ai_allowed"] is False
    assert app.probe("mcp", secret) == 401
    refused = owner.post(f"{app.prefix}/keys", json={"kind": "mcp", "name": "Another", **app.defaults(kind)})
    assert refused.status_code == 403 and _code(app, refused) == "ai_not_allowed"
    app.give_ai("owner")
    assert ok(app.probe("mcp", secret))
    assert owner.get(f"{app.prefix}/keys").json()["ai_allowed"] is True
