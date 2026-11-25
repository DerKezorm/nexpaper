"""The second factor: enrol, confirm, turn off, new recovery codes, the code step of a sign-in, the operator's reset.

The work is the shared account module's (``vendor/nexkonten/factor.py``): the seed waiting for its first code is sealed
in the database (``users.totp_pending``, ten minutes, it survives a restart and its QR code can be shown again), ten
recovery codes for new ones (the eight of 1.12.0 keep working), every code counted at the module's brake.

The password step of a sign-in lives in ``routers/auth.py``; when the account has a second factor it answers
``{"second_factor": true}`` and leaves a short-lived cookie. The code step here turns that into the session.

Right after signing in, a session that may only set up the second factor (``STAGE_SETUP``) enrols without giving the
password again: it was given a moment ago. Confirming the code moves that session on to ``STAGE_CODES``, where it shows
the recovery codes and waits for "I have kept them" (``/api/v1/auth/setup/done``). From the account page a full session
enrols with the password (or a fresh sign-in at the provider for an account without one).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Path, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import update

from ..deps import (
    BrowserAccount,
    DbSession,
    OperatorAccount,
    address_failed,
    address_guard,
    confirm_operator,
    confirmed_without_password,
    session_of,
)
from ..errors import error
from ..models import STAGE_CODES, STAGE_SETUP, AuthSession
from ..models import Account as AccountRow
from ..security import SESSION_COOKIE, hash_token
from ..services import accounts, kontenpost, notices, totp
from ..services.konten_store import KontenStore
from ..vendor import nexkonten
from ..vendor.nexkonten import factor
from .auth import PENDING_COOKIE, OperatorConfirmIn, account_view, browser_mark, fail, sign_in

logger = logging.getLogger("nexpaper.auth")

router = APIRouter(prefix="/api/v1", tags=["second factor"])


class PasswordIn(BaseModel):
    password: str = Field(default="", max_length=200)


class ConfirmIn(BaseModel):
    code: str = Field(max_length=32)
    #: The password, from the account page; not asked right after signing in.
    password: str = Field(default="", max_length=200)


class CodeIn(BaseModel):
    code: str = Field(max_length=32)
    #: "Stay signed in on this device", as ticked at this step; left out keeps what the first step said.
    remember: bool | None = None


def _row(db: DbSession, account: AccountRow) -> AccountRow:
    row = db.get(AccountRow, account.id)
    if row is None:
        raise error("sign_in_required", "Sign in first.", 401)
    return row


def _clear_pending_cookie(response: Response) -> None:
    response.delete_cookie(PENDING_COOKIE, path="/api/v1/auth")


def _confirmed(request: Request, row: AccountRow) -> bool:
    """``actor_confirmed`` for the module: the session right after signing in (it may only set up the factor), or an
    account without a password with a fresh sign-in at its provider. An account with a password gives it."""
    if session_of(request).stage == STAGE_SETUP:
        return True
    return confirmed_without_password(request, row)


# --- Enrolment --------------------------------------------------------------------------------------------------------


def _enrolment(enrolment: factor.Enrolment) -> dict[str, Any]:
    expires = enrolment.expires_at.isoformat() if enrolment.expires_at is not None else None
    return {"secret": enrolment.seed, "uri": enrolment.uri, "qr_svg": totp.qr_svg(enrolment.uri),
            "expires_at": expires}


@router.post("/auth/totp/begin", summary="Start enrolling an authenticator app; the seed is shown once")
def begin(account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    if account.totp_secret_enc:
        raise error("totp_enabled", "The second factor is on already. Turn it off first.", 409)
    try:
        return _enrolment(factor.begin_totp(KontenStore(db), account.id, issuer=totp.ISSUER))
    except nexkonten.AccountError as exc:
        raise fail(exc) from exc


@router.get("/auth/totp/setup", summary="The authenticator that waits for its first code, once more")
def waiting_setup(account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    """The same QR code and secret as ``begin`` gave while the setup waits (the page was reloaded, another tab),
    ``{"waiting": false}`` when nothing waits. Reading it changes nothing."""
    held = factor.pending_setup(KontenStore(db), account.id, issuer=totp.ISSUER)
    if held is None or account.totp_secret_enc:
        return {"waiting": False}
    return {"waiting": True, **_enrolment(held)}


def _to_codes_stage(request: Request, db: DbSession) -> None:
    """A session that was setting up moves on to showing the recovery codes."""
    if session_of(request).stage == STAGE_SETUP:
        db.execute(
            update(AuthSession)
            .where(AuthSession.token_hash == hash_token(request.cookies.get(SESSION_COOKIE) or ""),
                   AuthSession.stage == STAGE_SETUP)
            .values(stage=STAGE_CODES)
        )
        db.commit()


@router.post("/auth/totp/confirm", summary="Finish enrolling: a code from the app (and the password, later on)")
def confirm(payload: ConfirmIn, request: Request, account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    row = _row(db, account)
    if row.totp_secret_enc:
        raise error("totp_enabled", "The second factor is on already. Turn it off first.", 409)
    store = KontenStore(db)
    held = store.pending_totp(row.id)
    if held is None or held[1] <= nexkonten.common.utcnow():
        raise error("totp_enrolment_expired", "The enrolment timed out. Start again.", 410)
    setting_up = session_of(request).stage == STAGE_SETUP
    if row.totp_recovery and (setting_up or not totp.passkey_count(db, row.id)):
        # New codes with a first authenticator, as in 1.12.0 (the module keeps codes an account has).
        store.set_recovery(row.id, [])
    try:
        done = factor.confirm_totp(store, row.id, payload.code, password=payload.password,
                                   actor_confirmed=_confirmed(request, row))
    except nexkonten.AccountError as exc:
        db.rollback()
        if exc.code == "enrolment_expired":
            raise error("totp_enrolment_expired", "The enrolment timed out. Start again.", 410) from exc
        if exc.code == "code_wrong":
            raise error("totp_code_wrong", "The code is not right. Check the time on your phone and try again.",
                        422) from exc
        raise fail(exc) from exc
    _to_codes_stage(request, db)
    db.refresh(row)
    logger.info("Second factor turned on name=%s", row.name)
    return {"recovery_codes": done.codes or None, "next": done.next, "account": account_view(row)}


@router.post("/auth/totp/disable", summary="Turn the code from the app off; needs the password")
def disable(payload: PasswordIn, request: Request, account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    """Through the shared module only (``factor.disable_totp``): the password counts at its brake, a required factor
    stays (``second_factor_required``), a setup that waits ends too."""
    row = _row(db, account)
    if not row.totp_secret_enc:
        raise error("totp_not_enabled", "The second factor is not on.", 409)
    try:
        factor.disable_totp(KontenStore(db), row.id, password=payload.password,
                            actor_confirmed=confirmed_without_password(request, row))
    except nexkonten.AccountError as exc:
        db.rollback()
        if exc.code in ("factor_required", "last_factor"):
            raise error("second_factor_required", "The operator requires a second factor; it cannot be turned "
                        "off.", 409) from exc
        raise fail(exc) from exc
    totp.forget_account(row.id)
    db.refresh(row)
    logger.info("Second factor turned off name=%s", row.name)
    return account_view(row)


@router.post("/auth/totp/recovery", summary="New recovery codes; the old ones stop working")
def new_recovery_codes(payload: PasswordIn, request: Request, account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    row = _row(db, account)
    if not totp.has_second_factor(db, row):
        raise error("totp_not_enabled", "The second factor is not on.", 409)
    try:
        codes = factor.new_codes(KontenStore(db), row.id, password=payload.password,
                                 actor_confirmed=confirmed_without_password(request, row))
    except nexkonten.AccountError as exc:
        raise fail(exc) from exc
    db.refresh(row)
    logger.info("Recovery codes renewed name=%s", row.name)
    return {"recovery_codes": codes, "account": account_view(row)}


class FactorResetIn(OperatorConfirmIn):
    #: The paired devices go too (the lost phone may be one of them): on from the start, the page asks.
    disconnect_devices: bool = True
    #: The passkeys go too (a lost phone may carry one): on from the start, the page asks.
    remove_passkeys: bool = True


@router.get("/accounts/{account_id}/totp/reset", summary="Operator: what a reset of the second factor takes away")
def operator_reset_overview(
    account_id: Annotated[int, Path(ge=1)], operator: OperatorAccount, db: DbSession
) -> dict[str, Any]:
    """``factor.reset_overview``: the authenticator, the recovery codes left, the passkeys by name and the paired
    devices, for the dialog before the reset."""
    try:
        seen = factor.reset_overview(KontenStore(db), account_id, actor_id=operator.id)
    except nexkonten.AccountError as exc:
        raise fail(exc) from exc
    return {
        "authenticator": seen.authenticator,
        "recovery_codes": seen.recovery_codes,
        "passkeys": [{"uid": key.uid, "name": key.name} for key in seen.passkeys],
        "devices": [{"uid": entry.uid, "label": entry.label} for entry in seen.devices],
        "parts": list(seen.parts),
    }


@router.post("/accounts/{account_id}/totp/reset", summary="Operator: take the second factor of a locked-out account")
def operator_reset(
    account_id: Annotated[int, Path(ge=1)],
    payload: FactorResetIn,
    request: Request,
    operator: OperatorAccount,
    db: DbSession,
) -> dict[str, Any]:
    """Through the shared account module (``factor.operator_reset``): the code from the app, the recovery codes and,
    with ``remove_passkeys``, the passkeys go, every browser session and waiting sign-in ends, with
    ``disconnect_devices`` the paired devices too; the address hears of it, the devices by a push."""
    confirm_operator(request, db, operator, payload.current_password)
    if account_id == operator.id:
        raise error("use_disable", "Turn your own second factor off on your account page, with your password.", 409)
    row = db.get(AccountRow, account_id)
    if row is None:
        raise error("not_found", "No such account.", 404)
    if not totp.has_second_factor(db, row):
        raise error("totp_not_enabled", "The second factor is not on.", 409)
    store = KontenStore(db)
    try:
        mail = factor.operator_reset(store, row.id, actor_id=operator.id, actor_confirmed=True,
                                     disconnect_devices=payload.disconnect_devices,
                                     remove_passkeys=payload.remove_passkeys)
    except nexkonten.AccountError as exc:
        raise fail(exc) from exc
    totp.forget_account(row.id)
    kontenpost.queue(db, mail, by=operator.display_name or operator.name)
    notices.factor_reset(row, operator.name)
    db.refresh(row)
    logger.warning("Second factor reset by the operator name=%s by=%s, all sessions ended", row.name, operator.name)
    return account_view(row)


# --- The code step of a sign-in ---------------------------------------------------------------------------------------


def _expired(
    response: Response, token: str | None, text: str = "Start again with your password.",
    code: str = "second_factor_expired",
) -> Exception:
    if token:
        totp.finish_pending(token)
    _clear_pending_cookie(response)
    return error(code, text, 401)


@router.post("/auth/login/totp", summary="Second step of the sign-in: the code from the app or a recovery code")
def login_code(payload: CodeIn, request: Request, response: Response, db: DbSession) -> dict[str, Any]:
    token = request.cookies.get(PENDING_COOKIE)
    pending = totp.get_pending(token)
    if token is None or pending is None:
        raise _expired(response, None)
    address_guard(request)
    row = db.get(AccountRow, pending.account_id)
    if row is None or not (row.totp_secret_enc or totp.load_recovery(row.totp_recovery)):
        # Nothing a code could answer (an account with passkeys only answers with one, ``routers/passkeys``).
        raise _expired(response, token)
    if row.blocked_at is not None:
        # Blocked between the password and the code: no session.
        totp.finish_pending(token)
        _clear_pending_cookie(response)
        raise error("account_blocked", "This account is blocked. Ask the operator.", 403)
    # A browser that signed in as this account before is not kept out by a lock that strangers caused, here as at the
    # password step. What holds for it all the same: five codes per sign-in and the module's brake per account.
    known_device = bool(browser_mark(db, request, row.id))
    if accounts.is_locked(row) and not known_device:
        # Wrong codes count against the account like wrong passwords, whatever address they come from.
        totp.finish_pending(token)
        _clear_pending_cookie(response)
        raise error("account_locked", "Too many failed sign-ins. Try again later.", 429)

    store = KontenStore(db)
    if row.totp_secret_enc and store.totp_seed(row.id) is None:
        # A different secret.key than the one that sealed the seed. Failing closed is the only safe answer; the
        # operator resets the second factor and the person enrols again.
        raise _expired(response, token, "The second factor cannot be checked on this installation. Ask the "
                       "operator to reset it.", "second_factor_unavailable")
    try:
        # A code from the app or a recovery code (also those of 1.12.0), each counted once, also for two requests at
        # the same moment; every code counts at the module's brake (``code:<account>``).
        method = factor.check_code(store, row.id, payload.code)
    except nexkonten.AccountError as exc:
        if exc.code == "too_many_attempts":
            raise fail(exc) from exc
        address_failed(request)
        db.refresh(row)
        if not known_device:
            # Failures of a browser the account knows do not count towards the lock.
            accounts.note_failure(db, row)
        still_pending = totp.fail_pending(token) and (known_device or not accounts.is_locked(row))
        logger.warning("Second factor failed name=%s", row.name)
        if not still_pending:
            raise _expired(response, token, "Too many wrong codes. Start again with your password.") from exc
        raise error("totp_code_wrong", "The code is not right.", 401) from exc

    if totp.finish_pending(token) is None:
        # Another request with this sign-in finished it a moment ago.
        raise _expired(response, None)
    _clear_pending_cookie(response)
    db.refresh(row)
    if method == "recovery":
        logger.warning("Recovery code used name=%s left=%s", row.name, len(totp.load_recovery(row.totp_recovery)))
    else:
        logger.info("Second factor passed name=%s", row.name)
    remember = pending.remember if payload.remember is None else payload.remember
    return sign_in(db, request, response, row, remember=remember)


@router.post("/auth/login/totp/cancel", status_code=204, summary="Give up the second step and start over")
def cancel_code(request: Request, response: Response) -> None:
    token = request.cookies.get(PENDING_COOKIE)
    if token:
        totp.finish_pending(token)
    _clear_pending_cookie(response)
