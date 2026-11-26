"""Connecting two nex apps, both sides in one place (decision V3: both directions are one connection).

The app where the account clicks "Mit <partner> verbinden" **starts** (``start``): it checks the partner's description,
keeps a ``state`` and a PKCE verifier, and sends the browser to the partner's consent page. The partner **asks**
(``consent_info``, ``consent``): it checks the app that asks by its own description (the return address must be that
app's ``/connect/return``), shows what each side may do at the other, and answers with a code. Back at the start
(``come_back``) the app trades the code at the partner's ``/api/connect/token`` and hands over, in the same request,
the tokens it made for the partner. So each side holds an access and a refresh token of the other, and keeps only
hashes of what it gave; a side that uses nothing still holds one, which opens the module's ``hello`` and ``revoke``.

Afterwards a side **calls** the other with ``call`` (fresh access on its own, the state of the card kept up to date),
and the other **checks** the token with ``authenticate``. Either side **ends** it with ``disconnect``: the partner
hears it at ``/api/connect/revoke`` and drops its side too; while it cannot be reached, the revocation waits
(``retry_waiting``)."""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

from . import reach
from .config import CONSENT_PAGE, PREFIX, PROTOCOL, RETURN_PAGE, WELL_KNOWN, AppConfig
from .errors import GrantError, Refused
from .model import AccountId, Caller, Code, Connection, Pending
from .shared import BRAKE, oauthcore

logger = logging.getLogger("nexverbinden")

#: An access token is refreshed when it ends within this.
REFRESH_EARLY = timedelta(seconds=60)
#: "Last used" is written at most once a minute.
TOUCH_EVERY = timedelta(seconds=60)
MAX_STATE = 500
MAX_TOKEN = 300
MAX_NAME = 200


def connections_on(store: Any) -> bool:
    """Decision V1 (7a): the operator's own switch, on unless switched off."""
    return store.setting("connections") is not False


def _base(base: str) -> str:
    return base.strip().rstrip("/")


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


# --- the description of an app ----------------------------------------------------------------------------------------


def describe(config: AppConfig, store: Any) -> dict[str, Any]:
    """``GET /.well-known/nex-app``: who answers here, and whether it connects now."""
    return {
        "app": config.app_name,
        "version": config.version,
        "protocol": PROTOCOL,
        "connect": connections_on(store),
        "consent": CONSENT_PAGE,
        "return": RETURN_PAGE,
        "token": f"{PREFIX}/token",
        "revoke": f"{PREFIX}/revoke",
    }


def _ask(config: AppConfig, store: Any, base: str, method: str, path: str, **sent: Any) -> reach.Answer:
    seconds = sent.pop("seconds", config.seconds)
    return reach.ask(
        base,
        method,
        path,
        local_allowed=bool(store.local_allowed()),
        agent=config.user_agent,
        seconds=seconds,
        connect_seconds=min(config.connect_seconds, seconds),
        limit=config.max_answer,
        **sent,
    )


def partner_description(config: AppConfig, store: Any, base: str) -> dict[str, Any]:
    """The description at ``base``, checked: ``partner_too_old`` without one, ``unreachable`` when nothing came."""
    try:
        answer = _ask(config, store, base, "GET", WELL_KNOWN, seconds=config.describe_seconds)
    except reach.Unreachable:
        raise Refused("unreachable") from None
    data = answer.data
    if answer.status != 200 or not isinstance(data, dict) or not isinstance(data.get("app"), str):
        raise Refused("partner_too_old")
    if not isinstance(data.get("protocol"), int) or data["protocol"] < PROTOCOL:
        raise Refused("partner_too_old")
    return data


# --- the side that starts ---------------------------------------------------------------------------------------------


def _own_areas(store: Any, account_id: AccountId, chosen: Any) -> list[Any] | None:
    """``None`` (all, also later ones) or a non-empty part of the account's areas, in the app's order."""
    if chosen is None:
        return None
    own = {str(area["id"]): area["id"] for area in store.areas(account_id)}
    if not isinstance(chosen, list) or not chosen or not {str(area) for area in chosen} <= set(own):
        raise Refused("areas_invalid")
    wanted = {str(area) for area in chosen}
    return [own[key] for key in own if key in wanted]


