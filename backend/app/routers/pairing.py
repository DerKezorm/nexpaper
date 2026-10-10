"""Pairing a device by a code it uses once (``services/pairing.py``): the QR code under My account, and OAuth 2 with
PKCE for apps (``docs/api.md``).

Making a code and allowing an app want a signed-in browser with a full session (``BrowserAccount``): the second factor
was met there, and a device token never pairs another device. Trading a code for a token is open (the code is the
key) and needs no tab header (``PROGRAM_PATHS``), but only for programs: a request a web page made (``Origin``,
``Sec-Fetch-Site``) is refused before anything is counted, so a page a person visits cannot feed any brake of their
address. Wrong codes count on a brake of their own (``deps.pairing_guard``), never on the sign-in's.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..deps import BrowserAccount, DbSession, from_a_web_page, pairing_failed, pairing_guard
from ..errors import error
from ..services import pairing, settings_service, totp
from ..services.pairing import OAuthProblem
from .devices import DeviceOut, _out

logger = logging.getLogger("nexpaper.auth")

router = APIRouter(tags=["devices"])


def _base(request: Request, db: DbSession) -> str:
    return settings_service.public_url(db) or str(request.base_url).rstrip("/")


# --- The QR code ------------------------------------------------------------------------------------------------------


class PairingOut(BaseModel):
    #: The code to type by hand: twelve letters and digits in groups of four, valid until ``expires_at`` and once.
    code: str
    expires_at: datetime
    #: The public address of nexpaper, to type next to the code.
    server: str
    #: What the QR code holds: ``nexpaper://pair?server=...&code=...``.
    link: str
    #: The QR code as SVG.
    qr_svg: str


class PairingStateOut(BaseModel):
    #: ``open``, ``used``, ``expired``, or ``none`` (no code made yet).
    state: str
    expires_at: datetime | None = None
    #: The device the code became, once it was used.
    device: DeviceOut | None = None


@router.post("/api/v1/devices/pairing", response_model=PairingOut, status_code=201,
             summary="Make a code to pair a device (QR code; 5 minutes, once); one still open ends")
def start(request: Request, account: BrowserAccount, db: DbSession) -> PairingOut:
    row, code = pairing.start_qr(db, account.id)
    server = _base(request, db)
    link = "nexpaper://pair?" + urlencode({"server": server, "code": code})
    return PairingOut(code=code, expires_at=row.expires_at, server=server, link=link, qr_svg=totp.qr_svg(link))


@router.get("/api/v1/devices/pairing", response_model=PairingStateOut,
            summary="What became of the newest pairing code (for the page that shows it)")
def state(account: BrowserAccount, db: DbSession) -> PairingStateOut:
    found = pairing.qr_state(db, account.id)
    return PairingStateOut(state=found.state, expires_at=found.expires_at,  # type: ignore[arg-type]
                           device=_out(found.device) if found.device is not None else None)


@router.post("/api/v1/devices/pairing/cancel", status_code=204, summary="End the open pairing code")
def cancel(account: BrowserAccount, db: DbSession) -> None:
    pairing.cancel_qr(db, account.id)


class PairIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    #: The name the device gives itself ("iPhone of Jule"); the account sees it in its list.
    name: str = Field(min_length=1, max_length=80)


class PairedOut(BaseModel):
    device: DeviceOut
    #: The device token, shown once: ``Authorization: Bearer npd_...``.
    token: str
    #: The account the device now speaks for.
    account: str


@router.post("/api/v1/devices/pair", response_model=PairedOut, status_code=201,
             summary="Trade a pairing code for a device token (no sign-in; the code is the key)")
def pair(payload: PairIn, request: Request, db: DbSession) -> PairedOut:
    if from_a_web_page(request):
        raise error("origin_refused", "Pairing is for devices and apps, not web pages.", 403)
    pairing_guard(request)
    found = pairing.redeem_qr(db, payload.code, payload.name)
    if found is None:
        pairing_failed(request)
        raise error("pairing_code_invalid", "This code is not valid (wrong, used or run out).", 400)
    device, token, account = found
    return PairedOut(device=_out(device), token=token, account=account.name)


# --- OAuth 2 with PKCE ------------------------------------------------------------------------------------------------


class AuthorizeIn(BaseModel):
    client_id: str = Field(max_length=64)
    redirect_uri: str = Field(max_length=300)
    response_type: str = Field(default="code", max_length=16)
    code_challenge: str = Field(default="", max_length=128)
    code_challenge_method: str = Field(default="", max_length=8)
    state: str = Field(default="", max_length=pairing.STATE_MAX)
    device_name: str = Field(default="", max_length=200)
    #: True: the person allows it; false: they refuse, and the app hears ``access_denied``.
    allow: bool = True


class AskedOut(BaseModel):
    client_id: str
    #: The app's own name (the page shows its translation where it has one).
    client_name: str
    #: The name the device will carry in the list of devices.
    device_name: str
    redirect_uri: str


class RedirectOut(BaseModel):
    #: Where the browser goes next: back to the app, with ``code`` and ``state`` (or ``error``).
    redirect: str


def _checked(values: AuthorizeIn) -> pairing.Asked:
    try:
        return pairing.check(values.client_id, values.redirect_uri, values.response_type, values.code_challenge,
                             values.code_challenge_method, values.state, values.device_name)
    except OAuthProblem as exc:
        extra = {"redirect": exc.back} if exc.back else {}
        raise error(exc.code, exc.text, 400, **extra) from exc


@router.get("/api/v1/oauth/authorize", response_model=AskedOut,
            summary="Check what an app asks for, before the person allows it (the page /oauth/authorize)")
def asked(
    _account: BrowserAccount,
    client_id: str = Query(default="", max_length=64), redirect_uri: str = Query(default="", max_length=300),
    response_type: str = Query(default="", max_length=16), code_challenge: str = Query(default="", max_length=128),
    code_challenge_method: str = Query(default="", max_length=8),
    state: str = Query(default="", max_length=pairing.STATE_MAX), device_name: str = Query(default="", max_length=200),
) -> AskedOut:
    found = _checked(AuthorizeIn(client_id=client_id, redirect_uri=redirect_uri, response_type=response_type,
                                 code_challenge=code_challenge, code_challenge_method=code_challenge_method,
                                 state=state, device_name=device_name))
    return AskedOut(client_id=found.client.id, client_name=found.client.name, device_name=found.device_name,
                    redirect_uri=found.redirect_uri)


@router.post("/api/v1/oauth/authorize", response_model=RedirectOut,
             summary="Allow (or refuse) an app: the address that takes a code (valid 2 minutes, once) back to it")
def authorize(payload: AuthorizeIn, account: BrowserAccount, db: DbSession) -> RedirectOut:
    found = _checked(payload)
    if not payload.allow:
        return RedirectOut(redirect=pairing.denied(found))
    return RedirectOut(redirect=pairing.authorize(db, account.id, found))


_TOKEN_BODY = {
    "requestBody": {"required": True, "content": {"application/x-www-form-urlencoded": {"schema": {
        "type": "object", "required": ["grant_type", "code", "redirect_uri", "client_id", "code_verifier"],
        "properties": {
            "grant_type": {"type": "string", "enum": ["authorization_code"]},
            "code": {"type": "string"}, "redirect_uri": {"type": "string"}, "client_id": {"type": "string"},
            "code_verifier": {"type": "string", "description": "43 to 128 characters (RFC 7636)"},
        }}}}},
    "responses": {"200": {"description": "The device token", "content": {"application/json": {"schema": {
        "type": "object", "properties": {
            "access_token": {"type": "string", "description": "npd_..., for Authorization: Bearer"},
            "token_type": {"type": "string", "enum": ["Bearer"]},
            "device_id": {"type": "string"}, "account": {"type": "string"}}}}}},
        "400": {"description": "error: invalid_request, unsupported_grant_type or invalid_grant (RFC 6749, 5.2)"}},
}
#: The largest body of a token request; it holds five short fields.
TOKEN_BODY_MAX = 4096


def _oauth_error(code: str, text: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "error_description": text},
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@router.post("/api/v1/oauth/token", openapi_extra=_TOKEN_BODY, response_model=None,
             summary="Trade the code of an app and its PKCE verifier for a device token (OAuth 2, RFC 6749 and 7636)")
async def token(request: Request, db: DbSession) -> JSONResponse:
    if from_a_web_page(request):
        return _oauth_error("invalid_request", "The token route is for apps, not web pages.", 403)
    pairing_guard(request)
    body = await request.body()
    if len(body) > TOKEN_BODY_MAX:
        return _oauth_error("invalid_request", "The request is too large.")
    kind = request.headers.get("content-type", "").split(";")[0].strip().lower()
    values: dict[str, Any]
    try:
        if kind == "application/json":
            values = json.loads(body.decode("utf-8"))
            if not isinstance(values, dict):
                raise ValueError("not an object")
        else:
            values = dict(parse_qsl(body.decode("utf-8"), keep_blank_values=True, max_num_fields=10))
    except (ValueError, UnicodeDecodeError):
        return _oauth_error("invalid_request", "The body is neither a form nor JSON.")
    fields = {key: values.get(key) for key in ("grant_type", "code", "redirect_uri", "client_id", "code_verifier")}
    if any(not isinstance(value, str) for value in fields.values()):
        return _oauth_error("invalid_request",
                            "grant_type, code, redirect_uri, client_id and code_verifier are needed.")
    if fields["grant_type"] != "authorization_code":
        return _oauth_error("unsupported_grant_type", "Only authorization_code is offered.")
    found = pairing.trade(db, code=fields["code"], verifier=fields["code_verifier"],  # type: ignore[arg-type]
                          client_id=fields["client_id"], redirect_uri=fields["redirect_uri"])  # type: ignore[arg-type]
    if found is None:
        pairing_failed(request)
        return _oauth_error("invalid_grant", "The code is not valid (wrong, used, run out, or another verifier).")
    device, secret, account = found
    return JSONResponse(content={"access_token": secret, "token_type": "Bearer", "device_id": device.uid,
                                 "account": account.name},
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
