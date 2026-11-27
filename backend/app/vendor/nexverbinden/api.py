"""The routes of the module (the only part that needs FastAPI). The same places in every app (``config``):

``GET    /.well-known/nex-app``                   who answers here, and whether it connects now
``GET    /api/connect/partners``                   the cards: every partner of the app with its state (account)
``POST   /api/connect/partners/{partner}/start``   "Mit <partner> verbinden": ``{"go": <consent page>}`` (account;
                                                  since 0.1.8 at the operator's address, an ``address`` sent is
                                                  not taken, V42)
``POST   /api/connect/return``                     back from the partner with ``code``, ``state``, ``iss`` (account)
``POST   /api/connect/partners/{partner}/check``   "Jetzt prüfen" (account)
``DELETE /api/connect/partners/{partner}``         "Trennen", both directions (account)
``GET    /api/connect/consent``                    what the consent page shows (account)
``POST   /api/connect/consent``                    the account's answer: ``{"redirect": …}`` (account)
``GET|PUT /api/connect/admin``                     the operator: switch, addresses of the other nex apps, own network
                                                  (since 0.2.0 in one change, each address checked, B11, B18)
``POST|DELETE /api/connect/admin/suggestions/{partner}``  since 0.2.0: take or turn down an address another nex
                                                  app suggested (operator, B16)
``POST   /api/connect/token``, ``/revoke``         between the apps (forms, RFC 6749 and 7009)
``POST   /api/connect/retire``                     an older API key of this app ends itself (``Authorization``)
``GET    /api/connect/hello``                      a partner checks its connection (``Authorization``)
``GET    /api/connect/about/{purpose}``            since 0.1.13: what this app has about one person (``Authorization``,
                                                  ``name``, ``mail``, ``phone``; the app's hook ``about``)

Between the apps an ``Origin`` is refused (403 ``origin_refused``): browsers send one, apps do not. A refusal of the
partner never reaches the account's page as 401 (``errors``)."""

# No ``from __future__ import annotations``: the routes name dependencies made inside ``router()``.
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from . import connect, persons, reach
from .config import PREFIX, WELL_KNOWN, AppConfig
from .errors import CODES, GrantError, Refused
from .shared import BRAKE

logger = logging.getLogger("nexverbinden")

#: The largest form a partner sends.
MAX_FORM = 16 * 1024


def _now() -> datetime:
    return datetime.now(UTC)


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header[:7].lower() != "bearer ":
        return None
    return header[7:].strip() or None


def wall(code: str) -> JSONResponse:
    status, message = CODES[code]
    return JSONResponse({"detail": {"code": code, "message": message}}, status_code=status)


async def _form(request: Request) -> dict[str, str]:
    taken = b""
    async for chunk in request.stream():
        taken += chunk
        if len(taken) > MAX_FORM:
            raise GrantError("invalid_request", "The request is too large.", 413)
    try:
        return dict(parse_qsl(taken.decode("utf-8"), keep_blank_values=True))
    except (UnicodeDecodeError, ValueError):
        raise GrantError("invalid_request", "The body must be a form.") from None


