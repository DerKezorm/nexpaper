"""E-invoices: the data of a ZUGFeRD or Factur-X PDF (the XML inside it) and of an XRechnung (UBL or CII as XML).

Read **only in the worker process** (``app/worker.py`` loads this file by its path): an invoice comes from outside, and
whatever a hostile file does to the parser happens there, under the time and memory limits. This file imports nothing
from ``app`` (the worker stands alone); the server uses its constants and ``summary`` only.

**The XML is parsed safely.** lxml with ``resolve_entities=False``, ``no_network=True``, ``load_dtd=False`` and
``huge_tree=False`` (libxml2's own limits on depth and on the size of a text node stay on); on top of that, an XML text
that names a document type or an entity is refused before it is parsed at all (no e-invoice needs one, and it is how
entity bombs and external entities come in), as is one larger than ``MAX_XML`` bytes, deeper than ``MAX_DEPTH``, or
with more attributes, namespace declarations or tags than ``MAX_ATTRIBUTES``, ``MAX_NAMESPACES`` and ``MAX_TAGS`` allow
(libxml2 checks the attributes and namespaces of one element against each other, so tens of thousands of them keep
the one worker busy for minutes; the marks are counted in the bytes, before the parser runs). The XML inside a PDF is
read by a child process of its own with a short time limit (``read_within``): a hostile XML then costs only the
e-invoice, never the PDF.

**Fields exactly from the data**, never guessed: number, issue date, due date, seller (name, VAT id), buyer reference
(the "Leitweg-ID" of German authorities), IBAN, net, tax, gross, currency, lines. Amounts are decimals in the XML and
become whole cents here (rounded half up); a text is cut to its length and cleaned of control characters. What the
invoice does not say stays empty.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

#: The largest XML that is read (an e-invoice is a few kilobytes, one with a thousand lines some hundred).
MAX_XML = 1024 * 1024
#: The most attributes (counted as ``=``), namespace declarations and tags in an XML text. A real invoice has some
#: hundred attributes, a few dozen namespaces and a few thousand tags; these are far above that and still cheap.
MAX_ATTRIBUTES = 10_000
MAX_NAMESPACES = 200
MAX_TAGS = 200_000
#: How long the XML inside a PDF may take to be read, in seconds.
EMBEDDED_SECONDS = 5.0
#: The deepest nesting that is read; an e-invoice goes a dozen levels deep.
MAX_DEPTH = 40
#: The most lines kept, and the longest text of a field.
MAX_LINES = 200
TEXT_MAX = 200
#: The names an e-invoice has inside a PDF (ZUGFeRD 1 and 2, Factur-X, XRechnung in a PDF), compared without case.
EMBEDDED_NAMES = ("factur-x.xml", "zugferd-invoice.xml", "zugferd_invoice.xml", "xrechnung.xml", "order-x.xml")
#: The largest file inside a PDF that is looked at.
MAX_EMBEDDED = MAX_XML
#: The most files inside a PDF that are looked at.
MAX_ATTACHMENTS = 50

UBL_ROOTS = ("Invoice", "CreditNote")
CII_ROOTS = ("CrossIndustryInvoice", "CrossIndustryDocument")
_FORBIDDEN = (b"<!DOCTYPE", b"<!ENTITY", b"<!doctype", b"<!entity")
_DATE8 = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_DATE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_IBAN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$")


class InvoiceRefused(Exception):
    """An XML text that is not read: too large, too deep, with a document type, or no e-invoice at all."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# --- Reading XML safely -----------------------------------------------------------------------------------------------


def _parser() -> Any:
    from lxml import etree

    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False,
                           huge_tree=False, remove_comments=True, remove_pis=True, recover=False)


