"""Passkeys: list, add and remove the own (Account, Security), sign in with one, and confirm an act with one.

A passkey signs in on its own, without password and code: the device checked finger, face or PIN, and the key is
bound to nexpaper's address. Adding one needs the password (or, right after signing in, the session that sets up the
second factor); removing one needs the password. A failed answer counts like a wrong password: per address, and
against the account the passkey belongs to.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Path, Request, Response
from pydantic import BaseModel, Field

from ..deps import (
    BrowserAccount,
    DbSession,
    address_failed,
    address_guard,
    client_ip,
    confirm_self,
    session_of,
    too_many,
)
from ..errors import error
from ..models import STAGE_SETUP
from ..models import Account as AccountRow
from ..security import DEVICE_COOKIE, brake, devices_of
from ..services import accounts, passkeys, totp
from .auth import PENDING_COOKIE, account_view, secure_cookie, sign_in
from .totp import enrolled, last_factor_guard

logger = logging.getLogger("nexpaper.auth")

router = APIRouter(prefix="/api/v1", tags=["passkeys"])

#: The cookie that binds a passkey sign-in's challenge to the browser that asked for it.
CHALLENGE_COOKIE = "nexpaper_pk"
#: The browser's answer, as JSON. A real one is a few kilobytes; nothing near this.
CREDENTIAL_MAX = 16 * 1024


def _credential(value: dict[str, Any]) -> dict[str, Any]:
    import json

    if len(json.dumps(value)) > CREDENTIAL_MAX:
        raise error("passkey_invalid", "The browser's answer did not check out.", 422)
    return value


class AddIn(BaseModel):
    name: str = Field(default="", max_length=200)
    password: str = Field(default="", max_length=200)
    #: The browser's ``PublicKeyCredential`` as JSON; checked by py_webauthn.
    credential: dict[str, Any]


class PasswordIn(BaseModel):
    password: str = Field(default="", max_length=200)


class AnswerIn(BaseModel):
    credential: dict[str, Any]
    remember: bool = True


def _fail(exc: passkeys.PasskeyError) -> Exception:
    return error(exc.code, exc.message, exc.status)


Uid = Annotated[str, Path(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")]


@router.get("/auth/passkeys", summary="The own passkeys")
def listing(account: BrowserAccount, db: DbSession) -> list[dict[str, Any]]:
    return [passkeys.view(row) for row in passkeys.listing(db, account.id)]


@router.post("/auth/passkeys/begin", summary="Start adding a passkey; the browser gets the options")
def begin(request: Request, account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    row = db.get(AccountRow, account.id)
    assert row is not None
    try:
        return {"options": passkeys.begin_registration(db, row, session_of(request).uid)}
    except passkeys.PasskeyError as exc:
        raise _fail(exc) from exc


@router.post("/auth/passkeys", status_code=201, summary="Finish adding a passkey: the browser's answer, the password")
def add(payload: AddIn, request: Request, account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    row = db.get(AccountRow, account.id)
    assert row is not None
    if session_of(request).stage != STAGE_SETUP:
        confirm_self(request, db, row, payload.password)
    try:
        key = passkeys.finish_registration(db, row, session_of(request).uid, _credential(payload.credential),
                                           payload.name)
    except passkeys.PasskeyError as exc:
        raise _fail(exc) from exc
    codes = enrolled(request, db, row)
    return {"passkey": passkeys.view(key), "recovery_codes": codes, "account": account_view(row)}


@router.post("/auth/passkeys/{uid}/remove", summary="Remove an own passkey; needs the password")
def remove(uid: Uid, payload: PasswordIn, request: Request, account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    row = db.get(AccountRow, account.id)
    assert row is not None
    confirm_self(request, db, row, payload.password)
    keys = passkeys.listing(db, row.id)
    if not any(key.uid == uid for key in keys):
        raise error("not_found", "No such passkey.", 404)
    if len(keys) == 1 and not row.totp_secret_enc:
        last_factor_guard(db, row)
    gone = passkeys.remove(db, row.id, uid)
    if gone is None:
        raise error("not_found", "No such passkey.", 404)
    if not totp.has_second_factor(db, row):
        row.totp_recovery = ""
        db.commit()
    logger.info("Passkey removed name=%s passkey=%s", row.name, gone.name)
    return account_view(row)


# --- Signing in with a passkey ----------------------------------------------------------------------------------------


@router.post("/auth/passkey/begin", summary="Sign in with a passkey: the browser gets a challenge (no sign-in needed)")
def sign_in_begin(request: Request, response: Response, db: DbSession) -> dict[str, Any]:
    address_guard(request)
    # Every "begin" counts for the sender, whether anything follows or not: asking for challenges is no way to fill
    # the server's memory. A sender has room for ``BEGINS_PER_ADDRESS`` before it rests like after a failed password.
    key = "passkey-begin:" + client_ip(request)
    wait = brake.wait_seconds(key, passkeys.BEGINS_PER_ADDRESS)
    if wait:
        raise too_many(wait)
    brake.failed(key, passkeys.BEGINS_PER_ADDRESS)
    try:
        token, options = passkeys.begin_sign_in(db, client_ip(request))
    except passkeys.PasskeyError as exc:
        raise _fail(exc) from exc
    response.set_cookie(CHALLENGE_COOKIE, token, max_age=passkeys.CHALLENGE_SECONDS, httponly=True, samesite="strict",
                        secure=secure_cookie(request), path="/api/v1/auth/passkey")
    return {"options": options}


@router.post("/auth/passkey", summary="Sign in with a passkey: the browser's signed answer")
def sign_in_finish(payload: AnswerIn, request: Request, response: Response, db: DbSession) -> dict[str, Any]:
    address_guard(request)
    token = request.cookies.get(CHALLENGE_COOKIE)
    response.delete_cookie(CHALLENGE_COOKIE, path="/api/v1/auth/passkey")
    try:
        account = passkeys.finish_sign_in(db, token, _credential(payload.credential))
    except passkeys.PasskeyError as exc:
        raise _fail(exc) from exc
    except passkeys.Refused as refused:
        if refused.reason != "expired":
            address_failed(request)
            if refused.account is not None:
                row = db.get(AccountRow, refused.account.id)
                if row is not None and row.id not in devices_of(request.cookies.get(DEVICE_COOKIE)):
                    accounts.note_failure(db, row)
        raise error("passkey_refused", "The passkey was not accepted.", 401) from None
    row = db.get(AccountRow, account.id)
    known = row is not None and row.id in devices_of(request.cookies.get(DEVICE_COOKIE))
    if row is None or row.blocked_at is not None or (accounts.is_locked(row) and not known):
        # Like an unknown passkey: a blocked or locked account says nothing more.
        logger.warning("Passkey sign-in refused, account blocked or locked")
        raise error("passkey_refused", "The passkey was not accepted.", 401)
    accounts.note_success(db, row)
    # A passkey counts as both factors: a sign-in waiting for its code is done with.
    pending = request.cookies.get(PENDING_COOKIE)
    if pending:
        totp.finish_pending(pending)
        response.delete_cookie(PENDING_COOKIE, path="/api/v1/auth")
    logger.info("Signed in with a passkey name=%s", row.name)
    return sign_in(db, request, response, row, remember=payload.remember)
