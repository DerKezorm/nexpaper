"""E-invoices on the server side: keeping what the worker read (``app/einvoice_reader.py``), and handing it out.

The worker reads the XML (inside a ZUGFeRD or Factur-X PDF, or an XRechnung that came as XML) in its own process; what
comes back is checked once more here (``einvoice_reader.summary``: only known keys of the expected types) and kept in
``einvoices``, one row for the version that carries it. A later version (pages turned or joined, B5) no longer carries
the XML; the document shows the data of the newest version that did. The rights are those of reading the document.
"""

from __future__ import annotations

import base64
import binascii
from datetime import date as Date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, undefer

from .. import clock, einvoice_reader
from ..errors import error
from ..models import Document, EInvoice, Version
from . import filetypes, rights


def _day(value: str) -> Date | None:
    try:
        return Date.fromisoformat(value) if value else None
    except ValueError:
        return None


def keep(db: Session, document: Document, version: Version, data: dict[str, Any]) -> EInvoice | None:
    """The e-invoice the worker found for ``version`` (``data["einvoice"]``), in the caller's transaction; nothing when
    it found none. Replaces what an earlier run of the same version kept."""
    raw = data.get("einvoice")
    if not isinstance(raw, dict):
        return None
    found = einvoice_reader.summary(raw)
    if not found["format"]:
        return None
    xml: bytes | None = None
    encoded = raw.get("xml")
    if isinstance(encoded, str) and encoded:
        try:
            xml = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            xml = None
        if xml is not None and len(xml) > einvoice_reader.MAX_EMBEDDED:
            xml = None
    row = db.get(EInvoice, version.id)
    if row is None:
        row = EInvoice(version_id=version.id, document_id=document.id)
        db.add(row)
    row.format = found["format"]
    row.number, row.seller, row.seller_vat = found["number"], found["seller"], found["seller_vat"]
    row.buyer, row.buyer_ref, row.iban = found["buyer"], found["buyer_ref"], found["iban"]
    row.currency = found["currency"]
    row.issued, row.due = _day(found["issued"]), _day(found["due"])
    row.net, row.tax, row.gross, row.payable = found["net"], found["tax"], found["gross"], found["payable"]
    row.credit_note = found["credit_note"]
    row.lines = found["lines"]
    row.xml = xml
    row.created_at = clock.now()
    return row


def amount_of(row: EInvoice) -> int | None:
    """What the invoice asks to be paid: the amount due, else the gross total (a credit note as a negative amount)."""
    value = row.payable if row.payable is not None else row.gross
    if value is None:
        return None
    return -abs(value) if row.credit_note else value


def latest(db: Session, document_id: int) -> EInvoice | None:
    """The e-invoice of the newest version of a document that carries one."""
    return db.scalars(
        select(EInvoice).join(Version, Version.id == EInvoice.version_id)
        .where(EInvoice.document_id == document_id).order_by(Version.n.desc()).limit(1)
    ).first()


def formats(db: Session, document_ids: list[int]) -> dict[int, str]:
    """The format of the e-invoice of each of these documents that has one, in one query (for lists)."""
    if not document_ids:
        return {}
    newest = (select(EInvoice.document_id, func.max(Version.n).label("n"))
              .join(Version, Version.id == EInvoice.version_id)
              .where(EInvoice.document_id.in_(document_ids)).group_by(EInvoice.document_id).subquery())
    rows = db.execute(
        select(EInvoice.document_id, EInvoice.format).join(Version, Version.id == EInvoice.version_id)
        .join(newest, (newest.c.document_id == EInvoice.document_id) & (newest.c.n == Version.n))
    ).all()
    return {document_id: name for document_id, name in rows}


def numbers(db: Session, document_ids: list[int]) -> dict[int, str]:
    """The invoice number of each of these documents that has an e-invoice (for the export's list)."""
    if not document_ids:
        return {}
    rows = db.execute(
        select(EInvoice.document_id, EInvoice.number, Version.n).join(Version, Version.id == EInvoice.version_id)
        .where(EInvoice.document_id.in_(document_ids)).order_by(Version.n)
    ).all()
    return {document_id: number for document_id, number, _n in rows}


def detail(db: Session, uid: int, document_id: int) -> tuple[EInvoice, int, bool]:
    """The e-invoice of a document the caller may read: the row, the number of the version that carries it, and whether
    that version's original is the XML itself. 404 when there is none (or the caller may not see the document)."""
    rights.require_document(db, uid, document_id)
    row = latest(db, document_id)
    if row is None:
        raise error("not_found", "Not found.", 404)
    version = db.get(Version, row.version_id)
    assert version is not None
    return row, version.n, filetypes.KIND_OF_EXTENSION.get(_suffix(version.original_path)) == filetypes.XML


def _suffix(path: str) -> str:
    dot = path.rfind(".")
    return path[dot:].lower() if dot >= 0 else ""


def xml_of(db: Session, uid: int, document_id: int, number: int) -> tuple[Document, Version, bytes | None]:
    """The XML of the e-invoice of one version, for somebody who may read the document: the bytes taken out of a PDF,
    or None when the original of the version is the XML itself (the caller sends the file). 404 when the version
    carries no e-invoice."""
    access = rights.require_document(db, uid, document_id)
    version = db.scalar(select(Version).where(Version.document_id == document_id, Version.n == number))
    if version is None:
        raise error("not_found", "Not found.", 404)
    row = db.scalars(select(EInvoice).options(undefer(EInvoice.xml)).where(EInvoice.version_id == version.id)).first()
    if row is None:
        raise error("not_found", "Not found.", 404)
    if filetypes.KIND_OF_EXTENSION.get(_suffix(version.original_path)) == filetypes.XML:
        return access.document, version, None
    if not row.xml:
        raise error("not_found", "Not found.", 404)
    return access.document, version, row.xml


def embedded_xml(db: Session, version_id: int) -> bytes | None:
    """The XML taken out of the PDF of a version (for the export), or None."""
    return db.scalar(select(EInvoice.xml).where(EInvoice.version_id == version_id))


__all__ = ["amount_of", "detail", "embedded_xml", "formats", "keep", "latest", "numbers", "xml_of"]
