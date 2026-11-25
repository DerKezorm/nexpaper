"""Everything that happens to a key: an account makes, changes and revokes its own, the operator sees all of them and
locks or unlocks one, a program presents one. The rows stay in the app's tables (``Store``); here are the rules.

The rules are the ones the eight apps already had, the same in every app now:

- a new key: the app's prefix and 32 random bytes, stored as SHA-256 hex; shown once, never again;
- a name (whitespace made one, at most ``name_max``), one of the app's rights, its extras, its areas (a non-empty
  part of what the account may reach, or all, later ones too, where the app offers "all"), a lifetime where the app
  knows one; at most ``max_keys`` per account;
- the operator's switch of the kind must be on to make one (``api_off``, ``mcp_off``);
- an account whose keys rest until it sets up a second factor (``Store.keys_wait``) still makes keys: the page says
  "Works only once you set up a second factor" (decided 24.11.2026);
- a key is refused when it is unknown, locked, expired, of a blocked or deleted account, while its switch is off, and
  while its account's keys rest; ``last used`` is written at most once a minute.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from . import tokens
from .config import OPTION_MCP, SWITCH_MCP, AppConfig, KeyKind
from .errors import KeyRefused
from .model import ALL_AREAS, AccountId, Area, Holder, Key, KeyChange, KeyId, NewKey, Store

_SPACES = re.compile(r"\s+")


def now_utc() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime | None) -> datetime | None:
    """Every app stores UTC; a moment read without its zone is UTC."""
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _iso(moment: datetime | None) -> str | None:
    aware = _aware(moment)
    return aware.isoformat() if aware else None


@dataclass(frozen=True)
class Made:
    """A key just made: what the list shows, and the secret, shown this once."""

    key: Key
    secret: str
    #: ``False`` when the form's reference found a key made a moment ago (a double click): no secret then.
    new: bool = True


@dataclass(frozen=True)
class Caller:
    """Who presented a key: the key and its account."""

    key: Key
    holder: Holder


# --- reading ------------------------------------------------------------------------------------------------------


def expired(key: Key, now: datetime | None = None) -> bool:
    end = _aware(key.expires_at)
    return end is not None and end <= (now or now_utc())


def expiring(key: Key, config: AppConfig, now: datetime | None = None) -> bool:
    """Within ``warn_days`` of its end (and not past it)."""
    end = _aware(key.expires_at)
    moment = now or now_utc()
    return end is not None and moment < end <= moment + timedelta(days=config.warn_days)


def entry(key: Key, config: AppConfig, areas: list[Area] | None = None, now: datetime | None = None) -> dict:
    """A key as the page gets it: never its secret, never its hash. ``areas`` named where the account's own list is
    at hand (the account's page); elsewhere the ids only."""
    names = {area.id: area.name for area in areas or []}
    if key.areas is None:
        shown_areas = None
    else:
        shown_areas = [{"id": area, "name": names.get(area)} for area in key.areas]
    return {
        "id": key.id,
        "kind": key.kind,
        "name": key.name,
        "right": key.right,
        "options": dict(key.options),
        "areas": shown_areas,
        "prefix": key.prefix,
        "created_at": _iso(key.created_at),
        "last_used_at": _iso(key.last_used_at),
        # A program's access token runs out every hour and is renewed by its refresh: no end of the connection.
        "expires_at": None if key.program else _iso(key.expires_at),
        "expired": False if key.program else expired(key, now),
        "expiring": False if key.program else expiring(key, config, now),
        "blocked": key.blocked_at is not None,
        "legacy": key.legacy,
        "program": key.program,
    }


def rights_for(store: Store, kind: KeyKind, account_id: AccountId) -> tuple[str, ...]:
    """The rights the account may give a new key of ``kind`` now: the kind's, narrowed where the store says so
    (``Store.rights_allowed``, optional: nexlore's operator caps MCP keys with "highest level of a key")."""
    narrow = getattr(store, "rights_allowed", None)
    if not callable(narrow):
        return kind.rights
    allowed = set(narrow(account_id, kind.id))
    return tuple(right for right in kind.rights if right in allowed)


def _kind_choice(store: Store, config: AppConfig, kind: KeyKind, account_id: AccountId) -> dict:
    areas = store.areas_of(account_id, kind.id) if kind.areas else []
    rights = rights_for(store, kind, account_id)
    return {
        "id": kind.id,
        "prefix": kind.prefix,
        "creatable": kind.creatable,
        "editable": kind.editable,
        "rights": list(rights),
        "default_right": kind.default_right if kind.default_right in rights else (rights[0] if rights else None),
        "options": list(kind.options),
        "areas": [{"id": area.id, "name": area.name} for area in areas] if kind.areas else None,
        "areas_required": kind.areas_required,
        "expiry_days": list(kind.expiry_days) if kind.expiry_days is not None else None,
        "default_days": kind.default_days if kind.expiry_days is not None else None,
        "default_days_by_right": dict(kind.default_days_by_right),
        "max_keys": kind.max_keys,
        "count": _count(store, config, kind, account_id),
        "name_max": kind.name_max,
    }


def listing(store: Store, config: AppConfig, account_id: AccountId, now: datetime | None = None) -> dict:
    """The account's page: its keys and programs, what it may make, the switches, whether its keys rest."""
    moment = now or now_utc()
    areas: dict[str, list[Area]] = {kind.id: store.areas_of(account_id, kind.id) for kind in config.kinds if kind.areas}
    every = [area for found in areas.values() for area in found]
    keys = [entry(key, config, areas.get(key.kind, every), moment) for key in store.keys_of(account_id)]
    return {
        "app": config.app_name,
        "api": store.switch("api"),
        "mcp": store.switch(SWITCH_MCP) if config.has_mcp else None,
        "programs": config.programs,
        "api_path": config.api_path,
        "mcp_path": config.mcp_path,
        "keys_wait": bool(store.keys_wait(account_id)),
        "warn_days": config.warn_days,
        "kinds": [_kind_choice(store, config, kind, account_id) for kind in config.kinds],
        "keys": keys,
    }


def overview(store: Store, config: AppConfig, now: datetime | None = None) -> list[dict]:
    """Every key of every account for the operator: account, name, right, last used, locked. Never the key itself,
    never what it reached."""
    moment = now or now_utc()
    holders: dict[AccountId, Holder | None] = {}
    rows = []
    for key in store.all_keys():
        if key.account_id not in holders:
            holders[key.account_id] = store.holder(key.account_id)
        holder = holders[key.account_id]
        row = entry(key, config, None, moment)
        row["areas"] = None if key.areas is None else len(key.areas)
        row["account"] = (
            {
                "id": holder.id,
                "name": holder.name,
                "display_name": holder.display_name or holder.name,
                "out": holder.out,
            }
            if holder
            else {"id": key.account_id, "name": "", "display_name": "", "out": True}
        )
        rows.append(row)
    return rows


# --- an account's own keys ----------------------------------------------------------------------------------------


def _count(store: Store, config: AppConfig, kind: KeyKind, account_id: AccountId) -> int:
    counted = {kind.id, *kind.counted_with}
    return sum(
        1 for key in store.keys_of(account_id) if key.kind in counted and (kind.programs_count or not key.program)
    )


def clean_name(raw: str | None, kind: KeyKind, config: AppConfig) -> str:
    name = _SPACES.sub(" ", raw or "").strip()
    if not name:
        raise KeyRefused("name_missing", config=config)
    if len(name) > kind.name_max:
        raise KeyRefused("name_too_long", config=config, max=kind.name_max)
    return name


def _right(raw: str | None, kind: KeyKind, config: AppConfig, store: Store, account_id: AccountId) -> str:
    allowed = rights_for(store, kind, account_id)
    right = raw or (kind.default_right if kind.default_right in allowed else (allowed[0] if allowed else ""))
    if right not in allowed:
        raise KeyRefused("right_invalid", config=config)
    return right


def _options(raw: dict[str, bool] | None, kind: KeyKind, config: AppConfig, store: Store) -> dict[str, bool]:
    chosen = {name: bool(on) for name, on in (raw or {}).items()}
    for name in chosen:
        if name not in kind.options:
            raise KeyRefused("option_invalid", config=config)
    if chosen.get(OPTION_MCP) and not store.switch(SWITCH_MCP):
        raise KeyRefused("mcp_off", config=config)
    return {name: chosen.get(name, False) for name in kind.options}


def _areas(
    raw: list | str | None, kind: KeyKind, config: AppConfig, store: Store, account_id: AccountId
) -> list | None:
    """``None`` or ``ALL_AREAS``: all (where offered); a list: a non-empty part of the account's areas, in their
    order, each once. Ids compare as text, so ``"7"`` from a form finds the area ``7``."""
    if not kind.areas:
        return None
    if raw is None or raw == ALL_AREAS:
        if kind.areas_required:
            raise KeyRefused("choose_areas", config=config)
        return None
    if not isinstance(raw, list) or not raw:
        raise KeyRefused("choose_areas", config=config)
    if len(raw) > 500:
        raise KeyRefused("areas_invalid", config=config)
    own = store.areas_of(account_id, kind.id)
    wanted = {str(area) for area in raw}
    known = {str(area.id) for area in own}
    if not wanted <= known:
        raise KeyRefused("areas_invalid", config=config)
    return [area.id for area in own if str(area.id) in wanted]


def _expires(days: int | None | str, kind: KeyKind, config: AppConfig, right: str, now: datetime) -> datetime | None:
    if kind.expiry_days is None:
        return None
    if days == "default":
        days = kind.days_for(right)
    if days not in kind.expiry_days:
        raise KeyRefused("days_invalid", config=config)
    return None if days is None else now + timedelta(days=int(days))


def _kind(config: AppConfig, kind_id: str) -> KeyKind:
    kind = config.kind(kind_id)
    if kind is None:
        raise KeyRefused("kind_unknown", config=config)
    return kind


def make(
    store: Store,
    config: AppConfig,
    account_id: AccountId,
    *,
    kind: str = "api",
    name: str | None,
    right: str | None = None,
    areas: list | str | None = None,
    options: dict[str, bool] | None = None,
    days: int | None | str = "default",
    client_ref: str | None = None,
    now: datetime | None = None,
) -> Made:
    """Make a key for ``account_id``. ``days="default"``: the app's lifetime for this right."""
    chosen = _kind(config, kind)
    if not chosen.creatable:
        raise KeyRefused("kind_not_creatable", config=config)
    if not store.switch(chosen.switch):
        raise KeyRefused(f"{chosen.switch}_off", config=config)
    moment = now or now_utc()
    if client_ref:
        finder = getattr(store, "key_by_client_ref", None)
        if callable(finder):
            earlier = finder(account_id, client_ref[:64])
            if earlier is not None:
                return Made(key=earlier, secret="", new=False)
    clean = clean_name(name, chosen, config)
    picked = _right(right, chosen, config, store, account_id)
    extras = _options(options, chosen, config, store)
    limited = _areas(areas, chosen, config, store, account_id)
    end = _expires(days, chosen, config, picked, moment)
    if _count(store, config, chosen, account_id) >= chosen.max_keys:
        raise KeyRefused("too_many_keys", config=config, max=chosen.max_keys)
    secret = tokens.make_secret(chosen.prefix, chosen.secret_bytes)
    key = store.add_key(
        NewKey(
            account_id=account_id,
            kind=chosen.id,
            name=clean,
            right=picked,
            token_hash=tokens.digest(secret),
            prefix=tokens.shown_prefix(secret, chosen.prefix, chosen.shown_extra),
            created_at=moment,
            expires_at=end,
            areas=limited,
            options=extras,
            client_ref=client_ref[:64] if client_ref else None,
        )
    )
    store.commit()
    return Made(key=key, secret=secret)


def _own(store: Store, config: AppConfig, account_id: AccountId, key_id: KeyId) -> Key:
    key = store.key(key_id)
    if key is None or str(key.account_id) != str(account_id):
        raise KeyRefused("not_found", config=config)
    return key


def change(
    store: Store,
    config: AppConfig,
    account_id: AccountId,
    key_id: KeyId,
    *,
    name: str | None = None,
    right: str | None = None,
    areas: list | str | None = None,
    options: dict[str, bool] | None = None,
    areas_given: bool = False,
) -> Key:
    """Change name, right, areas or extras of a key of the account's own (nexmail could; now every app). A program's
    key is changed by its next consent, not here. ``areas_given``: ``areas`` was sent (``None`` then means all)."""
    key = _own(store, config, account_id, key_id)
    kind = _kind(config, key.kind)
    if not kind.editable or key.program or key.legacy:
        raise KeyRefused("key_not_editable", config=config)
    update = KeyChange(
        name=clean_name(name, kind, config) if name is not None else None,
        right=_right(right, kind, config, store, account_id) if right is not None else None,
        areas=(
            (lambda found: ALL_AREAS if found is None else found)(_areas(areas, kind, config, store, account_id))
            if areas_given and kind.areas
            else None
        ),
        options=_options({**key.options, **options}, kind, config, store) if options is not None else None,
    )
    changed = store.change_key(key.id, update)
    store.commit()
    return changed


def revoke(store: Store, config: AppConfig, account_id: AccountId, key_id: KeyId) -> None:
    """Revoke a key of the account's own, a program's too: the program is out at once, what it wrote stays."""
    key = _own(store, config, account_id, key_id)
    store.remove_key(key.id)
    store.commit()


# --- the operator -------------------------------------------------------------------------------------------------


def block(store: Store, config: AppConfig, key_id: KeyId, now: datetime | None = None) -> dict:
    """Lock a key: refused at once, the account sees it as "Locked by the operator". Locking twice keeps the first
    moment."""
    key = store.key(key_id)
    if key is None:
        raise KeyRefused("not_found", config=config)
    if key.blocked_at is None:
        store.set_blocked(key.id, now or now_utc())
        store.commit()
    return _entry_of(store, config, key.id)


def unblock(store: Store, config: AppConfig, key_id: KeyId) -> dict:
    """Unlock a key: it works again (new in every app; before, a lock was for good)."""
    key = store.key(key_id)
    if key is None:
        raise KeyRefused("not_found", config=config)
    if key.blocked_at is not None:
        store.set_blocked(key.id, None)
        store.commit()
    return _entry_of(store, config, key.id)


def _entry_of(store: Store, config: AppConfig, key_id: KeyId) -> dict:
    key = store.key(key_id)
    assert key is not None
    holder = store.holder(key.account_id)
    row = entry(key, config)
    row["areas"] = None if key.areas is None else len(key.areas)
    row["account"] = {
        "id": key.account_id,
        "name": holder.name if holder else "",
        "display_name": (holder.display_name or holder.name) if holder else "",
        "out": holder.out if holder else True,
    }
    return row


# --- a program presents a key -------------------------------------------------------------------------------------


def authenticate(
    store: Store,
    config: AppConfig,
    token: str | None,
    kinds: tuple[str, ...] = ("api",),
    *,
    now: datetime | None = None,
) -> Caller:
    """The key a program presents (``tokens.bearer`` of its ``Authorization``), for a route that takes keys of
    ``kinds``. An API key with the extra ``mcp`` also passes where ``kinds`` is ``("mcp",)``. Raises ``KeyRefused``:
    ``api_off``/``mcp_off`` while the switch is off, ``token_invalid`` for anything unknown, locked, expired or of an
    account that is out, ``second_factor_required`` while the account's keys rest."""
    moment = now or now_utc()
    for kind_id in kinds:
        kind = config.kind(kind_id)
        switch = kind.switch if kind else kind_id
        if switch in ("api", SWITCH_MCP) and not store.switch(switch):
            raise KeyRefused(f"{switch}_off", config=config)
    kind = config.kind_of(token or "")
    if not token or kind is None or not tokens.plausible(token, kind.prefixes, kind.max_length):
        raise KeyRefused("token_invalid", config=config)
    key = store.key_by_hash(tokens.digest(token))
    if key is None:
        raise KeyRefused("token_invalid", config=config)
    fits = key.kind in kinds or (SWITCH_MCP in kinds and key.kind == "api" and key.options.get(OPTION_MCP))
    if not fits or key.blocked_at is not None or expired(key, moment):
        raise KeyRefused("token_invalid", config=config)
    holder = store.holder(key.account_id)
    if holder is None or holder.out:
        raise KeyRefused("token_invalid", config=config)
    if store.keys_wait(key.account_id):
        raise KeyRefused("second_factor_required", config=config)
    last = _aware(key.last_used_at)
    if last is None or moment - last >= config.used_every:
        store.touch(key.id, moment)
        store.commit()
        key.last_used_at = moment
    return Caller(key=key, holder=holder)


__all__ = [
    "Caller",
    "Made",
    "authenticate",
    "block",
    "change",
    "clean_name",
    "entry",
    "expired",
    "expiring",
    "listing",
    "make",
    "now_utc",
    "overview",
    "revoke",
    "rights_for",
    "unblock",
]
