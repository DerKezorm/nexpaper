"""A new password by a link: the operator sends one, or a person asks for one ("Forgot your password?").

The operator has no way to set a password. The page of the link takes the new one from the person themselves.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, Field

from ..deps import (
    DbSession,
    OperatorAccount,
    address_failed,
    address_guard,
    client_ip,
    confirm_operator,
    too_many,
)
from ..errors import error
from ..models import OPERATOR, PasswordReset
from ..models import Account as AccountRow
from ..security import MIN_PASSWORD, brake
from ..services import mailer, notices, resets, settings_service
from .auth import OperatorConfirmIn, check_password

logger = logging.getLogger("nexpaper.auth")

router = APIRouter(prefix="/api/v1", tags=["password reset"])

Token = Annotated[str, Path(min_length=20, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]

#: Mails the operator may send in an hour.
MAILS_PER_HOUR = 20


class ForgotIn(BaseModel):
    #: The name of the account, or the mail address on record.
    name: str = Field(max_length=255)


class NewPasswordIn(BaseModel):
    password: str = Field(max_length=200)


# --- A person asks for a link ----------------------------------------------------------------------------------------


@router.post("/auth/forgot", status_code=202, summary="Ask for a link to set a new password (no sign-in needed)")
def forgot(payload: ForgotIn, request: Request, db: DbSession) -> dict[str, bool]:
    """The answer is the same whether the account exists or not, and so is the time it takes: the mail goes out in the
    background, and only to the address on record."""
    if not resets.available(db):
        raise error("reset_off", "Asking for a link is not set up on this server.", 409)
    address_guard(request)
    key = "forgot-addr:" + client_ip(request)
    wait = brake.wait_seconds(key, resets.PER_ADDRESS)
    if wait:
        raise too_many(wait)
    brake.failed(key, resets.PER_ADDRESS)
    # What was typed is counted too, found or not: a name that does not exist is held back exactly like one that does.
    typed_key = "forgot-typed:" + resets.key_of(payload.name)
    typed_wait = brake.wait_seconds(typed_key, resets.PER_ACCOUNT)
    brake.failed(typed_key, resets.PER_ACCOUNT)
    if typed_wait:
        return {"ok": True}
    # Nothing more happens in the request, found or not: making the link and mailing it are done in the background,
    # so that neither the answer nor the time it takes tells whether there is such an account.
    found = [account.id for account in resets.accounts_for(db, payload.name)]
    if found:
        notices.later(resets.issue_and_send, found)
    return {"ok": True}


# --- Using a link ----------------------------------------------------------------------------------------------------


def _valid(db: DbSession, request: Request, token: str) -> tuple[PasswordReset, AccountRow]:
    """The link and its account, or 404. A link that does not hold counts as a failure of the address: these links are
    no way to guess at."""
    address_guard(request)
    found = resets.find(db, token)
    # With signing in by password turned off, only the operator (who keeps the password as the way in) may set one.
    if found is None or (not settings_service.get(db, "password_login") and found[1].role != OPERATOR):
        address_failed(request)
        raise error("reset_invalid", "This link is not valid any more.", 404)
    return found


@router.get("/reset/{token}", summary="Whether a link to set a new password holds (no sign-in needed)")
def reset_state(token: Token, request: Request, db: DbSession) -> dict[str, Any]:
    _row, account = _valid(db, request, token)
    return {"name": account.name, "min_password": MIN_PASSWORD}


@router.post("/reset/{token}", status_code=204, summary="Set the new password; every session of the account ends")
def reset_password(token: Token, payload: NewPasswordIn, request: Request, db: DbSession) -> None:
    check_password(payload.password)
    _valid(db, request, token)
    if resets.use(db, token, payload.password) is None:
        address_failed(request)
        raise error("reset_invalid", "This link is not valid any more.", 404)


# --- The operator sends a link ---------------------------------------------------------------------------------------


@router.post("/accounts/{account_id}/reset-link", summary="Send an account a link to set a new password (operator)")
def send_link(
    account_id: Annotated[int, Path(ge=1)], payload: OperatorConfirmIn, request: Request, operator: OperatorAccount,
    db: DbSession,
) -> dict[str, Any]:
    """By mail where a server is set up, the public address is known and the account has an address; otherwise the
    link comes back once, for the operator to pass on."""
    confirm_operator(request, db, operator, payload.current_password)
    if account_id == operator.id:
        raise error("use_account_page", "Change your own password on your account page.", 409)
    row = db.get(AccountRow, account_id)
    if row is None:
        raise error("not_found", "No such account.", 404)
    if row.blocked_at is not None:
        raise error("account_blocked", "This account is blocked.", 409)
    by_mail = bool(mailer.configured(db) and settings_service.public_url(db) and row.email.strip())
    if by_mail:
        key = f"reset-mail:{operator.id}"
        if brake.wait_seconds(key, MAILS_PER_HOUR):
            raise error("too_many_attempts", "Too many mails. Try again later.", 429)
        brake.failed(key, MAILS_PER_HOUR)
    made, token = resets.make(db, row, operator)
    if by_mail:
        try:
            mailer.send_reset(db, row.email.strip(), resets.link_to(db, token), name=row.name, hours=resets.HOURS)
        except mailer.MailError as exc:
            # Mail was the way: kept, the link would stand without anybody holding it.
            db.delete(made)
            db.commit()
            raise error(exc.code, str(exc), 502) from exc
        return {"sent": True, "email": row.email.strip(), "expires_at": made.expires_at.isoformat()}
    base = settings_service.public_url(db) or str(request.base_url).rstrip("/")
    return {"sent": False, "link": f"{base}/reset/{token}", "expires_at": made.expires_at.isoformat()}
