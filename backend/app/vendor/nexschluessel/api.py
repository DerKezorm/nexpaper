"""The routes of the cards "API keys", "AI tools (MCP)", "Interfaces" and "API keys of all accounts":

``GET    <prefix>/keys``                     the account's keys and programs, what it may make, the switches
``POST   <prefix>/keys``                     make a key: ``{key, secret}`` (the secret this once)
``PATCH  <prefix>/keys/{id}``                change name, right, areas, extras
``DELETE <prefix>/keys/{id}``                revoke (a program's too)
``GET    <prefix>/admin/keys``               every key of every account (operator)
``POST   <prefix>/admin/keys/{id}/block``    lock a key (operator)
``POST   <prefix>/admin/keys/{id}/unblock``  unlock it (operator)
``GET    <prefix>/interfaces``               the operator's switches
``PUT    <prefix>/interfaces``               change them

The app mounts them with ``app.include_router(nexschluessel.api.router(...))`` and gives its own dependencies: the
store over its database session (one per request), the signed-in account (browser sessions only: a key or a device
never manages keys), the operator. ``prefix`` is ``/api/connections``; the app's older routes (``/api/tokens``,
``/api/api-tokens``, ``/api/keys``, ``/api/mcp/keys``, ``/api/v1/api-keys``, ``/api/apischluessel``) stay and call
the same functions in their old form.

The only part of the module that needs FastAPI; the rest is the standard library."""

# No ``from __future__ import annotations`` here: the routes name dependencies made inside ``router()``, which
# FastAPI must see as objects, not as text it would look up in the module.

from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import keys, switches
from .config import AppConfig
from .errors import KeyRefused
from .model import ALL_AREAS, Store

AreaIds = list[int | str] | Literal["all"] | None


class NewKeyIn(BaseModel):
    kind: Literal["api", "mcp"] = "api"
    name: str = Field(default="", max_length=1000)
    right: str | None = Field(default=None, max_length=32)
    #: ``"all"`` or missing: all (where offered); a list: these.
    areas: AreaIds = None
    options: dict[str, bool] | None = None
    #: Days; ``null``: never; missing: the app's lifetime for the right.
    days: int | None = None
    client_ref: str | None = Field(default=None, max_length=64)


class KeyChangeIn(BaseModel):
    name: str | None = Field(default=None, max_length=1000)
    right: str | None = Field(default=None, max_length=32)
    areas: AreaIds = None
    options: dict[str, bool] | None = None


