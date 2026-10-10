"""The operator's settings: address, sign-in, API keys, invitation mail, backups; "Ready for the internet?".

Secrets (the mail password) are written encrypted and never read back: the answer only says whether one is set.
The OIDC settings live in ``routers/oidc.py``.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, StrictInt

from ..deps import (
    DbSession,
    OperatorAccount,
    behind_unknown_proxy,
    confirm_operator,
)
from ..errors import error
from ..security import encrypt_secret
from ..services import accounts, limits, mailer, processing, readiness, settings_service, totp

logger = logging.getLogger("nexpaper.settings")

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class SettingsOut(BaseModel):
    public_url: str
    password_login: bool
    two_factor_required: bool
    oidc_second_factor_by_provider: bool
    backup_schedule: str
    backup_keep: int
    smtp_host: str
    smtp_port: int
    smtp_security: str
    smtp_user: str
    smtp_password_set: bool
    smtp_from: str
    api_keys_allowed: bool
    update_check: bool
    links_allowed: bool
    link_max_days: int
    #: Storage (what comes in): the biggest file in MB, the most pages of a document, the most pixels of a picture in
    #: millions, how many uploads in pieces and how many MB an account may have open at once, the time one document may
    #: take in the worker (seconds) and the memory it may use (MB; 0: no limit).
    upload_max_mb: int
    upload_max_pages: int
    upload_max_megapixels: int
    upload_open_count: int
    upload_open_mb: int
    process_timeout_seconds: int
    process_memory_mb: int
    cache_max_mb: int
    #: Pages of a long document drawn in the background after it was read (0: only the short ones, while reading).
    prerender_max_pages: int


class SettingsIn(BaseModel):
    public_url: str | None = Field(default=None, max_length=255)
    password_login: bool | None = None
    two_factor_required: bool | None = None
    oidc_second_factor_by_provider: bool | None = None
    #: The operator's password once more: asked when a change makes signing in weaker.
    current_password: str = Field(default="", max_length=200)
    backup_schedule: Literal["off", "daily", "weekly"] | None = None
    backup_keep: int | None = Field(default=None, ge=1, le=365)
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    # The same order as the mailbox's in routers/intake.py: Python treats two Literals of the same values as equal and
    # keeps the first one it built, so a different order here would change the description with the import order.
    smtp_security: Literal["tls", "starttls", "none"] | None = None
    smtp_user: str | None = Field(default=None, max_length=255)
    #: Empty removes the password; left out keeps it.
    smtp_password: str | None = Field(default=None, max_length=500)
    smtp_from: str | None = Field(default=None, max_length=255)
    api_keys_allowed: bool | None = None
    update_check: bool | None = None
    #: Links to documents for people without an account. Off ends every link at once.
    links_allowed: bool | None = None
    link_max_days: Literal[7, 14, 30, 90] | None = None
    upload_max_mb: StrictInt | None = Field(default=None, ge=1, le=10240)
    upload_max_pages: StrictInt | None = Field(default=None, ge=1, le=20000)
    upload_max_megapixels: StrictInt | None = Field(default=None, ge=1, le=1000)
    upload_open_count: StrictInt | None = Field(default=None, ge=1, le=100)
    upload_open_mb: StrictInt | None = Field(default=None, ge=1, le=1048576)
    process_timeout_seconds: StrictInt | None = Field(default=None, ge=5, le=86400)
    process_memory_mb: StrictInt | None = Field(default=None, ge=0, le=65536,
                                                description="0: no limit; else at least 256")
    cache_max_mb: StrictInt | None = Field(default=None, ge=64, le=1048576)
    prerender_max_pages: StrictInt | None = Field(default=None, ge=0, le=20000)


class TestMailIn(BaseModel):
    to: str = Field(max_length=255)


def _view(db: DbSession) -> SettingsOut:
    values = settings_service.get_all(db)
    return SettingsOut(
        public_url=values["public_url"],
        password_login=values["password_login"],
        two_factor_required=bool(values["two_factor_required"]),
        oidc_second_factor_by_provider=bool(values["oidc_second_factor_by_provider"]),
        backup_schedule=values["backup_schedule"],
        backup_keep=values["backup_keep"],
        smtp_host=values["smtp_host"],
        smtp_port=values["smtp_port"],
        smtp_security=values["smtp_security"],
        smtp_user=values["smtp_user"],
        smtp_password_set=bool(values["smtp_password_enc"]),
        smtp_from=values["smtp_from"],
        api_keys_allowed=bool(values["api_keys_allowed"]),
        update_check=bool(values["update_check"]),
        links_allowed=bool(values["links_allowed"]),
        link_max_days=int(values["link_max_days"]),
        **{key: int(values[key]) for key in limits.RANGES},
    )


@router.get("", response_model=SettingsOut)
def read(_operator: OperatorAccount, db: DbSession) -> SettingsOut:
    return _view(db)


#: Changes that make signing in weaker: each asks for the operator's password once more.
WEAKER = {"two_factor_required": False, "oidc_second_factor_by_provider": True}


@router.put("", response_model=SettingsOut)
def save(payload: SettingsIn, request: Request, operator: OperatorAccount, db: DbSession) -> SettingsOut:
    sent = payload.model_dump(exclude_unset=True)
    current = settings_service.get_all(db)
    if any(key in sent and sent[key] is weaker and bool(current[key]) is not weaker for key, weaker in WEAKER.items()):
        # A stolen session must not be enough to take the second factor away from everybody.
        confirm_operator(request, db, operator, payload.current_password)
    changes: dict[str, Any] = {}
    for key, value in sent.items():
        if value is None or key == "current_password":
            continue
        if key == "public_url":
            try:
                value = settings_service.normalize_public_url(value)
            except ValueError as exc:
                raise error("invalid_url", "Give an address like https://paper.example.com.", 422) from exc
        elif key == "smtp_from":
            value = value.strip()
            if value and not accounts.EMAIL_PATTERN.match(value):
                raise error("invalid_email", "This is not a mail address.", 422)
        elif key == "two_factor_required" and value and not current["two_factor_required"] and (
            not totp.has_second_factor(db, operator) and not totp.provider_checks(db, operator)
        ):
            # Else the operator would be the first one sent to set it up, with nothing else in reach.
            raise error("own_second_factor_first", "Set up your own second factor first.", 409)
        elif key == "password_login" and not value:
            current = settings_service.get_all(db)
            if not (current["oidc_issuer"] and current["oidc_client_id"]):
                # Without a provider nobody but the operator could sign in any more, and invitations would fail.
                raise error("provider_first", "Set up a sign-in provider first.", 409)
        elif key == "process_memory_mb" and 0 < value < limits.MEMORY_FLOOR:
            raise error("invalid_input", f"Use 0 (no limit) or at least {limits.MEMORY_FLOOR}.", 422, fields=[key])
        elif key == "smtp_password":
            changes["smtp_password_enc"] = encrypt_secret(value)
            continue
        elif isinstance(value, str):
            value = value.strip()
        changes[key] = value
    settings_service.save(db, changes)
    logger.info("Settings changed keys=%s by=%s", ",".join(sorted(changes)), operator.name)
    return _view(db)


class QueueOut(BaseModel):
    #: Documents being read now, and waiting to be read.
    running: int
    waiting: int


@router.get("/queue", response_model=QueueOut, summary="How many documents are being read, and how many wait")
def queue(_operator: OperatorAccount, db: DbSession) -> QueueOut:
    running, waiting = processing.waiting(db)
    return QueueOut(running=running, waiting=waiting)


@router.post("/mail-test", status_code=204, summary="Send a test mail through the configured server")
def mail_test(payload: TestMailIn, _operator: OperatorAccount, db: DbSession) -> None:
    to = payload.to.strip()
    if not accounts.EMAIL_PATTERN.match(to):
        raise error("invalid_email", "This is not a mail address.", 422)
    try:
        mailer.send_test(db, to)
    except mailer.MailError as exc:
        raise error(exc.code, str(exc), 502) from exc


@router.get("/readiness", summary="Ready for the internet? What nexpaper checks about itself")
def ready(request: Request, operator: OperatorAccount, db: DbSession) -> dict[str, Any]:
    return readiness.check(db, request, operator, behind_unknown_proxy(request))