def _grant_answer(body: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


def router(
    *,
    config: AppConfig,
    store: Callable[..., Any],
    account: Callable[..., Any],
    operator: Callable[..., Any],
    account_id: Callable[[Any], Any] = lambda signed_in: signed_in.id,
    address: Callable[[Request], str] | None = None,
    error: Callable[[Refused], Exception] | None = None,
    on_connected: Callable[[Any, Any, str], None] | None = None,
    on_disconnected: Callable[[Any, Any, str], None] | None = None,
    old_key: Callable[[Any, Any, str], str | None] | None = None,
    about: Callable[[Any, Any, str, Any], Any] | None = None,
    tags: list[str] | None = None,
) -> APIRouter:
    """The routes. ``store``: a dependency giving the app's ``nexverbinden.Store`` for this request. ``account``: the
    dependency of a signed-in browser session (never a key, never a device); ``operator``: the app's dependency for
    operators. ``address(request)``: the app's public address (its setting, else the request's through trusted proxies
    only). ``error``: the app's form of a refusal on its own pages. ``on_connected(store, account_id, partner)``: after
    a connection was made here (load lists, calendars). ``on_disconnected(store, account_id, partner)`` (since 0.1.4,
    V-13): after a connection ended here, by "Trennen" in this app or because the partner ended it (drop the app's own
    rows of it). ``old_key(store, account_id, partner)``: the API key of an
    older connection with this partner, if the app has one; after "Neu verbinden" it ends itself at the partner.
    ``about(store, caller, purpose, person)`` (since 0.1.13, V52): what the app has about ``person`` (``Person``) for
    one of its person purposes, only in ``caller.areas``: ``{"count", "next", "last", "open"}`` (``persons.cleaned``
    cuts it to that form); without it the app tells nothing about people (404 ``about_unknown``)."""
    routes = APIRouter(tags=tags or ["connect"])
    base_of = address or (lambda request: str(request.base_url).rstrip("/"))
    Data = Annotated[Any, Depends(store)]
    Own = Annotated[Any, Depends(account)]

    def refuse(refusal: Refused) -> Exception:
        if error is not None:
            return error(refusal)
        return HTTPException(status_code=refusal.status, detail=refusal.as_dict())

    def _partner(name: str) -> str:
        if name not in config.partners:
            raise refuse(Refused("partner_unknown"))
        return name

    # --- the description ------------------------------------------------------------------------------------------

    @routes.get(WELL_KNOWN, include_in_schema=False)
    def description(data: Data) -> JSONResponse:
        return JSONResponse(connect.describe(config, data), headers={"Cache-Control": "no-store"})

    # --- the account's card -----------------------------------------------------------------------------------------

    @routes.get(f"{PREFIX}/partners", summary="The other nex apps this one connects with, and how each stands")
    def partners(signed_in: Own, data: Data) -> list[dict]:
        return connect.views(config, data, account_id(signed_in), _now())

    @routes.post(f"{PREFIX}/partners/{{partner}}/start", summary="Start a connection: where to send the browser")
    def start(request: Request, partner: str, signed_in: Own, data: Data, body: Annotated[dict, Body()]) -> dict:
        try:
            go = connect.start(
                data,
                config,
                account_id(signed_in),
                _partner(partner),
                base_of(request),
                _now(),
                areas=body.get("areas"),
            )
        except Refused as refusal:
            data.rollback()
            raise refuse(refusal) from None
        return {"go": go}

    @routes.post(f"{PREFIX}/return", summary="Back from the partner's consent page: finish the connection")
    def come_back(request: Request, signed_in: Own, data: Data, body: Annotated[dict, Body()]) -> dict:
        who = account_id(signed_in)
        if body.get("error"):
            # Since 0.1.8 (B6, V47): the other app sent back a refusal of its consent page; the card of the partner
            # here shows it (``partner`` in the refusal).
            raise refuse(connect.came_back_refused(data, who, str(body.get("error")), str(body.get("state") or "")))
        try:
            made = connect.come_back(
                data,
                config,
                who,
                str(body.get("code") or ""),
                str(body.get("state") or ""),
                str(body.get("iss") or ""),
                base_of(request),
                _now(),
            )
        except Refused as refusal:
            data.rollback()
            raise refuse(refusal) from None
        if old_key is not None:
            found = old_key(data, who, made.partner)
            if found:
                connect.retire_at(data, config, made.partner_base, found)
        # Since 0.2.0 (B9, V56): the connection by click takes the place of an older one by API key with the partner
        # (after its key ended itself there, above).
        if connect.forget_legacy(data, who, made.partner):
            data.commit()
        if on_connected is not None:
            on_connected(data, who, made.partner)
        return connect.view(config, data, who, made.partner, _now(), made)

    @routes.post(f"{PREFIX}/partners/{{partner}}/check", summary="Check the connection now")
    def check(partner: str, signed_in: Own, data: Data) -> dict:
        who = account_id(signed_in)
        try:
            found = connect.check(data, config, who, _partner(partner), _now())
        except Refused as refusal:
            raise refuse(refusal) from None
        return connect.view(config, data, who, partner, _now(), found)

    @routes.delete(f"{PREFIX}/partners/{{partner}}", summary="End the connection, both directions")
    def disconnect(partner: str, signed_in: Own, data: Data) -> dict:
        who = account_id(signed_in)
        try:
            connect.disconnect(data, config, who, _partner(partner), _now())
        except Refused as refusal:
            raise refuse(refusal) from None
        if on_disconnected is not None:
            on_disconnected(data, who, partner)
        return connect.view(config, data, who, partner, _now(), None)

    # --- the consent page -------------------------------------------------------------------------------------------

    @routes.get(f"{PREFIX}/consent", summary="What another nex app asks to connect for")
    def consent_info(
        request: Request,
        signed_in: Own,
        data: Data,
        client_id: Annotated[str, Query(max_length=600)] = "",
        redirect_uri: Annotated[str, Query(max_length=2048)] = "",
        state: Annotated[str, Query(max_length=600)] = "",
        code_challenge: Annotated[str, Query(max_length=200)] = "",
        code_challenge_method: Annotated[str, Query(max_length=20)] = "",
    ) -> dict:
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        }
        try:
            return connect.consent_info(data, config, account_id(signed_in), params, base_of(request))
        except Refused as refusal:
            raise refuse(refusal) from None

    @routes.post(f"{PREFIX}/consent", summary="Agree to a connection, or turn it down")
    def consent(request: Request, signed_in: Own, data: Data, body: Annotated[dict, Body()]) -> dict:
        try:
            redirect = connect.consent(data, config, account_id(signed_in), body, base_of(request), _now())
        except Refused as refusal:
            data.rollback()
            raise refuse(refusal) from None
        return {"redirect": redirect}

    # --- the operator -----------------------------------------------------------------------------------------------

    def _admin(data: Any, *, saved: list[str] | None = None, checks: dict[str, Any] | None = None) -> dict:
        found = data.setting("addresses")
        addresses = found if isinstance(found, dict) else {}
        return {
            "connections": connect.connections_on(data),
            "partners": config.partners,
            "addresses": {partner: str(addresses.get(partner) or "") for partner in config.partners},
            # Since 0.1.4 (V-12): the switch for connections into the own network, the app's own setting.
            "local": bool(data.local_allowed()),
            # Since 0.2.0 (B16, V58): addresses other nex apps passed on, for the operator to take with a click.
            "suggestions": connect.suggestions(data, config),
            # Since 0.2.0 (B18, V60): what this change kept ("connections", "local", partners), and what answers at
            # each address kept anew (B11, V57); empty where nothing was changed.
            "saved": saved or [],
            "checks": checks or {},
        }

    def _keep_address(data: Any, partner: str, url: str) -> None:
        found = data.setting("addresses")
        kept = {name: str(value) for name, value in (found if isinstance(found, dict) else {}).items() if value}
        kept[partner] = url
        data.set_setting("addresses", {name: value for name, value in kept.items() if value})
        connect.drop_suggestion(data, partner)

    @routes.get(f"{PREFIX}/admin", dependencies=[Depends(operator)], summary="Switch and addresses (operator)")
    def admin_get(data: Data) -> dict:
        return _admin(data)

    @routes.put(f"{PREFIX}/admin", dependencies=[Depends(operator)], summary="Change switch or addresses (operator)")
    def admin_put(data: Data, body: Annotated[dict, Body()]) -> dict:
        """Since 0.2.0 (B18, V60): one change for the whole card, its switches and every address. First everything is
        checked: a switch that is not on or off (422), an address that is none (422 with ``partner`` and ``fields``,
        every field that is wrong with its code); then nothing is kept. Else all of it is kept, and every address kept
        anew is asked what answers there (B11, V57): ``checks``, kept also where nothing or another app answers."""
        for name in ("connections", "local"):
            if name in body and not isinstance(body[name], bool):
                raise HTTPException(status_code=422, detail={"code": "invalid", "message": "On or off."})
        given = body.get("addresses", {})
        if not isinstance(given, dict) or not set(given) <= set(config.partners):
            raise refuse(Refused("partner_unknown"))
        before = _admin(data)
        kept = dict(before["addresses"])
        wrong: dict[str, str] = {}
        for partner, raw in given.items():
            text = str(raw or "").strip()
            try:
                kept[partner] = reach.clean_url(text) if text else ""
            except Refused as refusal:
                wrong[partner] = refusal.code
        if wrong:
            first = next(iter(wrong))
            raise refuse(Refused(wrong[first], partner=first, fields=wrong))
        saved: list[str] = []
        if "connections" in body and body["connections"] != before["connections"]:
            data.set_setting("connections", body["connections"])
            saved.append("connections")
        if "local" in body and body["local"] != before["local"]:
            data.set_local_allowed(body["local"])
            saved.append("local")
        changed = [partner for partner in config.partners if kept[partner] != before["addresses"][partner]]
        if changed:
            data.set_setting("addresses", {partner: url for partner, url in kept.items() if url})
            for partner in changed:
                if kept[partner]:
                    connect.drop_suggestion(data, partner)
            saved += changed
        data.commit()
        if saved:
            logger.info("connections with other nex apps changed by the operator (%s)", ", ".join(saved))
        checks = {partner: connect.check_address(config, data, partner, kept[partner]) for partner in changed}
        return _admin(data, saved=saved, checks={partner: check for partner, check in checks.items() if kept[partner]})

    @routes.post(
        f"{PREFIX}/admin/suggestions/{{partner}}",
        dependencies=[Depends(operator)],
        summary="Take a suggested address of another nex app (operator)",
    )
    def suggestion_take(partner: str, data: Data) -> dict:
        """Since 0.2.0 (B16, V58): the operator takes a suggestion with one click; it is asked first like a typed
        address (B11, V57) and kept only where the right app answers there, else it stays a suggestion and the
        field says why."""
        wanted = _partner(partner)
        found = next((one for one in connect.suggestions(data, config) if one["partner"] == wanted), None)
        if found is None:
            raise refuse(Refused("suggestion_unknown"))
        check = connect.check_address(config, data, partner, found["address"])
        if not check["ok"]:
            return _admin(data, checks={partner: check})
        _keep_address(data, partner, found["address"])
        data.commit()
        logger.info("the operator took the suggested address of %s (from %s)", partner, found["from"] or "?")
        return _admin(data, saved=[partner], checks={partner: check})

    @routes.delete(
        f"{PREFIX}/admin/suggestions/{{partner}}",
        dependencies=[Depends(operator)],
        summary="Turn a suggested address down (operator)",
    )
    def suggestion_drop(partner: str, data: Data) -> dict:
        if not connect.drop_suggestion(data, _partner(partner)):
            raise refuse(Refused("suggestion_unknown"))
        data.commit()
        return _admin(data)

    # --- between the apps -------------------------------------------------------------------------------------------

    @routes.post(f"{PREFIX}/token", include_in_schema=False)
    async def token(request: Request, data: Data) -> JSONResponse:
        if request.headers.get("origin"):
            return wall("origin_refused")
        try:
            form = await _form(request)
            return _grant_answer(connect.token(data, config, form, base_of(request), _now()))
        except GrantError as refusal:
            return _grant_answer(refusal.as_dict(), refusal.status)

    @routes.post(f"{PREFIX}/revoke", include_in_schema=False)
    async def revoke(request: Request, data: Data) -> JSONResponse:
        if request.headers.get("origin"):
            return wall("origin_refused")
        try:
            form = await _form(request)
        except GrantError as refusal:
            return _grant_answer(refusal.as_dict(), refusal.status)
        ended = connect.revoke(data, form)
        if ended is not None and on_disconnected is not None:
            on_disconnected(data, ended.account_id, ended.partner)
        # RFC 7009, 2.2: the same answer for a token that was never there.
        return _grant_answer({})

    @routes.post(f"{PREFIX}/retire", include_in_schema=False)
    def retire(request: Request, data: Data) -> JSONResponse:
        if request.headers.get("origin"):
            return wall("origin_refused")
        found = _bearer(request)
        retired = bool(found) and bool(data.retire_key(found))
        if retired:
            data.commit()
            logger.info("an older API key ended itself after a new connection")
        return _grant_answer({"retired": retired})

    @routes.get(f"{PREFIX}/about/{{purpose}}", include_in_schema=False)
    def about_route(request: Request, purpose: str, data: Data) -> JSONResponse:
        if request.headers.get("origin"):
            return wall("origin_refused")
        granted = config.catalog.purposes.get(config.app_name, {}).get(purpose)
        if granted is None or not granted.person or about is None:
            return wall("about_unknown")
        try:
            caller = connect.authenticate(data, config, _bearer(request), _now())
            connect.require(caller, purpose)
            if not BRAKE.take(f"verbinden:about:{caller.connection_id}", config.about_per_minute):
                raise Refused("slow_down")
            person = persons.person_from(request.query_params.multi_items())
        except Refused as refusal:
            return wall(refusal.code)
        found = about(data, caller, purpose, person)
        return JSONResponse(persons.cleaned(found, granted), headers={"Cache-Control": "no-store"})

    @routes.get(f"{PREFIX}/hello", include_in_schema=False)
    def hello(request: Request, data: Data) -> JSONResponse:
        if request.headers.get("origin"):
            return wall("origin_refused")
        try:
            caller = connect.authenticate(data, config, _bearer(request), _now())
        except Refused as refusal:
            return wall(refusal.code)
        return JSONResponse(connect.hello(data, config, caller))

    return routes
