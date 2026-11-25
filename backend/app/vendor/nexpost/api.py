"""Since 1.1.0: the routes of the page Server › Mail, for operators only:

``GET  <prefix>``        the mail server as the page shows it (``settings.view``: never the password, whether one is
                         stored, the warning, the last mail sent, the last error, the mails waiting)
``PUT  <prefix>``        save it (``password`` left out or null keeps the stored one, "" removes it); the new view
``POST <prefix>/test``   the test mail at once (``{"to": …, "language": …}``), 204 or the reason

The app mounts them with ``app.include_router(nexpost.api.router(operator=<its dependency>, store=<its dependency>))``.
``operator`` is the app's own check (401 without a session, 403 for a member); ``store`` gives the app's ``Store``
over the request's session. ``prefix`` default ``/api/server/mail``; the app's older routes stay as they are (they may
call the same functions). Refusals: ``{"code", "message"}`` with the module's codes (``AppConfig.error_codes`` maps
them to the app's older ones), 409 without a mail server, 422 for what was typed, 502 for the mail server's no.

The only part of the module that needs FastAPI (and pydantic, which comes with it); the rest is the standard library,
and ``nexpost/__init__.py`` does not load it."""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from . import outbox, settings
from .errors import MailError
from .model import SECURITY


class MailView(BaseModel):
    host: str
    port: int
    security: str
    user: str
    password_set: bool
    sender: str
    sender_name: str
    #: The name an empty sender name stands for (the app's), the placeholder of the field.
    sender_name_default: str
    ca_file: str = ""
    configured: bool
    warnings: list[str] = Field(default_factory=list)
    last_ok_at: str | None = None
    last_error: str = ""
    last_error_at: str | None = None
    #: Mails waiting in the outbox; None where the store cannot tell.
    waiting: int | None = None


class MailChange(BaseModel):
    host: str = Field(default="", max_length=253)
    port: int = 587
    security: str = Field(default="starttls", max_length=16)
    user: str = Field(default="", max_length=254)
    #: None (or left out) keeps the stored password, "" removes it.
    password: str | None = Field(default=None, max_length=512)
    sender: str = Field(default="", max_length=254)
    sender_name: str = Field(default="", max_length=120)


class TestMail(BaseModel):
    to: str = Field(max_length=254)
    #: The page's language (``de``, ``en``, ``fr``); the test mail is written in it.
    language: str = Field(default="", max_length=16)


def _refuse(code: str, message: str, status: int) -> Exception:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def router(
    *,
    operator: Callable[..., Any],
    store: Callable[..., Any],
    prefix: str = "/api/server/mail",
    error: Callable[[str, str, int], Exception] | None = None,
    tags: list[str] | None = None,
) -> APIRouter:
    """The routes. ``operator``: the app's dependency for operators. ``store``: a dependency giving the app's
    ``Store`` over the request's session. ``error(code, message, status)``: the app's own form of a refusal (default
    ``HTTPException`` with ``{"code", "message"}`` as ``detail``)."""
    refuse = error or _refuse
    routes = APIRouter(prefix=prefix, tags=tags or ["mail"], dependencies=[Depends(operator)])

    def refused(problem: MailError) -> Exception:
        return refuse(problem.public_code, problem.message, problem.status)

    @routes.get("", response_model=MailView, summary="The mail server")
    def read_mail(own: Annotated[Any, Depends(store)]) -> dict[str, object]:
        return settings.view(own)

    @routes.put("", response_model=MailView, summary="Save the mail server")
    def save_mail(change: MailChange, own: Annotated[Any, Depends(store)]) -> dict[str, object]:
        if change.security.strip().lower() not in (*SECURITY, *settings.OLDER_SECURITY):
            raise refuse("mail_settings_invalid", "Encryption must be starttls, tls or none.", 422)
        current = own.mail_settings()
        kept = bool(current.password) if change.password is None else bool(change.password)
        try:
            checked = settings.check(
                host=change.host,
                port=change.port,
                security=change.security,
                user=change.user,
                sender=change.sender,
                sender_name=change.sender_name,
                ca_file=current.ca_file,
                password_given=kept,
            )
        except MailError as problem:
            raise refused(problem) from problem
        settings.save(own, checked, change.password)
        return settings.view(own)

    @routes.post("/test", status_code=204, summary="Send the test mail now")
    def send_test(body: TestMail, own: Annotated[Any, Depends(store)]) -> Response:
        try:
            outbox.test_mail(own, body.to, language=body.language)
        except MailError as problem:
            raise refused(problem) from problem
        return Response(status_code=204)

    return routes
