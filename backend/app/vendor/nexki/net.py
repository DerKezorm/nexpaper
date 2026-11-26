"""Where a request to an AI service may go, and how it goes there. Taken over from nexpaper (``services/outbound.py``),
where nexlore's security review was worked out, and the one place of the module that speaks to the network.

* **Resolved once, connected to exactly what was checked.** The name is looked up once per request; every address it
  gives is checked, and the connection goes to those addresses (tried in turn), never to a second lookup that could
  answer differently (DNS rebinding). Host header and TLS name stay the name that was typed.
* **Some addresses never**, whatever anybody types or allows: link-local (169.254.0.0/16, fe80::/10), multicast, the
  unspecified address, and the metadata services of cloud machines (``METADATA``), also where they hide inside an
  IPv6 address (mapped, NAT64, 6to4).
* **The own network only where it is allowed** (``place``): the operator's service may lie there (Ollama at home), an
  account's own service only on a host the operator listed (decision K4). A service on the internet only over https.
  A name that points into the own network and onto the internet at once is refused.
* **No redirect is followed** (that led into the own network in nexlore), no proxy and no certificates come from the
  environment, the answer is read up to a size, and the whole request, the answer read included, has one deadline: a
  service that sends a byte now and then holds nobody longer than that. The deadline sits in the socket itself
  (``DeadlineBackend``): every read and write waits at most for what is left of it.
"""
from __future__ import annotations

import ipaddress
import itertools
import socket
import ssl
import threading
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import cache
from typing import Any
from urllib.parse import urlsplit

import httpcore
import httpx

from .errors import AiRefused

IP = ipaddress.IPv4Address | ipaddress.IPv6Address

#: The metadata services of cloud machines (AWS, Azure, Google, Alibaba, Oracle, ECS tasks): never, not even when an
#: operator types or allows one. Most lie in link-local space, which is refused anyway; these say it out loud.
METADATA = frozenset(
    ipaddress.ip_address(address)
    for address in (
        "169.254.169.254",
        "169.254.170.2",
        "169.254.170.23",
        "169.254.169.253",
        "fd00:ec2::254",
        "fd00:ec2::23",
        "fd00:ec2::253",
        "100.100.100.200",
        "192.0.0.192",
    )
)
#: NAT64 (RFC 6052): an IPv4 address in the last 32 bits.
NAT64 = ipaddress.ip_network("64:ff9b::/96")


class Unreachable(Exception):
    """The name does not resolve."""


class Refused(Exception):
    """An address that is never reached, or one the caller's rule turns down; ``reason`` says which."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TooLarge(Exception):
    """The answer was larger than allowed."""


class Late(Exception):
    """The deadline passed while the answer was read."""


def ip_of(address: str) -> IP:
    """The address as an IP, an IPv4 mapped into IPv6 as the IPv4 it is. ``ValueError`` for anything else."""
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def inner(ip: IP) -> list[IP]:
    """The address and every IPv4 address it carries inside (NAT64, 6to4): a way to 169.254.169.254 through a
    translator is still a way to it."""
    found: list[IP] = [ip]
    if isinstance(ip, ipaddress.IPv6Address):
        if ip in NAT64:
            found.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        if ip.sixtofour is not None:
            found.append(ip.sixtofour)
    return found


def never(ip: IP) -> bool:
    """Whether an address is never reached, by anybody."""
    return any(one.is_link_local or one.is_multicast or one.is_unspecified or one in METADATA for one in inner(ip))


def public(address: str) -> bool:
    """Whether an address lies outside every own, shared or special network."""
    try:
        ip = ip_of(address)
    except ValueError:
        return False
    for one in inner(ip):
        special = one.is_multicast or one.is_reserved or one.is_loopback or one.is_link_local or one.is_private
        if special or not one.is_global:
            return False
    return True


def resolve(host: str, port: int) -> list[str]:
    """Every address of a name, each once, in the order the system gives them. ``Unreachable`` when there is none."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise Unreachable(host) from exc
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


@dataclass(frozen=True)
class Target:
    """Where a request really goes: every address checked, to be tried in turn, with the name kept for Host and
    TLS."""

    urls: tuple[str, ...]
    host: str
    named: str
    scheme: str
    port: int
    addresses: tuple[str, ...]


def port_of(url: str) -> int:
    """The port of an address, written or the scheme's own. ``ValueError`` when it is not a number."""
    parts = urlsplit(url)
    return parts.port or (443 if parts.scheme == "https" else 80)