def start(
    store: Any,
    config: AppConfig,
    account_id: AccountId,
    partner: str,
    address: str,
    base: str,
    now: datetime,
    *,
    areas: Any = None,
) -> str:
    """The account clicked "Mit <partner> verbinden": the address of the partner's consent page to send it to."""
    if not connections_on(store):
        raise Refused("connections_off")
    if partner not in config.usable:
        raise Refused("partner_unknown")
    url = reach.clean_url(address)
    # Only what goes out counts: a mistyped address costs nothing.
    if not BRAKE.take(f"verbinden:start:{account_id}", config.starts_per_minute):
        raise Refused("slow_down")
    found = partner_description(config, store, url)
    if found["app"] != partner:
        raise Refused("wrong_app")
    if found.get("connect") is False:
        raise Refused("partner_off")
    granted = _own_areas(store, account_id, areas)
    verifier = oauthcore.new_verifier()
    state = secrets.token_urlsafe(32)
    store.add_pending(
        Pending(
            state_hash=oauthcore.digest(state),
            account_id=account_id,
            partner=partner,
            partner_base=url,
            verifier=store.seal(verifier),
            areas_granted=granted,
            created_at=now,
        )
    )
    store.commit()
    own = _base(base)
    logger.info("connection with %s started", partner)
    query = {
        "client_id": own,
        "redirect_uri": own + RETURN_PAGE,
        "state": state,
        "code_challenge": oauthcore.challenge_of(verifier),
        "code_challenge_method": "S256",
    }
    return f"{url}{CONSENT_PAGE}?{urlencode(query)}"


def _areas_named(store: Any, account_id: AccountId, chosen: list[Any] | None) -> list[dict[str, Any]] | None:
    if chosen is None:
        return None
    keys = {str(area) for area in chosen}
    return [{"id": area["id"], "name": area["name"]} for area in store.areas(account_id) if str(area["id"]) in keys]


def _held(store: Any, access: str, refresh: str, expires: datetime, own_base: str) -> str:
    return store.seal(
        json.dumps({"access": access, "refresh": refresh, "expires": expires.isoformat(), "own": own_base})
    )


def _text(value: Any, size: int) -> str:
    return value if isinstance(value, str) and 0 < len(value) <= size else ""


def come_back(
    store: Any,
    config: AppConfig,
    account_id: AccountId,
    code: str,
    state: str,
    iss: str,
    base: str,
    now: datetime,
) -> Connection:
    """The browser is back from the partner's consent page: trade the code, hand over the partner's tokens, keep
    both."""
    pending = store.take_pending(oauthcore.digest(state or ""))
    store.commit()
    if (
        pending is None
        or pending.account_id != account_id
        or now - pending.created_at > timedelta(minutes=config.code_minutes)
        or (iss and not reach.same_place(iss, pending.partner_base))
        or not _text(code, MAX_TOKEN)
    ):
        raise Refused("return_invalid")
    own = _base(base)
    theirs = oauthcore.new_tokens(config.access_prefix, config.refresh_prefix, config.access_hours, now)
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": store.unseal(pending.verifier),
        "client_id": own,
        "redirect_uri": own + RETURN_PAGE,
        "reverse_access": theirs.access,
        "reverse_refresh": theirs.refresh,
        "reverse_expires_in": str(config.access_hours * 3600),
        "reverse_account": store.account_name(account_id),
        "reverse_areas": json.dumps(_areas_named(store, account_id, pending.areas_granted)),
        "reverse_version": config.version,
    }
    try:
        answer = _ask(config, store, pending.partner_base, "POST", f"{PREFIX}/token", form=form)
    except reach.Unreachable:
        raise Refused("unreachable") from None
    data = answer.data if isinstance(answer.data, dict) else {}
    if answer.status != 200:
        logger.info("%s did not confirm the connection (%s)", pending.partner, answer.code or answer.status)
        raise Refused("partner_off" if answer.code == "connections_off" else "consent_failed")
    access, refresh = _text(data.get("access_token"), MAX_TOKEN), _text(data.get("refresh_token"), MAX_TOKEN)
    connection_id = _text(data.get("connection_id"), 100)
    lasts = data.get("expires_in")
    if not access or not refresh or not connection_id or not isinstance(lasts, int) or not 60 <= lasts <= 86400:
        raise Refused("consent_failed")
    areas_used = data.get("areas")
    earlier = store.connection(account_id, pending.partner)
    if earlier is not None:
        _end(store, config, earlier, now)
    made = Connection(
        id=connection_id,
        account_id=account_id,
        partner=pending.partner,
        partner_base=pending.partner_base,
        partner_account=_text(data.get("account"), MAX_NAME) or "?",
        uses=config.catalog.uses(config.app_name, pending.partner),
        grants=config.catalog.uses(pending.partner, config.app_name),
        areas_granted=pending.areas_granted,
        areas_used=_area_list(areas_used),
        held=_held(store, access, refresh, now + timedelta(seconds=lasts), own),
        issued_access_hash=theirs.access_hash,
        issued_refresh_hash=theirs.refresh_hash,
        issued_access_expires=theirs.access_expires,
        created_at=now,
        used_at=now,
        ok_at=now,
        partner_version=_text(data.get("version"), 40),
    )
    store.save(made)
    store.commit()
    logger.info("connected with %s connection=%s", pending.partner, made.id)
    return made


