"""The own mail address, through the shared account module (``profiles``): changing it asks for the password once
more (an account without one: a fresh sign-in at its provider), because the address is the way back into the account.

With a mail server and the public address the new address waits for the link mailed to it, and counts and is proven
once it is opened; without, it counts at once but is not proven (the intake trusts only a proven address). The same
address again, while it is not proven, sends a link to it (``routers/auth.prove_address``). The old address hears of a
change where it counted. A link that does not hold counts as a failure of the sender, as the links for a new password
do.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, Field

from ..deps import BrowserAccount, DbSession, address_failed, address_guard, confirmed_without_password
from ..errors import error
from ..models import Account as AccountRow
from ..services import kontenpost, mailer
from ..services.konten_store import KontenStore
from ..vendor import nexkonten
from ..vendor.nexkonten import profiles
from .auth import account_view, change_address, fail

logger = logging.getLogger("nexpaper.auth")

router = APIRouter(prefix="/api/v1", tags=["mail address"])

Token = Annotated[str, Path(min_length=20, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class EmailIn(BaseModel):
    #: The new address; empty takes the address away.
    email: str = Field(max_length=255)
    #: The own password once more (an account from a provider has none and shows itself by a recent sign-in).
    password: str = Field(default="", max_length=200)


@router.put("/me/email", summary="Give a new mail address; with a mail server it counts once its link is opened")
def set_email(payload: EmailIn, request: Request, account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    row = db.get(AccountRow, account.id)
    assert row is not None
    # A malformed address answers ``invalid_email`` as in 1.12.0 (the module's ``email_invalid``, ``OLD_CODES``).
    address = payload.email.strip()
    try:
        fresh = confirmed_without_password(request, row)
        change_address(db, row, address, password=payload.password, fresh=fresh)
    except nexkonten.AccountError as exc:
        db.rollback()
        raise fail(exc) from exc
    db.refresh(row)
    return account_view(row)


@router.post("/me/email/resend", summary="Send the link for the address that waits once more")
def resend(account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    try:
        mail = profiles.resend_email_link(KontenStore(db), account.id)
    except nexkonten.AccountError as exc:
        raise fail(exc) from exc
    try:
        kontenpost.send_now(db, mail, keep=False)
    except mailer.MailError as exc:
        raise error(exc.code, "The mail server did not take the mail.", 502) from exc
    row = db.get(AccountRow, account.id)
    assert row is not None
    return account_view(row)


@router.delete("/me/email/pending", status_code=204, summary="Withdraw the address that waits for its link")
def withdraw(account: BrowserAccount, db: DbSession) -> None:
    profiles.withdraw_email_change(KontenStore(db), account.id)


def _refused(request: Request, exc: nexkonten.AccountError) -> Exception:
    address_failed(request)
    if exc.code == "email_taken":
        return fail(exc)
    return error("email_link_invalid", "This link is not valid any more.", 404, reason=exc.code)


@router.get("/email/confirm/{token}", summary="Whether a link that confirms a mail address holds (no sign-in needed)")
def confirm_state(token: Token, request: Request, db: DbSession) -> dict[str, str]:
    address_guard(request)
    store = KontenStore(db)
    try:
        change = profiles.email_change_state(store, token)
    except nexkonten.AccountError as exc:
        raise _refused(request, exc) from exc
    account = store.get_account(change.account_id)
    return {"name": account.username if account else "", "address": change.address}


@router.post("/email/confirm/{token}", summary="Confirm the mail address the link was sent to (no sign-in needed)")
def confirm(token: Token, request: Request, db: DbSession) -> dict[str, Any]:
    """The address counts and is proven from now on. The old address hears of the change where it counted (the
    shared module's rule, decided for every app)."""
    address_guard(request)
    try:
        done = profiles.confirm_email(KontenStore(db), token)
    except nexkonten.AccountError as exc:
        raise _refused(request, exc) from exc
    told = kontenpost.queue(db, done.notice)
    logger.info("Mail address confirmed name=%s", done.account.username)
    return {"name": done.account.username, "address": done.account.email, "old_told": told}
