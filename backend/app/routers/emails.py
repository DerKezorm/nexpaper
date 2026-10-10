"""The own mail address: changed by a link sent to the new address (``services/emails.py``).

Changing it asks for the password once more, counted like a sign-in, because the address is the way back into the
account. A link that does not hold counts as a failure of the sender, as the links for a new password do.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, Field

from ..deps import BrowserAccount, DbSession, address_failed, address_guard, confirm_self, too_many
from ..errors import error
from ..models import Account as AccountRow
from ..security import brake
from ..services import accounts, emails, mailer
from .auth import account_view

logger = logging.getLogger("nexpaper.auth")

router = APIRouter(prefix="/api/v1", tags=["mail address"])

Token = Annotated[str, Path(min_length=20, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class EmailIn(BaseModel):
    #: The new address; empty takes the address away.
    email: str = Field(max_length=255)
    #: The own password once more (an account from a provider has none and shows itself by a recent sign-in).
    password: str = Field(default="", max_length=200)


@router.put("/me/email", summary="Give a new mail address; it counts once the link mailed to it is opened")
def set_email(payload: EmailIn, request: Request, account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    row = db.get(AccountRow, account.id)
    assert row is not None
    address = payload.email.strip()
    if address and not accounts.EMAIL_PATTERN.match(address):
        raise error("invalid_email", "This is not a mail address.", 422)
    confirm_self(request, db, row, payload.password)
    if not address:
        # Taking the address away needs no link; whatever waited for one goes too.
        emails.withdraw(db, row.id)
        old = row.email.strip()
        was_confirmed = bool(old) and row.email_confirmed_at is not None
        row.email = ""
        row.email_confirmed_at = None
        row.email_from_provider = False
        db.commit()
        logger.info("Mail address removed name=%s", row.name)
        if was_confirmed:
            emails.notify_old(db, old, row.name, "")
        return account_view(row)
    if address.lower() == row.email.strip().lower() and row.email_confirmed_at is not None:
        raise error("email_same", "This is the address already confirmed.", 409)
    if not emails.available(db):
        raise error("mail_off", "No mail server is set up, so the link cannot be sent.", 409)
    key = f"email-link:{row.id}"
    wait = brake.wait_seconds(key, emails.PER_ACCOUNT)
    if wait:
        raise too_many(wait)
    brake.failed(key, emails.PER_ACCOUNT)
    made, token = emails.start(db, row, address)
    try:
        mailer.send_confirm(db, address, emails.link_to(db, token), name=row.name, hours=emails.HOURS)
    except mailer.MailError as exc:
        # Mail was the way: kept, the link would stand without anybody holding it.
        db.delete(made)
        db.commit()
        raise error(exc.code, str(exc), 502) from exc
    return account_view(row)


@router.delete("/me/email/pending", status_code=204, summary="Withdraw the address that waits for its link")
def withdraw(account: BrowserAccount, db: DbSession) -> None:
    emails.withdraw(db, account.id)


def _valid(db: DbSession, request: Request, token: str) -> tuple[Any, AccountRow]:
    address_guard(request)
    found = emails.find(db, token)
    if found is None:
        address_failed(request)
        raise error("email_link_invalid", "This link is not valid any more.", 404)
    return found


@router.get("/email/confirm/{token}", summary="Whether a link that confirms a mail address holds (no sign-in needed)")
def confirm_state(token: Token, request: Request, db: DbSession) -> dict[str, str]:
    row, account = _valid(db, request, token)
    return {"name": account.name, "address": row.address}


@router.post("/email/confirm/{token}", summary="Confirm the mail address the link was sent to (no sign-in needed)")
def confirm(token: Token, request: Request, db: DbSession) -> dict[str, Any]:
    _valid(db, request, token)
    done = emails.confirm(db, token)
    if done is None:
        address_failed(request)
        raise error("email_link_invalid", "This link is not valid any more.", 404)
    account, told = done
    return {"name": account.name, "address": account.email, "old_told": told}
