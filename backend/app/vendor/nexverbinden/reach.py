"""Asking a partner app: its address in a clean form, the rule for where the server asks at all, and one request with
the rules of ``outbound`` (as nextime and nexnotes asked their nextasks).

* The address: ``http`` or ``https``, a host, no credentials, query or fragment, a sub-path allowed; ports below 1024
  only 80 and 443; the machine itself by name never.
* Where it points is checked at every request: public addresses always, the own network (10/8, 172.16/12, 192.168/16,
  100.64/10, fc00::/7, fec0::/10) only with the operator's switch, the machine itself, link-local and the metadata of
  cloud machines never.
* No redirect is followed, the answer is read up to ``max_answer`` within ``seconds``, the request carries no
  ``Origin``. Every failure on the way is ``Unreachable``; why, the log says, never the page (nobody maps the server's
  network through a form)."""

from __future__ import annotations

import ipaddress
import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from . import outbound
from .errors import Refused
from .shared import oauthcore

logger = logging.getLogger("nexverbinden")

MAX_URL = 500
LOW_PORTS = (80, 443)
LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(net)
    for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7", "fec0::/10")
)
OWN_NAMES = ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback")

#: Stand-ins for the tests: how a name is resolved, the transport (``None``: the network).
RESOLVER = outbound.resolve
TRANSPORT: httpx.BaseTransport | None = None


class Unreachable(Exception):  # noqa: N818
    """Nothing usable came back from the partner (the reason is in the log)."""

    @property
    def local(self) -> bool:
        """Since 0.1.8 (B2): the partner was not asked because its address lies in the own network and the operator
        has not allowed connections there (``connections_local_network``)."""
        return bool(self.args) and self.args[0] == "local"


def clean_url(raw: str) -> str:
    """The address in its form (blanks at the edges and a slash at the end gone), or ``Refused``."""
    url = (raw or "").strip().rstrip("/")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise Refused("address_invalid") from exc
    if (
        len(url) > MAX_URL
        or parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.query
        or parts.fragment
        or parts.username
        or parts.password
        or "?" in url
        or "#" in url
        or (port is not None and not 0 < port < 65536)
    ):
        raise Refused("address_invalid")
    if port is not None and port < 1024 and port not in LOW_PORTS:
        raise Refused("address_port")
    host = parts.hostname.lower().rstrip(".")
    if not oauthcore.safe_host(host):
        # mcp 1.1.1 (M-8): no wildcard and no letter of another script that looks Latin, as for return addresses.
        raise Refused("address_invalid")
    if host in OWN_NAMES or host.endswith(".localhost"):
        raise Refused("address_refused")
    return url


def same_place(first: str, second: str) -> bool:
    """Whether two addresses name the same app (scheme, host, port and path, without the slash at the end)."""
    try:
        return clean_url(first).lower() == clean_url(second).lower()
    except Refused:
        return False


def _local(ip: outbound.IP) -> bool:
    return any(ip in net for net in LOCAL_NETWORKS if ip.version == net.version)


def address_rule(local_allowed: bool) -> Any:
    def rule(ip: outbound.IP) -> None:
        for one in outbound.inner(ip):
            if one.is_loopback:
                raise outbound.Refused("refused")
            if outbound.public(str(one)):
                continue
            if _local(one):
                if not local_allowed:
                    raise outbound.Refused("local")
                continue
            raise outbound.Refused("refused")

    return rule


@dataclass(frozen=True)
class Answer:
    status: int
    data: Any
    #: The module's or the app's code in ``{"detail": {"code"}}``, or the ``error`` of a token answer.
    code: str


def _code_of(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    detail = data.get("detail")
    if isinstance(detail, dict) and isinstance(detail.get("code"), str):
        return detail["code"]
    return str(data.get("error") or "")


def ask(
    base: str,
    method: str,
    path: str,
    *,
    local_allowed: bool,
    agent: str,
    seconds: float,
    connect_seconds: float,
    limit: int,
    bearer: str | None = None,
    form: dict[str, str] | None = None,
    body: Any = None,
    params: dict[str, str] | dict[str, list[str]] | None = None,
) -> Answer:
    """``<base><path>`` once; the answer whatever its status, ``Unreachable`` when none came that can be read."""
    url = clean_url(base) + path
    if params:
        url += "?" + urlencode(params, doseq=True)
    try:
        place = outbound.pin(url, RESOLVER, address_rule(local_allowed))
    except outbound.Refused as exc:
        logger.info("partner not asked: an address the server does not ask (%s)", exc.reason)
        # Since 0.1.8 (B2): "local" says the address lies in the own network and the operator has not allowed it.
        raise Unreachable("local" if exc.reason == "local" else "refused") from exc
    except outbound.Unreachable as exc:
        logger.info("partner not asked: the name does not resolve")
        raise Unreachable("name") from exc
    headers = {"User-Agent": agent, "Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    sent: dict[str, Any] = {}
    if form is not None:
        sent["content"] = urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        sent["content"] = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        with outbound.client(TRANSPORT) as session:
            answer = outbound.send(
                session,
                method,
                place,
                headers,
                deadline=time.monotonic() + seconds,
                ticks=time.monotonic,
                limit=limit,
                connect_seconds=connect_seconds,
                **sent,
            )
    except (outbound.Late, httpx.TimeoutException) as exc:
        logger.info("partner did not answer in time")
        raise Unreachable("late") from exc
    except outbound.TooLarge as exc:
        logger.info("partner answered more than %s bytes", limit)
        raise Unreachable("large") from exc
    except (outbound.Refused, httpx.HTTPError, OSError) as exc:
        logger.info("no connection to the partner (%s)", type(exc).__name__)
        raise Unreachable("connection") from exc
    if answer.status_code >= 500 or 300 <= answer.status_code < 400:
        # A redirect counts as nothing usable: the module follows none.
        logger.info("partner answered HTTP %s on %s", answer.status_code, path.split("?")[0])
        raise Unreachable("status")
    if answer.status_code == 204 or not answer.content:
        return Answer(answer.status_code, None, "")
    try:
        data = answer.json()
    except ValueError as exc:
        logger.info("partner answered something that is no JSON (HTTP %s)", answer.status_code)
        raise Unreachable("json") from exc
    return Answer(answer.status_code, data, _code_of(data))
