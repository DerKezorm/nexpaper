""""Ready for the internet?": what nexpaper checks about itself before it is reachable from outside.

Each point is ``ok``, ``warn`` or ``bad`` with the values its sentence needs; the interface says what it means and
what helps. Checked at every call, from the request that asks and the server as it stands: nothing is remembered.
"""

from __future__ import annotations

import ipaddress
import os
import stat
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Account
from ..security import Brake
from . import backups, settings_service, totp

OK, WARN, BAD = "ok", "warn", "bad"
#: Whether file modes say anything here: Windows has no owner-only mode to read, the folder's rights decide there.
CHECK_MODE = os.name != "nt"


#: Networks a reverse proxy may sit in: the machine itself, a home or office network, a container network, a VPN.
#: ``X-Forwarded-For`` from anywhere else is not to be believed, whatever the operator wrote.
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(network) for network in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "100.64.0.0/10",
    "::1/128", "fc00::/7", "fe80::/10",
))


@dataclass
class Point:
    key: str
    state: str
    values: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "state": self.state, "values": self.values}


def came_over_https(request: Request) -> bool:
    """The request reached nexpaper over https, or the proxy in front says it did."""
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return request.url.scheme == "https" or forwarded == "https"


def _https(db: Session, request: Request) -> Point:
    public = settings_service.public_url(db)
    if urlsplit(public).scheme != "https":
        return Point("https", BAD, {"address": public})
    if not came_over_https(request):
        return Point("https", WARN, {"address": public})
    return Point("https", OK, {"address": public})


def _two_factor(db: Session) -> Point:
    return Point("two_factor", OK if settings_service.get(db, "two_factor_required") else BAD)


def _own_account(db: Session, operator: Account) -> Point:
    return Point("own_account", OK if totp.has_second_factor(db, operator) else BAD)


def public_proxy_networks(spec: str) -> list[str]:
    """The entries of the list of trusted proxies that are not inside a private network: ``0.0.0.0/0``, ``::/0``, any
    public address or network. Whoever sends from there could write any sender into ``X-Forwarded-For``, and the
    brake against guessing would count a made-up one. Entries that are no address are ignored, as at sign-in."""
    found = []
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        if not any(network.version == private.version and network.subnet_of(private) for private in PRIVATE_NETWORKS):
            found.append(str(network))
    return found


def brake_works() -> bool:
    """Whether the brake against guessing does what it is for, tried on a copy of its own: after the failures it lets
    pass, the sender waits; another sender does not; and the wait ends the sender's count when it is told of a
    success. The brake sign-ins use is not touched."""
    probe = Brake(quiet=True)
    guesser, other = "probe:guesser", "probe:other"
    for _ in range(Brake.FREE):
        if probe.wait_seconds(guesser):
            return False
        probe.failed(guesser)
    held = probe.wait_seconds(guesser) > 0 and probe.wait_seconds(other) == 0
    probe.succeeded(guesser)
    return held and probe.wait_seconds(guesser) == 0


def _brake(unknown_proxy: bool) -> Point:
    # Checked, not taken for granted: the mechanism is tried on a copy, and the list of proxies must not let a
    # stranger choose the sender the brake counts. Behind a proxy nexpaper was not told about, every sender looks
    # alike and only the lock per account is left.
    public = public_proxy_networks(get_settings().trusted_proxies)
    if public:
        return Point("brake", BAD, {"networks": ", ".join(public)})
    if not brake_works():
        return Point("brake", BAD, {"broken": True})
    return Point("brake", WARN if unknown_proxy else OK)


def _secrets() -> Point:
    """``secret.key`` seals what the server must read on its own (OIDC client secret, mail password, AI key): only the
    owner may read it. Given in the environment (``NEXPAPER_SECRET_KEY``), there is no file to look at."""
    if get_settings().secret_key:
        return Point("secrets", OK, {"source": "environment"})
    path = get_settings().data_dir / "secret.key"
    try:
        info = path.stat()
    except OSError:
        return Point("secrets", BAD, {"path": str(path), "missing": True})
    if not CHECK_MODE:
        return Point("secrets", OK, {"path": str(path), "mode": None})
    mode = stat.S_IMODE(info.st_mode)
    open_to_others = bool(mode & 0o077)
    return Point("secrets", BAD if open_to_others else OK, {"path": str(path), "mode": f"{mode:04o}"})


def _cookies(request: Request) -> Point:
    mode = get_settings().cookie_secure.lower()
    if mode == "off":
        return Point("cookies", BAD, {"mode": mode})
    if not came_over_https(request):
        return Point("cookies", WARN, {"mode": mode})
    return Point("cookies", OK, {"mode": mode})


def _proxy(request: Request, unknown_proxy: bool) -> Point:
    if unknown_proxy:
        peer = request.client.host if request.client else ""
        return Point("proxy", WARN, {"proxy": peer})
    trusted = get_settings().trusted_proxies.strip()
    public = public_proxy_networks(trusted)
    if public:
        return Point("proxy", BAD, {"proxies": trusted, "networks": ", ".join(public)})
    return Point("proxy", OK, {"proxies": trusted, "forwarded": bool(request.headers.get("x-forwarded-for"))})


def _backups(db: Session) -> Point:
    """The database, the settings and the secrets are copied regularly (the documents are not part of it)."""
    every = backups.schedule(db)
    return Point("backups", OK if every != "off" else WARN, {"schedule": every})


def check(db: Session, request: Request, operator: Account, unknown_proxy: bool) -> dict[str, Any]:
    points = [
        _https(db, request),
        _two_factor(db),
        _own_account(db, operator),
        _brake(unknown_proxy),
        _secrets(),
        _cookies(request),
        _proxy(request, unknown_proxy),
        _backups(db),
    ]
    return {"points": [point.as_dict() for point in points], "open": sum(point.state != OK for point in points)}
