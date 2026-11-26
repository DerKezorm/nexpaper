"""Every key and every connected program of the older version keeps working after the update, on the same routes
(nothing is hashed again, no row moves); a connected program refreshes at the token endpoint it knows."""

from __future__ import annotations

from typing import Any

import pytest
from mcp_contract import refresh, rpc


def test_every_form_of_key_that_opened_mcp_before_still_does(older: Any) -> None:
    specs = older.legacy_keys()
    if not specs:
        pytest.skip("this app had no MCP before")
    for spec in specs:
        secret = older.make_legacy(spec)
        answer = rpc(older, secret, "initialize", {"protocolVersion": "2025-06-18"})
        assert answer.status_code == 200, (spec.label, answer.text)
        tools = rpc(older, secret, "tools/list").json()["result"]["tools"]
        assert tools, spec.label


def test_a_program_connected_before_refreshes_and_its_copies_still_end_it(older: Any) -> None:
    program = older.legacy_program()
    if program is None:
        pytest.skip("this app had no OAuth before")
    renewed = refresh(older, program.client_id, program.refresh_token)
    assert renewed.status_code == 200, renewed.text
    assert rpc(older, renewed.json()["access_token"], "ping").status_code == 200
    copy = refresh(older, program.client_id, program.refresh_token)
    assert copy.status_code == 400
    assert rpc(older, renewed.json()["access_token"], "ping").status_code == 401
