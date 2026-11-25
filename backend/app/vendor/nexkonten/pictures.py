"""A provider's picture for an account that has none.

A new account through a provider takes the provider's picture, and an account without any picture gets it at its next
sign-in through the provider. A picture the person set is never replaced; neither is one taken from a provider before
(the person can remove it, then the next sign-in takes the provider's again).

The address comes from the provider's token, so it is fetched with care:

- only ``https``, or ``http`` when the issuer itself is ``http``; only from the issuer's host (on the issuer's port or
  the scheme's own); or a ``data:image/…;base64,`` address;
- a redirect only to an address that passes the same rules, at most ``MAX_REDIRECTS``;
- at most ``MAX_BYTES`` and ``TIMEOUT`` seconds in all, held by a watchdog: a server that sends its headers drop by
  drop is cut off when the time is up, whatever httpx's own timeouts say;
- only PNG, JPEG, WebP, GIF, told by the first bytes and opened by Pillow with exactly these decoders, at most
  ``MAX_SIDE`` pixels a side, then written anew (PNG, a JPEG stays JPEG; the first frame of an animation): of the file
  only its picture survives, no metadata, no hidden second image.

Whatever fails, the account stays without a picture, one line goes to the log, and the sign-in goes on.
"""

from __future__ import annotations

import base64
import binascii
import io
import threading
import time
from urllib.parse import SplitResult, urljoin, urlsplit

import httpx

