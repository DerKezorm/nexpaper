"""What a search says, and where in a text it was found. Pure functions: no database, no settings.

**The language** is the one of the archive's search field (the mock's help list), in German and in English:

* words: every one must be found, in the title, the sender, the text, the notes or the tags; a part of a word is enough
  (``werke`` finds ``Stadtwerke``),
* ``"bitte überweisen"``: these words in this order,
* ``art:rechnung`` / ``kind:invoice``: the kind (its name or key begins so),
* ``absender:hansa`` / ``sender:hansa``: the sender (its name holds it),
* ``tag:auto``: a tag that begins so,
* ``betrag:>100`` / ``amount:<50,5`` / ``betrag:=12.30`` / ``betrag:100``: the amount in euros, comma or point,
* ``aufbewahren:abgelaufen`` / ``keep:expired``: the keeping time is over (``aufbewahren:läuft`` / ``keep:running``:
  it is not over yet); another word finds nothing.

Nothing a person types reaches SQL or FTS5 as syntax: every word is cut into the tokens FTS5 itself would make and
handed over inside double quotes, so ``NEAR``, ``*``, ``-``, ``(``, ``^`` and quotes are just characters. Filters are
values bound to the query, never text in it.

**Folding.** The word index compares without case and without accents (``unicode61 remove_diacritics 2``), and ``ß``
counts as ``ss`` (done here, before the text reaches the index and before a word reaches the query: FTS5 leaves ``ß``
alone). ``fold`` is the same for the words of a search; the marks find a folded word in a text that is not folded with
a regular expression of letter classes (``_pattern``), so their places are those of the text as it stands.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

#: Longest search accepted, in characters, and most terms (words, phrases, filters) in it.
MAX_LENGTH = 500
MAX_TERMS = 12
#: Most tokens in one phrase, and the longest token (a longer one is cut: nobody types 64 letters to find a word).
MAX_PHRASE_TOKENS = 16
MAX_TOKEN = 64
#: Words at least this long are found in the middle of a word too (shorter ones only at the start of a word).
MIDDLE_MIN = 3
#: Highest amount in a filter, in cents (the same limit a document's amount has).
AMOUNT_LIMIT = 10**12

KIND_KEYS = ("art", "kind")
SENDER_KEYS = ("absender", "sender")
TAG_KEYS = ("tag",)
AMOUNT_KEYS = ("betrag", "amount")
KEEP_KEYS = ("aufbewahren", "keep")
#: The words of ``aufbewahren:`` / ``keep:`` (folded) and what they ask for; any other word asks for ``none``.
KEEP_WORDS = {"abgelaufen": "expired", "expired": "expired", "laeuft": "running", "lauft": "running",
              "running": "running"}

# A piece of the search: key:"two words", key:value, "a phrase" (an unclosed one runs to the end), or anything up to a
# blank.
_PIECE = re.compile(r'(?P<key>[^\s:"]+):(?:"(?P<qval>[^"]*)"?|(?P<val>\S*))|"(?P<phrase>[^"]*)"?|(?P<word>\S+)')
# What FTS5's unicode61 counts as a token: letters, numbers (and private use); everything else separates.
_TOKEN = re.compile(r"[^\W_]+")
#: What parts two words typed without a blank between them; everything else between letters holds a word together.
_APART = re.compile(r"[^\w\-./,'’@]+")
_AMOUNT = re.compile(r"^(?P<op>[<>=]?)(?P<num>[0-9][0-9.,' ]*)$")


class SearchError(ValueError):
    """A search that cannot be run as it is; ``code`` says why."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _strip_marks(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def fold(text: str) -> str:
    """As the index compares: without accents, lower case, ``ß`` as ``ss``. May change the length (``ß``, ligatures)."""
    return _strip_marks(text).lower().replace("ß", "ss")


def for_index(text: str) -> str:
    """The text as it goes into the index: only ``ß`` becomes ``ss`` (case and accents are FTS5's business), and a NUL,
    which would end SQLite's string, goes."""
    return text.replace("ß", "ss").replace("ẞ", "SS").replace("\x00", " ")


def tokens(text: str) -> list[str]:
    """The tokens FTS5 makes of ``text`` (folded), each at most ``MAX_TOKEN`` characters."""
    return [token[:MAX_TOKEN] for token in _TOKEN.findall(fold(text))]


@dataclass
class Amount:
    op: str  # one of <, >, =
    cents: int


