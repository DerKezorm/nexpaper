"""Requests the server makes to an address somebody typed: the AI service of the operator (``services/ai.py``) and,
in later blocks, the mail, import and push targets. Taken over from nexlore, where it was worked out in a
security review.

* **Resolved once, connected to exactly what was checked.** The name is looked up once per request; every address it
  gives is checked, and the connection goes to those addresses (tried in turn), never to a second lookup that could
  answer differently (DNS rebinding). Host header and TLS name stay the name that was typed.
* **Some addresses never**, whatever anybody types or allows: link-local (169.254.0.0/16, fe80::/10), multicast, the
  unspecified address, and the metadata services of cloud machines (``METADATA``), also where they hide inside an
  IPv6 address (mapped, NAT64, 6to4). Each caller adds its own rule on top (the AI: own network or internet; the others:
  only what the operator allowed).
* **No redirect is followed** (that led into the own network in nexlore), the answer is read up to a size, and the
  whole request, the answer read included, has one deadline: a service that sends a byte now and then holds nobody
  longer than that. The deadline sits in the socket itself (``DeadlineBackend``): every read and write waits at most
  for what is left of it, so a head that comes a line per second ends at the deadline as well, not only the body.
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


# --- A file, straight to the disk (the Paperless import) --------------------------------------------------------------


@dataclass(frozen=True)
class Saved:
    """What ``download`` wrote: the status of the answer, how many bytes, their SHA-256 and the first of them."""

    status: int
    size: int
    sha256: str
    head: bytes


#: How many of the first bytes ``download`` keeps for the check of the kind of a file.
HEAD_BYTES = 4096


def download(
    session: httpx.Client,
    place: Target,
    headers: dict[str, str],
    path: Any,
    *,
    deadline: float,
    ticks: Callable[[], float],
    limit: int,
    connect_seconds: float,
) -> Saved:
    """A ``GET`` whose body goes to the file ``path`` piece by piece (never more than a piece in memory), with the rules
    of ``send``: the checked addresses only, no redirect, at most ``limit`` bytes (``TooLarge``; the file is removed),
    one deadline for all of it (``Late``). An answer that is not 200 writes nothing and gives its status."""
    import hashlib
    from pathlib import Path

    target = Path(path)
    extensions = {"sni_hostname": place.host} if place.scheme == "https" else {}
    _running.deadline, _running.ticks = deadline, ticks
    try:
        last: Exception | None = None
        for url in place.urls:
            left = deadline - ticks()
            if left <= 0:
                raise Late
            timeout = httpx.Timeout(left, connect=min(connect_seconds, left))
            asked = {**headers, "Host": place.named, "Accept-Encoding": "identity"}
            try:
                with session.stream("GET", url, headers=asked, extensions=extensions, timeout=timeout) as answer:
                    if answer.status_code != 200:
                        return Saved(answer.status_code, 0, "", b"")
                    declared = answer.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > limit:
                        raise TooLarge
                    encoding = answer.headers.get("content-encoding", "identity").strip().lower()
                    if encoding not in ("", "identity", "gzip", "x-gzip", "deflate"):
                        raise Refused("encoding")
                    unpack = None if encoding in ("", "identity") else zlib.decompressobj(zlib.MAX_WBITS | 32)
                    digest = hashlib.sha256()
                    head = bytearray()
                    size = 0
                    try:
                        with target.open("wb") as handle:
                            for chunk in answer.iter_raw():
                                pieces = [chunk]
                                if unpack is not None:
                                    pieces = []
                                    data = chunk
                                    while data:
                                        try:
                                            pieces.append(unpack.decompress(data, limit - size + 1))
                                        except zlib.error as exc:
                                            raise Refused("encoding") from exc
                                        data = unpack.unconsumed_tail
                                        if size + sum(len(p) for p in pieces) > limit:
                                            raise TooLarge
                                for piece in pieces:
                                    size += len(piece)
                                    if size > limit:
                                        raise TooLarge
                                    handle.write(piece)
                                    digest.update(piece)
                                    if len(head) < HEAD_BYTES:
                                        head.extend(piece[: HEAD_BYTES - len(head)])
                                if ticks() > deadline:
                                    raise Late
                    except BaseException:
                        target.unlink(missing_ok=True)
                        raise
                    return Saved(200, size, digest.hexdigest(), bytes(head))
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last = exc
        assert last is not None
        raise last
    except httpx.TimeoutException as exc:
        target.unlink(missing_ok=True)
        if ticks() >= deadline:
            raise Late from exc
        raise
    finally:
        _running.deadline = None
