"""What profile pictures and photos have in common: knowing a picture by its first bytes, the limits on what comes in,
and opening it without letting it take the server down.

* **The kind** is read from the first bytes, never from the name or the type the browser claims. An SVG, an HTML page
  named ``.jpg``, a PDF: none of them is a picture here.
* **The size** is limited twice: the request guard holds the body to ``MAX_BYTES`` before anything reads it
  (``middleware.LARGE_BODIES`` names every route that takes a picture), and the decoder refuses more than
  ``MAX_PIXELS`` before it unpacks a single row (a 1-bit PNG can be tiny on disk and huge in memory).
* **Decoding is rationed**: at most ``NEXPAPER_DECODE_SLOTS`` pictures (one by default) are unpacked at the same moment,
  and at most ``WAITING`` more uploads may hold their body while they wait for a place (``admitted``). Any further one
  is turned away before its body is read (503, ``Retry-After``). A 36-megapixel photo needs some 150 MB while it is
  open; twenty at once from one family must not exhaust a small server.

Whatever is kept is drawn anew from the pixels (``services/avatars.py``, later the pages of documents): no place,
no device, no hidden second picture, no script survives.
"""

from __future__ import annotations

import io
import logging
import struct
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger("nexpaper.pictures")

#: Larger than any photo a phone takes; above it the file is not even opened.
MAX_BYTES = 20 * 1024 * 1024
#: Pixels of the picture that came: more than any phone camera takes in its normal mode (48 MP sensors save 12 MP).
MAX_PIXELS = 36_000_000
#: Uploads that may wait, body in hand, for a free decoder, besides those being unpacked.
WAITING = 3
#: How long an upload waits for a free decoder before the server says it is busy.
DECODER_WAIT_SECONDS = 30

HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1", b"mif2"}
AVIF_BRANDS = {b"avif", b"avis"}

_decoders: threading.BoundedSemaphore | None = None
_admission_lock = threading.Lock()
_admitted = 0
_registered = False


def slots() -> int:
    from ..config import get_settings

    return min(max(int(get_settings().decode_slots), 1), 16)


def _semaphore() -> threading.BoundedSemaphore:
    global _decoders
    with _admission_lock:
        if _decoders is None:
            _decoders = threading.BoundedSemaphore(slots())
        return _decoders


@contextmanager
def admitted() -> Iterator[None]:
    """A place for one upload, taken before its body is read: unpacking or waiting to. ``DecodersBusy`` at once when
    every place is taken, so that no more bodies are held in memory than ``slots() + WAITING``."""
    global _admitted
    with _admission_lock:
        if _admitted >= slots() + WAITING:
            raise DecodersBusy
        _admitted += 1
    try:
        yield
    finally:
        with _admission_lock:
            _admitted -= 1


class PictureError(ValueError):
    """Not a picture this server takes (``kind``), or one too large (``size``)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DecodersBusy(RuntimeError):
    """Every place to unpack or to wait is taken, or a decoder stayed taken for ``DECODER_WAIT_SECONDS``."""


def sniff(head: bytes) -> str | None:
    """The kind of a picture by its first bytes (at least 64 of them), never by its name."""
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
    if head[4:8] == b"ftyp" and len(head) >= 12:
        size = struct.unpack(">I", head[:4])[0]
        brands = {head[8:12]} | {head[at : at + 4] for at in range(16, min(size, len(head)) - 3, 4)}
        if brands & AVIF_BRANDS:
            return "avif"
        if brands & HEIF_BRANDS:
            return "heic"
    return None


async def read_body(request: Any) -> bytes:
    """The body of an upload, read piece by piece and given up past ``MAX_BYTES`` (``PictureError("size")``): a body
    is held only once it was admitted (``admitted``), and never larger than a picture may be."""
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise PictureError("size")
    return bytes(body)


def _register() -> None:
    global _registered
    if not _registered:
        import pillow_heif

        pillow_heif.register_heif_opener()
        _registered = True


@contextmanager
def opened(data: bytes, kinds: set[str]) -> Iterator[Any]:
    """The picture in ``data``, opened, its pixels loaded and turned upright (EXIF orientation applied); only of the
    ``kinds`` named. ``PictureError("kind")`` for anything else, ``PictureError("size")`` for too many bytes or
    pixels, ``DecodersBusy`` when the server is unpacking enough pictures already."""
    if not data or len(data) > MAX_BYTES:
        raise PictureError("size" if data else "kind")
    if sniff(data[:64]) not in kinds:
        raise PictureError("kind")
    from PIL import Image

    _register()
    decoders = _semaphore()
    if not decoders.acquire(timeout=DECODER_WAIT_SECONDS):
        raise DecodersBusy
    try:
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format and image.format.lower() not in {"jpeg", "png", "webp", "gif", "bmp", "heif", "avif"}:
                    raise PictureError("kind")
                if image.width * image.height > MAX_PIXELS:
                    raise PictureError("size")
                yield image
        except PictureError:
            raise
        except Image.DecompressionBombError as exc:
            # A small file that claims a huge picture: Pillow refuses it while opening.
            raise PictureError("size") from exc
        except Exception as exc:
            # A broken, cut off or hostile picture fails in the decoder's own way.
            logger.info("A picture could not be read: %s", type(exc).__name__)
            raise PictureError("kind") from exc
    finally:
        decoders.release()
