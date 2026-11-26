"""The routes of the module (the only part that needs FastAPI):

``POST <mcp_path>``                                   MCP (JSON-RPC over HTTP), the walls in their fixed order
``GET  <mcp_path>``                                   405: no stream, every answer comes with its request
``GET  /.well-known/oauth-protected-resource[<mcp_path>]``, ``GET /.well-known/oauth-authorization-server``
``POST <oauth_prefix>/register``, ``/token``, ``/revoke`` the program's side of OAuth
``GET  <oauth_prefix>/authorize``                     what the consent page shows (signed-in account)
``POST <oauth_prefix>/authorize``                     the account's answer: ``{"redirect": …}``
``GET  <prefix>/tools``                               every tool with group, level, default, blocked
``GET|PUT <prefix>/keys/{key}/rights``                rights per tool of an own key or program
``GET  <prefix>/requests``, ``GET <prefix>/requests/{id}``, ``POST …/approve``, ``POST …/decline``
``GET|PUT <prefix>/admin``                            the operator: programs, highest level, blocked tools

The walls of ``POST <mcp_path>``, in this order: an ``Origin`` (403 ``origin_refused``: browsers send one, programs do
not, so no web page uses a key and DNS rebinding goes nowhere); MCP switched off (the app's status and code); too many
wrong keys from this sender (429 with ``Retry-After``); no valid key (401 with the app's code and ``WWW-Authenticate``
naming the metadata while programs may connect), a key of a resting program or of an account without AI (401); the
key's rate (429 ``slow_down``); an unknown ``MCP-Protocol-Version`` (400); a body over ``max_body`` (413); JSON that
does not parse (400, -32700). The session cookie counts for nothing here."""

# No ``from __future__ import annotations``: the routes name dependencies made inside ``router()``.
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from . import oauth, requests, rights
from .brake import BRAKE, sender_of
from .config import PROTOCOL_VERSIONS, RIGHTS, AppConfig, all_tools
from .errors import CODES, McpRefused, OAuthError
from .model import STATES
from .protocol import Session, handle, settings

logger = logging.getLogger("nexmcp")

#: The largest form a program sends to the token endpoint.
MAX_FORM = 16 * 1024


def _now() -> datetime:
    return datetime.now(UTC)


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header[:7].lower() != "bearer ":
        return None
    return header[7:].strip() or None


def wall(code: str, *, status: int | None = None, headers: dict[str, str] | None = None) -> JSONResponse:
    """A refusal of the endpoint in the form every app answered: ``{"detail": {"code", "message"}}``."""
    known_status, message = CODES[code]
    return JSONResponse(
        {"detail": {"code": code, "message": message}}, status_code=status or known_status, headers=headers
    )


