"""Requests: a call of a tool set to "ask" (or one the tool calls dangerous) waits for its account (decision 4: 24
hours; nexdeck 10 minutes). Its arguments are fixed as canonical JSON with their SHA-256: what the account sees is what
runs. Allowing runs exactly that, with the rights as they stand at that moment: the key still valid, MCP on, the tool
still there for the key, the account still allowed; otherwise it ends as failed. A dangerous request needs a second
yes. The program learns what came of it with ``request_status``, which every key has."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from . import rights
from .config import AppConfig, Tool
from .errors import McpRefused, ToolError
from .model import DECLINED, DONE, EXPIRED, FAILED, RUNNING, WAITING, AccountId, Request, Store

if TYPE_CHECKING:
    from .protocol import Session

logger = logging.getLogger("nexmcp")


def canonical(arguments: dict[str, Any]) -> str:
    """The arguments as one fixed text: sorted keys, no spaces."""
    return json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def listed(request: Request) -> dict[str, Any]:
    """A request as the account's pages and the program see it."""
    result = None
    if request.result is not None:
        try:
            result = json.loads(request.result)
        except ValueError:
            result = request.result
    return {
        "id": request.id,
        "key_id": request.key_id,
        "key_name": request.key_name,
        "tool": request.tool,
        "arguments": json.loads(request.arguments),
        "summary": request.summary,
        "dangerous": request.dangerous,
        "status": request.status,
        "created_at": request.created_at.isoformat(),
        "expires_at": request.expires_at.isoformat(),
        "decided_at": request.decided_at.isoformat() if request.decided_at else None,
        "decided_by": request.decided_by,
        "result": result,
    }


def ask(session: Session, tool: Tool, args: dict[str, Any], *, dangerous: bool = False) -> dict[str, Any]:
    """Keep the call as a request and tell the program its number; raises ``ToolError`` past the limits."""
    config, store, caller = session.config, session.store, session.caller
    now = session.now()
    text = canonical(args)
    if len(text.encode("utf-8")) > config.max_request_bytes:
        raise ToolError(f"The arguments of a request hold at most {config.max_request_bytes // 1024} kB.")
    store.expire(now)
    if store.count_waiting(caller.account_id) >= config.max_waiting:
        raise ToolError(f"{config.max_waiting} requests wait for this account already. Let it decide first.")
    if store.count_waiting(caller.account_id, caller.key_id) >= config.max_waiting_per_key:
        raise ToolError(
            f"{config.max_waiting_per_key} requests of this key wait already. Let the account decide first."
        )
    summary = ""
    if tool.describe is not None:
        summary = str(tool.describe(dict(args)) or "")[:300]
    made = store.add_request(
        Request(
            id=0,
            account_id=caller.account_id,
            key_id=caller.key_id,
            key_name=caller.key_name,
            tool=tool.name,
            arguments=text,
            digest=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            status=WAITING,
            created_at=now,
            expires_at=now + timedelta(minutes=config.request_minutes),
            summary=summary,
            dangerous=dangerous,
        )
    )
    store.commit()
    logger.info("MCP request made request_id=%s tool=%s key_id=%s", made.id, tool.name, caller.key_id)
    if session.notify is not None:
        session.notify("waiting", made)
    hours = config.request_minutes / 60
    span = f"{config.request_minutes} minutes" if config.request_minutes < 120 else f"{hours:g} hours"
    return {
        "request": made.id,
        "status": WAITING,
        "expires_at": made.expires_at.isoformat(),
        "note": f"Waiting for approval in {config.app_name}, request {made.id}. It runs out in {span}. "
        f"Ask request_status with request {made.id} to learn what came of it.",
    }


def _status(context: Any, args: dict[str, Any]) -> dict[str, Any]:
    """The tool ``request_status``: only the key's own requests."""
    store: Store = context.store
    store.expire(datetime.now(UTC))
    store.commit()
    found = store.request(args["request"])
    if found is None or str(found.key_id) != str(context.caller.key_id):
        raise ToolError("No such request.")
    shown = listed(found)
    return {key: shown[key] for key in ("id", "tool", "status", "expires_at", "decided_at", "result")}


