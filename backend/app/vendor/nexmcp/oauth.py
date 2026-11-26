"""Connecting programs with OAuth (decision 6, every app), the strictest of the three forms the apps had (nexdeck's),
with the lifetimes of nexnotes and nexlore (decision 7):

- metadata: the protected resource (RFC 9728) names the app as its own authorization server (RFC 8414);
- registration (RFC 7591): public programs only, 1 to 10 return addresses, ``https://`` or ``http://`` to the own
  machine, never a fragment or a user in the address; 10 per sender and hour (IPv6 per /64), 30 a minute for the
  server, at most ``max_clients`` (only an old one nobody uses makes room);
- consent: PKCE with S256 only, the account chooses level, areas and extras on the app's page; a mistake never sends
  anybody to an address the program did not register;
- a code is good once and for ``code_minutes``; brought again, it ends what the first trade gave;
- an access token lasts ``access_hours``, the refresh token changes at every refresh, and one of the last
  ``spent_kept`` brought again ends the whole program; a program signs in again after ``refresh_days`` and after
  ``idle_days`` without a refresh;
- ``resource`` (RFC 8707) is checked where a program sends it, and may be missing (programs connected so far sent
  none to nexnotes and nexlore);
- a program may revoke its own token (RFC 7009).

Only SHA-256 hex of codes and tokens is stored. Everything is closed while MCP or "programs" is switched off."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from . import oauthcore
from .brake import BRAKE, HOUR, sender_of
from .config import AppConfig
from .errors import McpRefused, OAuthError
from .model import AccountId, Client, Code, Grant, Store

logger = logging.getLogger("nexmcp")

SCOPE = "mcp"
# The shared core (``oauthcore``, since 1.1.0) under the names this file had.
LOOPBACK = oauthcore.LOOPBACK
_VERIFIER = oauthcore.VERIFIER
digest = oauthcore.digest


def programs_open(config: AppConfig, store: Store) -> bool:
    """Whether programs may connect now: OAuth offered, MCP on, the operator's "programs" not off."""
    return config.oauth and bool(store.mcp_on()) and store.setting("programs") is not False


def resource_of(base: str, config: AppConfig) -> str:
    return f"{base}{config.mcp_path}"


def same_resource(given: str, expected: str) -> bool:
    return given.rstrip("/") == expected.rstrip("/")


# --- metadata -----------------------------------------------------------------------------------------------------


def resource_metadata(base: str, config: AppConfig) -> dict[str, Any]:
    return {
        "resource": resource_of(base, config),
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [SCOPE],
    }


def server_metadata(base: str, config: AppConfig) -> dict[str, Any]:
    oauth = f"{base}{config.oauth_prefix}"
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}{config.consent_path}",
        "token_endpoint": f"{oauth}/token",
        "registration_endpoint": f"{oauth}/register",
        "revocation_endpoint": f"{oauth}/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [SCOPE],
        "authorization_response_iss_parameter_supported": True,
    }


def challenge(base: str, config: AppConfig, store: Store) -> str:
    """The ``WWW-Authenticate`` of a 401: where a program learns to connect, while it may."""
    if programs_open(config, store):
        return f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource"'
    return "Bearer"


# --- registration -------------------------------------------------------------------------------------------------


def valid_redirect(uri: Any) -> bool:
    return oauthcore.valid_redirect(uri)


def _make_room(store: Store, config: AppConfig, now: datetime) -> bool:
    """Below ``max_clients``, or room made by removing programs nobody uses that are older than an hour."""
    known = store.clients()
    if len(known) < config.max_clients:
        return True
    idle = sorted(
        (client for client in known if not client.in_use and now - client.created_at > timedelta(hours=1)),
        key=lambda client: client.last_used_at or client.created_at,
    )
    for client in idle[: len(known) - config.max_clients + 1]:
        store.remove_client(client.id)
    return len(known) - len(idle[: len(known) - config.max_clients + 1]) < config.max_clients


def register(store: Store, config: AppConfig, body: Any, sender: str, now: datetime) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise OAuthError("invalid_client_metadata", "The registration must be a JSON object.")
    if body.get("token_endpoint_auth_method", "none") != "none":
        raise OAuthError(
            "invalid_client_metadata", "Only public clients with PKCE sign in here (token_endpoint_auth_method none)."
        )
    uris = body.get("redirect_uris")
    if not isinstance(uris, list) or not 1 <= len(uris) <= 10 or not all(valid_redirect(uri) for uri in uris):
        raise OAuthError(
            "invalid_redirect_uri", "1 to 10 return addresses, https:// or http:// to the own machine, no fragment."
        )
    grants = body.get("grant_types", ["authorization_code", "refresh_token"])
    if not isinstance(grants, list) or not set(grants) <= {"authorization_code", "refresh_token"}:
        raise OAuthError("invalid_client_metadata", "Only authorization_code and refresh_token.")
    responses = body.get("response_types", ["code"])
    if not isinstance(responses, list) or not set(responses) <= {"code"}:
        raise OAuthError("invalid_client_metadata", "Only the response type code.")
    name = body.get("client_name")
    name = " ".join(name.split())[:100] if isinstance(name, str) and name.strip() else "MCP client"
    who = f"register:{sender_of(sender)}"
    if not BRAKE.take(who, config.register_per_sender, HOUR) or not BRAKE.take(
        "register:all", config.register_per_minute
    ):
        raise OAuthError("slow_down", "Too many programs registered. Try again later.", 429)
    if not _make_room(store, config, now):
        logger.warning("MCP program registration refused: %d programs are registered and in use", config.max_clients)
        raise OAuthError("slow_down", "Too many programs are registered here.", 429)
    client = Client(id=secrets.token_urlsafe(24), name=name, redirect_uris=tuple(uris), created_at=now)
    store.add_client(client)
    store.commit()
    logger.info("MCP program registered")
    return {
        "client_id": client.id,
        "client_name": client.name,
        "redirect_uris": list(client.redirect_uris),
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_id_issued_at": int(now.timestamp()),
    }


