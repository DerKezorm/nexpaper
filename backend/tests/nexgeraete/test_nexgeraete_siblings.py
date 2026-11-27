"""Another own device over iCloud (G9): a device's key asks for one of its own for the account's other device, at most
five an hour, counted in the database (a restart forgets nothing). Red here means a key is a factory of keys, or a
device lands in the wrong account."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from geraete_contract import NEW, auth, code_of, listed, new_device


def _sibling(app: Any, token: str, name: str = "Kim's iPad") -> Any:
    return app.device_client().post(
        f"{app.app_prefix}/devices", json={"device_name": name, "device_kind": "ipados"}, headers=auth(token)
    )


def test_a_device_brings_in_another_with_a_key_of_its_own(app: Any, config: Any) -> None:
    token = new_device(app)
    answer = _sibling(app, token)
    assert answer.status_code == 201, answer.text
    assert answer.headers["cache-control"] == "no-store"
    body = answer.json()
    assert body["token"] != token and body["token"].startswith(config.token_prefix)
    assert body["account"]["id"] == app.account_id("owner")
    assert body["device"]["via"] == "icloud" and body["device"]["kind"] == "ipados"
    assert sorted(row["name"] for row in listed(app)) == ["Kim's iPad", "Kim's iPhone"]
    ipad = next(row for row in listed(app) if row["name"] == "Kim's iPad")
    assert app.client("owner").delete(f"{app.browser_prefix}/app-devices/{ipad['id']}").status_code == 204
    assert app.probe(token, NEW).status_code == 200, "the iPhone stays when the iPad goes"
    assert app.probe(body["token"], NEW).status_code == 401


def test_the_new_device_belongs_to_the_account_of_the_key_that_asked(app: Any) -> None:
    mine = new_device(app)
    theirs = new_device(app, "other", name="Mila's iPhone")
    answer = _sibling(app, theirs, "Mila's iPad")
    assert answer.status_code == 201
    assert answer.json()["account"]["id"] == app.account_id("other")
    assert [row["name"] for row in listed(app)] == ["Kim's iPhone"]
    assert sorted(row["name"] for row in listed(app, "other")) == ["Mila's iPad", "Mila's iPhone"]
    assert app.probe(mine, NEW).json()["account"]["id"] == app.account_id("owner")


def test_the_sixth_in_an_hour_waits_also_after_a_restart(app: Any, config: Any) -> None:
    token = new_device(app)
    for number in range(config.siblings_per_hour):
        assert _sibling(app, token, f"iPad {number}").status_code == 201
    refused = _sibling(app, token)
    assert refused.status_code == 429 and code_of(refused) == "too_many_attempts"
    assert 1 <= int(refused.headers["retry-after"]) <= 3600
    app.restart()
    assert _sibling(app, token).status_code == 429, "counted in the database, not in memory"
    app.travel(timedelta(hours=1, seconds=1))
    assert _sibling(app, token).status_code == 201


def test_disconnected_siblings_still_count_for_the_hour(app: Any, config: Any) -> None:
    """Since 0.1.5 (G33 anew): disconnecting the new devices does not open the limit again, also after a restart
    (``Store.sibling_times`` counts them from the database)."""
    token = new_device(app)
    for number in range(config.siblings_per_hour):
        made = _sibling(app, token, f"iPad {number}")
        assert made.status_code == 201
        gone = app.client("owner").delete(f"{app.browser_prefix}/app-devices/{made.json()['device']['id']}")
        assert gone.status_code == 204
    assert [row["name"] for row in listed(app)] == ["Kim's iPhone"]
    refused = _sibling(app, token)
    assert refused.status_code == 429 and code_of(refused) == "too_many_attempts"
    app.restart()
    assert _sibling(app, token).status_code == 429, "the disconnected ones are counted in the database"
    app.travel(timedelta(hours=1, seconds=1))
    assert _sibling(app, token).status_code == 201


def test_without_a_key_there_is_no_sibling(app: Any) -> None:
    answer = app.device_client().post(f"{app.app_prefix}/devices", json={}, headers=NEW)
    assert answer.status_code == 401 and code_of(answer) == "device_disconnected"
