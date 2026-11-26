"""The walls of the endpoint in their fixed order, with the status and code each app answered so far."""

from __future__ import annotations

from typing import Any

from mcp_contract import mcp_key, rpc, switch_mcp


def test_a_web_page_is_turned_away_before_anything_else(app: Any) -> None:
    secret = mcp_key(app)["secret"]
    switch_mcp(app, False)
    answer = rpc(app, secret, "ping", Origin="https://evil.example.com")
    assert answer.status_code == 403 and answer.json()["detail"]["code"] == "origin_refused"


def test_switched_off_mcp_answers_as_the_app_answered(app: Any) -> None:
    secret = mcp_key(app)["secret"]
    switch_mcp(app, False)
    answer = rpc(app, secret, "ping")
    assert answer.status_code == app.config().off_status
    assert answer.json()["detail"]["code"] == app.config().off_code
    switch_mcp(app, True)
    assert rpc(app, secret, "ping").status_code == 200


def test_no_valid_key_gets_401_with_the_apps_code_and_the_way_to_connect(app: Any) -> None:
    answer = rpc(app, "wrong", "ping")
    assert answer.status_code == 401 and answer.json()["detail"]["code"] == app.config().invalid_code
    assert "resource_metadata=" in answer.headers["www-authenticate"]
    assert rpc(app, None, "ping").status_code == 401


def test_wrong_keys_from_one_sender_wait(app: Any, nexmcp: Any) -> None:
    for _ in range(app.config().free_wrong_keys):
        assert rpc(app, "wrong", "ping").status_code == 401
    answer = rpc(app, "wrong", "ping")
    assert answer.status_code == 429 and answer.json()["detail"]["code"] == "too_many_attempts"
    assert int(answer.headers["retry-after"]) > 0


def test_a_key_past_its_rate_is_slowed(app: Any) -> None:
    secret = mcp_key(app)["secret"]
    for _ in range(app.config().per_minute):
        assert rpc(app, secret, "ping").status_code == 200
    answer = rpc(app, secret, "ping")
    assert answer.status_code == 429 and answer.headers["retry-after"] == "60"


def test_the_browser_session_counts_for_nothing(app: Any) -> None:
    answer = app.client("owner").post(app.config().mcp_path, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert answer.status_code == 401