def parse_xml(data: bytes) -> Any:
    """The root element of an XML text, or ``InvoiceRefused``. Nothing is fetched, no entity is expanded."""
    from lxml import etree

    if len(data) > MAX_XML:
        raise InvoiceRefused("too_large")
    if any(marker in data for marker in _FORBIDDEN):
        raise InvoiceRefused("xml_doctype")
    # Counted without the zero bytes of UTF-16 and UTF-32, so every encoding is counted alike.
    flat = data.replace(b"\x00", b"")
    if flat.count(b"=") > MAX_ATTRIBUTES or flat.count(b"xmlns") > MAX_NAMESPACES or flat.count(b"<") > MAX_TAGS:
        raise InvoiceRefused("too_complex")
    try:
        root = etree.fromstring(data, parser=_parser())
    except etree.XMLSyntaxError as exc:
        raise InvoiceRefused("broken") from exc
    except (ValueError, MemoryError) as exc:
        raise InvoiceRefused("broken") from exc
    if root is None:
        raise InvoiceRefused("broken")
    info = root.getroottree().docinfo
    if info.doctype or info.internalDTD is not None or info.externalDTD is not None:
        # A document type in another encoding than the check of the bytes above sees (UTF-16): parsed without
        # loading or expanding anything, and refused all the same.
        raise InvoiceRefused("xml_doctype")
    if _depth(root) > MAX_DEPTH:
        raise InvoiceRefused("too_deep")
    return root


def _depth(root: Any) -> int:
    """How deep the tree goes, counted without recursion."""
    deepest = 0
    stack = [(root, 1)]
    while stack:
        element, level = stack.pop()
        deepest = max(deepest, level)
        if level > MAX_DEPTH:
            return level
        stack.extend((child, level + 1) for child in element)
    return deepest


def _local(element: Any) -> str:
    tag = element.tag
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _children(element: Any, name: str) -> list[Any]:
    return [child for child in element if _local(child) == name]


def _find(element: Any, path: str) -> Any:
    """The first element along a path of local names (``A/B/C``), namespaces aside; None when there is none."""
    current = [element]
    for name in path.split("/"):
        found = []
        for item in current:
            found.extend(_children(item, name))
        if not found:
            return None
        current = found
    return current[0]


def _all(element: Any, path: str) -> list[Any]:
    current = [element]
    for name in path.split("/"):
        found = []
        for item in current:
            found.extend(_children(item, name))
        current = found
    return current


def clean_text(value: str | None, limit: int = TEXT_MAX) -> str:
    """One line of text: control and format characters out, spaces joined, cut to ``limit``."""
    if not value:
        return ""
    value = unicodedata.normalize("NFC", value)
    kept = "".join(" " if unicodedata.category(char) in ("Cc", "Cf", "Zl", "Zp") else char for char in value)
    return " ".join(kept.split())[:limit]


def _text(element: Any, path: str, limit: int = TEXT_MAX) -> str:
    found = _find(element, path) if path else element
    if found is None:
        return ""
    return clean_text("".join(found.itertext()), limit)


