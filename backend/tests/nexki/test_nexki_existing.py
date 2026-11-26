"""Bestand: an installation updated from the older version notices nothing. The same service, the same model, the same
key (sealed the old way, read in the old place), the same way of setting up; the main switch on where the operator's
service was set up (K3); an own access in the own network on the operator's list (K4); a second start changes
nothing. One test per older form of the app (``older_forms``). Copied unchanged into every app."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from conftest import ADAPTER
from ki_contract import KEY, package
from nexki_service import ReferenceService

FORMS = tuple(ADAPTER.Adapter.older_forms)


@pytest.fixture(params=FORMS or ("none",))
def older(request: Any) -> Iterator[tuple[Any, ReferenceService, str]]:
    if request.param == "none":
        pytest.fail("the app names no older form; an app without AI before carries no Bestand test")
    found = ReferenceService(key=KEY)
    found.serve()
    adapter = ADAPTER.Adapter()
    package(adapter).brake.BRAKE.forget()
    adapter.start_older(request.param, found.base, KEY)
    try:
        yield adapter, found, request.param
    finally:
        adapter.stop()
        found.stop()


def test_the_older_installation_keeps_working(older: tuple[Any, ReferenceService, str]) -> None:
    app, service, form = older
    done = app.manual("owner", "Please tidy this text up")
    assert done.status_code == 200, done.text
    seen = service.seen[-1]
    assert seen.headers.get("authorization") == f"Bearer {KEY}" and seen.body["model"] == "plain"
    view = app.client("operator").get(app.server_prefix).json()
    assert view["enabled"] is True
    if form == "own":
        port = service.base.split(":")[2].split("/")[0]
        assert view["mode"] == "own" and f"127.0.0.1:{port}" in view["hosts"]
        own = app.client("owner").get(app.me_prefix).json()["own"]
        assert own["key_set"] is True and own["model"] == "plain"
    else:
        assert view["mode"] == "shared" and view["key_set"] is True and view["api"] == "openai"


def test_a_second_start_changes_nothing(older: tuple[Any, ReferenceService, str]) -> None:
    app, _, _ = older
    nexki = package(app)
    store = app.store()
    before = app.client("operator").get(app.server_prefix).json()
    assert nexki.settings.adopt(store, app.config()) == []
    assert app.client("operator").get(app.server_prefix).json() == before
