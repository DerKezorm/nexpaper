"""Connecting two nex apps, both sides in one place (decision V3: both directions are one connection).

The app where the account clicks "Mit <partner> verbinden" **starts** (``start``): it checks the partner's description,
keeps a ``state`` and a PKCE verifier, and sends the browser to the partner's consent page. The partner **asks**
(``consent_info``, ``consent``): it checks the app that asks by its own description (the return address must be that
app's ``/connect/return``), shows what each side may do at the other, and answers with a code. Back at the start
(``come_back``) the app trades the code at the partner's ``/api/connect/token`` and hands over, in the same request,
the tokens it made for the partner. So each side holds an access and a refresh token of the other, and keeps only
hashes of what it gave; a side that uses nothing still holds one, which opens the module's ``hello`` and ``revoke``.

Afterwards a side **calls** the other with ``call`` (fresh access on its own, the state of the card kept up to date),
and the other **checks** the token with ``authenticate``. Either side **ends** it with ``disconnect``: the partner
hears it at ``/api/connect/revoke`` and drops its side too; while it cannot be reached, the revocation waits
(``retry_waiting``)."""

from __future__ import annotations

import json
import logging
import secrets
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

from . import reach
from .config import CONSENT_PAGE, PREFIX, PROTOCOL, RETURN_PAGE, WELL_KNOWN, AppConfig
from .errors import GrantError, Refused
from .model import AccountId, Caller, Code, Connection, Pending
from .shared import BRAKE, oauthcore

logger = logging.getLogger("nexverbinden")

#: An access token is refreshed when it ends within this.
REFRESH_EARLY = timedelta(seconds=60)
#: "Last used" is written at most once a minute.
TOUCH_EVERY = timedelta(seconds=60)
MAX_STATE = 500
MAX_TOKEN = 300
MAX_NAME = 200
#: Since 0.2.1: how long this process remembers a refresh (both ways) beside the app's tables.
RENEWALS_KEPT = timedelta(hours=1)
#: The longest chain of refreshes followed from an older view of a connection.
_CHAIN = 20


@dataclass(frozen=True)
class _Issued:
    """A refresh this app answered (the side that is asked): what it gave in place of a spent refresh token."""

    connection_id: str
    access_hash: str
    refresh_hash: str
    access_expires: datetime
    #: The new access and refresh token, sealed by the app, for the same answer once more within the grace (BS2).
    sealed: str
    at: datetime


class Renewals:
    """Since 0.2.1 (BS1, BS2): what this process knows of the last refreshes of its connections, beside the app's
    tables.

    * A **lock** per connection: two requests of the app that find the token run out at the same moment refresh it
      once; the second takes what the first got (before, both brought the same refresh token and the partner ended the
      connection as copied).
    * The **latest tokens**: an app's ``Store`` may give a view of a connection read before another request of the same
      process refreshed it (a session that keeps what it read). Every save of the module puts the latest tokens it
      knows into such a view, so an older view never brings back a spent refresh token.
    * The **grace** (``AppConfig.refresh_grace``): the side that is asked answers a refresh token it spent within that
      time once more with the same tokens, while they are still the connection's (an answer lost on the way, two
      requests of the holder at once). Brought later, or after the connection was refreshed again, it is a copy as
      before and ends the connection.

    Nothing of it goes into the app's tables; a restart forgets it (then a token brought twice ends the connection as
    before 0.2.1)."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[tuple[str, str], threading.Lock] = {}
        #: The holder's side: the digest of a refresh token traded -> the sealed ``held`` it brought, and when.
        self._held: dict[str, tuple[str, datetime]] = {}
        #: The side that is asked: the digest of a refresh token spent -> what was given in its place.
        self._issued: dict[str, _Issued] = {}

    def lock(self, app: str, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault((app, key), threading.Lock())

    def _prune(self, now: datetime) -> None:
        self._held = {key: kept for key, kept in self._held.items() if now - kept[1] <= RENEWALS_KEPT}
        self._issued = {key: kept for key, kept in self._issued.items() if now - kept.at <= RENEWALS_KEPT}

    def renewed(self, spent: str, sealed_held: str, now: datetime) -> None:
        with self._guard:
            self._prune(now)
            self._held[spent] = (sealed_held, now)

    def issued(self, spent: str, given: _Issued) -> None:
        with self._guard:
            self._prune(given.at)
            self._issued[spent] = given

    def given_for(self, spent: str) -> _Issued | None:
        with self._guard:
            return self._issued.get(spent)

    def latest(self, store: Any, connection: Connection) -> Connection:
        """``connection`` with the latest tokens this process gave and got for it, where the view is older."""
        with self._guard:
            held, issued = dict(self._held), dict(self._issued)
        if not held and not issued:
            return connection
        changed = connection
        for _ in range(_CHAIN):
            given = issued.get(changed.issued_refresh_hash)
            if given is None or given.connection_id != changed.id:
                break
            changed = replace(
                changed,
                issued_access_hash=given.access_hash,
                issued_refresh_hash=given.refresh_hash,
                issued_access_expires=given.access_expires,
            )
        if held:
            for _ in range(_CHAIN):
                try:
                    spent = oauthcore.digest(json.loads(store.unseal(changed.held))["refresh"])
                except (ValueError, KeyError, TypeError):
                    break
                if spent not in held:
                    break
                changed = replace(changed, held=held[spent][0])
        return changed

    def forget(self) -> None:
        """For tests: as after a restart."""
        with self._guard:
            self._held.clear()
            self._issued.clear()


RENEWALS = Renewals()


def _save(store: Any, connection: Connection) -> Connection:
    """Saves a connection that exists already, with the latest tokens this process knows (BS1)."""
    latest = RENEWALS.latest(store, connection)
    store.save(latest)
    return latest


def connections_on(store: Any) -> bool:
    """Decision V1 (7a): the operator's own switch, on unless switched off."""
    return store.setting("connections") is not False


def _base(base: str) -> str:
    return base.strip().rstrip("/")


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


# --- the description of an app ----------------------------------------------------------------------------------------


def describe(config: AppConfig, store: Any) -> dict[str, Any]:
    """``GET /.well-known/nex-app``: who answers here, and whether it connects now."""
    return {
        "app": config.app_name,
        "version": config.version,
        "protocol": PROTOCOL,
        "connect": connections_on(store),
        "consent": CONSENT_PAGE,
        "return": RETURN_PAGE,
        "token": f"{PREFIX}/token",
        "revoke": f"{PREFIX}/revoke",
    }


def _ask(config: AppConfig, store: Any, base: str, method: str, path: str, **sent: Any) -> reach.Answer:
    seconds = sent.pop("seconds", config.seconds)
    return reach.ask(
        base,
        method,
        path,
        local_allowed=bool(store.local_allowed()),
        agent=config.user_agent,
        seconds=seconds,
        connect_seconds=min(config.connect_seconds, seconds),
        limit=config.max_answer,
        **sent,
    )


def unreachable(failure: reach.Unreachable) -> Refused:
    """Since 0.1.8 (B2): ``local_off`` where the address lies in the own network and the operator has not allowed it
    (the account learns who can change that, and where), else ``unreachable``."""
    return Refused("local_off" if failure.local else "unreachable")


