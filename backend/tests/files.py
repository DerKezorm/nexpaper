"""Files made in the tests: PDFs, pictures, e-invoices, broken and hostile ones. Nothing real, nothing from outside; every
file is built here from a few lines (the content is made up: Stadtwerke Lindenau, Julia Mustermann, example.com)."""

from __future__ import annotations

import io
from collections.abc import Iterable

FONT = 20


def make_pdf(texts: Iterable[str] = ("Rechnung 2026-1001 Stadtwerke Lindenau",), size: tuple[int, int] = (595, 842),
             padding: int = 0) -> bytes:
    """A valid PDF with one page per text (lines are separated by a line break; Helvetica, drawn by PDFium like any
    other), built by hand with a real cross-reference table. ``padding``: bytes of an object nothing refers to (random, so
    that it does not compress), to make a large file that is still a PDF."""
    pages = list(texts)
    objects: list[bytes] = []
    count = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(count))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode())
    for index, text in enumerate(pages):
        page_id = 3 + 2 * index
        content_id = page_id + 1
        shown = []
        for number, line in enumerate(text.split("\n")):
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            shown.append(f"({safe}) Tj" if number == 0 else f"0 -{FONT * 2} Td ({safe}) Tj")
        stream = f"BT /F1 {FONT} Tf 60 {size[1] - 120} Td {' '.join(shown)} ET".encode("cp1252", "replace")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {size[0]} {size[1]}] /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >> >> >> >>".encode())
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    if padding:
        import os

        objects.append(b"<< /Length " + str(padding).encode() + b" >>\nstream\n" + os.urandom(padding) + b"\nendstream")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_image(kind: str = "png", size: tuple[int, int] = (300, 400), text: str = "Quittung 14,90 EUR", **options: object) -> bytes:
    """A picture of the kind (png, jpeg, tiff, heic, webp, avif) with some text drawn on white."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).text((20, 30), text, fill="black")
    for row in range(60, min(size[1], 300), 24):
        ImageDraw.Draw(image).line((20, row, size[0] - 20, row), fill="gray", width=2)
    buffer = io.BytesIO()
    if kind == "heic":
        import pillow_heif

        pillow_heif.register_heif_opener()
        image.save(buffer, "HEIF", quality=70)
    elif kind in ("webp", "avif"):
        image.save(buffer, kind.upper(), **{"quality": 80, **options})  # type: ignore[arg-type]
    else:
        image.save(buffer, {"jpeg": "JPEG", "png": "PNG", "tiff": "TIFF"}[kind], **options)  # type: ignore[arg-type]
    return buffer.getvalue()


def make_hdr_jpeg(size: tuple[int, int] = (600, 800)) -> bytes:
    """What Safari sends for an HDR photo from an iPhone: a JPEG with its gain map as a second picture behind it
    (Multi-Picture Format). The photo is red and taller than wide, the gain map grey, small and wider than tall."""
    from PIL import Image

    photo = Image.new("RGB", size, (220, 30, 30))
    gain = Image.new("L", (size[1] // 4, size[0] // 4), 128)
    buffer = io.BytesIO()
    photo.save(buffer, "MPO", save_all=True, append_images=[gain])
    return buffer.getvalue()


def make_animated_webp(frames: int = 4, size: tuple[int, int] = (120, 160)) -> bytes:
    """A WebP animation: every frame has its own number on it."""
    from PIL import Image, ImageDraw

    images = []
    for index in range(frames):
        image = Image.new("RGB", size, "white")
        ImageDraw.Draw(image).text((10, 10), f"Bild {index + 1}", fill="black")
        images.append(image)
    buffer = io.BytesIO()
    images[0].save(buffer, "WEBP", save_all=True, append_images=images[1:], duration=100, lossless=True)
    return buffer.getvalue()


def bomb_webp(width: int = 3000, height: int = 3000) -> bytes:
    """A WebP that is tiny on the disk and large in memory (a white sheet of ``width`` x ``height`` pixels)."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, "WEBP", lossless=True)
    return buffer.getvalue()


def make_tiff(frames: int = 2) -> bytes:
    from PIL import Image, ImageDraw

    images = []
    for index in range(frames):
        image = Image.new("RGB", (200, 280), "white")
        ImageDraw.Draw(image).text((10, 10), f"Seite {index + 1}", fill="black")
        images.append(image)
    buffer = io.BytesIO()
    images[0].save(buffer, "TIFF", save_all=True, append_images=images[1:])
    return buffer.getvalue()


def encrypted_pdf(password: str) -> bytes:
    """A PDF that needs a password to be opened (pikepdf writes it; it is only used here, to make the test file)."""
    import pikepdf

    source = pikepdf.open(io.BytesIO(make_pdf(["Vertraulich"])))
    out = io.BytesIO()
    source.save(out, encryption=pikepdf.Encryption(user=password, owner=password + "-owner"))
    return out.getvalue()


def broken_pdf() -> bytes:
    """A PDF that starts right and is cut off in the middle."""
    return make_pdf(["Abgeschnitten"])[:90]


def bomb_png(width: int = 3000, height: int = 3000) -> bytes:
    """A picture that is tiny on the disk and large in memory (a white sheet of ``width`` x ``height`` pixels)."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("1", (width, height), 1).save(buffer, "PNG")
    return buffer.getvalue()


def invoice_xml(number: str = "2026-1001") -> bytes:
    """A small e-invoice in the UBL shape (made up)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
        'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
        f"<cbc:ID>{number}</cbc:ID><cbc:IssueDate>2026-10-01</cbc:IssueDate></Invoice>\n"
    ).encode()


def cii_xml() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100">'
        b"</rsm:CrossIndustryInvoice>\n"
    )


EXE = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 200
HTML = b"<!DOCTYPE html><html><body><script>alert(1)</script></body></html>"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><script>alert(1)</script></svg>'