def pin(url: str, resolver: Callable[[str, int], list[str]], rule: Callable[[IP], None]) -> Target:
    """The address resolved once and checked: no address that is ``never`` reached, and each one past ``rule``
    (which raises ``Refused`` for what the caller turns down). The caller checked scheme, host and credentials."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    port = port_of(url)
    addresses = resolver(host, port)
    if not addresses:
        raise Unreachable(host)
    for address in addresses:
        try:
            ip = ip_of(address)
        except ValueError as exc:
            raise Refused("refused") from exc
        if never(ip):
            raise Refused("refused")
        rule(ip)
    urls = tuple(parts._replace(netloc=f"[{address}]:{port}" if ":" in address else f"{address}:{port}").geturl()
                 for address in addresses)
    # An address literal of IPv6 stands in brackets in the Host header, as in the address itself.
    shown = f"[{host}]" if ":" in host else host
    return Target(
        urls=urls,
        host=host,
        named=shown if port in (80, 443) else f"{shown}:{port}",
        scheme=parts.scheme,
        port=port,
        addresses=tuple(addresses),
    )


def host_entries(host: str, port: int, addresses: Iterable[str]) -> set[str]:
    """The forms in which the operator's list may name a host: the name, the name with its port, each address, each
    address with the port (IPv6 in brackets)."""
    shown = f"[{host}]" if ":" in host else host
    found = {host, f"{shown}:{port}"}
    for address in addresses:
        bare = address.split("%", 1)[0]
        found |= {bare, f"[{bare}]:{port}" if ":" in bare else f"{bare}:{port}"}
    return found


def check_url(url: str) -> None:
    """The form of an address before anything is resolved: http or https, a host, no credentials, no query, no
    fragment, a port that is a number, at most 255 characters."""
    if len(url) > 255:
        raise AiRefused("ai_address_invalid")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise AiRefused("ai_address_invalid")
    if parts.query or parts.fragment:
        raise AiRefused("ai_address_invalid")
    try:
        port_of(url)
    except ValueError as exc:
        raise AiRefused("ai_address_invalid") from exc


def place(
    url: str,
    *,
    operator: bool,
    listed: Iterable[str],
    resolver: Callable[[str, int], list[str]],
) -> tuple[Target, bool]:
    """Where a request to ``url`` goes, resolved once and checked, and whether that lies in the own network.

    Never: link-local, multicast, unspecified, metadata (``ai_address_refused``). All addresses of a name on the same
    side (``ai_address_mixed``). On the internet: https only (``ai_https_required``). In the own network (loopback
    included): the operator's service always, an account's own service only when its host stands on the operator's
    list ``listed`` (``ai_address_private``)."""
    check_url(url)
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    port = port_of(url)
    try:
        addresses = resolver(host, port)
    except Unreachable as exc:
        raise AiRefused("ai_unreachable") from exc
    if not addresses:
        raise AiRefused("ai_unreachable")
    sides = set()
    for address in addresses:
        try:
            ip = ip_of(address)
        except ValueError as exc:
            raise AiRefused("ai_address_refused") from exc
        if never(ip):
            raise AiRefused("ai_address_refused")
        sides.add(public(address))
    if len(sides) > 1:
        raise AiRefused("ai_address_mixed")
    local = sides == {False}
    if not local and parts.scheme != "https":
        raise AiRefused("ai_https_required")
    if local and not operator:
        allowed = {entry.strip().lower() for entry in listed}
        if not host_entries(host, port, addresses) & allowed:
            raise AiRefused("ai_address_private")

    def rule(ip: IP) -> None:  # checked above already, address by address
        return None

    try:
        target = pin(url, lambda _host, _port: list(addresses), rule)
    except Refused as exc:
        raise AiRefused("ai_address_refused") from exc
    return target, local


@cache
def tls() -> ssl.SSLContext:
    """The certificates, loaded once (a new client loads them again each time; under Windows that alone took 0.9 s in
    nexlore)."""
    return httpx.create_ssl_context(trust_env=False)


# --- The deadline in the socket --------------------------------------------------------------------------------------

#: The deadline of the request running in this thread, and the clock it is measured on (``send`` sets both).
_running = threading.local()


def _left() -> float | None:
    deadline = getattr(_running, "deadline", None)
    if deadline is None:
        return None
    return deadline - _running.ticks()


def _bounded(timeout: float | None) -> float | None:
    """The time one read or write may wait: what the caller allows, never more than is left of the deadline."""
    left = _left()
    if left is None:
        return timeout
    if left <= 0:
        raise httpcore.ReadTimeout("the deadline passed")
    return left if timeout is None else min(timeout, left)


class _DeadlineStream(httpcore.NetworkStream):
    def __init__(self, inner: httpcore.NetworkStream) -> None:
        self._inner = inner

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self._inner.read(max_bytes, _bounded(timeout))

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._inner.write(buffer, _bounded(timeout))

    def close(self) -> None:
        self._inner.close()

    def start_tls(self, ssl_context: ssl.SSLContext, server_hostname: str | None = None,
                  timeout: float | None = None) -> httpcore.NetworkStream:
        return _DeadlineStream(self._inner.start_tls(ssl_context, server_hostname, _bounded(timeout)))

    def get_extra_info(self, info: str) -> Any:
        return self._inner.get_extra_info(info)


class DeadlineBackend(httpcore.NetworkBackend):
    """The sockets of ``client``: each read, write and TLS handshake waits at most for what is left of the deadline of
    the request in this thread."""

    def __init__(self, inner: httpcore.NetworkBackend | None = None) -> None:
        self._inner = inner or httpcore.SyncBackend()

    def connect_tcp(self, host: str, port: int, timeout: float | None = None, local_address: str | None = None,
                    socket_options: Iterable[Any] | None = None) -> httpcore.NetworkStream:
        return _DeadlineStream(self._inner.connect_tcp(host, port, _bounded(timeout), local_address, socket_options))

    def connect_unix_socket(self, path: str, timeout: float | None = None,
                            socket_options: Iterable[Any] | None = None) -> httpcore.NetworkStream:
        raise httpcore.ConnectError("no unix sockets here")

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


def transport() -> httpx.HTTPTransport:
    """httpx's own transport, with sockets that keep the deadline (``DeadlineBackend``)."""
    made = httpx.HTTPTransport(verify=tls(), trust_env=False)
    pool = made._pool
    if not hasattr(pool, "_network_backend"):
        raise RuntimeError("httpcore changed: the deadline cannot be set in the socket")
    pool._network_backend = DeadlineBackend(pool._network_backend)
    return made


