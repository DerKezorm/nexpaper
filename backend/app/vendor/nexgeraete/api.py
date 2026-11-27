"""The routes of the module, in two routers the app mounts, and the dependency for the app's own device routes.

App (``app_router``, prefix ``/api/app/1``; without a key only the two pickups):

``POST   pairing/{id}/key``   the key for the QR code (``{secret}``; old forms ``X-Pairing-Secret`` and ``{device}``)
``POST   pairing/code``       the key for a typed code or the one-time code of the sign-in (``verifier`` with PKCE)
``POST   devices``            a key of its own for another device of the account (iCloud)
``GET    devices``            the account's devices, ``this`` marked
``DELETE devices/{id}``       disconnect one of them
``PATCH  device``             rename this device
``DELETE device``             this device disconnects itself
``PUT    push``               ``{ticket, key, understands}`` (nexmail also ``schluessel``); ``DELETE push``
``GET    push/kinds``         the kinds of this device; ``PUT push/kinds`` ``{<kind>: bool}``

Browser (``browser_router``, prefix ``/api``; sessions only, a device's key hears ``403 browser_only``):
``/app-pairing``, ``/app-pairing/{id}``, ``/app-connect``, ``/app-devices``, ``/app-devices/{id}``,
``/app-devices/{id}/push-kinds``, ``/server/accounts/{id}/devices`` (operator).

The app routes answer in the form of the request (``forms.py``): with ``X-Nex-App`` in ``nex``, else in the app's old
form. ``device(...)`` is the dependency the app puts before its own ``/api/app/1`` routes (``me``, ``changes`` …).

The only part of the module that needs FastAPI."""

# No ``from __future__ import annotations`` here: the routes name dependencies made inside the factories, which
# FastAPI must see as objects, not as text it would look up in the module.

import logging
import math
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import devices, forms, notices, pairing, push, qr, tokens
from .config import CLIENT_HEADER, FORM_NEX, LANGUAGES, AppConfig
from .devices import Caller
from .errors import DeviceRefused
from .model import Device, Holder, Store

logger = logging.getLogger("nexgeraete")


class Brake(Protocol):
    """The sign-in brake of ``konten`` (``BRAKE``): ``claim`` checks and counts an attempt as a failure (the wait in
    seconds when it must not run, else 0), ``succeeded`` takes the count back."""

    def claim(self, keys: list[str]) -> float: ...

    def succeeded(self, keys: list[str]) -> None: ...


#: G59: the bodies carry the module's name in the description (``NexgeraetePairIn``), so they never meet an app's
#: own ``PairIn`` or ``AddressIn`` and FastAPI renames nothing; the routes may stay in the app's description.
class NexgeraetePairIn(BaseModel):
    secret: str | None = Field(default=None, max_length=200)
    code: str | None = Field(default=None, max_length=200)
    verifier: str | None = Field(default=None, max_length=200)
    device_name: str | None = Field(default=None, max_length=200)
    device_kind: str | None = Field(default=None, max_length=16)
    #: The old forms' name of the device.
    device: str | None = Field(default=None, max_length=200)


class NexgeraetePushIn(BaseModel):
    ticket: str = Field(min_length=1, max_length=push.TICKET_MAX)
    key: str | None = Field(default=None, max_length=10_000)
    #: nexmail's name of ``key``.
    schluessel: str | None = Field(default=None, max_length=10_000)
    understands: list[str] | None = Field(default=None, max_length=100)


class NexgeraeteNameIn(BaseModel):
    name: str | None = Field(default=None, max_length=1000)


class NexgeraeteAddressIn(BaseModel):
    #: Where the browser sees the app now; counts only when the app gives no public address.
    address: str = Field(default="", max_length=600)


class NexgeraeteConnectIn(BaseModel):
    state: str | None = Field(default=None, max_length=200)
    challenge: str | None = Field(default=None, max_length=200)
    #: nextasks, nexlore: ``/app-connect?device=<name>`` leads to the QR code's link.
    device: str | None = Field(default=None, max_length=200)


#: The optional bodies as the routes take them.
PairBody = Annotated[NexgeraetePairIn | None, Body()]
AddressBody = Annotated[NexgeraeteAddressIn | None, Body()]


def _respond(answer: forms.Answer) -> Response:
    status, body, headers = answer
    if body is None:
        return Response(status_code=status, headers=headers)
    return JSONResponse(status_code=status, content=body, headers=headers)


def _refuse(form: str, refused: DeviceRefused) -> Response:
    return _respond(forms.refusal(form, refused))


