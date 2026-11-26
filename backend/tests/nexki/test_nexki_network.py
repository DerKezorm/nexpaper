"""Where a request may go (decision K1: this closes nexmail's open place; K4: the own network only from the operator's
list): the home network, 169.254.169.254, a redirect, the size, one deadline, no proxy from the environment, the key
never to a new host. Through the app's own routes; copied unchanged into every app."""

from __future__ import annotations

import time
from typing import Any

import pytest
from ki_contract import (
    KEY,
    PUBLIC,
    code,
    fast_clock,
    internet,
    last_body,
    operator_puts,
    own,
    package,
    resolving,
    said,
    shared,
    task,
    values,
)


def test_the_operators_service_may_lie_in_the_own_network(app: Any, service: Any) -> None:
    shared(app, service.base)
    done = task(app, "owner", "Please tidy this text up")
    assert done.status_code == 200, done.text
    assert done.json()["text"].startswith("Done:")
    # In the own network a thinking model is asked not to think (nexpaper 1.5.1).
    assert last_body(service)["reasoning_effort"] == "none"


def test_an_own_service_in_the_home_network_needs_the_operators_list(app: Any, service: Any) -> None:
    own(app)
    owner = app.client("owner")
    refused = owner.put(app.me_prefix, json={"api": "openai", "url": "http://192.168.1.20:11434/v1", "model": "x"})
    assert refused.status_code == 422 and code(refused) == "ai_address_private"
    refused = owner.put(app.me_prefix, json={"url": service.base, "model": "plain"})
    assert code(refused) == "ai_address_private"
    port = service.base.split(":")[2].split("/")[0]
    own(app, hosts=[f"127.0.0.1:{port}", "192.168.1.20:11434"])
    assert owner.put(app.me_prefix, json={"url": "http://192.168.1.20:11434/v1", "model": "x"}).status_code == 200
    assert owner.put(app.me_prefix, json={"url": service.base, "model": "plain"}).status_code == 200
    done = task(app, "owner", "Please tidy this text up")
    assert done.status_code == 200, done.text
    # Taken off the list, the same access stops at the next request: checked at every request, not when saved.
    own(app, hosts=["192.168.1.20:11434"])
    again = task(app, "owner", "Please tidy this text up")
    assert said(app, again, "ai_address_private")


@pytest.mark.parametrize(
    "url, names",
    [
        ("http://169.254.169.254/v1", {}),
        ("http://[::ffff:169.254.169.254]/v1", {}),
        ("http://[64:ff9b::a9fe:a9fe]/v1", {}),
        ("http://metadata.example.com/v1", {"metadata.example.com": ["169.254.169.254"]}),
        ("http://[fe80::1]/v1", {}),
        ("http://100.100.100.200/v1", {}),
    ],
)
def test_the_metadata_address_and_link_local_are_never_reached(app: Any, url: str, names: dict) -> None:
    with resolving(app, names):
        for_operator = operator_puts(app, api="openai", url=url, model="x")
        assert for_operator.status_code == 422 and code(for_operator) == "ai_address_refused", for_operator.text
        own(app, hosts=["169.254.169.254", "metadata.example.com", "[fe80::1]", "100.100.100.200"])
        for_account = app.client("owner").put(app.me_prefix, json={"url": url, "model": "x"})
        assert code(for_account) == "ai_address_refused", for_account.text


def test_a_redirect_is_not_followed(app: Any, service: Any, recorder: Any) -> None:
    service.redirect_to = recorder.address + "v1/chat/completions"
    shared(app, service.base, model="redirect")
    done = task(app, "owner", "Please tidy this text up")
    assert said(app, done, "ai_service_failed")
    assert values(app, done).get("answered") == 307
    assert recorder.hits == []


def test_an_answer_that_is_too_large_is_not_read(app: Any, service: Any) -> None:
    shared(app, service.base, model="huge")
    done = task(app, "owner", "Please tidy this text up")
    assert said(app, done, "ai_unreadable")


def test_one_deadline_for_the_whole_request(app: Any, service: Any) -> None:
    """A service that sends a byte now and then holds nobody longer than the task's deadline, whatever it is."""
    shared(app, service.base, model="slow")
    started = time.monotonic()
    with fast_clock(app, factor=200.0):
        done = task(app, "owner", "Please tidy this text up")
    assert said(app, done, "ai_timeout")
    assert time.monotonic() - started < 15


