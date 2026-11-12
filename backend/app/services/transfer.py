"""The transfer code ("Überweisen", K1): what a bank transfer for a document can take, and the EPC QR code ("GiroCode")
a banking app scans.

**What it takes.** The recipient is the seller of the document's e-invoice, else its sender. The IBANs are the ones read
from the document (``services/numbers.py``): those of the e-invoice first; when there is one, the text is not asked. The
amount is what the e-invoice says is to be paid, else the amount of the document. The purpose is the invoice number.
Each comes with where it is from (``einvoice``, ``text``, ``sender``, ``document``), because a forged invoice carries a
strange IBAN in its text: the page says "read from the text, compare with the document". It is enough (``ready``) with
at least one IBAN, an amount above 0, the euro, a recipient, and no credit note.

**The code** is made for one of the document's own IBANs (never one the caller chooses), an amount from 0.01 to
999,999,999.99 euros and a purpose of at most 140 characters of the SEPA set (with the German umlauts). Nothing of it is
stored, and neither the IBAN nor the purpose goes to the log: they travel in the body of the request, not in its
address. The lines follow EPC069-12 (version 002, character set 1, UTF-8): service tag, version, character set,
identification, BIC (empty), name, IBAN, amount ``EUR12.30``, purpose code (empty), structured reference (empty),
text. Error correction M.

**Rights.** Reading the document is enough (a browser, a device; the information also for a key that reads). Never
through a link, and never in a reminder.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import segno
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..einvoice_reader import clean_iban
from ..errors import error
from ..models import Document, EInvoice, Sender, Version
from . import numbers, rights

#: The most a code may ask for, in cents, and the least.
AMOUNT_MIN = 1
AMOUNT_MAX = 99_999_999_999
#: The purpose ("Verwendungszweck") and the recipient's name, at most, in characters.
PURPOSE_MAX = 140
NAME_MAX = 70
#: The most bytes the data of an EPC code may have.
PAYLOAD_MAX = 331
#: What a purpose may hold: the SEPA set of Latin characters, and the German umlauts and ß German banks take.
PURPOSE_CHARS = re.compile(r"[A-Za-z0-9/\-?:().,'+ ÄÖÜäöüß]*")
EURO = "EUR"
EINVOICE, TEXT, SENDER, DOCUMENT = "einvoice", "text", "sender", "document"


@dataclass
class Info:
    """What a transfer for a document can take, each with where it comes from."""

    recipient: str = ""
    recipient_origin: str | None = None
    ibans: list[tuple[str, str]] = field(default_factory=list)
    amount: int | None = None
    amount_origin: str | None = None
    currency: str = EURO
    purpose: str = ""
    purpose_origin: str | None = None
    #: The newest e-invoice is a credit note: nothing to pay.
    credit_note: bool = False

    @property
    def missing(self) -> list[str]:
        """Why it is not enough: ``iban``, ``amount``, ``currency``, ``recipient``, ``credit_note``; empty when it
        is."""
        out = []
        if not self.ibans:
            out.append("iban")
        if self.amount is None or self.amount < AMOUNT_MIN or self.amount > AMOUNT_MAX:
            out.append("amount")
        if self.currency != EURO:
            out.append("currency")
        if not self.recipient:
            out.append("recipient")
        if self.credit_note:
            out.append("credit_note")
        return out

    @property
    def ready(self) -> bool:
        return not self.missing


def clean_name(value: str) -> str:
    """A name as the code carries it: one line, no control characters, at most ``NAME_MAX`` characters."""
    text = " ".join("".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in value or "").split())
    return text[:NAME_MAX].rstrip()


def _invoice(db: Session, document_id: int) -> EInvoice | None:
    """The e-invoice of the newest version of the document that carries one."""
    return db.scalar(select(EInvoice).join(Version, Version.id == EInvoice.version_id)
                     .where(EInvoice.document_id == document_id).order_by(Version.n.desc()).limit(1))


def info_of(db: Session, document: Document) -> Info:
    """What a transfer for the document can take. No rights here: the caller checked them."""
    out = Info()
    invoice = _invoice(db, document.id)
    sender = db.get(Sender, document.sender_id) if document.sender_id else None
    if invoice is not None and clean_name(invoice.seller):
        out.recipient, out.recipient_origin = clean_name(invoice.seller), EINVOICE
    elif sender is not None and clean_name(sender.name):
        out.recipient, out.recipient_origin = clean_name(sender.name), SENDER
    payment = numbers.for_payment(db, document.id)
    out.ibans = [(iban, origin) for iban, origin in payment.ibans if clean_iban(iban)]
    if invoice is not None and invoice.payable is not None:
        out.amount, out.amount_origin = invoice.payable, EINVOICE
        out.currency = (invoice.currency or document.currency or EURO).upper()
        out.credit_note = bool(invoice.credit_note)
    elif document.amount is not None:
        out.amount, out.amount_origin = document.amount, DOCUMENT
        out.currency = (document.currency or EURO).upper()
    else:
        out.currency = (document.currency or EURO).upper()
    if payment.invoice_number is not None:
        value, origin = payment.invoice_number
        purpose = _purpose_of(value)
        if purpose:
            out.purpose, out.purpose_origin = purpose, origin
    return out


def _purpose_of(number: str) -> str:
    """An invoice number as a purpose: only the characters a purpose may hold, at most ``PURPOSE_MAX``."""
    kept = "".join(char for char in number if PURPOSE_CHARS.fullmatch(char))
    return " ".join(kept.split())[:PURPOSE_MAX]


def info(db: Session, uid: int, document_id: int) -> Info:
    """``info_of`` for a document the caller may read (404 else)."""
    access = rights.require_document(db, uid, document_id)
    return info_of(db, access.document)


# --- The code ---------------------------------------------------------------------------------------------------------


def check_purpose(value: str) -> str:
    """The purpose as the code carries it, or ``invalid_purpose``: one line, at most ``PURPOSE_MAX`` characters of
    ``PURPOSE_CHARS``. Blanks at both ends go."""
    text = value.strip()
    if len(text) > PURPOSE_MAX:
        raise error("invalid_purpose", f"A purpose has at most {PURPOSE_MAX} characters.", 422, max=PURPOSE_MAX)
    if not PURPOSE_CHARS.fullmatch(text):
        wrong = next(char for char in text if not PURPOSE_CHARS.fullmatch(char))
        # The character is named only when it is one a person can read (never a control character).
        shown = wrong if wrong.isprintable() else ""
        raise error("invalid_purpose", "A purpose holds letters, digits, blanks and / - ? : ( ) . , ' + only.", 422,
                    char=shown)
    return text


def amount_text(cents: int) -> str:
    """``EUR12.30``: euros with a point and two places, no separator of thousands."""
    return f"{EURO}{cents // 100}.{cents % 100:02d}"


def payload(*, name: str, iban: str, cents: int, text: str = "", bic: str = "", purpose_code: str = "",
            reference: str = "", info: str = "", version: str = "002") -> bytes:
    """The data of an EPC QR code (EPC069-12), in UTF-8 (character set 1), lines parted by a line feed; what is empty at
    the end is left out. ``bic``, ``purpose_code``, ``reference`` and ``info`` are not used by nexpaper (they are here
    for the example of the standard)."""
    if not 1 <= len(name) <= NAME_MAX or "\n" in name:
        raise error("invalid_recipient", "The recipient's name has 1 to 70 characters.", 422)
    if not AMOUNT_MIN <= cents <= AMOUNT_MAX:
        raise error("invalid_amount", "An amount from 0.01 to 999,999,999.99 euros.", 422)
    amount = amount_text(cents) if version == "002" or cents % 100 else f"{EURO}{cents // 100}"
    lines = ["BCD", version, "1", "SCT", bic, name, iban, amount, purpose_code, reference, text, info]
    while lines and lines[-1] == "":
        lines.pop()
    data = "\n".join(lines).encode("utf-8")
    if len(data) > PAYLOAD_MAX:
        raise error("transfer_too_long", "The name and the purpose are too long together for a code.", 422)
    return data


def svg_of(data: bytes) -> str:
    """The code as SVG: error correction M (the standard asks for it, no other)."""
    code = segno.make_qr(data, error="m", boost_error=False)
    out = io.BytesIO()
    code.save(out, kind="svg", scale=4, dark="#111111", light="#ffffff", border=4, xmldecl=False, svgns=True)
    return out.getvalue().decode("utf-8")


def code(db: Session, uid: int, document_id: int, iban: str, cents: int, purpose: str) -> str:
    """The code for a document the caller may read: one of its own IBANs (``unknown_iban`` for any other), an amount,
    a purpose. ``transfer_not_possible`` when the document gives no transfer (another currency, no recipient, a credit
    note, no IBAN). Nothing is stored."""
    text = check_purpose(purpose)
    if not AMOUNT_MIN <= cents <= AMOUNT_MAX:
        raise error("invalid_amount", "An amount from 0.01 to 999,999,999.99 euros.", 422)
    found = info(db, uid, document_id)
    blockers = [reason for reason in found.missing if reason != "amount"]
    if blockers:
        raise error("transfer_not_possible", "This document gives no transfer.", 409, missing=blockers)
    wanted = clean_iban(iban.replace(" ", "")) if isinstance(iban, str) else ""
    if not wanted or wanted not in {known for known, _origin in found.ibans}:
        raise error("unknown_iban", "Choose one of the IBANs of the document.", 422)
    return svg_of(payload(name=found.recipient, iban=wanted, cents=cents, text=text))


__all__ = [
    "AMOUNT_MAX",
    "AMOUNT_MIN",
    "PURPOSE_MAX",
    "Info",
    "amount_text",
    "check_purpose",
    "code",
    "info",
    "info_of",
    "payload",
    "svg_of",
]
