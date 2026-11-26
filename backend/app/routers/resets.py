"""A new password by a link: the operator makes one, or a person asks for one ("Forgot your password?").

Through the shared account module (``vendor/nexkonten/resets.py``): the link the person asks for holds one hour and
goes only to the account's own address that counts; the operator's holds 1, 7 or 30 days (one from the start), goes by
mail to that address where a mail server is there and is shown once otherwise, also for a blocked account (which stays
blocked). Using a link ends the browser sessions and the sign-ins waiting for a code; paired devices, API keys and
passkeys stay, and the account page lists them at the next sign-in ("These devices still have access"). The operator
never sets a password.
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
    confirmed_without_password,
)
from ..errors import error
from ..models import Account as AccountRow
from ..security import MIN_PASSWORD
from ..services import kontenpost, mailer, notices, post_store, resets, settings_service
from ..services.konten_store import KontenStore, own_store
from ..vendor import nexkonten, nexpost
from ..vendor.nexkonten import resets as konten_resets
from .auth import OperatorConfirmIn, check_confirm, check_password, fail

logger = logging.getLogger("nexpaper.auth")

router = APIRouter(prefix="/api/v1", tags=["password reset"])

Token = Annotated[str, Path(min_length=20, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class ForgotIn(BaseModel):
    #: "Username or email" (the field kept its name).
    name: str = Field(max_length=255)


class NewPasswordIn(BaseModel):
    password: str = Field(max_length=200)
    #: The password typed a second time; checked when given.
    password_confirm: str | None = Field(default=None, max_length=200)


class ResetLinkIn(OperatorConfirmIn):
    #: How long the link holds: 1, 7 or 30 days (one from the start).
    days: int = Field(default=konten_resets.OPERATOR_DAYS_DEFAULT)
    #: By mail to the account's address where a mail server is there (as 1.12.0 did from itself); False shows it.
    send: bool = True


# --- A person asks for a link ----------------------------------------------------------------------------------------


def _send(mail: nexkonten.Mail) -> None:
    """The link of "Forgot your password?", at once (the module drops the link when this raises): through
    ``mailer.send_reset`` (a thin name for ``kontenpost.send_reset``, the test "Bestand" catches it there), the way
    1.12.0 sent it, written by the shared post module in the account's language."""
    from ..db import SessionLocal

    with SessionLocal() as db:
        link = kontenpost.link_for(db, mail)
        if not link:
            raise ValueError("No public address for the link.")
        mailer.send_reset(db, mail.to, link, name=mail.username, hours=mail.hours)
        logger.info("Password link mailed name=%s", mail.username)


@router.post("/auth/forgot", status_code=202, summary="Ask for a link to set a new password (no sign-in needed)")
def forgot(payload: ForgotIn, request: Request, db: DbSession) -> dict[str, bool]:
    """The answer is the same whether the account exists or not, and so is the time it takes: the search, the link and
    the mail run in the background (``resets.forgot_in_background``), and the link goes only to the address of the
    account that counts. One sender may ask ten times (the module's brake ``forgot:<sender>``), one account gets five
    links in a while."""
    if not resets.available(db):
        raise error("reset_off", "Asking for a link is not set up on this server.", 409)
    try:
        konten_resets.forgot_in_background(
            payload.name, open_store=own_store, send=_send, later=notices.later, sender=client_ip(request)
        )
    except nexkonten.AccountError as exc:
        raise fail(exc) from exc
    return {"ok": True}


# --- Using a link ----------------------------------------------------------------------------------------------------


def _password_login(db: DbSession) -> bool:
    return bool(settings_service.get(db, "password_login"))


@router.get("/reset/{token}", summary="Whether a link to set a new password holds (no sign-in needed)")
def reset_state(token: Token, request: Request, db: DbSession) -> dict[str, Any]:
    """A link that does not hold counts as a failure of the sender: these links are no way to guess at."""
    address_guard(request)
    try:
        account = konten_resets.reset_state(KontenStore(db), token, password_login=_password_login(db))
    except nexkonten.AccountError as exc:
        address_failed(request)
        raise error("reset_invalid", "This link is not valid any more.", 404, reason=exc.code) from exc
    return {"name": account.username, "display_name": account.display_name, "min_password": MIN_PASSWORD}


@router.post("/reset/{token}", status_code=204, summary="Set the new password; browser sessions of the account end")
def reset_password(token: Token, payload: NewPasswordIn, request: Request, db: DbSession) -> None:
    """Browser sessions and sign-ins waiting for a code end; paired devices, API keys and passkeys stay, and the account
    page lists them at the next sign-in with "Disconnect all" (``GET /api/v1/auth/access``)."""
    check_password(payload.password)
    check_confirm(payload.password, payload.password_confirm)
    address_guard(request)
    try:
        done = konten_resets.use_reset(KontenStore(db), token, payload.password, password_login=_password_login(db))
    except nexkonten.AccountError as exc:
        if exc.code == "password_too_short":
            raise fail(exc) from exc
        address_failed(request)
        raise error("reset_invalid", "This link is not valid any more.", 404, reason=exc.code) from exc
    from ..services import totp

    totp.forget_account(int(done.account.id))
    logger.warning("Password set through a link name=%s origin=%s", done.account.username, done.origin)


# --- The operator makes a link ---------------------------------------------------------------------------------------


@router.post("/accounts/{account_id}/reset-link", summary="Make an account a link to set a new password (operator)")
def send_link(
    account_id: Annotated[int, Path(ge=1)], payload: ResetLinkIn, request: Request, operator: OperatorAccount,
    db: DbSession,
) -> dict[str, Any]:
    """With the operator's own password. By mail to the account's address that counts where a mail server is there
    (and ``send`` is not False); otherwise the link comes back once, for the operator to pass on (built from the
    public address, else from the address the operator opened nexpaper under). Also for a blocked account: it stays
    blocked. For an account through a provider only it is its first password, while signing in with one is on."""
    row = db.get(AccountRow, account_id)
    if row is None:
        raise error("not_found", "No such account.", 404)
    actor = db.get(AccountRow, operator.id)
    assert actor is not None
    store = KontenStore(db)
    can_mail = post_store.configured(db) and payload.send
    try:
        fresh = confirmed_without_password(request, actor)
        made = konten_resets.reset_link(
            store, account_id, actor_id=operator.id, password=payload.current_password, actor_confirmed=fresh,
            mail=can_mail, password_login=_password_login(db), days=payload.days,
        )
    except nexkonten.AccountError as exc:
        raise fail(exc) from exc
    base = settings_service.public_url(db) or str(request.base_url).rstrip("/")
    if made.mail is not None:
        try:
            kontenpost.send_now(db, made.mail, keep=False, base=base)
        except nexpost.MailError as exc:
            # Mail was the way: kept, the link would stand without anybody holding it.
            konten_resets.reset_mail_failed(KontenStore(db), account_id)
            raise error(post_store.app_code(exc), str(exc), 502) from exc
        return {"sent": True, "email": made.mail.to, "expires_at": made.expires_at.isoformat()}
    return {"sent": False, "link": f"{base}/reset/{made.token}", "expires_at": made.expires_at.isoformat()}