def _exception(form: str, refused: DeviceRefused) -> HTTPException:
    """A refusal raised from a dependency. In the form ``mail`` the values travel as ``werte`` beside ``detail``, the
    way nexmail's own handler renders them."""
    status, body, headers = forms.refusal(form, refused)
    error = HTTPException(status_code=status, detail=body["detail"], headers=headers)
    if "werte" in body:
        error.werte = body["werte"]  # type: ignore[attr-defined]
    return error


def _now(clock: Callable[[], datetime] | None) -> datetime:
    return clock() if clock is not None else devices.utcnow()


def _client(request: Request) -> devices.Client | None:
    return devices.client_of(request.headers.get(CLIENT_HEADER))


def _language(request: Request, holder: Holder) -> str:
    asked = request.headers.get("accept-language", "")[:2].lower()
    return asked if asked in LANGUAGES else (holder.language if holder.language in LANGUAGES else "en")


def _sender(request: Request) -> str:
    return request.client.host if request.client else ""


def device(*, config: AppConfig, store: Callable[..., Store], clock: Callable[[], datetime] | None = None) -> Callable:
    """The dependency of a device route: ``Caller(device, holder)``, or the refusal in the request's form (G12)."""

    def dependency(request: Request, data: Annotated[Store, Depends(store)]) -> Caller:
        form = forms.form_of(config, request.headers)
        token = tokens.bearer(request.headers.get("authorization"))
        try:
            return devices.authenticate(data, config, token, client=_client(request), now=_now(clock))
        except DeviceRefused as refused:
            data.rollback()
            raise _exception(form, refused) from None

    return dependency


def hello_fields(config: AppConfig) -> dict[str, Any]:
    """What the app's ``hello`` adds: the ways a device may come in."""
    return {"pairing": ["qr", "code", "browser", "icloud"]}


def me_fields(config: AppConfig, caller: Caller) -> dict[str, Any]:
    """What the app's ``me`` adds: the account, this device, the server's mark, whether notifications can go out."""
    found: dict[str, Any] = {
        "account": forms.account_out(caller.holder),
        "device": devices.entry(caller.device, caller.device.id),
        "offers": {"push": bool(config.relay())},
    }
    if config.server_id is not None:
        found["server_id"] = config.server_id()
    return found


def _device_id(config: AppConfig, raw: str) -> Any:
    if config.device_id is int:
        if not raw.isdigit() or len(raw) > 18:
            raise DeviceRefused("not_found")
        return int(raw)
    if not 0 < len(raw) <= 64:
        raise DeviceRefused("not_found")
    return raw


def _account_id(config: AppConfig, raw: str) -> Any:
    if config.account_id is int:
        if not raw.isdigit() or len(raw) > 18:
            raise DeviceRefused("not_found")
        return int(raw)
    if not 0 < len(raw) <= 64:
        raise DeviceRefused("not_found")
    return raw