def test_no_proxy_from_the_environment(app: Any, service: Any, recorder: Any, monkeypatch: Any) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, recorder.address)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    shared(app, service.base)
    done = task(app, "owner", "Please tidy this text up")
    assert done.status_code == 200, done.text
    assert recorder.hits == [] and service.seen


def test_the_key_does_not_go_to_a_new_host(app: Any) -> None:
    from nexki_service import ReferenceService

    remote = ReferenceService()
    with internet(app, remote):
        shared(app, "https://ai.example.com/v1/", key=KEY)
        assert task(app, "owner", "Please tidy this text up").status_code == 200
        assert remote.seen[-1].headers.get("authorization") == f"Bearer {KEY}"
        moved = operator_puts(app, url="https://other.example.com/v1/")
        assert moved.status_code == 200 and moved.json()["key_set"] is False
        assert task(app, "owner", "Please tidy this text up").status_code == 200
        assert "authorization" not in remote.seen[-1].headers
        # A model list with a typed address gets the stored key only for the stored address.
        operator_puts(app, url="https://ai.example.com/v1/", key=KEY)
        listed = app.client("operator").post(f"{app.server_prefix}/models", json={"url": "https://third.example.com/v1/"})
        assert listed.status_code == 200
        assert "authorization" not in remote.seen[-1].headers
    for seen in remote.seen:
        assert seen.via.startswith(PUBLIC)


def test_the_own_access_forgets_its_key_on_a_new_host_too(app: Any) -> None:
    from nexki_service import ReferenceService

    remote = ReferenceService()
    with internet(app, remote):
        own(app)
        owner = app.client("owner")
        assert owner.put(app.me_prefix, json={"api": "openai", "url": "https://ai.example.com/v1/", "model": "plain",
                                              "key": KEY}).json()["own"]["key_set"] is True
        moved = owner.put(app.me_prefix, json={"url": "https://other.example.com/v1/"})
        assert moved.json()["own"]["key_set"] is False


def test_the_internet_only_over_https(app: Any) -> None:
    from nexki_service import ReferenceService

    with internet(app, ReferenceService()):
        done = operator_puts(app, api="openai", url="http://ai.example.com/v1", model="x")
    assert said(app, done, "ai_https_required")


def test_a_name_on_both_sides_is_refused(app: Any) -> None:
    with resolving(app, {"both.example.com": [PUBLIC, "192.168.1.20"]}):
        done = operator_puts(app, api="openai", url="https://both.example.com/v1", model="x")
    assert said(app, done, "ai_address_mixed")


def test_the_services_own_words_only_from_the_internet(app: Any, service: Any) -> None:
    from nexki_service import ReferenceService

    shared(app, service.base, model="fail")
    local = task(app, "owner", "Please tidy this text up")
    assert said(app, local, "ai_service_failed") and values(app, local).get("said") == ""
    remote = ReferenceService()
    with internet(app, remote):
        shared(app, "https://ai.example.com/v1/", model="fail")
        far = task(app, "owner", "Please tidy this text up")
    assert said(app, far, "ai_service_failed") and "broke down" in str(values(app, far).get("said"))


def test_the_connection_goes_to_the_address_checked(app: Any) -> None:
    """Resolved once per request, and connected to exactly the address checked: a second answer of the name server
    (rebinding) never decides where a request goes."""
    from nexki_service import ReferenceService

    remote = ReferenceService()
    with internet(app, remote) as asked:
        shared(app, "https://ai.example.com/v1/")
        before = asked.count("ai.example.com")
        done = task(app, "owner", "Please tidy this text up")
    assert done.status_code == 200, done.text
    assert asked.count("ai.example.com") == before + 1
    assert remote.seen[-1].via == f"{PUBLIC}:443"


def test_a_connection_that_never_came_is_not_reached_and_a_late_one_is_late(
    app: Any, service: Any, monkeypatch: Any
) -> None:
    """K-6 (0.1.2): a connection that never came about, with time left, is "not reached"; out of time, "too late"."""
    import httpx

    nexki = package(app)
    shared(app, service.base)

    def never(*args: Any, **kwargs: Any) -> Any:
        raise httpx.ConnectTimeout("no connection")

    monkeypatch.setattr(nexki.net, "send", never)
    assert said(app, task(app, "owner", "Please tidy this text up"), "ai_unreachable")

    def late(*args: Any, **kwargs: Any) -> Any:
        raise nexki.net.Late

    monkeypatch.setattr(nexki.net, "send", late)
    assert said(app, task(app, "owner", "Please tidy this text up"), "ai_timeout")