def _area_list(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    return [
        {"id": area.get("id"), "name": str(area.get("name"))[:MAX_NAME]}
        for area in raw[:500]
        if isinstance(area, dict) and "id" in area
    ]


# --- the side that is asked: consent ---------------------------------------------------------------------------------


def _checked_asker(store: Any, config: AppConfig, params: dict[str, Any], base: str) -> tuple[str, str, str]:
    """The app that asks (its name, its address) and its return address, checked; or ``Refused``."""
    if not connections_on(store):
        raise Refused("connections_off")
    try:
        client = reach.clean_url(str(params.get("client_id") or ""))
    except Refused:
        raise Refused("client_invalid") from None
    redirect = str(params.get("redirect_uri") or "")
    own_scheme = urlsplit(_base(base)).scheme
    host = urlsplit(client).hostname or ""
    http_hosts = (*oauthcore.LOOPBACK, host) if own_scheme == "http" else oauthcore.LOOPBACK
    if redirect != client + RETURN_PAGE or not oauthcore.valid_redirect(redirect, http_hosts=http_hosts):
        raise Refused("redirect_invalid")
    challenge = str(params.get("code_challenge") or "")
    if params.get("code_challenge_method") != "S256" or not oauthcore.VERIFIER.fullmatch(challenge):
        raise Refused("pkce_required")
    state = params.get("state")
    if not isinstance(state, str) or not 0 < len(state) <= MAX_STATE:
        raise Refused("client_invalid")
    found = partner_description(config, store, client)
    if found["app"] not in config.partners:
        raise Refused("client_invalid")
    if found.get("connect") is False:
        raise Refused("partner_off")
    return found["app"], client, redirect


def _words_of(config: AppConfig, granted_by: str, purposes: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "id": purpose,
            "level": config.catalog.purpose(granted_by, purpose).level,
            "areas": config.catalog.purpose(granted_by, purpose).areas,
        }
        for purpose in purposes
    ]


def consent_info(store: Any, config: AppConfig, account_id: AccountId, params: dict[str, Any], base: str) -> dict:
    """What the consent page shows: the app that asks, what it may do here and what this app gets there."""
    asker, client, _ = _checked_asker(store, config, params, base)
    theirs = config.catalog.uses(asker, config.app_name)
    mine = config.catalog.uses(config.app_name, asker)
    with_areas = any(config.catalog.purpose(config.app_name, purpose).areas for purpose in theirs)
    return {
        "app": config.app_name,
        "partner": asker,
        "partner_host": urlsplit(client).netloc,
        "account": store.account_name(account_id),
        "partner_may": _words_of(config, config.app_name, theirs),
        "app_may": _words_of(config, asker, mine),
        "areas": [{"id": area["id"], "name": area["name"]} for area in store.areas(account_id)] if with_areas else [],
        "replaces": store.connection(account_id, asker) is not None,
    }