def app_router(
    *,
    config: AppConfig,
    store: Callable[..., Store],
    brake: Brake | None = None,
    on_paired: Callable[[Holder, Device], None] | None = None,
    send: push.Send | None = None,
    sender: Callable[[Request], str] | None = None,
    clock: Callable[[], datetime] | None = None,
    prefix: str = "/api/app/1",
    tags: list[str] | None = None,
) -> APIRouter:
    """The app's routes. ``store``: the dependency giving the app's ``Store`` for this request. ``brake``: the sign-in
    brake of ``konten`` (pot ``app-pairing:<sender>``); ``sender(request)`` the sender's address behind the app's
    proxies (``konten`` ``client_address``). ``on_paired(holder, device)``: after every new device (G29, the mail "Neue
    Anmeldung"). ``send``: what posts to the relay (default ``push.post``)."""
    routes = APIRouter(prefix=prefix, tags=tags or ["app"])
    Data = Annotated[Store, Depends(store)]
    Found = Annotated[Caller, Depends(device(config=config, store=store, clock=clock))]
    address_of = sender or _sender

    def after(data: Store, done: pairing.Paired) -> None:
        """After the commit: the app's hook (mail), then ``security`` to the other devices. Neither changes the
        result."""
        if on_paired is not None:
            try:
                on_paired(done.holder, done.device)
            except Exception as error:  # noqa: BLE001 (a hook must not undo a pairing)
                logger.warning("After pairing, the app's hook failed: %s", type(error).__name__)
        try:
            notices.paired(data, config, done, send=send)
        except Exception as error:  # noqa: BLE001
            logger.warning("After pairing, the notice failed: %s", type(error).__name__)

    def pickup(request: Request, data: Store, take: Callable[[], pairing.Paired]) -> Response:
        """The brake counts per sender: there is no account to count at before the code is known; only failures
        stay counted."""
        form = forms.form_of(config, request.headers)
        try:
            pairing.ready(data, config)
        except DeviceRefused as refused:
            return _refuse(form, refused)
        keys = [f"app-pairing:{address_of(request)}"]
        if brake is not None:
            wait = brake.claim(keys)
            if wait > 0:
                return _refuse(form, DeviceRefused("too_many_attempts", retry_after=max(1, math.ceil(wait))))
        try:
            done = take()
        except DeviceRefused as refused:
            data.rollback()
            if refused.code == "pairing_gone":
                logger.warning("Pairing refused")
            elif brake is not None:
                brake.succeeded(keys)
            return _refuse(form, refused)
        if brake is not None:
            brake.succeeded(keys)
        logger.info("Device paired device_id=%s via=%s", done.device.id, done.device.via)
        after(data, done)
        return _respond(
            forms.paired(form, done.token, done.holder, done.device, devices.entry(done.device), sibling=False)
        )

    @routes.post("/pairing/{pairing_id}/key", response_model=None, summary="The device's key for the QR code")
    def by_secret(pairing_id: str, request: Request, data: Data, body: PairBody = None) -> Any:
        given = body or NexgeraetePairIn()
        secret = given.secret or request.headers.get("x-pairing-secret")
        return pickup(
            request,
            data,
            lambda: pairing.redeem(
                data,
                config,
                pairing_id,
                secret,
                name=given.device_name or given.device,
                kind=given.device_kind,
                client=_client(request),
                now=_now(clock),
            ),
        )

    @routes.post(
        "/pairing/code", response_model=None, summary="The device's key for a typed code or the code of the sign-in"
    )
    def by_code(request: Request, data: Data, body: NexgeraetePairIn) -> Any:
        return pickup(
            request,
            data,
            lambda: pairing.redeem_code(
                data,
                config,
                body.code,
                verifier=body.verifier,
                name=body.device_name or body.device,
                kind=body.device_kind,
                client=_client(request),
                now=_now(clock),
            ),
        )

    @routes.post(
        "/devices", response_model=None, status_code=201, summary="A key of its own for another device of this account"
    )
    def bring_in(request: Request, found: Found, data: Data, body: PairBody = None) -> Any:
        form = forms.form_of(config, request.headers)
        given = body or NexgeraetePairIn()
        try:
            done = pairing.sibling(
                data,
                config,
                found,
                name=given.device_name or given.device,
                kind=given.device_kind,
                client=_client(request),
                now=_now(clock),
            )
        except DeviceRefused as refused:
            data.rollback()
            return _refuse(form, refused)
        logger.info("Device brought in by device_id=%s new device_id=%s", found.device.id, done.device.id)
        after(data, done)
        return _respond(
            forms.paired(form, done.token, done.holder, done.device, devices.entry(done.device), sibling=True)
        )

    @routes.get("/devices", response_model=None, summary="The account's devices, this one marked")
    def own_devices(found: Found, data: Data) -> Any:
        return devices.listing(data, config, found.holder.id, this=found.device.id)

    @routes.delete(
        "/devices/{device_id}", response_model=None, status_code=204, summary="Disconnect one of the account's devices"
    )
    def drop(device_id: str, request: Request, found: Found, data: Data) -> Any:
        try:
            devices.disconnect(data, config, found.holder.id, _device_id(config, device_id))
        except DeviceRefused as refused:
            data.rollback()
            return _refuse(forms.form_of(config, request.headers), refused)
        return Response(status_code=204)

    @routes.patch("/device", response_model=None, summary="Rename this device")
    def rename_self(request: Request, found: Found, data: Data, body: NexgeraeteNameIn) -> Any:
        try:
            changed = (
                devices.rename(data, config, found.holder.id, found.device.id, body.name)
                if body.name is not None
                else found.device
            )
        except DeviceRefused as refused:
            data.rollback()
            return _refuse(forms.form_of(config, request.headers), refused)
        return devices.entry(changed, found.device.id)

    @routes.delete("/device", response_model=None, status_code=204, summary="This device disconnects itself")
    def forget_self(found: Found, data: Data) -> Any:
        devices.disconnect(data, config, found.holder.id, found.device.id)
        return Response(status_code=204)

    @routes.put(
        "/push",
        response_model=None,
        summary="Notifications for this device: the relay's ticket, its key, what it understands",
    )
    def push_on(request: Request, found: Found, data: Data, body: NexgeraetePushIn) -> Any:
        form = forms.form_of(config, request.headers)
        try:
            push.register(data, config, found, body.ticket, body.key or body.schluessel or "", body.understands)
        except DeviceRefused as refused:
            data.rollback()
            return _refuse(form, refused)
        return _respond(forms.done(form))

    @routes.delete("/push", response_model=None, summary="No more notifications for this device; it stays connected")
    def push_off(request: Request, found: Found, data: Data) -> Any:
        push.unregister(data, config, found)
        return _respond(forms.done(forms.form_of(config, request.headers)))

    @routes.get("/push/kinds", response_model=None, summary="The kinds of notification of this device")
    def push_kinds(request: Request, found: Found) -> Any:
        return {"kinds": push.kinds(config, found.device, found.holder, _language(request, found.holder))}

    @routes.put("/push/kinds", response_model=None, summary="Switch kinds of notification on or off on this device")
    def set_push_kinds(request: Request, found: Found, data: Data, body: Annotated[dict[str, bool], Body()]) -> Any:
        try:
            changed = push.set_kinds(data, config, found.device, found.holder, body)
        except DeviceRefused as refused:
            data.rollback()
            return _refuse(forms.form_of(config, request.headers), refused)
        return {"kinds": push.kinds(config, changed, found.holder, _language(request, found.holder))}

    return routes


