"""Setting up the first account, signing in and out, the own account and its signed-in devices, and the operator's
list of accounts.

Setup, sign-in, the profile and the operator's acts on accounts run through the shared account module
(``vendor/nexkonten``, store ``services/konten_store.py``), the same in every nex app; the routes and their field names
stay as 1.12.0 had them (``name`` is the username, at sign-in "Username or email"; answers only gain fields).

Every way in ends in ``start``: an account that needs a second factor and has none gets a session that may only set
it up (``STAGE_SETUP``); after the code and the recovery codes, ``/api/v1/auth/setup/done`` swaps it for a full one.
Invitations are in ``routers/invites.py``, a new password by a link in ``routers/resets.py``, the address in
``routers/emails.py``, the second factor in ``routers/totp.py``, passkeys in ``routers/passkeys.py``.
"""

from __future__ import annotations

import logging
import unicodedata
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import __version__
from ..config import get_settings
from ..db import SessionLocal
from ..deps import (
    Account,
    BrowserAccount,
    DbSession,
    OperatorAccount,
    address_failed,
    address_guard,
    bearer_token,
    behind_unknown_proxy,
    client_ip,
    confirm_operator,
    confirmed_without_password,
    fresh_session,
    reauth_failed,
    reauth_guard,
    reauth_succeeded,
    session_of,
)
from ..errors import detail, error
from ..models import (
    OPERATOR,
    ROLES,
    SIGN_IN_PASSWORD,
    STAGE_CODES,
    STAGE_FULL,
    STAGE_SETUP,
    AuthSession,
    Vault,
    utcnow,
)
from ..models import Account as AccountRow
from ..models_accounts import FormerName
from ..security import (
    DEVICE_COOKIE,
    DEVICE_DAYS,
    MIN_PASSWORD,
    SESSION_COOKIE,
    devices_of,
    end_all_sessions,
    end_session,
    hash_token,
    server_key,
    session_account,
    start_session,
)
from ..services import (
    accounts,
    catalog,
    kontenpost,
    locales,
    notices,
    oidc_store,
    post_store,
    quota,
    settings_service,
    timezones,
    totp,
)
from ..services import vaults as vaults_service
from ..services.accounts import AccountError
from ..services.konten_store import KontenStore, blocked_since, counts, pending_of, proven, theme_of
from ..vendor import nexkonten, nexpost
from ..vendor.nexkonten import login as konten_login
from ..vendor.nexkonten import profiles
from ..vendor.nexkonten import sessions as konten_sessions
from ..vendor.nexkonten import setup as konten_setup

logger = logging.getLogger("nexpaper.auth")

router = APIRouter(prefix="/api/v1", tags=["auth"])

#: The languages inside the frontend; others come as files from the operator.
SHIPPED = ("en", "de", "fr")
#: Names a sign-in waiting for its second factor (``services/totp.py``), and nothing else.
PENDING_COOKIE = "nexpaper_2fa" + get_settings().cookie_name_suffix()


class SetupIn(BaseModel):
    #: The username (field ``name`` as in 1.12.0); left out, a suggestion from the display name.
    name: str | None = Field(default=None, max_length=64)
    #: The display name (since the shared account module); left out, the username stands in (a page of 1.12.0).
    display_name: str | None = Field(default=None, max_length=200)
    email: str = Field(default="", max_length=255)
    password: str = Field(max_length=200)
    #: The password typed a second time; checked when given (see ``check_confirm``).
    password_confirm: str | None = Field(default=None, max_length=200)
    #: The browser's language (1.12.0 sent the one picked on the page); empty: the browser's, read from the request.
    language: str = Field(default="", max_length=16)
    #: The setup code from the server's log (or NEXPAPER_SETUP_TOKEN).
    code: str = Field(default="", max_length=200)


class LoginIn(BaseModel):
    #: "Username or email" (the field kept its name): an address is looked up by its @. Up to 254 characters, the
    #: longest address: a long one is a wrong sign-in, not a malformed request.
    name: str = Field(max_length=254)
    password: str = Field(max_length=200)
    #: "Stay signed in on this device": the session lasts until it was not used for 30 days. Without, it ends with
    #: the browser, and after twelve hours at the latest.
    remember: bool = True


class PasswordChangeIn(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)
    #: The new password typed a second time; checked when given (see ``check_confirm``).
    password_confirm: str | None = Field(default=None, max_length=200)


class LanguageIn(BaseModel):
    language: str = Field(max_length=16)


class ProfileIn(BaseModel):
    #: Left out, it stays as it is; empty shows the username.
    display_name: str | None = Field(default=None, max_length=200)
    #: A new username (since the shared account module).
    name: str | None = Field(default=None, max_length=64)
    #: A new address (since the shared account module; ``PUT /api/v1/me/email`` does the same).
    email: str | None = Field(default=None, max_length=255)
    #: The own password, for a new username or address of an account that has one (one question for both).
    password: str = Field(default="", max_length=200)


#: Longest display name, in characters.
DISPLAY_NAME_MAX = 80


def check_display_name(value: str) -> str:
    """The checks of 1.12.0 with their codes (``display_name_invalid``, ``display_name_too_long``), before the shared
    module cleans the name and checks it is unique.

    Format characters (Unicode Cf: the right-to-left override, zero-width spaces) let a name read other than it is.
    """
    if any(ord(char) < 32 or ord(char) == 127 or unicodedata.category(char) == "Cf" for char in value):
        raise error("display_name_invalid", "A display name cannot hold control or invisible characters.", 422)
    clean = " ".join(value.split())
    if len(clean) > DISPLAY_NAME_MAX:
        raise error(
            "display_name_too_long", f"Use at most {DISPLAY_NAME_MAX} characters.", 422, maximum=DISPLAY_NAME_MAX
        )
    return clean


def secure_cookie(request: Request) -> bool:
    mode = get_settings().cookie_secure.lower()
    if mode == "on":
        return True
    if mode == "off":
        return False
    # The scheme of a trusted proxy is the request's already (``middleware.ForwardedProtoMiddleware``); the header of
    # anybody else counts for nothing (shared sign-in module, "Hinter einem Proxy": nobody is trusted from the start).
    return request.url.scheme == "https"


#: How long the browser keeps the cookie of a session that stays: as long as browsers allow (400 days). The server
#: decides when it ends: 30 days without use.
LONG_COOKIE_DAYS = konten_sessions.REMEMBER_COOKIE_DAYS


def _set_cookie(response: Response, request: Request, token: str, remember: bool) -> None:
    # Without "stay signed in" a cookie for the browser's session only: it goes when the browser closes.
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=LONG_COOKIE_DAYS * 86400 if remember else None,
        httponly=True,
        samesite="lax",
        secure=secure_cookie(request),
        path="/",
    )


def fail(exc: AccountError | nexkonten.AccountError) -> HTTPException:
    """A refusal of nexpaper's own account code or of the shared module, in nexpaper's form: the module's codes answer
    under the names 1.12.0 used where it had others (``public_code``); a brake answers 429 with ``Retry-After``."""
    code = getattr(exc, "public_code", exc.code)
    values = dict(getattr(exc, "extra", {}) or {})
    if code != exc.code:
        # The module's own code too where 1.12.0's name answers (``AccountError.as_dict``, konten 0.3.10): the pages
        # say "expired" even where the answer says ``invite_invalid``.
        values.setdefault("account_code", exc.code)
    if exc.code == "too_many_attempts":
        wait = int(values.get("retry_after") or 1)
        values["retry_after"] = wait
        return HTTPException(status_code=429, detail=detail(code, exc.message, **values),
                             headers={"Retry-After": str(wait)})
    if exc.code == "password_too_short":
        values.setdefault("minimum", MIN_PASSWORD)
    return error(code, exc.message, exc.status, **values)


