"""Sign-in through OpenID Connect providers, their list, linking, and the authentik button.

The protocol, who an identity is, the provider list and the button live in the shared module ``vendor/nexoidc``
(the blueprint "Anmeldung mit OIDC und authentik", the same in every nex app); this router puts nexpaper around it:
sessions and their stages, the sign-in brake, the password asked again before linking, the second factor, the page a
sign-in started from (``services/landing.py``), and the error answers.

The return leg is a browser redirect, not an API answer: the provider sends the browser back with GET, and a human
sees whatever comes out. So every outcome of a callback ends in a redirect: to ``/`` (or the page the sign-in started
from) with the session cookie, to the sign-in page with ``?error=<code>``, to ``/login?step=code`` when the code of
nexpaper's own second factor is still due, or to the account page after linking.

What only a browser the person sits at may do (linking, unlinking, every operator route) is refused to a device
token (``BrowserAccount``, ``OperatorAccount``).

Paths (all below ``/api/v1/oidc``):

| Method | Path | Who |
|---|---|---|
| GET | ``/providers`` | anybody: slug and label of the active entries (sign-in and invitation page) |
| GET, POST | ``/admin/providers`` | operator: the list (never a secret), add one |
| PUT | ``/admin/providers/order`` | operator: ``{"ids": [...]}`` |
| PUT, DELETE | ``/admin/providers/{id}`` | operator: save (``dropped`` links), remove (``count``, ``only``) |
| GET | ``/admin/providers/{id}/impact?issuer=`` | operator: the numbers for the two confirmations |
| GET | ``/admin/links`` | operator: which account is linked to which provider (the account list) |
| GET | ``/{slug}/start[?invite=<token>][&next=<page>]`` | anybody: off to the provider |
| GET | ``/{slug}/callback``, ``/callback`` | anybody: the return (the second belongs to the entry ``oidc``) |
| GET | ``/me`` | signed in: every active entry with ``linked`` and the address the provider knows |
| POST, DELETE | ``/{slug}/link`` | signed in: link (``{"password"}`` → ``{"url"}``), unlink |
| POST | ``/me/address`` | signed in: take the address of the provider named in ``{"slug"}`` as the own one |
| DELETE | ``/admin/accounts/{account}/links/{provider}`` | operator, with the own password |
| POST | ``/authentik/setup`` | operator: ``{"url", "token", "confirm_issuer_change", "public_url"}`` → 200, the steps |
| GET, POST | ``/authentik/address`` | operator: what the card shows about the public address; "Use it only" |
| GET | ``/authentik/blueprint`` | operator: ``nexpaper-authentik.yaml`` (409 without a public address) |
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import SessionLocal
from ..deps import (
    BrowserAccount,
    OperatorAccount,
    client_ip,
    confirm_operator,
    reauth_failed,
    reauth_guard,
    reauth_succeeded,
)
from ..errors import error
from ..models import SIGN_IN_PASSWORD, STAGE_FULL, STAGE_SETUP, OidcLink
from ..models import Account as AccountRow
from ..security import SESSION_COOKIE, brake, current_session
from ..services import accounts, landing, logs, tell
from ..services.oidc_store import SqlStore, take_address
from ..vendor.nexoidc import OidcError, ProviderInvalid, attempt, authentik, flow, providers
from ..vendor.nexoidc import accounts as oidc_accounts
from ..vendor.nexoidc.config import current
from . import auth as auth_router
from .auth import OperatorConfirmIn, secure_cookie

router = APIRouter(prefix="/api/v1/oidc", tags=["oidc"])
logger = logging.getLogger("nexpaper.oidc")

#: Where the sign-in page asks for the code of nexpaper's own second factor after a provider that is not trusted.
CODE_STEP = "/login?step=code"
#: Codes that cost nothing to produce (a forged return, a braked sender, an unknown provider): they do not count
#: against the sender. Nor does any return without an attempt cookie of this server (``?error=`` from anybody).
FREE_REFUSALS = ("oidc_state_mismatch", "too_many_attempts", "oidc_not_configured")


class ProviderIn(BaseModel):
    label: str = Field(max_length=200)
    slug: str = Field(default="", max_length=100)
    issuer: str = Field(max_length=600)
    client_id: str = Field(max_length=300)
    client_secret: str = Field(default="", max_length=2000)
    scopes: str = Field(default="openid profile email", max_length=500)
    enabled: bool = True
    auto_create: bool = False
    trusts_second_factor: bool = True


class PasswordIn(BaseModel):
    password: str = Field(max_length=200)


class SetupIn(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    token: str = Field(min_length=1, max_length=2000)
    #: The answer to the button's question "another issuer, {count} accounts link again": the run stops at ``reached``
    #: with the reason ``issuer_change`` until it comes with ``true``.
    confirm_issuer_change: bool = False
    #: The address the card proposes (the browser's own) and the operator confirmed; used only while nexpaper has no
    #: public address of its own. The module cleans it and refuses an address that is none.
    public_url: str = Field(default="", max_length=600)


class AddressIn(BaseModel):
    public_url: str = Field(max_length=600)
    #: The answer to the question "the redirect address at authentik changes" (409 ``public_url_change``).
    confirm: bool = False


class TakeAddressIn(BaseModel):
    slug: str = Field(min_length=1, max_length=40)


class OrderIn(BaseModel):
    ids: list[int] = Field(max_length=200)


@contextmanager
def store() -> Iterator[SqlStore]:
    with SessionLocal() as db:
        yield SqlStore(db)


def _base(request: Request) -> str:
    # The scheme of a trusted proxy is the request's already (``ForwardedProtoMiddleware``); nothing else is read.
    return str(request.base_url)


def _redirect(target: flow.Redirect, request: Request) -> RedirectResponse:
    # 303: the browser loads the target with GET whatever way it came.
    response = RedirectResponse(target.location, status_code=303)
    cookie = target.cookie
    secure = cookie.secure or secure_cookie(request)
    if cookie.max_age == 0:
        response.delete_cookie(cookie.name, path=cookie.path, secure=secure, httponly=True, samesite="lax")
    else:
        response.set_cookie(cookie.name, cookie.value, max_age=cookie.max_age, path=cookie.path,
                            httponly=cookie.http_only, samesite="lax", secure=secure)
    return response


def _landing_cookie(response: Response, request: Request, page: str | None) -> None:
    """The page the sign-in started from goes along beside the attempt cookie; without one an old one goes."""
    value = landing.pack(page)
    if value is None:
        response.delete_cookie(landing.COOKIE, path=current().cookie_path, httponly=True, samesite="lax")
        return
    response.set_cookie(landing.COOKIE, value, max_age=landing.MINUTES * 60, path=current().cookie_path,
                        httponly=True, samesite="lax", secure=secure_cookie(request))


def _refused(exc: OidcError, cookie: str | None, request: Request, page: str | None) -> RedirectResponse:
    """The module's way back after a failure; the sign-in page keeps the page asked for, so a second try still lands
    there."""
    target = flow.refused(exc, cookie)
    location = target.location
    if page and location.startswith(current().login_page + "?"):
        location += f"&next={quote(page, safe='')}"
    response = _redirect(flow.Redirect(location, target.cookie), request)
    _landing_cookie(response, request, None)
    return response


def _form_error(exc: ProviderInvalid) -> Exception:
    return error(exc.code, exc.message, 422, field=exc.field)


# --- The provider list -------------------------------------------------------------------------------------------


@router.get("/providers", summary="The active sign-in providers: slug and label (no sign-in needed)")
def public_providers() -> list[dict[str, str]]:
    # Public: the sign-in and invitation pages ask before anybody is signed in. Nothing but the buttons leaves.
    with store() as s:
        return providers.public_list(s)


@router.get("/admin/providers", summary="The provider list for the operator (never a secret)")
def admin_providers(_operator: OperatorAccount, request: Request) -> list[dict[str, Any]]:
    with store() as s:
        return [providers.admin_view(entry, _base(request), len(s.links_of_provider(entry.id)))
                for entry in s.list_providers()]


@router.post("/admin/providers", status_code=201, summary="Add a provider; the issuer is checked by discovery")
async def add_provider(payload: ProviderIn, operator: OperatorAccount, request: Request) -> dict[str, Any]:
    with store() as s:
        try:
            created = await providers.create(s, providers.Form(**payload.model_dump()))
        except ProviderInvalid as exc:
            raise _form_error(exc) from exc
        logger.info("OIDC provider %s added by=%s", created.slug, operator.name)
        return providers.admin_view(created, _base(request), 0)


@router.put("/admin/providers/order", summary="Put the providers in this order (the drag handle)")
def order_providers(payload: OrderIn, _operator: OperatorAccount) -> list[dict[str, str]]:
    with store() as s:
        try:
            providers.reorder(s, payload.ids)
        except ProviderInvalid as exc:
            raise _form_error(exc) from exc
        return providers.public_list(s)


@router.get("/admin/links", summary="Which account is linked to which provider (the marks in the account list)")
def admin_links(_operator: OperatorAccount) -> list[dict[str, Any]]:
    with store() as s:
        labels = {entry.id: (entry.slug, entry.label) for entry in s.list_providers()}
        rows = s.db.scalars(select(OidcLink).order_by(OidcLink.account_id, OidcLink.provider_id))
        return [{"account_id": row.account_id, "provider_id": row.provider_id, "slug": labels[row.provider_id][0],
                 "label": labels[row.provider_id][1]} for row in rows if row.provider_id in labels]


@router.put("/admin/providers/{provider_id}", summary="Save a provider; another issuer drops its links")
async def save_provider(
    provider_id: Annotated[int, Path(ge=1, le=2**31 - 1)], payload: ProviderIn, operator: OperatorAccount,
    request: Request,
) -> dict[str, Any]:
    with store() as s:
        try:
            saved, dropped = await providers.update(s, provider_id, providers.Form(**payload.model_dump()))
        except ProviderInvalid as exc:
            raise _form_error(exc) from exc
        logger.info("OIDC provider %s saved by=%s", saved.slug, operator.name)
        view = providers.admin_view(saved, _base(request), len(s.links_of_provider(saved.id)))
        return {**view, "dropped": dropped}


@router.get("/admin/providers/{provider_id}/impact", summary="Who loses a link when the issuer changes or it goes")
def provider_impact(
    provider_id: Annotated[int, Path(ge=1, le=2**31 - 1)],
    _operator: OperatorAccount,
    issuer: Annotated[str, Query(max_length=600)] = "",
) -> dict[str, Any]:
    with store() as s:
        if s.get_provider(provider_id) is None:
            raise error("provider_unknown", "No such provider.", 404, field="id")
        removal = providers.removal_impact(s, provider_id)
        change = providers.issuer_change_impact(s, provider_id, issuer) if issuer else 0
        return {"issuer_change": change, **asdict(removal)}


@router.delete("/admin/providers/{provider_id}", summary="Remove a provider with its links")
def remove_provider(provider_id: Annotated[int, Path(ge=1, le=2**31 - 1)], operator: OperatorAccount) -> dict[str, Any]:
    with store() as s:
        try:
            impact = providers.remove(s, provider_id)
        except ProviderInvalid as exc:
            raise _form_error(exc) from exc
    logger.info("OIDC provider %s removed by=%s", provider_id, operator.name)
    return asdict(impact)


# Registered before ``/{slug}/...``: the paths of the authentik card would otherwise be taken for a slug, and the entry
# the button makes is called ``authentik`` (its own routes are ``/authentik/start`` and ``/authentik/callback``, which
# these do not cover).
@router.get("/authentik/address", summary="What the authentik card shows about the public address")
def authentik_address(_operator: OperatorAccount, request: Request) -> dict[str, Any]:
    with store() as s:
        return authentik.address_view(s, _base(request), request.headers)


@router.post("/authentik/address", summary="Use the address as nexpaper's public address, without setting up")
def authentik_save_address(payload: AddressIn, operator: OperatorAccount, request: Request) -> dict[str, Any]:
    # "Use it only" in the card.
    with store() as s:
        try:
            saved = authentik.save_public_url(s, payload.public_url, _base(request), confirm=payload.confirm)
        except ValueError as exc:
            raise error("public_url_invalid", "This is not an address nexpaper can be reached at.", 422) from exc
        except authentik.PublicUrlChange as asked:
            raise error("public_url_change", "The redirect address at authentik changes.", 409,
                        **asked.question) from asked
        except authentik.PublicUrlNotKept as exc:
            raise error("public_url_needed", "nexpaper could not keep the address.", 409) from exc
    logger.info("Public address set from the authentik card by=%s", operator.name)
    return saved


@router.post("/authentik/setup", summary="Set up provider and application in authentik with a one-time token")
async def authentik_setup(payload: SetupIn, operator: OperatorAccount, request: Request) -> dict[str, Any]:
    # Always 200 with the steps that ran, a failed one included: the page says why in the operator's language.
    logger.info("authentik setup started by=%s", operator.name)
    with store() as s:
        result = await authentik.setup(s, payload.url, payload.token, _base(request),
                                       confirm_issuer_change=payload.confirm_issuer_change,
                                       public_url=payload.public_url, headers=request.headers)
    return result.as_dict()


@router.get("/authentik/blueprint", summary="Download a blueprint that creates the same objects in authentik")
def authentik_blueprint(_operator: OperatorAccount, request: Request) -> Response:
    with store() as s:
        try:
            redirect = authentik.blueprint_redirect(s, _base(request))
        except authentik.PublicUrlNeeded as exc:
            raise error("public_url_needed", "nexpaper has no public address yet; confirm one in the card.",
                        409) from exc
        text = authentik.blueprint(redirect)
    return Response(content=text, media_type="application/yaml",
                    headers={"Content-Disposition": f'attachment; filename="{authentik.blueprint_filename()}"'})


# --- Start and return --------------------------------------------------------------------------------------------


def _brake_key(request: Request) -> str:
    return "oidc:" + client_ip(request)


@router.get("/{slug}/start", summary="Send the browser to the provider (no sign-in needed)")
async def start(
    slug: Annotated[str, Path(max_length=40)],
    request: Request,
    invite: Annotated[str | None, Query(max_length=64, pattern=r"^[A-Za-z0-9_-]+$")] = None,
    # No length limit here: a too long one is only dropped (``landing.safe_next``), never a refusal of the sign-in.
    next_page: Annotated[str | None, Query(alias="next", description="A page of nexpaper to come back to")] = None,
) -> RedirectResponse:
    # Public: this is the sign-in button. Failures land on the sign-in page with a code. ``next`` is the page the
    # button was pressed for (an app's request to be paired, say); only a path of nexpaper's own goes along.
    page = landing.safe_next(next_page)
    with store() as s:
        try:
            if brake.wait_seconds(_brake_key(request)):
                raise OidcError("too_many_attempts", "sender is braked")
            target = await flow.begin(s, slug, request_base=_base(request), invite=invite)
        except OidcError as exc:
            return _refused(exc, None, request, page)
    response = _redirect(target, request)
    _landing_cookie(response, request, page)
    return response


async def _returned(slug: str, request: Request) -> RedirectResponse:
    """The return from the provider. The order is the module's: the provider's own error, our cookie and state,
    the single use of the state, then the provider; nothing is written before all that passed."""
    cookie = request.cookies.get(current().cookie_name)
    page = landing.read(request.cookies.get(landing.COOKIE))
    key = _brake_key(request)
    with store() as s:
        try:
            if brake.wait_seconds(key):
                raise OidcError("too_many_attempts", "sender is braked")
            arrival = await flow.finish(s, slug, cookie=cookie, params=dict(request.query_params))
            if arrival.started.purpose == "link":
                found = current_session(s.db, request.cookies.get(SESSION_COOKIE))
                # Only a full session links: one that waits for a second factor to be set up is nobody yet.
                signed = found[1].id if found is not None and found[0].stage == STAGE_FULL else None
                oidc_accounts.link(s, arrival, signed)
                brake.succeeded(key)
                return _redirect(flow.arrived(arrival, flow.linked_page(slug)), request)
            signed_in = oidc_accounts.sign_in(s, arrival)
        except OidcError as exc:
            # A return without an attempt cookie of this server (``?error=`` from anybody, garbage) costs nothing to
            # make: it never feeds the brake, or a stranger could lock a household out.
            if exc.code not in FREE_REFUSALS and attempt.read(cookie) is not None:
                brake.failed(key)
            return _refused(exc, cookie, request, page)
        brake.succeeded(key)
        row = s.db.get(AccountRow, signed_in.account_id)
        assert row is not None
        logs.set_actor(row.name)
        after = f"next={quote(page, safe='')}" if page else ""
        if signed_in.second_factor_due:
            # The provider is not trusted with the second factor and the account has one here: the same waiting
            # sign-in as after the password, the code step of the sign-in page finishes it.
            response = _redirect(flow.arrived(arrival, CODE_STEP + ("&" + after if after else "")), request)
            auth_router.park(request, response, s.db, row, True)
            _landing_cookie(response, request, None)
            logger.info("Provider accepted, second factor waiting name=%s", row.name)
            return response
        response = _redirect(flow.arrived(arrival, page), request)
        _landing_cookie(response, request, None)
        stage = auth_router.start(s.db, request, response, row,
                                  by_provider=arrival.provider.trusts_second_factor)
        if stage == STAGE_SETUP:
            # Without a second factor where one is required: the sign-in page sets it up first, then goes on.
            response.headers["location"] = current().login_page + ("?" + after if after else "")
            logger.info("Signed in via OIDC, second factor to be set up first name=%s", row.name)
        return response


@router.get("/callback", summary="The return from the provider of the entry oidc (the address of 1.0.1)")
async def legacy_callback(request: Request) -> RedirectResponse:
    return await _returned("oidc", request)


@router.get("/{slug}/callback", summary="The return from the provider (no sign-in needed)")
async def callback(slug: Annotated[str, Path(max_length=40)], request: Request) -> RedirectResponse:
    return await _returned(slug, request)


# --- My account --------------------------------------------------------------------------------------------------


@router.get("/me", summary="The active providers and whether the own account is linked to each")
def my_providers(account: BrowserAccount) -> list[dict[str, Any]]:
    with store() as s:
        links = {link.provider_id: link for link in s.links_of_account(account.id)}
        row = s.db.get(AccountRow, account.id)
        own = (row.email if row is not None else "").strip().lower()
        out = []
        for entry in s.list_providers():
            if not entry.enabled:
                continue
            link = links.get(entry.id)
            # The address the provider knows, offered when it is not the account's own (Bauplan 01): an account
            # through the provider only follows it anyway.
            offered = link.email if link is not None and link.email and link.email.strip().lower() != own else None
            out.append({"slug": entry.slug, "label": entry.label, "linked": link is not None, "address": offered})
        return out


@router.post("/{slug}/link", summary="Start linking the own account to a provider; needs the password")
async def link_start(
    slug: Annotated[str, Path(max_length=40)], payload: PasswordIn, request: Request, response: Response,
    account: BrowserAccount,
) -> dict[str, str]:
    """Linking hands the account to whoever the browser is at the provider, so it asks for the password: a page
    elsewhere cannot start it (the tab header), and neither can somebody at an unattended browser."""
    with store() as s:
        row = s.db.get(AccountRow, account.id)
        assert row is not None
        # The same brake as before start and return (Bauplan 02, "Ablauf" 4): a braked sender links nothing.
        wait = brake.wait_seconds(_brake_key(request))
        if wait:
            raise error("too_many_attempts", "Too many attempts. Try again later.", 429, retry_after=wait)
        if row.sign_in != SIGN_IN_PASSWORD or not row.password_hash:
            raise error("oidc_only_account", "This account has no password; it signs in through a provider.", 409)
        reauth_guard(request, row)
        if not accounts.check_password(row, payload.password):
            reauth_failed(request, s.db, row)
            raise error("wrong_password", "The password is wrong.", 401)
        reauth_succeeded(request, s.db, row)
        try:
            target = await flow.begin(s, slug, request_base=_base(request), link_account_id=row.id)
        except OidcError as exc:
            raise error(exc.code, exc.message, 409) from exc
    cookie = target.cookie
    response.set_cookie(cookie.name, cookie.value, max_age=cookie.max_age, path=cookie.path, httponly=True,
                        samesite="lax", secure=cookie.secure or secure_cookie(request))
    logger.info("Account starts linking to provider %s name=%s", slug, account.name)
    return {"url": target.location}


@router.delete("/{slug}/link", status_code=204, summary="Unlink the own account from a provider")
def unlink(slug: Annotated[str, Path(max_length=40)], account: BrowserAccount) -> None:
    with store() as s:
        entry = s.provider_by_slug(slug)
        if entry is None:
            raise error("oidc_not_configured", "This provider is not set up.", 404)
        try:
            oidc_accounts.unlink(s, account.id, entry.id)
        except OidcError as exc:
            raise error(exc.code, exc.message, 409) from exc


# Under ``/me`` with the slug in the body: ``/{slug}/address`` would be taken by the operator's ``/authentik/address``
# for the entry the authentik button makes (its slug is ``authentik``).
@router.post("/me/address", summary="Take the address the provider knows as the own one (unconfirmed)")
def take_provider_address(payload: TakeAddressIn, account: BrowserAccount) -> dict[str, Any]:
    """Offered on the account page when the provider knows the account by another address (Bauplan 01). It is the
    account's address from then on, but not confirmed: the mail intake counts it only once the person opened the link
    nexpaper sends (a provider's word is not the person's). It goes again with the last link."""
    with store() as s:
        entry = s.provider_by_slug(payload.slug)
        link = next((item for item in s.links_of_account(account.id) if entry and item.provider_id == entry.id), None)
        row = s.db.get(AccountRow, account.id)
        if entry is None or link is None or not link.email or row is None:
            raise error("not_found", "Not found.", 404)
        if not take_address(s.db, row, link.email):
            raise error("email_taken", "Another account has this address already.", 409)
        s.commit()
        logger.info("Account took the address of provider %s name=%s", entry.slug, row.name)
        return {"email": row.email, "email_confirmed": row.email_confirmed_at is not None}


def _unlinked_notice(provider: str, by: str) -> tell.Notice:
    texts = {
        "de": ("Verknüpfung gelöst", f"{by} hat die Verknüpfung deines Kontos mit {provider} gelöst."),
        "en": ("Link removed", f"{by} removed the link of your account to {provider}."),
    }
    return tell.Notice(
        texts=texts, url="/konto?tab=sicherheit", tag="oidc-unlinked",
        mail_subject="nexpaper: a sign-in link of your account was removed",
        mail_body=(f"{by} removed the link of your nexpaper account to the sign-in provider {provider}.\n\n"
                   "See your account: {where}\n"),
    )


@router.delete("/admin/accounts/{account_id}/links/{provider_id}", status_code=204,
               summary="Operator: unlink an account from a provider (with the own password)")
def operator_unlink(
    account_id: Annotated[int, Path(ge=1, le=2**31 - 1)],
    provider_id: Annotated[int, Path(ge=1, le=2**31 - 1)],
    payload: OperatorConfirmIn,
    request: Request,
    operator: OperatorAccount,
) -> None:
    with store() as s:
        confirm_operator(request, s.db, operator, payload.current_password)
        entry = s.get_provider(provider_id)
        target = s.db.get(AccountRow, account_id)
        if target is None or entry is None:
            raise error("not_found", "Not found.", 404)
        try:
            removed = oidc_accounts.unlink(s, account_id, provider_id)
        except OidcError as exc:
            raise error(exc.code, exc.message, 409) from exc
        if not removed:
            raise error("not_found", "Not found.", 404)
    if account_id != operator.id:
        # Never unseen (Bauplan 01): the account hears of it, with the provider's name.
        tell.person(account_id, _unlinked_notice(entry.label, operator.display_name or operator.name))
    logger.warning("Operator unlinked account %s from provider %s by=%s", account_id, provider_id, operator.name)
