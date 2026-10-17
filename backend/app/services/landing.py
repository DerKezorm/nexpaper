"""The page a sign-in through a provider started from (an app's request to be paired, say): it survives the trip to
the provider.

The shared sign-in module carries what the protocol needs in its attempt cookie; where nexpaper lands afterwards is
nexpaper's own business. The page travels in a cookie of its own beside the attempt, signed with a key derived from
the server secret, and is checked with ``safe_next`` going in and coming back: only a path of nexpaper itself, never
another host.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from ..config import get_settings

#: The cookie beside the attempt cookie, as long-lived as the attempt.
COOKIE = "nexpaper_oidc_next" + get_settings().cookie_name_suffix()
MINUTES = 10
#: The longest page a sign-in comes back to (the address of an app's request with its PKCE challenge fits easily).
NEXT_MAX = 1000


def safe_next(value: object) -> str | None:
    """A path of nexpaper itself to come back to after the sign-in, or None. Only ``/something``: never ``//host``,
    never a backslash (browsers read ``/\\host`` as another site), no control character or space a browser would drop
    or fold, nothing longer than ``NEXT_MAX``."""
    if not isinstance(value, str) or not value or len(value) > NEXT_MAX:
        return None
    if not value.startswith("/") or value.startswith("//") or value == "/":
        return None
    if "\\" in value or any(ord(char) <= 32 or ord(char) == 127 or 0x80 <= ord(char) <= 0x9F for char in value):
        return None
    return value


def _key() -> bytes:
    secret = get_settings().resolved_secret_key().encode("utf-8")
    return hashlib.sha256(b"nexpaper-oidc-next:" + secret).digest()


def _signature(page: str) -> str:
    digest = hmac.new(_key(), page.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def pack(page: str | None) -> str | None:
    """The cookie value for a page (the page in base64, a dot, its signature: nothing a cookie has to quote), or None
    when it is not one to land on."""
    landing = safe_next(page)
    if not landing:
        return None
    encoded = base64.urlsafe_b64encode(landing.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{encoded}.{_signature(landing)}"


def read(value: str | None) -> str | None:
    """The page from the cookie: signed by this server and still a path of nexpaper's own, else None."""
    if not value or value.count(".") != 1:
        return None
    encoded, signature = value.split(".")
    try:
        page = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    if not hmac.compare_digest(signature.encode(), _signature(page).encode()):
        return None
    return safe_next(page)
