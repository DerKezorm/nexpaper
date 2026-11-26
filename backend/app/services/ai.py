"""The AI of the operator: since ki 0.1.0 the shared module ``vendor/nexki`` (``services/ki_store.py``), with
nexpaper's older routes and names on top of it.

The module does the request itself: where it may go (a service of the operator in the own network or on the internet
over https, an own access only to hosts on the operator's list; never link-local, the metadata services, a redirect or
a proxy from the environment), one deadline for the whole of it, the size of the answer, the peculiarities of models
(``max_completion_tokens``, ``temperature``, ``reasoning_effort``), the brakes, the log without content, and "Was ging
hinaus". The chain of switches is the module's too: the operator's main switch "KI auf diesem Server erlaubt" (new,
K3: on after the update where the service was set up), "KI erlaubt" of the account, the person's own switch, and
nexpaper's own check (``ai_skip_personal``: personal vaults never go to the AI).

What stays here is what the older routes (``/api/v1/ai``, ``/api/v1/settings/ai…``, ``routers/ai.py``) answered and
checked, in their old form and with their old codes (Bauplan E53, E55): the kind of service named ``none``, ``local``,
``openai`` or ``messages``; a ``local`` service must lie in the own network and one on the internet on the internet;
the operator's own wishes for the proposals and the switch of personal vaults (nexpaper's own, not the module's).

``transport``, ``resolver`` and ``ticks`` stand in for the module's (``nexki.client``): a test that puts its own here
puts it there.
"""

from __future__ import annotations

import logging
import sys
import types
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import urljoin, urlsplit

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import error
from ..models import Account
from ..vendor import nexki
from . import outbound, settings_service
from .ki_store import CONFIG

logger = logging.getLogger("nexpaper.ai")

#: The kinds of service of the older routes: ``local`` is the OpenAI form in the own network (K9: a place, not an
#: interface), ``none`` no service.
PROVIDERS = ("none", "local", "openai", "messages")
CLOUD = ("openai", "messages")
WORKING = ("local", "openai", "messages")
MESSAGES_VERSION = "2023-06-01"
#: The operator's key, sealed in this context since 1.0.0 (the module reads it there).
KEY_CONTEXT = CONFIG.operator_key_context
LIST_SECONDS = CONFIG.list_seconds
TEXT_SECONDS = 180.0
CONNECT_SECONDS = CONFIG.connect_seconds
MAX_OUT = 1_200
THINKING_OUT = CONFIG.thinking_out
MAX_ANSWER = CONFIG.max_answer
MAX_MODELS = CONFIG.max_models
SAID_CHARS = CONFIG.said_chars
AT_ONCE = CONFIG.at_once
OPERATOR_PER_MINUTE = CONFIG.operator_per_minute
#: The longest the operator's own wishes for the proposals may be.
INSTRUCTIONS_MAX = 2000
PROBE = CONFIG.probe_text

#: The English sentences of the older routes; the module's own where it says the same.
AI_MESSAGES = {
    **{code: text for code, (_status, text) in nexki.CODES.items()},
    "ai_off": "No AI is set up on this server.",
    "ai_provider_unknown": "There is no such kind of AI service.",
    "ai_address_private": "This address lies in the own network; choose a local model for it.",
    "ai_address_public": "This address lies on the internet; a local model must stay in the own network.",
}

#: The status an older route answered with where the module's differs (E55): turning the AI off for oneself, the
#: operator's say and "none set up" were 403 for a person.
OLD_STATUS = {"ai_switched_off": 403, "ai_not_allowed": 403}


def fail(code: str, status: int = 422, **values: Any) -> HTTPException:
    return error(code, AI_MESSAGES.get(code, "The AI service did not work."), status, **values)


def refusal(refused: nexki.AiRefused, status: int | None = None) -> HTTPException:
    """A refusal of the module in the form of nexpaper's older routes (``{"detail": {"code", "message", …}}``)."""
    values = {key: value for key, value in (refused.values or {}).items() if key not in ("code", "message")}
    return fail(refused.code, status or OLD_STATUS.get(refused.code, refused.status), **values)


# --- The store of this request -------------------------------------------------------------------------------------


def store_of(db: Session) -> Any:
    from .mcp_store import McpStore

    return McpStore(db)


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def allowed_for(db: Session, account_id: int) -> bool:
    """Whether the operator allows this account the AI (on from the start; single accounts can be taken out)."""
    return bool(db.scalar(select(Account.ai_allowed).where(Account.id == account_id)))


def check_allowed(db: Session, account_id: int) -> None:
    """403 ``ai_not_allowed`` for an account the operator took the AI from."""
    if not allowed_for(db, account_id):
        raise fail("ai_not_allowed", 403)