# --- consent ------------------------------------------------------------------------------------------------------


def _checked(store: Store, config: AppConfig, params: dict[str, Any], base: str) -> Client:
    if not programs_open(config, store):
        raise McpRefused("programs_off")
    client = store.client(str(params.get("client_id") or ""))
    if client is None:
        raise McpRefused("client_unknown")
    if params.get("redirect_uri") not in client.redirect_uris:
        raise McpRefused("redirect_invalid")
    if params.get("response_type", "code") != "code":
        raise McpRefused("response_type")
    challenge_given = str(params.get("code_challenge") or "")
    if params.get("code_challenge_method") != "S256" or not _VERIFIER.fullmatch(challenge_given):
        raise McpRefused("pkce_required")
    resource = str(params.get("resource") or "")
    if resource and not same_resource(resource, resource_of(base, config)):
        raise McpRefused("resource_invalid")
    return client


def levels_allowed(config: AppConfig, store: Store) -> list[str]:
    found = store.setting("max_level")
    ceiling = found if found in config.levels else config.highest
    return [level for level in config.levels if config.at_least(ceiling, level)]


def consent_info(
    store: Store, config: AppConfig, account_id: AccountId, params: dict[str, Any], base: str
) -> dict[str, Any]:
    """What the consent page shows: the program, where it returns to, the levels, areas and extras to choose."""
    client = _checked(store, config, params, base)
    return {
        "app": config.app_name,
        "client": {"id": client.id, "name": client.name},
        "redirect_uri": params["redirect_uri"],
        "redirect_host": urlsplit(str(params["redirect_uri"])).netloc,
        "levels": levels_allowed(config, store),
        "level": config.levels[0],
        "areas": store.key_areas(account_id),
        "extras": list(config.extras),
        "ai_allowed": bool(store.ai_allowed(account_id)),
    }


def _back(redirect_uri: str, values: dict[str, str]) -> str:
    return oauthcore.back(redirect_uri, values)


def consent(
    store: Store,
    config: AppConfig,
    account_id: AccountId,
    body: dict[str, Any],
    base: str,
    now: datetime,
) -> str:
    """The account's answer; returns the address to send the browser to (the program's, with a code or a refusal)."""
    client = _checked(store, config, body, base)
    state = body.get("state")
    extra = {"state": str(state)} if isinstance(state, str) and state else {}
    if not body.get("allow"):
        logger.info("MCP program sign-in declined")
        return _back(body["redirect_uri"], {"error": "access_denied", **extra, "iss": base})
    if not store.ai_allowed(account_id):
        raise McpRefused("ai_not_allowed")
    level = body.get("level") or config.levels[0]
    if level not in levels_allowed(config, store):
        raise McpRefused("level_invalid")
    areas = body.get("areas")
    if areas is not None:
        own = {str(area["id"]): area["id"] for area in store.key_areas(account_id)}
        if not isinstance(areas, list) or not areas or not {str(area) for area in areas} <= set(own):
            raise McpRefused("areas_invalid")
        areas = [own[key] for key in own if key in {str(area) for area in areas}]
    options = body.get("options") or {}
    if not isinstance(options, dict) or not set(options) <= set(config.extras):
        raise McpRefused("extra_invalid")
    code = config.code_prefix + secrets.token_urlsafe(32)
    store.add_code(
        Code(
            code_hash=digest(code),
            client_id=client.id,
            account_id=account_id,
            redirect_uri=body["redirect_uri"],
            challenge=str(body["code_challenge"]),
            level=level,
            areas=areas,
            options={name: bool(options.get(name)) for name in config.extras},
            expires_at=now + timedelta(minutes=config.code_minutes),
            resource=str(body.get("resource") or ""),
        )
    )
    store.commit()
    logger.info("MCP program sign-in agreed level=%s", level)
    return _back(body["redirect_uri"], {"code": code, **extra, "iss": base})


# --- tokens -------------------------------------------------------------------------------------------------------