def consent(
    store: Any, config: AppConfig, account_id: AccountId, body: dict[str, Any], base: str, now: datetime
) -> str:
    """The account's answer; the address to send the browser to (the asking app's return, with a code or a no)."""
    asker, client, redirect = _checked_asker(store, config, body, base)
    state = str(body["state"])
    own = _base(base)
    if not body.get("allow"):
        logger.info("connection with %s declined", asker)
        return oauthcore.back(redirect, {"error": "access_denied", "state": state, "iss": own})
    granted = _own_areas(store, account_id, body.get("areas"))
    code = config.code_prefix + secrets.token_urlsafe(32)
    store.add_code(
        Code(
            code_hash=oauthcore.digest(code),
            account_id=account_id,
            partner=asker,
            partner_base=client,
            redirect_uri=redirect,
            challenge=str(body["code_challenge"]),
            areas_granted=granted,
            expires_at=now + timedelta(minutes=config.code_minutes),
        )
    )
    store.commit()
    logger.info("connection with %s agreed", asker)
    return oauthcore.back(redirect, {"code": code, "state": state, "iss": own})


# --- the side that is asked: tokens ----------------------------------------------------------------------------------


def _answer(config: AppConfig, connection: Connection, access: str, refresh: str, store: Any) -> dict[str, Any]:
    return {
        "connection_id": connection.id,
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "Bearer",
        "expires_in": config.access_hours * 3600,
        "account": store.account_name(connection.account_id),
        "areas": _areas_named(store, connection.account_id, connection.areas_granted),
        "app": config.app_name,
        "version": config.version,
    }


def token(store: Any, config: AppConfig, form: dict[str, str], base: str, now: datetime) -> dict[str, Any]:
    """``POST /api/connect/token``: a code traded (with the asking app's tokens for this one), or a refresh."""
    if not connections_on(store):
        raise GrantError("connections_off", "Connections are switched off here.", 403)
    grant_type = form.get("grant_type", "")
    if grant_type == "authorization_code":
        return _trade(store, config, form, base, now)
    if grant_type == "refresh_token":
        return _refresh(store, config, form, now)
    raise GrantError("unsupported_grant_type", "Only authorization_code and refresh_token.")


def _end_copy(store: Any, token_hash: str, what: str) -> None:
    """A spent code or refresh token brought again: somebody holds a copy, the connection ends."""
    connection_id = store.spent_by(token_hash)
    if connection_id is not None:
        store.remove(connection_id)
        store.commit()
        logger.warning("connection %s brought twice, connection ended connection=%s", what, connection_id)


def _trade(store: Any, config: AppConfig, form: dict[str, str], base: str, now: datetime) -> dict[str, Any]:
    code_hash = oauthcore.digest(form.get("code", ""))
    code = store.take_code(code_hash)
    store.commit()
    if code is None:
        _end_copy(store, code_hash, "code")
        raise GrantError("invalid_grant", "The code is not valid (any more).")
    if (
        code.expires_at <= now
        or not reach.same_place(form.get("client_id", ""), code.partner_base)
        or form.get("redirect_uri", "") != code.redirect_uri
        or not oauthcore.verifier_fits(form.get("code_verifier", ""), code.challenge)
    ):
        raise GrantError("invalid_grant", "The code is not valid (any more).")
    if not store.account_may(code.account_id):
        raise GrantError("account_resting", "The account may not connect now.")
    reverse_access, reverse_refresh = (
        _text(form.get("reverse_access"), MAX_TOKEN),
        _text(form.get("reverse_refresh"), MAX_TOKEN),
    )
    try:
        lasts = int(form.get("reverse_expires_in", ""))
        areas_used = json.loads(form.get("reverse_areas") or "null")
    except ValueError:
        raise GrantError("invalid_request", "The tokens for this app are missing.") from None
    if not reverse_access or not reverse_refresh or not 60 <= lasts <= 86400:
        raise GrantError("invalid_request", "The tokens for this app are missing.")
    earlier = store.connection(code.account_id, code.partner)
    if earlier is not None:
        # The asking app replaces its side as well: the earlier tokens on both sides end here.
        store.remove(earlier.id)
    made_tokens = oauthcore.new_tokens(config.access_prefix, config.refresh_prefix, config.access_hours, now)
    made = Connection(
        id=secrets.token_urlsafe(18),
        account_id=code.account_id,
        partner=code.partner,
        partner_base=code.partner_base,
        partner_account=_text(form.get("reverse_account"), MAX_NAME) or "?",
        uses=config.catalog.uses(config.app_name, code.partner),
        grants=config.catalog.uses(code.partner, config.app_name),
        areas_granted=code.areas_granted,
        areas_used=_area_list(areas_used),
        held=_held(store, reverse_access, reverse_refresh, now + timedelta(seconds=lasts), _base(base)),
        issued_access_hash=made_tokens.access_hash,
        issued_refresh_hash=made_tokens.refresh_hash,
        issued_access_expires=made_tokens.access_expires,
        created_at=now,
        used_at=now,
        ok_at=now,
        partner_version=_text(form.get("reverse_version"), 40),
    )
    store.save(made)
    store.spend(made.id, code_hash, config.spent_kept)
    store.commit()
    logger.info("connection with %s confirmed connection=%s", code.partner, made.id)
    return _answer(config, made, made_tokens.access, made_tokens.refresh, store)