from . import config
from .common import log
from .errors import PictureRefused
from .model import PICTURE_NONE, AccountId, Picture, Store

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 5.0
MAX_SIDE = 4096
MAX_REDIRECTS = 3
#: What the first bytes tell, and the decoder Pillow may use for it.
FORMATS = {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP", "gif": "GIF"}
DATA_TYPES = {"image/png": "png", "image/jpeg": "jpeg", "image/jpg": "jpeg", "image/webp": "webp", "image/gif": "gif"}
_DEFAULT_PORTS = {"http": 80, "https": 443}
_REDIRECTS = {301, 302, 303, 307, 308}


def sniff(head: bytes) -> str | None:
    """The kind of a file by its first bytes, never by a name or a header."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    return None


def _port(parts: SplitResult) -> int | None:
    try:
        port = parts.port
    except ValueError:
        return None
    return port if port is not None else _DEFAULT_PORTS.get(parts.scheme)


def allowed(url: str, issuer: str) -> bool:
    """Whether a picture may be fetched from this address for this issuer (``data:`` addresses aside)."""
    try:
        picture, origin = urlsplit(url), urlsplit(issuer)
    except ValueError:
        return False
    if picture.scheme not in _DEFAULT_PORTS or origin.scheme not in _DEFAULT_PORTS:
        return False
    if picture.scheme == "http" and origin.scheme != "http":
        return False
    if picture.username is not None or picture.password is not None:
        return False
    host = (picture.hostname or "").rstrip(".").lower()
    if not host or host != (origin.hostname or "").rstrip(".").lower():
        return False
    port = _port(picture)
    return port is not None and port in {_port(origin), _DEFAULT_PORTS[picture.scheme]}


def redraw(data: bytes) -> Picture:
    """The picture of a file, written anew; ``PictureRefused`` for anything else."""
    if len(data) > MAX_BYTES:
        raise PictureRefused(f"larger than {MAX_BYTES} bytes")
    kind = sniff(data[:16])
    if kind is None:
        raise PictureRefused("not a PNG, JPEG, WebP or GIF")
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data), formats=[FORMATS[kind]]) as image:
            width, height = image.size
            if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE):
                raise PictureRefused(f"{width}x{height} pixels, at most {MAX_SIDE} a side")
            image.load()
            out = io.BytesIO()
            if kind == "jpeg":
                image.convert("RGB").save(out, format="JPEG", quality=90)
                content_type = "image/jpeg"
            else:
                image.convert("RGBA").save(out, format="PNG")
                content_type = "image/png"
    except PictureRefused:
        raise
    except Exception as error:  # a broken file makes Pillow raise anything: struct, index, zero division
        raise PictureRefused(f"Pillow could not read it ({error.__class__.__name__})") from error
    return Picture(out.getvalue(), content_type, width, height)


def _from_data(url: str) -> bytes:
    header, comma, payload = url.partition(",")
    if not comma:
        raise PictureRefused("a data address without data")
    parts = [part.strip().lower() for part in header[len("data:") :].split(";")]
    if parts[0] not in DATA_TYPES or parts[-1] != "base64":
        raise PictureRefused("a data address that is no base64 picture")
    if len(payload) > (MAX_BYTES * 4) // 3 + 8:
        raise PictureRefused(f"larger than {MAX_BYTES} bytes")
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as error:
        raise PictureRefused("a data address with broken base64") from error


def _client(deadline: float) -> httpx.Client:
    cfg = config.current()
    return httpx.Client(
        transport=config.transport(),
        verify=cfg.ssl_context if cfg.ssl_context is not None else True,
        timeout=httpx.Timeout(max(deadline - time.monotonic(), 0.1)),
        follow_redirects=False,
        trust_env=False,
    )


def _download(url: str, issuer: str, box: dict[str, object]) -> bytes:
    deadline = time.monotonic() + TIMEOUT
    with _client(deadline) as client:
        box["client"] = client
        for _ in range(MAX_REDIRECTS + 1):
            if not allowed(url, issuer):
                raise PictureRefused(f"address not allowed for this issuer (host {urlsplit(url).hostname!r})")
            with client.stream("GET", url, headers={"Accept": "image/*"}) as response:
                if response.status_code in _REDIRECTS:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                if response.status_code != 200:
                    raise PictureRefused(f"the provider answered {response.status_code}")
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > MAX_BYTES:
                    raise PictureRefused(f"larger than {MAX_BYTES} bytes")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise PictureRefused(f"larger than {MAX_BYTES} bytes")
                    if time.monotonic() > deadline:
                        raise PictureRefused(f"took longer than {TIMEOUT} seconds")
                return bytes(body)
    raise PictureRefused(f"more than {MAX_REDIRECTS} redirects")


def fetch_picture(url: str, issuer: str) -> Picture:
    """The provider's picture at ``url`` for a provider with ``issuer``, written anew; ``PictureRefused`` with the
    reason (for the log) for anything that does not pass. Synchronous: run it outside the event loop."""
    text = (url or "").strip()
    if not text:
        raise PictureRefused("no address")
    if text[:5].lower() == "data:":
        return redraw(_from_data(text))
    return redraw(_within_deadline(text, issuer))


def _within_deadline(url: str, issuer: str) -> bytes:
    """``_download`` in a worker that gets ``TIMEOUT`` seconds in all; then its client is closed and the fetch is
    refused, however slowly the server drips."""
    box: dict[str, object] = {}

    def work() -> None:
        try:
            box["data"] = _download(url, issuer, box)
        except Exception as error:  # noqa: BLE001 (handed to the caller below)
            box["error"] = error

    worker = threading.Thread(target=work, name="nexkonten-picture", daemon=True)
    worker.start()
    worker.join(TIMEOUT)
    if worker.is_alive():
        client = box.get("client")
        if isinstance(client, httpx.Client):
            try:
                client.close()
            except Exception:  # noqa: BLE001, S110 (closing a client that hangs; nothing more to do)
                pass
        raise PictureRefused(f"took longer than {TIMEOUT} seconds")
    error = box.get("error")
    if isinstance(error, PictureRefused):
        raise error
    if isinstance(error, httpx.HTTPError):
        raise PictureRefused(f"could not be fetched ({error.__class__.__name__})") from error
    if isinstance(error, Exception):
        raise PictureRefused(f"could not be fetched ({error.__class__.__name__})") from error
    data = box.get("data")
    if not isinstance(data, bytes):
        raise PictureRefused("nothing came")
    return data


def take_provider_picture(store: Store, account_id: AccountId, url: str, issuer: str) -> bool:
    """For an account without any picture: the provider's, fetched and stored. Never raises; False when nothing was
    stored (the account has a picture, no address, or the picture did not pass)."""
    try:
        account = store.get_account(account_id)
        if account is None or account.picture != PICTURE_NONE or not (url or "").strip():
            return False
        try:
            picture = fetch_picture(url, issuer)
        except PictureRefused as error:
            log().warning("Provider picture not taken name=%s: %s", account.username, error)
            return False
        stored = store.set_provider_picture(account.id, picture)
        store.commit()
    except Exception as error:  # noqa: BLE001 (a picture must never break a sign-in)
        store.rollback()
        log().warning("Provider picture not taken for account %s: %r", account_id, error)
        return False
    if stored:
        log().info("Provider picture taken name=%s", account.username)
    return stored