def _rpc_error(code: int, text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": text}}


async def _limited_body(request: Request, limit: int) -> bytes | None:
    taken = b""
    async for chunk in request.stream():
        taken += chunk
        if len(taken) > limit:
            return None
    return taken


async def _form(request: Request) -> dict[str, str]:
    body = await _limited_body(request, MAX_FORM)
    if body is None:
        raise OAuthError("invalid_request", "The request is too large.", 413)
    try:
        return dict(parse_qsl(body.decode("utf-8"), keep_blank_values=True))
    except (UnicodeDecodeError, ValueError):
        raise OAuthError("invalid_request", "The body must be a form.") from None


def _oauth_answer(body: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


def router(
    *,
    config: AppConfig,
    store: Callable[..., Any],
    account: Callable[..., Any],
    operator: Callable[..., Any],
    account_id: Callable[[Any], Any] = lambda signed_in: signed_in.id,
    account_name: Callable[[Any], str] = lambda signed_in: str(signed_in.name),
    address: Callable[[Request], str] | None = None,
    sender: Callable[[Request], str] | None = None,
    prefix: str = "/api/connections/mcp",
    error: Callable[[McpRefused], Exception] | None = None,
    notify: Callable[[str, Any], None] | None = None,
    tags: list[str] | None = None,
) -> APIRouter:
    """The routes. ``store``: a dependency giving the app's ``nexmcp.Store`` for this request. ``account``: the
    dependency of a signed-in browser session with a password or a provider (never a key, never a device);
    ``operator``: the app's dependency for operators. ``address(request)``: the app's public address (its setting,
    else the request's through trusted proxies only). ``sender(request)``: the sender's address as the app reads it
    behind its trusted proxies. ``notify(event, request)``: ``waiting`` and ``decided``, for the app's bell and its
    channels. ``error``: the app's form of a refusal on its own pages."""
    routes = APIRouter(tags=tags or ["mcp"])
    base_of = address or (lambda request: str(request.base_url).rstrip("/"))
    sender_ip = sender or (lambda request: request.client.host if request.client else "")
    Data = Annotated[Any, Depends(store)]
    Own = Annotated[Any, Depends(account)]

    def refuse(refusal: McpRefused) -> Exception:
        if error is not None:
            return error(refusal)
        return HTTPException(status_code=refusal.status, detail=refusal.as_dict())

    # --- the endpoint -------------------------------------------------------------------------------------------

    @routes.post(config.mcp_path, summary="MCP (JSON-RPC over HTTP) with a key in Authorization: Bearer")
    async def endpoint(request: Request, data: Data) -> Response:
        if request.headers.get("origin"):
            return wall("origin_refused")
        if not data.mcp_on():
            return wall(config.off_code, status=config.off_status)
        who = "mcp:" + sender_of(sender_ip(request))
        wait = BRAKE.wait_seconds(who, config.free_wrong_keys)
        if wait:
            return wall("too_many_attempts", headers={"Retry-After": str(wait)})
        token = _bearer(request)
        caller = data.caller(token) if token else None
        if caller is None:
            BRAKE.failed(who)
            base = base_of(request)
            return wall(config.invalid_code, headers={"WWW-Authenticate": oauth.challenge(base, config, data)})
        if caller.program and data.setting("programs") is False:
            return wall(config.invalid_code, headers={"WWW-Authenticate": "Bearer"})
        if not caller.ai_allowed:
            return wall("ai_rests", headers={"WWW-Authenticate": "Bearer"})
        if not BRAKE.take(f"key:{caller.key_id}", config.per_minute):
            return wall("slow_down", headers={"Retry-After": "60"})
        asked = request.headers.get("mcp-protocol-version")
        if asked is not None and asked not in PROTOCOL_VERSIONS:
            return wall("protocol_version")
        body = await _limited_body(request, config.max_body)
        if body is None:
            return wall("too_large")
        try:
            message = json.loads(body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            # RecursionError: JSON nested deeper than Python's stack, sent to break the server.
            return JSONResponse(_rpc_error(-32700, "Parse error."), status_code=400)
        blocked, max_level = settings(config, data)
        session = Session(config=config, store=data, caller=caller, blocked=blocked, max_level=max_level, notify=notify)
        answer = await handle(message, session)
        if answer is None:
            return Response(status_code=202)
        return JSONResponse(answer)

    @routes.get(config.mcp_path, include_in_schema=False)
    def no_stream() -> Response:
        return Response(status_code=405, headers={"Allow": "POST"})

    # --- OAuth: the program's side ------------------------------------------------------------------------------

    def _closed() -> JSONResponse:
        return wall("not_found")

    def resource_metadata(request: Request, data: Data) -> JSONResponse:
        if not oauth.programs_open(config, data):
            return _closed()
        return JSONResponse(oauth.resource_metadata(base_of(request), config), headers={"Cache-Control": "no-store"})

    routes.add_api_route("/.well-known/oauth-protected-resource", resource_metadata, include_in_schema=False)
    routes.add_api_route(
        f"/.well-known/oauth-protected-resource{config.mcp_path}", resource_metadata, include_in_schema=False
    )

    @routes.get("/.well-known/oauth-authorization-server", include_in_schema=False)
    def server_metadata(request: Request, data: Data) -> JSONResponse:
        if not oauth.programs_open(config, data):
            return _closed()
        return JSONResponse(oauth.server_metadata(base_of(request), config), headers={"Cache-Control": "no-store"})

    @routes.post(f"{config.oauth_prefix}/register", include_in_schema=False)
    async def register(request: Request, data: Data) -> JSONResponse:
        if not oauth.programs_open(config, data):
            return _closed()
        try:
            body = json.loads(await _limited_body(request, MAX_FORM) or b"null")
            return _oauth_answer(oauth.register(data, config, body, sender_ip(request), _now()), 201)
        except ValueError:
            return _oauth_answer({"error": "invalid_client_metadata", "error_description": "JSON, please."}, 400)
        except OAuthError as refusal:
            return _oauth_answer(refusal.as_dict(), refusal.status)

    @routes.post(f"{config.oauth_prefix}/token", include_in_schema=False)
    async def token(request: Request, data: Data) -> JSONResponse:
        try:
            form = await _form(request)
            return _oauth_answer(oauth.token(data, config, form, base_of(request), _now()))
        except OAuthError as refusal:
            return _oauth_answer(refusal.as_dict(), refusal.status)

    @routes.post(f"{config.oauth_prefix}/revoke", include_in_schema=False)
    async def revoke(request: Request, data: Data) -> JSONResponse:
        try:
            form = await _form(request)
        except OAuthError as refusal:
            return _oauth_answer(refusal.as_dict(), refusal.status)
        if oauth.programs_open(config, data):
            oauth.revoke(data, config, form)
        # RFC 7009, 2.2: the same answer for a token that was never there.
        return _oauth_answer({})

    # --- OAuth: the account's side ------------------------------------------------------------------------------

    @routes.get(f"{config.oauth_prefix}/authorize", summary="What a program asks to sign in for")
    def consent_info(
        request: Request,
        signed_in: Own,
        data: Data,
        client_id: Annotated[str, Query(max_length=200)] = "",
        redirect_uri: Annotated[str, Query(max_length=2048)] = "",
        response_type: Annotated[str, Query(max_length=40)] = "code",
        code_challenge: Annotated[str, Query(max_length=200)] = "",
        code_challenge_method: Annotated[str, Query(max_length=20)] = "",
        state: Annotated[str, Query(max_length=1000)] = "",
        resource: Annotated[str, Query(max_length=2048)] = "",
        scope: Annotated[str, Query(max_length=200)] = "",
    ) -> dict:
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": response_type,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "state": state,
            "resource": resource,
        }
        try:
            return oauth.consent_info(data, config, account_id(signed_in), params, base_of(request))
        except McpRefused as refusal:
            raise refuse(refusal) from None

    @routes.post(f"{config.oauth_prefix}/authorize", summary="Agree to a program's sign-in, or turn it down")
    def consent(request: Request, signed_in: Own, data: Data, body: Annotated[dict, Body()]) -> dict:
        try:
            redirect = oauth.consent(data, config, account_id(signed_in), body, base_of(request), _now())
        except McpRefused as refusal:
            data.rollback()
            raise refuse(refusal) from None
        return {"redirect": redirect}

    # --- the account's pages ------------------------------------------------------------------------------------

    def _tool_rows(data: Any) -> list[dict]:
        blocked, _ = settings(config, data)
        return [
            {
                "name": tool.name,
                "group": tool.group,
                "level": tool.level,
                "description": tool.description,
                "admin_only": tool.admin_only,
                "needs": tool.needs,
                "always": tool.always,
                "blocked": tool.name in blocked and not tool.always,
                "default": "allow" if tool.always else config.default_rights.get(tool.group, "allow"),
            }
            for tool in all_tools(config)
        ]

    @routes.get(f"{prefix}/tools", summary="Every tool with its group, level, default right and whether it is blocked")
    def tool_list(signed_in: Own, data: Data) -> dict:
        _, max_level = settings(config, data)
        return {
            "levels": list(config.levels),
            "max_level": max_level or config.highest,
            "extras": list(config.extras),
            "tools": _tool_rows(data),
        }

    def _own_key(data: Any, signed_in: Any, key: str) -> Any:
        caller = data.caller_of_key(_int(key))
        if caller is None or str(caller.account_id) != str(account_id(signed_in)):
            raise refuse(McpRefused("key_unknown"))
        return caller

    def _int(raw: str) -> Any:
        """A number where the app numbers its rows, else the text (nexlore ``mcp-12``, nexmail text ids)."""
        return int(raw) if raw.isdigit() and len(raw) <= 18 else raw

    def _rights_of(data: Any, caller: Any) -> dict:
        blocked, max_level = settings(config, data)
        caller.rights = data.key_rights(caller.key_id)
        return {
            "key": {"id": caller.key_id, "name": caller.key_name, "program": caller.program},
            "level": rights.level_of(config, caller, max_level),
            "tools": [
                {
                    "name": tool.name,
                    "group": tool.group,
                    "right": "allow" if tool.always else rights.chosen(config, caller, tool),
                    "asks_never": tool.looks_only or tool.always,
                    "reason": rights.why_not(config, caller, tool, blocked, max_level),
                    "always": tool.always,
                }
                for tool in all_tools(config)
            ],
        }

    @routes.get(f"{prefix}/keys/{{key}}/rights", summary="Rights per tool of an own key or program")
    def key_rights(key: str, signed_in: Own, data: Data) -> dict:
        return _rights_of(data, _own_key(data, signed_in, key))

    @routes.put(f"{prefix}/keys/{{key}}/rights", summary="Set what an own key may do with each tool")
    def set_key_rights(key: str, signed_in: Own, data: Data, body: Annotated[dict, Body()]) -> dict:
        caller = _own_key(data, signed_in, key)
        wanted = body.get("rights")
        if not isinstance(wanted, dict):
            raise refuse(McpRefused("right_invalid"))
        for name, value in wanted.items():
            if config.tool(name) is None:
                raise refuse(McpRefused("tool_unknown"))
            if value not in RIGHTS:
                raise refuse(McpRefused("right_invalid"))
        data.set_key_rights(caller.key_id, rights.own_rights(config, wanted))
        data.commit()
        return _rights_of(data, caller)

    @routes.get(f"{prefix}/requests", summary="The own requests, newest first")
    def request_list(
        signed_in: Own, data: Data, status: Annotated[str | None, Query(max_length=20)] = None
    ) -> list[dict]:
        data.expire(_now())
        data.commit()
        found = data.requests_of(account_id(signed_in))
        return [requests.listed(row) for row in found if status is None or status not in STATES or row.status == status]

    def _one(data: Any, signed_in: Any, request_id: str) -> Any:
        data.expire(_now())
        data.commit()
        found = data.request(_int(request_id))
        if found is None or str(found.account_id) != str(account_id(signed_in)):
            raise refuse(McpRefused("request_unknown"))
        return found

    @routes.get(f"{prefix}/requests/{{request_id}}", summary="One own request")
    def request_one(request_id: str, signed_in: Own, data: Data) -> dict:
        return requests.listed(_one(data, signed_in, request_id))

    @routes.post(f"{prefix}/requests/{{request_id}}/approve", summary="Allow a request: it runs now, as asked")
    async def approve(request_id: str, signed_in: Own, data: Data, body: Annotated[dict | None, Body()] = None) -> dict:
        try:
            done = await requests.approve(
                config,
                data,
                account_id(signed_in),
                account_name(signed_in),
                _int(request_id),
                confirm=bool((body or {}).get("confirm")),
                notify=notify,
            )
        except McpRefused as refusal:
            data.rollback()
            raise refuse(refusal) from None
        return requests.listed(done)

    @routes.post(f"{prefix}/requests/{{request_id}}/decline", summary="Turn a request down")
    def decline(request_id: str, signed_in: Own, data: Data) -> dict:
        try:
            done = requests.decline(
                data, account_id(signed_in), account_name(signed_in), _int(request_id), notify=notify
            )
        except McpRefused as refusal:
            data.rollback()
            raise refuse(refusal) from None
        return requests.listed(done)

    # --- the operator -------------------------------------------------------------------------------------------

    def _admin(data: Any) -> dict:
        blocked, max_level = settings(config, data)
        return {
            "programs": data.setting("programs") is not False,
            "levels": list(config.levels),
            "max_level": max_level or config.highest,
            "blocked_tools": list(blocked),
            "tools": [
                {"name": tool.name, "group": tool.group, "level": tool.level}
                for tool in all_tools(config)
                if not tool.always
            ],
        }

    @routes.get(f"{prefix}/admin", summary="The operator's settings of MCP", dependencies=[Depends(operator)])
    def admin_get(data: Data) -> dict:
        return _admin(data)

    @routes.put(f"{prefix}/admin", summary="Change the operator's settings of MCP", dependencies=[Depends(operator)])
    def admin_put(data: Data, body: Annotated[dict, Body()]) -> dict:
        if "max_level" in body and body["max_level"] not in config.levels:
            raise refuse(McpRefused("level_invalid"))
        if "blocked_tools" in body:
            names = body["blocked_tools"]
            known = {tool.name for tool in config.tools}
            if not isinstance(names, list) or not all(name in known for name in names):
                raise refuse(McpRefused("tool_unknown"))
            data.set_setting("blocked_tools", sorted(set(names)))
        if "max_level" in body:
            data.set_setting("max_level", body["max_level"])
        if "programs" in body:
            data.set_setting("programs", bool(body["programs"]))
        data.commit()
        return _admin(data)

    return routes
