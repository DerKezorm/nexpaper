"""The AI of the operator: the service that later proposes title, sender, kind, date and amount for a document.

Taken over from nexlore (``services/ai.py``), where the checks of the address were worked out in a security review.
This block holds the setting and the test of the service; the proposals themselves come with the block that sorts
documents (B6).

* **The operator decides, for everybody.** One service for the whole server, set up only by the operator: none (from
  the start), a local model in the own network (Ollama or any service that speaks ``/v1/chat/completions``, a key
  optional), a service on the internet that speaks the same, or a service that speaks the Messages API
  (``/v1/messages``, with the address the interface fills in for it). The key is sealed with the server's secret, never
  shown again, never logged, and forgotten when the address or the kind of service changes without a new one.
* **"Nothing leaves the house" has to be true.** A local service must lie in the own network: an address that resolves
  to the internet is refused when it is saved (resolved and checked then) and again at every request. A service on the
  internet must be reached over https and lie on the internet. Link-local addresses (169.254.169.254, the metadata of
  cloud machines) never. The name is resolved once per request and only the addresses checked are connected to, one
  after the other (``localhost`` may answer ``::1`` first while the service listens on 127.0.0.1).
* **Nothing on its own without a switch.** Every person may switch the AI off for themselves, and the operator may take
  it from single accounts (``check_allowed``: whatever sends a person's text anywhere asks it first).
* **Limits:** one request per person at a time, a few per minute, a few on the server at once; the operator's model
  list and probe the same way. Every request has a deadline for the whole of it, the answer read included, and is read
  up to a size. The log names provider, model, status and time, never a word of a text or of the answer.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import error
from ..models import Account
from ..security import decrypt_secret, encrypt_secret
from . import outbound, settings_service

logger = logging.getLogger("nexpaper.ai")

#: For the tests: an ``httpx`` transport that stands in for the service. Never a real key in a test.
transport: httpx.BaseTransport | None = None
#: The clock for deadlines and the brake per minute; the tests put their own in.
ticks: Callable[[], float] = time.monotonic

#: ``openai``: ``/chat/completions`` on the internet; ``messages``: ``/messages`` on the internet (the interface fills
#: in the provider's address and does not show the field); ``local``: ``/chat/completions`` in the own network.
PROVIDERS = ("none", "local", "openai", "messages")
CLOUD = ("openai", "messages")
WORKING = ("local", "openai", "messages")
MESSAGES_VERSION = "2023-06-01"
#: The operator's key has a context of its own: it could not be passed off as another secret of the server.
KEY_CONTEXT = "operator:ai-key"

#: The whole of a model list: a list that takes longer is a broken address, and the operator should hear so soon.
LIST_SECONDS = 10.0
#: The whole of a request that asks for text, the answer read included; a model at home without a graphics card
#: takes minutes.
TEXT_SECONDS = 180.0
#: The longest a connection may take to be made, within the deadline.
CONNECT_SECONDS = 10.0
#: What may come back, in the model's units and in bytes.
MAX_OUT = 1_200
MAX_ANSWER = 2 * 1024 * 1024
MAX_MODELS = 500
#: How much of a service's own words about an error the person sees.
SAID_CHARS = 300
#: Requests of the operator at the same moment, on the whole server.
AT_ONCE = 4
#: The operator's model lists and probes per minute.
OPERATOR_PER_MINUTE = 10


def fail(code: str, status: int = 422, **values: Any) -> HTTPException:
    return error(code, AI_MESSAGES.get(code, "The AI service did not work."), status, **values)


#: The English sentences for whoever uses the API directly; the interface has its own.
AI_MESSAGES = {
    "ai_off": "No AI is set up on this server.",
    "ai_switched_off": "You switched the AI off for yourself.",
    "ai_not_allowed": "Your operator has not allowed the AI for your account.",
    "ai_incomplete": "The AI service is not set up completely.",
    "ai_provider_unknown": "There is no such kind of AI service.",
    "ai_address_missing": "Give the address of the service.",
    "ai_address_invalid": "This is not an address of a service.",
    "ai_https_required": "A service on the internet is reached over https only.",
    "ai_address_refused": "This address is never reached.",
    "ai_address_private": "This address lies in the own network; choose a local model for it.",
    "ai_address_public": "This address lies on the internet; a local model must stay in the own network.",
    "ai_unreachable": "The server cannot reach the AI service.",
    "ai_timeout": "The AI service took too long.",
    "ai_key_refused": "The AI service refused the key.",
    "ai_address_not_found": "The AI service does not know this address.",
    "ai_service_busy": "The AI service is busy. Try again in a moment.",
    "ai_service_failed": "The AI service answered with an error.",
    "ai_unreadable": "The answer of the AI service could not be read.",
    "ai_empty": "The AI service gave back nothing.",
    "ai_no_list": "This service lists no models; type the name of the model.",
    "ai_no_models": "This service offers no models.",
    "ai_too_often": "Too many requests to the AI. Wait a little.",
    "ai_busy": "The AI is already working on a request of yours.",
    "ai_server_busy": "The AI is busy right now. Try again in a moment.",
}


# --- The service ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Service:
    """The operator's service: what a request goes out with."""

    provider: str
    url: str
    model: str
    key: str

    @property
    def complete(self) -> bool:
        return self.provider in WORKING and bool(self.url and self.model)