def partner_description(config: AppConfig, store: Any, base: str) -> dict[str, Any]:
    """The description at ``base``, checked: ``partner_too_old`` without one, ``unreachable`` when nothing came,
    ``local_off`` when the address lies in the own network and the operator has not allowed that (0.1.8, B2)."""
    try:
        answer = _ask(config, store, base, "GET", WELL_KNOWN, seconds=config.describe_seconds)
    except reach.Unreachable as failure:
        raise unreachable(failure) from None
    data = answer.data
    if answer.status != 200 or not isinstance(data, dict) or not isinstance(data.get("app"), str):
        raise Refused("partner_too_old")
    if not isinstance(data.get("protocol"), int) or data["protocol"] < PROTOCOL:
        raise Refused("partner_too_old")
    return data


# --- the side that starts ---------------------------------------------------------------------------------------------


def _own_areas(store: Any, account_id: AccountId, chosen: Any) -> list[Any] | None:
    """``None`` (all, also later ones) or a non-empty part of the account's areas, in the app's order."""
    if chosen is None:
        return None
    own = {str(area["id"]): area["id"] for area in store.areas(account_id)}
    if not isinstance(chosen, list) or not chosen or not {str(area) for area in chosen} <= set(own):
        raise Refused("areas_invalid")
    wanted = {str(area) for area in chosen}
    return [own[key] for key in own if key in wanted]


def operator_address(store: Any, partner: str) -> str:
    """The address of ``partner`` the operator set under Server › Verbindungen › Andere nex-Apps ("" where none)."""
    addresses = store.setting("addresses")
    return str(addresses.get(partner) or "") if isinstance(addresses, dict) else ""


def check_address(config: AppConfig, store: Any, partner: str, address: str) -> dict[str, Any]:
    """Decision V57 (B11, decided 27.11.2026): what answers at the address the operator gave for ``partner``, said at
    the field: ``found`` (``ok``, with the app's name and version), ``partner_off`` (the right app, its operator has
    switched connections off; ``ok`` as well), ``name_unknown``, ``unreachable``, ``local_off`` (the operator here has
    not allowed the own network), ``address_refused``, ``wrong_app`` (with the name of the app that answered),
    ``partner_too_old`` (no description). The address is kept either way (the partner may be off right now); only the
    operator sees this, so the reason may be named (the account's card never says more than "nicht erreichbar")."""
    try:
        answer = _ask(config, store, address, "GET", WELL_KNOWN, seconds=config.describe_seconds)
    except Refused as refusal:
        return {"ok": False, "code": refusal.code, "app": None, "version": None}
    except reach.Unreachable as failure:
        why = failure.args[0] if failure.args else ""
        code = {"local": "local_off", "name": "name_unknown", "refused": "address_refused"}.get(why, "unreachable")
        return {"ok": False, "code": code, "app": None, "version": None}
    data = answer.data if isinstance(answer.data, dict) else {}
    app = _text(data.get("app"), 40) or None
    version = _text(data.get("version"), 40) or None
    if answer.status != 200 or app is None:
        return {"ok": False, "code": "partner_too_old", "app": None, "version": None}
    if app != partner:
        return {"ok": False, "code": "wrong_app", "app": app, "version": version}
    if not isinstance(data.get("protocol"), int) or data["protocol"] < PROTOCOL:
        return {"ok": False, "code": "partner_too_old", "app": app, "version": version}
    code = "partner_off" if data.get("connect") is False else "found"
    return {"ok": True, "code": code, "app": app, "version": version}


# --- suggestions of addresses (B16) -----------------------------------------------------------------------------------

#: Since 0.2.0 (B16, V58): the setting in which the operator's suggestions are kept (``Store.setting``), and the most
#: addresses one side passes on.
SUGGESTIONS = "suggestions"
MAX_KNOWN = 16


def known_addresses(config: AppConfig, store: Any, own_base: str, other: str) -> dict[str, str]:
    """Decision V58 (B16, decided 27.11.2026): the addresses of nex apps this side knows, passed on to ``other`` as
    suggestions when the two connect: the operator's addresses of the apps ``other`` connects with, and this app's own
    (the way of connecting has proved it). Never ``other`` itself, never an address an account typed in."""
    wanted = set(config.catalog.partners(other))
    found: dict[str, str] = {}
    if config.app_name in wanted:
        found[config.app_name] = _base(own_base)
    for partner in config.partners:
        address = operator_address(store, partner)
        if partner in wanted and partner != other and address:
            found[partner] = address
    return found


def _kept_suggestions(store: Any) -> dict[str, dict[str, str]] | None:
    """The suggestions kept so far, or ``None`` where the app's ``Store`` keeps no setting ``suggestions`` (an app not
    updated to 0.2.0: the suggestions are left out, nothing else changes)."""
    try:
        found = store.setting(SUGGESTIONS)
    except Exception:  # an app whose settings know only the names of before 0.2.0
        return None
    if not isinstance(found, dict):
        return {}
    return {
        str(partner): {"address": str(entry["address"]), "from": str(entry.get("from") or "")}
        for partner, entry in found.items()
        if isinstance(entry, dict) and isinstance(entry.get("address"), str)
    }


def keep_suggestions(store: Any, config: AppConfig, raw: Any, source: str) -> int:
    """V58 (B16): the addresses ``source`` passed on, kept as suggestions for the operator, never as addresses (the
    operator takes each with a click, after it was checked like a typed one, V57). Only apps this one connects with,
    without an address of the operator here, in a clean form. The number of new ones."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return 0
    if not isinstance(raw, dict):
        return 0
    kept = _kept_suggestions(store)
    if kept is None:
        return 0
    added = 0
    for partner, address in list(raw.items())[:MAX_KNOWN]:
        if partner not in config.partners or not isinstance(address, str) or operator_address(store, partner):
            continue
        try:
            url = reach.clean_url(address)
        except Refused:
            continue
        if kept.get(partner, {}).get("address") == url:
            continue
        kept[partner] = {"address": url, "from": source}
        added += 1
    if added:
        store.set_setting(SUGGESTIONS, kept)
        logger.info("%s suggested %s address(es) of other nex apps", source, added)
    return added


def suggestions(store: Any, config: AppConfig) -> list[dict[str, str]]:
    """V58: the suggestions the operator sees under Server › Verbindungen › Andere nex-Apps, in the order of the
    catalog; one for an app that has an address meanwhile is left out."""
    kept = _kept_suggestions(store) or {}
    return [
        {"partner": partner, **kept[partner]}
        for partner in config.partners
        if partner in kept and not operator_address(store, partner)
    ]


def drop_suggestion(store: Any, partner: str) -> bool:
    """V58: a suggestion taken over or turned down by the operator goes."""
    kept = _kept_suggestions(store)
    if not kept or partner not in kept:
        return False
    del kept[partner]
    store.set_setting(SUGGESTIONS, kept)
    return True


def partner_address(store: Any, account_id: AccountId, partner: str) -> str:
    """Decision V42 (B3, decided 27.11.2026): where the account connects with ``partner``. Only the operator sets the
    other apps up; the account types no address. A connection there is (also one made with an address typed in before
    0.1.8) and an older one by API key keep their own address, so that they go on as they are and "Neu verbinden"
    reaches the same app; else the operator's. "" where there is none: the app is not set up on this server."""
    connection = store.connection(account_id, partner)
    if connection is not None:
        return connection.partner_base
    legacy = next((row for row in store.legacy(account_id) if row.partner == partner), None)
    if legacy is not None and legacy.partner_base:
        return legacy.partner_base
    return operator_address(store, partner)


