"""Since 1.1.0: "Ready for the internet?" on the page Server › Sign-in, the same in every app (plan "Einstellungen",
Anmeldung; contents after nexpaper's and nexdiary's card, which it replaces).

The server checks itself each time the page opens and says per point ``ok`` (green), ``warn`` (orange: something to
look at) or ``bad`` (red: critical); the card's symbol takes the colour of the worst. The common points, in this order:

1. ``address``: the public address with https (red without https or without an address, orange when this request
   came without https although the address has it);
2. ``factorForAll``: a second factor for everybody (red when off or switched off by the emergency hammer, orange when
   a provider that checks it itself lets accounts in without it);
3. ``ownAccount``: the operator's own account has a second factor (red without);
4. ``brake``: protection against guessing (the module's wording: 5 tries free, then waiting, after 10 the account is
   locked for 15 minutes; red when the trusted proxies name public networks or the brake fails its own test, orange
   behind an unknown proxy);
5. ``cookies``: sessions and cookies (red when the app's cookie switch says off, orange without https);
6. ``proxy``: behind the proxy (red with public networks, orange behind a proxy the app does not trust).

An app adds its own points (``Point`` with its own text keys; nexdiary: entries encrypted, master key saved; nexpaper:
server secrets, backup, upload requests), each at the end or after a common point (``after``).
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from . import brake, config, factor, sessions

OK, WARN, BAD = "ok", "warn", "bad"
STATES = (OK, WARN, BAD)
#: The common points in their order.
POINTS = ("address", "factorForAll", "ownAccount", "brake", "cookies", "proxy")
_RANK = {OK: 0, WARN: 1, BAD: 2}


@dataclass(frozen=True)
class Point:
    """One point: its key, its state, the text keys of its title and its sentence (i18next, namespace ``account`` for
    the module's own, the app's namespace for its own) and the values of the sentence. ``after``: an app's point
    stands after this common point (``""``: at the end)."""

    key: str
    state: str
    title: str
    text: str
    values: Mapping[str, object] = field(default_factory=dict)
    after: str = ""

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError(f"state {self.state!r} is none of {STATES}")
        if self.after and self.after not in POINTS:
            raise ValueError(f"after {self.after!r} is no common point")

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "state": self.state,
            "title": self.title,
            "text": self.text,
            "values": dict(self.values),
        }


@dataclass(frozen=True)
class Readiness:
    points: tuple[Point, ...]

    @property
    def state(self) -> str:
        """The worst state of all points: the colour of the card's symbol."""
        return max((point.state for point in self.points), key=_RANK.__getitem__, default=OK)

    @property
    def open(self) -> int:
        """How many points are not ``ok``."""
        return sum(1 for point in self.points if point.state != OK)

    def as_dict(self) -> dict[str, object]:
        return {"state": self.state, "open": self.open, "points": [point.as_dict() for point in self.points]}


def _common(key: str, state: str, variant: str, **values: object) -> Point:
    return Point(key, state, f"account.ready.{key}.title", f"account.ready.{key}.{variant}", values)


def brake_works() -> bool:
    """The brake's own test: a fresh brake lets five tries of one account through and holds the sixth."""
    test = brake.Brake()
    keys = ("sender:selftest", "account:selftest")
    for _ in range(brake.FREE["account"]):
        if test.claim(keys, now=0.0) > 0:
            return False
    return test.claim(keys, now=0.0) > 0