def check_password(password: str) -> None:
    """The rule for a password set from now on (the module's: at least 12 characters), with 1.12.0's code."""
    try:
        nexkonten.names.check_password_rule(password)
    except nexkonten.AccountError as exc:
        raise error("password_too_short", f"Use at least {MIN_PASSWORD} characters.", 422,
                    minimum=MIN_PASSWORD) from exc


def check_confirm(password: str, confirm: str | None) -> None:
    """A new password typed twice must be the same twice. The web pages send the second one; a client that leaves it
    out (a script, a page of 1.12.0) is not checked, since only a person typing can mistype."""
    if confirm is not None and confirm != password:
        raise error("password_mismatch", "The passwords do not match.", 422, field="password_confirm")


#: The language the page is shown in, sent by the interface with every request.
LANGUAGE_HEADER = "x-nexpaper-language"


def _known(language: str) -> bool:
    return language in SHIPPED or language in {item.code for item in locales.available()}


def interface_language(request: Request) -> str:
    """The language of the page that asks: the one the interface names (``X-Nexpaper-Language``), else the first of
    the browser's languages nexpaper has, by their weight (``locales.best_match``); empty when none fits."""
    named = request.headers.get(LANGUAGE_HEADER, "").strip()[:16]
    if named and _known(named):
        return named
    known = set(SHIPPED) | {item.code for item in locales.available()}
    return locales.best_match(request.headers.get("accept-language", ""), known)


def check_language(language: str) -> str:
    """Empty (the browser decides) or a language nexpaper has."""
    if language and language not in SHIPPED and language not in {item.code for item in locales.available()}:
        raise error("unknown_language", "nexpaper does not have this language.", 422)
    return language


def former_name(db: Session, account: AccountRow) -> str:
    """The username the account had before its last change ("formerly …" under the field), "" for none."""
    return db.scalar(select(FormerName.name).where(FormerName.account_id == account.id)
                     .order_by(FormerName.id.desc()).limit(1)) or ""


def account_view(account: AccountRow) -> dict[str, Any]:
    """The own account as every page of 1.12.0 read it, and what the shared module adds (answers only gain fields).
    ``email_confirmed`` keeps its meaning: the address is proven by a link (only then does the intake trust it);
    ``email_counts`` says it counts for signing in and "Forgot your password?"."""
    with SessionLocal() as db:
        keys = totp.passkey_count(db, account.id)
        pending = pending_of(db, account.id)
        before = former_name(db, account)
        state = nexkonten.factor.state(KontenStore(db), account.id)
    on = bool(account.totp_secret_enc) or keys > 0
    offered = KontenStore.offered(account)
    return {
        "id": account.id,
        "name": account.name,
        "display_name": account.display_name,
        # "What's new" (block X3): the running version and the one the account has read.
        "version": __version__,
        "whats_new_seen": account.whats_new_seen,
        "role": account.role,
        "sign_in": account.sign_in,
        "has_password": account.sign_in == SIGN_IN_PASSWORD and bool(account.password_hash),
        "email": account.email,
        # Proven by a link sent to it; an address the operator typed or one set without a mail server is not.
        "email_confirmed": proven(account),
        # The address counts: signing in with it, "Forgot your password?", notices.
        "email_counts": counts(account),
        "email_source": "provider" if account.email and account.email_from_provider else "",
        # A new address waiting for its link; the one in "email" stays until it is opened.
        "email_pending": pending,
        "former_name": before,
        # The address a sign-in provider knows the account by, offered on the profile.
        "offered_email": offered,
        "offered_email_provider": (account.offered_email_provider or "") if offered else "",
        "language": account.language,
        # Linked to at least one sign-in provider (which ones: ``GET /api/v1/oidc/me``).
        "oidc_linked": _has_links(account.id),
        # A second factor of any kind: a code from an app (``totp``) or a passkey.
        "two_factor": on,
        "totp": bool(account.totp_secret_enc),
        "passkeys": keys,
        # "On" or "Off" beside the heading of the second factor (``SECOND_FACTOR_STATE`` of the shared module).
        "factor_state": state,
        # NEXPAPER_SECOND_FACTOR_OFF: the emergency hammer holds, no second factor is asked of anybody.
        "second_factor_off": nexkonten.factor.switched_off(),
        "two_factor_recovery_left": len(totp.load_recovery(account.totp_recovery)) if on else 0,
        "created_at": account.created_at.isoformat(),
        "last_seen_at": account.last_seen_at.isoformat() if account.last_seen_at else None,
        "password_changed_at": account.password_changed_at.isoformat() if account.password_changed_at else None,
        # A password set through a link: the page lists the ways in that stayed, until put away.
        "new_password_origin": account.new_password_origin or "",
        "avatar": account.avatar_at.isoformat() if account.avatar_at else None,
        "profile": profile_of(account.profile),
        # What the operator allows this account (on from the start): the AI.
        "ai_allowed": bool(account.ai_allowed),
    }


def _has_links(account_id: int) -> bool:
    from ..models import OidcLink

    with SessionLocal() as db:
        return db.scalar(select(OidcLink.id).where(OidcLink.account_id == account_id).limit(1)) is not None


#: Where the device cookie goes: the sign-in with a password and every return from a provider (all of them lie below
#: ``/api/v1/oidc``: ``/callback`` of the entry ``oidc``, ``/<slug>/callback`` of the others), nowhere else.
DEVICE_PATHS = ("/api/v1/oidc", "/api/v1/auth")
#: Where 1.0.1 put it for its single provider: it goes when a sign-in renews the cookie (``/api/v1/oidc`` holds it now).
OLD_DEVICE_PATHS = ("/api/v1/oidc/callback",)


def browser_mark(db: Session, request: Request, account_id: int) -> str:
    """The mark of a browser that signed in as this account before, "" for none: a mark of the shared module
    (random per account, signed, no account id in it), or a cookie entry of 1.12.0 (``<id>.<nonce>.<mark>``), read
    for one version so that owners stay known."""
    cookie = request.cookies.get(DEVICE_COOKIE, "")
    if not cookie:
        return ""
    try:
        key = KontenStore(db).device_key(account_id)
    except LookupError:
        return ""
    db.commit()
    return konten_sessions.known_mark(cookie, server_key(), key,
                                      older=lambda entry: account_id in devices_of(entry))


def remember_device(db: Session, request: Request, response: Response, account: AccountRow) -> bool:
    """This browser is known for the account from now on: a lock that strangers cause by guessing does not keep it
    out, the brake counts it in a pot of its own, and signing in from it again is no new sign-in. Gives whether it
    was known before."""
    known = bool(browser_mark(db, request, account.id))
    mark = konten_sessions.mark(server_key(), KontenStore(db).device_key(account.id))
    db.commit()
    value = konten_sessions.add_mark(request.cookies.get(DEVICE_COOKIE, ""), mark)
    for path in OLD_DEVICE_PATHS:
        response.delete_cookie(DEVICE_COOKIE, path=path, httponly=True, samesite="lax", secure=secure_cookie(request))
    for path in DEVICE_PATHS:
        response.set_cookie(DEVICE_COOKIE, value, max_age=DEVICE_DAYS * 86400, httponly=True, samesite="lax",
                            secure=secure_cookie(request), path=path)
    return known