def start(
    store: Any,
    config: AppConfig,
    account_id: AccountId,
    partner: str,
    base: str,
    now: datetime,
    *,
    areas: Any = None,
) -> str:
    """The account clicked "Mit <partner> verbinden": the address of the partner's consent page to send it to. Since
    0.1.8 (V42) the address is the operator's (or the one of the connection there is), never one the account types."""
    if not connections_on(store):
        raise Refused("connections_off")
    if partner not in config.usable:
        raise Refused("partner_unknown")
    address = partner_address(store, account_id, partner)
    if not address:
        raise Refused("partner_not_set_up")
    url = reach.clean_url(address)
    # Only what goes out counts: a mistyped address costs nothing.
    if not BRAKE.take(f"verbinden:start:{account_id}", config.starts_per_minute):
        raise Refused("slow_down")
    found = partner_description(config, store, url)
    if found["app"] != partner:
        raise Refused("wrong_app")
    if found.get("connect") is False:
        raise Refused("partner_off")
    granted = _own_areas(store, account_id, areas)
    verifier = oauthcore.new_verifier()
    state = secrets.token_urlsafe(32)
    store.add_pending(
        Pending(
            state_hash=oauthcore.digest(state),
            account_id=account_id,
            partner=partner,
            partner_base=url,
            verifier=store.seal(verifier),
            areas_granted=granted,
            created_at=now,
        )
    )
    store.commit()
    own = _base(base)
    logger.info("connection with %s started", partner)
    query = {
        "client_id": own,
        "redirect_uri": own + RETURN_PAGE,
        "state": state,
        "code_challenge": oauthcore.challenge_of(verifier),
        "code_challenge_method": "S256",
    }
    return f"{url}{CONSENT_PAGE}?{urlencode(query)}"


def _areas_named(store: Any, account_id: AccountId, chosen: list[Any] | None) -> list[dict[str, Any]] | None:
    if chosen is None:
        return None
    keys = {str(area) for area in chosen}
    return [{"id": area["id"], "name": area["name"]} for area in store.areas(account_id) if str(area["id"]) in keys]


def _held(store: Any, access: str, refresh: str, expires: datetime, own_base: str) -> str:
    return store.seal(
        json.dumps({"access": access, "refresh": refresh, "expires": expires.isoformat(), "own": own_base})
    )


def _text(value: Any, size: int) -> str:
    return value if isinstance(value, str) and 0 < len(value) <= size else ""


def come_back(
    store: Any,
    config: AppConfig,
    account_id: AccountId,
    code: str,
    state: str,
    iss: str,
    base: str,
    now: datetime,
) -> Connection:
    """The browser is back from the partner's consent page: trade the code, hand over the partner's tokens, keep
    both."""
    pending = store.take_pending(oauthcore.digest(state or ""))
    store.commit()
    if (
        pending is None
        or pending.account_id != account_id
        or now - pending.created_at > timedelta(minutes=config.code_minutes)
        or (iss and not reach.same_place(iss, pending.partner_base))
        or not _text(code, MAX_TOKEN)
    ):
        # Since 0.1.8 (B6): the card of the partner shows it, where the return belongs to one started here.
        mine = pending is not None and pending.account_id == account_id
        raise Refused("return_invalid", **({"partner": pending.partner} if mine and pending else {}))
    own = _base(base)
    theirs = oauthcore.new_tokens(config.access_prefix, config.refresh_prefix, config.access_hours, now)
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": store.unseal(pending.verifier),
        "client_id": own,
        "redirect_uri": own + RETURN_PAGE,
        "reverse_access": theirs.access,
        "reverse_refresh": theirs.refresh,
        "reverse_expires_in": str(config.access_hours * 3600),
        "reverse_account": account_shown(store, account_id),
        "reverse_areas": json.dumps(_areas_named(store, account_id, pending.areas_granted)),
        "reverse_version": config.version,
        # Since 0.2.0 (B16, V58): the addresses of other nex apps known here, a suggestion for the partner's operator.
        "reverse_known": json.dumps(known_addresses(config, store, own, pending.partner)),
    }
    try:
        answer = _ask(config, store, pending.partner_base, "POST", f"{PREFIX}/token", form=form)
    except reach.Unreachable as failure:
        raise Refused(unreachable(failure).code, partner=pending.partner) from None
    data = answer.data if isinstance(answer.data, dict) else {}
    if answer.status != 200:
        logger.info("%s did not confirm the connection (%s)", pending.partner, answer.code or answer.status)
        raise Refused("partner_off" if answer.code == "connections_off" else "consent_failed", partner=pending.partner)
    access, refresh = _text(data.get("access_token"), MAX_TOKEN), _text(data.get("refresh_token"), MAX_TOKEN)
    connection_id = _text(data.get("connection_id"), 100)
    lasts = data.get("expires_in")
    if not access or not refresh or not connection_id or not isinstance(lasts, int) or not 60 <= lasts <= 86400:
        raise Refused("consent_failed", partner=pending.partner)
    areas_used = data.get("areas")
    earlier = store.connection(account_id, pending.partner)
    if earlier is not None:
        _end(store, config, earlier, now)
    made = Connection(
        id=connection_id,
        account_id=account_id,
        partner=pending.partner,
        partner_base=pending.partner_base,
        partner_account=_text(data.get("account"), MAX_NAME) or "?",
        uses=config.catalog.uses(config.app_name, pending.partner),
        grants=config.catalog.uses(pending.partner, config.app_name),
        areas_granted=pending.areas_granted,
        areas_used=_area_list(areas_used),
        held=_held(store, access, refresh, now + timedelta(seconds=lasts), own),
        issued_access_hash=theirs.access_hash,
        issued_refresh_hash=theirs.refresh_hash,
        issued_access_expires=theirs.access_expires,
        created_at=now,
        used_at=now,
        ok_at=now,
        partner_version=_text(data.get("version"), 40),
    )
    store.save(made)
    keep_suggestions(store, config, data.get("known"), pending.partner)
    store.commit()
    logger.info("connected with %s connection=%s", pending.partner, made.id)
    # The older connection by API key with the partner ends in the route (``api``), after its key retired itself there.
    return made


#: Since 0.1.8 (B6): what another app may send back with ``error`` from its consent page, and what the card here says.
#: ``access_denied`` is the account's no (RFC 6749); the others are the module's own (``way_back`` on the other side).
CAME_BACK = {
    "access_denied": "declined",
    "partner_off": "partner_off",
    "partner_local_off": "partner_local_off",
    "partner_cannot_reach": "partner_cannot_reach",
    "connections_off": "connections_off",
    "consent_failed": "consent_failed",
}


def came_back_refused(store: Any, account_id: AccountId, error: str, state: str) -> Refused:
    """Decision V47 (B6): the browser is back from the partner's consent page with ``error`` instead of a code: the
    refusal for the card of the partner where "Verbinden" was clicked (``partner`` in it where the ``state`` belongs to
    a connection this account started here; the start is used up). Anything not in ``CAME_BACK`` says
    ``consent_failed``. Since 0.2.0 (B9, V56): a no leaves nothing connected, an older connection by API key with the
    partner ends as well (``forget_legacy``)."""
    pending = store.take_pending(oauthcore.digest(state or ""))
    store.commit()
    code = CAME_BACK.get(str(error), "consent_failed")
    if pending is None or pending.account_id != account_id:
        return Refused(code)
    logger.info("connection with %s not made (%s)", pending.partner, code)
    if code == "declined" and forget_legacy(store, account_id, pending.partner):
        store.commit()
    return Refused(code, partner=pending.partner)


