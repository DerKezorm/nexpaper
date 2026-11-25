"""The invitations that bring people in: the operator makes a link (and may send it by mail), whoever follows it makes
an account. Only the hash of the token is kept, and a link works once.

Accepting runs through the shared account module (``invites.accept_invite``): display name, username (a suggestion),
address (the invitation's), password twice. A request of 1.12.0 sends only ``name`` and ``password``: the username
stands in for the display name, the invitation's address is taken (``older_request``). An invitation that went by
mail and is accepted with its address unchanged proves that address (the person holds the mailbox); otherwise the
address counts, and the intake trusts it once its link is opened.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Request, Response
from fastapi import Path as PathParam
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..deps import DbSession, OperatorAccount, address_failed, address_guard, too_many
from ..errors import error
from ..models import Account as AccountRow
from ..models import Invite
from ..security import MIN_PASSWORD, SESSION_COOKIE, brake, session_account
from ..services import accounts, kontenpost, mailer, settings_service
from ..services.accounts import AccountError
from ..services.konten_store import KontenStore
from ..vendor import nexkonten
from ..vendor.nexkonten import invites as konten_invites
from .auth import check_confirm, check_password, fail, interface_language, sign_in

logger = logging.getLogger("nexpaper.auth")

router = APIRouter(prefix="/api/v1", tags=["invitations"])

Token = Annotated[str, PathParam(min_length=20, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class InviteIn(BaseModel):
    days: int = 7
    email: str = Field(default="", max_length=255)
    #: What the operator gives as the display name; the person may change it on the page of the link.
    display_name: str = Field(default="", max_length=200)
    send: bool = False


class AcceptIn(BaseModel):
    #: The username (field ``name`` as in 1.12.0).
    name: str = Field(max_length=64)
    password: str = Field(max_length=200)
    #: Since the shared account module; left out (a page of 1.12.0), the username stands in.
    display_name: str | None = Field(default=None, max_length=200)
    #: Left out, the invitation's address.
    email: str | None = Field(default=None, max_length=255)
    password_confirm: str | None = Field(default=None, max_length=200)


#: Invitation mails the operator may send in an hour.
MAILS_PER_HOUR = 20
#: Taken names one sender may try when accepting invitations before it waits.
NAME_TRIES = 8


def _invite_view(invite: Invite, db: DbSession) -> dict[str, Any]:
    by = db.get(AccountRow, invite.created_by) if invite.created_by else None
    return {
        "id": invite.id,
        "email": invite.email,
        "display_name": invite.display_name or "",
        "by": by.name if by else None,
        "created_at": invite.created_at.isoformat(),
        "expires_at": invite.expires_at.isoformat(),
        # Ran out: it stays in the list until withdrawn, and the link says so.
        "expired": accounts.expired(invite),
        "mailed": bool(invite.mailed),
    }


def _link(db: DbSession, request: Request, token: str) -> str:
    base = settings_service.public_url(db) or str(request.base_url).rstrip("/")
    return f"{base}/invite/{token}"


@router.get("/invites", summary="Open invitations, also those that ran out (operator)")
def list_invites(_operator: OperatorAccount, db: DbSession) -> list[dict[str, Any]]:
    return [_invite_view(invite, db) for invite in accounts.open_invites(db)]


@router.post("/invites", status_code=201, summary="Invite somebody into nexpaper; the link is shown once (operator)")
def invite(payload: InviteIn, request: Request, operator: OperatorAccount, db: DbSession) -> dict[str, Any]:
    """Address and display name are what the shared module takes (``invites.invite_values``: an address another account
    has is refused, a display name another shows too); no username is set here, the person chooses it."""
    email = payload.email.strip()
    if payload.send and not email:
        raise error("invalid_email", "Sending needs a mail address.", 422)
    try:
        email, shown = konten_invites.invite_values(KontenStore(db), email=email, display_name=payload.display_name)
    except nexkonten.AccountError as exc:
        raise fail(exc) from exc
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
        row, token = accounts.create_invite(db, operator, days=payload.days, email=email, display_name=shown,
                                            mailed=payload.send)
    except AccountError as exc:
        raise fail(exc) from exc
    link = _link(db, request, token)
    sent = False
    if payload.send:
        try:
            mailer.send_invite(db, email, link, by=operator.display_name or operator.name,
                               until=row.expires_at.date().isoformat(), days=payload.days)
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


def _form(db: DbSession, request: Request, token: str) -> nexkonten.invites.InviteForm:
    """The invitation's form, or 404. A link that does not hold counts as a failure of the address: invitation links
    are no way to guess at."""
    address_guard(request)
    try:
        return konten_invites.invite_form(KontenStore(db), token)
    except nexkonten.AccountError as exc:
        address_failed(request)
        raise error("invite_invalid", "This invitation is not valid any more.", 404, reason=exc.code) from exc


@router.get("/invite/{token}", summary="Whether an invitation holds, and what the form starts with (no sign-in needed)")
def invite_state(token: Token, request: Request, db: DbSession) -> dict[str, Any]:
    form = _form(db, request, token)
    signed_in = session_account(db, request.cookies.get(SESSION_COOKIE))
    return {
        "min_password": MIN_PASSWORD,
        "signed_in_as": signed_in.name if signed_in else None,
        "display_name": form.display_name,
        "name": form.username,
        "email": form.email,
    }


@router.post("/invite/{token}", summary="Accept an invitation with a new account")
def accept(token: Token, payload: AcceptIn, request: Request, response: Response, db: DbSession) -> dict[str, Any]:
    # A name that is taken must be said, so the person can pick another; the brake keeps it from being a way to try
    # names one after another.
    key = "invite-name:" + (request.client.host if request.client else "-")
    wait = brake.wait_seconds(key, NAME_TRIES)
    if wait:
        raise too_many(wait)
    check_password(payload.password)
    check_confirm(payload.password, payload.password_confirm)
    if not settings_service.get(db, "password_login"):
        raise error("password_login_off", "Sign-in with a password is turned off.", 403)
    store = KontenStore(db)
    found = store.find_invite(token)
    if found is None:
        address_guard(request)
        address_failed(request)
        raise error("invite_invalid", "This invitation is not valid any more.", 404)
    older = payload.display_name is None
    address = found.email if payload.email is None else payload.email
    row = found.rights
    mailed = isinstance(row, Invite) and bool(row.mailed)
    try:
        done = konten_invites.accept_invite(
            store, token, display_name=payload.display_name or "", username=payload.name, email=address,
            password=payload.password, language=interface_language(request), mail=kontenpost.can_mail(db),
            older_request=older, proven=mailed,
        )
    except nexkonten.AccountError as exc:
        if exc.code == "username_taken":
            brake.failed(key, NAME_TRIES)
        if exc.code in ("invite_invalid", "invite_expired"):
            raise error("invite_invalid", "This invitation is not valid any more.", 404, reason=exc.code) from exc
        raise fail(exc) from exc
    if done.mail is not None:
        # Another address than the invitation's: it waits for its link (sent now; a failure leaves it waiting, the
        # profile sends it again).
        kontenpost.send_now(db, done.mail)
    account = db.get(AccountRow, int(done.account.id))
    assert account is not None
    logger.info("Invite used name=%s", account.name)
    return sign_in(db, request, response, account)