def start(
    db: DbSession, request: Request, response: Response, account: AccountRow, *, remember: bool = True,
    by_provider: bool = False,
) -> str:
    """The session of a sign-in that went through, by any way; gives its stage.

    An account that must set up a second factor first gets a session that may do only that, for a quarter of an hour,
    and nothing else happens yet. A full session brings the cookies and, when this browser is new for the account, the
    notice to the other devices and the mail of the shared modules (``services/notices.py``). ``by_provider``: it came
    in through a provider whose entry checks the second factor itself; "require a second factor" does not send this
    session to set one up, and the session keeps that mark."""
    agent = request.headers.get("user-agent", "")
    account.second_factor_by_provider = by_provider
    if totp.setup_required(db, account):
        token = start_session(db, account, client_ip(request), agent, remember=remember, stage=STAGE_SETUP)
        _set_cookie(response, request, token, False)
        return STAGE_SETUP
    first = not account.signed_in_before
    account.signed_in_before = True
    known = remember_device(db, request, response, account)
    konten_login.succeeded(KontenStore(db), account.id)
    token = start_session(db, account, client_ip(request), agent, remember=remember,
                          second_factor_by_provider=by_provider)
    _set_cookie(response, request, token, remember)
    notices.new_sign_in(account, agent, first=first, known=known)
    return STAGE_FULL


def sign_in(
    db: DbSession, request: Request, response: Response, account: AccountRow, *, remember: bool = True
) -> dict[str, Any]:
    stage = start(db, request, response, account, remember=remember)
    if stage == STAGE_SETUP:
        logger.info("Signed in, second factor to be set up first name=%s", account.name)
    else:
        logger.info("Signed in name=%s", account.name)
    return {**account_view(account), "session_stage": stage,
            "second_factor_setup_required": stage == STAGE_SETUP}


@router.get("/setup", summary="Does nexpaper still need its first account, and is this browser signed in?")
def setup_state(request: Request, db: DbSession) -> dict[str, Any]:
    # ``signed_in`` lets the page ask for the account only when there is one: a 401 would show as an error in the
    # browser's console on every visit of the sign-in page.
    return {
        "needs_setup": accounts.count(db) == 0,
        # The first account needs the setup code from the server's log.
        "code_required": True,
        "signed_in": session_account(db, request.cookies.get(SESSION_COOKIE)) is not None,
        "version": __version__,
        "min_password": MIN_PASSWORD,
        # Whether the operator will set up a second factor right after (the page says so only then).
        "factor_required": bool(settings_service.get(db, "two_factor_required")),
    }


@router.post("/setup", summary="Create the operator account")
def setup(payload: SetupIn, request: Request, response: Response, db: DbSession) -> dict[str, Any]:
    """Through the shared module (``setup.setup``): the code first, then display name, username, address, password.
    A page of 1.12.0 sends ``name`` and no display name: the username stands in for it."""
    key = "setup:" + client_ip(request)
    address_guard(request, key)
    check_confirm(payload.password, payload.password_confirm)
    language = check_language(payload.language) or interface_language(request)
    shown = payload.display_name if payload.display_name is not None and payload.display_name.strip() else (
        payload.name or "")
    username = payload.name if payload.name is not None else nexkonten.names.suggest_username(shown)
    try:
        done = konten_setup.setup(
            KontenStore(db), code=payload.code, display_name=shown, username=username, email=payload.email,
            password=payload.password, language=language,
        )
    except nexkonten.AccountError as exc:
        if exc.code == "setup_code_wrong":
            address_failed(request, key)
            logger.warning("Setup refused: wrong setup code")
        raise fail(exc) from exc
    account = db.get(AccountRow, int(done.account.id))
    assert account is not None
    # The kinds that come with nexpaper in the language of the one who sets it up (renamed ones stay as they are).
    catalog.name_kinds_for(db, language)
    db.commit()
    return sign_in(db, request, response, account)


@router.get("/auth/methods", summary="How one can sign in here (no sign-in needed)")
def methods(request: Request, db: DbSession) -> dict[str, Any]:
    from ..services import passkeys, resets
    from ..vendor.nexoidc import providers

    values = settings_service.get_all(db)
    return {
        "password": bool(values["password_login"]),
        # A button per active sign-in provider, in the operator's order: slug and label, nothing else (the same as
        # ``GET /api/v1/oidc/providers``).
        "providers": providers.public_list(oidc_store.SqlStore(db)),
        # Passkeys work under the public https address, or on localhost, while the operator allows them.
        "passkeys": bool(values["passkeys_allowed"]) and passkeys.available(db, request.url.hostname),
        # "Forgot your password?" where a mail goes out and the link has a public address to point to.
        "forgot": bool(values["password_login"]) and resets.available(db),
        # How long "stay signed in" lasts without use (NEXPAPER_SESSION_DAYS): the sign-in page says it before anybody
        # is signed in, and the list of devices says it after.
        "session_days": get_settings().session_days,
        # NEXPAPER_SECOND_FACTOR_OFF holds: the sign-in page says plainly that no code is asked.
        "second_factor_off": nexkonten.factor.switched_off(),
    }


def park(request: Request, response: Response, db: DbSession, account: AccountRow, remember: bool) -> dict[str, Any]:
    """The first step went through and the account has a second factor: nothing opens yet. The browser gets a
    short-lived cookie that names the waiting sign-in and nothing else, and learns which factors it may give."""
    response.set_cookie(
        PENDING_COOKIE,
        totp.start_pending(account.id, remember),
        max_age=totp.PENDING_SECONDS,
        httponly=True,
        samesite="lax",
        secure=secure_cookie(request),
        path="/api/v1/auth",
    )
    logger.info("First step passed, second factor waiting name=%s", account.name)
    return {"second_factor": True, "totp": bool(account.totp_secret_enc),
            "passkey": totp.passkey_count(db, account.id) > 0}


@router.post("/auth/login", summary="Sign in with username or email and password")
def login(payload: LoginIn, request: Request, response: Response, db: DbSession) -> dict[str, Any]:
    """The shared account module signs in (``login.sign_in``, konten 0.3.10): its brake, then its check. One answer
    for everything wrong, as long for an unknown name as for a wrong password, failures counted at the account and its
    lock after ten (a browser that signed in as the account before passes the lock and counts in a pot of its own).

    The brake counts in the module's two pots, the sender (30 free) and the account it names (or what was typed, five
    free). A full sender's pot answers 429 with ``Retry-After``; a full pot of the account answers like a wrong
    password, ``wrong_credentials`` (as for a name that is none): nothing tells that the account exists, and an
    installation of 1.12.0 knows that answer for an account under attack (test "Bestand")."""
    behind_unknown_proxy(request)
    store = KontenStore(db)
    meant = konten_login.resolve_login(store, payload.name)
    mark = browser_mark(db, request, int(meant.id)) if meant is not None else ""
    try:
        konto = konten_login.sign_in(
            store, payload.name, payload.password, sender=client_ip(request), browser=mark,
            known_browser=meant.id if mark and meant is not None else None,
        )
    except nexkonten.AccountError as exc:
        raise fail(exc) from exc
    account = db.get(AccountRow, int(konto.id))
    assert account is not None
    if not settings_service.get(db, "password_login") and account.role != OPERATOR:
        # The operator keeps the password as the way in when the provider is down.
        raise error("password_login_off", "Sign-in with a password is turned off.", 403)
    step = nexkonten.common.next_step(store, konto)
    if step in (nexkonten.NEXT_SECOND_FACTOR, nexkonten.NEXT_PASSKEY):
        return park(request, response, db, account, payload.remember)
    return sign_in(db, request, response, account, remember=payload.remember)