def _refresh(store: Any, config: AppConfig, form: dict[str, str], now: datetime) -> dict[str, Any]:
    brought = oauthcore.digest(form.get("refresh_token", ""))
    connection = store.by_issued_refresh(brought)
    if connection is None:
        _end_copy(store, brought, "refresh token")
        raise GrantError("invalid_grant", "The refresh token is not valid (any more).")
    if not reach.same_place(form.get("client_id", ""), connection.partner_base):
        raise GrantError("invalid_grant", "The refresh token is not valid (any more).")
    if not store.account_may(connection.account_id):
        raise GrantError("account_resting", "The account rests on this side.")
    if now - (connection.used_at or connection.created_at) > timedelta(days=config.idle_days):
        raise GrantError("connection_resting", "The connection was not used for a long time. Connect again.")
    made = oauthcore.new_tokens(config.access_prefix, config.refresh_prefix, config.access_hours, now)
    fresh = replace(
        connection,
        issued_access_hash=made.access_hash,
        issued_refresh_hash=made.refresh_hash,
        issued_access_expires=made.access_expires,
        used_at=now,
    )
    store.save(fresh)
    store.spend(connection.id, brought, config.spent_kept)
    store.commit()
    return _answer(config, fresh, made.access, made.refresh, store)


def revoke(store: Any, form: dict[str, str]) -> None:
    """``POST /api/connect/revoke`` (RFC 7009): a token this app gave ends the whole connection on this side; anything
    else is ignored (the same answer either way)."""
    brought = oauthcore.digest(form.get("token", ""))
    connection = store.by_issued_refresh(brought) or store.by_issued_access(brought)
    if connection is None:
        return
    client = form.get("client_id", "")
    if client and not reach.same_place(client, connection.partner_base):
        return
    store.remove(connection.id)
    store.commit()
    logger.info("%s ended the connection connection=%s", connection.partner, connection.id)


# --- checking a token of a partner ------------------------------------------------------------------------------------


def authenticate(store: Any, config: AppConfig, token_value: str | None, now: datetime) -> Caller:
    """The connection behind a token a partner brings (``Authorization: Bearer``), or ``Refused``: ``token_invalid``
    (401), ``connections_off`` (403), ``account_resting`` (401, the account is blocked or deleted: it rests, E41)."""
    if not token_value or not token_value.startswith(config.access_prefix):
        raise Refused("token_invalid")
    connection = store.by_issued_access(oauthcore.digest(token_value))
    if connection is None or connection.issued_access_expires <= now:
        raise Refused("token_invalid")
    if not connections_on(store):
        raise Refused("connections_off")
    if not store.account_may(connection.account_id):
        raise Refused("account_resting")
    if connection.used_at is None or now - connection.used_at >= TOUCH_EVERY:
        store.save(replace(connection, used_at=now))
        store.commit()
    return Caller(
        account_id=connection.account_id,
        connection_id=connection.id,
        partner=connection.partner,
        purposes=connection.grants,
        areas=connection.areas_granted,
        level=config.catalog.level(config.app_name, connection.grants),
    )


def require(caller: Caller, purpose: str) -> None:
    """For the app's routes: the connection must allow ``purpose`` (else 403 ``purpose_missing``)."""
    if not caller.may(purpose):
        raise Refused("purpose_missing")


# --- calling the partner ----------------------------------------------------------------------------------------------


