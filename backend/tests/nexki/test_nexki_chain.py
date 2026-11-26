"""The chain of switches (K2, K3; MCP decision 10) and the brakes, through the app's own routes. Every switch alone
says no, at every request; switched off deletes nothing. Copied unchanged into every app."""

from __future__ import annotations

from typing import Any

import pytest
from ki_contract import code, operator_puts, own, package, shared


def test_a_new_installation_starts_closed_with_the_operators_service_for_all(app: Any) -> None:
    view = app.client("operator").get(app.server_prefix).json()
    assert view["enabled"] is False and view["mode"] == "shared" and view["key_set"] is False
    done = app.manual("owner", "Please tidy this text up")
    assert done.status_code == 409 and code(done) == "ai_off"


def test_the_main_switch_alone_says_no_and_deletes_nothing(app: Any, service: Any) -> None:
    shared(app, service.base, enabled=False)
    assert code(app.manual("owner", "Please tidy this text up")) == "ai_off"
    assert operator_puts(app, enabled=True).status_code == 200
    assert app.manual("owner", "Please tidy this text up").status_code == 200
    assert operator_puts(app, enabled=False).json()["model"] == "plain"
    assert code(app.manual("owner", "Please tidy this text up")) == "ai_off"


def test_ai_allowed_of_the_account_alone_says_no_and_rests_ai_programs(app: Any, service: Any) -> None:
    nexki = package(app)
    shared(app, service.base)
    owner = app.account_id("owner")
    assert nexki.chain.for_programs(app.store(), owner) is True
    app.take_ai("owner")
    done = app.manual("owner", "Please tidy this text up")
    assert done.status_code == 403 and code(done) == "ai_not_allowed"
    assert nexki.chain.for_programs(app.store(), owner) is False
    assert app.manual("other", "Please tidy this text up").status_code == 200
    app.give_ai("owner")
    assert app.manual("owner", "Please tidy this text up").status_code == 200


def test_a_blocked_account_sends_nothing_and_its_ai_programs_rest(app: Any, service: Any) -> None:
    nexki = package(app)
    shared(app, service.base)
    owner = app.account_id("owner")
    app.shut_out("owner")
    assert nexki.chain.for_programs(app.store(), owner) is False
    with pytest.raises(nexki.AiRefused) as refused:
        app.automatic("owner", "A letter for the inbox")
    assert refused.value.code == "ai_not_allowed"
    app.let_in("owner")
    assert nexki.chain.for_programs(app.store(), owner) is True


def test_the_persons_own_switch_alone_says_no(app: Any, service: Any) -> None:
    shared(app, service.base)
    owner = app.client("owner")
    state = owner.put(app.me_prefix, json={"mine": False}).json()
    assert state["mine"] is False and state["available"] is False and state["reason"] == "ai_switched_off"
    done = app.manual("owner", "Please tidy this text up")
    assert done.status_code == 403 and code(done) == "ai_switched_off"
    assert owner.put(app.me_prefix, json={"mine": True}).json()["available"] is True


def test_the_apps_own_check_says_no_for_one_request(app: Any, service: Any) -> None:
    shared(app, service.base)
    done = app.app_refused("owner", "Something the app keeps from the AI")
    if done is None:  # the app has no check of its own
        return
    assert done.status_code == 403 and code(done) == "ai_app_refused"
    assert len(service.seen) == 0


def test_own_accesses_only_in_the_way_own(app: Any, service: Any) -> None:
    shared(app, service.base)
    refused = app.client("owner").put(app.me_prefix, json={"url": service.base, "model": "plain"})
    assert refused.status_code == 409 and code(refused) == "ai_own_off"
    own(app)
    done = app.manual("owner", "Please tidy this text up")
    assert done.status_code == 409 and code(done) == "ai_incomplete"


def test_the_operators_routes_are_the_operators(app: Any) -> None:
    for role in ("owner", "other"):
        client = app.client(role)
        assert client.get(app.server_prefix).status_code in (401, 403)
        assert client.put(app.server_prefix, json={"enabled": True}).status_code in (401, 403)
        assert client.post(f"{app.server_prefix}/probe").status_code in (401, 403)
    assert app.client("anonymous").get(app.me_prefix).status_code in (401, 403)


def test_a_member_never_learns_a_host_of_the_own_network(app: Any, service: Any) -> None:
    shared(app, service.base)
    state = app.client("owner").get(app.me_prefix).json()
    assert state["available"] is True and state["local"] is True and state["to"] == ""
    assert "127.0.0.1" not in str(state) and "url" not in state


def test_the_key_never_comes_back(app: Any, keyed: Any) -> None:
    from ki_contract import KEY

    view = shared(app, keyed.base, key=KEY)
    assert view["key_set"] is True and KEY not in str(view)
    assert KEY not in app.client("operator").get(app.server_prefix).text
    assert app.manual("owner", "Please tidy this text up").status_code == 200
    assert KEY not in app.dump()


def test_the_brakes_per_minute_and_per_day_on_the_server(app: Any, service: Any) -> None:
    shared(app, service.base)
    operator_puts(app, per_minute=1)
    assert app.manual("owner", "Please tidy this text up").status_code == 200
    slowed = app.manual("owner", "Please tidy this text up")
    assert slowed.status_code == 429 and code(slowed) == "ai_too_often" and slowed.headers.get("retry-after") == "60"
    package(app).brake.BRAKE.forget()
    operator_puts(app, per_minute=60, server_day=2)
    assert app.manual("other", "Please tidy this text up").status_code in (200, 429)
    used = app.manual("other", "Please tidy this text up")
    assert used.status_code == 429 and code(used) == "ai_day_used"
    assert app.client("operator").get(app.server_prefix).json()["used_today"] == 2
