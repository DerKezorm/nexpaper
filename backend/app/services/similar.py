"""Finding a document the person already has: the same file, or one that looks the same.

**Only what the person may see is compared.** The query that fetches the candidates carries the rights (the same clause
every list uses), so a file somebody else kept in a vault the person is not in is never even read: it cannot change an
answer, and nothing in the answer, in its time or in an error can tell the person it exists.

**The same file** is the same SHA-256, found by an index. It is checked when the file arrives (the piece-by-piece upload
answers "already there" before anything is sent) and kept on the document.

**A file that looks the same** is the same sheet scanned or photographed again (B3). The picture and the text must both
say so:

* the picture: the fingerprints of the first pages (``app/worker.py``, 1024 bits) differ in at most ``PICTURE_BITS``,
* the text: nearly the same words and nearly the same numbers (``text_alike``).

Measured (``tests/test_similar_text.py``; ``docs/search.md`` has the numbers):

* The picture alone does not carry. B2 set ``THRESHOLD_BITS`` to 16 for the same file drawn again (other brightness,
  blur, size, JPEG); its reviewer found 32 of 45 pairs of monthly invoices of one form within it. Real rescans (turned
  by up to one degree, specks, another brightness, JPEG) of the same sheet lay 125 to 298 bits apart, monthly invoices
  106 to 202, unrelated pages from 92 up: a sheet turned a little moves every gradient. So the picture only rules out
  what does not look alike at all (``PICTURE_BITS``, a third of the bits; unrelated pages lie at half on average).
* The text decides. Monthly invoices of one form share 95 % of their words but only 51 to 71 % of their numbers (date,
  invoice number, period, amounts); the same sheet read twice by Tesseract shared all its words and 93 % of its
  numbers. Hence 80 % for both. That is not enough alone: a phone invoice with fixed prices and contract lines shared
  80 % of its numbers with the next month (found by the reviewer of B3), a rent the same amount every month. So the
  numbers that tell one sheet from the next must agree too (``distinct``): the longest number (an invoice number) and
  the dates. A rescan where the recognition misread one of them is not called alike: no hint is the safe side.

The candidates are found by the text first: the documents whose text holds the longest numbers of this one (an invoice
number, a customer number) in the word index, then those with the nearest pictures. Without text or without a
fingerprint on either side nothing is called alike: only the very same file (same SHA-256) is reported then.
"""

from __future__ import annotations

import re

from sqlalchemy import Integer, bindparam, column, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from ..models import TRASH, Document, Version, VersionText
from . import rights, searchtext

#: How many of the 1024 bits may differ for two first pages to be the same file drawn again (B2; ``similar_file``).
THRESHOLD_BITS = 16
#: How many may differ for two first pages that could be the same sheet scanned again: a third of the bits.
PICTURE_BITS = 340
SAME, SIMILAR = "same", "similar"
#: Share of the words two texts must have in common (of the words either has), and share of the numbers.
WORDS_ALIKE = 0.8
NUMBERS_ALIKE = 0.8
#: Share of the dates two texts must have in common (when either has one): a misread date among many is forgiven.
DATES_ALIKE = 0.75
#: Fewer numbers than this in both texts: the words alone decide, and must agree more.
FEW_NUMBERS = 3
WORDS_ALONE = 0.85
#: Candidates whose text is compared: found by their numbers, and the nearest pictures.
BY_NUMBERS = 200
BY_PICTURE = 50
#: Numbers of at least this many digits find candidates (shorter ones are in nearly every document).
LONG_NUMBER = 5
_DIGIT = re.compile(r"\d")
_NUMBER = re.compile(r"\d(?:[\d.,:/-]*\d)?")
_DATE = re.compile(r"\d{1,2}\.\d{1,2}\.(?:\d{2}|\d{4})|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})")


def distance(a: str, b: str) -> int:
    """The number of bits in which two fingerprints (hex strings of the same length) differ; a very large number when
    they cannot be compared."""
    if not a or not b or len(a) != len(b):
        return 1 << 20
    try:
        return (int(a, 16) ^ int(b, 16)).bit_count()
    except ValueError:
        return 1 << 20


def same_file(db: Session, uid: int, sha256: str, exclude: int | None = None) -> Document | None:
    """The oldest document ``uid`` may see (not in the trash) whose current file has this checksum."""
    query = (
        select(Document).join(Version, (Version.document_id == Document.id) & (Version.n == Document.current_version))
        .where(Version.sha256 == sha256, Document.status != TRASH, rights.visible_clause(uid))
    )
    if exclude is not None:
        query = query.where(Document.id != exclude)
    return db.scalars(query.order_by(Document.id).limit(1)).first()


def similar_file(db: Session, uid: int, phash: str, exclude: int | None = None) -> Document | None:
    """The closest document ``uid`` may see (not in the trash) whose first page looks like this one, within the
    threshold; the nearest wins, the oldest among equals."""
    if not phash:
        return None
    query = (
        select(Document.id, Version.phash)
        .join(Version, (Version.document_id == Document.id) & (Version.n == Document.current_version))
        .where(Version.phash != "", Document.status != TRASH, rights.visible_clause(uid))
    )
    if exclude is not None:
        query = query.where(Document.id != exclude)
    best: tuple[int, int] | None = None
    for document_id, other in db.execute(query.order_by(Document.id)):
        gap = distance(phash, other)
        if gap <= THRESHOLD_BITS and (best is None or gap < best[0]):
            best = (gap, document_id)
    return db.get(Document, best[1]) if best else None


