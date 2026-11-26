"""The module's routes (FastAPI). New routes only (plan: "Neue Wege unter /api/server/ai und /api/me/ai kommen dazu");
the app's older routes stay in the app and call the same functions, with their old shapes and codes.

| Route | Who | |
|---|---|---|
| ``GET /api/server/ai`` | operator | the settings without the key (``key_set``) |
| ``PUT /api/server/ai`` | operator | change what is sent |
| ``POST /api/server/ai/models`` | operator | the models of the typed or stored service |
| ``POST /api/server/ai/probe`` | operator | one tiny question, nothing of anybody's data |
| ``GET /api/me/ai`` | account | whether the AI works for me and where my text goes |
| ``PUT /api/me/ai`` | account | my own switch; in mode "own" my own service |
| ``POST /api/me/ai/models`` | account | models of my own service (mode "own") |
| ``GET /api/me/ai/events`` / ``DELETE`` | account | what went out, 14 days / clear it now |

Refusals: ``{"detail": {"code", "message", …}}`` with the status of ``errors.CODES``.
"""

# No ``from __future__ import annotations`` here: FastAPI reads the dependencies from the annotations, and the
# aliases ``Data``, ``Account``, ``Operator`` live inside ``router``.
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import chain, client, net, settings
from .config import AppConfig
from .errors import AiRefused


class OperatorIn(BaseModel):
    enabled: bool | None = None
    mode: str | None = Field(default=None, max_length=10)
    api: str | None = Field(default=None, max_length=20)
    url: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=200)
    key: str | None = Field(default=None, max_length=500)
    hosts: list[str] | None = Field(default=None, max_length=50)
    per_minute: int | None = Field(default=None, ge=1, le=1_000_000)
    per_day: int | None = Field(default=None, ge=0, le=1_000_000)
    server_day: int | None = Field(default=None, ge=0, le=1_000_000)


class ModelsIn(BaseModel):
    api: str | None = Field(default=None, max_length=20)
    url: str | None = Field(default=None, max_length=255)
    key: str | None = Field(default=None, max_length=500)


class MineIn(BaseModel):
    mine: bool | None = None
    api: str | None = Field(default=None, max_length=20)
    url: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=200)
    key: str | None = Field(default=None, max_length=500)


def refusal(refused: AiRefused) -> HTTPException:
    headers = {"Retry-After": "60"} if refused.code == "ai_too_often" else None
    return HTTPException(status_code=refused.status, detail=refused.as_dict(), headers=headers)


def local_of(store: Any, config: AppConfig, account_id: Any) -> bool | None:
    """Whether the service this account's text goes to lies in the own network (resolved now; ``None`` when it does
    not resolve or is not allowed: then the host is named, which is never wrong for a member to read)."""
    way = settings.mode(store, config)
    found = settings.operator_service(store, config) if way == "shared" else settings.own_service(
        store, config, account_id
    )
    if found is None or not found.url:
        return None
    try:
        _, local = net.place(found.url, operator=found.operator, listed=settings.hosts(store), resolver=client.resolver)
    except AiRefused:
        return None
    return local


def router(
    *,
    config: AppConfig,
    store: Callable[..., Any],
    account: Callable[..., Any],
    operator: Callable[..., Any],
    account_id: Callable[[Any], Any] = lambda row: row.id,
    server_prefix: str = "/api/server/ai",
    me_prefix: str = "/api/me/ai",
) -> APIRouter:
    """The routes, with the app's dependencies: ``store`` gives the ``Store`` of this request, ``account`` the signed-in
    account (any role), ``operator`` an operator (403 otherwise)."""
    made = APIRouter(tags=["ai"])
    Data = Annotated[Any, Depends(store)]
    Account = Annotated[Any, Depends(account)]
    Operator = Annotated[Any, Depends(operator)]

    def me(found: Any, data: Any) -> dict[str, Any]:
        who = account_id(found)
        return chain.state(data, config, who, local=local_of(data, config, who))

    @made.get(server_prefix, summary="The AI settings of the server, without the key")
    def operator_view(_operator: Operator, data: Data) -> dict[str, Any]:
        return settings.operator_view(data, config)

    @made.put(server_prefix, summary="Change the AI settings of the server; only the fields sent change")
    def operator_save(body: OperatorIn, _operator: Operator,
                      data: Data) -> dict[str, Any]:
        try:
            return settings.save_operator(
                data, config, resolver=client.resolver, enabled_now=body.enabled, mode_now=body.mode, api=body.api,
                url=body.url, model=body.model, key=body.key, hosts_now=body.hosts, per_minute=body.per_minute,
                per_day=body.per_day, server_day=body.server_day,
            )
        except AiRefused as refused:
            raise refusal(refused) from None

    @made.post(f"{server_prefix}/models", summary="The models of the typed or the stored service")
    def operator_models(body: ModelsIn, found: Operator,
                        data: Data) -> list[dict[str, str]]:
        try:
            return client.list_models(data, config, operator=True, account_id=account_id(found), api=body.api,
                                      url=body.url, key=body.key)
        except AiRefused as refused:
            raise refusal(refused) from None

    @made.post(f"{server_prefix}/probe", summary="One tiny question to the stored service, nothing of anybody's data")
    def operator_probe(found: Operator, data: Data) -> dict[str, Any]:
        try:
            return client.probe(data, config, account_id(found))
        except AiRefused as refused:
            raise refusal(refused) from None

    @made.get(me_prefix, summary="Whether the AI works for me, why not, and where my text goes")
    def mine_view(found: Account, data: Data) -> dict[str, Any]:
        return me(found, data)

    @made.put(me_prefix, summary="My own switch; in the way \"own\" my own service")
    def mine_save(body: MineIn, found: Account, data: Data) -> dict[str, Any]:
        who = account_id(found)
        try:
            if any(value is not None for value in (body.api, body.url, body.model, body.key)):
                settings.save_own(data, config, who, resolver=client.resolver, api=body.api, url=body.url,
                                  model=body.model, key=body.key)
            if body.mine is not None:
                data.set_person_on(who, body.mine)
                data.commit()
        except AiRefused as refused:
            raise refusal(refused) from None
        return me(found, data)

    @made.post(f"{me_prefix}/models", summary="The models of my own service (way \"own\")")
    def mine_models(body: ModelsIn, found: Account, data: Data) -> list[dict[str, str]]:
        who = account_id(found)
        try:
            if not chain.for_programs(data, who):
                raise AiRefused("ai_not_allowed")
            return client.list_models(data, config, operator=False, account_id=who, api=body.api, url=body.url,
                                      key=body.key)
        except AiRefused as refused:
            raise refusal(refused) from None

    @made.get(f"{me_prefix}/events", summary="What went out to the AI, newest first (14 days)")
    def mine_events(found: Account, data: Data) -> list[dict[str, Any]]:
        return client.events(data, config, account_id(found))

    @made.delete(f"{me_prefix}/events", summary="Clear what went out, now")
    def mine_clear(found: Account, data: Data) -> dict[str, int]:
        cleared = data.clear_events(account_id(found))
        data.commit()
        return {"cleared": cleared}

    return made