@router.post("/auth/setup/done", summary="The recovery codes are kept: the session that set up the second factor "
             "becomes a full one")
def setup_done(request: Request, response: Response, account: Account, db: DbSession) -> dict[str, Any]:
    info = session_of(request)
    if info.stage != STAGE_CODES:
        raise error("not_in_setup", "There is nothing to confirm.", 409)
    row = db.get(AccountRow, account.id)
    assert row is not None
    # A new token for the full session: what was known of the one before (it lived through the setup) opens nothing.
    gone = db.execute(delete(AuthSession).where(
        AuthSession.token_hash == hash_token(request.cookies.get(SESSION_COOKIE) or ""),
        AuthSession.stage == STAGE_CODES))
    db.commit()
    if int(getattr(gone, "rowcount", 0) or 0) != 1:
        # A second click at the same moment: the first one made the session.
        raise error("not_in_setup", "There is nothing to confirm.", 409)
    stage = start(db, request, response, row, remember=info.remember)
    logger.info("Second factor set up, signed in name=%s", row.name)
    return {**account_view(row), "session_stage": stage, "second_factor_setup_required": False}


@router.post("/auth/setup/codes", summary="New recovery codes while they wait to be confirmed (a reload lost them)")
def setup_codes(request: Request, account: Account, db: DbSession) -> dict[str, Any]:
    """Shown once, the codes are gone with a reload of the page. Until the person confirms they are kept, this session
    (which set up the second factor a moment ago) may make new ones; the old ones stop working."""
    if session_of(request).stage != STAGE_CODES:
        raise error("not_in_setup", "There is nothing to confirm.", 409)
    try:
        codes = nexkonten.factor.new_codes(KontenStore(db), account.id, actor_confirmed=True)
    except nexkonten.AccountError as exc:
        raise fail(exc) from exc
    logger.info("Recovery codes made again during the setup name=%s", account.name)
    return {"recovery_codes": codes}


@router.post("/auth/logout", status_code=204, summary="Sign out in this browser")
def logout(request: Request, response: Response, db: DbSession) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    account = session_account(db, token)
    end_session(db, token)
    if account is not None:
        logger.info("Signed out name=%s", account.name)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.post("/auth/logout-all", status_code=204, summary="Sign out every other browser and paired device")
def logout_everywhere(request: Request, response: Response, account: BrowserAccount, db: DbSession) -> None:
    """"Sign out everywhere else": every other browser and every paired device; API keys and passkeys stay (the list
    under Security says so)."""
    end_all_sessions(db, account.id, except_token=request.cookies.get(SESSION_COOKIE))
    # The other browsers are not known any more; this one stays known.
    KontenStore(db).renew_device_key(account.id)
    db.commit()
    row = db.get(AccountRow, account.id)
    if row is not None:
        remember_device(db, request, response, row)
    logger.info("All other sessions ended by their owner name=%s", account.name)


@router.get("/auth/me", summary="The signed-in account, and what this server offers it")
def me(request: Request, account: Account, db: DbSession) -> dict[str, Any]:
    stage = session_of(request).stage
    return {
        **account_view(account),
        "mail": post_store.configured(db),
        # A link for a new address can go out (a mail server and the public address); without, an address counts at
        # once (and is not proven: the intake does not trust it).
        "mail_links": kontenpost.can_mail(db),
        "session_stage": stage,
        "second_factor_setup_required": stage != STAGE_FULL or totp.setup_required(db, account),
        "second_factor_required": bool(settings_service.get(db, "two_factor_required"))
        and not totp.provider_checks(db, account) and not nexkonten.factor.switched_off(),
        # This session came in through a provider that checks the second factor, and the account (with a password)
        # has none of its own: its device tokens and API keys wait until it sets one up (they have no provider behind
        # them). Making one stays possible; the page says so beside them.
        "keys_wait_for_second_factor": bool(account.second_factor_by_provider) and totp.keys_wait(db, account),
        "passkeys_allowed": bool(settings_service.get(db, "passkeys_allowed")),
        # konten 1.1.0: light, dark or system for the account on every device ("" while it never chose: the page
        # hands the server its browser's value once, ``POST /api/v1/me/theme/adopt``), and whether the profile shows
        # "Address not confirmed yet" with "Send link" (an address that counts, never proven, a mail server to send).
        "theme": theme_of(account),
        "email_needs_proof": _needs_proof(db, account),
        "min_password": MIN_PASSWORD,
        # Signed in at a provider within the last minutes: an account without a password may confirm with that.
        "fresh_sign_in": fresh_session(request),
    }


def _needs_proof(db: Session, account: AccountRow) -> bool:
    konto = KontenStore(db).get_account(account.id)
    return konto is not None and profiles.needs_proof(konto, mail_server=kontenpost.can_mail(db))


class ThemeIn(BaseModel):
    #: ``light``, ``dark`` or ``system``.
    theme: str = Field(max_length=16)


@router.put("/me/theme", summary="Light, dark or as the device says, for the own account on every device")
def set_theme(payload: ThemeIn, account: Account, db: DbSession) -> dict[str, str]:
    """``profiles.change_theme`` of the shared module; kept in ``profile.mode`` as before (``PUT /me/preferences`` with
    ``mode`` changes the same)."""
    try:
        changed = profiles.change_theme(KontenStore(db), account.id, payload.theme)
    except nexkonten.AccountError as exc:
        db.rollback()
        raise fail(exc) from exc
    return {"theme": changed.theme}


@router.post("/me/theme/adopt", summary="The browser's earlier choice, taken once while the account has none")
def adopt_theme(payload: ThemeIn, account: Account, db: DbSession) -> dict[str, str]:
    """``profiles.adopt_theme``: an account that never chose takes what this browser had; one that chose keeps it.
    Answers the theme in effect."""
    return {"theme": profiles.adopt_theme(KontenStore(db), account.id, payload.theme)}


# --- The own signed-in devices ----------------------------------------------------------------------------------------


@router.get("/auth/sessions", summary="Where the own account is signed in: browsers and paired devices")
def sessions(request: Request, account: Account, db: DbSession) -> list[dict[str, Any]]:
    """The shared module's list ("Firefox on Linux", never the stored browser text, paired devices by their name):
    this browser first, then the others. The fields of 1.12.0 stay beside (``device``, ``network``, ``here``)."""
    here = session_of(request).uid
    language = (interface_language(request) or account.language or "en")[:2]
    listed = konten_sessions.listing(KontenStore(db), account.id, here, language=language)
    rows = {row.uid: row for row in db.scalars(select(AuthSession).where(AuthSession.account_id == account.id))}
    out: list[dict[str, Any]] = []
    for item in listed:
        entry = dict(item)
        row = rows.get(str(entry.get("uid", "")))
        # The fields of 1.12.0: ``id``, ``device`` the name shown, ``phone``, ``network``, ``here``.
        entry["id"] = entry.get("uid", "")
        entry["device"] = entry.get("label", "")
        entry["phone"] = entry.get("kind") == "device"
        if row is not None:
            entry["network"] = notices.network_of(row.ip, language)
            entry["phone"] = notices.system_of(row.user_agent or "") in ("iPhone", "Android")
            entry["remember"] = bool(row.remember)
        entry["here"] = bool(entry.get("current"))
        out.append(entry)
    return sorted(out, key=lambda item: not item["here"])