def _provider(db: Session) -> str:
    """The kind of the operator's service as the older routes name it; ``none`` while the main switch is off or the
    service is not complete."""
    values = settings_service.get_all(db)
    stored = values["ai_provider"] if values["ai_provider"] in PROVIDERS else "none"
    return stored


def state(db: Session, own_switch: bool, allowed: bool, account_id: int | None = None) -> dict[str, Any]:
    """What a person may know about the AI (``GET /api/v1/ai``, its form of before): whether there is one for them,
    of which kind, and where the text goes. A host in the own network is never told."""
    values = settings_service.get_all(db)
    store = store_of(db)
    found = nexki.settings.operator_service(store, CONFIG)
    provider = _provider(db) if (nexki.settings.enabled(store) and found.complete) else "none"
    if nexki.settings.mode(store, CONFIG) == "own" and account_id is not None:
        own = nexki.settings.own_service(store, CONFIG, account_id)
        found = own if own is not None else found
        provider = (own.api if own is not None and own.complete and nexki.settings.enabled(store) else "none")
    local = provider == "local"
    if provider not in ("none", "local") and found.url:
        try:
            local = nexki.client._place(found, "models", store)[1]
        except nexki.AiRefused:
            local = False
    return {
        "provider": provider,
        "to": host_of(found.url) if provider != "none" and not local else "",
        "model": found.model if provider != "none" else "",
        "mine": own_switch,
        "allowed": allowed,
        "available": provider != "none" and own_switch and allowed,
        "skip_personal": bool(values.get("ai_skip_personal", True)),
    }


def operator_view(db: Session) -> dict[str, Any]:
    """The operator's service in the form of ``GET /api/v1/settings/ai`` before the module."""
    values = settings_service.get_all(db)
    store = store_of(db)
    view = nexki.settings.operator_view(store, CONFIG)
    provider = _provider(db)
    return {
        "provider": provider if view["enabled"] or provider == "none" else "none",
        "url": str(values["ai_url"] or ""),
        "model": str(values["ai_model"] or ""),
        "key_set": bool(values["ai_key_enc"]),
        "skip_personal": bool(values.get("ai_skip_personal", True)),
        "daily_limit": int(view["server_day"]),
        "used_today": int(view["used_today"]),
        "instructions": str(values.get("ai_instructions") or ""),
    }


def clean_instructions(text: str) -> str:
    """The operator's wishes as they are kept: lines and tabs stay, other control and format characters go, at most
    ``INSTRUCTIONS_MAX`` characters, no blank lines at either end."""
    kept = "".join(char for char in text.replace("\r\n", "\n").replace("\r", "\n")
                   if char in "\n\t" or unicodedata.category(char) not in ("Cc", "Cf"))
    return kept.strip()[:INSTRUCTIONS_MAX].strip()


def check_address(url: str, provider: str) -> str:
    """The base address, cleaned, with its slash at the end. Only http and https, no credentials in it; a service on
    the internet over https only (the older route's checks, before the module's)."""
    url = (url or "").strip()
    if not url:
        raise fail("ai_address_missing")
    if len(url) > 255:
        raise fail("ai_address_invalid")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise fail("ai_address_invalid")
    if parts.query or parts.fragment:
        raise fail("ai_address_invalid")
    try:
        parts.port  # noqa: B018 - raises ValueError when the port is not a number
    except ValueError as exc:
        raise fail("ai_address_invalid") from exc
    if provider in CLOUD and parts.scheme != "https":
        raise fail("ai_https_required")
    return url if url.endswith("/") else url + "/"


def _resolving(host: str, port: int) -> list[str]:
    try:
        return nexki.client.resolver(host, port)
    except nexki.AiRefused as refused:
        raise refusal(refused) from None
    except outbound.Unreachable as exc:
        raise fail("ai_unreachable", 502) from exc


def checked_place(url: str, provider: str) -> None:
    """The older route's rule of the place: a ``local`` service only in the own network, one on the internet only on
    the internet (the module allows the operator's service either, K9; the older route keeps its word)."""

    def rule(ip: Any) -> None:
        if provider == "local" and outbound.public(str(ip)):
            raise fail("ai_address_public")
        if provider != "local" and not outbound.public(str(ip)):
            raise fail("ai_address_private")

    try:
        outbound.pin(url, _resolving, rule)
    except outbound.Refused as exc:
        raise fail("ai_address_refused") from exc
    except outbound.Unreachable as exc:
        raise fail("ai_unreachable", 502) from exc


