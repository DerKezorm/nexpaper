"""Notifications (G15–G18, G24, G25, G29): sealed for the one device, only kinds it understands and has on, nothing
while the account is blocked, the app is off or the device is gone, a 410 drops the ticket, a ticket belongs to one
device, "Neue Version" only to operators, "Neues Gerät verbunden" to the other devices. Red here means a message goes
where it must not, or a phone shows "changed" for a kind it does not know.

An app without a kind of its own (``kinds=()``, like nexlore) runs every case with the module's ``security``; only
what needs two different kinds asks for one of the app's own."""

from __future__ import annotations

import json
from typing import Any

from geraete_contract import NEW, auth, code_of, listed, new_device, sign_up_push

KIND_SECURITY = "security"


def _own_kind(config: Any) -> str:
    """One of the app's own kinds, or ``security`` where the app has none."""
    return str(config.kinds[0].id) if config.kinds else KIND_SECURITY


def _sent(app: Any, ticket: str) -> int:
    return len(app.relay.to(ticket))


def _messages(app: Any, ticket: str, private: str, package: Any) -> list[dict[str, Any]]:
    info = app.config().push_info
    return [json.loads(package.seal.unseal(body["enc"], private, info)) for body in app.relay.to(ticket)]


def test_a_message_is_sealed_for_the_device_and_the_relay_sees_nothing_of_it(app: Any, config: Any,
                                                                               package: Any) -> None:
    token = new_device(app)
    private = sign_up_push(app, token, understands=[_own_kind(config)])
    app.tell("owner", _own_kind(config))
    sent = app.relay.to("ticket-one")
    assert len(sent) == 1 and sent[0]["ticket"] == "ticket-one"
    assert app.relay.sent[0][0] == f"{config.relay()}/v1/send"
    assert "Kim Example" not in json.dumps(sent[0])
    assert _messages(app, "ticket-one", private, package)[0]["type"] == _own_kind(config)
    assert listed(app)[0]["push"] is True


def test_a_key_that_is_none_is_refused(app: Any) -> None:
    token = new_device(app)
    answer = app.device_client().put(f"{app.app_prefix}/push", json={"ticket": "t", "key": "not-a-key"},
                                     headers=auth(token))
    assert answer.status_code == 422 and code_of(answer) == "push_ticket_invalid"


def test_only_kinds_the_device_understands_and_without_a_list_the_published_ones(app: Any, config: Any) -> None:
    told = new_device(app)
    sign_up_push(app, told, understands=["security"], ticket="knows-little")
    old = new_device(app, name="old app")
    sign_up_push(app, old, ticket="old-app")
    before = len(app.relay.to("knows-little"))
    assert before == 1, "the pairing of the old app is told as security"
    chooses = {row["name"]: row["chooses_kinds"] for row in listed(app)}
    assert chooses == {"Kim's iPhone": True, "old app": False}, "only an app naming what it understands shows ticks"
    assert app.relay.to("old-app") == [], "an app without understands never gets security"
    if config.kinds:
        app.tell("owner", _own_kind(config))
        assert len(app.relay.to("knows-little")) == before
        assert len(app.relay.to("old-app")) == (1 if _own_kind(config) in config.legacy_kinds else 0)
    already = len(app.relay.to("old-app"))
    app.announce("9.9.9")
    new_device(app, name="third")
    assert len(app.relay.to("old-app")) == already, "an app without understands never gets update or security"
    assert len(app.relay.to("knows-little")) == before + 1, "but one that names security gets it"


def test_kinds_are_switched_per_device_in_the_app_and_in_the_browser(app: Any, config: Any) -> None:
    kind = _own_kind(config)
    phone = new_device(app)
    sign_up_push(app, phone, understands=[kind], ticket="phone")
    ipad = new_device(app, name="Kim's iPad")
    sign_up_push(app, ipad, understands=[kind], ticket="ipad")
    listed_kinds = app.device_client().get(f"{app.app_prefix}/push/kinds", headers=auth(phone)).json()["kinds"]
    ids = [entry["id"] for entry in listed_kinds]
    assert kind in ids and "security" in ids and "update" not in ids, "update is for operators only"
    assert all(entry["title"] and isinstance(entry["on"], bool) for entry in listed_kinds)
    off = app.device_client().put(f"{app.app_prefix}/push/kinds", json={kind: False}, headers=auth(phone))
    assert off.status_code == 200 and next(e for e in off.json()["kinds"] if e["id"] == kind)["on"] is False
    ipad_id = next(row["id"] for row in listed(app) if row["name"] == "Kim's iPad")
    path = f"{app.browser_prefix}/app-devices/{ipad_id}/push-kinds"
    assert app.client("owner").put(path, json={kind: False}).status_code == 200
    assert app.client("owner").put(path, json={kind: True}).status_code == 200
    assert app.client("other").get(path).status_code == 404
    unknown = app.client("owner").put(path, json={"update": True})
    assert unknown.status_code == 422 and code_of(unknown) == "kind_unknown"
    phone_before, ipad_before = _sent(app, "phone"), _sent(app, "ipad")
    app.tell("owner", kind)
    assert _sent(app, "phone") == phone_before and _sent(app, "ipad") == ipad_before + 1