def client(chosen: httpx.BaseTransport | None) -> httpx.Client:
    """A client that follows no redirect, reads no proxy or certificate from the environment, and keeps the deadline
    in its sockets (a stand-in transport of the tests is taken as it is)."""
    return httpx.Client(follow_redirects=False, transport=chosen or transport(), trust_env=False, verify=tls())


def send(
    session: httpx.Client,
    method: str,
    place: Target,
    headers: dict[str, str],
    *,
    deadline: float,
    ticks: Callable[[], float],
    limit: int,
    connect_seconds: float,
    accept: Callable[[httpx.Response], None] | None = None,
    **sent: Any,
) -> httpx.Response:
    """One request to the checked addresses, tried in turn while one cannot be connected to; never a redirect
    followed, the answer read up to ``limit`` bytes (``TooLarge``) and only until the deadline (``Late``).
    ``accept`` sees the head of the answer before its body is read and may refuse it (a wrong type of content)."""
    extensions = {"sni_hostname": place.host} if place.scheme == "https" else {}
    _running.deadline, _running.ticks = deadline, ticks
    try:
        return _send(session, method, place, headers, extensions, deadline, ticks, limit, connect_seconds, accept,
                     **sent)
    except httpx.TimeoutException as exc:
        # A socket that waited out the rest of the deadline: late, whatever part of the answer it was.
        if ticks() >= deadline:
            raise Late from exc
        raise
    finally:
        _running.deadline = None


def _send(session: httpx.Client, method: str, place: Target, headers: dict[str, str], extensions: dict[str, Any],
          deadline: float, ticks: Callable[[], float], limit: int, connect_seconds: float,
          accept: Callable[[httpx.Response], None] | None, **sent: Any) -> httpx.Response:
    last: Exception | None = None
    for url in place.urls:
        left = deadline - ticks()
        if left <= 0:
            raise Late
        timeout = httpx.Timeout(left, connect=min(connect_seconds, left))
        try:
            # Nothing packed, please: a packed answer is unpacked here piece by piece, never at once (a bomb).
            asked = {**headers, "Host": place.named, "Accept-Encoding": "identity"}
            with session.stream(method, url, headers=asked, extensions=extensions,
                                timeout=timeout, **sent) as answer:
                if accept is not None:
                    accept(answer)
                declared = answer.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > limit:
                    raise TooLarge
                body = _read(answer, limit, deadline, ticks)
                # Unpacked already: the new answer must not say it is packed, or it is unpacked a second time.
                kept = [(name, value) for name, value in answer.headers.multi_items()
                        if name.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
                return httpx.Response(answer.status_code, headers=kept, content=body, request=answer.request)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # The next address checked, if there is one: localhost may name ::1 first while the service is on IPv4.
            last = exc
    assert last is not None
    raise last


def _read(answer: httpx.Response, limit: int, deadline: float, ticks: Callable[[], float]) -> bytes:
    """The body as it came, or unpacked from gzip or deflate in bounded steps: never more than ``limit`` bytes in
    memory, however small the packed answer. Any other packing is refused."""
    encoding = answer.headers.get("content-encoding", "identity").strip().lower()
    if encoding not in ("", "identity", "gzip", "x-gzip", "deflate"):
        raise Refused("encoding")
    unpack = None if encoding in ("", "identity") else zlib.decompressobj(zlib.MAX_WBITS | 32)
    body = bytearray()
    try:
        chunks = answer.iter_raw()
        first = next(chunks, b"")
    except httpx.StreamConsumed:
        # An answer made in memory (a stand-in in the tests): its body is there already, unpacked.
        content = answer.content
        if len(content) > limit:
            raise TooLarge from None
        return content
    for chunk in itertools.chain([first], chunks):
        if unpack is None:
            body.extend(chunk)
        else:
            data = chunk
            while data:
                try:
                    body.extend(unpack.decompress(data, limit - len(body) + 1))
                except zlib.error as exc:
                    raise Refused("encoding") from exc
                if len(body) > limit:
                    raise TooLarge
                data = unpack.unconsumed_tail
        if len(body) > limit:
            raise TooLarge
        if ticks() > deadline:
            raise Late
    return bytes(body)
