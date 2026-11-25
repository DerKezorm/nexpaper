"""What a display name shows: invisible characters gone, blanks as one, and a key under which names that look alike
are equal.

``visible`` drops what a reader cannot see (Unicode's default ignorable code points: joiners, variation selectors,
the grapheme joiner, Hangul fillers, direction marks, tags) and keeps only the two that draw emoji: the zero width
joiner between two emoji and a variation selector after one. Runs of blanks of any kind become one space.

``skeleton`` maps letters of Cyrillic and Greek that look like Latin ones to those (a subset of the confusables of
Unicode Technical Standard 39, after case folding), so that "Мaх" and "Max" have one key.
"""

from __future__ import annotations

import re
import unicodedata

#: Unicode's Default_Ignorable_Code_Point, as ranges (DerivedCoreProperties).
_IGNORABLE = (
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)
_ZWJ = 0x200D
_VS15, _VS16 = 0xFE0E, 0xFE0F
_BLANKS = re.compile(r"\s+")

#: Letters of other scripts that look like Latin ones, after case folding (``str.casefold``): the lower case form
#: stands for itself and for its capital (Cyrillic "М" folds to "м" and looks like "M").
_SKELETON = str.maketrans(
    {
        # Cyrillic
        "а": "a", "в": "b", "е": "e", "ё": "e", "з": "3", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p",
        "с": "c", "т": "t", "у": "y", "х": "x", "ѕ": "s", "і": "i", "ї": "i", "ј": "j", "һ": "h", "ԁ": "d",
        "ԛ": "q", "ԝ": "w", "ӏ": "l", "ү": "y", "ɡ": "g",
        # Greek
        "α": "a", "β": "b", "ε": "e", "ζ": "z", "η": "h", "ι": "i", "κ": "k", "μ": "m", "ν": "v", "ο": "o",
        "ρ": "p", "τ": "t", "υ": "y", "χ": "x", "ω": "w", "ϲ": "c", "ϳ": "j",
        # Latin that looks like plain Latin
        "ı": "i", "ȷ": "j", "ł": "l", "ø": "o", "đ": "d", "ħ": "h",
    }
)


def _ignorable(code: int) -> bool:
    return any(low <= code <= high for low, high in _IGNORABLE)


def _emoji(char: str) -> bool:
    """A character that draws as an emoji (or a part of one: skin tones, keycap base)."""
    code = ord(char)
    return code >= 0x1F000 or (0x2190 <= code <= 0x2BFF and unicodedata.category(char) == "So") or code == 0x20E3


def visible(text: str) -> str:
    """The text without what nobody can see, blanks as one space, without blanks at the edges."""
    chars = list(unicodedata.normalize("NFC", text or ""))
    kept: list[str] = []
    for index, char in enumerate(chars):
        code = ord(char)
        category = unicodedata.category(char)
        if code == _ZWJ:
            before = kept[-1] if kept else ""
            after = chars[index + 1] if index + 1 < len(chars) else ""
            if before and after and _emoji(before) and _emoji(after):
                kept.append(char)
            continue
        if code in (_VS15, _VS16):
            if kept and _emoji(kept[-1]):
                kept.append(char)
            continue
        if _ignorable(code) or category in ("Cc", "Cf", "Co", "Cs", "Cn"):
            continue
        kept.append(char)
    return _BLANKS.sub(" ", "".join(kept)).strip()


def has_something_to_see(text: str) -> bool:
    """Not only blanks and invisible characters."""
    return any(not char.isspace() and ord(char) not in (_ZWJ, _VS15, _VS16) for char in visible(text))


def skeleton(text: str) -> str:
    """The key two names that look alike share: visible, NFKC, case folded, look-alike letters as Latin, emoji
    selectors gone, blanks as one."""
    folded = unicodedata.normalize("NFKC", visible(text)).casefold()
    folded = "".join(char for char in folded if ord(char) not in (_ZWJ, _VS15, _VS16))
    return _BLANKS.sub(" ", folded.translate(_SKELETON)).strip()