@dataclass
class Query:
    #: Single words (folded tokens): each must be found, at the start of a word or (from ``MIDDLE_MIN`` letters) in
    #: the middle of one.
    words: list[str] = field(default_factory=list)
    #: Tokens in a row: a phrase in quotes, or a word that FTS5 cuts in pieces (``R-2026-17``, ``e-mail``). ``prefix``:
    #: the last token may go on (a word typed without quotes).
    phrases: list[tuple[list[str], bool]] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    senders: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    amounts: list[Amount] = field(default_factory=list)
    #: ``expired``, ``running`` or ``none`` (a word the search does not know: nothing is found).
    keeps: list[str] = field(default_factory=list)

    @property
    def has_text(self) -> bool:
        return bool(self.words or self.phrases)

    @property
    def empty(self) -> bool:
        return not (self.has_text or self.kinds or self.senders or self.tags or self.amounts or self.keeps)

    def patterns(self) -> list[str]:
        """Regular expressions for the places a hit is marked at, as the index finds them: a word of
        ``MIDDLE_MIN`` letters and more anywhere, a shorter one at the start of a word (one letter: as a whole word), a
        phrase as its words in a row with anything but letters and digits between them. Longest first."""
        found: list[tuple[int, str]] = []
        for word in self.words:
            if len(word) >= MIDDLE_MIN:
                found.append((len(word), _pattern(word)))
            else:
                found.append((len(word), _START + _pattern(word) + (_END if len(word) == 1 else "")))
        for parts, prefix in self.phrases:
            body = _GAP.join(_pattern(part) for part in parts)
            found.append((sum(map(len, parts)) + len(parts), _START + body + ("" if prefix else _END)))
        return [pattern for _length, pattern in sorted(set(found), key=lambda item: (-item[0], item[1]))]


def _amount(value: str) -> Amount:
    found = _AMOUNT.match(value.replace("€", "").replace("eur", "").strip())
    if not found:
        raise SearchError("invalid_amount")
    number = found.group("num").replace(" ", "").replace("'", "")
    if "," in number and "." in number:
        # 1.234,56 or 1,234.56: the last sign is the decimal one.
        if number.rfind(",") > number.rfind("."):
            number = number.replace(".", "").replace(",", ".")
        else:
            number = number.replace(",", "")
    else:
        number = number.replace(",", ".")
    try:
        euros = Decimal(number)
    except InvalidOperation as exc:
        raise SearchError("invalid_amount") from exc
    if not euros.is_finite():
        raise SearchError("invalid_amount")
    cents = int((euros * 100).to_integral_value())
    if abs(cents) > AMOUNT_LIMIT:
        raise SearchError("invalid_amount")
    return Amount(op=found.group("op") or "=", cents=cents)


def _add_text(query: Query, text: str, *, quoted: bool) -> None:
    if quoted:
        parts = tokens(text)
        if parts:
            query.phrases.append((parts[:MAX_PHRASE_TOKENS], False))
        return
    # Brackets, stars, colons and the like part words; a hyphen, a point, a slash inside a word hold it together, and
    # such a word (``R-2026-17``, ``12.30``, ``e-mail``) is looked for as its pieces in a row.
    for piece in _APART.split(text):
        parts = tokens(piece)
        if len(parts) == 1:
            if parts[0] not in query.words:
                query.words.append(parts[0])
        elif parts:
            query.phrases.append((parts[:MAX_PHRASE_TOKENS], True))


def parse(raw: str) -> Query:
    """The search as a ``Query``. ``SearchError``: too long, too many terms, or an amount that is not one."""
    if len(raw) > MAX_LENGTH:
        raise SearchError("query_too_long")
    text = unicodedata.normalize("NFC", raw.replace("\x00", " "))
    query = Query()
    pieces = list(_PIECE.finditer(text))
    if len(pieces) > MAX_TERMS:
        raise SearchError("too_many_terms")
    for piece in pieces:
        key = piece.group("key")
        if key is not None:
            value = piece.group("qval") if piece.group("qval") is not None else piece.group("val") or ""
            name = key.lower()
            clean = value.strip()
            if name in AMOUNT_KEYS:
                if clean:
                    query.amounts.append(_amount(clean))
                continue
            if name in KEEP_KEYS:
                if clean:
                    query.keeps.append(KEEP_WORDS.get(fold(clean), "none"))
                continue
            if name in KIND_KEYS + SENDER_KEYS + TAG_KEYS:
                if clean:
                    target = query.kinds if name in KIND_KEYS else query.senders if name in SENDER_KEYS else query.tags
                    target.append(clean[:160])
                continue
            # Not a key this search knows: the whole piece is text ("12:30", "re:anfrage").
            _add_text(query, piece.group(0), quoted=False)
            continue
        if piece.group("phrase") is not None:
            _add_text(query, piece.group("phrase"), quoted=True)
            continue
        _add_text(query, piece.group("word") or "", quoted=False)
    return query


