"""Every key made before the module keeps working: written the way the older version wrote it, presented to the app's
real routes, listed by the module with its prefix and right, revoked, locked and unlocked through the module. Red
here means a program, an iPhone shortcut, Home Assistant or another nex app would lose its access."""

from __future__ import annotations

from typing import Any

from schluessel_contract import LegacyKey, ok


def _listed(app: Any, role: str = "owner") -> list[dict]:
    answer = app.client(role).get(f"{app.prefix}/keys")
    assert answer.status_code == 200, answer.text
    return answer.json()["keys"]


def _find(rows: list[dict], spec: LegacyKey) -> dict | None:
    return next((row for row in rows if row["prefix"].startswith(spec.prefix)), None)


def test_a_key_of_the_older_version_works_unchanged(app: Any, spec: LegacyKey) -> None:
    secret = app.make_legacy(spec)
    assert secret.startswith(spec.prefix)
    assert ok(app.probe(spec.kind, secret)), f"{spec.label}: refused by the app's own route"


def test_the_module_lists_it_with_its_prefix_right_and_form_for_its_owner_only(app: Any, spec: LegacyKey) -> None:
    secret = app.make_legacy(spec)
    row = _find(_listed(app), spec)
    assert row is not None, f"{spec.label} is missing from the owner's list"
    assert secret.startswith(row["prefix"]) and len(row["prefix"]) < len(secret)
    assert row["kind"] == spec.kind and row["right"] == spec.right
    assert row["legacy"] == spec.legacy and row["program"] == spec.program
    assert row["blocked"] is False and row["expired"] is False
    assert _find(_listed(app, "other"), spec) is None


def test_neither_the_secret_nor_its_hash_ever_leaves_the_server(app: Any, spec: LegacyKey, package: Any) -> None:
    secret = app.make_legacy(spec)
    for role, path in (("owner", "/keys"), ("operator", "/admin/keys")):
        text = app.client(role).get(f"{app.prefix}{path}").text
        assert secret not in text and package.digest(secret) not in text and secret[-20:] not in text


def test_revoking_through_the_module_ends_it_at_once(app: Any, spec: LegacyKey) -> None:
    secret = app.make_legacy(spec)
    row = _find(_listed(app), spec)
    assert row is not None
    assert app.client("other").delete(f"{app.prefix}/keys/{row['id']}").status_code == 404
    assert ok(app.probe(spec.kind, secret)), "another account's attempt to revoke must change nothing"
    assert app.client("owner").delete(f"{app.prefix}/keys/{row['id']}").status_code == 204
    assert not ok(app.probe(spec.kind, secret))
    assert _find(_listed(app), spec) is None


def test_the_operator_locks_and_unlocks_it(app: Any, spec: LegacyKey) -> None:
    secret = app.make_legacy(spec)
    row = _find(_listed(app), spec)
    assert row is not None
    operator = app.client("operator")
    every = operator.get(f"{app.prefix}/admin/keys").json()["keys"]
    shown = next(found for found in every if str(found["id"]) == str(row["id"]))
    assert shown["account"]["name"] and shown["right"] == spec.right
    locked = operator.post(f"{app.prefix}/admin/keys/{row['id']}/block")
    assert locked.status_code == 200 and locked.json()["blocked"] is True
    assert not ok(app.probe(spec.kind, secret))
    assert _find(_listed(app), spec)["blocked"] is True
    unlocked = operator.post(f"{app.prefix}/admin/keys/{row['id']}/unblock")
    assert unlocked.status_code == 200 and unlocked.json()["blocked"] is False
    assert ok(app.probe(spec.kind, secret))


def test_an_expired_key_is_refused_and_listed_as_expired(app: Any, spec: LegacyKey) -> None:
    secret = app.make_legacy(spec, expired=True)
    assert not ok(app.probe(spec.kind, secret))
    row = _find(_listed(app), spec)
    # A connector's access token runs out every hour; the connection itself has no end on the page.
    assert row is not None and row["expired"] is (not spec.program)


def test_its_keys_rest_while_the_account_owes_a_second_factor(app: Any, spec: LegacyKey) -> None:
    secret = app.make_legacy(spec)
    app.owe_factor()
    assert not ok(app.probe(spec.kind, secret))
    assert app.client("owner").get(f"{app.prefix}/keys").json()["keys_wait"] is True


def test_switching_its_interface_off_holds_it_and_on_brings_it_back(app: Any, spec: LegacyKey) -> None:
    secret = app.make_legacy(spec)
    switch = "mcp" if spec.kind == "mcp" else "api"
    operator = app.client("operator")
    assert operator.put(f"{app.prefix}/interfaces", json={switch: False}).json()[switch] is False
    assert not ok(app.probe(spec.kind, secret))
    assert _find(_listed(app), spec) is not None, "switching off deletes nothing"
    assert operator.put(f"{app.prefix}/interfaces", json={switch: True}).json()[switch] is True
    assert ok(app.probe(spec.kind, secret))
