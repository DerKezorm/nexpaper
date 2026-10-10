"""Names that become folders and files on the disk.

Everything a person typed (a sender, a vault, a kind) can end up as a folder or file name under ``dokumente/``. This
module makes such a text safe: no path parts, no characters a file system refuses, no reserved Windows names, a
length that fits. It has no dependencies on purpose (``models.py`` uses it while an account is being made).
"""

from __future__ import annotations

import re
import unicodedata

#: Characters no file system of the usual kinds takes in a name (Windows is the strictest), and the path separators.
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
#: Names Windows reserves, with or without an extension ("CON", "con.txt").
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(\..*)?$", re.IGNORECASE)

SEGMENT_MAX = 48
#: The kind part of a file name is shorter: the date comes before it and a counter or an extension after it.
KIND_MAX = 40


def clean_segment(text: str, fallback: str, limit: int = SEGMENT_MAX) -> str:
    """One path segment from free text. Never empty, never ``.`` or ``..``, never longer than ``limit`` characters."""
    # A lone surrogate (JSON may carry one) cannot be written into a file name at all.
    text = text.encode("utf-8", "replace").decode("utf-8", "replace")
    text = unicodedata.normalize("NFC", text)
    cleaned = []
    for char in text:
        category = unicodedata.category(char)
        if _FORBIDDEN.match(char) or category in ("Cc", "Cf", "Zl", "Zp", "Cs", "Co", "Cn"):
            cleaned.append(" ")
        else:
            cleaned.append(char)
    result = " ".join("".join(cleaned).split())
    # No dots or spaces at either end (Windows drops them, a leading dot hides the folder), and no ".." inside.
    result = re.sub(r"\.{2,}", ".", result).strip(" .")
    if len(result) > limit:
        result = result[:limit].strip(" .")
    if not result or result in (".", ".."):
        result = fallback
    if _RESERVED.match(result):
        result = "_" + result
    return result


def folded(text: str) -> str:
    """The form in which two names count as the same on a disk that ignores case (Windows, macOS, a NAS share)."""
    return unicodedata.normalize("NFC", text).casefold()


def name_key(text: str) -> str:
    """The form in which two names of a sender, a tag or a kind count as the same: Unicode composed, case folded
    (``Müller``, ``MÜLLER`` and ``Müller`` are one). Kept in a column of its own: SQLite's ``lower()`` folds only
    ASCII."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", text).casefold())


def search_key(text: str) -> str:
    """The form in which a typed word meets a name when looking for it: case and accents aside as well (``bäckerei``,
    ``Backerei`` and ``BÄCKEREI`` meet). Not for telling two names apart (that is ``name_key``): only for finding."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))