def _origin(raw: str) -> str | None:
    parts = urlsplit(raw.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def browser_router(
    *,
    config: AppConfig,
    store: Callable[..., Store],
    account: Callable[..., Any],
    operator: Callable[..., Any],
    account_id: Callable[[Any], Any] = lambda signed_in: signed_in.id,
    address: Callable[[Request], str] | None = None,
    send: push.Send | None = None,
    clock: Callable[[], datetime] | None = None,
    prefix: str = "/api",
    tags: list[str] | None = None,
) -> APIRouter:
    """The browser's routes. ``account``: the dependency of a signed-in browser session (``account_id`` reads its
    id); ``operator``: the app's dependency for operators; ``address(request)``: the public address the app knows
    (its setting), which wins over the browser's."""

    def only_browser(request: Request) -> None:
        if tokens.bearer(request.headers.get("authorization")) is not None:
            raise _exception(FORM_NEX, DeviceRefused("browser_only"))

    routes = APIRouter(prefix=prefix, tags=tags or ["app"], dependencies=[Depends(only_browser)])
    Own = Annotated[Any, Depends(account)]
    Data = Annotated[Store, Depends(store)]

    def refuse(data: Store, refused: DeviceRefused) -> Response:
        data.rollback()
        return _refuse(FORM_NEX, refused)

    def where(request: Request, given: str) -> str:
        for candidate in (address(request) if address else "", given, str(request.base_url)):
            found = _origin(candidate or "")
            if found:
                return found
        raise DeviceRefused("app_address_missing")

    def own_device(data: Store, signed_in: Any, raw: str) -> Device:
        found = data.device(_device_id(config, raw))
        if found is None or str(found.account_id) != str(account_id(signed_in)):
            raise DeviceRefused("not_found")
        return found

    @routes.post(
        "/app-pairing",
        response_model=None,
        status_code=201,
        summary="A QR code and a code for the app (10 minutes, one device)",
    )
    def pair(request: Request, signed_in: Own, data: Data, body: AddressBody = None) -> Any:
        try:
            started = pairing.start(
                data,
                config,
                account_id(signed_in),
                address=where(request, body.address if body else ""),
                now=_now(clock),
            )
        except DeviceRefused as refused:
            return refuse(data, refused)
        logger.info("Pairing made for the app")
        return JSONResponse(
            status_code=201,
            content={
                "id": started.pairing.id,
                "secret": started.secret,
                "code": started.code,
                "link": started.link,
                "address": started.address,
                "expires_at": devices.iso(started.pairing.expires_at),
                "qr_svg": qr.svg(started.link),
                "app_store_url": config.app_store_url,
            },
            headers={"Cache-Control": "no-store"},
        )

    @routes.get(
        "/app-pairing/{pairing_id}", response_model=None, summary="Whether the app used the QR code or the code"
    )
    def pairing_state(pairing_id: str, signed_in: Own, data: Data) -> Any:
        try:
            state, found = pairing.state(data, config, account_id(signed_in), pairing_id, _now(clock))
        except DeviceRefused as refused:
            return refuse(data, refused)
        return {"state": state, "device": devices.entry(found) if found is not None else None}

    @routes.delete("/app-pairing/{pairing_id}", response_model=None, status_code=204, summary="Withdraw a QR code")
    def withdraw(pairing_id: str, signed_in: Own, data: Data) -> Any:
        try:
            pairing.withdraw(data, config, account_id(signed_in), pairing_id)
        except DeviceRefused as refused:
            return refuse(data, refused)
        return Response(status_code=204)

    @routes.post("/app-connect", response_model=None, summary="Connect the app that opened /app-connect")
    def connect(request: Request, signed_in: Own, data: Data, body: NexgeraeteConnectIn) -> Any:
        """With ``state``: the link back into the app with a one-time code (five minutes, once; ``challenge`` for
        PKCE). With ``device`` alone (nextasks, nexlore): the QR code's link of a new pairing."""
        try:
            if body.state is not None:
                link = pairing.consent(
                    data, config, account_id(signed_in), body.state, challenge=body.challenge, now=_now(clock)
                )
            elif body.device is not None:
                link = pairing.start(
                    data, config, account_id(signed_in), address=where(request, ""), now=_now(clock)
                ).link
            else:
                raise DeviceRefused("invalid_input", fields=["state"])
        except DeviceRefused as refused:
            return refuse(data, refused)
        logger.info("Link made for the app")
        return JSONResponse(content={"redirect": link}, headers={"Cache-Control": "no-store"})

    @routes.get("/app-devices", response_model=None, summary="The own devices")
    def own_devices(signed_in: Own, data: Data) -> Any:
        return {
            "devices": devices.listing(data, config, account_id(signed_in)),
            "max": config.max_devices,
            "app_store_url": config.app_store_url,
            "has_app": config.has_app,
        }

    @routes.patch("/app-devices/{device_id}", response_model=None, summary="Rename a device")
    def rename(device_id: str, signed_in: Own, data: Data, body: NexgeraeteNameIn) -> Any:
        try:
            found = own_device(data, signed_in, device_id)
            changed = devices.rename(data, config, account_id(signed_in), found.id, body.name)
        except DeviceRefused as refused:
            return refuse(data, refused)
        return devices.entry(changed)

    @routes.delete("/app-devices/{device_id}", response_model=None, status_code=204, summary="Disconnect a device")
    def disconnect(device_id: str, signed_in: Own, data: Data) -> Any:
        try:
            found = own_device(data, signed_in, device_id)
            devices.disconnect(data, config, account_id(signed_in), found.id)
        except DeviceRefused as refused:
            return refuse(data, refused)
        return Response(status_code=204)

    @routes.delete("/app-devices", response_model=None, summary="Disconnect every device of the account")
    def disconnect_all(signed_in: Own, data: Data) -> Any:
        return {"removed": devices.disconnect_all(data, config, account_id(signed_in))}

    def holder_of(data: Store, signed_in: Any) -> Holder:
        found = data.holder(account_id(signed_in))
        if found is None:
            raise DeviceRefused("not_found")
        return found

    @routes.get(
        "/app-devices/{device_id}/push-kinds", response_model=None, summary="The kinds of notification of a device"
    )
    def device_kinds(device_id: str, request: Request, signed_in: Own, data: Data) -> Any:
        try:
            found = own_device(data, signed_in, device_id)
            holder = holder_of(data, signed_in)
        except DeviceRefused as refused:
            return refuse(data, refused)
        return {"kinds": push.kinds(config, found, holder, _language(request, holder))}

    @routes.put(
        "/app-devices/{device_id}/push-kinds", response_model=None, summary="Switch kinds of notification on a device"
    )
    def set_device_kinds(
        device_id: str, request: Request, signed_in: Own, data: Data, body: Annotated[dict[str, bool], Body()]
    ) -> Any:
        try:
            found = own_device(data, signed_in, device_id)
            holder = holder_of(data, signed_in)
            changed = push.set_kinds(data, config, found, holder, body)
        except DeviceRefused as refused:
            return refuse(data, refused)
        return {"kinds": push.kinds(config, changed, holder, _language(request, holder))}

    @routes.get(
        "/server/accounts/{account}/devices",
        response_model=None,
        summary="How many devices an account has, which, last seen",
        dependencies=[Depends(operator)],
    )
    def account_devices(account: str, data: Data) -> Any:
        try:
            return devices.of_account(data, config, _account_id(config, account))
        except DeviceRefused as refused:
            return refuse(data, refused)

    @routes.delete(
        "/server/accounts/{account}/devices",
        response_model=None,
        summary="Disconnect every device of an account",
        dependencies=[Depends(operator)],
    )
    def account_devices_off(account: str, data: Data) -> Any:
        try:
            return {"removed": devices.disconnect_all(data, config, _account_id(config, account))}
        except DeviceRefused as refused:
            return refuse(data, refused)

    return routes