def service(db: Session) -> Service:
    values = settings_service.get_all(db)
    provider = values["ai_provider"] if values["ai_provider"] in PROVIDERS else "none"
    url = str(values["ai_url"] or "")
    return Service(provider, url, str(values["ai_model"] or ""), decrypt_secret(str(values["ai_key_enc"] or ""),
                                                                               KEY_CONTEXT))


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def allowed_for(db: Session, account_id: int) -> bool:
    """Whether the operator allows this account the AI (on from the start; single accounts can be taken out)."""
    return bool(db.scalar(select(Account.ai_allowed).where(Account.id == account_id)))


def check_allowed(db: Session, account_id: int) -> None:
    """403 ``ai_not_allowed`` for an account the operator took the AI from. Whatever sends a person's text to the
    service asks this first, besides the operator's service and the person's own switch."""
    if not allowed_for(db, account_id):
        raise fail("ai_not_allowed", 403)


def state(db: Session, own_switch: bool, allowed: bool) -> dict[str, Any]:
    """What a person may know about the AI: whether there is one for them, of which kind, and where the text goes.
    The address of a local service is not told (it names a machine in the own network); a service on the internet
    is named by its host, so that the interface can say where the text goes."""
    values = settings_service.get_all(db)
    provider = values["ai_provider"] if values["ai_provider"] in WORKING else "none"
    url, model = str(values["ai_url"] or ""), str(values["ai_model"] or "")
    if not (url and model):
        provider = "none"
    return {
        "provider": provider,
        "to": host_of(url) if provider in CLOUD else "",
        "model": model if provider != "none" else "",
        "mine": own_switch,
        # The operator's say for this account: without it there is no button and the server refuses.
        "allowed": allowed,
        "available": provider != "none" and own_switch and allowed,
        # Documents in personal vaults never go to the AI (the operator's choice, on from the start).
        "skip_personal": bool(values.get("ai_skip_personal", True)),
    }


def operator_view(db: Session) -> dict[str, Any]:
    values = settings_service.get_all(db)
    provider = values["ai_provider"] if values["ai_provider"] in PROVIDERS else "none"
    return {
        "provider": provider,
        "url": str(values["ai_url"] or ""),
        "model": str(values["ai_model"] or ""),
        "key_set": bool(values["ai_key_enc"]),
        "skip_personal": bool(values.get("ai_skip_personal", True)),
        "daily_limit": int(values.get("ai_daily_limit") or 0),
        "used_today": used_today(values),
    }


def used_today(values: dict[str, Any]) -> int:
    """The requests of today's proposals so far (the count is of the day it was made; a new day starts at zero)."""
    stored = values.get("ai_day")
    if isinstance(stored, dict) and stored.get("day") == clock.now().date().isoformat():
        return int(stored.get("count") or 0)
    return 0


def check_address(url: str, provider: str) -> str:
    """The base address, cleaned, with its slash at the end (``urljoin(".../v1", "models")`` drops the ``v1``).
    Only http and https, no credentials in it; a service on the internet over https only."""
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


