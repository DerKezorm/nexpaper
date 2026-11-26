"""``tools/list`` and ``tools/call``: a key sees what its level, its extras and the operator allow, never more than
its account; a tool it does not have answers like one that is not there; arguments are checked before anything runs."""

from __future__ import annotations

from typing import Any

import pytest
from mcp_contract import call, mcp_key, names, rpc


def _levels(app: Any) -> tuple[str, str]:
    levels = app.config().levels
    return levels[0], levels[-1]


def test_a_key_of_the_lowest_level_sees_only_its_tools_and_request_status(app: Any) -> None:
    lowest, _ = _levels(app)
    seen = names(app, mcp_key(app, right=lowest)["secret"])
    config = app.config()
    expected = {
        tool.name for tool in config.tools if tool.level == lowest and tool.needs is None and not tool.admin_only
    }
    assert seen == (expected - set(config.blocked_by_default)) | {"request_status"}


def test_a_tool_the_key_does_not_have_answers_like_one_that_is_not_there(app: Any) -> None:
    lowest, _ = _levels(app)
    secret = mcp_key(app, right=lowest)["secret"]
    name, args = app.change_call()
    above = call(app, secret, name, args)
    nothing = call(app, secret, "no_such_tool", {})
    assert above["isError"] and nothing["isError"]
    assert above["content"][0]["text"] == f"No tool called {name!r}."
    assert nothing["content"][0]["text"] == "No tool called 'no_such_tool'."


def test_what_the_account_may_not_read_answers_not_found(app: Any) -> None:
    secret = mcp_key(app)["secret"]
    name, args = app.foreign_call()
    answer = call(app, secret, name, args)
    assert answer["isError"] and answer["content"][0]["text"] == "Not found."
    name, args = app.read_call()
    found = call(app, secret, name, args)
    assert not found["isError"], found


def test_arguments_are_checked_before_anything_runs(app: Any) -> None:
    secret = mcp_key(app)["secret"]
    name, args = app.read_call()
    tool = app.config().tool(name)
    required = list(tool.input_schema.get("required") or [])
    if required:
        missing = call(app, secret, name, {key: value for key, value in args.items() if key != required[0]})
        assert missing["isError"] and missing["content"][0]["text"] == f"'{required[0]}' is missing."
    deep: Any = "x"
    for _ in range(30):
        deep = [deep]
    nested = call(app, secret, name, {**args, required[0] if required else "x": deep})
    assert nested["isError"]
    assert call(app, secret, name, "not an object")["isError"]  # type: ignore[arg-type]


def test_a_tool_that_needs_an_extra_is_there_only_with_it(app: Any) -> None:
    """Decisions 2 and 9: "Mailtext lesen", "Einträge lesen": off from the start, a tool that needs it is not there."""
    config = app.config()
    needing = [tool for tool in config.tools if tool.needs]
    if not needing:
        pytest.skip("no tool of this app needs an extra")
    without = names(app, mcp_key(app)["secret"])
    extras = {tool.needs: True for tool in needing}
    with_them = names(app, mcp_key(app, options=extras)["secret"])
    for tool in needing:
        assert tool.name not in without and tool.name in with_them


def test_tools_list_marks_what_only_looks_and_what_is_risky(app: Any) -> None:
    secret = mcp_key(app)["secret"]
    listed = {tool["name"]: tool for tool in rpc(app, secret, "tools/list").json()["result"]["tools"]}
    for name, tool in listed.items():
        known = app.config().tool(name)
        assert tool["annotations"]["readOnlyHint"] is (known.group in ("read", "admin"))
        assert tool["annotations"]["destructiveHint"] is (known.group == "risky")
        assert tool["inputSchema"]["type"] == "object"
