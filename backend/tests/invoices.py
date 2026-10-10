"""Made-up documents for the tests of the text: monthly invoices of one form (only month, dates, numbers and amounts
change, as with power or phone), and sheets drawn as a scanner or a phone would deliver them (a little skewed, noisy,
as PNG, JPEG or a PDF of pictures). No real names, no real addresses."""

from __future__ import annotations

import io
import random

MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November",
          "Dezember"]


def monthly_invoice(month: int, customer: str = "K-4711-0815") -> list[str]:
    """The lines of the invoice of one month (1 to 12) of a made-up power company."""
    rng = random.Random(month * 7919)
    kwh = 180 + rng.randint(0, 140)
    net = kwh * 0.3245 + 12.5
    gross = round(net * 1.19, 2)
    name = MONTHS[month - 1]
    return [
        "Stadtwerke Lindenau GmbH, Lindenallee 4, 12345 Lindenau",
        "Frau Jule Beispiel, Am Muehlbach 3, 12345 Lindenau",
        f"Rechnung Nr. 2026-{month:02d}-{rng.randint(10000, 99999)}",
        f"Rechnungsdatum {rng.randint(1, 5):02d}.{month:02d}.2026",
        f"Kundennummer {customer}   Vertragskonto 600 123 456",
        f"Abrechnungszeitraum 01.{month:02d}.2026 bis 28.{month:02d}.2026 ({name})",
        f"Verbrauch {kwh} kWh, Arbeitspreis 0,3245 EUR/kWh",
        "Grundpreis 12,50 EUR",
        f"Nettobetrag {net:.2f} EUR".replace(".", ","),
        f"Umsatzsteuer 19 Prozent {gross - net:.2f} EUR".replace(".", ","),
        f"Rechnungsbetrag {gross:.2f} EUR".replace(".", ","),
        f"Bitte ueberweisen Sie den Betrag bis zum 15.{month:02d}.2026",
        "IBAN DE00 1234 5678 9012 3456 78, Kreissparkasse Lindenau",
        "Fragen? Telefon 01234 56789, Montag bis Freitag 8 bis 18 Uhr",
    ]


def sheet(lines: list[str], *, angle: float = 0.0, noise: int = 0, brightness: int = 255, seed: int = 1,
          width: int = 1654, height: int = 2339) -> object:
    """The lines drawn on an A4 sheet at 200 dpi as a scanner sees it: turned by ``angle`` degrees, with ``noise``
    specks, on paper of ``brightness``. Returns a Pillow picture."""
    from PIL import Image, ImageDraw, ImageFont

    picture = Image.new("L", (width, height), brightness)
    draw = ImageDraw.Draw(picture)
    font = ImageFont.load_default(size=40)
    for number, line in enumerate(lines):
        draw.text((140, 160 + number * 78), line, fill=20, font=font)
    if angle:
        picture = picture.rotate(angle, fillcolor=brightness, resample=Image.Resampling.BICUBIC)
    if noise:
        rng = random.Random(seed)
        pixels = picture.load()
        for _ in range(noise):
            x, y = rng.randrange(width), rng.randrange(height)
            pixels[x, y] = rng.choice((0, 90, 160))
    return picture


def picture_bytes(picture: object, kind: str = "png", quality: int = 85) -> bytes:
    out = io.BytesIO()
    if kind == "jpeg":
        picture.convert("RGB").save(out, "JPEG", quality=quality, dpi=(200, 200))  # type: ignore[attr-defined]
    else:
        picture.save(out, "PNG", dpi=(200, 200))  # type: ignore[attr-defined]
    return out.getvalue()


def scan_pdf(*pictures: object) -> bytes:
    """A PDF of pictures only, one per page, as a scanner writes it (no text in it)."""
    import img2pdf

    return img2pdf.convert([picture_bytes(p, "jpeg", 80) for p in pictures])


def joined_pdf(*parts: bytes) -> bytes:
    """Several PDFs as one."""
    import pikepdf

    out = pikepdf.Pdf.new()
    opened = [pikepdf.open(io.BytesIO(part)) for part in parts]
    for pdf in opened:
        out.pages.extend(pdf.pages)
    buffer = io.BytesIO()
    out.save(buffer)
    return buffer.getvalue()
