"""The readable copy of an e-invoice that came as XML only: a plain A4 PDF set from its fields.

Set **in the worker process** (``app/worker.py`` loads this file by its path), like the reading of the XML: what is set
comes from outside. No library and no font file: the PDF is written here with the two standard fonts every PDF reader
has (Helvetica and Helvetica-Bold, WinAnsi), their widths for breaking lines below. A typesetting program such as
Typst would add some 30 MB and a program of its own to the image for one plain page, and fpdf2 is not there on every
machine nexpaper is developed on. A character the fonts do not have becomes ``?``; the XML stays the original and
keeps it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

WIDTH, HEIGHT = 595, 842
LEFT, RIGHT, TOP, BOTTOM = 56, 539, 786, 64
#: More pages than this are not set (a thousand lines): the rest is in the XML.
MAX_PAGES = 30

_REGULAR = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, *[556] * 10, 278, 278, 584,
            584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778,
            722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278,
            556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334,
            260, 334, 584]
_BOLD = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, *[556] * 10, 333, 333, 584,
         584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722,
         667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611,
         278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]

LABELS = {
    "de": {
        "title": "Rechnung", "credit": "Gutschrift", "number": "Rechnungsnummer", "issued": "Rechnungsdatum",
        "due": "Zahlbar bis", "seller": "Verkäufer", "vat": "USt-IdNr.", "buyer": "Käufer", "buyer_ref": "Leitweg-ID",
        "iban": "IBAN", "format": "Format", "quantity": "Menge", "item": "Bezeichnung", "price": "Einzelpreis",
        "total": "Betrag", "net": "Netto", "tax": "Umsatzsteuer", "gross": "Gesamt", "payable": "Zu zahlen",
        "more": "Weitere Positionen stehen im XML.",
        "footer": "Lesbare Fassung, von nexpaper aus der E-Rechnung gesetzt. Das XML bleibt das Original.",
    },
    "en": {
        "title": "Invoice", "credit": "Credit note", "number": "Invoice number", "issued": "Invoice date",
        "due": "Due", "seller": "Seller", "vat": "VAT ID", "buyer": "Buyer", "buyer_ref": "Buyer reference",
        "iban": "IBAN", "format": "Format", "quantity": "Qty", "item": "Item", "price": "Unit price",
        "total": "Amount", "net": "Net", "tax": "VAT", "gross": "Total", "payable": "Amount due",
        "more": "More lines are in the XML.",
        "footer": "Readable copy, set by nexpaper from the e-invoice. The XML stays the original.",
    },
}


def _encode(value: str) -> bytes:
    return value.encode("cp1252", "replace")


def width(value: str, size: float, bold: bool = False) -> float:
    table = _BOLD if bold else _REGULAR
    total = 0
    for byte in _encode(value):
        total += table[byte - 32] if 32 <= byte <= 126 else 556
    return total * size / 1000


def _escape(value: str) -> bytes:
    return _encode(value).replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def wrap(value: str, room: float, size: float, bold: bool = False) -> list[str]:
    """The text broken into lines that fit ``room`` points; a word longer than a line is cut."""
    lines: list[str] = []
    current = ""
    for word in value.split():
        trial = f"{current} {word}" if current else word
        if width(trial, size, bold) <= room:
            current = trial
            continue
        if current:
            lines.append(current)
        while width(word, size, bold) > room and len(word) > 1:
            cut = len(word)
            while cut > 1 and width(word[:cut], size, bold) > room:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return lines or [""]


def money(amount: int | None, currency: str, language: str) -> str:
    if amount is None:
        return ""
    sign = "-" if amount < 0 else ""
    whole, part = divmod(abs(amount), 100)
    grouped = f"{whole:,}"
    if language == "de":
        return f"{sign}{grouped.replace(',', '.')},{part:02d} {currency}".strip()
    return f"{currency} {sign}{grouped}.{part:02d}".strip()


def day(value: str, language: str) -> str:
    if len(value) != 10:
        return value
    year, month, number = value.split("-")
    return f"{number}.{month}.{year}" if language == "de" else value


class _Pages:
    def __init__(self) -> None:
        self.pages: list[list[bytes]] = [[]]
        self.y = TOP

    @property
    def full(self) -> bool:
        return len(self.pages) >= MAX_PAGES

    def need(self, height: float) -> bool:
        """Room for ``height`` points, on a new page when this one is full; False when no page may be added."""
        if self.y - height >= BOTTOM:
            return True
        if self.full:
            return False
        self.pages.append([])
        self.y = TOP
        return True

    def text(self, x: float, y: float, value: str, size: float, bold: bool = False) -> None:
        font = b"/F2" if bold else b"/F1"
        self.pages[-1].append(b"BT " + font + b" %.1f Tf %.2f %.2f Td (" % (size, x, y) + _escape(value) + b") Tj ET")

    def right(self, x: float, y: float, value: str, size: float, bold: bool = False) -> None:
        self.text(x - width(value, size, bold), y, value, size, bold)

    def rule(self, y: float) -> None:
        self.pages[-1].append(b"0.75 G 0.5 w %d %.2f m %d %.2f l S 0 G" % (LEFT, y, RIGHT, y))


def write(found: dict[str, Any], target: Path, language: str = "de") -> int:
    """The readable copy of ``found`` (``einvoice_reader.summary``) as a PDF at ``target``; returns its pages."""
    words = LABELS.get(language, LABELS["en"])
    currency = str(found.get("currency") or "")
    sheet = _Pages()
    heading = words["credit"] if found.get("credit_note") else words["title"]
    seller = str(found.get("seller") or "")
    for line in wrap(seller or heading, RIGHT - LEFT, 18, True)[:3]:
        sheet.text(LEFT, sheet.y, line, 18, True)
        sheet.y -= 24
    sheet.text(LEFT, sheet.y, f"{heading} {found.get('number') or ''}".strip(), 11)
    sheet.y -= 28
    facts = [
        (words["number"], str(found.get("number") or "")),
        (words["issued"], day(str(found.get("issued") or ""), language)),
        (words["due"], day(str(found.get("due") or ""), language)),
        (words["seller"], seller),
        (words["vat"], str(found.get("seller_vat") or "")),
        (words["buyer"], str(found.get("buyer") or "")),
        (words["buyer_ref"], str(found.get("buyer_ref") or "")),
        (words["iban"], str(found.get("iban") or "")),
        (words["format"], str(found.get("format") or "")),
    ]
    for label, value in facts:
        if not value:
            continue
        rows = wrap(value, RIGHT - LEFT - 130, 10)
        if not sheet.need(14 * len(rows)):
            break
        sheet.text(LEFT, sheet.y, label, 10, True)
        for row in rows:
            sheet.text(LEFT + 130, sheet.y, row, 10)
            sheet.y -= 14
    sheet.y -= 14
    lines = found.get("lines") or []
    if lines and sheet.need(40):
        sheet.text(LEFT, sheet.y, words["quantity"], 9, True)
        sheet.text(LEFT + 50, sheet.y, words["item"], 9, True)
        sheet.right(RIGHT - 90, sheet.y, words["price"], 9, True)
        sheet.right(RIGHT, sheet.y, words["total"], 9, True)
        sheet.y -= 6
        sheet.rule(sheet.y)
        sheet.y -= 14
        for line in lines:
            item = wrap(str(line.get("text") or ""), RIGHT - LEFT - 50 - 190, 9)
            if not sheet.need(12 * len(item) + 4):
                sheet.text(LEFT, max(sheet.y, BOTTOM), words["more"], 9)
                break
            quantity = " ".join(part for part in (str(line.get("quantity") or ""), str(line.get("unit") or "")) if part)
            sheet.text(LEFT, sheet.y, quantity, 9)
            sheet.right(RIGHT - 90, sheet.y, money(line.get("price"), currency, language), 9)
            sheet.right(RIGHT, sheet.y, money(line.get("total"), currency, language), 9)
            for row in item:
                sheet.text(LEFT + 50, sheet.y, row, 9)
                sheet.y -= 12
            sheet.y -= 4
        sheet.rule(sheet.y + 8)
        sheet.y -= 8
    for key in ("net", "tax", "gross", "payable"):
        amount = found.get(key)
        if amount is None or (key == "payable" and amount == found.get("gross")):
            continue
        if not sheet.need(16):
            break
        bold = key in ("gross", "payable")
        sheet.text(RIGHT - 230, sheet.y, words[key], 10, bold)
        sheet.right(RIGHT, sheet.y, money(amount, currency, language), 10, bold)
        sheet.y -= 16
    for page in sheet.pages:
        page.append(b"BT /F1 8 Tf 0.4 g %d %d Td (" % (LEFT, BOTTOM - 30) + _escape(words["footer"]) + b") Tj ET")
    return _save(sheet.pages, target)


def _save(pages: list[list[bytes]], target: Path) -> int:
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    fonts = (b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
             b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    objects.extend(fonts)
    kids = []
    for content in pages:
        stream = b"\n".join(content)
        page_id = len(objects) + 1
        kids.append(page_id)
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
                       b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>" % (WIDTH, HEIGHT, page_id + 1))
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % kid for kid in kids) + b"] /Count %d >>" % len(kids)
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.part")
    partial.write_bytes(bytes(out))
    partial.replace(target)
    return len(pages)


__all__ = ["write"]