def STATUS_TOOL(config: AppConfig) -> Tool:  # noqa: N802 (a fixed tool, made per app for its lowest level)
    return Tool(
        name="request_status",
        group="read",
        level=config.levels[0],
        description=f"How a request stands that waits for approval in {config.app_name} (a tool set to 'ask' gives "
        "its number): waiting, done (with the tool's answer), failed, declined or expired.",
        input_schema={
            "type": "object",
            "properties": {"request": {"type": "integer", "minimum": 1}},
            "required": ["request"],
            "additionalProperties": False,
        },
        run=_status,
        always=True,
    )


# --- the account answers ------------------------------------------------------------------------------------------


def _own(store: Store, account_id: AccountId, request_id: int | str, now: datetime) -> Request:
    store.expire(now)
    found = store.request(request_id)
    if found is None or str(found.account_id) != str(account_id):
        raise McpRefused("request_unknown")
    if found.status == EXPIRED:
        raise McpRefused("request_expired")
    if found.status != WAITING:
        raise McpRefused("request_decided")
    return found


def decline(
    store: Store,
    account_id: AccountId,
    account_name: str,
    request_id: int | str,
    *,
    now: datetime | None = None,
    notify: Callable[[str, Any], None] | None = None,
) -> Request:
    moment = now or datetime.now(UTC)
    found = _own(store, account_id, request_id, moment)
    if not store.claim(found.id, DECLINED, now=moment, by=account_name):
        raise McpRefused("request_decided")
    store.commit()
    logger.info("MCP request declined request_id=%s", found.id)
    done = store.request(found.id)
    assert done is not None
    if notify is not None:
        notify("decided", done)
    return done


def _no_longer(why: str) -> str:
    return json.dumps({"message": f"This is no longer possible: {why}."})


async def approve(
    config: AppConfig,
    store: Store,
    account_id: AccountId,
    account_name: str,
    request_id: int | str,
    *,
    confirm: bool = False,
    now: datetime | None = None,
    notify: Callable[[str, Any], None] | None = None,
) -> Request:
    """Allow a request: run exactly its arguments with the rights of now. Raises ``McpRefused`` for a request that
    is not the account's, decided, run out, or dangerous without ``confirm``."""
    from .protocol import Context, run, settings  # noqa: PLC0415 (protocol imports this module)

    moment = now or datetime.now(UTC)
    found = _own(store, account_id, request_id, moment)
    if found.dangerous and not confirm:
        raise McpRefused("confirm_needed")
    if not store.claim(found.id, RUNNING, now=moment, by=account_name):
        raise McpRefused("request_decided")
    store.commit()
    tool = config.tool(found.tool)
    caller = store.caller_of_key(found.key_id)
    blocked, max_level = settings(config, store)
    programs = store.setting("programs")
    if caller is None:
        result, status = _no_longer("the key is gone or may not work now"), FAILED
    elif not store.mcp_on() or (caller.program and programs is False):
        result, status = _no_longer("MCP is switched off"), FAILED
    elif not caller.ai_allowed:
        result, status = _no_longer("the account may not use AI"), FAILED
    elif tool is None or rights.right(config, caller, tool, blocked, max_level) is None:
        result, status = _no_longer("the tool is not there for the key any more"), FAILED
    else:
        context = Context(caller=caller, store=store, config=config, approved_by=account_name, request_id=found.id)
        try:
            answer = await run(tool, context, json.loads(found.arguments))
            result, status = json.dumps(answer, default=str, ensure_ascii=False), DONE
        except ToolError as exc:
            result, status = json.dumps({"message": str(exc) or "Not possible."}), FAILED
        except LookupError:
            result, status = json.dumps({"message": "Not found."}), FAILED
        except Exception as exc:
            from .protocol import _refused  # noqa: PLC0415

            refused = _refused(exc)
            result, status = json.dumps({"message": refused["content"][0]["text"]}), FAILED
    store.finish(found.id, status, result, datetime.now(UTC))
    store.commit()
    logger.info("MCP request approved request_id=%s status=%s", found.id, status)
    done = store.request(found.id)
    assert done is not None
    if notify is not None:
        notify("decided", done)
    return done
