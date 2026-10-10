"""Profile pictures: what comes in is a picture of any kind a phone or camera makes; what is kept is a square WebP of
``SIZE`` pixels, drawn anew. Nothing of the file that came survives but its pixels: no place, no device, no hidden
second picture, no script in an SVG (an SVG is not taken at all).

Kept in the database next to the account (a few kilobytes), so every backup carries it and nothing lies beside.
Seen by everybody on the server: a household knows each other, and a shared document shows who shared it.
"""

from __future__ import annotations

import io
import logging

from sqlalchemy.orm import Session

from ..models import Account
from . import pictures

logger = logging.getLogger("nexpaper.accounts")

SIZE = 256
#: The same limit for every picture that comes in; the request guard holds the body of ``/api/v1/auth/avatar`` to it
#: (``middleware.LARGE_BODIES``), so both say the same.
MAX_BYTES = pictures.MAX_BYTES
MAX_PIXELS = pictures.MAX_PIXELS
#: What phones and cameras make. The decoder opens more (TIFF, PSD, EPS, which would start Ghostscript): not here.
KINDS = {"jpeg", "png", "webp", "gif", "bmp", "heic", "avif"}
sniff = pictures.sniff


class AvatarError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def make(data: bytes) -> bytes:
    """The square WebP of a picture, upright and cut to its middle. ``AvatarError`` for anything else."""
    from PIL import Image, ImageOps

    try:
        with pictures.opened(data, KINDS) as image:
            upright = ImageOps.exif_transpose(image)
            square = ImageOps.fit(upright.convert("RGBA"), (SIZE, SIZE), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            square.save(out, "WEBP", quality=85, method=4, exif=b"", xmp=b"")
            return out.getvalue()
    except pictures.PictureError as exc:
        raise AvatarError("avatar_too_large" if exc.reason == "size" else "avatar_not_a_picture") from exc


def may_see(db: Session, viewer: Account, owner_id: int) -> bool:
    """Everybody on the server sees everybody's name and picture: a household knows each other's faces, and a shared
    document shows who it comes from."""
    return True
