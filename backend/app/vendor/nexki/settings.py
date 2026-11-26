"""The settings: the operator's service, the main switch, the way the AI is set up, the hosts of the own network, the
brakes; an account's own service and its own switch; and ``adopt``, which an app runs at every start so that an
installation updated from an older version keeps working as before (K2, K3, K4).

* **The key belongs to the address it was given for.** A new address or another interface without a new key forgets
  the stored one, or a changed address would carry the key to whatever host it names (nexpaper's rule, now in every
  app). A model list asked for with a typed address gets the stored key only when the address is the stored one.
* **A new address is checked when it is saved**, so that the operator hears at once that it lies in the wrong network;
  every request checks again.
* **Switched off is not deleted:** keys, models and own accesses stay while the main switch is off.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from . import net
from .brake import today
from .config import APIS, MODES, AppConfig
from .errors import AiRefused
from .model import AccountId, OwnAccess, Service, Store

logger = logging.getLogger("nexki")

#: The longest list of hosts in the own network.
MAX_HOSTS = 50
_HOST = re.compile(r"^(?:\[[0-9a-f:.]+\]|[a-z0-9.-]+)(?::\d{1,5})?$")


def parse_hosts(value: Any) -> list[str]:
    """The operator's hosts in the own network: a list or a text with one per line (or comma), ``host`` or
    ``host:port``, lower case, each once, at most ``MAX_HOSTS``."""
    parts = value if isinstance(value, list) else str(value or "").replace(",", "\n").splitlines()
    hosts: list[str] = []
    for part in parts:
        part = str(part).strip().lower()
        if not part:
            continue
        if not _HOST.match(part):
            raise AiRefused("ai_hosts_invalid")
        hosts.append(part)
    return list(dict.fromkeys(hosts))[:MAX_HOSTS]


def clean_url(url: str) -> str:
    """The base address with its slash at the end (``urljoin(".../v1", "models")`` drops the ``v1``)."""
    url = (url or "").strip()
    if not url:
        raise AiRefused("ai_address_missing")
    net.check_url(url)
    return url if url.endswith("/") else url + "/"


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _api(value: Any) -> str:
    return "openai" if value == "local" else str(value or "")  # nexpaper's and nexdiary's "local" is the OpenAI form


def mode(store: Store, config: AppConfig) -> str:
    found = store.setting("mode")
    return found if found in config.modes else "shared"


def enabled(store: Store) -> bool:
    return bool(store.setting("enabled"))


def hosts(store: Store) -> list[str]:
    try:
        return parse_hosts(store.setting("hosts") or [])
    except AiRefused:
        return []


def limits(store: Store, config: AppConfig) -> dict[str, int]:
    def pick(name: str, default: int) -> int:
        value = store.setting(name)
        return int(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else default

    return {
        "per_minute": max(1, pick("per_minute", config.per_minute)),
        "per_day": pick("per_day", config.per_day),
        "server_day": pick("server_day", config.server_day),
    }


def used_today(store: Store) -> int:
    stored = store.setting("day")
    if isinstance(stored, dict) and stored.get("day") == today():
        return int(stored.get("count") or 0)
    return 0


def operator_service(store: Store, config: AppConfig) -> Service:
    key = store.unseal(str(store.setting("key") or ""), config.operator_key_context) if store.setting("key") else ""
    return Service(_api(store.setting("api")), str(store.setting("url") or ""), str(store.setting("model") or ""),
                   key, operator=True)


def own_service(store: Store, config: AppConfig, account_id: AccountId) -> Service | None:
    access = store.own_access(account_id)
    if access is None:
        return None
    key = store.unseal(access.key, config.account_key_context(account_id)) if access.key else ""
    return Service(_api(access.api), access.url, access.model, key, operator=False)


# --- The operator ---------------------------------------------------------------------------------------------------


def operator_view(store: Store, config: AppConfig) -> dict[str, Any]:
    found = operator_service(store, config)
    return {
        "enabled": enabled(store),
        "mode": mode(store, config),
        "modes": list(config.modes),
        "api": found.api,
        "url": found.url,
        "model": found.model,
        "key_set": bool(store.setting("key")),
        "complete": found.complete,
        "hosts": hosts(store),
        **limits(store, config),
        "used_today": used_today(store),
        "messages_url": config.messages_url,
    }


def save_operator(
    store: Store,
    config: AppConfig,
    *,
    resolver: Callable[[str, int], list[str]],
    enabled_now: bool | None = None,
    mode_now: str | None = None,
    api: str | None = None,
    url: str | None = None,
    model: str | None = None,
    key: str | None = None,
    hosts_now: Any = None,
    per_minute: int | None = None,
    per_day: int | None = None,
    server_day: int | None = None,
) -> dict[str, Any]:
    """Changes what was sent; what is left out stays. An empty address or model takes the service away."""
    before = operator_service(store, config)
    if mode_now is not None:
        if mode_now not in MODES or mode_now not in config.modes:
            raise AiRefused("ai_mode_unknown")
        store.set_setting("mode", mode_now)
    if api is not None and api not in APIS:
        raise AiRefused("ai_api_unknown")
    next_api = api if api is not None else before.api
    next_url = before.url
    if url is not None:
        next_url = clean_url(url) if url.strip() else ""
        if next_url:
            # Checked now as well as at every request: the operator hears at once that it lies in the wrong place.
            net.place(next_url, operator=True, listed=(), resolver=resolver)
        store.set_setting("url", next_url)
    if api is not None:
        store.set_setting("api", api)
    if model is not None:
        store.set_setting("model", " ".join(model.split())[:200])
    moved = (next_api != before.api) or (next_url != before.url)
    if key is not None:
        store.set_setting("key", store.seal(key.strip(), config.operator_key_context) if key.strip() else "")
    elif moved and store.setting("key"):
        store.set_setting("key", "")
    if hosts_now is not None:
        store.set_setting("hosts", parse_hosts(hosts_now))
    for name, value in (("per_minute", per_minute), ("per_day", per_day), ("server_day", server_day)):
        if value is not None:
            store.set_setting(name, max(1 if name == "per_minute" else 0, min(int(value), 1_000_000)))
    if enabled_now is not None:
        store.set_setting("enabled", bool(enabled_now))
    store.commit()
    logger.info("The operator changed the AI settings")
    return operator_view(store, config)


# --- An account -----------------------------------------------------------------------------------------------------


def own_view(store: Store, config: AppConfig, account_id: AccountId) -> dict[str, Any] | None:
    access = store.own_access(account_id)
    if access is None:
        return None
    return {"api": _api(access.api), "url": access.url, "model": access.model, "key_set": bool(access.key)}


def save_own(
    store: Store,
    config: AppConfig,
    account_id: AccountId,
    *,
    resolver: Callable[[str, int], list[str]],
    api: str | None = None,
    url: str | None = None,
    model: str | None = None,
    key: str | None = None,
) -> None:
    """The account's own service (mode "own" only). Empty address and model take it away; the same rule for the key
    as the operator's."""
    if mode(store, config) != "own":
        raise AiRefused("ai_own_off")
    before = store.own_access(account_id) or OwnAccess("openai", "", "", "")
    if api is not None and api not in APIS:
        raise AiRefused("ai_api_unknown")
    next_api = api if api is not None else _api(before.api)
    next_url = before.url
    if url is not None:
        next_url = clean_url(url) if url.strip() else ""
        if next_url:
            net.place(next_url, operator=False, listed=hosts(store), resolver=resolver)
    next_model = " ".join(model.split())[:200] if model is not None else before.model
    context = config.account_key_context(account_id)
    if key is not None:
        sealed = store.seal(key.strip(), context) if key.strip() else ""
    elif next_api != _api(before.api) or next_url != before.url:
        sealed = ""
    else:
        sealed = before.key
    if not next_url and not next_model:
        store.set_own_access(account_id, None)
    else:
        store.set_own_access(account_id, OwnAccess(next_api, next_url, next_model, sealed))
    store.commit()
    logger.info("An account changed its own AI service")


