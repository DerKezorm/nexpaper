"""Setting up the first account, signing in and out, the own account and its signed-in devices, and the operator's
list of accounts.

Every way in ends in ``start``: an account that needs a second factor and has none gets a session that may only set
it up (``STAGE_SETUP``); after the code and the recovery codes, ``/api/v1/auth/setup/done`` swaps it for a full one.
Invitations are in ``routers/invites.py``, the second factor in ``routers/totp.py``, passkeys in
``routers/passkeys.py``.
"""

from __future__ import annotations

import logging
import unicodedata
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import delete, select

from .. import __version__, clock
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
    client_ip,
    confirm_operator,
    reauth_failed,
    reauth_guard,
    reauth_succeeded,
    session_of,
)
from ..errors import error
from ..middleware import claims_https
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
from ..security import (
    DEVICE_COOKIE,
    DEVICE_DAYS,
    MIN_PASSWORD,
    SESSION_COOKIE,
    device_token,
    devices_of,
    end_all_sessions,
    end_session,
    hash_token,
    session_account,
    start_session,
)
from ..services import (
    accounts,
    catalog,
    emails,
    locales,
    mailer,
    notices,
    oidc_store,
    resets,
    settings_service,
    timezones,
    totp,
)
from ..services import vaults as vaults_service
from ..services.accounts import AccountError

logger = logging.getLogger("nexpaper.auth")

router = APIRouter(prefix="/api/v1", tags=["auth"])

#: The languages inside the frontend; others come as files from the operator.
SHIPPED = ("en", "de")
#: Names a sign-in waiting for its second factor (``services/totp.py``), and nothing else.
PENDING_COOKIE = "nexpaper_2fa" + get_settings().cookie_name_suffix()


class SetupIn(BaseModel):
    name: str = Field(max_length=64)
    password: str = Field(max_length=200)
    language: str = Field(default="", max_length=16)
    #: The setup code from the server's log (or NEXPAPER_SETUP_TOKEN).
    code: str = Field(default="", max_length=200)


class LoginIn(BaseModel):
    name: str = Field(max_length=64)
    password: str = Field(max_length=200)
    #: "Stay signed in on this device": the session lasts until it was not used for 30 days. Without, it ends with
    #: the browser, and after twelve hours at the latest.
    remember: bool = True