SessionUid = Annotated[str, Path(min_length=1, max_length=48, pattern=r"^[0-9a-zA-Z_-]+$")]


@router.delete("/auth/sessions/{uid}", status_code=204, summary="Sign out one of the own browsers or devices")
def end_one(uid: SessionUid, request: Request, account: BrowserAccount, db: DbSession) -> None:
    if uid == session_of(request).uid:
        raise error("this_session", "To sign out here, use Sign out.", 409)
    # Only a session of the own account: another account's looks exactly like one that does not exist.
    if not konten_sessions.sign_out(KontenStore(db), account.id, uid):
        raise error("not_found", "No such session.", 404)
    db.commit()
    logger.info("A device signed out by its owner name=%s", account.name)


@router.get("/auth/access", summary="What still has access after a password set through a link")
def remaining_access(account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    row = db.get(AccountRow, account.id)
    assert row is not None
    return {
        "origin": row.new_password_origin or "",
        "access": [
            {"id": str(item.id), "kind": item.kind, "label": item.label,
             "last_used_at": item.last_used_at.isoformat() if item.last_used_at else None}
            for item in KontenStore(db).list_access(account.id)
        ],
    }


@router.post("/auth/access/disconnect", summary="Disconnect all: every paired device, API key and passkey")
def disconnect_all(request: Request, account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    """Only right after signing in (the shared module's five minutes): whoever set the new password a moment ago."""
    if not fresh_session(request):
        raise error("sign_in_again", "Sign in again first: this needs a sign-in from the last minutes.", 403,
                    minutes=nexkonten.common.FRESH_SIGN_IN_MINUTES)
    from ..vendor.nexkonten import resets

    count = resets.disconnect_all(KontenStore(db), account.id)
    row = db.get(AccountRow, account.id)
    assert row is not None
    row.new_password_origin = ""
    db.commit()
    totp.forget_account(account.id)
    return {"disconnected": count}


@router.post("/auth/access/seen", summary="The list of what still has access is put away")
def remaining_access_seen(account: BrowserAccount, db: DbSession) -> dict[str, Any]:
    row = db.get(AccountRow, account.id)
    assert row is not None
    row.new_password_origin = ""
    db.commit()
    return account_view(row)


@router.put("/auth/password", status_code=204, summary="Change the own password")
def change_password(payload: PasswordChangeIn, request: Request, response: Response, account: BrowserAccount,
                    db: DbSession) -> None:
    row = db.get(AccountRow, account.id)
    assert row is not None
    if row.sign_in != SIGN_IN_PASSWORD:
        raise error("oidc_account", "This account signs in through OIDC.", 409)
    check_password(payload.new)
    check_confirm(payload.new, payload.password_confirm)
    reauth_guard(request, row)
    try:
        accounts.change_password(db, row, payload.current, payload.new)
    except AccountError as exc:
        if exc.code == "wrong_password":
            reauth_failed(request, db, row)
        raise fail(exc) from exc
    reauth_succeeded(request, db, row)
    row.password_changed_at = utcnow()
    db.commit()
    # Other browsers and paired devices must sign in again and are not known any more (as in 1.12.0); this one stays,
    # and stays known.
    end_all_sessions(db, row.id, except_token=request.cookies.get(SESSION_COOKIE))
    KontenStore(db).renew_device_key(row.id)
    db.commit()
    db.refresh(row)
    remember_device(db, request, response, row)
    logger.info("Password changed, every other session ended name=%s", row.name)


def change_address(db: Session, row: AccountRow, address: str, *, password: str, fresh: bool) -> str:
    """A new address through the shared module (``profiles.change_email``): with the own password, and with a mail
    server and the public address it waits for the link sent there (at once: a server that does not take it leaves
    nothing waiting, 502); without, it counts at once but is not proven (the intake does not trust it). "" takes the
    address away. The address that now waits for its link, "" for none.

    As in 1.12.0 the same address again while it is not proven sends a link to it, with the password as well
    (``prove_address``, the module's ``profiles.prove_email``)."""
    mail = kontenpost.can_mail(db)
    clean = address.strip()
    if clean and (row.email or "").strip().lower() == clean.lower() and not proven(row):
        if not mail:
            raise error("email_same", "This is your address already.", 409)
        store = KontenStore(db)
        konto = store.get_account(row.id)
        assert konto is not None
        nexkonten.common.confirm(store, konto, password, fresh, without_password=True)
        return prove_address(db, row)
    changed = profiles.change_email(KontenStore(db), row.id, address, password=password, actor_confirmed=fresh,
                                    mail=mail)
    if changed.mail is not None:
        try:
            kontenpost.send_now(db, changed.mail, keep=False)
        except nexpost.MailError as exc:
            profiles.withdraw_email_change(KontenStore(db), row.id)
            raise error(post_store.app_code(exc), "The mail server did not take the mail.", 502) from exc
        logger.info("Address confirmation sent name=%s", row.name)
    kontenpost.queue(db, changed.notice)
    return changed.pending


def prove_address(db: Session, row: AccountRow) -> str:
    """A link to the address the account has, which counts but is not proven yet (an invitation's, one set without a
    mail server): opened, it is proven, and the intake trusts it (the module's ``profiles.prove_email``, counted at
    its brake ``mail:<id>``, confirmed by ``profiles.confirm_email``). A mail the server does not take leaves nothing
    waiting (502). The address that waits for its link."""
    if not kontenpost.can_mail(db):
        raise error("mail_off", "There is no mail server set up.", 409)
    letter = profiles.prove_email(KontenStore(db), row.id)
    address = letter.to
    try:
        kontenpost.send_now(db, letter, keep=False)
    except nexpost.MailError as exc:
        profiles.withdraw_email_change(KontenStore(db), row.id)
        raise error(post_store.app_code(exc), "The mail server did not take the mail.", 502) from exc
    logger.info("Link to prove the address sent name=%s", row.name)
    return address


@router.put("/me/profile", summary="The own display name, username and address")
def set_profile(payload: ProfileIn, request: Request, account: Account, db: DbSession) -> dict[str, Any]:
    """Field by field, through the shared module: the display name without a password (it may be empty: then the
    username shows), a new username and a new address with the own password (an account without one: a fresh
    sign-in at its provider), one "Save" for all. A paired device changes the display name only."""
    row = db.get(AccountRow, account.id)
    assert row is not None
    changes_email = payload.email is not None and payload.email.strip().lower() != (row.email or "").strip().lower()
    changes_name = payload.name is not None and payload.name.strip().lower() != row.name.lower()
    if (changes_email or changes_name) and bearer_token(request) is not None:
        raise error("browser_only", "This needs a signed-in browser, not a device token.", 403)
    store = KontenStore(db)
    try:
        if payload.display_name is not None:
            shown = check_display_name(payload.display_name)
            if shown != (row.display_name or ""):
                profiles.change_display_name(store, row.id, shown, actor_id=row.id)
        fresh = confirmed_without_password(request, row) if (changes_email or changes_name) else False
        if changes_name:
            notice = profiles.change_username(store, row.id, payload.name or "", actor_id=row.id,
                                              password=payload.password, actor_confirmed=fresh)
            kontenpost.queue(db, notice)
            logger.info("Username changed by its owner account_id=%s", row.id)
        if changes_email:
            change_address(db, row, payload.email or "", password=payload.password, fresh=fresh)
    except nexkonten.AccountError as exc:
        db.rollback()
        raise fail(exc) from exc
    db.refresh(row)
    return account_view(row)


@router.post("/me/whats-new/seen", summary="\"What's new\" of the running version is read or put away")
def whats_new_seen(account: Account, db: DbSession) -> dict[str, Any]:
    row = db.get(AccountRow, account.id)
    assert row is not None
    row.whats_new_seen = __version__
    db.commit()
    return account_view(row)


@router.put("/me/language", summary="The language of the own account; empty follows the browser")
def set_language(payload: LanguageIn, account: Account, db: DbSession) -> dict[str, Any]:
    row = db.get(AccountRow, account.id)
    assert row is not None
    row.language = check_language(payload.language)
    db.commit()
    return account_view(row)


#: What a person may set for themselves, with the values allowed; the first one is the default.
PROFILE: dict[str, tuple[Any, ...]] = {
    #: Light, dark, or as the system is set.
    "mode": ("system", "light", "dark"),
    #: A phone opens on the quick upload (``/schnell``) instead of the archive.
    "quick_start": (True, False),
    #: How the archive shows the documents: a list or tiles.
    "view": ("list", "grid"),
    #: The AI for this person (Account, AI): off, no proposal is asked for and the server refuses.
    "ai": (True, False),
    #: A push and a mail when the account signs in from a new device (``services/notices.py``).
    "notify_login": (True, False),
    #: Deadlines for this person (Mein Konto, Erinnerungen): off, the menu has no "Fristen", nothing is reminded and no
    #: weekly mail comes (``services/deadlines.wanted``). The dates on the documents stay.
    "deadlines": (True, False),
    #: Where the time zone came from: the browser in use, or the person's own choice, which no browser overrides.
    "timezone_source": ("browser", "manual"),
}
#: The vault new documents go to when the person does not choose; the id of a vault they may add to, or none (their
#: personal vault). Set only to a vault the person may add to; a vault they lost later is ignored where it is used.
DEFAULT_VAULT_MAX = 2**31 - 1


def _default_vault(value: Any) -> int | None:
    return value if type(value) is int and 1 <= value <= DEFAULT_VAULT_MAX else None


def profile_of(stored: Any) -> dict[str, Any]:
    stored = stored if isinstance(stored, dict) else {}
    out = {
        key: stored[key] if stored.get(key) in allowed and type(stored.get(key)) is type(allowed[0]) else allowed[0]
        for key, allowed in PROFILE.items()
    }
    out["default_vault"] = _default_vault(stored.get("default_vault"))
    # The time zone the browser reported ("Europe/Berlin"): the notices of a new sign-in name their time in it.
    out["timezone"] = stored.get("timezone") if timezones.valid_time_zone(stored.get("timezone")) else ""
    return out


#: Choices that guard the account: a device token may not change them (a lost phone could switch off the notice that
#: tells the owner of a new sign-in), only a signed-in browser may.
BROWSER_ONLY_PREFERENCES = frozenset({"notify_login"})


@router.put("/me/preferences", summary="The own profile choices; only the values sent change")
def set_preferences(payload: dict[str, Any], request: Request, account: Account, db: DbSession) -> dict[str, Any]:
    if bearer_token(request) is not None and BROWSER_ONLY_PREFERENCES.intersection(payload):
        raise error("browser_only", "This needs a signed-in browser, not a device token.", 403)
    row = db.get(AccountRow, account.id)
    assert row is not None
    current = profile_of(row.profile)
    # A zone the browser reports does not overrule one the person chose: the rest of the change still counts.
    if payload.get("timezone_source") == "browser" and current["timezone_source"] == "manual":
        payload = {key: value for key, value in payload.items() if key not in ("timezone", "timezone_source")}
    for key, value in payload.items():
        if key == "timezone":
            if not timezones.valid_time_zone(value):
                raise error("bad_preference", "This value is not one nexpaper offers.", 422, field=key)
            current[key] = value
            continue
        if key == "default_vault":
            if value is not None and (
                _default_vault(value) is None or not vaults_service.can_add_to(db, account.id, value)
            ):
                # Only a vault the person may add to can be where their uploads go.
                raise error("bad_preference", "This value is not one nexpaper offers.", 422, field=key)
            current[key] = value
            continue
        allowed = PROFILE.get(key)
        if allowed is None or value not in allowed or type(value) is not type(allowed[0]):
            raise error("bad_preference", "This value is not one nexpaper offers.", 422, field=key)
        current[key] = value
    row.profile = current
    db.commit()
    return current


# --- Accounts (operator) --------------------------------------------------------------------------------------------


class RoleIn(BaseModel):
    role: str = Field(max_length=16)
    #: The operator's own password once more (see ``confirm_operator``); empty for an account from a provider.
    current_password: str = Field(default="", max_length=200)


class OperatorConfirmIn(BaseModel):
    current_password: str = Field(default="", max_length=200)


class AccountDeleteIn(BaseModel):
    """Deleting an account: the operator's password, the account's name typed once more, and, when its own vault holds
    documents, where they go."""

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(default="", max_length=200)
    #: The name of the account, as it is: a slip of the hand in a list must not delete the wrong one.
    confirm_name: str = Field(default="", max_length=200)
    documents: Literal["transfer_to_user", "transfer_to_vault", "delete_documents"] | None = None
    target_user_id: int | None = Field(default=None, ge=1, le=2**31 - 1)
    target_vault_id: int | None = Field(default=None, ge=1, le=2**31 - 1)


class VaultRef(BaseModel):
    id: int
    name: str


class SharedVaultRef(VaultRef):
    #: The operator is in this vault and would see documents put there.
    you_see: bool


class AccountLeaving(BaseModel):
    #: Documents in the account's own vault, the trash included.
    documents: int
    #: Shared vaults the account is the only manager of; deleting it is refused while there are.
    sole_manager_of: list[VaultRef]
    #: The shared vaults the documents can go to.
    shared_vaults: list[SharedVaultRef]
    #: The people whose own vault the operator is in (the operator included): documents given to them the operator
    #: sees afterwards.
    heirs_you_see: list[int]


def _row(db: DbSession, account_id: int) -> AccountRow:
    row = db.get(AccountRow, account_id)
    if row is None:
        raise error("not_found", "No such account.", 404)
    return row


@router.get("/accounts", summary="All accounts (never what is written in them)")
def list_accounts(operator: OperatorAccount, db: DbSession) -> list[dict[str, Any]]:
    """Every account as the operator's list of the shared module needs it (``ListedAccount``): besides the fields of
    1.12.0 whether the address is shared with another account, whether the row is the operator's own, when it was
    blocked, and the number of documents in its own vault (the trash included, as ``/leaving`` counts them)."""
    rows = list(db.scalars(select(AccountRow).order_by(AccountRow.created_at)))
    shared: dict[str, int] = {}
    for row in rows:
        if (row.email or "").strip():
            key = row.email.strip().lower()
            shared[key] = shared.get(key, 0) + 1
    documents = vaults_service.documents_per_account(db)
    used = quota.used_per_account(db)
    return [listed(row, operator.id, shared, documents.get(row.id, 0), used.get(row.id, 0)) for row in rows]


def listed(row: AccountRow, operator_id: int, shared: dict[str, int], documents: int, used: int) -> dict[str, Any]:
    """One account of the operator's list. Since konten 1.1.0 also when it was deleted and when it goes for good
    (``deleted_at``, ``purge_at``), its storage limit and what its documents take (``storage_limit``,
    ``storage_used``, bytes), and the rights the operator gave it (``rights``: ``ai``). ``blocked`` is a block by
    the operator; the mark a deletion sets is not one."""
    blocked_at = blocked_since(row)
    deleted_at = row.deleted_at
    konto_rights = ["ai"] if row.ai_allowed else []
    # Never what a person chose for themselves either: when they are reminded, their time zone, their looks.
    return {**{key: value for key, value in account_view(row).items() if key != "profile"},
            "locked": accounts.is_locked(row), "blocked": blocked_at is not None,
            "blocked_at": blocked_at.isoformat() if blocked_at else None,
            "deleted_at": deleted_at.isoformat() if deleted_at else None,
            "purge_at": nexkonten.manage.purge_at(deleted_at).isoformat() if deleted_at else None,
            "storage_limit": row.storage_limit,
            "storage_used": used,
            "rights": konto_rights,
            "has_password": bool(row.password_hash),
            "email_duplicate": bool((row.email or "").strip()) and shared.get(row.email.strip().lower(), 0) > 1,
            "self": row.id == operator_id,
            "documents": documents}


def _listed_one(db: Session, row: AccountRow, operator_id: int) -> dict[str, Any]:
    address = (row.email or "").strip().lower()
    shared = {address: int(db.scalar(select(func.count()).select_from(AccountRow).where(
        func.lower(func.trim(AccountRow.email)) == address)) or 0)} if address else {}
    return listed(row, operator_id, shared, vaults_service.documents_per_account(db).get(row.id, 0),
                  quota.used(db, row.id))


class RenameIn(BaseModel):
    #: The new username (``PUT /accounts/{id}/name``) or display name (``/display-name``).
    name: str = Field(max_length=200)
    #: The operator's own password (an operator without one: a fresh sign-in at the provider).
    current_password: str = Field(default="", max_length=200)


def _operator_confirmed(request: Request, db: Session, operator: AccountRow) -> bool:
    row = db.get(AccountRow, operator.id)
    return confirmed_without_password(request, row if row is not None else operator)


@router.put("/accounts/{account_id}/name", summary="Operator: give an account another username")
def rename_account(
    account_id: Annotated[int, Path(ge=1, le=2**31 - 1)], payload: RenameIn, request: Request,
    operator: OperatorAccount, db: DbSession,
) -> dict[str, Any]:
    """Through the shared module (``profiles.change_username``) with the operator's own password. The old name stays
    the account's former name: its intake folder and plus address still reach it, and nobody else ever gets it."""
    row = _row(db, account_id)
    try:
        notice = profiles.change_username(KontenStore(db), row.id, payload.name, actor_id=operator.id,
                                          password=payload.current_password,
                                          actor_confirmed=_operator_confirmed(request, db, operator))
    except nexkonten.AccountError as exc:
        db.rollback()
        raise fail(exc) from exc
    kontenpost.queue(db, notice)
    db.refresh(row)
    logger.warning("Username changed by the operator account_id=%s by=%s", row.id, operator.name)
    return account_view(row)


@router.put("/accounts/{account_id}/display-name", summary="Operator: give an account another display name")
def rename_display(
    account_id: Annotated[int, Path(ge=1, le=2**31 - 1)], payload: RenameIn, request: Request,
    operator: OperatorAccount, db: DbSession,
) -> dict[str, Any]:
    """With the operator's own password, as everything the operator changes at an account."""
    row = _row(db, account_id)
    shown = check_display_name(payload.name)
    confirm_operator(request, db, operator, payload.current_password)
    try:
        profiles.change_display_name(KontenStore(db), row.id, shown, actor_id=operator.id, actor_confirmed=True)
    except nexkonten.AccountError as exc:
        db.rollback()
        raise fail(exc) from exc
    db.refresh(row)
    logger.warning("Display name changed by the operator account_id=%s by=%s", row.id, operator.name)
    return account_view(row)


@router.delete("/accounts/{account_id}/email", summary="Operator: take an account's address away (never set one)")
def remove_account_email(
    account_id: Annotated[int, Path(ge=1, le=2**31 - 1)], payload: OperatorConfirmIn, request: Request,
    operator: OperatorAccount, db: DbSession,
) -> dict[str, Any]:
    """The operator may only take an address away (``profiles.remove_email``): setting one would send a link for a
    new password to an address of the operator's choice. The old address hears of it where a mail can go."""
    row = _row(db, account_id)
    try:
        changed = profiles.remove_email(KontenStore(db), row.id, actor_id=operator.id,
                                        password=payload.current_password,
                                        actor_confirmed=_operator_confirmed(request, db, operator),
                                        mail=post_store.configured(db))
    except nexkonten.AccountError as exc:
        db.rollback()
        raise fail(exc) from exc
    kontenpost.queue(db, changed.notice)
    db.refresh(row)
    logger.warning("Address removed by the operator account_id=%s by=%s", row.id, operator.name)
    return account_view(row)


@router.get("/accounts/{account_id}/leaving", response_model=AccountLeaving,
            summary="What deleting an account would take along: the number of documents in its own vault")
def account_leaving(account_id: int, operator: OperatorAccount, db: DbSession) -> AccountLeaving:
    """A number, never what the documents are: the operator decides where they go without reading them, and is told
    where they would see them afterwards."""
    _row(db, account_id)
    found = vaults_service.leaving(db, account_id, operator.id)
    shared = db.scalars(select(Vault).where(Vault.personal_of.is_(None)).order_by(Vault.id))
    return AccountLeaving(documents=found.documents,
                          sole_manager_of=[VaultRef(id=v.id, name=v.name) for v in found.sole_manager_of],
                          shared_vaults=[SharedVaultRef(id=v.id, name=v.name, you_see=v.id in found.vaults_you_see)
                                         for v in shared],
                          heirs_you_see=found.heirs_you_see)


@router.delete("/accounts/{account_id}", status_code=204,
               summary="Delete an account (it can be brought back for 30 days)")
def delete_account(
    account_id: int, payload: AccountDeleteIn, request: Request, operator: OperatorAccount, db: DbSession,
) -> None:
    """Through the shared account module (konten 1.1.0, ``manage.remove``): the account is gone for everybody at once
    and has no way in any more; for 30 days the operator brings it back (``POST /accounts/{id}/restore``), then it is
    removed for good with everything that belongs to it (``KontenStore.purge_account``). The documents of its own vault
    go where ``documents`` says, checked now as before (without a choice, a vault with documents answers 409 with
    their number) and handed over when it is removed for good. A refusal changes nothing; deleting it again does
    nothing."""
    confirm_operator(request, db, operator, payload.current_password)
    if account_id == operator.id:
        raise error("cannot_delete_self", "You cannot delete your own account.", 409)
    row = _row(db, account_id)
    name = row.name
    if payload.confirm_name.strip() != name:
        raise error("name_mismatch", "Type the name of the account to delete it.", 422)
    if row.deleted_at is not None:
        return
    held = vaults_service.check_leaving(
        db, account_id, choice=payload.documents, target_user=payload.target_user_id,
        target_vault=payload.target_vault_id,
    )
    row.leaving = {"documents": payload.documents, "target_user_id": payload.target_user_id,
                   "target_vault_id": payload.target_vault_id, "by": operator.id}
    try:
        removed = nexkonten.manage.remove(KontenStore(db), row.id, actor_id=operator.id, actor_confirmed=True)
    except nexkonten.AccountError as exc:
        db.rollback()
        raise fail(exc) from exc
    totp.forget_account(account_id)
    logger.warning("Account deleted name=%s by=%s documents=%s choice=%s purge_at=%s", name, operator.name, held,
                   payload.documents if held else "-", removed.purge_at.isoformat())


@router.post("/accounts/{account_id}/restore", summary="Bring a deleted account back within its 30 days")
def restore_account(
    account_id: int, payload: OperatorConfirmIn, request: Request, operator: OperatorAccount, db: DbSession,
) -> dict[str, Any]:
    """With the operator's own password (``manage.restore``). Blocked before the deletion, blocked after; its
    sessions and devices of before stay ended, its documents are where they were. After its days ``not_found``."""
    confirm_operator(request, db, operator, payload.current_password)
    row = _row(db, account_id)
    try:
        nexkonten.manage.restore(KontenStore(db), row.id, actor_id=operator.id, actor_confirmed=True)
    except nexkonten.AccountError as exc:
        db.rollback()
        raise fail(exc) from exc
    db.refresh(row)
    logger.warning("Account restored name=%s by=%s", row.name, operator.name)
    return _listed_one(db, row, operator.id)


@router.post("/accounts/{account_id}/sign-out", status_code=204, summary="End every session of an account")
def sign_out_account(account_id: int, operator: OperatorAccount, db: DbSession) -> None:
    """Every browser and paired device of the account; API keys and passkeys stay (the shared module's rule). Not at
    the own account: "Sign out everywhere else" under Security is for that."""
    if account_id == operator.id:
        raise error("use_account_page", "Sign out your other devices on your account page.", 409)
    row = _row(db, account_id)
    end_all_sessions(db, row.id)
    logger.warning("All sessions ended name=%s by=%s", row.name, operator.name)


@router.post("/accounts/{account_id}/block", status_code=204, summary="Block an account (its sessions end)")
def block_account(
    account_id: int, payload: OperatorConfirmIn, request: Request, operator: OperatorAccount, db: DbSession,
) -> None:
    """Blocked, the account gets in nowhere: its sessions and devices end, its keys stop working, its upload requests
    end (``manage.block``, ``KontenStore.shut_out``). Never the own account, never the last operator."""
    confirm_operator(request, db, operator, payload.current_password)
    if account_id == operator.id:
        raise error("cannot_block_self", "You cannot block yourself.", 409)
    row = _row(db, account_id)
    try:
        nexkonten.manage.block(KontenStore(db), row.id, actor_id=operator.id, actor_confirmed=True)
    except nexkonten.AccountError as exc:
        db.rollback()
        raise fail(exc) from exc
    logger.warning("Account blocked name=%s by=%s", row.name, operator.name)


@router.post("/accounts/{account_id}/unblock", status_code=204, summary="Let a blocked account in again")
def unblock_account(
    account_id: int, payload: OperatorConfirmIn, request: Request, operator: OperatorAccount, db: DbSession,
) -> None:
    """``manage.unblock``: it signs in again, its sessions of before stay ended."""
    confirm_operator(request, db, operator, payload.current_password)
    row = _row(db, account_id)
    if row.id == operator.id:
        return
    try:
        nexkonten.manage.unblock(KontenStore(db), row.id, actor_id=operator.id, actor_confirmed=True)
    except nexkonten.AccountError as exc:
        db.rollback()
        raise fail(exc) from exc
    logger.warning("Account unblocked name=%s by=%s", row.name, operator.name)


class PermissionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ai_allowed: StrictBool | None = None


@router.put("/accounts/{account_id}/permissions", summary="Allow an account the AI, or take it away")
def set_permissions(
    account_id: int, payload: PermissionsIn, operator: OperatorAccount, db: DbSession,
) -> dict[str, Any]:
    """On for every account until the operator takes it away; only the fields sent change. It comes on top of the
    operator's switch for the whole server and the person's own switch. Taking it away stops the next request at once;
    nothing the person kept is touched."""
    row = _row(db, account_id)
    changes: dict[str, bool] = {key: value for key, value in payload.model_dump().items() if value is not None}
    if changes:
        try:
            # "AI allowed" of the shared account module (konten 1.1.0): a box that saves at once, in ``ai_allowed``.
            nexkonten.manage.set_right(KontenStore(db), row.id, nexkonten.config.FEATURE_AI, changes["ai_allowed"],
                                       actor_id=operator.id)
        except nexkonten.AccountError as exc:
            db.rollback()
            raise fail(exc) from exc
        db.refresh(row)
        logger.warning("Permissions changed name=%s %s by=%s", row.name,
                       " ".join(f"{key}={'yes' if value else 'no'}" for key, value in sorted(changes.items())),
                       operator.name)
    return {key: bool(getattr(row, key)) for key in ("ai_allowed",)}


@router.put("/accounts/{account_id}/role", summary="Make an account operator or member")
def set_role(
    account_id: int, payload: RoleIn, request: Request, operator: OperatorAccount, db: DbSession,
) -> dict[str, Any]:
    """Several operators (konten 1.1.0, ``manage.set_role``): never the own account, never the last operator who can
    sign in (``last_operator``), never a deleted account."""
    confirm_operator(request, db, operator, payload.current_password)
    if payload.role not in ROLES:
        raise error("invalid_role", "Unknown role.", 422)
    row = _row(db, account_id)
    if row.id == operator.id and payload.role != OPERATOR:
        raise error("cannot_demote_self", "You cannot take the operator role from yourself.", 409)
    if row.id != operator.id:
        try:
            nexkonten.manage.set_role(KontenStore(db), row.id, payload.role == OPERATOR, actor_id=operator.id,
                                      actor_confirmed=True)
        except nexkonten.AccountError as exc:
            db.rollback()
            raise fail(exc) from exc
        db.refresh(row)
    logger.warning("Role changed name=%s role=%s by=%s", row.name, payload.role, operator.name)
    return account_view(row)


class StorageLimitIn(BaseModel):
    #: Bytes; null removes the limit.
    limit: int | None = Field(default=None, ge=0, le=nexkonten.manage.STORAGE_LIMIT_MAX)
    #: The operator's own password, as for everything the operator changes at an account.
    current_password: str = Field(default="", max_length=200)


@router.put("/accounts/{account_id}/storage-limit", summary="Set or remove the storage limit of an account")
def set_storage_limit(
    account_id: int, payload: StorageLimitIn, request: Request, operator: OperatorAccount, db: DbSession,
) -> dict[str, Any]:
    """What the account's documents may take (``services/quota.py``); the own account too. Reaching it refuses
    uploads, nothing kept is touched (``manage.set_storage_limit``)."""
    confirm_operator(request, db, operator, payload.current_password)
    row = _row(db, account_id)
    try:
        nexkonten.manage.set_storage_limit(KontenStore(db), row.id, payload.limit, actor_id=operator.id,
                                           actor_confirmed=True)
    except nexkonten.AccountError as exc:
        db.rollback()
        raise fail(exc) from exc
    db.refresh(row)
    logger.warning("Storage limit set name=%s limit=%s by=%s", row.name, payload.limit, operator.name)
    return _listed_one(db, row, operator.id)
