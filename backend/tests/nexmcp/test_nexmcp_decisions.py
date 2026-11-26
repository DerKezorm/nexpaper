"""The decisions of the plan that are the app's to keep (Entwurf MCP-Modul, Entscheidungen 5, 6, 10, 11, 12)."""

from __future__ import annotations

from typing import Any

import pytest
from mcp_contract import connect, mcp_key, rpc


def test_mcp_is_off_on_a_fresh_installation(fresh: Any) -> None:
    """Decision 5: a new installation starts with MCP off; the operator switches it on."""
    switches = fresh.client("operator").get(f"{fresh.keys_prefix}/interfaces").json()
    assert switches["mcp"] is False
    assert rpc(fresh, "anything", "ping").status_code == fresh.config().off_status


def test_an_installation_that_had_mcp_on_keeps_it(older: Any) -> None:
    """Decision 5: the update writes the old default down before the default becomes off."""
    if not older.older_had_mcp_on:
        pytest.skip("the older version had MCP off from the start, or no MCP")
    assert older.client("operator").get(f"{older.keys_prefix}/interfaces").json()["mcp"] is True


def test_programs_connect_and_mcp_keys_are_made_by_hand_in_every_app(app: Any) -> None:
    """Decisions 6, 11, 12: OAuth and MCP keys by hand; an API key offers no "also for AI tools" any more."""
    keys = app.keys_config()
    mcp_kind = keys.kind("mcp")
    assert keys.programs and mcp_kind is not None and mcp_kind.creatable and mcp_kind.editable
    api = keys.kind("api")
    if api is not None and "mcp" in api.options:
        assert "mcp" in api.retired_options
    assert rpc(app, mcp_key(app)["secret"], "ping").status_code == 200
    _, tokens = connect(app)
    assert rpc(app, tokens["access_token"], "ping").status_code == 200


def test_without_ai_the_accounts_mcp_keys_and_programs_rest(app: Any) -> None:
    """Decision 10: the operator takes AI from the account; keys and programs rest (401) and work again."""
    if not app.has_ai:
        pytest.skip("this app has no 'AI allowed' per account")
    secret = mcp_key(app)["secret"]
    client_id, tokens = connect(app)
    app.take_ai("owner")
    for token in (secret, tokens["access_token"]):
        answer = rpc(app, token, "ping")
        assert answer.status_code == 401 and answer.json()["detail"]["code"] == "ai_rests"
    shown = app.client("owner").get(
        f"{app.config().oauth_prefix}/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "http://127.0.0.1:33418/callback",
            "code_challenge": "a" * 43,
            "code_challenge_method": "S256",
        },
    )
    assert shown.json()["ai_allowed"] is False
    app.give_ai("owner")
    assert rpc(app, secret, "ping").status_code == 200
    assert rpc(app, tokens["access_token"], "ping").status_code == 200