def _mark(store: Any, connection: Connection, state: str, now: datetime, problem: str | None = None) -> Connection:
    if state == "connected":
        changed = replace(connection, state=state, ok_at=now, stale_since=None, problem=None)
    elif state == "unreachable":
        changed = replace(connection, state=state, stale_since=connection.stale_since or now, problem="unreachable")
    else:
        changed = replace(connection, state=state, problem=problem or state)
    store.save(changed)
    store.commit()
    return changed


def _state_of_refusal(code: str) -> str:
    if code in ("account_resting", "connection_resting"):
        return "resting"
    if code == "connections_off":
        return "off"
    return "refused"


def _held_of(store: Any, connection: Connection) -> dict[str, str]:
    return json.loads(store.unseal(connection.held))


def _fresh_access(store: Any, config: AppConfig, connection: Connection, now: datetime, *, force: bool = False) -> str:
    held = _held_of(store, connection)
    if not force and datetime.fromisoformat(held["expires"]) - now > REFRESH_EARLY:
        return held["access"]
    form = {"grant_type": "refresh_token", "refresh_token": held["refresh"], "client_id": held["own"]}
    try:
        answer = _ask(config, store, connection.partner_base, "POST", f"{PREFIX}/token", form=form)
    except reach.Unreachable:
        _mark(store, connection, "unreachable", now)
        raise Refused("unreachable") from None
    data = answer.data if isinstance(answer.data, dict) else {}
    access, refresh = _text(data.get("access_token"), MAX_TOKEN), _text(data.get("refresh_token"), MAX_TOKEN)
    lasts = data.get("expires_in")
    if answer.status != 200 or not access or not refresh or not isinstance(lasts, int):
        state = _state_of_refusal(answer.code)
        _mark(store, connection, state, now, answer.code or None)
        raise Refused(state if state != "off" else "partner_off")
    renewed = replace(connection, held=_held(store, access, refresh, now + timedelta(seconds=lasts), held["own"]))
    store.save(renewed)
    store.commit()
    return access


def call(
    store: Any,
    config: AppConfig,
    account_id: AccountId,
    partner: str,
    method: str,
    path: str,
    now: datetime,
    *,
    body: Any = None,
    params: dict[str, str] | None = None,
) -> reach.Answer:
    """One request to the partner (``path`` from its root, ``/api/v1/tasks``) with the connection's token: refreshed on
    its own, the card's state kept. Raises ``Refused`` with ``not_connected``, ``unreachable`` (the last state stays
    and the card says since when), ``refused``, ``resting`` or ``partner_off``; any other answer comes back as it is."""
    connection = store.connection(account_id, partner)
    if connection is None:
        raise Refused("not_connected")
    for attempt in (1, 2):
        access = _fresh_access(store, config, connection, now, force=attempt == 2)
        connection = store.connection(account_id, partner) or connection
        try:
            answer = _ask(config, store, connection.partner_base, method, path, bearer=access, body=body, params=params)
        except reach.Unreachable:
            _mark(store, connection, "unreachable", now)
            raise Refused("unreachable") from None
        if answer.status == 401 and answer.code != "account_resting" and attempt == 1:
            continue
        if answer.status in (401, 403) and answer.code in ("token_invalid", "account_resting", "connections_off"):
            state = _state_of_refusal(answer.code)
            _mark(store, connection, state, now, answer.code)
            raise Refused(state if state != "off" else "partner_off")
        if answer.status == 401:
            _mark(store, connection, "refused", now, answer.code or "token_invalid")
            raise Refused("refused")
        _mark(store, connection, "connected", now)
        return answer
    raise Refused("refused")  # pragma: no cover (the loop always returns or raises)


def check(store: Any, config: AppConfig, account_id: AccountId, partner: str, now: datetime) -> Connection:
    """ "Jetzt prüfen": the partner's ``hello`` with the connection; the connection as it stands afterwards."""
    if not BRAKE.take(f"verbinden:check:{account_id}", config.starts_per_minute):
        raise Refused("slow_down")
    try:
        answer = call(store, config, account_id, partner, "GET", f"{PREFIX}/hello", now)
    except Refused as refusal:
        if refusal.code == "not_connected":
            raise
        found = store.connection(account_id, partner)
        if found is None:
            raise
        return found
    connection = store.connection(account_id, partner)
    assert connection is not None
    if isinstance(answer.data, dict):
        connection = replace(
            connection,
            partner_account=_text(answer.data.get("account"), MAX_NAME) or connection.partner_account,
            partner_version=_text(answer.data.get("version"), 40) or connection.partner_version,
        )
        store.save(connection)
        store.commit()
    return connection