def save(db: Session, *, provider: str | None, url: str | None, model: str | None,
         key: str | None, skip_personal: bool | None = None, daily_limit: int | None = None,
         instructions: str | None = None) -> dict[str, Any]:
    """``PUT /api/v1/settings/ai`` as before: changes what was sent. Choosing a kind of service switches the AI on for
    the server (that was what choosing one meant), ``none`` off. The key belongs to its address (the module forgets it
    on a new address or kind without a new one)."""
    current = operator_view(db)
    stored_provider = _provider(db)
    next_provider = stored_provider if provider is None else provider
    if next_provider not in PROVIDERS:
        raise fail("ai_provider_unknown")
    next_url = None
    if next_provider in WORKING and (url is not None or provider is not None):
        typed = current["url"] if url is None else url.strip()
        next_url = check_address(typed, next_provider) if typed else ""
        if next_url:
            checked_place(urljoin(next_url, "models"), next_provider)
    elif url is not None:
        next_url = url.strip()
    store = store_of(db)
    api = None if next_provider == "none" else ("openai" if next_provider == "local" else next_provider)
    try:
        nexki.settings.save_operator(
            store, CONFIG, resolver=nexki.client.resolver,
            api=api if provider is not None and api is not None else None,
            url=next_url, model=model,
            key=key, server_day=daily_limit,
            enabled_now=(next_provider != "none") if provider is not None else None,
        )
    except nexki.AiRefused as refused:
        raise refusal(refused) from None
    changes: dict[str, Any] = {}
    if provider is not None:
        # The older name of the kind stays readable for the older routes (the module reads ``local`` as its form).
        changes["ai_provider"] = provider
        if next_provider != stored_provider and key is None and current["key_set"]:
            changes["ai_key_enc"] = ""
    if skip_personal is not None:
        changes["ai_skip_personal"] = skip_personal
    if instructions is not None:
        changes["ai_instructions"] = clean_instructions(instructions)
    if changes:
        settings_service.save(db, changes)
    logger.info("The operator changed the AI service")
    return operator_view(db)


def _old_place(db: Session, url: str | None = None, provider: str | None = None) -> None:
    """The older routes' rule of the place, at every request of theirs as before (E55): ``local`` in the own network,
    the others on the internet. The module itself lets the operator's service lie in either (K9)."""
    kind = provider or _provider(db)
    base = (url or "").strip() or str(settings_service.get_all(db)["ai_url"] or "")
    if kind in WORKING and base:
        checked_place(urljoin(check_address(base, kind), "models"), kind)


def list_models(db: Session, operator_id: int, *, provider: str | None, url: str | None,
                key: str | None) -> list[dict[str, str]]:
    """``POST /api/v1/settings/ai/models`` as before: the models of what is typed or stored. The stored key goes only
    to the stored address."""
    store = store_of(db)
    api = None if provider in (None, "none") else ("openai" if provider == "local" else provider)
    try:
        with _one_lookup():
            _old_place(db, url, provider)
            found = nexki.client.list_models(store, CONFIG, operator=True, account_id=operator_id, api=api, url=url,
                                             key=key)
    except nexki.AiRefused as refused:
        raise refusal(refused) from None
    return [{"id": entry["id"], "name": entry.get("name", "")} for entry in found]


@contextmanager
def _one_lookup() -> Iterator[None]:
    """One lookup of a name for the older routes' rule and the module's request together: a second lookup could answer
    differently (DNS rebinding) and pass the rule with one address and connect to another."""
    asked = nexki.client.resolver
    seen: dict[tuple[str, int], list[str]] = {}

    def once(host: str, port: int) -> list[str]:
        if (host, port) not in seen:
            seen[(host, port)] = list(asked(host, port))
        return list(seen[(host, port)])

    nexki.client.resolver = once
    try:
        yield
    finally:
        if nexki.client.resolver is once:
            nexki.client.resolver = asked


def probe(db: Session, operator_id: int) -> float:
    """``POST /api/v1/settings/ai/probe`` as before: one tiny question to the stored service; the seconds it took."""
    store = store_of(db)
    if _provider(db) == "none" or not nexki.settings.enabled(store):
        raise fail("ai_off", 409)
    try:
        with _one_lookup():
            _old_place(db)
            return float(nexki.client.probe(store, CONFIG, operator_id)["seconds"])
    except nexki.AiRefused as refused:
        raise refusal(refused, 409 if refused.code in ("ai_off", "ai_incomplete") else None) from None


def forget() -> None:
    """For tests: the module's brakes start empty."""
    nexki.brake.BRAKE.forget()


class _Module(types.ModuleType):
    """``ai.transport``, ``ai.resolver`` and ``ai.ticks`` are the module's (``nexki.client``)."""

    _FORWARDED = ("transport", "resolver", "ticks")

    def __getattr__(self, name: str) -> Any:
        if name in _Module._FORWARDED:
            return getattr(nexki.client, name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in _Module._FORWARDED:
            setattr(nexki.client, name, value)
            return
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if name in _Module._FORWARDED:
            return
        super().__delattr__(name)


transport: Any
resolver: Callable[[str, int], list[str]]
ticks: Callable[[], float]
sys.modules[__name__].__class__ = _Module
