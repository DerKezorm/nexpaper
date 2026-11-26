"""MCP over HTTP as JSON-RPC 2.0 ("Streamable HTTP" without streams): one message in, its answer out. The walls of the
endpoint are in ``api.py``; here the methods, the calls of tools and their answers.

A call goes: the tool must exist for the key (``rights.right``), the arguments must fit (``arguments.check``), then
either it waits for the account (right "ask", or the tool calls this call dangerous: ``requests.ask``) or it runs
with the key's account (``Context``). Every failure of a tool is its answer with ``isError``, never a 500."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import arguments, requests, rights
from .brake import BRAKE
from .config import ASK, PROTOCOL_VERSIONS, AppConfig, Tool
from .errors import ToolError
from .model import Caller, Store

logger = logging.getLogger("nexmcp")


@dataclass
class Context:
    """What a tool gets besides its arguments: who calls (``caller.account`` is the app's own object), the store of
    this request, and, for a request the account allowed, who allowed it."""

    caller: Caller
    store: Store
    config: AppConfig
    #: One identity per call (nexlore: an MCP write never holds a lock or passes for an editor's tab).
    client: str = field(default_factory=lambda: secrets.token_hex(4))
    approved_by: str = ""
    request_id: int | str | None = None


@dataclass
class Session:
    """One request to the endpoint: the app's MCP, its store, the caller, the operator's settings read once."""

    config: AppConfig
    store: Store
    caller: Caller
    blocked: tuple[str, ...] = ()
    max_level: str | None = None
    notify: Callable[[str, Any], None] | None = None
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def context(self, **more: Any) -> Context:
        return Context(caller=self.caller, store=self.store, config=self.config, **more)


def settings(config: AppConfig, store: Store) -> tuple[tuple[str, ...], str | None]:
    """The tools the operator blocked (default: the app's ``blocked_by_default``) and the highest level."""
    blocked = store.setting("blocked_tools")
    names = tuple(name for name in blocked if isinstance(name, str)) if isinstance(blocked, list) else None
    found = store.setting("max_level")
    return (config.blocked_by_default if names is None else names), (found if found in config.levels else None)


def tool_result(value: Any, failed: bool = False) -> dict[str, Any]:
    """A tool's answer: the text (JSON for data), the data itself where it is an object, ``isError``."""
    plain = json.loads(json.dumps(value, default=str, ensure_ascii=False))
    text = plain if isinstance(plain, str) else json.dumps(plain, ensure_ascii=False)
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": failed}
    if not failed and isinstance(plain, dict):
        result["structuredContent"] = plain
    return result


def listed(tool: Tool) -> dict[str, Any]:
    """A tool as ``tools/list`` gives it, with the hints a program may use to ask its person before a change."""
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": dict(tool.input_schema),
        "annotations": {
            "readOnlyHint": tool.looks_only,
            "destructiveHint": tool.group == "risky",
            "openWorldHint": False,
        },
    }


async def run(tool: Tool, context: Context, args: dict[str, Any]) -> Any:
    """Run a tool; a plain function goes to a worker thread, so a slow one does not hold up the server."""
    if inspect.iscoroutinefunction(tool.run):
        return await tool.run(context, dict(args))
    found = await asyncio.to_thread(tool.run, context, dict(args))
    return await found if inspect.isawaitable(found) else found


async def call_tool(session: Session, name: Any, args: Any) -> dict[str, Any]:
    config, caller = session.config, session.caller
    tool = config.tool(name) if isinstance(name, str) else None
    allowed = rights.right(config, caller, tool, session.blocked, session.max_level) if tool else None
    if tool is None or allowed is None:
        # A tool above the key's level, denied, blocked or for operators only is as unknown as one that is not there.
        return tool_result(f"No tool called {str(name)[:100]!r}.", failed=True)
    problem = arguments.check(tool.input_schema, args)
    if problem:
        return tool_result(problem, failed=True)
    context = session.context()
    try:
        dangerous = bool(tool.dangerous(context, dict(args))) if tool.dangerous else False
        if allowed == ASK or dangerous:
            return tool_result(requests.ask(session, tool, args, dangerous=dangerous))
        if tool.per_minute is not None and not BRAKE.take(f"tool:{caller.key_id}:{tool.name}", tool.per_minute):
            return tool_result(f"{tool.name} was called too often with this key. Wait a minute.", failed=True)
        logger.info("MCP tool called tool=%s key_id=%s", tool.name, caller.key_id)
        return tool_result(await run(tool, context, args))
    except ToolError as exc:
        return tool_result(str(exc) or "Not possible.", failed=True)
    except LookupError:
        return tool_result("Not found.", failed=True)
    except Exception as exc:
        # The app's routes refuse with an exception carrying a status and a detail (FastAPI's HTTPException): the
        # same "Not found." for what the account may not read, the route's own sentence for the rest.
        return _refused(exc)


def _refused(exc: Exception) -> dict[str, Any]:
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        raise exc
    if status == 404:
        return tool_result("Not found.", failed=True)
    detail = getattr(exc, "detail", None)
    text = detail.get("message") if isinstance(detail, dict) else detail
    return tool_result(str(text) if isinstance(text, str) and text else "Not possible.", failed=True)


def _error(message_id: Any, code: int, text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": text}}


async def handle(message: Any, session: Session) -> dict[str, Any] | None:
    """One JSON-RPC message: its answer, or ``None`` for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid request.")
    method = message["method"]
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if "id" not in message:
        return None
    message_id = message["id"]
    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": session.config.app_name, "version": session.config.version},
                "instructions": session.config.instructions,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": message_id, "result": {}}
    if method == "tools/list":
        tools = rights.visible(session.config, session.caller, session.blocked, session.max_level)
        return {"jsonrpc": "2.0", "id": message_id, "result": {"tools": [listed(tool) for tool in tools]}}
    if method == "tools/call":
        result = await call_tool(session, params.get("name"), params.get("arguments", {}))
        return {"jsonrpc": "2.0", "id": message_id, "result": result}
    return _error(message_id, -32601, "Method not found.")
