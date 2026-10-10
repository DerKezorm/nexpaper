"""What kind of file came in, read from its content and nothing else.

Neither the name nor the type a browser claims counts: a program renamed ``.pdf``, a web page named ``.png`` and a
picture drawn as SVG (which can carry a script) are all turned away. These kinds are taken: PDF, JPEG, PNG, TIFF, HEIC
(the photo format of iPhones), WebP and AVIF (what Android phones, newer cameras and browsers save) and XML, the last
one only when it is an e-invoice (UBL or CII); reading it comes with a later block, here it is kept. The decision looks
at the first bytes only, so it costs nothing and nothing large is held in memory. Whether the file can really be opened
is found out later, in the worker, where a broken file harms nobody.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

#: What may stand before the "%PDF-" of a PDF: a byte order mark and white space.
BEFORE_PDF = bytes([0xEF, 0xBB, 0xBF, 0x20, 0x09, 0x0D, 0x0A, 0x00])
#: How many bytes ``sniff`` looks at.
HEAD = 4096

PDF, JPEG, PNG, TIFF, HEIC, WEBP, AVIF, XML = "pdf", "jpeg", "png", "tiff", "heic", "webp", "avif", "xml"
KINDS = (PDF, JPEG, PNG, TIFF, HEIC, WEBP, AVIF, XML)
#: What the answer to a refused file lists (the browser's own sentence has the same list: ``errors.unsupported_type``).
ALLOWED = "PDF, JPEG, PNG, TIFF, HEIC, WebP, AVIF or XML"
#: The ending a file of each kind gets on the disk, and what a browser is told it is.
EXTENSION = {PDF: ".pdf", JPEG: ".jpg", PNG: ".png", TIFF: ".tif", HEIC: ".heic", WEBP: ".webp",
             AVIF: ".avif", XML: ".xml"}
MEDIA_TYPE = {PDF: "application/pdf", JPEG: "image/jpeg", PNG: "image/png", TIFF: "image/tiff", HEIC: "image/heic",
              WEBP: "image/webp", AVIF: "image/avif", XML: "application/xml"}
#: What a browser shows in place (everything else is offered as a download).
INLINE = {PDF, JPEG, PNG}
IMAGES = (JPEG, PNG, TIFF, HEIC, WEBP, AVIF)
KIND_OF_EXTENSION = {value: key for key, value in EXTENSION.items()}

_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1"}
#: AVIF shares the generic HEIF brands (``mif1``) with HEIC; it is a different codec, told apart by these brands.
_AVIF_BRANDS = {b"avif", b"avis"}
#: The roots of the e-invoice formats this app is to read: CII (ZUGFeRD, Factur-X, XRechnung) and UBL.
_INVOICE_ROOTS = {"crossindustryinvoice", "invoice", "creditnote"}
_ROOT = re.compile(rb"<\s*(?:([A-Za-z_][\w.-]*):)?([A-Za-z_][\w.-]*)")


class NotAccepted(Exception):
    """The file is not one this server takes. ``reason`` is a short code for the answer."""

    def __init__(self, reason: str, text: str) -> None:
        super().__init__(text)
        self.reason = reason
        self.text = text


@dataclass(frozen=True)
class Found:
    kind: str

    @property
    def extension(self) -> str:
        return EXTENSION[self.kind]


def _xml_root(head: bytes) -> str | None:
    """The local name of the first element of an XML text, or None when it is none. A prolog, comments and a byte order
    mark may come before it; a DOCTYPE may not (a document type is how external entities get in)."""
    text = head[3:] if head.startswith(b"\xef\xbb\xbf") else head
    text = text.lstrip()
    if text.startswith(b"<?xml"):
        end = text.find(b"?>")
        if end < 0:
            return None
        text = text[end + 2 :].lstrip()
    while text.startswith(b"<!--"):
        end = text.find(b"-->")
        if end < 0:
            return None
        text = text[end + 3 :].lstrip()
    if text[:9].upper() == b"<!DOCTYPE" and not text[9:].lstrip().lower().startswith(b"html"):
        raise NotAccepted("xml_doctype", "XML with a document type definition is not taken.")
    if text[:9].upper() == b"<!DOCTYPE" or text.startswith(b"<!ENTITY"):
        return None
    if not text.startswith(b"<"):
        return None
    found = _ROOT.match(text)
    return found.group(2).decode("ascii", "replace") if found else None


def sniff(head: bytes) -> Found:
    """The kind of the file whose first bytes are ``head`` (at most ``HEAD`` are looked at), or ``NotAccepted``."""
    head = head[:HEAD]
    marker = head[:1024].find(b"%PDF-")
    if marker >= 0 and not head[:marker].strip(BEFORE_PDF):
        return Found(PDF)
    if head.startswith(b"\xff\xd8\xff"):
        return Found(JPEG)
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return Found(PNG)
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return Found(TIFF)
    if head[4:8] == b"ftyp" and len(head) >= 12:
        size = struct.unpack(">I", head[:4])[0]
        brands = {head[8:12]} | {head[at : at + 4] for at in range(16, min(size, len(head)) - 3, 4)}
        if brands & _AVIF_BRANDS:
            return Found(AVIF)
        if brands & _HEIF_BRANDS:
            return Found(HEIC)
        raise NotAccepted("unsupported_type", f"This kind of file is not taken. Use {ALLOWED}.")
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP" and head[12:16] in (b"VP8 ", b"VP8L", b"VP8X"):
        return Found(WEBP)
    if head.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<"):
        root = _xml_root(head)
        if root is not None and root.lower() in _INVOICE_ROOTS:
            return Found(XML)
        if root is not None and root.lower() not in ("svg", "html"):
            raise NotAccepted("xml_not_invoice", "XML is taken only as an e-invoice (UBL or CII).")
    raise NotAccepted("unsupported_type", f"This kind of file is not taken. Use {ALLOWED}.")


#: Characters that turn the direction of text around (embeddings, overrides, isolates, marks): in a title they make
#: "Rechnung exe.txt" out of "Rechnung txt.exe". They are taken out of titles and of the names of files.
BIDI_CONTROLS = dict.fromkeys([*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x200E, 0x200F, 0x061C])
#: What a title is called when nothing of the name or the subject is left.
NO_TITLE = "Document"


def _plain(text: str) -> str:
    text = text.translate(BIDI_CONTROLS)
    text = "".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in text)
    return " ".join(text.split())


def file_name(filename: str) -> str:
    """A file name as it was sent, kept until the file is taken (an upload in pieces): no folder, no control or
    direction characters, at most 200 characters with its ending. The title is made of it once, when the file is
    taken (``title_from``)."""
    name = _plain(filename.replace("\\", "/").rsplit("/", 1)[-1])
    if len(name) > 200:
        stem, dot, ending = name.rpartition(".")
        name = f"{stem[:199 - len(ending)]}.{ending}" if dot and 0 < len(ending) <= 10 else name[:200]
    return name


def plain_title(text: str) -> str:
    """A title of a text (the subject of a mail): no control or direction characters, at most 200 characters, never
    empty."""
    return _plain(text).strip(" .")[:200] or NO_TITLE


def title_from(filename: str) -> str:
    """A title proposed by a file name: no folder, no ending, no control or direction characters, at most 200
    characters; a name of nothing else (an ending alone, ".pdf") gets ``NO_TITLE``. A name longer than 200 characters
    is cut as ``file_name`` cuts it, so a file sent in pieces is called the same as one sent at once."""
    name = file_name(filename)
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return plain_title(stem)