def hello(store: Any, config: AppConfig, caller: Caller) -> dict[str, Any]:
    """``GET /api/connect/hello``: the partner checks the connection ("Jetzt prüfen")."""
    return {
        "app": config.app_name,
        "version": config.version,
        "connection": caller.connection_id,
        "account": store.account_name(caller.account_id),
    }


# --- ending -----------------------------------------------------------------------------------------------------------


def _end(store: Any, config: AppConfig, connection: Connection, now: datetime) -> None:
    """Tells the partner (or keeps the revocation for later) and drops this side."""
    held = _held_of(store, connection)
    form = {"token": held["refresh"], "client_id": held["own"]}
    try:
        _ask(config, store, connection.partner_base, "POST", f"{PREFIX}/revoke", form=form)
    except reach.Unreachable:
        store.revoke_later(connection.account_id, connection.partner_base, store.seal(json.dumps(form)), now)
        logger.info("%s not reached, the revocation waits connection=%s", connection.partner, connection.id)
    store.remove(connection.id)
    store.commit()


def disconnect(store: Any, config: AppConfig, account_id: AccountId, partner: str, now: datetime) -> None:
    """ "Trennen" on either side: both directions end (V3)."""
    connection = store.connection(account_id, partner)
    if connection is None:
        raise Refused("not_connected")
    _end(store, config, connection, now)
    logger.info("connection with %s ended here connection=%s", partner, connection.id)


def end_all(store: Any, config: AppConfig, account_id: AccountId, now: datetime) -> int:
    """The account is deleted for good: every connection ends, the partners hear it (or later)."""
    found = store.connections(account_id)
    for connection in found:
        _end(store, config, connection, now)
    return len(found)


def retry_waiting(store: Any, config: AppConfig, now: datetime) -> int:
    """Revocations the partner has not heard yet, tried again (the app's clock calls this now and then); the number
    that are done (heard, or given up after ``revoke_days``)."""
    done = 0
    for waiting in store.waiting():
        if now - waiting.since <= timedelta(days=config.revoke_days):
            try:
                _ask(
                    config,
                    store,
                    waiting.partner_base,
                    "POST",
                    f"{PREFIX}/revoke",
                    form=json.loads(store.unseal(waiting.token)),
                )
            except reach.Unreachable:
                continue
        store.done_waiting(waiting.id)
        store.commit()
        done += 1
    return done


def retire_at(store: Any, config: AppConfig, base: str, old_key: str) -> bool:
    """After "Neu verbinden": the partner's older API key, typed in by hand once, ends itself there."""
    try:
        answer = _ask(config, store, base, "POST", f"{PREFIX}/retire", bearer=old_key)
    except (reach.Unreachable, Refused):
        return False
    return answer.status == 200 and isinstance(answer.data, dict) and bool(answer.data.get("retired"))


# --- what the card shows ----------------------------------------------------------------------------------------------