def test_nothing_goes_out_while_blocked_switched_off_or_disconnected(app: Any, config: Any) -> None:
    kind = _own_kind(config)
    token = new_device(app)
    sign_up_push(app, token, understands=[kind])
    app.block()
    app.tell("owner", kind)
    app.unblock()
    app.switch("app", False)
    app.tell("owner", kind)
    app.switch("app", True)
    assert app.relay.sent == []
    app.tell("owner", kind)
    assert len(app.relay.sent) == 1, "after the block the ticket works again (G26)"
    row = listed(app)[0]
    app.client("owner").delete(f"{app.browser_prefix}/app-devices/{row['id']}")
    app.tell("owner", kind)
    assert len(app.relay.sent) == 1


def test_a_410_drops_the_ticket_and_off_means_off(app: Any, config: Any) -> None:
    kind = _own_kind(config)
    token = new_device(app)
    sign_up_push(app, token, understands=[kind], ticket="going")
    app.relay.answers["going"] = 410
    app.tell("owner", kind)
    app.tell("owner", kind)
    assert len(app.relay.to("going")) == 1 and listed(app)[0]["push"] is False
    sign_up_push(app, token, understands=[kind], ticket="again")
    assert app.device_client().delete(f"{app.app_prefix}/push", headers=auth(token)).status_code == 204
    app.tell("owner", kind)
    assert app.relay.to("again") == []


def test_a_ticket_belongs_to_one_device(app: Any, config: Any) -> None:
    kind = _own_kind(config)
    first = new_device(app)
    sign_up_push(app, first, understands=[kind], ticket="same")
    second = new_device(app, name="paired again")
    sign_up_push(app, second, understands=[kind], ticket="same")
    before = _sent(app, "same")
    app.tell("owner", kind)
    assert _sent(app, "same") == before + 1
    assert {row["name"]: row["push"] for row in listed(app)} == {"Kim's iPhone": False, "paired again": True}


def test_new_version_only_to_operators_that_have_it_on(app: Any, package: Any) -> None:
    boss = new_device(app, "operator", name="Olli's iPhone")
    private = sign_up_push(app, boss, understands=["update"], ticket="operator")
    quiet = new_device(app, "operator", name="Olli's iPad")
    sign_up_push(app, quiet, understands=["update"], ticket="operator-off")
    app.device_client().put(f"{app.app_prefix}/push/kinds", json={"update": False}, headers=auth(quiet))
    member = new_device(app)
    sign_up_push(app, member, understands=["update"], ticket="member")
    refused = app.device_client().put(f"{app.app_prefix}/push/kinds", json={"update": True}, headers=auth(member))
    assert refused.status_code == 422
    app.announce("9.9.9")
    assert app.relay.to("member") == [] and app.relay.to("operator-off") == []
    message = _messages(app, "operator", private, package)
    assert len(message) == 1 and message[0]["type"] == "update" and message[0]["version"] == "9.9.9"
    assert "9.9.9" in message[0]["title"] and app.running() in message[0]["text"]
    assert message[0]["current"] == app.running()
    kinds = app.device_client().get(f"{app.app_prefix}/push/kinds", headers=auth(boss)).json()["kinds"]
    assert next(entry for entry in kinds if entry["id"] == "update")["operator_only"] is True


def test_an_operator_s_device_that_wants_new_versions_counts_as_a_bell(app: Any, package: Any) -> None:
    """G56, U24: ``notices.update_wanted`` is what ``nexupdates`` asks before its daily look (``devices_want``)."""
    wanted = lambda: app.update_wanted()  # noqa: E731
    member = new_device(app)
    sign_up_push(app, member, understands=["update"], ticket="member")
    assert wanted() is False, "a member's device is no bell"
    boss = new_device(app, "operator", name="Olli's iPhone")
    assert wanted() is False, "not signed up for notifications"
    sign_up_push(app, boss, understands=["security"], ticket="operator")
    assert wanted() is False, "an app that does not name update"
    sign_up_push(app, boss, understands=["update"], ticket="operator")
    assert wanted() is True
    app.device_client().put(f"{app.app_prefix}/push/kinds", json={"update": False}, headers=auth(boss))
    assert wanted() is False, "switched off on the device"
    app.device_client().put(f"{app.app_prefix}/push/kinds", json={"update": True}, headers=auth(boss))
    app.switch("app", False)
    assert wanted() is False, "the iPhone app is switched off"
    app.switch("app", True)
    app.block("operator")
    assert wanted() is False, "a blocked operator"
    app.unblock("operator")
    assert wanted() is True


def test_a_new_device_is_told_to_the_others_not_to_itself(app: Any, package: Any) -> None:
    phone = new_device(app)
    private = sign_up_push(app, phone, understands=["security"], ticket="phone")
    answer = app.device_client().post(f"{app.app_prefix}/devices", json={"device_name": "Kim's iPad"},
                                      headers=auth(phone, NEW))
    assert answer.status_code == 201
    told = _messages(app, "phone", private, package)
    assert len(told) == 1 and told[0]["type"] == "security" and "Kim's iPad" in told[0]["text"]
    assert app.paired_mails()[-1] == (app.account_id("owner"), "Kim's iPad")