def _area_list(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    return [
        {"id": area.get("id"), "name": str(area.get("name"))[:MAX_NAME]}
        for area in raw[:500]
        if isinstance(area, dict) and "id" in area
    ]


# --- the side that is asked: consent ---------------------------------------------------------------------------------


def _checked_asker(store: Any, config: AppConfig, params: dict[str, Any], base: str) -> tuple[str, str, str]:
    """The app that asks (its name, its address) and its return address, checked; or ``Refused``."""
    if not connections_on(store):
        raise Refused("connections_off")
    try:
        client = reach.clean_url(str(params.get("client_id") or ""))
    except Refused:
        raise Refused("client_invalid") from None
    redirect = str(params.get("redirect_uri") or "")
    own_scheme = urlsplit(_base(base)).scheme
    host = urlsplit(client).hostname or ""
    http_hosts = (*oauthcore.LOOPBACK, host) if own_scheme == "http" else oauthcore.LOOPBACK
    if redirect != client + RETURN_PAGE or not oauthcore.valid_redirect(redirect, http_hosts=http_hosts):
        raise Refused("redirect_invalid")
    challenge = str(params.get("code_challenge") or "")
    if params.get("code_challenge_method") != "S256" or not oauthcore.VERIFIER.fullmatch(challenge):
        raise Refused("pkce_required")
    state = params.get("state")
    if not isinstance(state, str) or not 0 < len(state) <= MAX_STATE:
        raise Refused("client_invalid")
    found = partner_description(config, store, client)
    if found["app"] not in config.partners:
        raise Refused("client_invalid")
    if found.get("connect") is False:
        raise Refused("partner_off")
    return found["app"], client, redirect


def named(config: AppConfig, refusal: Refused) -> Refused:
    """Decision V59 (B14): a refusal the consent page shows itself names the app that refused (``app``), so that its
    words never start with an empty name ("… fragt Adressen im eigenen Netz erst …")."""
    return Refused(refusal.code, status=refusal.status, **{"app": config.app_name, **refusal.details})


#: Since 0.1.8 (B6): a refusal on this side, said as the app that asks understands it (its ``CAME_BACK``).
ECHO = {
    "connections_off": "partner_off",
    "local_off": "partner_local_off",
    "unreachable": "partner_cannot_reach",
    "partner_off": "connections_off",
}


def _known(store: Any, config: AppConfig, account_id: AccountId, client: str) -> bool:
    """Whether ``client`` is an app this side knows without asking it: the address the operator set for one of the
    partners, or the address of a connection (or an older one by API key) of this account."""
    places = [operator_address(store, partner) for partner in config.partners]
    places += [connection.partner_base for connection in store.connections(account_id)]
    places += [row.partner_base for row in store.legacy(account_id)]
    return any(place and reach.same_place(client, place) for place in places)


def way_back(
    store: Any, config: AppConfig, account_id: AccountId, params: dict[str, Any], base: str, refusal: Refused
) -> str | None:
    """Decision V47 (B6): where a refusal on the consent page goes, so that the account reads it in the card of the
    app where it clicked "Verbinden": that app's return address with ``error`` (``ECHO``), ``state`` and ``iss``. Only
    to an app this side knows (``_known``: the operator's address or a connection of the account), whose return is
    exactly ``<its address>/connect/return`` and a valid one; else ``None`` and the page says it itself."""
    try:
        client = reach.clean_url(str(params.get("client_id") or ""))
    except Refused:
        return None
    redirect = str(params.get("redirect_uri") or "")
    state = params.get("state")
    if not isinstance(state, str) or not 0 < len(state) <= MAX_STATE or redirect != client + RETURN_PAGE:
        return None
    own = _base(base)
    host = urlsplit(client).hostname or ""
    http_hosts = (*oauthcore.LOOPBACK, host) if urlsplit(own).scheme == "http" else oauthcore.LOOPBACK
    if not oauthcore.valid_redirect(redirect, http_hosts=http_hosts) or not _known(store, config, account_id, client):
        return None
    code = ECHO.get(refusal.code, "consent_failed")
    logger.info("connection asked for not possible here (%s), sent back", refusal.code)
    return oauthcore.back(redirect, {"error": code, "state": state, "iss": own})


#: The forms of a picture's address the consent page shows: the app's own route, a web address, a picture inline.
PICTURE_FORMS = ("/", "https://", "http://", "data:image/")


def account_card(store: Any, account_id: AccountId) -> dict[str, Any]:
    """Decision V43 (B1): who is signed in, for "Angemeldet als Kim Example (kim)" with the picture. The app's
    ``Store.account_card(account_id)`` (since 0.1.8, optional) gives ``name`` (the shown name), ``username``,
    ``picture`` (the address of the own picture, or none) and ``color`` (the app's colour of the person, or none);
    without it the account's name alone, as before."""
    plain = store.account_name(account_id)
    given = getattr(store, "account_card", None)
    found = given(account_id) if callable(given) else None
    found = found if isinstance(found, dict) else {}
    username = _text(found.get("username"), MAX_NAME) or plain
    name = _text(found.get("name"), MAX_NAME)
    picture = found.get("picture")
    shown = isinstance(picture, str) and 0 < len(picture) <= 2048 and picture.startswith(PICTURE_FORMS)
    picture = picture if shown else None
    color = found.get("color")
    color = color if isinstance(color, str) and 0 < len(color) <= 40 else None
    return {"name": name if name != username else "", "username": username, "picture": picture, "color": color}


def account_shown(store: Any, account_id: AccountId) -> str:
    """Decision V55 (27.11.2026): the name the other app keeps and shows for the linked account is written like
    on the consent page (V43), "Kim Example (kim)"; without a shown name of its own, the user name alone. Sent when
    connecting (``reverse_account``, ``account`` of the token answer) and with every check (``hello``), so connections
    made before take the new form at their next check."""
    card = account_card(store, account_id)
    shown = f"{card['name']} ({card['username']})" if card["name"] else card["username"]
    return shown if len(shown) <= MAX_NAME else card["username"][:MAX_NAME]


def _words_of(config: AppConfig, granted_by: str, purposes: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "id": purpose,
            "level": config.catalog.purpose(granted_by, purpose).level,
            "areas": config.catalog.purpose(granted_by, purpose).areas,
        }
        for purpose in purposes
    ]


def consent_info(store: Any, config: AppConfig, account_id: AccountId, params: dict[str, Any], base: str) -> dict:
    """What the consent page shows: the app that asks, what it may do here and what this app gets there. Since 0.1.8
    (B6): where the app that asks cannot connect here but has a safe way back (``way_back``), only ``{"back": …,
    "refused": <code>}``, and the page sends the browser there."""
    try:
        asker, client, _ = _checked_asker(store, config, params, base)
    except Refused as refusal:
        back = way_back(store, config, account_id, params, base, refusal)
        if back is None:
            raise named(config, refusal) from None
        return {"back": back, "refused": refusal.code}
    theirs = config.catalog.uses(asker, config.app_name)
    mine = config.catalog.uses(config.app_name, asker)
    with_areas = any(config.catalog.purpose(config.app_name, purpose).areas for purpose in theirs)
    return {
        "app": config.app_name,
        "partner": asker,
        "partner_host": urlsplit(client).netloc,
        "account": store.account_name(account_id),
        # Since 0.1.8 (B1): the shown name, the user name and the picture of the account.
        "account_card": account_card(store, account_id),
        "partner_may": _words_of(config, config.app_name, theirs),
        "app_may": _words_of(config, asker, mine),
        "areas": [{"id": area["id"], "name": area["name"]} for area in store.areas(account_id)] if with_areas else [],
        "replaces": store.connection(account_id, asker) is not None,
        # Since 0.1.13 (V53): which side sends the other a person when asking (the page says so).
        "partner_sends_person": _asks_person(config, config.app_name, theirs),
        "app_sends_person": _asks_person(config, asker, mine),
    }