def save(db: Session, *, provider: str | None, url: str | None, model: str | None,
         key: str | None, skip_personal: bool | None = None, daily_limit: int | None = None) -> dict[str, Any]:
    """Changes what was sent; left out stays. A new address is resolved and checked before it is kept, so that the
    operator hears at once that it lies in the wrong network (every request checks again).

    ⚠️ The key belongs to the address it was given for: a new address or another kind of service without a new key
    forgets the old one, or a changed address would carry the stored key to whatever host it names."""
    current = operator_view(db)
    changes: dict[str, Any] = {}
    next_provider = current["provider"] if provider is None else provider
    if next_provider not in PROVIDERS:
        raise fail("ai_provider_unknown")
    if provider is not None:
        changes["ai_provider"] = provider
    next_url = current["url"] if url is None else url.strip()
    if next_provider in WORKING and (url is not None or provider is not None):
        next_url = check_address(next_url, next_provider) if next_url else ""
        if next_url:
            checked_target(urljoin(next_url, "models"), next_provider)
        changes["ai_url"] = next_url
    if model is not None:
        changes["ai_model"] = " ".join(model.split())[:200]
    moved = next_provider != current["provider"] or (next_provider in WORKING and next_url != current["url"])
    if key is not None:
        changes["ai_key_enc"] = encrypt_secret(key.strip(), KEY_CONTEXT) if key.strip() else ""
    elif moved and current["key_set"]:
        changes["ai_key_enc"] = ""
    if skip_personal is not None:
        changes["ai_skip_personal"] = skip_personal
    if daily_limit is not None:
        changes["ai_daily_limit"] = max(0, min(int(daily_limit), 1_000_000))
    settings_service.save(db, changes)
    logger.info("The operator changed the AI service fields=%s", ",".join(sorted(changes)) or "nothing")
    return operator_view(db)


# --- Where a request goes -------------------------------------------------------------------------------------------


def _resolve(host: str, port: int) -> list[str]:
    try:
        return outbound.resolve(host, port)
    except outbound.Unreachable as exc:
        raise fail("ai_unreachable", 502) from exc


#: Resolves a name to its addresses; the tests put their own in.
resolver: Callable[[str, int], list[str]] = _resolve

public = outbound.public
Target = outbound.Target


