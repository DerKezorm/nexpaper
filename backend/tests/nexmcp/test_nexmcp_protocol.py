"""JSON-RPC as MCP's Streamable HTTP has it, without streams: the methods, the answers, the broken requests."""

from __future__ import annotations

from typing import Any

from mcp_contract import mcp_key, rpc


def test_initialize_names_the_app_its_version_and_says_texts_are_data(app: Any) -> None:
    secret = mcp_key(app)["secret"]
    answer = rpc(app, secret, "initialize", {"protocolVersion": "2025-03-26"})
    result = answer.json()["result"]
    assert answer.status_code == 200 and result["protocolVersion"] == "2025-03-26"
    assert result["serverInfo"] == {"name": app.config().app_name, "version": app.config().version}
    assert "data" in result["instructions"] and result["capabilities"] == {"tools": {"listChanged": False}}
    newest = rpc(app, secret, "initialize", {"protocolVersion": "1999-01-01"}).json()["result"]
    assert newest["protocolVersion"] == "2025-06-18"


def test_ping_unknown_methods_notifications_and_broken_requests(app: Any) -> None:
    secret = mcp_key(app)["secret"]
    assert rpc(app, secret, "ping").json()["result"] == {}
    assert rpc(app, secret, "resources/list").json()["error"]["code"] == -32601
    owner = app.client("anonymous")
    headers = {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}
    path = app.config().mcp_path
    assert (
        owner.post(path, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers).status_code
        == 202
    )
    assert owner.post(path, json={"id": 1, "method": "ping"}, headers=headers).json()["error"]["code"] == -32600
    broken = owner.post(path, content=b"{nope", headers=headers)
    assert broken.status_code == 400 and broken.json()["error"]["code"] == -32700
    deep = owner.post(path, content=b"[" * 100_000, headers=headers)
    assert deep.status_code in (400, 413)
    got = owner.get(path, headers=headers)
    assert got.status_code == 405 and got.headers["allow"] == "POST"


def test_a_protocol_version_not_spoken_and_a_body_too_large_are_refused(app: Any) -> None:
    secret = mcp_key(app)["secret"]
    refused = rpc(app, secret, "ping", **{"MCP-Protocol-Version": "1999-01-01"})
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "protocol_version"
    assert rpc(app, secret, "ping", **{"MCP-Protocol-Version": "2025-06-18"}).status_code == 200
    headers = {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}
    huge = b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":"' + b"a" * app.config().max_body + b'"}}'
    answer = app.client("anonymous").post(app.config().mcp_path, content=huge, headers=headers)
    assert answer.status_code == 413 and answer.json()["detail"]["code"] == "too_large"