def cents(value: str | None) -> int | None:
    """A decimal amount of the XML (``189.00``, ``-12.5``) as whole cents; None for anything else."""
    if not value:
        return None
    try:
        number = Decimal(value.strip())
    except InvalidOperation:
        return None
    if not number.is_finite() or abs(number) >= Decimal(10) ** 12:
        return None
    return int((number * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _quantity(value: str | None) -> str:
    """A quantity as it is written, shortened (``1.000`` becomes ``1``); empty for what is no number."""
    if not value:
        return ""
    try:
        number = Decimal(value.strip())
    except InvalidOperation:
        return ""
    if not number.is_finite() or abs(number) >= Decimal(10) ** 9:
        return ""
    text = format(number.normalize(), "f")
    return text[:20]


def iso_date(value: str | None) -> str:
    """``2026-10-01`` from ``20261001`` (CII format 102) or ``2026-10-01`` (UBL); empty for anything else."""
    value = (value or "").strip()
    found = _DATE8.match(value) or _DATE_ISO.match(value)
    if not found:
        return ""
    year, month, day = (int(part) for part in found.groups())
    if not (1900 <= year <= 2200 and 1 <= month <= 12 and 1 <= day <= 31):
        return ""
    import datetime

    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return ""


def clean_iban(value: str | None) -> str:
    """An IBAN without spaces in capitals, when its check digits are right; empty else."""
    compact = re.sub(r"\s+", "", value or "").upper()[:40]
    if not _IBAN.match(compact):
        return ""
    moved = compact[4:] + compact[:4]
    digits = "".join(str(int(char, 36)) for char in moved)
    return compact if int(digits) % 97 == 1 else ""


def _currency(value: str | None) -> str:
    value = (value or "").strip().upper()
    return value if re.fullmatch(r"[A-Z]{3}", value) else ""


# --- UBL -------------------------------------------------------------------------------------------------------------


def _ubl(root: Any) -> dict[str, Any]:
    credit = _local(root) == "CreditNote"
    seller = _find(root, "AccountingSupplierParty/Party")
    buyer = _find(root, "AccountingCustomerParty/Party")
    totals = _find(root, "LegalMonetaryTotal")
    due = _text(root, "DueDate") or _text(root, "PaymentMeans/PaymentDueDate")
    iban = ""
    for account in _all(root, "PaymentMeans/PayeeFinancialAccount"):
        iban = clean_iban(_text(account, "ID"))
        if iban:
            break
    tax = None
    for total in _all(root, "TaxTotal"):
        amount = cents(_text(total, "TaxAmount"))
        if amount is not None:
            tax = amount
            break
    lines = []
    for line in _all(root, "CreditNoteLine" if credit else "InvoiceLine")[:MAX_LINES]:
        quantity = _find(line, "CreditedQuantity" if credit else "InvoicedQuantity")
        lines.append({
            "text": _text(line, "Item/Name") or _text(line, "Item/Description"),
            "quantity": _quantity("".join(quantity.itertext())) if quantity is not None else "",
            "unit": clean_text(quantity.get("unitCode"), 8) if quantity is not None else "",
            "price": cents(_text(line, "Price/PriceAmount")),
            "total": cents(_text(line, "LineExtensionAmount")),
        })
    customization = _text(root, "CustomizationID", 300).lower()
    return {
        "syntax": "ubl",
        "xrechnung": "xrechnung" in customization,
        "profile": _profile(customization),
        "credit_note": credit,
        "number": _text(root, "ID", 100),
        "issued": iso_date(_text(root, "IssueDate")),
        "due": iso_date(due),
        "currency": _currency(_text(root, "DocumentCurrencyCode")),
        "seller": (_text(seller, "PartyLegalEntity/RegistrationName") or _text(seller, "PartyName/Name"))
        if seller is not None else "",
        "seller_vat": _text(seller, "PartyTaxScheme/CompanyID", 40) if seller is not None else "",
        "buyer": (_text(buyer, "PartyLegalEntity/RegistrationName") or _text(buyer, "PartyName/Name"))
        if buyer is not None else "",
        "buyer_ref": _text(root, "BuyerReference", 100),
        "iban": iban,
        "net": cents(_text(totals, "TaxExclusiveAmount")) if totals is not None else None,
        "tax": tax,
        "gross": cents(_text(totals, "TaxInclusiveAmount")) if totals is not None else None,
        "payable": cents(_text(totals, "PayableAmount")) if totals is not None else None,
        "lines": lines,
    }


# --- CII -------------------------------------------------------------------------------------------------------------


def _cii(root: Any) -> dict[str, Any]:
    document = _find(root, "ExchangedDocument")
    trade = _find(root, "SupplyChainTradeTransaction")
    agreement = _find(trade, "ApplicableHeaderTradeAgreement") if trade is not None else None
    settlement = _find(trade, "ApplicableHeaderTradeSettlement") if trade is not None else None
    seller = _find(agreement, "SellerTradeParty") if agreement is not None else None
    buyer = _find(agreement, "BuyerTradeParty") if agreement is not None else None
    sums = _find(settlement, "SpecifiedTradeSettlementHeaderMonetarySummation") if settlement is not None else None
    iban = ""
    vat = ""
    if seller is not None:
        for registration in _all(seller, "SpecifiedTaxRegistration"):
            found = _find(registration, "ID")
            if found is not None and (found.get("schemeID") or "").upper() == "VA":
                vat = clean_text("".join(found.itertext()), 40)
                break
    if settlement is not None:
        for means in _all(settlement, "SpecifiedTradeSettlementPaymentMeans"):
            iban = clean_iban(_text(means, "PayeePartyCreditorFinancialAccount/IBANID"))
            if iban:
                break
    currency = _currency(_text(settlement, "InvoiceCurrencyCode")) if settlement is not None else ""
    tax = None
    if sums is not None:
        # A tax total may come twice (in the invoice's currency and in the tax currency): the invoice's counts.
        for total in _children(sums, "TaxTotalAmount"):
            unit = _currency(total.get("currencyID"))
            if not unit or not currency or unit == currency:
                tax = cents("".join(total.itertext()))
                break
    due = ""
    if settlement is not None:
        for terms in _all(settlement, "SpecifiedTradePaymentTerms"):
            due = iso_date(_text(terms, "DueDateDateTime/DateTimeString"))
            if due:
                break
    lines = []
    for line in (_all(trade, "IncludedSupplyChainTradeLineItem") if trade is not None else [])[:MAX_LINES]:
        quantity = _find(line, "SpecifiedLineTradeDelivery/BilledQuantity")
        lines.append({
            "text": _text(line, "SpecifiedTradeProduct/Name"),
            "quantity": _quantity("".join(quantity.itertext())) if quantity is not None else "",
            "unit": clean_text(quantity.get("unitCode"), 8) if quantity is not None else "",
            "price": cents(_text(line, "SpecifiedLineTradeAgreement/NetPriceProductTradePrice/ChargeAmount")),
            "total": cents(_text(line, "SpecifiedLineTradeSettlement/SpecifiedTradeSettlementLineMonetarySummation/"
                                       "LineTotalAmount")),
        })
    guideline = _text(root, "ExchangedDocumentContext/GuidelineSpecifiedDocumentContextParameter/ID", 300).lower()
    return {
        "syntax": "cii",
        "xrechnung": "xrechnung" in guideline,
        "profile": _profile(guideline),
        "credit_note": _text(document, "TypeCode", 8) == "381" if document is not None else False,
        "number": _text(document, "ID", 100) if document is not None else "",
        "issued": iso_date(_text(document, "IssueDateTime/DateTimeString")) if document is not None else "",
        "due": due,
        "currency": currency,
        "seller": _text(seller, "Name") if seller is not None else "",
        "seller_vat": vat,
        "buyer": _text(buyer, "Name") if buyer is not None else "",
        "buyer_ref": _text(agreement, "BuyerReference", 100) if agreement is not None else "",
        "iban": iban,
        "net": cents(_text(sums, "TaxBasisTotalAmount")) if sums is not None else None,
        "tax": tax,
        "gross": cents(_text(sums, "GrandTotalAmount")) if sums is not None else None,
        "payable": cents(_text(sums, "DuePayableAmount")) if sums is not None else None,
        "lines": lines,
    }


#: Words in the specification's id (``urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0``) and the
#: profile they name, the most specific first.
PROFILES = (("xrechnung", "XRechnung"), ("extended", "EXTENDED"), ("en16931", "EN 16931"), ("basicwl", "BASIC WL"),
            ("basic", "BASIC"), ("minimum", "MINIMUM"))


def _profile(identifier: str) -> str:
    for word, name in PROFILES:
        if word in identifier:
            return name
    return ""


def read_invoice(data: bytes) -> dict[str, Any]:
    """The fields of an e-invoice given as XML (UBL or CII); ``InvoiceRefused`` for anything else."""
    root = parse_xml(data)
    name = _local(root)
    if name in UBL_ROOTS:
        return _ubl(root)
    if name in CII_ROOTS:
        return _cii(root)
    raise InvoiceRefused("not_invoice")


# --- The XML inside a PDF ---------------------------------------------------------------------------------------------


def read_within(data: bytes, seconds: float | None = None) -> dict[str, Any] | None:
    """``read_invoice(data)`` in a child process of its own that is stopped after ``seconds``. None when it took too
    long or failed in any way (the XML is then no invoice; the PDF that carried it stays what it is). ``InvoiceRefused``
    still comes for an XML that is plainly refused (the parent knows the same checks)."""
    limit = EMBEDDED_SECONDS if seconds is None else seconds
    try:
        done = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve())], input=data, capture_output=True,
                              timeout=limit, check=False)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    if done.returncode != 0 or len(done.stdout) > 4 * MAX_XML:
        return None
    try:
        found = json.loads(done.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None
    if not isinstance(found, dict):
        return None
    if "refused" in found:
        raise InvoiceRefused(str(found["refused"])[:40])
    return found


def _main() -> None:
    """The child of ``read_within``: the XML on standard input; the fields or the refusal as JSON on standard output."""
    data = sys.stdin.buffer.read(MAX_XML + 2)
    try:
        answer: dict[str, Any] = read_invoice(data)
    except InvoiceRefused as exc:
        answer = {"refused": exc.code}
    sys.stdout.write(json.dumps(answer, default=str))



def embedded_xml(path: Path) -> tuple[str, bytes] | None:
    """The e-invoice inside a PDF (ZUGFeRD, Factur-X): ``(its name, its bytes)`` or None. Only the files a PDF attaches
    by name are looked at, at most ``MAX_ATTACHMENTS``; one larger than ``MAX_EMBEDDED`` is left alone. A PDF that
    cannot be opened has none."""
    import pikepdf

    try:
        pdf = pikepdf.open(path)
    except Exception:  # noqa: BLE001 - a PDF pikepdf cannot read has no invoice for us; reading it is the worker's job
        return None
    try:
        attachments = pdf.attachments
        names = list(attachments.keys())[:MAX_ATTACHMENTS]
        wanted = sorted((name for name in names if name.lower() in EMBEDDED_NAMES),
                        key=lambda name: EMBEDDED_NAMES.index(name.lower()))
        for name in wanted:
            try:
                spec = attachments[name]
                stream = spec.get_file()
                size = int(stream.size or 0)
                if size > MAX_EMBEDDED:
                    continue
                data = stream.read_bytes()
            except Exception:  # noqa: BLE001, S112 - a broken attachment is no invoice
                continue
            if len(data) <= MAX_EMBEDDED:
                return name, data
        return None
    finally:
        pdf.close()


def format_name(found: dict[str, Any], embedded_name: str = "") -> str:
    """What the interface calls the format: ``ZUGFeRD (EN 16931)``, ``Factur-X (BASIC)``, ``XRechnung (UBL)``,
    ``XRechnung (CII)``, ``UBL``, ``CII``."""
    syntax = "UBL" if found.get("syntax") == "ubl" else "CII"
    profile = str(found.get("profile") or "")
    if embedded_name:
        family = "Factur-X" if embedded_name.lower().startswith("factur-x") else (
            "XRechnung" if embedded_name.lower().startswith("xrechnung") else "ZUGFeRD")
        if family == "XRechnung" or profile == "XRechnung":
            return f"XRechnung ({syntax})"
        return f"{family} ({profile})" if profile else family
    if found.get("xrechnung"):
        return f"XRechnung ({syntax})"
    return syntax


def summary(found: dict[str, Any]) -> dict[str, Any]:
    """Only the keys the server keeps, of the types it expects; whatever else came is dropped. The server calls this on
    the worker's answer once more: it trusts the shape of nothing that crossed a process."""
    def text(key: str, limit: int = TEXT_MAX) -> str:
        value = found.get(key)
        return clean_text(value, limit) if isinstance(value, str) else ""

    def number(key: str) -> int | None:
        value = found.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and abs(value) < 10**14 else None

    lines = []
    raw = found.get("lines")
    for line in raw[:MAX_LINES] if isinstance(raw, list) else []:
        if not isinstance(line, dict):
            continue
        price, total = line.get("price"), line.get("total")
        lines.append({
            "text": clean_text(line.get("text"), TEXT_MAX) if isinstance(line.get("text"), str) else "",
            "quantity": clean_text(line.get("quantity"), 20) if isinstance(line.get("quantity"), str) else "",
            "unit": clean_text(line.get("unit"), 8) if isinstance(line.get("unit"), str) else "",
            "price": price if isinstance(price, int) and not isinstance(price, bool) and abs(price) < 10**14 else None,
            "total": total if isinstance(total, int) and not isinstance(total, bool) and abs(total) < 10**14 else None,
        })
    return {
        "format": text("format", 40), "number": text("number", 100), "issued": iso_date(text("issued", 10)),
        "due": iso_date(text("due", 10)), "currency": _currency(text("currency", 3)), "seller": text("seller"),
        "seller_vat": text("seller_vat", 40), "buyer": text("buyer"), "buyer_ref": text("buyer_ref", 100),
        "iban": clean_iban(text("iban", 40)), "net": number("net"), "tax": number("tax"), "gross": number("gross"),
        "payable": number("payable"), "credit_note": found.get("credit_note") is True, "lines": lines,
    }


__all__ = ["InvoiceRefused", "embedded_xml", "format_name", "parse_xml", "read_invoice", "read_within", "summary"]


if __name__ == "__main__":
    _main()
