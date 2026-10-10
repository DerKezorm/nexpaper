"""Made-up batch scans for the tests of the blank separator pages: sheets as a scanner at 150 dots per inch would give
them, with the noise of the scanner, specks of dust, a sheet that went in at a slant (dark wedges beside it), the
writing of the other side shining through, a tinted paper; and the pages that must not be taken for empty ones: a back
that carries only its page number, a page with one short line. Every page is drawn here from a seed, the same each run;
nothing real (Stadtwerke Lindenau, example.com)."""

from __future__ import annotations

import io
import random
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFont

#: A sheet of A4 at 150 dots per inch.
SIZE = (1240, 1754)
DPI = 150


def _points(size_pt: float) -> int:
    return max(6, round(size_pt / 72 * DPI))


@dataclass
class Sheet:
    """How one made-up scan looks."""

    #: What stands on it: none (an empty sheet), a page number, a line, a letter, a pale page of text (``pale``), a pale
    #: receipt (``receipt``), a bar across the sheet (``bar``), ruled paper (``ruled``).
    content: str = "empty"
    #: The grey of the writing of a pale page, a receipt, a bar or the rules.
    ink: int = 25
    text: str = ""
    size_pt: float = 9
    #: The paper's grey (255 is white); a tinted or recycled paper is darker.
    paper: int = 246
    #: Gaussian noise of the scanner (standard deviation in grey levels).
    noise: float = 6
    #: Specks of dust: how many, and how large at most (pixels across).
    specks: int = 0
    speck_size: int = 2
    #: Turned by this many degrees, the corners filled with the dark lid of the scanner (``wedge``).
    slant: float = 0
    wedge: int = 20
    #: The writing of the other side, shining through in this grey (0: none).
    show_through: int = 0
    #: Saved as a JPEG of this quality before it goes into the PDF (0: no JPEG).
    jpeg: int = 70
    seed: int = 1


def draw(sheet: Sheet) -> Image.Image:
    rng = random.Random(sheet.seed)
    image = Image.new("L", SIZE, sheet.paper)
    pen = ImageDraw.Draw(image)
    if sheet.show_through:
        mirrored = Image.new("L", SIZE, 0)
        ghost = ImageDraw.Draw(mirrored)
        font = ImageFont.load_default(size=_points(11))
        for row in range(10):
            ghost.text((140, 220 + row * 60), "Stadtwerke Lindenau, Abschlag fuer Strom und Gas", fill=255, font=font)
        mirrored = mirrored.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        shade = Image.new("L", SIZE, sheet.show_through)
        image.paste(shade, mask=mirrored)
    font = ImageFont.load_default(size=_points(sheet.size_pt))
    if sheet.content == "number":
        width = pen.textlength(sheet.text or "- 2 -", font=font)
        pen.text(((SIZE[0] - width) / 2, SIZE[1] - _points(sheet.size_pt) - 110), sheet.text or "- 2 -", fill=25,
                 font=font)
    elif sheet.content == "line":
        pen.text((150, 200), sheet.text or "Anlage: Zaehlerstand vom 14.03.2026", fill=25, font=font)
    elif sheet.content == "letter":
        big = ImageFont.load_default(size=_points(11))
        pen.text((150, 160), sheet.text or "Stadtwerke Lindenau, Rechnung 2026-1001", fill=20, font=big)
        for row in range(30):
            length = rng.randint(500, 940)
            pen.text((150, 260 + row * 42), ("Abschlag Strom Gas Wasser " * 6)[: length // 18], fill=30, font=big)
    elif sheet.content == "pale":
        text = ImageFont.load_default(size=_points(11))
        for row in range(20):
            pen.text((150, 250 + row * 55), "Quittung Stadtwerke Lindenau Betrag 14,90 EUR zahlbar bis", fill=sheet.ink,
                     font=text)
    elif sheet.content == "receipt":
        text = ImageFont.load_default(size=_points(10))
        for row in range(3):
            pen.text((420, 300 + row * 45), "SUMME EUR 14,90  MwSt 19%", fill=sheet.ink, font=text)
    elif sheet.content == "bar":
        pen.rectangle((0, 160, SIZE[0], 200), fill=sheet.ink)
    elif sheet.content == "ruled":
        for y in range(240, SIZE[1] - 100, 50):
            pen.line((0, y, SIZE[0], y), fill=sheet.ink, width=2)
    for _ in range(sheet.specks):
        x, y = rng.randint(30, SIZE[0] - 30), rng.randint(30, SIZE[1] - 30)
        size = rng.randint(1, sheet.speck_size)
        pen.ellipse((x, y, x + size - 1, y + size - 1), fill=rng.randint(20, 90))
    if sheet.noise:
        noise = Image.effect_noise(SIZE, sheet.noise)
        image = ImageChops.add(image, noise, scale=1.0, offset=-128)
    if sheet.slant:
        image = image.rotate(sheet.slant, resample=Image.Resampling.BICUBIC, fillcolor=sheet.wedge)
    return image


def pdf_of(sheets: list[Sheet]) -> bytes:
    """A PDF with one scanned page per sheet, as a scanner writes it (a JPEG per page)."""
    pages = []
    for sheet in sheets:
        image = draw(sheet)
        if sheet.jpeg:
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=sheet.jpeg)
            image = Image.open(io.BytesIO(buffer.getvalue()))
        pages.append(image.convert("RGB"))
    out = io.BytesIO()
    pages[0].save(out, "PDF", save_all=True, append_images=pages[1:], resolution=float(DPI))
    return out.getvalue()


#: Empty sheets as scanners give them: each must count as empty.
EMPTY = [
    Sheet(seed=1),
    Sheet(noise=14, seed=2),
    Sheet(specks=40, speck_size=2, seed=3),
    Sheet(specks=6, speck_size=3, seed=4),
    Sheet(slant=2.5, wedge=15, seed=5),
    Sheet(slant=-1.5, wedge=60, noise=10, seed=6),
    Sheet(show_through=205, seed=7),
    Sheet(paper=226, noise=10, seed=8),
    Sheet(show_through=200, slant=1.2, specks=20, noise=12, jpeg=50, seed=9),
]

#: Sheets that are nearly empty but are no separator: each must count as a page.
NEARLY_EMPTY = [
    Sheet(content="number", text="- 2 -", size_pt=9, seed=11),
    Sheet(content="number", text="2", size_pt=10, seed=12),
    Sheet(content="number", text="Seite 2 von 2", size_pt=8, seed=13),
    Sheet(content="number", text="- 3 -", size_pt=9, noise=14, specks=20, seed=14),
    Sheet(content="line", size_pt=10, seed=15),
    Sheet(content="number", text="2", size_pt=10, slant=2.0, show_through=205, seed=16),
    # Pale writing: a page of text in grey 160 and 170, a faded receipt, a bar across the sheet, ruled paper.
    Sheet(content="pale", ink=160, seed=17),
    Sheet(content="pale", ink=170, seed=18),
    Sheet(content="receipt", ink=160, seed=19),
    Sheet(content="bar", ink=40, seed=20),
    Sheet(content="ruled", ink=150, seed=22),
]

LETTER = Sheet(content="letter", seed=21)
