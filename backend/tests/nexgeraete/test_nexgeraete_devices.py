"""The devices of an account (G11, G28): the list in the browser and in the app with "this one", renaming in both,
disconnecting one or all, the operator's view of an account (how many, which kind, last seen; never a name) and his
"Geräte trennen". Never a key or its hash in an answer. Red here means a list shows what it must not, or a device
another account can end."""

from __future__ import annotations

from typing import Any

from geraete_contract import NEW, auth, code_of, listed, new_device

FIELDS = {"id", "name", "kind", "model", "system", "app_version", "via", "created_at", "last_seen_at", "push", "this"}


def test_the_browser_lists_the_own_devices_only_with_every_field(app: Any, config: Any, package: Any) -> None:
    token = new_device(app)
    new_device(app, "other", name="Mila's iPhone")
    answer = app.client("owner").get(f"{app.browser_prefix}/app-devices")
    body = answer.json()
    assert body["max"] == config.max_devices and body["has_app"] == config.has_app
    assert body["app_store_url"] == config.app_store_url
    rows = body["devices"]
    assert [row["name"] for row in rows] == ["Kim's iPhone"] and set(rows[0]) >= FIELDS
    assert token not in answer.text and package.tokens.digest(token) not in answer.text


def test_the_app_lists_the_account_s_devices_and_marks_this_one(app: Any) -> None:
    phone = new_device(app)
    new_device(app, name="Kim's Mac")
    answer = app.device_client().get(f"{app.app_prefix}/devices", headers=auth(phone))
    assert answer.status_code == 200
    rows = answer.json()
    assert {row["name"]: row["this"] for row in rows} == {"Kim's iPhone": True, "Kim's Mac": False}
    assert phone not in answer.text


def test_renaming_in_the_browser_and_in_the_app(app: Any, config: Any) -> None:
    token = new_device(app)
    row = listed(app)[0]
    browser = app.client("owner")
    changed = browser.patch(f"{app.browser_prefix}/app-devices/{row['id']}", json={"name": "  Kims   Phone "})
    assert changed.status_code == 200 and changed.json()["name"] == "Kims Phone"
    for bad in ("", "   ", "x" * (config.name_max + 1), "bad\u0007name"):
        refused = browser.patch(f"{app.browser_prefix}/app-devices/{row['id']}", json={"name": bad})
        assert refused.status_code == 422 and code_of(refused) == "name_invalid", repr(bad)
    assert app.client("other").patch(f"{app.browser_prefix}/app-devices/{row['id']}",
                                     json={"name": "Taken"}).status_code == 404
    own = app.device_client().patch(f"{app.app_prefix}/device", json={"name": "Desk"}, headers=auth(token))
    assert own.status_code == 200 and own.json()["name"] == "Desk" and own.json()["this"] is True
    assert listed(app)[0]["name"] == "Desk"


def test_a_long_name_from_an_app_is_cut_not_refused(app: Any, config: Any) -> None:
    from geraete_contract import pick_up, start_pairing

    answer = pick_up(app, start_pairing(app), name="n" * 150)
    assert answer.status_code == 200 and answer.json()["device"]["name"] == "n" * config.name_max


def test_disconnecting_one_in_the_app_and_another_account_s_never(app: Any) -> None:
    phone = new_device(app)
    mac = new_device(app, name="Kim's Mac")
    other = new_device(app, "other", name="Mila's iPhone")
    mac_id = next(row["id"] for row in listed(app) if row["name"] == "Kim's Mac")
    client = app.device_client()
    assert client.delete(f"{app.app_prefix}/devices/{mac_id}", headers=auth(other)).status_code == 404
    assert app.probe(mac, NEW).status_code == 200
    assert client.delete(f"{app.app_prefix}/devices/{mac_id}", headers=auth(phone)).status_code == 204
    assert app.probe(mac, NEW).status_code == 401
    assert client.delete(f"{app.app_prefix}/device", headers=auth(phone)).status_code == 204
    assert app.probe(phone, NEW).status_code == 401
    assert listed(app) == []


def test_disconnecting_all_leaves_other_accounts(app: Any) -> None:
    tokens = [new_device(app), new_device(app, name="Kim's iPad")]
    other = new_device(app, "other")
    answer = app.client("owner").delete(f"{app.browser_prefix}/app-devices")
    assert answer.status_code == 200 and answer.json() == {"removed": 2}
    assert all(app.probe(token, NEW).status_code == 401 for token in tokens)
    assert app.probe(other, NEW).status_code == 200


def test_the_operator_sees_how_many_which_and_when_never_names_and_can_end_them(app: Any) -> None:
    token = new_device(app)
    path = f"{app.browser_prefix}/server/accounts/{app.account_id('owner')}/devices"
    assert app.client("other").get(path).status_code in (401, 403)
    seen = app.client("operator").get(path)
    assert seen.status_code == 200
    body = seen.json()
    assert body["count"] == 1 and body["devices"][0]["kind"] == "ios"
    assert body["devices"][0]["model"] == "iPhone 16 Pro" and set(body["devices"][0]) == {"kind", "model",
                                                                                            "last_seen_at"}
    assert "Kim's iPhone" not in seen.text and token not in seen.text
    assert app.client("other").delete(path).status_code in (401, 403)
    assert app.probe(token, NEW).status_code == 200
    ended = app.client("operator").delete(path)
    assert ended.status_code == 200 and ended.json() == {"removed": 1}
    assert app.probe(token, NEW).status_code == 401