def view(
    config: AppConfig, store: Any, account_id: AccountId, partner: str, now: datetime, connection: Connection | None
) -> dict[str, Any]:
    """One card: the partner, its state, what flows (both directions), the address to start from."""
    addresses = store.setting("addresses") or {}
    from_operator = str(addresses.get(partner) or "") if isinstance(addresses, dict) else ""
    legacy = next((row for row in store.legacy(account_id) if row.partner == partner), None)
    found: dict[str, Any] = {
        "partner": partner,
        "state": "none",
        "address": from_operator,
        "address_from_operator": bool(from_operator),
        "host": "",
        "uses": list(config.catalog.uses(config.app_name, partner)),
        "grants": list(config.catalog.uses(partner, config.app_name)),
        "account": None,
        "since": None,
        "ok_at": None,
        "used_at": None,
        "stale_since": None,
        "problem": None,
        "areas_used": None,
        "areas_granted": None,
        "legacy": None,
        "version": None,
    }
    if connection is not None:
        found.update(uses=list(connection.uses), grants=list(connection.grants))
    found["uses_levels"] = {purpose: config.catalog.purpose(partner, purpose).level for purpose in found["uses"]}
    found["grants_levels"] = {
        purpose: config.catalog.purpose(config.app_name, purpose).level for purpose in found["grants"]
    }
    # Decision V16 (F1 = a): where the partner reads areas of this app, the card asks for them before the click; the
    # account's own areas to choose from (empty when the partner reads none).
    catalog_grants = config.catalog.uses(partner, config.app_name)
    reads_areas = any(config.catalog.purpose(config.app_name, purpose).areas for purpose in catalog_grants)
    found["areas_choice"] = (
        [{"id": area["id"], "name": area["name"]} for area in store.areas(account_id)] if reads_areas else []
    )
    if connection is not None:
        found.update(
            state=connection.state,
            address=connection.partner_base,
            host=urlsplit(connection.partner_base).netloc,
            account=connection.partner_account,
            since=_iso(connection.created_at),
            ok_at=_iso(connection.ok_at),
            used_at=_iso(connection.used_at),
            stale_since=_iso(connection.stale_since),
            problem=connection.problem,
            areas_used=connection.areas_used,
            areas_granted=_areas_named(store, account_id, connection.areas_granted),
            version=connection.partner_version or None,
        )
        return found
    if legacy is not None:
        state = "legacy"
        if legacy.problem in ("unreachable", "refused"):
            state = legacy.problem
        elif legacy.expires_at is not None and legacy.expires_at - now <= timedelta(days=config.expiring_days):
            state = "expiring" if legacy.expires_at > now else "refused"
        found.update(
            state=state,
            address=legacy.partner_base,
            host=urlsplit(legacy.partner_base).netloc,
            ok_at=_iso(legacy.ok_at),
            legacy={"shown": legacy.shown, "expires_at": _iso(legacy.expires_at)},
        )
    return found


def views(config: AppConfig, store: Any, account_id: AccountId, now: datetime) -> list[dict[str, Any]]:
    """The partners of the app in the order of the catalog, connected or not; no token, no hash in it. Decision V20: a
    partner the app has no use for yet (``in_use``) is left out, unless a connection grants it something here."""
    mine = {connection.partner: connection for connection in store.connections(account_id)}
    shown = [
        partner for partner in config.partners if partner in config.usable or (partner in mine and mine[partner].grants)
    ]
    return [view(config, store, account_id, partner, now, mine.get(partner)) for partner in shown]


# --- using a connection with the app's own requests (decision V18) ------------------------------------------------


@dataclass(frozen=True)
class Access:
    """What an app's own request to the partner needs (its ``request()`` with address and key): the partner's address
    and a fresh access token of the connection, until ``expires_at``."""

    base: str
    token: str
    expires_at: datetime


def access(
    store: Any, config: AppConfig, account_id: AccountId, partner: str, now: datetime, *, force: bool = False
) -> Access:
    """Decision V18: the address and a fresh token of the connection with ``partner``, for the app's own requests (as
    it asked with an address and a key typed in by hand). Refreshes on its own; ``force`` refreshes even a token still
    valid (after the partner answered 401 once). Raises ``Refused`` like ``call``: ``not_connected``, ``unreachable``,
    ``refused``, ``resting``, ``partner_off``. The app tells the module how its own request went with ``reached``."""
    connection = store.connection(account_id, partner)
    if connection is None:
        raise Refused("not_connected")
    token = _fresh_access(store, config, connection, now, force=force)
    held = _held_of(store, store.connection(account_id, partner) or connection)
    return Access(base=connection.partner_base, token=token, expires_at=datetime.fromisoformat(held["expires"]))


def reached(store: Any, account_id: AccountId, partner: str, now: datetime, *, problem: str | None = None) -> None:
    """How the app's own request to the partner went, for the card: ``problem`` ``None`` (it answered), ``unreachable``
    (nothing usable came), or the partner's code of a refusal (``token_invalid`` after ``access(force=True)``,
    ``account_resting``, ``connections_off``)."""
    connection = store.connection(account_id, partner)
    if connection is None:
        return
    if problem is None:
        _mark(store, connection, "connected", now)
    elif problem == "unreachable":
        _mark(store, connection, "unreachable", now)
    else:
        _mark(store, connection, _state_of_refusal(problem), now, problem)