def checked_target(url: str, provider: str) -> Target:
    """The service's address, resolved and checked once; the connection then goes to exactly the addresses checked
    (no second lookup that could answer differently). A local service only in the own network, one on the internet
    only on the internet; link-local, multicast, the unspecified address and the metadata services never
    (``outbound``)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    try:
        outbound.port_of(url)
    except ValueError as exc:
        raise fail("ai_address_invalid") from exc
    if parts.scheme not in ("http", "https") or not host or parts.username or parts.password:
        raise fail("ai_address_invalid")
    if provider in CLOUD and parts.scheme != "https":
        raise fail("ai_https_required")

    def rule(ip: Any) -> None:
        if provider == "local" and public(str(ip)):
            raise fail("ai_address_public")
        if provider != "local" and not public(str(ip)):
            raise fail("ai_address_private")

    try:
        return outbound.pin(url, resolver, rule)
    except outbound.Refused as exc:
        raise fail("ai_address_refused") from exc
    except outbound.Unreachable as exc:
        raise fail("ai_unreachable", 502) from exc


def _client() -> httpx.Client:
    return outbound.client(transport)


def _late(seconds: float) -> HTTPException:
    return fail("ai_timeout", 504, seconds=int(seconds))


def _send(client: httpx.Client, method: str, place: Target, headers: dict[str, str], deadline: float,
          seconds: float, **sent: Any) -> httpx.Response:
    """One request to the checked addresses (``outbound.send``): no redirect followed, the answer read up to
    MAX_ANSWER and only until the deadline."""
    try:
        return outbound.send(client, method, place, headers, deadline=deadline, ticks=ticks, limit=MAX_ANSWER,
                             connect_seconds=CONNECT_SECONDS, **sent)
    except outbound.Late as exc:
        raise _late(seconds) from exc
    except (outbound.TooLarge, outbound.Refused) as exc:
        raise fail("ai_unreadable", 502) from exc


def _headers(found: Service) -> dict[str, str]:
    headers = {"content-type": "application/json"}
    if found.provider == "messages":
        headers["anthropic-version"] = MESSAGES_VERSION
        if found.key:
            headers["x-api-key"] = found.key
    elif found.key:
        headers["authorization"] = f"Bearer {found.key}"
    return headers


def _said(answer: httpx.Response) -> str:
    """The service's own words about the error (``{"error": {"message": …}}`` nearly everywhere), one line, short.
    Never logged."""
    try:
        data = answer.json()
    except ValueError:
        return ""
    found = data.get("error") if isinstance(data, dict) else None
    if isinstance(found, dict):
        found = found.get("message")
    if not isinstance(found, str):
        return ""
    return " ".join("".join(c if c.isprintable() else " " for c in found).split())[:SAID_CHARS]


def _judge(answer: httpx.Response, place: Target) -> None:
    """A status that says where to look: the key, the address, or waiting. The service's own words only from the
    internet: a host in the own network could be any device there."""
    if answer.status_code == 200:
        return
    if answer.status_code in (401, 403):
        raise fail("ai_key_refused", 502)
    if answer.status_code == 404:
        raise fail("ai_address_not_found", 502)
    if answer.status_code == 429:
        raise fail("ai_service_busy", 502)
    from_internet = all(public(address) for address in place.addresses)
    raise fail("ai_service_failed", 502, answered=answer.status_code, said=_said(answer) if from_internet else "")


def _log(found: Service, what: str, status: str, started: float) -> None:
    # Provider, model, what, how it ended and how long: never a word of a note, of the answer or of the key.
    logger.info("AI %s provider=%s model=%s status=%s seconds=%.1f", what, found.provider, found.model[:80], status,
                ticks() - started)


def _exchange(found: Service, method: str, path: str, what: str, seconds: float,
              body: Callable[[bool], dict[str, Any]] | None = None) -> httpx.Response:
    """One request with its deadline, judged; a model that turns down the temperature is asked once more without it.
    Every way it ends is logged without content."""
    place = checked_target(urljoin(found.url, path), found.provider)
    started = ticks()
    deadline = started + seconds
    try:
        with _client() as client:
            sent = {"json": body(True)} if body else {}
            answer = _send(client, method, place, _headers(found), deadline, seconds, **sent)
            # Newer models choose it themselves and turn down a request that sets it: once more without.
            if body and answer.status_code == 400 and "temperature" in _said(answer).lower():
                answer = _send(client, method, place, _headers(found), deadline, seconds, json=body(False))
    except httpx.TimeoutException as exc:
        _log(found, what, "timeout", started)
        raise _late(seconds) from exc
    except httpx.HTTPError as exc:
        _log(found, what, "unreachable", started)
        raise fail("ai_unreachable", 502) from exc
    except HTTPException as exc:
        _log(found, what, str(exc.detail.get("code") if isinstance(exc.detail, dict) else exc.status_code), started)
        raise
    if path.endswith("models") and answer.status_code in (404, 405, 501):
        _log(found, what, "no-list", started)
        raise fail("ai_no_list")
    try:
        _judge(answer, place)
    except HTTPException:
        _log(found, what, f"http-{answer.status_code}", started)
        raise
    _log(found, what, "ok", started)
    return answer


def list_models(db: Session, operator_id: int, *, provider: str | None, url: str | None,
                key: str | None) -> list[dict[str, str]]:
    """The models a service offers, for the operator, with what is typed (not saved yet) or what is stored. The stored
    key goes only to the stored address: typed elsewhere, the address gets no key but the one typed with it."""
    stored = service(db)
    kind = provider or stored.provider
    if kind not in WORKING:
        raise fail("ai_off", 409)
    base = check_address(url if url is not None else stored.url, kind)
    same_place = kind == stored.provider and base == stored.url
    found = Service(kind, base, "", (key or "").strip() or (stored.key if same_place else ""))
    with _one_at_a_time(("operator", operator_id)):
        operator_pace.take(operator_id)
        answer = _exchange(found, "GET", "models", "models", LIST_SECONDS)
    try:
        data = answer.json()
    except ValueError as exc:
        raise fail("ai_unreadable", 502) from exc
    raw = data.get("data") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise fail("ai_unreadable", 502)
    out: list[dict[str, str]] = []
    for entry in raw[:MAX_MODELS]:
        if isinstance(entry, dict) and str(entry.get("id") or "").strip():
            out.append({"id": str(entry["id"]).strip()[:200],
                        "name": str(entry.get("display_name") or "").strip()[:200]})
    if not out:
        raise fail("ai_no_models")
    return out


# --- What the model is asked ----------------------------------------------------------------------------------------


def _body(found: Service, system: str, user: str, temperature: bool, max_out: int = MAX_OUT) -> dict[str, Any]:
    body: dict[str, Any] = {"model": found.model, "max_tokens": max_out}
    if temperature:
        body["temperature"] = 0.3
    if found.provider == "messages":
        body["system"] = system
        body["messages"] = [{"role": "user", "content": user}]
    else:
        body["messages"] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        body["stream"] = False
    return body


def _content_of(found: Service, data: Any) -> str:
    if found.provider == "messages":
        parts = data.get("content") if isinstance(data, dict) else None
        if not isinstance(parts, list):
            raise fail("ai_unreadable", 502)
        return "".join(part.get("text", "") for part in parts if isinstance(part, dict) and part.get("type") == "text")
    content = data["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str):
        raise fail("ai_unreadable", 502)
    return content


# --- The limits -----------------------------------------------------------------------------------------------------


class _Pace:
    """Requests per minute for one account. In memory: a restart forgets them, which is fine for a brake."""

    def __init__(self, per_minute: int) -> None:
        self._lock = threading.Lock()
        self._minute: dict[int, deque[float]] = {}
        self.per_minute = per_minute

    def take(self, account_id: int) -> None:
        moment = ticks()
        with self._lock:
            seen = self._minute.setdefault(account_id, deque())
            while seen and moment - seen[0] > 60:
                seen.popleft()
            if len(seen) >= self.per_minute:
                exc = fail("ai_too_often", 429)
                exc.headers = {"Retry-After": "60"}
                raise exc
            seen.append(moment)

    def forget(self) -> None:
        with self._lock:
            self._minute.clear()


operator_pace = _Pace(OPERATOR_PER_MINUTE)
_writing: set[Hashable] = set()
_writing_lock = threading.Lock()
#: The requests on the whole server at once; the tests put a smaller one in.
server_slots = threading.BoundedSemaphore(AT_ONCE)


@contextmanager
def _one_at_a_time(who: Hashable) -> Iterator[None]:
    """One request per person at a time (a double click makes one), and a few on the server at once."""
    with _writing_lock:
        if who in _writing:
            raise fail("ai_busy", 409)
        _writing.add(who)
    try:
        slots = server_slots
        if not slots.acquire(blocking=False):
            raise fail("ai_server_busy", 503)
        try:
            yield
        finally:
            slots.release()
    finally:
        with _writing_lock:
            _writing.discard(who)


def forget() -> None:
    """For the tests."""
    operator_pace.forget()
    with _writing_lock:
        _writing.clear()


# --- Asking ---------------------------------------------------------------------------------------------------------


def _ask(found: Service, system: str, user: str, what: str, max_out: int = MAX_OUT) -> str:
    """One request with the rules and the material; the text the model wrote."""
    path = "messages" if found.provider == "messages" else "chat/completions"
    answer = _exchange(found, "POST", path, what, TEXT_SECONDS,
                       body=lambda temperature: _body(found, system, user, temperature, max_out))
    try:
        content = _content_of(found, answer.json())
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise fail("ai_unreadable", 502) from exc
    if not content.strip():
        raise fail("ai_empty", 502)
    return content


def usable(db: Session, own_switch: bool) -> Service:
    """The service, or the reason there is none for this person (403 off, 409 not complete)."""
    if not own_switch:
        raise fail("ai_switched_off", 403)
    found = service(db)
    if found.provider not in WORKING:
        raise fail("ai_off", 403)
    if not found.complete:
        raise fail("ai_incomplete", 409)
    return found


PROBE_RULES = "You answer with a single word."
PROBE = "Answer with the single word OK."


def probe(db: Session, operator_id: int) -> float:
    """Asks the operator's service one tiny question with no document in it; the seconds it took."""
    found = service(db)
    if found.provider not in WORKING:
        raise fail("ai_off", 409)
    if not found.complete:
        raise fail("ai_incomplete", 409)
    with _one_at_a_time(("operator", operator_id)):
        operator_pace.take(operator_id)
        started = ticks()
        _ask(found, PROBE_RULES, PROBE, "probe", max_out=20)
        return round(ticks() - started, 1)
