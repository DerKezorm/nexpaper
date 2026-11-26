"""Rights per tool and requests (decisions 3 and 4): a new key may use every tool of its level at once; "ask" keeps
the call as a request for 24 hours (``request_minutes``) that runs exactly as asked, with the rights of the moment it
is allowed; a looking tool is never asked for; the operator's blocks and highest level hold for every key."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from mcp_contract import call, mcp_key, names


def _rights(app: Any, key_id: Any, rights: dict[str, str], role: str = "owner") -> Any:
    return app.client(role).put(f"{app.prefix}/keys/{key_id}/rights", json={"rights": rights})


def _asked(app: Any) -> tuple[Any, str, str, dict[str, Any]]:
    made = mcp_key(app, right=app.config().levels[-1])
    name, args = app.change_call()
    set_ = _rights(app, made["key"]["id"], {name: "ask"})
    assert set_.status_code == 200, set_.text
    return made, made["secret"], name, args


def test_a_new_key_uses_every_tool_of_its_level_at_once(app: Any) -> None:
    secret = mcp_key(app, right=app.config().levels[-1])["secret"]
    name, args = app.change_call()
    answer = call(app, secret, name, args)
    assert not answer["isError"], answer
    assert "request" not in (answer.get("structuredContent") or {})


def test_ask_keeps_the_call_for_24_hours_and_request_status_tells(app: Any) -> None:
    _, secret, name, args = _asked(app)
    waiting = call(app, secret, name, args)["structuredContent"]
    assert waiting["status"] == "waiting"
    rows = app.client("owner").get(f"{app.prefix}/requests", params={"status": "waiting"}).json()
    row = next(found for found in rows if found["id"] == waiting["request"])
    span = datetime.fromisoformat(row["expires_at"]) - datetime.fromisoformat(row["created_at"])
    assert span.total_seconds() == app.config().request_minutes * 60
    assert row["arguments"] == args and row["tool"] == name
    status = call(app, secret, "request_status", {"request": waiting["request"]})["structuredContent"]
    assert status["status"] == "waiting"


def test_allowing_runs_exactly_what_was_asked_and_declining_runs_nothing(app: Any) -> None:
    _, secret, name, args = _asked(app)
    first = call(app, secret, name, args)["structuredContent"]["request"]
    second = call(app, secret, name, args)["structuredContent"]["request"]
    done = app.client("owner").post(f"{app.prefix}/requests/{first}/approve", json={})
    assert done.status_code == 200 and done.json()["status"] == "done", done.text
    assert done.json()["decided_by"]
    declined = app.client("owner").post(f"{app.prefix}/requests/{second}/decline")
    assert declined.json()["status"] == "declined"
    again = app.client("owner").post(f"{app.prefix}/requests/{first}/approve", json={})
    assert again.status_code == 409
    assert app.client("other").post(f"{app.prefix}/requests/{second}/approve", json={}).status_code == 404
    told = call(app, secret, "request_status", {"request": first})["structuredContent"]
    assert told["status"] == "done" and told["result"] is not None


def test_a_request_of_a_key_revoked_meanwhile_fails_when_allowed(app: Any) -> None:
    made, secret, name, args = _asked(app)
    number = call(app, secret, name, args)["structuredContent"]["request"]
    assert app.client("owner").delete(f"{app.keys_prefix}/keys/{made['key']['id']}").status_code == 204
    failed = app.client("owner").post(f"{app.prefix}/requests/{number}/approve", json={})
    assert failed.json()["status"] == "failed"
    assert "no longer possible" in str(failed.json()["result"])


def test_a_looking_tool_is_never_asked_for_and_deny_makes_a_tool_disappear(app: Any) -> None:
    made = mcp_key(app, right=app.config().levels[-1])
    read_name, read_args = app.read_call()
    change_name, _ = app.change_call()
    shown = _rights(app, made["key"]["id"], {read_name: "ask", change_name: "deny"}).json()
    rows = {row["name"]: row for row in shown["tools"]}
    assert rows[read_name]["right"] == "allow" and rows[change_name]["right"] == "deny"
    assert not call(app, made["secret"], read_name, read_args)["isError"]
    assert change_name not in names(app, made["secret"])
    assert _rights(app, made["key"]["id"], {"no_such_tool": "allow"}).status_code == 422
    assert _rights(app, made["key"]["id"], {read_name: "sometimes"}).status_code == 422
    assert _rights(app, made["key"]["id"], {read_name: "allow"}, role="other").status_code == 404


def test_the_operator_blocks_tools_and_caps_the_level_for_every_key(app: Any) -> None:
    secret = mcp_key(app, right=app.config().levels[-1])["secret"]
    change_name, _ = app.change_call()
    operator = app.client("operator")
    blocked = operator.put(f"{app.prefix}/admin", json={"blocked_tools": [change_name]})
    assert blocked.status_code == 200 and change_name in blocked.json()["blocked_tools"]
    assert change_name not in names(app, secret)
    operator.put(f"{app.prefix}/admin", json={"blocked_tools": [], "max_level": app.config().levels[0]})
    assert change_name not in names(app, secret)
    assert "request_status" in names(app, secret)
    assert app.client("owner").put(f"{app.prefix}/admin", json={"blocked_tools": []}).status_code in (401, 403)


def test_a_request_whose_tool_the_operator_blocked_meanwhile_fails_when_allowed(app: Any) -> None:
    _, secret, name, args = _asked(app)
    number = call(app, secret, name, args)["structuredContent"]["request"]
    app.client("operator").put(f"{app.prefix}/admin", json={"blocked_tools": [name]})
    failed = app.client("owner").post(f"{app.prefix}/requests/{number}/approve", json={})
    assert failed.json()["status"] == "failed" and "no longer possible" in str(failed.json()["result"])


def test_a_dangerous_call_always_waits_and_takes_a_second_yes(app: Any) -> None:
    found = app.dangerous_call()
    if found is None:
        pytest.skip("no tool of this app calls anything dangerous")
    name, args = found
    app.client("operator").put(f"{app.prefix}/admin", json={"blocked_tools": []})
    secret = mcp_key(app, right=app.config().levels[-1])["secret"]
    waiting = call(app, secret, name, args)["structuredContent"]
    assert waiting["status"] == "waiting"
    path = f"{app.prefix}/requests/{waiting['request']}/approve"
    once = app.client("owner").post(path, json={})
    assert once.status_code == 409 and app.refusal(once)["code"] == "confirm_needed"
    twice = app.client("owner").post(path, json={"confirm": True})
    assert twice.status_code == 200 and twice.json()["status"] == "done", twice.text


def test_the_app_hears_of_each_new_request_exactly_once(app: Any) -> None:
    """MCP 14 (since 1.1.1): "Ein Programm wartet auf dein Ja" reaches the account on the app's ways (bell, else push or
    mail) through ``notify``: once per new request, never for asking its status, once more when it is decided."""
    _, secret, name, args = _asked(app)
    before = list(app.notified())
    first = call(app, secret, name, args)["structuredContent"]["request"]
    second = call(app, secret, name, args)["structuredContent"]["request"]
    call(app, secret, "request_status", {"request": first})
    app.client("owner").get(f"{app.prefix}/requests", params={"status": "waiting"})
    told = app.notified()[len(before) :]
    assert [(event, str(found)) for event, found in told] == [("waiting", str(first)), ("waiting", str(second))]
    assert app.client("owner").post(f"{app.prefix}/requests/{first}/approve", json={}).status_code == 200
    assert [(event, str(found)) for event, found in app.notified()[len(before) + 2 :]] == [("decided", str(first))]


def test_a_request_changed_after_it_was_asked_never_runs(app: Any) -> None:
    """M-9 (since 1.1.1): what the account allows is what the program asked. Arguments changed in the app's table
    afterwards are refused with 409 ``request_changed``; nothing runs, the request ends as failed."""
    import json

    _, secret, name, args = _asked(app)
    asked = call(app, secret, name, args)["structuredContent"]["request"]
    app.change_arguments(asked, json.dumps({**args, "changed": "after asking"}, sort_keys=True))
    done = app.client("owner").post(f"{app.prefix}/requests/{asked}/approve", json={})
    assert done.status_code == 409 and done.json()["detail"]["code"] == "request_changed", done.text
    told = call(app, secret, "request_status", {"request": asked})["structuredContent"]
    assert told["status"] == "failed"


def test_the_line_of_a_request_is_made_with_the_caller(app: Any) -> None:
    """M-12 (since 1.1.1): ``Tool.describe(arguments, caller)`` gets the caller, so the line for the account speaks its
    language and names its things; a ``describe(arguments)`` of before still works."""
    made, secret, name, args = _asked(app)
    tool = app.config().tool(name)
    seen: list[Any] = []

    def spy(arguments: dict[str, Any], caller: Any) -> str:
        seen.append(caller)
        return f"line for {caller.key_id}"

    kept = tool.describe
    object.__setattr__(tool, "describe", spy)
    try:
        asked = call(app, secret, name, args)["structuredContent"]["request"]
    finally:
        object.__setattr__(tool, "describe", kept)
    assert len(seen) == 1 and str(seen[0].key_id) == str(made["key"]["id"])
    rows = app.client("owner").get(f"{app.prefix}/requests").json()
    assert next(row for row in rows if row["id"] == asked)["summary"] == f"line for {seen[0].key_id}"
    object.__setattr__(tool, "describe", lambda arguments: "line of before")
    try:
        older = call(app, secret, name, args)["structuredContent"]["request"]
    finally:
        object.__setattr__(tool, "describe", kept)
    rows = app.client("owner").get(f"{app.prefix}/requests").json()
    assert next(row for row in rows if row["id"] == older)["summary"] == "line of before"