def consent(
    store: Any, config: AppConfig, account_id: AccountId, body: dict[str, Any], base: str, now: datetime
) -> str:
    """The account's answer; the address to send the browser to (the asking app's return, with a code or a no; since
    0.1.8 with the error mark of a refusal where there is a safe way back, ``way_back``)."""
    try:
        asker, client, redirect = _checked_asker(store, config, body, base)
    except Refused as refusal:
        back = way_back(store, config, account_id, body, base, refusal)
        if back is None:
            raise named(config, refusal) from None
        return back
    state = str(body["state"])
    own = _base(base)
    if not body.get("allow"):
        logger.info("connection with %s declined", asker)
        # Since 0.2.0 (B9, V56): a no leaves nothing connected here either, also no older connection by API key.
        if forget_legacy(store, account_id, asker):
            store.commit()
        return oauthcore.back(redirect, {"error": "access_denied", "state": state, "iss": own})
    granted = _own_areas(store, account_id, body.get("areas"))
    code = config.code_prefix + secrets.token_urlsafe(32)
    store.add_code(
        Code(
            code_hash=oauthcore.digest(code),
            account_id=account_id,
            partner=asker,
            partner_base=client,
            redirect_uri=redirect,
            challenge=str(body["code_challenge"]),
            areas_granted=granted,
            expires_at=now + timedelta(minutes=config.code_minutes),
        )
    )
    store.commit()
    logger.info("connection with %s agreed", asker)
    return oauthcore.back(redirect, {"code": code, "state": state, "iss": own})


# --- the side that is asked: tokens ----------------------------------------------------------------------------------


def _answer(
    config: AppConfig,
    connection: Connection,
    access: str,
    refresh: str,
    store: Any,
    known: dict[str, str] | None = None,
    lasts: int | None = None,
) -> dict[str, Any]:
    found: dict[str, Any] = {} if known is None else {"known": known}
    return {
        **found,
        "connection_id": connection.id,
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "Bearer",
        "expires_in": config.access_hours * 3600 if lasts is None else lasts,
        "account": account_shown(store, connection.account_id),
        "areas": _areas_named(store, connection.account_id, connection.areas_granted),
        "app": config.app_name,
        "version": config.version,
    }


def token(
    store: Any,
    config: AppConfig,
    form: dict[str, str],
    base: str,
    now: datetime,
    *,
    traded: list[Connection] | None = None,
) -> dict[str, Any]:
    """``POST /api/connect/token``: a code traded (with the asking app's tokens for this one), or a refresh. Since
    0.2.1 (BS6) the connection a code made is added to ``traded`` (the routes call ``on_connected`` with it)."""
    if not connections_on(store):
        raise GrantError("connections_off", "Connections are switched off here.", 403)
    grant_type = form.get("grant_type", "")
    if grant_type == "authorization_code":
        return _trade(store, config, form, base, now, traded)
    if grant_type == "refresh_token":
        return _refresh(store, config, form, now)
    raise GrantError("unsupported_grant_type", "Only authorization_code and refresh_token.")


def _end_copy(store: Any, token_hash: str, what: str) -> None:
    """A spent code or refresh token brought again: somebody holds a copy, the connection ends."""
    connection_id = store.spent_by(token_hash)
    if connection_id is not None:
        store.remove(connection_id)
        store.commit()
        logger.warning("connection %s brought twice, connection ended connection=%s", what, connection_id)


def _trade(
    store: Any,
    config: AppConfig,
    form: dict[str, str],
    base: str,
    now: datetime,
    traded: list[Connection] | None = None,
) -> dict[str, Any]:
    code_hash = oauthcore.digest(form.get("code", ""))
    code = store.take_code(code_hash)
    store.commit()
    if code is None:
        _end_copy(store, code_hash, "code")
        raise GrantError("invalid_grant", "The code is not valid (any more).")
    if (
        code.expires_at <= now
        or not reach.same_place(form.get("client_id", ""), code.partner_base)
        or form.get("redirect_uri", "") != code.redirect_uri
        or not oauthcore.verifier_fits(form.get("code_verifier", ""), code.challenge)
    ):
        raise GrantError("invalid_grant", "The code is not valid (any more).")
    if not store.account_may(code.account_id):
        raise GrantError("account_resting", "The account may not connect now.")
    reverse_access, reverse_refresh = (
        _text(form.get("reverse_access"), MAX_TOKEN),
        _text(form.get("reverse_refresh"), MAX_TOKEN),
    )
    try:
        lasts = int(form.get("reverse_expires_in", ""))
        areas_used = json.loads(form.get("reverse_areas") or "null")
    except ValueError:
        raise GrantError("invalid_request", "The tokens for this app are missing.") from None
    if not reverse_access or not reverse_refresh or not 60 <= lasts <= 86400:
        raise GrantError("invalid_request", "The tokens for this app are missing.")
    earlier = store.connection(code.account_id, code.partner)
    if earlier is not None:
        # The asking app replaces its side as well: the earlier tokens on both sides end here.
        store.remove(earlier.id)
    made_tokens = oauthcore.new_tokens(config.access_prefix, config.refresh_prefix, config.access_hours, now)
    made = Connection(
        id=secrets.token_urlsafe(18),
        account_id=code.account_id,
        partner=code.partner,
        partner_base=code.partner_base,
        partner_account=_text(form.get("reverse_account"), MAX_NAME) or "?",
        uses=config.catalog.uses(config.app_name, code.partner),
        grants=config.catalog.uses(code.partner, config.app_name),
        areas_granted=code.areas_granted,
        areas_used=_area_list(areas_used),
        held=_held(store, reverse_access, reverse_refresh, now + timedelta(seconds=lasts), _base(base)),
        issued_access_hash=made_tokens.access_hash,
        issued_refresh_hash=made_tokens.refresh_hash,
        issued_access_expires=made_tokens.access_expires,
        created_at=now,
        used_at=now,
        ok_at=now,
        partner_version=_text(form.get("reverse_version"), 40),
    )
    store.save(made)
    store.spend(made.id, code_hash, config.spent_kept)
    # Since 0.2.0 (B9, V56): the connection by click takes the place of an older one by API key with the partner.
    forget_legacy(store, code.account_id, code.partner)
    # B16, V58: what the asking app knows of other nex apps, kept as suggestions for the operator here.
    keep_suggestions(store, config, form.get("reverse_known"), code.partner)
    store.commit()
    logger.info("connection with %s confirmed connection=%s", code.partner, made.id)
    if traded is not None:
        traded.append(made)
    known = known_addresses(config, store, base, code.partner)
    return _answer(config, made, made_tokens.access, made_tokens.refresh, store, known)


