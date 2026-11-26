"""The OAuth core the modules share (since 1.1.0): what ``oauth`` (programs connecting to MCP) and the module
``verbinden`` (nex apps connecting to each other) both need, and nothing that knows MCP. Standard library only.

- ``digest``: the SHA-256 hex every code and token is stored as;
- PKCE with S256 only: ``VERIFIER`` (43 to 128 characters of RFC 7636), ``verifier_fits`` on the server,
  ``new_verifier`` and ``challenge_of`` for an app that asks;
- ``valid_redirect``: a return address without fragment or user, ``https://``, or ``http://`` to the own machine
  (``http_hosts`` widens the second for an app that runs without TLS itself);
- ``back``: the return address with the answer added to its query;
- ``new_tokens``: an access and a refresh token with their hashes and the access token's end.

A module that uses the core imports it from the package ``nexmcp`` next to it (``app.vendor.nexmcp.oauthcore`` in an
app); the core is changed only here."""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

LOOPBACK = ("localhost", "127.0.0.1", "::1")
VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}")


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def challenge_of(verifier: str) -> str:
    """The S256 code challenge of a verifier (RFC 7636)."""
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def new_verifier() -> str:
    """A fresh PKCE verifier: 43 characters of the unreserved set."""
    return secrets.token_urlsafe(32)


def verifier_fits(verifier: str, challenge: str) -> bool:
    if not VERIFIER.fullmatch(verifier):
        return False
    return secrets.compare_digest(challenge_of(verifier), challenge)


def valid_redirect(uri: object, http_hosts: Iterable[str] = LOOPBACK) -> bool:
    """A return address a server may send a browser to: at most 2048 characters, no blank or control character, a
    host, no fragment, no user or password; ``https://``, or ``http://`` only to one of ``http_hosts``."""
    if not isinstance(uri, str) or not 0 < len(uri) <= 2048 or any(ord(char) < 33 for char in uri):
        return False
    try:
        parts = urlsplit(uri)
        _ = parts.port  # a broken port raises here
    except ValueError:
        return False
    if "#" in uri or parts.username is not None or parts.password is not None or not parts.hostname:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and parts.hostname in set(http_hosts)


def back(redirect_uri: str, values: dict[str, str]) -> str:
    """``redirect_uri`` with ``values`` added to its query (what it had stays)."""
    parts = urlsplit(redirect_uri)
    query = [*parse_qsl(parts.query, keep_blank_values=True), *values.items()]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


@dataclass(frozen=True)
class Tokens:
    """A fresh pair; only the hashes are kept by the server that made it."""

    access: str
    refresh: str
    access_hash: str
    refresh_hash: str
    #: The first characters of the access token, to tell keys apart in a list (``rn_mcp_AbCd``).
    access_shown: str
    access_expires: datetime


def new_tokens(access_prefix: str, refresh_prefix: str, access_hours: int, now: datetime) -> Tokens:
    access = access_prefix + secrets.token_urlsafe(32)
    refresh = refresh_prefix + secrets.token_urlsafe(32)
    return Tokens(
        access=access,
        refresh=refresh,
        access_hash=digest(access),
        refresh_hash=digest(refresh),
        access_shown=access[: len(access_prefix) + 4],
        access_expires=now + timedelta(hours=access_hours),
    )
