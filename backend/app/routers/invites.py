"""The invitations that bring people in: the operator makes a link (and may send it by mail), whoever follows it makes
an account. Only the hash of the token is kept, and a link works once."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi import Path as PathParam
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..deps import DbSession, OperatorAccount, address_failed, address_guard, client_ip
from ..errors import detail, error
from ..models import Account as AccountRow
from ..models import Invite
from ..security import MIN_PASSWORD, SESSION_COOKIE, brake, session_account
from ..services import accounts, mailer, settings_service
from ..services.accounts import AccountError
from .auth import check_password, fail, interface_language, sign_in

logger = logging.getLogger("nexpaper.auth")

router = APIRouter(prefix="/api/v1", tags=["invitations"])

Token = Annotated[str, PathParam(min_length=20, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class InviteIn(BaseModel):
    days: int = 7
    email: str = Field(default="", max_length=255)
    send: bool = False


class AcceptIn(BaseModel):
    name: str = Field(max_length=64)
    password: str = Field(max_length=200)


#: Invitation mails the operator may send in an hour.
MAILS_PER_HOUR = 20
#: Taken names one sender may try when accepting invitations before it waits.
NAME_TRIES = 8


def _invite_view(invite: Invite, db: DbSession) -> dict[str, Any]:
    by = db.get(AccountRow, invite.created_by) if invite.created_by else None
    return {
        "id": invite.id,
        "email": invite.email,
        "by": by.name if by else None,
        "created_at": invite.created_at.isoformat(),
        "expires_at": invite.expires_at.isoformat(),
    }


def _link(db: DbSession, request: Request, token: str) -> str:
    base = settings_service.public_url(db) or str(request.base_url).rstrip("/")
    return f"{base}/invite/{token}"


@router.get("/invites", summary="Open invitations (operator)")
def list_invites(_operator: OperatorAccount, db: DbSession) -> list[dict[str, Any]]:
    return [_invite_view(invite, db) for invite in accounts.open_invites(db)]


@router.post("/invites", status_code=201, summary="Invite somebody into nexpaper; the link is shown once (operator)")
def invite(payload: InviteIn, request: Request, operator: OperatorAccount, db: DbSession) -> dict[str, Any]:
    email = payload.email.strip()
    if email and not accounts.EMAIL_PATTERN.match(email):
        raise error("invalid_email", "This is not a mail address.", 422)
    if payload.send and not email:
        raise error("invalid_email", "Sending needs a mail address.", 422)
    if payload.send:
        # A mail goes out under the operator's mail server: never with a link to an address the request made up
        # (the Host header), and not without end.
        if not settings_service.public_url(db):
            raise error("public_url_missing", "Mail needs the public address of nexpaper; the operator sets it.", 409)
        key = f"invite-mail:{operator.id}"
        if brake.wait_seconds(key, MAILS_PER_HOUR):
            raise error("too_many_attempts", "Too many invitation mails. Try again later.", 429)
        brake.failed(key, MAILS_PER_HOUR)
    if email:
        # One open invitation per address: a second one replaces the first, so no old link stays valid beside it.
        for old in db.scalars(select(Invite).where(func.lower(Invite.email) == email.lower())):
            db.delete(old)
    try:
        row, token = accounts.create_invite(db, operator, days=payload.days, email=email)
    except AccountError as exc:
        raise fail(exc) from exc
    link = _link(db, request, token)
    sent = False
    if payload.send:
        try:
            mailer.send_invite(db, email, link, by=operator.display_name or operator.name,
                               until=row.expires_at.date().isoformat())
            sent = True
        except mailer.MailError as exc:
            # The link was to go by mail only: kept, the invitation would stand without anybody holding its link.
            db.delete(row)
            db.commit()
            raise error(exc.code, str(exc), 502) from exc
    return {**_invite_view(row, db), "link": link, "sent": sent}


@router.delete("/invites/{invite_id}", status_code=204, summary="Withdraw an invitation (operator)")
def withdraw(invite_id: Annotated[int, PathParam(ge=1)], _operator: OperatorAccount, db: DbSession) -> None:
    row = db.get(Invite, invite_id)
    if row is None:
        raise error("not_found", "No such invitation.", 404)
    db.delete(row)
    db.commit()


def _valid(db: DbSession, request: Request, token: str) -> Invite:
    """The invitation, or 404. A link that does not hold counts as a failure of the address: invitation links are
    no way to guess at."""
    address_guard(request)
    row = accounts.find_invite(db, token)
    if row is None:
        address_failed(request)
        raise error("invite_invalid", "This invitation is not valid any more.", 404)
    return row


@router.get("/invite/{token}", summary="Whether an invitation holds (no sign-in needed)")
def invite_state(token: Token, request: Request, db: DbSession) -> dict[str, Any]:
    _valid(db, request, token)
    signed_in = session_account(db, request.cookies.get(SESSION_COOKIE))
    return {"min_password": MIN_PASSWORD, "signed_in_as": signed_in.name if signed_in else None}


@router.post("/invite/{token}", summary="Accept an invitation with a new account")
def accept(token: Token, payload: AcceptIn, request: Request, response: Response, db: DbSession) -> dict[str, Any]:
    # A name that is taken must be said, so the person can pick another; the brake keeps it from being a way to try
    # names one after another.
    key = "invite-name:" + client_ip(request)
    wait = brake.wait_seconds(key, NAME_TRIES)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=detail("too_many_attempts", "Too many attempts. Try again later.", retry_after=wait),
            headers={"Retry-After": str(wait)},
        )
    check_password(payload.password)
    if not settings_service.get(db, "password_login"):
        raise error("password_login_off", "Sign-in with a password is turned off.", 403)
    _valid(db, request, token)
    try:
        account = accounts.accept_invite(db, token, payload.name, payload.password)
    except AccountError as exc:
        if exc.code == "name_taken":
            brake.failed(key, NAME_TRIES)
        raise fail(exc) from exc
    # The account speaks the language its person chose the page in, from the first day (the values it starts with).
    if not account.language:
        account.language = interface_language(request)
        db.commit()
    return sign_in(db, request, response, account)