def _again(store: Any, config: AppConfig, form: dict[str, str], brought: str, now: datetime) -> dict[str, Any] | None:
    """Since 0.2.1 (BS2): a refresh token spent here within ``refresh_grace``, brought again while what was given for
    it is still the connection's: the same answer once more (the first got lost on the way, or two requests of the
    holder came at once). ``None`` where that does not hold (then it is a copy)."""
    given = RENEWALS.given_for(brought)
    if given is None or not timedelta(0) <= now - given.at <= timedelta(seconds=config.refresh_grace):
        return None
    connection = store.by_issued_refresh(given.refresh_hash)
    if (
        connection is None
        or connection.id != given.connection_id
        or connection.issued_access_hash != given.access_hash
        or not reach.same_place(form.get("client_id", ""), connection.partner_base)
    ):
        return None
    if not store.account_may(connection.account_id):
        raise GrantError("account_resting", "The account rests on this side.")
    access, refresh = json.loads(store.unseal(given.sealed))
    logger.info("refresh token brought again within the grace, the same answer connection=%s", connection.id)
    lasts = max(1, int((given.access_expires - now).total_seconds()))
    return _answer(config, connection, access, refresh, store, lasts=lasts)


def _refresh(store: Any, config: AppConfig, form: dict[str, str], now: datetime) -> dict[str, Any]:
    # Since 0.2.1 (BS1): one refresh at a time in this app, so that two with the same token meet the grace (BS2).
    with RENEWALS.lock(config.app_name, "token"):
        return _refresh_one(store, config, form, now)


def _refresh_one(store: Any, config: AppConfig, form: dict[str, str], now: datetime) -> dict[str, Any]:
    brought = oauthcore.digest(form.get("refresh_token", ""))
    connection = store.by_issued_refresh(brought)
    if connection is None:
        again = _again(store, config, form, brought, now)
        if again is not None:
            return again
        _end_copy(store, brought, "refresh token")
        raise GrantError("invalid_grant", "The refresh token is not valid (any more).")
    if not reach.same_place(form.get("client_id", ""), connection.partner_base):
        raise GrantError("invalid_grant", "The refresh token is not valid (any more).")
    if not store.account_may(connection.account_id):
        raise GrantError("account_resting", "The account rests on this side.")
    if now - (connection.used_at or connection.created_at) > timedelta(days=config.idle_days):
        raise GrantError("connection_resting", "The connection was not used for a long time. Connect again.")
    made = oauthcore.new_tokens(config.access_prefix, config.refresh_prefix, config.access_hours, now)
    fresh = replace(
        connection,
        issued_access_hash=made.access_hash,
        issued_refresh_hash=made.refresh_hash,
        issued_access_expires=made.access_expires,
        used_at=now,
    )
    fresh = _save(store, fresh)
    store.spend(connection.id, brought, config.spent_kept)
    store.commit()
    RENEWALS.issued(
        brought,
        _Issued(
            connection_id=connection.id,
            access_hash=made.access_hash,
            refresh_hash=made.refresh_hash,
            access_expires=made.access_expires,
            sealed=store.seal(json.dumps([made.access, made.refresh])),
            at=now,
        ),
    )
    return _answer(config, fresh, made.access, made.refresh, store)


def revoke(store: Any, form: dict[str, str]) -> Connection | None:
    """``POST /api/connect/revoke`` (RFC 7009): a token this app gave ends the whole connection on this side; anything
    else is ignored (the same answer either way). Returns the connection that ended (since 0.1.4, for
    ``on_disconnected``)."""
    brought = oauthcore.digest(form.get("token", ""))
    connection = store.by_issued_refresh(brought) or store.by_issued_access(brought)
    if connection is None:
        return None
    client = form.get("client_id", "")
    if client and not reach.same_place(client, connection.partner_base):
        return None
    store.remove(connection.id)
    store.commit()
    logger.info("%s ended the connection connection=%s", connection.partner, connection.id)
    return connection


# --- checking a token of a partner ------------------------------------------------------------------------------------


def authenticate(store: Any, config: AppConfig, token_value: str | None, now: datetime) -> Caller:
    """The connection behind a token a partner brings (``Authorization: Bearer``), or ``Refused``: ``token_invalid``
    (401), ``connections_off`` (403), ``account_resting`` (401, the account is blocked or deleted, or since 0.2.1
    locked or owing its second factor where ``Store.account_may`` says so: it rests, E41)."""
    if not token_value or not token_value.startswith(config.access_prefix):
        raise Refused("token_invalid")
    connection = store.by_issued_access(oauthcore.digest(token_value))
    if connection is None or connection.issued_access_expires <= now:
        raise Refused("token_invalid")
    if not connections_on(store):
        raise Refused("connections_off")
    if not store.account_may(connection.account_id):
        raise Refused("account_resting")
    if connection.used_at is None or now - connection.used_at >= TOUCH_EVERY:
        _save(store, replace(connection, used_at=now))
        store.commit()
    return Caller(
        account_id=connection.account_id,
        connection_id=connection.id,
        partner=connection.partner,
        purposes=connection.grants,
        areas=connection.areas_granted,
        level=config.catalog.level(config.app_name, connection.grants),
    )


def require(caller: Caller, purpose: str) -> None:
    """For the app's routes: the connection must allow ``purpose`` (else 403 ``purpose_missing``)."""
    if not caller.may(purpose):
        raise Refused("purpose_missing")


# --- calling the partner ----------------------------------------------------------------------------------------------


def _mark(store: Any, connection: Connection, state: str, now: datetime, problem: str | None = None) -> Connection:
    if state == "connected":
        changed = replace(connection, state=state, ok_at=now, stale_since=None, problem=None)
    elif state == "unreachable":
        # Since 0.1.8 (B2): ``local_off`` where the operator does not allow the own network, so the card says why.
        changed = replace(
            connection, state=state, stale_since=connection.stale_since or now, problem=problem or "unreachable"
        )
    else:
        changed = replace(connection, state=state, problem=problem or state)
    changed = _save(store, changed)
    store.commit()
    return changed


def _state_of_refusal(code: str) -> str:
    if code in ("account_resting", "connection_resting"):
        return "resting"
    if code == "connections_off":
        return "off"
    return "refused"


def _held_of(store: Any, connection: Connection) -> dict[str, str]:
    return json.loads(store.unseal(connection.held))


def _lasts(held: dict[str, str], now: datetime) -> bool:
    return datetime.fromisoformat(held["expires"]) - now > REFRESH_EARLY


def _fresh_access(
    store: Any,
    config: AppConfig,
    connection: Connection,
    now: datetime,
    *,
    force: bool = False,
    failed: str | None = None,
) -> dict[str, str]:
    """The tokens held of the partner, the access token fresh: refreshed when it ends within ``REFRESH_EARLY``, or with
    ``force`` (the partner answered 401). Since 0.2.1 (BS1) one refresh per connection at a time; who waited takes the
    tokens the other got, and with ``force`` and ``failed`` (the access token that got the 401) refreshes only where
    that is still the one held."""
    held = _held_of(store, RENEWALS.latest(store, connection))
    if not force and _lasts(held, now):
        return held
    with RENEWALS.lock(config.app_name, connection.id):
        found = store.connection(connection.account_id, connection.partner)
        if found is None or found.id != connection.id:
            raise Refused("not_connected")
        current = RENEWALS.latest(store, found)
        held = _held_of(store, current)
        if _lasts(held, now) and (not force or (failed is not None and held["access"] != failed)):
            return held
        form = {"grant_type": "refresh_token", "refresh_token": held["refresh"], "client_id": held["own"]}
        try:
            answer = _ask(config, store, current.partner_base, "POST", f"{PREFIX}/token", form=form)
        except reach.Unreachable as failure:
            _mark(store, current, "unreachable", now, unreachable(failure).code)
            raise Refused("unreachable") from None
        data = answer.data if isinstance(answer.data, dict) else {}
        access, refresh = _text(data.get("access_token"), MAX_TOKEN), _text(data.get("refresh_token"), MAX_TOKEN)
        lasts = data.get("expires_in")
        if answer.status != 200 or not access or not refresh or not isinstance(lasts, int):
            state = _state_of_refusal(answer.code)
            _mark(store, current, state, now, answer.code or None)
            raise Refused(state if state != "off" else "partner_off")
        renewed = replace(current, held=_held(store, access, refresh, now + timedelta(seconds=lasts), held["own"]))
        renewed = _save(store, renewed)
        store.commit()
        RENEWALS.renewed(oauthcore.digest(held["refresh"]), renewed.held, now)
        return _held_of(store, renewed)