def fts_string(parts: list[str], prefix: bool) -> str:
    """Tokens as one FTS5 string (a phrase), the last one open to the right when ``prefix``. The tokens hold only
    letters and digits (``tokens``), so a quote cannot end the string early."""
    return '"' + " ".join(parts) + '"' + ("*" if prefix else "")


# --- Marks ------------------------------------------------------------------------------------------------------------


def _utf16(text: str, index: int) -> int:
    """The offset of character ``index`` counted in UTF-16 code units, as JavaScript, Swift's NSString and Kotlin do."""
    return index + sum(1 for char in text[:index] if ord(char) > 0xFFFF)


def _variants() -> dict[str, set[str]]:
    """For every folded letter, the characters that fold to it (Latin, Greek, Cyrillic: what a document from here
    holds). ``ß`` and ``ẞ`` fold to two letters and are handled apart."""
    table: dict[str, set[str]] = {}
    for code in list(range(0x20, 0x250)) + list(range(0x370, 0x530)) + list(range(0x1E00, 0x1F00)):
        char = chr(code)
        folded = fold(char)
        if len(folded) == 1:
            table.setdefault(folded, set()).add(char)
    return table


_VARIANTS = _variants()


def _pattern(term: str) -> str:
    """A regular expression that finds ``term`` (folded) in a text that is not folded: each letter as the class of the
    letters that fold to it, ``ss`` also as ``ß``."""
    out = []
    index = 0
    while index < len(term):
        if term.startswith("ss", index):
            out.append("(?:[sSſ][sSſ]|[ßẞ])")
            index += 2
            continue
        char = term[index]
        group = _VARIANTS.get(char, {char}) | {char}
        out.append("[" + "".join(re.escape(c) for c in sorted(group)) + "]" if len(group) > 1 else re.escape(char))
        index += 1
    return "".join(out)


#: A word begins here, ends here; what may stand between the words of a phrase.
_START = r"(?<![^\W_])"
_END = r"(?![^\W_])"
_GAP = r"[\W_]+"


def find_marks(text: str, patterns: list[str], limit: int = 50) -> list[tuple[int, int]]:
    """Where the patterns (``Query.patterns``) match ``text``, as ``[start, end)`` in characters of ``text`` (overlaps
    merged), at most ``limit`` of them."""
    if not text or not patterns:
        return []
    spans: list[tuple[int, int]] = []
    for pattern in patterns:
        for found in re.finditer(pattern, text):
            spans.append(found.span())
            if len(spans) >= limit * 4:
                break
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged[:limit]


def as_utf16(text: str, spans: list[tuple[int, int]]) -> list[list[int]]:
    return [[_utf16(text, start), _utf16(text, end)] for start, end in spans]


#: Characters of text on each side of the first place found, in an excerpt.
SNIPPET_SIDE = 90
#: The excerpt is about the first place: the text is looked through no further than this.
SNIPPET_SCAN = 200_000


def snippet(text: str, patterns: list[str], side: int = SNIPPET_SIDE) -> tuple[str, list[tuple[int, int]]]:
    """A piece of ``text`` around the first place one of the patterns matches, with the places marked in it (in
    characters of the piece). Without such a place: the start of the text, unmarked. Page breaks become blanks."""
    first = re.compile("|".join(patterns)).search(text, 0, SNIPPET_SCAN) if patterns and text else None
    if first is None:
        return " ".join(text[: side * 2].split()), []
    found = first.start()
    start = max(0, found - side)
    end = min(len(text), found + side)
    # Not in the middle of a word.
    while start > 0 and text[start - 1].isalnum() and found - start < side + 20:
        start -= 1
    while end < len(text) and text[end].isalnum() and end - found < side + 20:
        end += 1
    piece = " ".join(text[start:end].split())
    shown = ("… " if start > 0 else "") + piece + (" …" if end < len(text) else "")
    return shown, find_marks(shown, patterns)