# --- After an update ------------------------------------------------------------------------------------------------


def adopt(store: Store, config: AppConfig, *, resolver: Callable[[str, int], list[str]] = net.resolve) -> list[str]:
    """Run at every start; changes only what was never stored, so a second run does nothing. Returns what it did.

    * The way (K2): an installation whose accounts set up their own services keeps "own" (nexmail, nexlore); every
      other one starts with the operator's service for all.
    * The main switch (K3): never stored, it is on where the operator's service is complete (nexpaper, nexdiary had no
      switch), else off (a new installation: closed). Apps that had a switch (nexmail ``ki_erlaubt``, nexlore
      ``ai_allowed``) map it to "enabled" with their old default, so it is never "never stored" there.
    * The hosts (K4): once, the host of every own access whose address lies in the own network goes onto the list, so
      that an account's Ollama at home keeps working; a name that does not resolve now is passed over (logged)."""
    done: list[str] = []
    urls = [url for url in store.own_access_urls() if url]
    if store.setting("mode") is None:
        chosen = "own" if urls and "own" in config.modes else "shared"
        store.set_setting("mode", chosen)
        done.append(f"mode={chosen}")
    if store.setting("enabled") is None:
        # Only the operator's service opens it: own accesses never worked without an operator's yes (nexmail's and
        # nexlore's switch, which the app maps to "enabled", stays as it was).
        on = operator_service(store, config).complete
        store.set_setting("enabled", on)
        done.append(f"enabled={on}")
    if not store.setting("hosts_adopted"):
        listed = hosts(store)
        for url in urls:
            try:
                parts = urlsplit(url)
                host = (parts.hostname or "").lower()
                port = net.port_of(url)
                addresses = resolver(host, port)
            except (ValueError, net.Unreachable):
                logger.info("An own AI access was not resolved while adopting its host")
                continue
            if addresses and not any(net.public(address) for address in addresses):
                shown = f"[{host}]" if ":" in host else host
                entry = f"{shown}:{port}"
                if entry not in listed:
                    listed.append(entry)
                    done.append(f"host={entry}")
        store.set_setting("hosts", listed[:MAX_HOSTS])
        store.set_setting("hosts_adopted", True)
    if done:
        store.commit()
        logger.info("AI settings adopted after an update: %s", ", ".join(item.split("=")[0] for item in done))
    return done