def _verifier_fits(verifier: str, challenge_given: str) -> bool:
    return oauthcore.verifier_fits(verifier, challenge_given)


def _grant(config: AppConfig, now: datetime) -> tuple[Grant, str, str]:
    made = oauthcore.new_tokens(config.access_prefix, config.refresh_prefix, config.access_hours, now)
    grant = Grant(
        access_hash=made.access_hash,
        access_prefix=made.access_shown,
        access_expires=made.access_expires,
        refresh_hash=made.refresh_hash,
    )
    return grant, made.access, made.refresh


def _answer(config: AppConfig, access: str, refresh: str) -> dict[str, Any]:
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": config.access_hours * 3600,
        "refresh_token": refresh,
        "scope": SCOPE,
    }


def token(store: Store, config: AppConfig, form: dict[str, str], base: str, now: datetime) -> dict[str, Any]:
    if not programs_open(config, store):
        raise OAuthError("access_denied", "Connecting programs is switched off here.", 403)
    client = store.client(form.get("client_id", ""))
    if client is None:
        raise OAuthError("invalid_client", "Unknown client.", 401)
    resource = form.get("resource", "")
    if resource and not same_resource(resource, resource_of(base, config)):
        raise OAuthError("invalid_target", "The program asks for access to something other than this app.")
    grant_type = form.get("grant_type", "")
    if grant_type == "authorization_code":
        return _trade_code(store, config, client, form, now)
    if grant_type == "refresh_token":
        return _refresh(store, config, client, form, now)
    raise OAuthError("unsupported_grant_type", "Only authorization_code and refresh_token.")


def _end_copy(store: Store, token_hash: str, what: str) -> None:
    """A spent code or refresh token brought again: somebody holds a copy, the whole program ends."""
    key_id = store.spent_by(token_hash)
    if key_id is not None:
        store.end_program(key_id)
        store.commit()
        logger.warning("MCP %s brought twice, program ended key_id=%s", what, key_id)


def _trade_code(store: Store, config: AppConfig, client: Client, form: dict[str, str], now: datetime) -> dict[str, Any]:
    code_hash = digest(form.get("code", ""))
    code = store.take_code(code_hash)
    store.commit()
    if code is None:
        _end_copy(store, code_hash, "code")
        raise OAuthError("invalid_grant", "The code is not valid (any more).")
    if (
        code.expires_at <= now
        or code.client_id != client.id
        or code.redirect_uri != form.get("redirect_uri", "")
        or not _verifier_fits(form.get("code_verifier", ""), code.challenge)
        or (code.resource and form.get("resource") and not same_resource(code.resource, form["resource"]))
    ):
        raise OAuthError("invalid_grant", "The code is not valid (any more).")
    if not store.account_may(code.account_id) or not store.ai_allowed(code.account_id):
        raise OAuthError("invalid_grant", "The account may not sign in now.")
    if not store.has_program(code.account_id, client.id) and store.count_keys(code.account_id) >= config.max_keys:
        raise OAuthError("invalid_grant", f"The account holds {config.max_keys} keys already. Revoke one first.")
    grant, access, refresh = _grant(config, now)
    key_id = store.program_signed_in(
        code.account_id, client, level=code.level, areas=code.areas, options=code.options, grant=grant, now=now
    )
    store.spend(key_id, code_hash, config.spent_kept)
    store.touch_client(client.id, now)
    store.commit()
    logger.info("MCP program tokens issued key_id=%s", key_id)
    return _answer(config, access, refresh)


def _refresh(store: Store, config: AppConfig, client: Client, form: dict[str, str], now: datetime) -> dict[str, Any]:
    brought = digest(form.get("refresh_token", ""))
    program = store.program_by_refresh(brought)
    if program is None or program.client_id != client.id:
        _end_copy(store, brought, "refresh token")
        raise OAuthError("invalid_grant", "The refresh token is not valid (any more).")
    if now - program.signed_in_at > timedelta(days=config.refresh_days) or now - program.refreshed_at > timedelta(
        days=config.idle_days
    ):
        raise OAuthError("invalid_grant", "The program has to sign in again.")
    if not store.account_may(program.account_id) or not store.ai_allowed(program.account_id):
        raise OAuthError("invalid_grant", "The account may not sign in now.")
    grant, access, refresh = _grant(config, now)
    store.program_refreshed(program.key_id, grant, now)
    store.spend(program.key_id, brought, config.spent_kept)
    store.touch_client(client.id, now)
    store.commit()
    logger.info("MCP program tokens refreshed key_id=%s", program.key_id)
    return _answer(config, access, refresh)


def revoke(store: Store, config: AppConfig, form: dict[str, str]) -> None:
    """RFC 7009: the program's own access or refresh token ends the program; anything else is ignored (the same
    answer either way)."""
    program = store.program_of_token(digest(form.get("token", "")))
    if program is None or program.client_id != form.get("client_id", ""):
        return
    store.end_program(program.key_id)
    store.commit()
    logger.info("MCP program revoked itself key_id=%s", program.key_id)
