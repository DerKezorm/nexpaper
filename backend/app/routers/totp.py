"""The second factor: enrol, confirm, turn off, new recovery codes, the code step of a sign-in, the operator's reset.

The password step of a sign-in lives in ``routers/auth.py``; when the account has a second factor it answers
``{"second_factor": true}`` and leaves a short-lived cookie. The code step here turns that into the session.

Right after signing in, a session that may only set up the second factor (``STAGE_SETUP``) enrols without giving the
password again: it was given a moment ago. Confirming the code moves that session on to ``STAGE_CODES``, where it shows
the recovery codes and waits for "I have kept them" (``/api/v1/auth/setup/done``). From the account page a full session
enrols with the password (``deps.confirm_self``).
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
    confirm_self,
    session_of,
)
from ..errors import error
from ..models import STAGE_CODES, STAGE_SETUP, AuthSession
from ..models import Account as AccountRow
from ..security import DEVICE_COOKIE, SESSION_COOKIE, devices_of, end_all_sessions, hash_token
from ..services import accounts, notices, passkeys, settings_service, totp
from .auth import PENDING_COOKIE, OperatorConfirmIn, account_view, sign_in

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


def last_factor_guard(db: DbSession, row: AccountRow) -> None:
    """The operator asks for a second factor: the last one cannot go."""
    if settings_service.get(db, "two_factor_required") and not totp.provider_checks(db, row):
        raise error("second_factor_required", "The operator requires a second factor; it cannot be turned off.", 409)


def enrolled(request: Request, db: DbSession, row: AccountRow) -> list[str] | None:
    """After a new second factor: the recovery codes when this was the account's first (or it had none left), and a
    session that was setting up moves on to showing them. Gives the codes, or None when the old ones stay."""
    codes = None
    if not totp.load_recovery(row.totp_recovery) or session_of(request).stage == STAGE_SETUP:
        codes = totp.generate_recovery_codes()
        row.totp_recovery = totp.recovery_hashes(codes)
    db.commit()
    if session_of(request).stage == STAGE_SETUP:
        db.execute(
            update(AuthSession)
            .where(AuthSession.token_hash == hash_token(request.cookies.get(SESSION_COOKIE) or ""),
                   AuthSession.stage == STAGE_SETUP)
            .values(stage=STAGE_CODES)
        )
        db.commit()
    return codes


# --- Enrolment --------------------------------------------------------------------------------------------------------


@router.post("/auth/totp/begin", summary="Start enrolling an authenticator app; the seed is shown once")
def begin(account: BrowserAccount) -> dict[str, Any]:
    if account.totp_secret_enc:
        raise error("totp_enabled", "The second factor is on already. Turn it off first.", 409)
    seed = totp.begin_enrolment(account.id)
    uri = totp.provisioning_uri(seed, account.name)
    return {"secret": seed, "uri": uri, "qr_svg": totp.qr_svg(uri)}


@router.post("/auth/totp/confirm", summary="Finish enrolling: a code from the app (and the password, later on)")
def confirm(payload: ConfirmIn, request: Request, account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    row = _row(db, account)
    if row.totp_secret_enc:
        raise error("totp_enabled", "The second factor is on already. Turn it off first.", 409)
    seed = totp.pending_seed(row.id)
    if seed is None:
        raise error("totp_enrolment_expired", "The enrolment timed out. Start again.", 410)
    if session_of(request).stage != STAGE_SETUP:
        confirm_self(request, db, row, payload.password)
    step = totp.verify_code(seed, payload.code)
    if step is None:
        raise error("totp_code_wrong", "The code is not right. Check the time on your phone and try again.", 422)
    row.totp_secret_enc = totp.seal_seed(seed)
    row.totp_last_step = step
    codes = enrolled(request, db, row)
    totp.drop_enrolment(row.id)
    logger.info("Second factor turned on name=%s", row.name)
    return {"recovery_codes": codes, "account": account_view(row)}


@router.post("/auth/totp/disable", summary="Turn the code from the app off; needs the password")
def disable(payload: PasswordIn, request: Request, account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    row = _row(db, account)
    if not row.totp_secret_enc:
        raise error("totp_not_enabled", "The second factor is not on.", 409)
    confirm_self(request, db, row, payload.password)
    if totp.passkey_count(db, row.id) == 0:
        last_factor_guard(db, row)
    row.totp_secret_enc = ""
    row.totp_last_step = 0
    if totp.passkey_count(db, row.id) == 0:
        # The last factor went; recovery codes for nothing would only be a way around it.
        row.totp_recovery = ""
    db.commit()
    totp.forget_account(row.id)
    logger.info("Second factor turned off name=%s", row.name)
    return account_view(row)


@router.post("/auth/totp/recovery", summary="New recovery codes; the old ones stop working")
def new_recovery_codes(payload: PasswordIn, request: Request, account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    row = _row(db, account)
    if not totp.has_second_factor(db, row):
        raise error("totp_not_enabled", "The second factor is not on.", 409)
    confirm_self(request, db, row, payload.password)
    codes = totp.generate_recovery_codes()
    row.totp_recovery = totp.recovery_hashes(codes)
    db.commit()
    logger.info("Recovery codes renewed name=%s", row.name)
    return {"recovery_codes": codes, "account": account_view(row)}


@router.post("/accounts/{account_id}/totp/reset", summary="Operator: take the second factor of a locked-out account")
def operator_reset(
    account_id: Annotated[int, Path(ge=1)],
    payload: OperatorConfirmIn,
    request: Request,
    operator: OperatorAccount,
    db: DbSession,
) -> dict[str, Any]:
    confirm_operator(request, db, operator, payload.current_password)
    if account_id == operator.id:
        raise error("use_disable", "Turn your own second factor off on your account page, with your password.", 409)
    row = db.get(AccountRow, account_id)
    if row is None:
        raise error("not_found", "No such account.", 404)
    if not totp.has_second_factor(db, row):
        raise error("totp_not_enabled", "The second factor is not on.", 409)
    row.totp_secret_enc = ""
    row.totp_recovery = ""
    row.totp_last_step = 0
    db.commit()
    passkeys.remove_all(db, row.id)
    totp.forget_account(row.id)
    # A reset is what happens after a lost phone or a suspected intruder: whoever holds a session of that account
    # is thrown out, and signs in afresh, setting the second factor up again where the operator asks for one.
    end_all_sessions(db, row.id)
    notices.factor_reset(row, operator.name)
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
    if row is None or not totp.has_second_factor(db, row) or row.blocked_at is not None:
        raise _expired(response, token)
    # A browser that signed in as this account before is not kept out by a lock that strangers caused, here as at the
    # password step. What holds for it all the same: five codes per sign-in and the brake per address.
    known_device = row.id in devices_of(request.cookies.get(DEVICE_COOKIE))
    if accounts.is_locked(row) and not known_device:
        # Wrong codes count against the account like wrong passwords, whatever address they come from.
        totp.finish_pending(token)
        _clear_pending_cookie(response)
        raise error("account_locked", "Too many failed sign-ins. Try again later.", 429)

    typed = totp.normalize_code(payload.code)
    used_recovery = False
    accepted = False
    if len(typed) == totp.DIGITS and typed.isdigit():
        if row.totp_secret_enc:
            try:
                seed = totp.open_seed(row.totp_secret_enc)
            except totp.SeedUnreadable:
                # A different secret.key than the one that sealed the seed. Failing closed is the only safe answer;
                # the operator resets the second factor and the person enrols again.
                logger.error("Second factor seed unreadable name=%s (secret.key changed?)", row.name)
                raise _expired(response, token, "The second factor cannot be checked on this installation. Ask the "
                               "operator to reset it.", "second_factor_unavailable") from None
            step = totp.verify_code(seed, typed, after_step=row.totp_last_step)
            # Checked and written in one: the same code twice, even at the same moment, lets in once.
            accepted = step is not None and totp.claim_step(db, row.id, step)
    else:
        before = row.totp_recovery
        remaining = totp.use_recovery(before, typed)
        accepted = remaining is not None and totp.claim_recovery(db, row.id, before, remaining)
        used_recovery = accepted
    if not accepted:
        address_failed(request)
        db.refresh(row)
        if not known_device:
            # Failures of a browser the account knows do not count towards the lock (see ``accounts.authenticate``).
            accounts.note_failure(db, row)
        still_pending = totp.fail_pending(token) and (known_device or not accounts.is_locked(row))
        logger.warning("Second factor failed name=%s", row.name)
        if not still_pending:
            raise _expired(response, token, "Too many wrong codes. Start again with your password.")
        raise error("totp_code_wrong", "The code is not right.", 401)

    if totp.finish_pending(token) is None:
        # Another request with this sign-in finished it a moment ago.
        raise _expired(response, None)
    _clear_pending_cookie(response)
    db.refresh(row)
    accounts.note_success(db, row)
    if used_recovery:
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
