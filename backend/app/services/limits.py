"""The limits on what comes in, as the operator set them (Settings, Storage), with the ranges they may take.

Every limit exists in the interface and is read anew for each request, so a change counts at once. A value the database
holds that is out of range (a hand edit) is pulled back into range rather than trusted.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from . import settings_service

MB = 1024 * 1024
#: (smallest, largest) the operator may set, in the unit of the setting.
RANGES: dict[str, tuple[int, int]] = {
    "upload_max_mb": (1, 10240),
    "upload_max_pages": (1, 20000),
    "upload_max_megapixels": (1, 1000),
    "upload_open_count": (1, 100),
    "upload_open_mb": (1, 1048576),
    "process_timeout_seconds": (5, 86400),
    "process_memory_mb": (0, 65536),
    "cache_max_mb": (64, 1048576),
    "prerender_max_pages": (0, 20000),
}
#: A memory limit below this is none that PDFium and Pillow can work under (they would fail on loading): such a value is
#: raised to it. 0 stays "no limit".
MEMORY_FLOOR = 256
#: Files in one request of the browser's upload (the rest goes in the next one).
FILES_PER_REQUEST = 10
#: The largest piece of a piece-by-piece upload, and the one the server proposes.
MAX_PIECE = 64 * MB
PIECE = 8 * MB
#: A piece-by-piece upload runs out this long after its last piece.
UPLOAD_HOURS = 24
#: Document pages are never rendered larger than this many pixels, whatever width was asked for.
MAX_RENDER_PIXELS = 16_000_000


def _value(db: Session, key: str) -> int:
    low, high = RANGES[key]
    raw = settings_service.get(db, key)
    try:
        number = int(raw)
    except (TypeError, ValueError):
        number = int(settings_service.DEFAULTS[key])
    number = min(max(number, low), high)
    if key == "process_memory_mb" and 0 < number < MEMORY_FLOOR:
        number = MEMORY_FLOOR
    return number


@dataclass(frozen=True)
class Limits:
    max_file: int
    max_pages: int
    max_pixels: int
    open_count: int
    open_bytes: int
    timeout_seconds: int
    memory_mb: int
    cache_bytes: int
    #: The pages of a document drawn in the background after it was read (small pictures); 0: none beyond the short
    #: documents the worker draws while it reads them.
    prerender_pages: int

    @property
    def max_request(self) -> int:
        """The body of one request of the browser's upload: a number of files at most as large as the limit, and some
        room for the envelope."""
        return self.max_file * FILES_PER_REQUEST + MB


def current(db: Session) -> Limits:
    return Limits(
        max_file=_value(db, "upload_max_mb") * MB,
        max_pages=_value(db, "upload_max_pages"),
        max_pixels=_value(db, "upload_max_megapixels") * 1_000_000,
        open_count=_value(db, "upload_open_count"),
        open_bytes=_value(db, "upload_open_mb") * MB,
        timeout_seconds=_value(db, "process_timeout_seconds"),
        memory_mb=_value(db, "process_memory_mb"),
        cache_bytes=_value(db, "cache_max_mb") * MB,
        prerender_pages=_value(db, "prerender_max_pages"),
    )


def request_limit() -> int:
    """For the guard in front of the routes: how large the body of the browser's upload may be right now."""
    from ..db import SessionLocal

    with SessionLocal() as db:
        return current(db).max_request