def _networks(entries: Sequence[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    found = []
    for entry in entries:
        for part in str(entry).split(","):
            text = part.strip()
            if not text:
                continue
            try:
                found.append(ipaddress.ip_network(text, strict=False))
            except ValueError:
                continue
    return found


def public_networks(entries: Sequence[str]) -> list[str]:
    """Trusted proxies that are public networks, or reach beyond one private block (``0.0.0.0/0``): anybody could then
    make up a sender."""
    return [
        str(network)
        for network in _networks(entries)
        if not (network.is_private or network.is_loopback or network.is_link_local)
    ]


def _variable(name: str) -> str:
    return config.current().app_name.upper().replace("-", "_") + "_" + name


def check(
    *,
    public_url: str,
    request_https: bool,
    factor_required: bool,
    own_factor: bool,
    trusted_proxies: Sequence[str] = (),
    peer: str = "",
    forwarded: bool = False,
    cookie_secure: str = "auto",
    providers_checking: Sequence[str] = (),
    session_days: int = sessions.REMEMBER_DAYS,
    factor_off: bool | None = None,
    works: bool | None = None,
    proxies_variable: str = "",
    cookie_variable: str = "",
    extra: Sequence[Point] = (),
) -> Readiness:
    """The points for the page. What the app knows of the request: ``request_https`` (after the trusted proxy's
    ``X-Forwarded-Proto``), ``peer`` (the address that connected), ``forwarded`` (an ``X-Forwarded-For`` came). Its
    settings: ``public_url``, ``factor_required``, ``trusted_proxies`` (the list as configured), ``cookie_secure``
    (``auto``, ``on``, ``off``), the names of its variables (default ``<APP>_TRUSTED_PROXIES``,
    ``<APP>_COOKIE_SECURE``). ``own_factor``: the operator's account has a second factor (``signin.has_own_factor``).
    ``providers_checking``: the labels of active providers that check the second factor themselves. ``extra``: the
    app's own points."""
    proxies_variable = proxies_variable or _variable("TRUSTED_PROXIES")
    cookie_variable = cookie_variable or _variable("COOKIE_SECURE")
    app = config.current().app_name
    points: list[Point] = []

    url = (public_url or "").strip()
    if not url:
        points.append(_common("address", BAD, "missing", app=app))
    elif not url.lower().startswith("https://"):
        points.append(_common("address", BAD, "bad", address=url, app=app))
    elif not request_https:
        points.append(_common("address", WARN, "warn", address=url, app=app, variable=proxies_variable))
    else:
        points.append(_common("address", OK, "ok", address=url, app=app))

    off = factor.switched_off() if factor_off is None else factor_off
    if off:
        points.append(_common("factorForAll", BAD, "off", variable=config.current().second_factor_off_env, app=app))
    elif not factor_required:
        points.append(_common("factorForAll", BAD, "bad"))
    elif providers_checking:
        points.append(_common("factorForAll", WARN, "warn", providers=", ".join(providers_checking), app=app))
    else:
        points.append(_common("factorForAll", OK, "ok"))

    points.append(_common("ownAccount", OK if own_factor else BAD, "ok" if own_factor else "bad"))

    networks = _networks(trusted_proxies)
    public = public_networks(trusted_proxies)
    try:
        address = ipaddress.ip_address((peer or "").strip())
        peer_trusted = any(address in network for network in networks)
    except ValueError:
        peer_trusted = False
    unknown_proxy = forwarded and not peer_trusted
    working = brake_works() if works is None else works
    if public:
        points.append(_common("brake", BAD, "bad", networks=", ".join(public)))
    elif not working:
        points.append(_common("brake", BAD, "broken", app=app))
    elif unknown_proxy:
        points.append(_common("brake", WARN, "warn", app=app))
    else:
        points.append(_common("brake", OK, "ok"))

    secure = (cookie_secure or "auto").strip().lower()
    if secure in {"off", "false", "0", "no"}:
        points.append(_common("cookies", BAD, "bad", variable=cookie_variable))
    elif not request_https:
        points.append(_common("cookies", WARN, "warn", app=app))
    else:
        points.append(_common("cookies", OK, "ok", count=session_days))

    if public:
        points.append(_common("proxy", BAD, "bad", networks=", ".join(public), variable=proxies_variable))
    elif unknown_proxy:
        points.append(_common("proxy", WARN, "warn", proxy=peer, variable=proxies_variable))
    elif peer_trusted:
        points.append(_common("proxy", OK, "ok", proxies=", ".join(str(network) for network in networks)))
    else:
        points.append(_common("proxy", OK, "direct"))

    ordered: list[Point] = []
    for point in points:
        ordered.append(point)
        ordered.extend(own for own in extra if own.after == point.key)
    ordered.extend(own for own in extra if not own.after)
    return Readiness(tuple(ordered))