def call(
    store: Any,
    config: AppConfig,
    account_id: AccountId,
    partner: str,
    method: str,
    path: str,
    now: datetime,
    *,
    body: Any = None,
    params: dict[str, str] | dict[str, list[str]] | None = None,
) -> reach.Answer:
    """One request to the partner (``path`` from its root, ``/api/v1/tasks``) with the connection's token: refreshed on
    its own, the card's state kept. Raises ``Refused`` with ``not_connected``, ``unreachable`` (the last state stays
    and the card says since when), ``refused``, ``resting`` or ``partner_off``; any other answer comes back as it is."""
    connection = store.connection(account_id, partner)
    if connection is None:
        raise Refused("not_connected")
    access: str | None = None
    for attempt in (1, 2):
        access = _fresh_access(store, config, connection, now, force=attempt == 2, failed=access)["access"]
        connection = RENEWALS.latest(store, store.connection(account_id, partner) or connection)
        try:
            answer = _ask(config, store, connection.partner_base, method, path, bearer=access, body=body, params=params)
        except reach.Unreachable as failure:
            _mark(store, connection, "unreachable", now, unreachable(failure).code)
            raise Refused("unreachable") from None
        if answer.status == 401 and answer.code != "account_resting" and attempt == 1:
            continue
        if answer.status in (401, 403) and answer.code in ("token_invalid", "account_resting", "connections_off"):
            state = _state_of_refusal(answer.code)
            _mark(store, connection, state, now, answer.code)
            raise Refused(state if state != "off" else "partner_off")
        if answer.status == 401:
            _mark(store, connection, "refused", now, answer.code or "token_invalid")
            raise Refused("refused")
        _mark(store, connection, "connected", now)
        return answer
    raise Refused("refused")  # pragma: no cover (the loop always returns or raises)


def check(store: Any, config: AppConfig, account_id: AccountId, partner: str, now: datetime) -> Connection:
    """ "Jetzt prüfen": the partner's ``hello`` with the connection; the connection as it stands afterwards."""
    if not BRAKE.take(f"verbinden:check:{account_id}", config.starts_per_minute):
        raise Refused("slow_down")
    try:
        answer = call(store, config, account_id, partner, "GET", f"{PREFIX}/hello", now)
    except Refused as refusal:
        if refusal.code == "not_connected":
            raise
        found = store.connection(account_id, partner)
        if found is None:
            raise
        return found
    connection = store.connection(account_id, partner)
    assert connection is not None
    connection = RENEWALS.latest(store, connection)
    if isinstance(answer.data, dict):
        connection = replace(
            connection,
            partner_account=_text(answer.data.get("account"), MAX_NAME) or connection.partner_account,
            partner_version=_text(answer.data.get("version"), 40) or connection.partner_version,
        )
        connection = _save(store, connection)
        store.commit()
    return connection


def hello(store: Any, config: AppConfig, caller: Caller) -> dict[str, Any]:
    """``GET /api/connect/hello``: the partner checks the connection ("Jetzt prüfen")."""
    return {
        "app": config.app_name,
        "version": config.version,
        "connection": caller.connection_id,
        "account": account_shown(store, caller.account_id),
    }


# --- ending -----------------------------------------------------------------------------------------------------------


def _end(store: Any, config: AppConfig, connection: Connection, now: datetime) -> None:
    """Tells the partner (or keeps the revocation for later) and drops this side."""
    held = _held_of(store, RENEWALS.latest(store, connection))
    form = {"token": held["refresh"], "client_id": held["own"]}
    try:
        _ask(config, store, connection.partner_base, "POST", f"{PREFIX}/revoke", form=form)
    except reach.Unreachable:
        store.revoke_later(connection.account_id, connection.partner_base, store.seal(json.dumps(form)), now)
        logger.info("%s not reached, the revocation waits connection=%s", connection.partner, connection.id)
    except Refused as refusal:
        # Since 0.2.1 (BS4): an address the module never asks (a port below 1024, a name of this server) cannot hear
        # it later either; the connection ends here all the same (also while an account is deleted for good).
        logger.info(
            "%s not asked (%s), the revocation is given up connection=%s",
            connection.partner,
            refusal.code,
            connection.id,
        )
    store.remove(connection.id)
    store.commit()


def forget_legacy(store: Any, account_id: AccountId, partner: str) -> bool:
    """Decision V56 (B9, decided 27.11.2026): the account's older connection with ``partner`` by an API key typed in by
    hand ends here; the app drops its row with the key (``Store.forget_legacy(account_id, partner)``, since 0.2.0). So
    after a connection by click (made from either side), after "Trennen" and after a no on the consent page the card
    shows no older connection that comes forward again. A ``Store`` without the method keeps everything as before 0.2.0.
    True when one ended; the caller commits."""
    forget = getattr(store, "forget_legacy", None)
    if not callable(forget) or not any(row.partner == partner for row in store.legacy(account_id)):
        return False
    forget(account_id, partner)
    logger.info("older connection with %s by API key ended here", partner)
    return True


def disconnect(store: Any, config: AppConfig, account_id: AccountId, partner: str, now: datetime) -> None:
    """ "Trennen" on either side: both directions end (V3). Since 0.2.0 (B9, V56) an older connection by API key with
    the partner ends with it, or alone where there is no connection by click."""
    connection = store.connection(account_id, partner)
    forgot = forget_legacy(store, account_id, partner)
    if forgot:
        # Since 0.2.1 (BS3): committed before the partner is asked over the network, so no write lock waits on it.
        store.commit()
    if connection is None:
        if not forgot:
            raise Refused("not_connected")
        return
    _end(store, config, connection, now)
    logger.info("connection with %s ended here connection=%s", partner, connection.id)


def end_all(store: Any, config: AppConfig, account_id: AccountId, now: datetime) -> int:
    """The account is deleted for good: every connection ends, the partners hear it (or later)."""
    found = store.connections(account_id)
    for connection in found:
        _end(store, config, connection, now)
    return len(found)


def retry_waiting(store: Any, config: AppConfig, now: datetime) -> int:
    """Revocations the partner has not heard yet, tried again (the app's clock calls this now and then); the number
    that are done (heard, or given up after ``revoke_days``)."""
    done = 0
    for waiting in store.waiting():
        if now - waiting.since <= timedelta(days=config.revoke_days):
            try:
                _ask(
                    config,
                    store,
                    waiting.partner_base,
                    "POST",
                    f"{PREFIX}/revoke",
                    form=json.loads(store.unseal(waiting.token)),
                )
            except reach.Unreachable:
                continue
            except Refused:
                # Since 0.2.1 (BS4): an address the module never asks; given up, as after ``revoke_days``.
                logger.info("a waiting revocation is given up: the address is never asked")
        store.done_waiting(waiting.id)
        store.commit()
        done += 1
    return done


