"""Every device paired before the module keeps working (Bestand): written the way the older version wrote it, presented
to the app's real device route in the old form and the new, listed by the module, its push ticket still delivering the
kinds the published app knows, disconnected and renamed through the module. Red here means a phone out there loses
its connection with the update of the server."""

from __future__ import annotations

import json
from typing import Any

from geraete_contract import NEW, LegacyDevice, listed


def test_a_device_of_the_older_version_works_unchanged(app: Any, spec: LegacyDevice) -> None:
    made = app.make_legacy(spec)
    assert app.probe(made.token).status_code == 200, f"{spec.label}: refused by the app's own route"
    assert app.probe(made.token, NEW).status_code == 200


def test_the_module_lists_it_for_its_owner_only(app: Any, spec: LegacyDevice, package: Any) -> None:
    made = app.make_legacy(spec)
    rows = listed(app)
    assert len(rows) == 1 and rows[0]["name"] == spec.label and rows[0]["push"] is spec.push
    assert rows[0]["chooses_kinds"] is False, "the published app shows no ticks of its own"
    assert rows[0]["kind"] in ("ios", "ipados", "mac")
    assert listed(app, "other") == []
    text = app.client("owner").get(f"{app.browser_prefix}/app-devices").text
    assert made.token not in text and package.tokens.digest(made.token) not in text


def test_its_push_ticket_delivers_what_the_published_app_knows(app: Any, spec: LegacyDevice, config: Any,
                                                                package: Any) -> None:
    if not spec.push or not config.legacy_kinds:
        return
    made = app.make_legacy(spec)
    app.tell("owner", config.legacy_kinds[0])
    sent = app.relay.to(made.ticket)
    assert len(sent) == 1
    message = json.loads(package.seal.unseal(sent[0]["enc"], made.private_key, config.push_info))
    assert message["type"] == config.legacy_kinds[0]
    app.announce("9.9.9")
    assert len(app.relay.to(made.ticket)) == 1, "an older app never gets a kind it does not know"


def test_the_module_renames_and_disconnects_it(app: Any, spec: LegacyDevice) -> None:
    made = app.make_legacy(spec)
    row = listed(app)[0]
    client = app.client("owner")
    assert client.patch(f"{app.browser_prefix}/app-devices/{row['id']}", json={"name": "Renamed"}).json()["name"] == (
        "Renamed"
    )
    assert app.probe(made.token).status_code == 200
    assert client.delete(f"{app.browser_prefix}/app-devices/{row['id']}").status_code == 204
    assert app.probe(made.token, NEW).status_code == 401


def test_it_rests_while_blocked_and_works_again(app: Any, spec: LegacyDevice) -> None:
    made = app.make_legacy(spec)
    app.block()
    assert app.probe(made.token, NEW).status_code == 401
    app.unblock()
    assert app.probe(made.token).status_code == 200