class PasswordChangeIn(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


class LanguageIn(BaseModel):
    language: str = Field(max_length=16)


class ProfileIn(BaseModel):
    display_name: str = Field(max_length=200)


#: Longest display name, in characters.
DISPLAY_NAME_MAX = 80


def check_display_name(value: str) -> str:
    """Spaces gathered, no control or format characters, at most DISPLAY_NAME_MAX characters; empty shows the name.

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
    # The scheme of a trusted proxy is the request's already (``middleware.ForwardedProtoMiddleware``). Any other
    # proxy's word only ever makes the cookie stricter, as before: its rightmost value, which that proxy wrote.
    return request.url.scheme == "https" or claims_https(request.scope.get("headers", []))


#: How long the browser keeps the cookie of a session that stays: as long as browsers allow (400 days). The server
#: decides when it ends: 30 days without use.
LONG_COOKIE_DAYS = 400


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


def fail(exc: AccountError) -> HTTPException:
    return error(exc.code, exc.message, exc.status)


def check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise error("password_too_short", f"Use at least {MIN_PASSWORD} characters.", 422, minimum=MIN_PASSWORD)


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


def account_view(account: AccountRow) -> dict[str, Any]:
    with SessionLocal() as db:
        keys = totp.passkey_count(db, account.id)
        pending = emails.pending_of(db, account.id)
    on = bool(account.totp_secret_enc) or keys > 0
    return {
        "id": account.id,
        "name": account.name,
        "display_name": account.display_name,
        # "What's new" (block X3): the running version and the one the account has read.
        "version": __version__,
        "whats_new_seen": account.whats_new_seen,
        "role": account.role,
        "sign_in": account.sign_in,
        "email": account.email,
        # Confirmed by a link sent to it (or by the provider); an address the operator typed is not.
        "email_confirmed": account.email_confirmed_at is not None,
        # A new address waiting for its link; the one in "email" stays until it is opened.
        "email_pending": pending,
        "language": account.language,
        # Linked to at least one sign-in provider (which ones: ``GET /api/v1/oidc/me``).
        "oidc_linked": _has_links(account.id),
        # A second factor of any kind: a code from an app (``totp``) or a passkey.
        "two_factor": on,
        "totp": bool(account.totp_secret_enc),
        "passkeys": keys,
        "two_factor_recovery_left": len(totp.load_recovery(account.totp_recovery)) if on else 0,
        "created_at": account.created_at.isoformat(),
        "last_seen_at": account.last_seen_at.isoformat() if account.last_seen_at else None,
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


def remember_device(request: Request, response: Response, account: AccountRow) -> bool:
    """This browser is known for the account from now on: a lock that strangers cause by guessing does not keep it
    out, and signing in from it again is no new sign-in. Gives whether it was known before."""
    current = request.cookies.get(DEVICE_COOKIE)
    known = account.id in devices_of(current)
    token = device_token(account.id, current)
    for path in OLD_DEVICE_PATHS:
        response.delete_cookie(DEVICE_COOKIE, path=path, httponly=True, samesite="lax", secure=secure_cookie(request))
    for path in DEVICE_PATHS:
        response.set_cookie(DEVICE_COOKIE, token, max_age=DEVICE_DAYS * 86400, httponly=True, samesite="lax",
                            secure=secure_cookie(request), path=path)
    return known


def start(
    db: DbSession, request: Request, response: Response, account: AccountRow, *, remember: bool = True,
    by_provider: bool = False,
) -> str:
    """The session of a sign-in that went through, by any way; gives its stage.

    An account that must set up a second factor first gets a session that may do only that, for a quarter of an hour,
    and nothing else happens yet. A full session brings the cookies and, when this browser is new for the account, the
    notice to the other devices (``services/notices.py``). ``by_provider``: it came in through a provider whose entry
    checks the second factor itself; "require a second factor" does not send this session to set one up (Bauplan 01),
    and the session keeps that mark."""
    agent = request.headers.get("user-agent", "")
    account.second_factor_by_provider = by_provider
    if totp.setup_required(db, account):
        token = start_session(db, account, client_ip(request), agent, remember=remember, stage=STAGE_SETUP)
        _set_cookie(response, request, token, False)
        return STAGE_SETUP
    first = not account.signed_in_before
    account.signed_in_before = True
    known = remember_device(request, response, account)
    token = start_session(db, account, client_ip(request), agent, remember=remember,
                          second_factor_by_provider=by_provider)
    _set_cookie(response, request, token, remember)
    notices.new_sign_in(account, client_ip(request), agent, first=first, known=known)
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
    }


@router.post("/setup", summary="Create the operator account")
def setup(payload: SetupIn, request: Request, response: Response, db: DbSession) -> dict[str, Any]:
    key = "setup:" + client_ip(request)
    address_guard(request, key)
    check_password(payload.password)
    language = check_language(payload.language)
    try:
        account = accounts.create_operator(db, payload.name, payload.password, payload.code)
    except AccountError as exc:
        if exc.code == "setup_code_wrong":
            address_failed(request, key)
            logger.warning("Setup refused: wrong setup code")
        raise fail(exc) from exc
    account.language = language
    # The kinds that come with nexpaper in the language of the one who sets it up (renamed ones stay as they are).
    catalog.name_kinds_for(db, language or interface_language(request))
    db.commit()
    return sign_in(db, request, response, account)


@router.get("/auth/methods", summary="How one can sign in here (no sign-in needed)")
def methods(request: Request, db: DbSession) -> dict[str, Any]:
    from ..services import passkeys
    from ..vendor.nexoidc import providers

    values = settings_service.get_all(db)
    return {
        "password": bool(values["password_login"]),
        # A button per active sign-in provider, in the operator's order: slug and label, nothing else (the same as
        # ``GET /api/v1/oidc/providers``).
        "providers": providers.public_list(oidc_store.SqlStore(db)),
        # Passkeys work under the public https address, or on localhost.
        "passkeys": passkeys.available(db, request.url.hostname),
        # "Forgot your password?" where a mail goes out and the link has a public address to point to.
        "forgot": bool(values["password_login"]) and resets.available(db),
        # How long "stay signed in" lasts without use (NEXPAPER_SESSION_DAYS): the sign-in page says it before anybody
        # is signed in, and the list of devices says it after.
        "session_days": get_settings().session_days,
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


@router.post("/auth/login", summary="Sign in with name and password")
def login(payload: LoginIn, request: Request, response: Response, db: DbSession) -> dict[str, Any]:
    # The brake first, then the password, then the rules: an unknown name costs the time of a wrong password, so
    # neither the answer nor its timing tells which names exist.
    #
    # Five failures per address, whatever the name (``deps.address_guard``); a sign-in that works does not reset that.
    address_guard(request)
    try:
        account = accounts.authenticate(db, payload.name, payload.password,
                                        devices_of(request.cookies.get(DEVICE_COOKIE)))
    except AccountError as exc:
        address_failed(request)
        raise fail(exc) from exc
    if not settings_service.get(db, "password_login") and account.role != OPERATOR:
        # The operator keeps the password as the way in when the provider is down.
        raise error("password_login_off", "Sign-in with a password is turned off.", 403)
    if totp.has_second_factor(db, account):
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
    row = db.get(AccountRow, account.id)
    assert row is not None
    codes = totp.generate_recovery_codes()
    row.totp_recovery = totp.recovery_hashes(codes)
    db.commit()
    logger.info("Recovery codes made again during the setup name=%s", row.name)
    return {"recovery_codes": codes}


@router.post("/auth/logout", status_code=204, summary="Sign out in this browser")
def logout(request: Request, response: Response, db: DbSession) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    account = session_account(db, token)
    end_session(db, token)
    if account is not None:
        logger.info("Signed out name=%s", account.name)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.post("/auth/logout-all", status_code=204, summary="Sign out every other browser of the own account")
def logout_everywhere(request: Request, account: BrowserAccount, db: DbSession) -> None:
    end_all_sessions(db, account.id, except_token=request.cookies.get(SESSION_COOKIE))
    logger.info("All other sessions ended by their owner name=%s", account.name)


@router.get("/auth/me", summary="The signed-in account, and what this server offers it")
def me(request: Request, account: Account, db: DbSession) -> dict[str, Any]:
    stage = session_of(request).stage
    return {
        **account_view(account),
        "mail": mailer.configured(db),
        "session_stage": stage,
        "second_factor_setup_required": stage != STAGE_FULL or totp.setup_required(db, account),
        "second_factor_required": bool(settings_service.get(db, "two_factor_required"))
        and not totp.provider_checks(db, account),
        # This session came in through a provider that checks the second factor, and the account (with a password)
        # has none of its own: its device tokens and API keys wait until it sets one up (they have no provider behind
        # them). Making one stays possible; the page says so beside them.
        "keys_wait_for_second_factor": bool(account.second_factor_by_provider) and totp.keys_wait(db, account),
    }


# --- The own signed-in devices ----------------------------------------------------------------------------------------


def _session_view(row: AuthSession, here: str, language: str) -> dict[str, Any]:
    return {
        "id": row.uid,
        "device": notices.device_name(row.user_agent, language),
        "phone": notices.system_of(row.user_agent or "") in ("iPhone", "Android"),
        "network": notices.network_of(row.ip, language),
        "created_at": row.created_at.isoformat(),
        "last_seen_at": row.last_seen_at.isoformat(),
        "remember": row.remember,
        "here": row.uid == here,
    }


@router.get("/auth/sessions", summary="Where the own account is signed in: device, network, last use")
def sessions(request: Request, account: Account, db: DbSession) -> list[dict[str, Any]]:
    here = session_of(request).uid
    language = interface_language(request) or account.language
    rows = db.scalars(
        select(AuthSession)
        .where(AuthSession.account_id == account.id, AuthSession.stage == STAGE_FULL,
               AuthSession.expires_at > clock.now())
        .order_by(AuthSession.last_seen_at.desc())
    )
    found = [_session_view(row, here, language) for row in rows]
    # This device first, then the others by their last use.
    return sorted(found, key=lambda item: not item["here"])


SessionUid = Annotated[str, Path(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")]


@router.delete("/auth/sessions/{uid}", status_code=204, summary="Sign out one of the own devices")
def end_one(uid: SessionUid, request: Request, account: BrowserAccount, db: DbSession) -> None:
    if uid == session_of(request).uid:
        raise error("this_session", "To sign out here, use Sign out.", 409)
    # Only a session of the own account: another account's looks exactly like one that does not exist.
    gone = db.execute(delete(AuthSession).where(AuthSession.uid == uid, AuthSession.account_id == account.id))
    db.commit()
    if not int(getattr(gone, "rowcount", 0) or 0):
        raise error("not_found", "No such session.", 404)
    logger.info("A device signed out by its owner name=%s", account.name)


@router.put("/auth/password", status_code=204, summary="Change the own password")
def change_password(payload: PasswordChangeIn, request: Request, account: BrowserAccount, db: DbSession) -> None:
    row = db.get(AccountRow, account.id)
    assert row is not None
    if row.sign_in != SIGN_IN_PASSWORD:
        raise error("oidc_account", "This account signs in through OIDC.", 409)
    check_password(payload.new)
    reauth_guard(request, row)
    try:
        accounts.change_password(db, row, payload.current, payload.new)
    except AccountError as exc:
        if exc.code == "wrong_password":
            reauth_failed(request, db, row)
        raise fail(exc) from exc
    reauth_succeeded(request, db, row)
    # Other browsers must sign in again; this one stays.
    end_all_sessions(db, row.id, except_token=request.cookies.get(SESSION_COOKIE))
    logger.info("Password changed, every other session ended name=%s", row.name)


@router.put("/me/profile", summary="The own display name; empty shows the name")
def set_profile(payload: ProfileIn, account: Account, db: DbSession) -> dict[str, Any]:
    row = db.get(AccountRow, account.id)
    assert row is not None
    shown = check_display_name(payload.display_name)
    if shown and _taken_by_another(db, row.id, shown):
        # Nobody shows up as somebody else: not under another account's name, nor its display name.
        raise error("display_name_taken", "Another account goes by this name.", 409)
    row.display_name = shown
    db.commit()
    return account_view(row)


def _taken_by_another(db: DbSession, own_id: int, shown: str) -> bool:
    folded = unicodedata.normalize("NFKC", shown).casefold()
    for other_id, name, display in db.execute(select(AccountRow.id, AccountRow.name, AccountRow.display_name)):
        if other_id == own_id:
            continue
        for taken in (name, display):
            if taken and unicodedata.normalize("NFKC", taken).casefold() == folded:
                return True
    return False


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
def list_accounts(_operator: OperatorAccount, db: DbSession) -> list[dict[str, Any]]:
    # Never what a person chose for themselves either: when they are reminded, their time zone, their looks.
    return [
        {**{key: value for key, value in account_view(row).items() if key != "profile"},
         "locked": accounts.is_locked(row), "blocked": row.blocked_at is not None,
         "has_password": bool(row.password_hash)}
        for row in db.scalars(select(AccountRow).order_by(AccountRow.created_at))
    ]


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


@router.delete("/accounts/{account_id}", status_code=204, summary="Delete an account")
def delete_account(
    account_id: int, payload: AccountDeleteIn, request: Request, operator: OperatorAccount, db: DbSession,
) -> None:
    """Everything that belongs to the account goes with it. The documents of its own vault go where ``documents``
    says; without a choice, a vault with documents answers 409 with their number. One transaction: a refusal changes
    nothing."""
    confirm_operator(request, db, operator, payload.current_password)
    if account_id == operator.id:
        raise error("cannot_delete_self", "You cannot delete your own account.", 409)
    row = _row(db, account_id)
    name = row.name
    if payload.confirm_name.strip() != name:
        raise error("name_mismatch", "Type the name of the account to delete it.", 422)
    held = vaults_service.before_account_delete(
        db, account_id, choice=payload.documents, target_user=payload.target_user_id,
        target_vault=payload.target_vault_id, by=operator.id, account_name=name,
    )
    # The database takes what hangs on the account with it (ON DELETE CASCADE): sessions, passkeys, keys, devices, its
    # links to sign-in providers. The way back to 1.0.1 follows in the same commit (its subject leaves the old column).
    db.delete(row)
    oidc_store.way_back_changed(db)
    db.commit()
    totp.forget_account(account_id)
    logger.warning("Account deleted name=%s by=%s documents=%s choice=%s", name, operator.name, held,
                   payload.documents if held else "-")


@router.post("/accounts/{account_id}/sign-out", status_code=204, summary="End every session of an account")
def sign_out_account(account_id: int, operator: OperatorAccount, db: DbSession) -> None:
    row = _row(db, account_id)
    end_all_sessions(db, row.id)
    logger.warning("All sessions ended name=%s by=%s", row.name, operator.name)


@router.post("/accounts/{account_id}/block", status_code=204, summary="Block an account (its sessions end)")
def block_account(
    account_id: int, payload: OperatorConfirmIn, request: Request, operator: OperatorAccount, db: DbSession,
) -> None:
    """Blocked, the account gets in nowhere: its sessions end, its tokens stop working."""
    confirm_operator(request, db, operator, payload.current_password)
    if account_id == operator.id:
        raise error("cannot_block_self", "You cannot block yourself.", 409)
    row = _row(db, account_id)
    row.blocked_at = utcnow()
    db.commit()
    end_all_sessions(db, row.id)
    logger.warning("Account blocked name=%s by=%s", row.name, operator.name)


@router.post("/accounts/{account_id}/unblock", status_code=204, summary="Let a blocked account in again")
def unblock_account(
    account_id: int, payload: OperatorConfirmIn, request: Request, operator: OperatorAccount, db: DbSession,
) -> None:
    confirm_operator(request, db, operator, payload.current_password)
    row = _row(db, account_id)
    row.blocked_at = None
    db.commit()
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
        for key, value in changes.items():
            setattr(row, key, value)
        db.commit()
        logger.warning("Permissions changed name=%s %s by=%s", row.name,
                       " ".join(f"{key}={'yes' if value else 'no'}" for key, value in sorted(changes.items())),
                       operator.name)
    return {key: bool(getattr(row, key)) for key in ("ai_allowed",)}


@router.put("/accounts/{account_id}/role", summary="Make an account operator or member")
def set_role(
    account_id: int, payload: RoleIn, request: Request, operator: OperatorAccount, db: DbSession,
) -> dict[str, Any]:
    confirm_operator(request, db, operator, payload.current_password)
    if payload.role not in ROLES:
        raise error("invalid_role", "Unknown role.", 422)
    row = _row(db, account_id)
    if row.id == operator.id and payload.role != OPERATOR:
        raise error("cannot_demote_self", "You cannot take the operator role from yourself.", 409)
    row.role = payload.role
    db.commit()
    logger.warning("Role changed name=%s role=%s by=%s", row.name, payload.role, operator.name)
    return account_view(row)