def retire_at(store: Any, config: AppConfig, base: str, old_key: str) -> bool:
    """After "Neu verbinden": the partner's older API key, typed in by hand once, ends itself there."""
    try:
        answer = _ask(config, store, base, "POST", f"{PREFIX}/retire", bearer=old_key)
    except (reach.Unreachable, Refused):
        return False
    return answer.status == 200 and isinstance(answer.data, dict) and bool(answer.data.get("retired"))


# --- what the card shows ----------------------------------------------------------------------------------------------


def _asks_person(config: AppConfig, granted_by: str, purposes: Any) -> bool:
    """Whether one of ``purposes`` (granted by ``granted_by``) is asked with a person (V51)."""
    own = config.catalog.purposes.get(granted_by, {})
    return any(own[purpose].person for purpose in purposes if purpose in own)


def view(
    config: AppConfig, store: Any, account_id: AccountId, partner: str, now: datetime, connection: Connection | None
) -> dict[str, Any]:
    """One card: the partner, its state, what flows (both directions), the address to start from."""
    from_operator = operator_address(store, partner)
    legacy = next((row for row in store.legacy(account_id) if row.partner == partner), None)
    found: dict[str, Any] = {
        "partner": partner,
        "state": "none",
        "address": from_operator,
        "address_from_operator": bool(from_operator),
        # Since 0.1.8 (V42, B3): whether the account can connect from here (an address of the operator, of the
        # connection or of an older one); without, the card says the app is not set up on this server.
        "set_up": bool(from_operator),
        "host": "",
        "uses": list(config.catalog.uses(config.app_name, partner)),
        "grants": list(config.catalog.uses(partner, config.app_name)),
        "account": None,
        "since": None,
        "ok_at": None,
        "used_at": None,
        "stale_since": None,
        "problem": None,
        "areas_used": None,
        "areas_granted": None,
        "legacy": None,
        "version": None,
    }
    if connection is not None:
        found.update(uses=list(connection.uses), grants=list(connection.grants))
    found["uses_levels"] = {purpose: config.catalog.purpose(partner, purpose).level for purpose in found["uses"]}
    found["grants_levels"] = {
        purpose: config.catalog.purpose(config.app_name, purpose).level for purpose in found["grants"]
    }
    # Since 0.1.13 (V53): whether this app sends the partner a person (name, mail addresses, numbers of the contact
    # looked at), or the partner sends one here; the card says so.
    found["sends_person"] = _asks_person(config, partner, found["uses"])
    found["receives_person"] = _asks_person(config, config.app_name, found["grants"])
    # Decisions V16 (F1 = a) and V41: where a purpose the partner uses here has areas, reading or writing, the card asks
    # for them before the click; the account's own areas to choose from (empty when no purpose of the partner has any).
    catalog_grants = config.catalog.uses(partner, config.app_name)
    asks_areas = any(config.catalog.purpose(config.app_name, purpose).areas for purpose in catalog_grants)
    found["areas_choice"] = (
        [{"id": area["id"], "name": area["name"]} for area in store.areas(account_id)] if asks_areas else []
    )
    if connection is not None:
        found.update(
            state=connection.state,
            address=connection.partner_base,
            host=urlsplit(connection.partner_base).netloc,
            account=connection.partner_account,
            since=_iso(connection.created_at),
            ok_at=_iso(connection.ok_at),
            used_at=_iso(connection.used_at),
            stale_since=_iso(connection.stale_since),
            problem=connection.problem,
            areas_used=connection.areas_used,
            areas_granted=_areas_named(store, account_id, connection.areas_granted),
            version=connection.partner_version or None,
            set_up=True,
        )
        return found
    if legacy is not None:
        state = "legacy"
        if legacy.problem in ("unreachable", "refused"):
            state = legacy.problem
        elif legacy.expires_at is not None and legacy.expires_at - now <= timedelta(days=config.expiring_days):
            state = "expiring" if legacy.expires_at > now else "refused"
        found.update(
            state=state,
            address=legacy.partner_base,
            host=urlsplit(legacy.partner_base).netloc,
            ok_at=_iso(legacy.ok_at),
            # Since 0.2.0 (B9, V56): "Trennen" ends it, where the app's Store can forget it.
            legacy={
                "shown": legacy.shown,
                "expires_at": _iso(legacy.expires_at),
                "can_end": callable(getattr(store, "forget_legacy", None)),
            },
            set_up=bool(legacy.partner_base) or bool(from_operator),
        )
    return found


def views(config: AppConfig, store: Any, account_id: AccountId, now: datetime) -> list[dict[str, Any]]:
    """The partners of the app in the order of the catalog, connected or not; no token, no hash in it. Decision V20: a
    partner the app has no use for yet (``in_use``) is left out, unless a connection grants it something here."""
    mine = {connection.partner: connection for connection in store.connections(account_id)}
    shown = [
        partner for partner in config.partners if partner in config.usable or (partner in mine and mine[partner].grants)
    ]
    return [view(config, store, account_id, partner, now, mine.get(partner)) for partner in shown]


# --- using a connection with the app's own requests (decision V18) ------------------------------------------------


@dataclass(frozen=True)
class Access:
    """What an app's own request to the partner needs (its ``request()`` with address and key): the partner's address
    and a fresh access token of the connection, until ``expires_at``."""

    base: str
    token: str
    expires_at: datetime


def access(
    store: Any,
    config: AppConfig,
    account_id: AccountId,
    partner: str,
    now: datetime,
    *,
    force: bool = False,
    failed: str | None = None,
) -> Access:
    """Decision V18: the address and a fresh token of the connection with ``partner``, for the app's own requests (as
    it asked with an address and a key typed in by hand). Refreshes on its own; ``force`` refreshes even a token still
    valid (after the partner answered 401 once); since 0.2.1 with ``failed``, the token that got the 401, only where it
    is still the one held (another request may have refreshed it meanwhile). Raises ``Refused`` like ``call``:
    ``not_connected``, ``unreachable``, ``refused``, ``resting``, ``partner_off``. The app tells the module how its
    own request went with ``reached``."""
    connection = store.connection(account_id, partner)
    if connection is None:
        raise Refused("not_connected")
    held = _fresh_access(store, config, connection, now, force=force, failed=failed)
    return Access(
        base=connection.partner_base, token=held["access"], expires_at=datetime.fromisoformat(held["expires"])
    )


def reached(store: Any, account_id: AccountId, partner: str, now: datetime, *, problem: str | None = None) -> None:
    """How the app's own request to the partner went, for the card: ``problem`` ``None`` (it answered), ``unreachable``
    (nothing usable came), or the partner's code of a refusal (``token_invalid`` after ``access(force=True)``,
    ``account_resting``, ``connections_off``)."""
    connection = store.connection(account_id, partner)
    if connection is None:
        return
    if problem is None:
        _mark(store, connection, "connected", now)
    elif problem in ("unreachable", "local_off"):
        _mark(store, connection, "unreachable", now, problem)
    else:
        _mark(store, connection, _state_of_refusal(problem), now, problem)