class SwitchesIn(BaseModel):
    api: bool | None = None
    mcp: bool | None = None
    app: bool | None = None
    pairing: bool | None = None


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def router(
    *,
    config: AppConfig,
    store: Callable[..., Store],
    account: Callable[..., Any],
    operator: Callable[..., Any],
    account_id: Callable[[Any], Any] = lambda signed_in: signed_in.id,
    address: Callable[[Request], str] | None = None,
    prefix: str = "/api/connections",
    error: Callable[[KeyRefused], Exception] | None = None,
    tags: list[str] | None = None,
) -> APIRouter:
    """The routes. ``store``: a dependency giving the app's ``Store`` for this request. ``account``: the dependency
    of a signed-in browser session (``account_id`` reads its id). ``operator``: the app's dependency for operators.
    ``address(request)``: the public address programs use (the app's setting, else the request's). ``error``: the
    app's form of a refusal (default ``HTTPException`` with ``KeyRefused.as_dict()`` as ``detail``)."""
    routes = APIRouter(prefix=prefix, tags=tags or ["keys"])
    public = address or _base

    def refuse(refusal: KeyRefused) -> Exception:
        if error is not None:
            return error(refusal)
        return HTTPException(status_code=refusal.status, detail=refusal.as_dict())

    def key_id(raw: str) -> Any:
        if config.key_id is int:
            if not raw.isdigit() or len(raw) > 18:
                raise refuse(KeyRefused("not_found", config=config))
            return int(raw)
        if not 0 < len(raw) <= 64:
            raise refuse(KeyRefused("not_found", config=config))
        return raw

    Own = Annotated[Any, Depends(account)]
    Data = Annotated[Store, Depends(store)]

    @routes.get("/keys", summary="The account's keys and connected programs")
    def own_keys(request: Request, signed_in: Own, data: Data) -> dict:
        found = keys.listing(data, config, account_id(signed_in))
        found["address"] = public(request)
        return found

    @routes.post("/keys", status_code=201, summary="Make a key; its secret is shown this once")
    def make_key(body: NewKeyIn, signed_in: Own, data: Data, response: Response) -> dict:
        days: int | None | str = body.days if "days" in body.model_fields_set else "default"
        try:
            made = keys.make(
                data,
                config,
                account_id(signed_in),
                kind=body.kind,
                name=body.name,
                right=body.right,
                areas=body.areas,
                options=body.options,
                days=days,
                client_ref=body.client_ref,
            )
        except KeyRefused as refusal:
            data.rollback()
            raise refuse(refusal) from None
        response.headers["Cache-Control"] = "no-store"
        if not made.new:
            response.status_code = 200
        listed = keys.listing(data, config, account_id(signed_in))
        shown = next((row for row in listed["keys"] if str(row["id"]) == str(made.key.id)), None)
        return {"key": shown or keys.entry(made.key, config), "secret": made.secret or None}

    @routes.patch("/keys/{key}", summary="Change name, right, areas or extras of an own key")
    def change_key(key: str, body: Annotated[KeyChangeIn, Body()], signed_in: Own, data: Data) -> dict:
        given = "areas" in body.model_fields_set
        try:
            changed = keys.change(
                data,
                config,
                account_id(signed_in),
                key_id(key),
                name=body.name,
                right=body.right,
                areas=ALL_AREAS if given and body.areas is None else body.areas,
                options=body.options,
                areas_given=given,
            )
        except KeyRefused as refusal:
            data.rollback()
            raise refuse(refusal) from None
        listed = keys.listing(data, config, account_id(signed_in))
        return next(row for row in listed["keys"] if str(row["id"]) == str(changed.id))

    @routes.delete("/keys/{key}", status_code=204, summary="Revoke an own key or a connected program")
    def revoke_key(key: str, signed_in: Own, data: Data) -> Response:
        try:
            keys.revoke(data, config, account_id(signed_in), key_id(key))
        except KeyRefused as refusal:
            data.rollback()
            raise refuse(refusal) from None
        return Response(status_code=204)

    @routes.get("/admin/keys", summary="Every key of every account", dependencies=[Depends(operator)])
    def every_key(data: Data) -> dict:
        return {"keys": keys.overview(data, config)}

    @routes.post("/admin/keys/{key}/block", summary="Lock a key", dependencies=[Depends(operator)])
    def block_key(key: str, data: Data) -> dict:
        try:
            return keys.block(data, config, key_id(key))
        except KeyRefused as refusal:
            data.rollback()
            raise refuse(refusal) from None

    @routes.post("/admin/keys/{key}/unblock", summary="Unlock a key", dependencies=[Depends(operator)])
    def unblock_key(key: str, data: Data) -> dict:
        try:
            return keys.unblock(data, config, key_id(key))
        except KeyRefused as refusal:
            data.rollback()
            raise refuse(refusal) from None

    @routes.get("/interfaces", summary="The operator's switches", dependencies=[Depends(operator)])
    def read_switches(data: Data) -> dict:
        return switches.state(data, config)

    @routes.put("/interfaces", summary="Change the operator's switches", dependencies=[Depends(operator)])
    def set_switches(body: SwitchesIn, data: Data) -> dict:
        try:
            return switches.change(data, config, body.model_dump(exclude_none=True))
        except KeyRefused as refusal:
            data.rollback()
            raise refuse(refusal) from None

    return routes
