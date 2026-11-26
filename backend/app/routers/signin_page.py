"""The page Server › Sign-in of the shared account module (konten 1.1.0): its switches with the module's rules
(``signin.view``, ``signin.change``) and "Ready for the internet?" in the module's form (``readiness.check``) with
nexpaper's own points (the server's secrets, the backup, upload requests).

The old routes stay as they were: ``GET/PUT /api/v1/settings`` (the same switches, the public address with its
question about the providers' redirect address) and ``GET /api/v1/settings/readiness`` (nexpaper's nine points).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy import select

from ..config import get_settings
from ..deps import DbSession, OperatorAccount, confirmed_without_password, has_password
from ..models import Account as AccountRow
from ..models import OidcProvider
from ..services import readiness as own_readiness
from ..services import settings_service
from ..services.konten_store import KontenStore
from ..vendor import nexkonten
from ..vendor.nexkonten import readiness, signin
from .auth import fail

logger = logging.getLogger("nexpaper.settings")

router = APIRouter(prefix="/api/v1/server", tags=["settings"])


def _view(db: DbSession, operator: AccountRow) -> dict[str, Any]:
    store = KontenStore(db)
    row = db.get(AccountRow, operator.id)
    return {
        **signin.view(store, operator.id, provider_checked=bool(operator.second_factor_by_provider)),
        # The card's field "Public address" (saved through ``PUT /api/v1/settings`` with ``public_url``).
        "public_url": str(settings_service.get(db, "public_url") or ""),
        "public_url_effective": settings_service.public_url(db),
        # Turning "Require a second factor" off asks for this password; without one, a fresh sign-in at the provider.
        "operator_has_password": has_password(row if row is not None else operator),
    }


@router.get("/sign-in", summary="The operator's sign-in switches, with what may change now")
def read_sign_in(operator: OperatorAccount, db: DbSession) -> dict[str, Any]:
    return _view(db, operator)


class SignInIn(BaseModel):
    password_login: StrictBool | None = None
    factor_required: StrictBool | None = None
    passkeys_allowed: StrictBool | None = None
    #: The operator's own password, asked when "Require a second factor" goes off.
    password: str = Field(default="", max_length=200)


@router.put("/sign-in", summary="Change the operator's sign-in switches")
def change_sign_in(payload: SignInIn, request: Request, operator: OperatorAccount, db: DbSession) -> dict[str, Any]:
    """The module's rules: the password sign-in goes off only with an active provider (``provider_first``), the second
    factor for everybody goes on only with one of the operator's own (``own_second_factor_first``) and off only with
    the operator's password (``wrong_password``; without one a fresh sign-in at the provider)."""
    store = KontenStore(db)
    weaker = payload.factor_required is False and store.sign_in_settings().factor_required
    row = db.get(AccountRow, operator.id)
    confirmed = confirmed_without_password(request, row if row is not None else operator) if weaker else False
    try:
        signin.change(store, operator.id, password_login=payload.password_login,
                      factor_required=payload.factor_required, passkeys_allowed=payload.passkeys_allowed,
                      password=payload.password, actor_confirmed=confirmed,
                      provider_checked=bool(operator.second_factor_by_provider))
    except nexkonten.AccountError as exc:
        db.rollback()
        raise fail(exc) from exc
    return _view(db, operator)


def _points(db: DbSession) -> list[readiness.Point]:
    """nexpaper's own points, with the words its pages had (``ready.secrets``, ``ready.backups``,
    ``uploadRequest.ready``): the server's secrets after the brake, the backup and the upload requests at the end."""
    found = own_readiness.own_points(db)
    secrets, backups, uploads = found["secrets"], found["backups"], found["upload_requests"]
    if secrets.state == own_readiness.BAD:
        sentence = "ready.secrets.missing" if secrets.values.get("missing") else "ready.secrets.bad"
    else:
        sentence = "ready.secrets.env" if secrets.values.get("source") else "ready.secrets.ok"
    return [
        readiness.Point("secrets", secrets.state, "ready.secrets.title", sentence, secrets.values, after="brake"),
        readiness.Point("backups", backups.state, "ready.backups.title", f"ready.backups.{backups.state}",
                        backups.values),
        readiness.Point("upload_requests", uploads.state, "uploadRequest.ready.title",
                        f"uploadRequest.ready.{uploads.state}", uploads.values),
    ]


@router.get("/readiness", summary="Ready for the internet? In the form of the shared account module")
def ready(request: Request, operator: OperatorAccount, db: DbSession) -> dict[str, Any]:
    settings = get_settings()
    checking = list(db.scalars(select(OidcProvider.label).where(
        OidcProvider.enabled.is_(True), OidcProvider.trusts_second_factor.is_(True)).order_by(OidcProvider.position)))
    found = readiness.check(
        public_url=settings_service.public_url(db),
        request_https=own_readiness.came_over_https(request),
        factor_required=bool(settings_service.get(db, "two_factor_required")),
        own_factor=signin.has_own_factor(KontenStore(db), operator.id),
        trusted_proxies=[entry.strip() for entry in settings.trusted_proxies.split(",") if entry.strip()],
        peer=request.client.host if request.client else "",
        forwarded=bool(request.headers.get("x-forwarded-for")),
        cookie_secure=settings.cookie_secure,
        providers_checking=checking,
        session_days=settings.session_days,
        extra=_points(db),
    )
    return found.as_dict()
