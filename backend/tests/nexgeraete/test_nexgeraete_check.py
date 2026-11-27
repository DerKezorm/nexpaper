"""Knowing a device again (G12, G13, G26, G27): every reason of a refusal with its code, at the app's own device
route; a blocked or deleted account's devices rest and come back without pairing anew; one deleted for good is gone;
a year unused ends a device; the operator's switch; a device's key opens no browser route; ``X-Nex-App`` notes model,
system and version. Red here means a device hears the wrong reason, or keeps access it must not have."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from geraete_contract import NEW, auth, code_of, listed, new_device


def _reason(app: Any, token: str | None) -> tuple[int, str]:
    answer = app.probe(token, NEW)
    return answer.status_code, code_of(answer) if answer.status_code >= 400 else ""


def test_an_unknown_key_and_none_hear_disconnected(app: Any, config: Any) -> None:
    assert _reason(app, None) == (401, "device_disconnected")
    assert _reason(app, config.token_prefix + "x" * 43) == (401, "device_disconnected")
    assert _reason(app, "something-else") == (401, "device_disconnected")


def test_a_disconnected_device_hears_so(app: Any) -> None:
    token = new_device(app)
    assert _reason(app, token) == (200, "")
    row = listed(app)[0]
    assert app.client("owner").delete(f"{app.browser_prefix}/app-devices/{row['id']}").status_code == 204
    assert _reason(app, token) == (401, "device_disconnected")


def test_a_blocked_account_s_devices_rest_and_come_back_after_unblocking(app: Any) -> None:
    token = new_device(app)
    app.block()
    assert _reason(app, token) == (401, "account_blocked")
    app.unblock()
    assert _reason(app, token) == (200, ""), "G26: no pairing anew after unblocking"


def test_a_deleted_account_s_devices_rest_and_come_back_when_restored(app: Any) -> None:
    token = new_device(app)
    app.remove()
    assert _reason(app, token) == (401, "account_blocked")
    app.restore()
    assert _reason(app, token) == (200, "")


def test_an_account_deleted_for_good_leaves_its_devices_disconnected(app: Any) -> None:
    token = new_device(app)
    app.purge()
    assert _reason(app, token) == (401, "device_disconnected")


def test_a_missing_second_factor_lets_devices_rest(app: Any) -> None:
    token = new_device(app)
    other = new_device(app, "other")
    app.owe_factor("owner")
    assert _reason(app, token) == (401, "second_factor_required")
    assert _reason(app, other) == (200, "")


def test_the_app_switched_off_answers_403_and_on_again_works(app: Any) -> None:
    token = new_device(app)
    app.switch("app", False)
    assert _reason(app, token) == (403, "app_disabled")
    app.switch("app", True)
    assert _reason(app, token) == (200, "")


def test_a_device_s_key_opens_no_browser_route(app: Any) -> None:
    token = new_device(app)
    client = app.device_client()
    for method, path in (("get", "/app-devices"), ("post", "/app-pairing"), ("delete", "/app-devices"),
                         ("post", "/app-connect")):
        answer = getattr(client, method)(f"{app.browser_prefix}{path}", headers=auth(token))
        assert answer.status_code == 403 and code_of(answer) == "browser_only", (method, path)
    assert len(listed(app)) == 1


def test_the_header_of_the_new_apps_notes_model_system_and_version(app: Any) -> None:
    token = new_device(app)
    row = listed(app)[0]
    assert (row["model"], row["system"], row["app_version"]) == ("iPhone 16 Pro", "iOS 18.1", "2.1.0")
    app.travel(timedelta(minutes=2))
    app.probe(token, {"X-Nex-App": "sample-ios/2.2.0 (iPad Air; iPadOS 18.2)"})
    row = listed(app)[0]
    assert (row["model"], row["system"], row["app_version"]) == ("iPad Air", "iPadOS 18.2", "2.2.0")
    assert row["last_seen_at"] is not None


def test_a_year_unused_ends_a_device_at_its_next_call_and_in_the_daily_run(app: Any, config: Any) -> None:
    token = new_device(app)
    kept = new_device(app, name="used")
    swept = new_device(app, name="swept")
    app.travel(timedelta(days=config.idle_days - 1))
    assert _reason(app, kept) == (200, "")
    app.travel(timedelta(days=2))
    assert _reason(app, token) == (401, "device_disconnected")
    assert app.sweep() == 1
    assert [row["name"] for row in listed(app)] == ["used"]
    assert _reason(app, swept) == (401, "device_disconnected")
