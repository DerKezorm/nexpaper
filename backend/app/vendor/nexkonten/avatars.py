"""Profile pictures: upload, remove, deliver, who may see them.

What comes in is any picture a phone or camera makes (JPEG, PNG, WebP, GIF, BMP, HEIC and AVIF where the app has
``pillow_heif``), told by its first bytes, never by a name; what is kept is a square WebP of 256 pixels, drawn anew:
no place, no device, no hidden second picture survives. At most 20 MB and 36 million pixels; at most two pictures
are decoded at the same moment, a third waits for a free place (``avatars_busy`` with a wait, instead of a spike of
memory). The app stores the bytes in its own column (``avatar``, ``avatar_at``; nexmail ``profilbild``).

Who sees a picture: every signed-in account of the server, in every app alike; nobody signed out. The picture of a
blocked or deleted account only the operator.

Delivery: ``image/webp`` (a picture of an older version in its own type) under the app's fixed address with
``?v=<time it was set>``, cached for a year
(``immutable``), and an ``ETag`` from its bytes for native apps that ask with ``If-None-Match``.
"""

from __future__ import annotations

import hashlib
import io
import struct
import threading
from dataclasses import dataclass
from datetime import datetime

from .common import log, utcnow
from .errors import AccountError
from .model import PICTURE_OWN, Account, AccountId
from .model2 import PictureStore

SIZE = 256
QUALITY = 85
#: Since 1.0.0 by name: the largest picture in MB, in the sentence ``account.error.avatar_too_large`` (``{{mb}}``,
#: ``AVATAR_MAX_MB`` and ``kontenVariables`` in ``konten.ts``) and in the answer (``mb``).
MAX_MB = 20
MAX_BYTES = MAX_MB * 1024 * 1024
MAX_PIXELS = 36_000_000
DECODERS = 2
BUSY_WAIT_SECONDS = 2
KINDS = {"jpeg", "png", "webp", "gif", "bmp", "heic", "avif"}
_AVIF = {b"avif", b"avis"}
_HEIF = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}

_places = threading.BoundedSemaphore(DECODERS)


def kind_of(head: bytes) -> str | None:
    """The kind of a file by its first bytes."""
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if head.startswith(b"BM") and len(head) > 14:
        return "bmp"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        length = struct.unpack(">I", head[:4])[0]
        brands = {head[8:12]} | {head[index : index + 4] for index in range(16, min(length, len(head)) - 3, 4)}
        if brands & _AVIF:
            return "avif"
        if brands & _HEIF:
            return "heic"
    return None


def too_large() -> AccountError:
    return AccountError("avatar_too_large", f"The picture is larger than {MAX_MB} MB.", 422, mb=MAX_MB)


def not_a_picture() -> AccountError:
    return AccountError("avatar_not_a_picture", "This is not a picture we can read.", 422)


def draw(data: bytes) -> bytes:
    """The square WebP of a picture, upright and cut to its middle. ``avatar_too_large``, ``avatar_not_a_picture``,
    or ``avatars_busy`` when two pictures are being decoded already."""
    if len(data) > MAX_BYTES:
        raise too_large()
    kind = kind_of(data[:64])
    if kind not in KINDS:
        raise not_a_picture()
    if not _places.acquire(blocking=False):
        raise AccountError("avatars_busy", "Too many pictures at once. Try again in a moment.", 503,
                           retry_after=BUSY_WAIT_SECONDS)
    try:
        return _draw(data, kind)
    finally:
        _places.release()


def _draw(data: bytes, kind: str) -> bytes:
    from PIL import Image, ImageOps

    if kind in ("heic", "avif"):
        try:
            import pillow_heif  # type: ignore[import-not-found]
        except ImportError as error:
            raise not_a_picture() from error
        pillow_heif.register_heif_opener()
    try:
        with Image.open(io.BytesIO(data)) as picture:
            if picture.width * picture.height > MAX_PIXELS:
                raise too_large()
            upright = ImageOps.exif_transpose(picture)
            square = ImageOps.fit(upright.convert("RGBA"), (SIZE, SIZE), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            square.save(out, format="WEBP", quality=QUALITY, method=4)
            return out.getvalue()
    except AccountError:
        raise
    except Image.DecompressionBombError as error:
        raise too_large() from error
    except Exception as error:  # a broken file makes Pillow raise anything
        raise not_a_picture() from error


def set_own(store: PictureStore, account_id: AccountId, data: bytes) -> datetime:
    """The person's own picture, drawn and stored; the time it was set (for ``?v=``). The app commits."""
    drawn = draw(data)
    at = utcnow()
    store.set_picture(account_id, drawn, at, PICTURE_OWN)
    log().info("Profile picture set account=%s", account_id)
    return at


def remove(store: PictureStore, account_id: AccountId) -> None:
    store.remove_picture(account_id)


def may_see(viewer: Account | None, owner: Account | None) -> bool:
    """Every signed-in account sees every picture; a blocked or deleted owner's only the operator."""
    if viewer is None or viewer.blocked or owner is None:
        return False
    return not owner.blocked or viewer.operator or viewer.id == owner.id


def etag(data: bytes) -> str:
    return '"' + hashlib.sha256(data).hexdigest()[:32] + '"'


@dataclass(frozen=True)
class Delivery:
    """What the app answers: 200 with ``data`` and ``headers``, or 304 when ``not_modified``."""

    data: bytes
    headers: dict[str, str]
    not_modified: bool = False


def deliver(store: PictureStore, viewer: Account | None, owner: Account | None, if_none_match: str = "") -> Delivery:
    """The picture for an address; ``not_found`` (404) when there is none or the viewer may not see it."""
    if owner is None or not may_see(viewer, owner):
        raise AccountError("not_found", "No such picture.", 404)
    found = store.picture_of(owner.id)
    if found is None:
        raise AccountError("not_found", "No such picture.", 404)
    data, _ = found
    tag = etag(data)
    # A picture of an older version may be a PNG or JPEG: it keeps its own type until the person sets a new one.
    kind = kind_of(data[:64]) or "webp"
    headers = {
        "Content-Type": f"image/{kind}",
        "Cache-Control": "private, max-age=31536000, immutable",
        "ETag": tag,
        "X-Content-Type-Options": "nosniff",
    }
    if if_none_match and tag in [part.strip() for part in if_none_match.split(",")]:
        return Delivery(b"", headers, not_modified=True)
    return Delivery(data, headers)


def version(at: datetime | None) -> str:
    """The ``v`` of the address: changes with every new picture."""
    return str(int(at.timestamp())) if at else ""


def placeholder(name: str) -> tuple[str, int]:
    """The picture for an account without a photo: one letter and a hue (0 to 359) from the name, the same as
    ``avatarPlaceholder`` in ``konten.ts`` (FNV-1a over the name in small letters)."""
    text = (name or "").strip()
    letter = text[:1].upper()[:1] if text else "?"
    value = 0x811C9DC5
    for byte in text.lower().encode("utf-8"):
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return letter, value % 360