def visible_duplicate(db: Session, uid: int, document: Document) -> Document | None:
    """The document ``document`` was found to repeat, when ``uid`` may see it (else nothing, as if there were none)."""
    if not document.duplicate_of:
        return None
    return db.scalars(select(Document).where(
        Document.id == document.duplicate_of, Document.status != TRASH, rights.visible_clause(uid))).first()


def _features(text: str) -> tuple[set[str], set[str]]:
    """The words (two letters and more, folded) and the numbers of a text. A number keeps its points, commas, dashes and
    slashes (``15.03.2026``, ``84,00``, ``2026-03-48213``): a date or an amount is one number, which another month
    changes as a whole."""
    tokens = searchtext.tokens(_NUMBER.sub(" ", text))
    words = {token for token in tokens if len(token) > 1 and not _DIGIT.search(token)}
    numbers = set(_NUMBER.findall(text))
    return words, numbers


def _share(a: set[str], b: set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def text_likeness(a: str, b: str) -> tuple[float, float, int]:
    """(share of words in common, share of numbers in common, the fewer numbers of the two)."""
    words_a, numbers_a = _features(a)
    words_b, numbers_b = _features(b)
    return _share(words_a, words_b), _share(numbers_a, numbers_b), min(len(numbers_a), len(numbers_b))


def _dates(numbers: set[str]) -> set[str]:
    """The numbers that are dates (``15.03.2026``, ``2026-03-15``, ``15/03/26``)."""
    return {n for n in numbers if _DATE.fullmatch(n)}


def _longest(numbers: set[str]) -> set[str]:
    """The numbers with the most digits (an invoice number, a customer number), dates aside (they count apart)."""
    digits = {n: sum(c.isdigit() for c in n) for n in numbers if not _DATE.fullmatch(n)}
    most = max(digits.values(), default=0)
    return {n for n, count in digits.items() if count == most and count >= LONG_NUMBER}


def distinct(a: str, b: str) -> bool:
    """Whether the numbers that tell one sheet from the next differ: the longest number (with its digits as the
    invoice number usually has them), or the dates. Two months of the same invoice with fixed prices, a rent with the
    same amount every month: their words and most numbers agree, their dates and their numbers do not."""
    _words_a, numbers_a = _features(a)
    _words_b, numbers_b = _features(b)
    longest_a, longest_b = _longest(numbers_a), _longest(numbers_b)
    if longest_a and longest_b and not longest_a & longest_b:
        return True
    dates_a, dates_b = _dates(numbers_a), _dates(numbers_b)
    return bool(dates_a or dates_b) and _share(dates_a, dates_b) < DATES_ALIKE


def text_alike(a: str, b: str) -> bool:
    """Whether two texts are the same sheet read twice: nearly the same words and numbers, and the numbers that tell
    one sheet from the next (``distinct``) the same."""
    if not a.strip() or not b.strip() or distinct(a, b):
        return False
    words, numbers, fewest = text_likeness(a, b)
    if fewest < FEW_NUMBERS:
        return words >= WORDS_ALONE and numbers >= NUMBERS_ALIKE if fewest else words >= WORDS_ALONE
    return words >= WORDS_ALIKE and numbers >= NUMBERS_ALIKE


def _numbers_of(text: str) -> list[list[str]]:
    """The longest numbers of a text (at most three), as the tokens the word index holds."""
    longest = sorted({n for n in _NUMBER.findall(text) if sum(c.isdigit() for c in n) >= LONG_NUMBER},
                     key=lambda n: (-len(n), n))[:3]
    return [parts for parts in (searchtext.tokens(n) for n in longest) if parts]


def similar_document(db: Session, document: Document, phash: str, text: str) -> Document | None:
    """The document the owner of ``document`` may see (not in the trash, not this one) that is the same sheet: the
    picture alike and the text alike, the nearest picture first. Nothing without an owner, a fingerprint or a text."""
    if document.owner_id is None or not phash or not text.strip():
        return None
    base = (
        select(Document.id, Version.phash, Version.id)
        .join(Version, (Version.document_id == Document.id) & (Version.n == Document.current_version))
        .where(Version.phash != "", Document.status != TRASH, Document.id != document.id,
               rights.visible_clause(document.owner_id))
    )
    found: dict[int, tuple[int, int]] = {}
    numbers = _numbers_of(text)
    if numbers:
        expression = "{title sender text notes tags} : (" + " OR ".join(
            searchtext.fts_string(parts, False) for parts in numbers) + ")"
        lookup = sql_text("SELECT rowid FROM doc_fts WHERE doc_fts MATCH :expr")
        lookup = lookup.bindparams(bindparam("expr", value=expression)).columns(column("rowid", Integer))
        for document_id, other, version_id in db.execute(base.where(Document.id.in_(lookup)).limit(BY_NUMBERS)):
            found[document_id] = (distance(phash, other), version_id)
    nearest = sorted((distance(phash, other), document_id, version_id)
                     for document_id, other, version_id in db.execute(base))[:BY_PICTURE]
    for gap, document_id, version_id in nearest:
        found.setdefault(document_id, (gap, version_id))
    candidates = sorted((gap, document_id, version_id) for document_id, (gap, version_id) in found.items()
                        if gap <= PICTURE_BITS)
    if not candidates:
        return None
    texts = dict(db.execute(select(VersionText.version_id, VersionText.text)
                            .where(VersionText.version_id.in_([v for _g, _d, v in candidates]))).all())
    for _gap, document_id, version_id in candidates:
        if text_alike(text, (texts.get(version_id) or "").replace("\f", "\n")):
            return db.get(Document, document_id)
    return None
