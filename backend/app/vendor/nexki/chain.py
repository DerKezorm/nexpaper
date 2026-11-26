"""The chain of switches: whatever sends a person's text anywhere asks it first, at every request, never only when
saving. In this order, the first no is the reason given (``errors.CHAIN``):

1. the main switch of the server "KI auf diesem Server erlaubt" (K3) and, in mode "shared", the operator's service:
   ``ai_off``;
2. "KI erlaubt" of the account (module konten) and the account neither blocked nor deleted: ``ai_not_allowed``;
3. the person's own switch: ``ai_switched_off``;
4. the app's own check for this one request (nexmail: received mail; nexpaper: a personal vault; nexdiary: writing in
   the morning): ``ai_app_refused``;
5. in mode "own": the account's own service, complete: ``ai_incomplete``.

``for_programs`` is what the modules ``schluessel`` and ``mcp`` ask (``Store.ai_allowed``, MCP decision 10): only
step 2. AI programs from outside need no service of the operator and are switched by "MCP-Zugang" (K8)."""

from __future__ import annotations

from typing import Any

from . import settings
from .config import AppConfig
from .errors import CHAIN, AiRefused
from .model import AccountId, Service, Store


def for_programs(store: Store, account_id: AccountId) -> bool:
    """"KI erlaubt" for AI programs from outside (MCP): the account's right, and the account not shut out."""
    return bool(store.account_allowed(account_id)) and not store.account_out(account_id)


def usable(store: Store, config: AppConfig, account_id: AccountId, *, app_ok: bool = True) -> Service:
    """The service this account's request goes out with, or the refusal of the first switch that says no."""
    if not settings.enabled(store):
        raise AiRefused("ai_off")
    shared = settings.mode(store, config) == "shared"
    if shared and not settings.operator_service(store, config).complete:
        raise AiRefused("ai_off")
    if not for_programs(store, account_id):
        raise AiRefused("ai_not_allowed")
    if not store.person_on(account_id):
        raise AiRefused("ai_switched_off")
    if not app_ok:
        raise AiRefused("ai_app_refused")
    if shared:
        return settings.operator_service(store, config)
    own = settings.own_service(store, config, account_id)
    if own is None or not own.complete:
        raise AiRefused("ai_incomplete")
    return own


def reason(store: Store, config: AppConfig, account_id: AccountId, *, app_ok: bool = True) -> str | None:
    """The code of the first switch that says no, ``None`` when the AI works for this account."""
    try:
        usable(store, config, account_id, app_ok=app_ok)
    except AiRefused as refused:
        assert refused.code in CHAIN
        return refused.code
    return None


def state(store: Store, config: AppConfig, account_id: AccountId, *, local: bool | None) -> dict[str, Any]:
    """What a person may know: whether the AI works for them and why not, the way, the model, and where the text goes
    (a host on the internet by its name; a host in the own network is never named to a member, only "the own
    network")."""
    why = reason(store, config, account_id)
    way = settings.mode(store, config)
    found = settings.operator_service(store, config) if way == "shared" else settings.own_service(
        store, config, account_id
    )
    out: dict[str, Any] = {
        "available": why is None,
        "reason": why,
        "enabled": settings.enabled(store),
        "allowed": for_programs(store, account_id),
        "mine": bool(store.person_on(account_id)),
        "mode": way,
        "api": found.api if found else "",
        "model": found.model if found else "",
        "local": bool(local),
        "to": "" if (local or found is None or not found.url) else settings.host_of(found.url),
    }
    if way == "own":
        # The own access is the person's own; the operator's list of hosts in the own network is not told.
        out["own"] = settings.own_view(store, config, account_id)
    return out
