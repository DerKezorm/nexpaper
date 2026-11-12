"""Numbers read from a document: what tells which other documents it goes with, and what a transfer needs.

**What is read.** An invoice, order (also a purchase order or an order confirmation), delivery note, customer or
contract number, each only after a word that names it (German and English, the usual ways of writing it: ``Rechnungs-
Nr.``, ``Rechnung Nr.``, ``Re.-Nr.``, ``Invoice No.``, ``Bestellnummer``, ``Ihre Bestellung``, ``Auftrag``, ``PO #``,
``Lieferschein``, ``LS-Nr.``, ``Kd.-Nr.`` ...), and an IBAN, only with valid check digits. The number may stand on the
next line when nothing else follows the word on its line (a scan breaks lines). An e-invoice brings its number and IBAN
in its data: they go first, and the text is not asked for those two then (``buyer_ref`` never: the Leitweg-ID is the
same on every invoice to an authority).

**The form numbers are compared in** (``compare``): without blanks, dashes, points, slashes and underscores, in
capitals, and the letters text recognition mixes up with digits taken as the digits (``O`` as ``0``, ``I`` and ``L``
as ``1``). ``R-2026 - 0O17`` and ``r2026/0017`` are the same number.

**Hostile text costs nothing.** Only the first ``textfacts.MAX_TEXT`` characters are read; every pattern is bounded and
has no nested repetition, and the number after a word is taken by a plain loop over at most ``VALUE_MAX`` characters.

**When.** Whenever a document takes a change number (``changes.next_seq``), right before its transaction commits, the
digest of what its numbers come from (the text of its current version, its e-invoice) is compared with the one they
were read from (``NumbersRead``); only when it changed are they read again, in the same transaction (a new document, a
new version, pages joined or split, a version brought back). The documents there were before are read once by the job
``numbers``, in portions with pauses (``run_job``). No number ever goes to the log.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, event, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..einvoice_reader import clean_iban
from ..models import Document, DocumentNumber, EInvoice, NumbersRead, Version, VersionText
from . import textfacts

logger = logging.getLogger("nexpaper.numbers")

INVOICE, ORDER, DELIVERY, CUSTOMER, CONTRACT, IBAN = "invoice", "order", "delivery", "customer", "contract", "iban"
KINDS = (INVOICE, ORDER, DELIVERY, CUSTOMER, CONTRACT, IBAN)
TEXT, EINVOICE = "text", "einvoice"
#: Raised when the reading changes: a document read with an older reader is read again (the digest names it).
READER = "1"
#: The longest number taken after a word, in characters of the text.
VALUE_MAX = 40
#: The most numbers kept of one kind, and of a document.
PER_KIND = 10
PER_DOCUMENT = 40
#: A transaction that touched more documents than this does not look at their numbers under its lock (a sender
#: renamed on thousands of them changes no text); the job does, in portions.
SYNC_LIMIT = 200

_PLAIN = r"(?:nummer|number|nr\.?|no\.?|#)"
#: A few blanks between the words of a label.
_B = r"[ \t]{0,3}"
_LABELS: dict[str, tuple[str, ...]] = {
    INVOICE: (
        rf"rechnungs[ \t-]?{_PLAIN}", rf"rechnung(?:{_B}{_PLAIN})?", r"re\.?[ \t]?-?[ \t]?nr\.?",
        r"rg\.?[ \t]?-?[ \t]?nr\.?", rf"invoice(?:{_B}(?:{_PLAIN}|id))?", rf"inv\.?[ \t]?{_PLAIN}",
    ),
    ORDER: (
        rf"bestell(?:ungs)?[ \t-]?{_PLAIN}", rf"bestellung(?:{_B}{_PLAIN})?",
        rf"auftrags[ \t-]?{_PLAIN}", rf"auftragsbest(?:ä|ae)tigung(?:{_B}{_PLAIN})?",
        rf"auftrag(?:{_B}{_PLAIN})?", r"ab[ \t]?-?[ \t]?nr\.?",
        rf"purchase[ \t]+order(?:{_B}{_PLAIN})?", rf"po{_B}{_PLAIN}",
        rf"order(?:{_B}(?:{_PLAIN}|id|ref\.?|reference))?",
    ),
    DELIVERY: (
        rf"lieferschein[ \t-]?{_PLAIN}", r"lieferschein", r"ls[ \t]?-?[ \t]?nr\.?",
        rf"delivery[ \t]+note(?:{_B}{_PLAIN})?", rf"delivery{_B}{_PLAIN}",
        rf"packing[ \t]+slip(?:{_B}{_PLAIN})?", rf"dispatch[ \t]+note(?:{_B}{_PLAIN})?",
    ),
    CUSTOMER: (
        rf"kunden[ \t-]?{_PLAIN}", r"kd\.?[ \t]?-?[ \t]?nr\.?", r"kdnr\.?", rf"mitglieds[ \t-]?{_PLAIN}",
        rf"customer{_B}(?:{_PLAIN}|id)", rf"account{_B}{_PLAIN}", rf"client{_B}(?:{_PLAIN}|id)",
    ),
    CONTRACT: (
        rf"vertrags[ \t-]?{_PLAIN}", rf"vertragskonto(?:[ \t-]?{_PLAIN})?",
        rf"versicherungs(?:schein)?[ \t-]?{_PLAIN}", rf"policen?[ \t-]?{_PLAIN}",
        rf"contract{_B}(?:{_PLAIN}|id)", rf"policy{_B}{_PLAIN}",
    ),
}
_LETTER = "A-Za-zÄÖÜäöüß"
_LABEL = re.compile(
    rf"(?<![{_LETTER}0-9])(?:" + "|".join(f"(?P<{kind}>{'|'.join(words)})" for kind, words in _LABELS.items())
    + rf")(?![{_LETTER}])",
    re.IGNORECASE,
)
#: Words between the label and the number that are left out ("Rechnung Nr.", "Order ID:").
_FILLER = {"NR", "NO", "NUMMER", "NUMBER", "NUM", "ID", "REF", "REFERENCE"}
_DATE = re.compile(r"^(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2})$")
_AMOUNT = re.compile(r"^\d{1,3}(?:[.,]\d{3})*,\d{2}$")
_IBAN_TEXT = re.compile(r"(?<![A-Z0-9])([A-Z]{2}\d{2}(?: ?[A-Z0-9]){10,32})")
#: The length of an IBAN in the countries a household here meets most; others are tried from long to short.
IBAN_LENGTHS = {"DE": 22, "AT": 20, "CH": 21, "LI": 21, "NL": 18, "BE": 16, "LU": 20, "FR": 27, "MC": 27, "IT": 27,
                "ES": 24, "PT": 25, "GB": 22, "IE": 22, "PL": 28, "CZ": 24, "SK": 24, "DK": 18, "SE": 24, "NO": 15,
                "FI": 18, "HU": 28, "SI": 19, "HR": 21}
_SEPARATORS = "-/._"
_SAME = str.maketrans({"O": "0", "I": "1", "L": "1"})


@dataclass(frozen=True)
class Number:
    kind: str
    value: str
    compare: str
    origin: str = TEXT


def compare_form(value: str) -> str:
    """The form numbers are compared in (see the top of this file)."""
    kept = "".join(char for char in value.upper() if char.isascii() and char.isalnum())
    return kept.translate(_SAME)


def _value_at(text: str, start: int) -> str:
    """The number that follows a label ending at ``start``, or empty. A plain loop, never more than ``VALUE_MAX``
    characters of number and a few of filler: a hostile text costs as much as its length."""
    end = len(text)
    at = start
    newline = False
    # What stands between the word and the number: blanks, ":", "#", ".", filler words, one line break.
    for _round in range(4):
        skipped = 0
        while at < end and skipped < 12 and text[at] in " \t:#.-=":
            at += 1
            skipped += 1
        if at < end and text[at] == "\n" and not newline:
            newline = True
            at += 1
            continue
        word_end = at
        while word_end < end and word_end - at < 10 and text[word_end].isascii() and text[word_end].isalpha():
            word_end += 1
        if word_end > at and text[at:word_end].upper() in _FILLER and (word_end >= end or not text[word_end].isalnum()):
            at = word_end
            continue
        break
    chunks: list[str] = []
    seps: list[str] = []
    #: Whether a blank stands in the separator before the next piece.
    loose: list[bool] = []
    total = 0
    while at < end and len(chunks) < 8:
        chunk_end = at
        while chunk_end < end and chunk_end - at < 24 and text[chunk_end].isascii() and text[chunk_end].isalnum():
            chunk_end += 1
        if chunk_end == at:
            break
        chunk = text[at:chunk_end]
        if chunks and loose[-1] and not any(char.isdigit() for char in chunk):
            # After a blank only a piece with a digit goes on ("12345 vom", "00017. Bitte" end there).
            seps.pop()
            loose.pop()
            break
        if not chunks and not any(char.isdigit() for char in chunk) and not (chunk.isupper() and len(chunk) <= 5) \
                and not (len(chunk) <= 3 and chunk_end < end and text[chunk_end] in "-/"):
            # A word ("vom", "Datum", "folgt"): no number follows the label. A short prefix joined to the number by a
            # dash or slash ("r-2026-17", a scan that read small letters) is part of it.
            return ""
        chunks.append(chunk)
        total += len(chunk)
        at = chunk_end
        if total > VALUE_MAX:
            return ""
        # What may join two pieces of one number: a dash, a slash, a point (a blank around it, as a scan has it), or a
        # single blank before a piece with a digit (looked at when the piece is read).
        look = at
        if look < end and text[look] == " ":
            look += 1
        if look < end and text[look] in _SEPARATORS:
            look += 1
            if look < end and text[look] == " ":
                look += 1
            if look < end and text[look].isascii() and text[look].isalnum():
                seps.append(text[at:look].strip() or " ")
                loose.append(" " in text[at:look])
                at = look
                continue
            break
        if at < end and text[at] == " " and look < end and text[look].isascii() and text[look].isalnum():
            seps.append(" ")
            loose.append(True)
            at = look
            continue
        break
    if not chunks:
        return ""
    if at + 2 < end and text[at] == "," and text[at + 1:at + 3].isdigit():
        # An amount ("12,50"), not a number.
        return ""
    # A dash or point left hanging at the end belongs to the sentence.
    seps = seps[: len(chunks) - 1]
    value = chunks[0] + "".join(sep + chunk for sep, chunk in zip(seps, chunks[1:], strict=False))
    if not any(char.isdigit() for char in value) or _DATE.match(value) or _AMOUNT.match(value):
        return ""
    return value[:64]


def ibans_in(text: str) -> list[str]:
    """Every IBAN with valid check digits in ``text``, in the order of the text, each once."""
    found: list[str] = []
    for match in _IBAN_TEXT.finditer(text):
        compact = match.group(1).replace(" ", "")
        country = compact[:2]
        lengths = [IBAN_LENGTHS[country]] if country in IBAN_LENGTHS else list(range(min(34, len(compact)), 14, -1))
        for length in lengths:
            if len(compact) < length:
                continue
            iban = clean_iban(compact[:length])
            if iban:
                if iban not in found:
                    found.append(iban)
                break
    return found


def read(text: str, *, invoice_number: str = "", invoice_iban: str = "") -> list[Number]:
    """The numbers of a document: from its text, and from its e-invoice (``invoice_number``, ``invoice_iban``), which go
    first. Each kind and compare form once, at most ``PER_KIND`` of a kind and ``PER_DOCUMENT`` in all."""
    text = (text or "")[: textfacts.MAX_TEXT].replace("\r", "\n").replace("\f", "\n")
    out: list[Number] = []
    seen: set[tuple[str, str]] = set()
    counts: dict[str, int] = {}

    def add(kind: str, value: str, origin: str) -> None:
        compare = compare_form(value)
        if not compare or (kind, compare) in seen or counts.get(kind, 0) >= PER_KIND or len(out) >= PER_DOCUMENT:
            return
        seen.add((kind, compare))
        counts[kind] = counts.get(kind, 0) + 1
        out.append(Number(kind=kind, value=value[:64], compare=compare[:64], origin=origin))

    given_number = " ".join((invoice_number or "").split())[:64]
    if given_number and any(char.isdigit() for char in given_number):
        add(INVOICE, given_number, EINVOICE)
    given_iban = clean_iban(invoice_iban)
    if given_iban:
        add(IBAN, given_iban, EINVOICE)
    for match in _LABEL.finditer(text):
        kind = match.lastgroup or ""
        if kind == INVOICE and given_number:
            continue
        value = _value_at(text, match.end())
        if value:
            add(kind, value, TEXT)
    if not given_iban:
        for iban in ibans_in(text):
            add(IBAN, iban, TEXT)
    return out


# --- Keeping them --------------------------------------------------------------------------------------------------


def _digest(text_digest: str | None, number: str | None, iban: str | None) -> str:
    joined = "\x1f".join((READER, text_digest or "", number or "", iban or ""))
    return hashlib.sha1(joined.encode("utf-8"), usedforsecurity=False).hexdigest()


def _invoices(db: Session, ids: list[int]) -> dict[int, tuple[str, str]]:
    """The number and IBAN of the e-invoice of the newest version of each document that has one."""
    newest = (select(EInvoice.document_id, func.max(Version.n).label("n"))
              .join(Version, Version.id == EInvoice.version_id)
              .where(EInvoice.document_id.in_(ids)).group_by(EInvoice.document_id).subquery())
    rows = db.execute(
        select(EInvoice.document_id, EInvoice.number, EInvoice.iban).join(Version, Version.id == EInvoice.version_id)
        .join(newest, (newest.c.document_id == EInvoice.document_id) & (newest.c.n == Version.n))
    ).all()
    return {document_id: (number or "", iban or "") for document_id, number, iban in rows}


def refresh(db: Session, ids: Iterable[int]) -> int:
    """Reads the numbers of these documents again where what they come from changed; in the caller's transaction (the
    caller holds the write lock and commits). Returns how many documents were read."""
    wanted = sorted(set(ids))
    read_count = 0
    for start in range(0, len(wanted), SYNC_LIMIT):
        chunk = wanted[start: start + SYNC_LIMIT]
        current = (Version.document_id == Document.id) & (Version.n == Document.current_version)
        light = db.execute(
            select(Document.id, VersionText.version_id, VersionText.digest).outerjoin(Version, current)
            .outerjoin(VersionText, VersionText.version_id == Version.id).where(Document.id.in_(chunk))
        ).all()
        invoices = _invoices(db, chunk)
        stored = dict(db.execute(select(NumbersRead.document_id, NumbersRead.digest)
                                 .where(NumbersRead.document_id.in_(chunk))).all())
        for document_id, version_id, text_digest in light:
            number, iban = invoices.get(document_id, ("", ""))
            digest = _digest(text_digest, number, iban)
            if stored.get(document_id) == digest:
                continue
            body = db.scalar(select(VersionText.text).where(VersionText.version_id == version_id)) \
                if version_id is not None else ""
            found = read((body or "").replace("\f", "\n"), invoice_number=number, invoice_iban=iban)
            db.execute(delete(DocumentNumber).where(DocumentNumber.document_id == document_id))
            for item in found:
                db.add(DocumentNumber(document_id=document_id, kind=item.kind, value=item.value,
                                      compare=item.compare, origin=item.origin))
            db.execute(sqlite_insert(NumbersRead).values(document_id=document_id, digest=digest)
                       .on_conflict_do_update(index_elements=["document_id"], set_={"digest": digest}))
            read_count += 1
    db.flush()
    return read_count


#: The job's kind (``services/jobs.py``) and how many documents it reads per transaction.
JOB = "numbers"
BATCH = 100
PAUSE_SECONDS = 0.2


def run_job(db: Session, payload: Any) -> None:
    """The job ``numbers``: one portion of the documents after ``payload["after"]`` (by id) read where needed, then the
    job is queued again for the next portion (the loop's pause between two runs is the pause between portions). Ends
    when the last document was looked at. A stop in between costs at most one portion read twice (it changes
    nothing)."""
    from . import changes, jobs

    after = payload.get("after", 0) if isinstance(payload, dict) else 0
    after = after if isinstance(after, int) and after >= 0 else 0
    changes.write_lock(db)
    ids = list(db.scalars(select(Document.id).where(Document.id > after).order_by(Document.id).limit(BATCH)))
    if not ids:
        db.rollback()
        logger.info("Numbers of the documents read")
        return
    refresh(db, ids)
    jobs.enqueue(db, JOB, 0, {"after": ids[-1]})
    db.commit()
    # A breath between two portions: the write lock is free, and what waits behind (a rename) goes first.
    jobs.stopping.wait(PAUSE_SECONDS)


# --- Right before a commit -----------------------------------------------------------------------------------------


def _before_commit(session: Session) -> None:
    """The documents that took a change number in this transaction (``search_index.SEQ_KEY``, read and left for the
    search index, which runs after this): their numbers follow their text in the same transaction."""
    from . import search_index

    first = session.info.get(search_index.SEQ_KEY)
    if first is None:
        return
    session.flush()
    ids = list(session.scalars(select(Document.id).where(Document.change_seq >= first)))
    if not ids:
        return
    if len(ids) > SYNC_LIMIT:
        from . import jobs

        jobs.enqueue(session, JOB, 0, {"after": 0})
        return
    refresh(session, ids)


# First of the listeners: the search index takes the number off the session.
event.listen(Session, "before_commit", _before_commit, insert=True)


# --- For the transfer code (K1) ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Payment:
    """What a transfer for a document can take: its IBANs and its invoice number, each with where it comes from
    (``einvoice`` or ``text``). The IBANs of the e-invoice first; when there is one, the text is not asked."""

    ibans: list[tuple[str, str]]
    invoice_number: tuple[str, str] | None


def for_payment(db: Session, document_id: int) -> Payment:
    """The IBANs and the invoice number of a document as they were read. No rights here: the caller checked them."""
    rows = db.execute(select(DocumentNumber.kind, DocumentNumber.value, DocumentNumber.origin)
                      .where(DocumentNumber.document_id == document_id, DocumentNumber.kind.in_((IBAN, INVOICE)))
                      .order_by(DocumentNumber.id)).all()
    ibans = [(value, origin) for kind, value, origin in rows if kind == IBAN]
    ibans.sort(key=lambda item: item[1] != EINVOICE)
    invoices = [(value, origin) for kind, value, origin in rows if kind == INVOICE]
    invoices.sort(key=lambda item: item[1] != EINVOICE)
    return Payment(ibans=ibans, invoice_number=invoices[0] if invoices else None)


__all__ = ["JOB", "KINDS", "Number", "Payment", "compare_form", "for_payment", "ibans_in", "read", "refresh",
           "run_job"]
