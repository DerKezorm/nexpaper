"""The worker: reads one document's file in a process of its own and reports what it found.

Run as ``python -I app/worker.py`` by ``services/processing.py``, one process for one task, then it ends. A broken or
hostile file can take only this process down: the server asked for a time limit (it kills the process when it is
reached) and, where the system allows it, a memory limit (``setrlimit``); the process has no database, no settings and
no secret, only the paths it was given and what it prints back. Nothing from ``app`` is imported for that reason: this
file stands alone (the standard library, Pillow, pillow-heif, pypdfium2, img2pdf and ocrmypdf).

Input: one JSON object on standard input. Output: one JSON object on the last line of standard output.

* ``{"op": "process", ...}``: a file that has just come in. Pictures become a PDF beside the original (``archive_out``);
  the pages are counted, the first page is drawn as the preview picture (``thumb_out``) and fingerprinted. Answer:
  ``{"ok": true, "pages": n, "phash": "...", "derived": true|false}`` or ``{"ok": false, "error": code, "retry":
  false}``. The codes: ``encrypted``, ``broken``, ``too_many_pages``, ``too_large``.
* ``{"op": "render", ...}``: one page of a PDF drawn as a WebP picture of a given width.
* ``{"op": "render_pages", ...}``: the pages ``first`` to ``last`` (counted from 1) of a PDF drawn as WebP pictures into
  ``pattern`` (``{page}`` is the number), the ones that are there already left as they are. For the pictures of a long
  document, drawn in the background after it was read, at a lower priority than the server. Answer: ``{"ok": true,
  "drawn": n}``.
* ``{"op": "recognize", ...}``: the text of every page; where a page carries none, ocrmypdf (Tesseract) recognises it
  and writes a searchable copy of the PDF (``recognize``). ocrmypdf is imported only here, and only when it is needed.
* ``{"op": "assemble", ...}``: new PDFs made of pages of others (the page tools: turn, delete, put in another order,
  join, split), with pikepdf; each new PDF gets its preview, its small pages and its fingerprint (``assemble``).
* ``{"op": "blanks", ...}``: how much ink each page carries, to find the empty sheets put between letters (``blanks``).
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

#: A page wider or higher than this many points (1 point = 1/72 inch) is refused: no real sheet is, and the standard's
#: own limit is 14,400.
MAX_PAGE_POINTS = 20_000
#: The picture of a page is never larger than this many pixels, whatever width was asked for.
DEFAULT_RENDER_PIXELS = 16_000_000
#: A fingerprint is a gradient hash of ``HASH_ROWS`` rows of ``HASH_COLUMNS`` neighbours each (``HASH_ROWS`` x
#: ``HASH_COLUMNS - 1`` bits, 1024 of them).
HASH_ROWS = 32
HASH_COLUMNS = 33
#: A page with fewer bits set than this has almost nothing on it (an empty sheet, one line): every such page would look
#: like every other, so it gets no fingerprint at all.
MIN_BITS = 48
#: The width the first page is drawn at for the fingerprint.
HASH_SOURCE_WIDTH = 512
#: A file being written has a name with this prefix until it is whole: a worker that is killed leaves it behind, and
#: the next start of the server sweeps such names away (``storage.sweep_incoming``, ``pagetools.sweep_scratch``).
PART = ".incoming-part-"


def _partial(target: Path, suffix: str = "") -> Path:
    return target.with_name(f"{PART}{os.getpid()}-{target.name}{suffix}")


class Refused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _limit_memory(megabytes: int) -> None:
    if megabytes <= 0:
        return
    try:
        import resource
    except ImportError:  # Windows has no setrlimit
        return
    size = megabytes * 1024 * 1024
    for name in ("RLIMIT_AS", "RLIMIT_DATA"):
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(getattr(resource, name), (size, size))
            return


def _stop_with_the_parent() -> None:
    """The server went away (killed, restarted): this process ends too instead of working on for nobody."""
    parent = os.getppid()

    def watch() -> None:
        while True:
            time.sleep(2)
            if os.getppid() != parent:
                os._exit(3)

    threading.Thread(target=watch, daemon=True).start()


# --- Pictures ---------------------------------------------------------------------------------------------------------


def _pillow(max_pixels: int) -> Any:
    import PIL.Image
    import pillow_heif

    pillow_heif.register_heif_opener()
    # Pillow warns above the limit and refuses above twice the limit (a decompression bomb); both stop here.
    PIL.Image.MAX_IMAGE_PIXELS = max_pixels
    return PIL.Image


def _drawn(page: Any, width: int, max_pixels: int) -> Any:
    """A page as a PIL picture ``width`` pixels wide (less when that would be more than ``max_pixels``)."""
    points_wide, points_high = page.get_size()
    if points_wide <= 0 or points_high <= 0:
        raise Refused("broken")
    if points_wide > MAX_PAGE_POINTS or points_high > MAX_PAGE_POINTS:
        # A sheet of paper this large does not exist (the PDF standard stops at 14,400 points, 200 inches); drawing it
        # small enough would only hide how large it is, and a limit on memory (``setrlimit``) is not everywhere.
        raise Refused("too_large")
    scale = width / points_wide
    if points_wide * scale * points_high * scale > max_pixels:
        scale = (max_pixels / (points_wide * points_high)) ** 0.5
    image = page.render(scale=scale).to_pil().convert("RGB")
    if scale * points_wide >= width - 1 and image.width != width:
        # The renderer rounds up; the picture is as wide as it was asked to be (a pixel or two, never more).
        image = image.resize((width, max(1, round(image.height * width / image.width))))
    return image


def _save_webp(image: Any, target: Path, quality: int = 78) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = _partial(target)
    image.save(partial, "WEBP", quality=quality, method=4)
    os.replace(partial, target)


def fingerprint(image: Any) -> str:
    """How a sheet looks, as 32 x 32 bits in 256 hex digits (or nothing for a page that is almost empty): the page in
    grey, its contrast stretched and blurred a
    little, shrunk to 33 x 32 and, for each row, 1 where a pixel is brighter than its right neighbour. The same sheet
    scanned or photographed again, with another brightness, resolution or compression, lands within a few bits
    (``services/similar.py`` says how many are too many)."""
    from PIL import Image, ImageFilter, ImageOps

    grey = ImageOps.autocontrast(image.convert("L"), cutoff=1).filter(ImageFilter.GaussianBlur(radius=2))
    small = grey.resize((HASH_COLUMNS, HASH_ROWS), resample=Image.Resampling.BOX)
    pixels = list(small.get_flattened_data())
    bits = 0
    for row in range(HASH_ROWS):
        for column in range(HASH_COLUMNS - 1):
            left = pixels[row * HASH_COLUMNS + column]
            right = pixels[row * HASH_COLUMNS + column + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    if bits.bit_count() < MIN_BITS:
        return ""
    return f"{bits:0{HASH_ROWS * (HASH_COLUMNS - 1) // 4}x}"


#: Kinds that are one picture to a document even when the file holds an animation or a series: the first frame is taken.
SINGLE_FRAME = ("webp", "avif")


def _check_picture(source: Path, max_pixels: int, max_pages: int, kind: str = "") -> tuple[Any, int]:
    """Opens a picture and checks its size (every frame of a multi-page TIFF); returns it and the number of frames.
    A WebP or AVIF that is an animation is one page, its first frame: its frames are not looked at."""
    image_module = _pillow(max_pixels)
    try:
        image = image_module.open(source)
        frames = 1 if kind in SINGLE_FRAME else int(getattr(image, "n_frames", 1) or 1)
        if frames > max_pages:
            raise Refused("too_many_pages")
        for index in range(frames):
            image.seek(index)
            if image.width * image.height > max_pixels:
                raise Refused("too_large")
        image.seek(0)
        return image, frames
    except Refused:
        raise
    except image_module.DecompressionBombError as exc:
        raise Refused("too_large") from exc
    except MemoryError:
        raise
    except Exception as exc:
        raise Refused("broken") from exc


def _to_pdf(source: Path, kind: str, target: Path, max_pixels: int, max_pages: int) -> None:
    """The picture as a PDF of one page per frame, written whole to a temporary name and put in place."""
    import img2pdf

    image, _frames = _check_picture(source, max_pixels, max_pages, kind)
    partial = _partial(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch: list[Path] = []
    try:
        feed: Path = source
        has_dpi = bool(image.info.get("dpi")) and all(60 <= float(part) <= 2400 for part in image.info["dpi"])
        if kind in ("heic", "webp", "avif"):
            # img2pdf does not know HEIC, WebP or AVIF: a JPEG of the same pixels (the first frame, turned upright,
            # transparency on white), goes in.
            upright = _opaque(image)
            feed = partial.with_suffix(".jpg")
            scratch.append(feed)
            upright.save(feed, "JPEG", quality=94)
            has_dpi = False
        layout = None if has_dpi else img2pdf.get_fixed_dpi_layout_fun((200, 200))
        try:
            data = img2pdf.convert(str(feed), layout_fun=layout) if layout else img2pdf.convert(str(feed))
        except Exception:  # noqa: BLE001 - transparency, odd colour modes, 16 bits: draw it again plainly
            data = _plain_pdf(image)
        partial.write_bytes(data)
        os.replace(partial, target)
    finally:
        image.close()
        for path in [partial, *scratch]:
            with contextlib.suppress(OSError):
                path.unlink()


def _opaque(image: Any) -> Any:
    """The first frame of a picture, turned upright, in opaque RGB (what is transparent becomes white)."""
    from PIL import Image, ImageOps

    image.seek(0)
    frame = ImageOps.exif_transpose(image)
    if frame.mode in ("RGBA", "LA", "PA", "P") or "transparency" in frame.info:
        frame = frame.convert("RGBA")
        sheet = Image.new("RGB", frame.size, (255, 255, 255))
        sheet.paste(frame, mask=frame.getchannel("A"))
        return sheet
    return frame.convert("RGB")


def _plain_pdf(image: Any) -> bytes:
    """A PDF of every frame of a picture that img2pdf would not take: opaque RGB (transparency on white), re-encoded."""
    from PIL import Image, ImageOps

    frames = []
    for index in range(int(getattr(image, "n_frames", 1) or 1)):
        image.seek(index)
        frame = ImageOps.exif_transpose(image)
        if frame.mode in ("RGBA", "LA", "P"):
            frame = frame.convert("RGBA")
            sheet = Image.new("RGB", frame.size, (255, 255, 255))
            sheet.paste(frame, mask=frame.getchannel("A"))
            frame = sheet
        frames.append(frame.convert("RGB"))
    buffer = io.BytesIO()
    frames[0].save(buffer, "PDF", save_all=True, append_images=frames[1:], resolution=200.0)
    return buffer.getvalue()


# --- Documents --------------------------------------------------------------------------------------------------------


def _open_pdf(path: Path) -> Any:
    import pypdfium2

    try:
        return pypdfium2.PdfDocument(str(path))
    except MemoryError:
        raise
    except pypdfium2.PdfiumError as exc:
        text = str(exc).lower()
        raise Refused("encrypted" if "password" in text else "broken") from exc
    except Exception as exc:
        raise Refused("broken") from exc


def process(request: dict[str, Any]) -> dict[str, Any]:
    source = Path(request["source"])
    kind = request["kind"]
    max_pixels = int(request.get("max_pixels") or 100_000_000)
    max_pages = int(request.get("max_pages") or 2000)
    render_pixels = int(request.get("render_pixels") or DEFAULT_RENDER_PIXELS)
    derived = False
    pdf_path = source
    invoice: dict[str, Any] = {}
    if kind == "xml":
        # An e-invoice that is XML only: its fields, and a readable copy set from them, read like a PDF from here on.
        invoice = _xml_invoice(source, Path(request["archive_out"]), str(request.get("language") or "de"))
        pdf_path = Path(request["archive_out"])
        derived = True
    elif kind == "pdf":
        invoice = _embedded_invoice(source)
    if kind not in ("pdf", "xml"):
        archive_out = Path(request["archive_out"])
        try:
            _to_pdf(source, kind, archive_out, max_pixels, max_pages)
        except (Refused, MemoryError):
            raise
        except Exception as exc:
            raise Refused("broken") from exc
        pdf_path = archive_out
        derived = True
    document = _open_pdf(pdf_path)
    try:
        pages = len(document)
        if pages < 1:
            raise Refused("broken")
        if pages > max_pages:
            raise Refused("too_many_pages")
        page = document[0]
        try:
            first = _drawn(page, HASH_SOURCE_WIDTH, render_pixels)
            phash = fingerprint(first)
            thumb = request.get("thumb_out")
            if thumb:
                width = int(request.get("thumb_width") or 360)
                if first.width > width:
                    first = first.resize((width, max(1, round(first.height * width / first.width))))
                _save_webp(first, Path(thumb))
        finally:
            page.close()
        _prerender(document, pages, request, render_pixels)
    except (Refused, MemoryError):
        raise
    except Exception as exc:
        raise Refused("broken") from exc
    finally:
        document.close()
    answer: dict[str, Any] = {"ok": True, "pages": pages, "phash": phash, "derived": derived}
    if invoice:
        answer["einvoice"] = invoice
    return answer


# --- E-invoices -------------------------------------------------------------------------------------------------------


def _sibling(name: str) -> Any:
    """A module that lies beside this file, loaded by its path (``-I`` puts no folder of the app on the path)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"nexpaper_{name}", Path(__file__).resolve().parent / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _xml_invoice(source: Path, target: Path, language: str) -> dict[str, Any]:
    """The fields of an e-invoice that is XML only, and its readable copy written to ``target``. An XML text that is no
    readable e-invoice is ``broken`` (it never becomes one on a second try)."""
    reader = _sibling("einvoice_reader")
    sheet = _sibling("einvoice_sheet")
    if source.stat().st_size > reader.MAX_XML:
        raise Refused("too_large")
    try:
        found = reader.read_invoice(source.read_bytes())
    except reader.InvoiceRefused as exc:
        raise Refused("too_large" if exc.code == "too_large" else "broken") from exc
    found["format"] = reader.format_name(found)
    kept = reader.summary(found)
    sheet.write(kept, target, language)
    return kept


def _embedded_invoice(source: Path) -> dict[str, Any]:
    """The e-invoice inside a PDF (ZUGFeRD, Factur-X), its XML as base64; nothing when there is none or when it cannot
    be read (the PDF stays a PDF, only without the invoice's data)."""
    import base64

    reader = _sibling("einvoice_reader")
    try:
        embedded = reader.embedded_xml(source)
        if embedded is None:
            return {}
        name, data = embedded
        # In a child process of its own with a short time limit: whatever a hostile XML does to the parser costs only
        # the e-invoice, never the PDF that carried it.
        found = reader.read_within(data)
        if found is None:
            print("e-invoice not read: timeout", file=sys.stderr)
            return {}
    except reader.InvoiceRefused as exc:
        print(f"e-invoice not read: {exc.code}", file=sys.stderr)
        return {}
    except Exception as exc:  # noqa: BLE001 - the PDF is still read; only the invoice in it is not
        print(f"e-invoice not read: {type(exc).__name__}", file=sys.stderr)
        return {}
    found["format"] = reader.format_name(found, name)
    kept = reader.summary(found)
    kept["xml"] = base64.b64encode(data).decode("ascii")
    return kept


def _prerender(document: Any, pages: int, request: dict[str, Any], render_pixels: int) -> None:
    """The small pictures of a short document, drawn now (the server then never has to draw them while somebody waits).
    A page that does not draw is left for later; it fails when it is asked for."""
    pattern = request.get("pages_pattern")
    if not pattern or pages > int(request.get("prerender_pages") or 0):
        return
    width = int(request.get("pages_width") or 720)
    for number in range(pages):
        page = document[number]
        try:
            _save_webp(_drawn(page, width, render_pixels), Path(str(pattern).replace("{page}", str(number + 1))))
        except Exception as exc:  # noqa: BLE001 - left for later, and said on the error stream the server logs
            print(f"page {number + 1} not drawn: {type(exc).__name__}", file=sys.stderr)
        finally:
            page.close()


def render(request: dict[str, Any]) -> dict[str, Any]:
    document = _open_pdf(Path(request["pdf"]))
    try:
        number = int(request["page"])
        if not 0 <= number < len(document):
            raise Refused("broken")
        page = document[number]
        try:
            image = _drawn(page, int(request["width"]), int(request.get("render_pixels") or DEFAULT_RENDER_PIXELS))
            _save_webp(image, Path(request["out"]))
        finally:
            page.close()
    except (Refused, MemoryError):
        raise
    except Exception as exc:
        raise Refused("broken") from exc
    finally:
        document.close()
    return {"ok": True}


def render_pages(request: dict[str, Any]) -> dict[str, Any]:
    with contextlib.suppress(AttributeError, OSError):
        os.nice(10)  # behind the server and behind a document that is being read; not on Windows
    pattern = str(request["pattern"])
    width = int(request["width"])
    render_pixels = int(request.get("render_pixels") or DEFAULT_RENDER_PIXELS)
    document = _open_pdf(Path(request["pdf"]))
    drawn = 0
    try:
        first = max(1, int(request["first"]))
        last = min(int(request["last"]), len(document))
        for number in range(first, last + 1):
            target = Path(pattern.replace("{page}", str(number)))
            if target.is_file():
                continue
            page = document[number - 1]
            try:
                _save_webp(_drawn(page, width, render_pixels), target)
                drawn += 1
            except Exception as exc:  # noqa: BLE001 - left for later: drawn (or refused) when it is asked for
                print(f"page {number} not drawn: {type(exc).__name__}", file=sys.stderr)
            finally:
                page.close()
    finally:
        document.close()
    return {"ok": True, "drawn": drawn}


# --- Text -------------------------------------------------------------------------------------------------------------

#: A page with fewer letters and digits than this has no text of its own worth keeping: a scan that carries a page
#: number, a stamp or a footer ("Seite 1 von 3") as text. It is recognised like a scan (the whole page drawn and read,
#: the little text included).
MIN_PAGE_CHARACTERS = 30
#: The languages the image carries (``Dockerfile``); nothing else is asked for, nothing is loaded at run time.
LANGUAGES = ("deu", "eng", "fra", "nld", "pol", "tur")


def page_texts(path: Path, max_chars: int) -> list[str]:
    """The text of every page of a PDF as PDFium reads it (what the file carries itself, or the layer the recognition
    put in), at most ``max_chars`` characters in all."""
    document = _open_pdf(path)
    texts: list[str] = []
    total = 0
    try:
        for number in range(len(document)):
            if total >= max_chars:
                texts.append("")
                continue
            page = document[number]
            try:
                textpage = page.get_textpage()
                try:
                    value = textpage.get_text_bounded() or ""
                finally:
                    textpage.close()
            finally:
                page.close()
            value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n").replace("\x00", "")
            value = value[: max(0, max_chars - total)]
            total += len(value)
            texts.append(value)
    finally:
        document.close()
    return texts


def _has_text(value: str) -> bool:
    return sum(1 for char in value if char.isalnum()) >= MIN_PAGE_CHARACTERS


def recognize(request: dict[str, Any]) -> dict[str, Any]:
    """The text of a PDF, recognised where the pages carry none or nearly none. ocrmypdf (Tesseract) writes a
    searchable copy to ``out``: the pages with text of their own (``MIN_PAGE_CHARACTERS`` and more) stay as they are,
    the others are drawn and read anew (``pages`` with ``force_ocr``: a footer or a page number as text does not keep a
    scan from being read), get an invisible text layer and are straightened and turned upright when asked. The text of
    every page goes to ``text_out`` (it can be long; the answer stays short): ``{"ok": true, "pages": n, "ocr_pages": k,
    "archive": true|false, "ocr": state}``, the state being ``done``, ``not_needed`` (every page has text),
    ``unavailable`` (no ocrmypdf or Tesseract here) or ``signed``."""
    source = Path(request["pdf"])
    max_chars = int(request.get("max_chars") or 2_000_000)
    before = page_texts(source, max_chars)
    if len(before) > int(request.get("max_pages") or 2000):
        raise Refused("too_many_pages")
    blank = [index for index, value in enumerate(before) if not _has_text(value)]
    outcome: dict[str, Any] = {"ok": True, "pages": len(before), "ocr_pages": 0, "archive": False, "languages": ""}
    texts = before
    if not blank:
        outcome["ocr"] = "not_needed"
    else:
        languages = [lang for lang in request.get("languages") or [] if lang in LANGUAGES] or ["deu", "eng"]
        target = Path(request["out"])
        state = _ocr(source, target, languages, request, blank)
        outcome["ocr"] = state
        if state == "done" and target.is_file():
            texts = page_texts(target, max_chars)
            outcome["archive"] = True
            outcome["ocr_pages"] = sum(1 for index in blank if index < len(texts) and _has_text(texts[index]))
            outcome["languages"] = "+".join(languages)
    Path(request["text_out"]).write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
    return outcome


def _ocr(source: Path, target: Path, languages: list[str], request: dict[str, Any], pages: list[int]) -> str:
    """Runs ocrmypdf: ``done``, or ``unavailable`` when it or Tesseract is not installed (a development machine), or
    ``signed``. Only ``pages`` (counted from 0) are read; the others are copied as they are. Every program it starts
    (Tesseract) runs in this process's group and dies with it at the time limit."""
    try:
        import ocrmypdf
        from ocrmypdf import exceptions as ocr_errors
    except ImportError:
        return "unavailable"
    import logging

    # Its messages would quote the file; the answer and the error stream say enough.
    logging.getLogger("ocrmypdf").setLevel(logging.CRITICAL)
    straighten = bool(request.get("straighten", True))
    partial = _partial(target, ".pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        ocrmypdf.ocr(
            source, partial, language=languages, force_ocr=True, pages=",".join(str(page + 1) for page in pages),
            deskew=straighten, rotate_pages=straighten,
            jobs=int(request.get("jobs") or 1), use_threads=True, output_type="pdf", optimize=0, progress_bar=False,
            tesseract_timeout=float(request.get("page_seconds") or 120),
        )
        os.replace(partial, target)
    except ocr_errors.MissingDependencyError:
        return "unavailable"
    except ocr_errors.EncryptedPdfError as exc:
        raise Refused("encrypted") from exc
    except ocr_errors.InputFileError as exc:
        raise Refused("broken") from exc
    except ocr_errors.DigitalSignatureError:
        # A signed PDF is not rewritten (the signature would break): its own text is all there is.
        return "signed"
    finally:
        with contextlib.suppress(OSError):
            partial.unlink()
    return "done"


# --- Page tools (B5) --------------------------------------------------------------------------------------------------

#: The turns a page may get, in degrees clockwise.
TURNS = (0, 90, 180, 270)


def _open_for_pages(path: Path, max_pages: int) -> Any:
    """A PDF opened with pikepdf to take pages from. A file that needs a password, or that pikepdf cannot read, is
    refused like the reader refuses it."""
    import pikepdf

    try:
        pdf = pikepdf.open(str(path))
    except pikepdf.PasswordError as exc:
        raise Refused("encrypted") from exc
    except MemoryError:
        raise
    except Exception as exc:
        raise Refused("broken") from exc
    if len(pdf.pages) > max_pages:
        pdf.close()
        raise Refused("too_many_pages")
    return pdf


def _draw_made(path: Path, output: dict[str, Any], render_pixels: int) -> dict[str, Any]:
    """The pictures of a PDF that was just made: its preview, its small pages (a short one) and its fingerprint."""
    document = _open_pdf(path)
    try:
        pages = len(document)
        page = document[0]
        try:
            first = _drawn(page, HASH_SOURCE_WIDTH, render_pixels)
            phash = fingerprint(first)
            thumb = output.get("thumb_out")
            if thumb:
                width = int(output.get("thumb_width") or 360)
                if first.width > width:
                    first = first.resize((width, max(1, round(first.height * width / first.width))))
                _save_webp(first, Path(thumb))
        finally:
            page.close()
        _prerender(document, pages, output, render_pixels)
    finally:
        document.close()
    return {"pages": pages, "phash": phash}


#: The actions a link may keep: going to a web address or to a place in the document.
SAFE_ACTIONS = ("/URI", "/GoTo")


def _safe_action(action: Any) -> bool:
    try:
        kind = str(action.get("/S"))
        if kind not in SAFE_ACTIONS or "/Next" in action:
            return False
        if kind == "/URI":
            address = str(action.get("/URI", "")).strip().lower()
            return address.startswith(("http://", "https://", "mailto:"))
        return True
    except Exception:  # noqa: BLE001 - an action that cannot be read is no safe one
        return False


#: How far up the chain of parents of a form field the actions are looked for. A real form is a few levels deep.
PARENT_DEPTH = 64


def _quiet_parents(annot: Any) -> None:
    """The actions of the fields above a widget go too (``/AA`` and ``/A`` on every parent, up the chain): the
    widget inherits from its parents, and a script on a parent would stay in the file as long as one widget points to
    it. A chain that loops, or is deeper than ``PARENT_DEPTH``, is cut where it stops being believable."""
    import pikepdf

    seen: set[tuple[int, int]] = set()
    current = annot.get("/Parent")
    for _ in range(PARENT_DEPTH):
        if not isinstance(current, pikepdf.Dictionary):
            return
        if current.is_indirect:
            if current.objgen in seen:
                return
            seen.add(current.objgen)
        for key in ("/AA", "/A"):
            if key in current:
                del current[key]
        current = current.get("/Parent")


def _quiet(page: Any) -> None:
    """What a page could do when it is opened or clicked goes; what it shows stays. Removed: the actions of the page
    (``/AA``), files attached as annotations, every action of a form field and of the fields above it, and every link
    action other than a web or mail address or a place in the document (JavaScript, Launch, submitting a form,
    importing data, chains of actions). A form field is cut loose from its parents and from the page it was on
    (``/Parent`` and ``/P``): the form itself is not taken along, a parent would bring along every other widget of the
    field with the pages they sit on, and its look comes from the field's own appearance. Kept: the page's content,
    links to web addresses and places, notes, highlights, the look of form fields (which can no longer be filled)."""
    import pikepdf

    obj = page.obj
    if "/AA" in obj:
        del obj["/AA"]
    annots = obj.get("/Annots")
    if annots is None or not isinstance(annots, pikepdf.Array):
        return
    kept = pikepdf.Array()
    for annot in annots:
        if not isinstance(annot, pikepdf.Dictionary):
            continue
        if str(annot.get("/Subtype")) == "/FileAttachment":
            continue
        if "/AA" in annot:
            del annot["/AA"]
        _quiet_parents(annot)
        if str(annot.get("/Subtype")) == "/Widget" and "/Parent" in annot:
            del annot["/Parent"]
        if "/P" in annot:
            del annot["/P"]
        action = annot.get("/A")
        if action is not None and (str(annot.get("/Subtype")) == "/Widget" or not _safe_action(action)):
            del annot["/A"]
        kept.append(annot)
    obj["/Annots"] = kept


def assemble(request: dict[str, Any]) -> dict[str, Any]:
    """New PDFs from pages of others. ``sources``: the PDFs pages are taken from; ``outputs``: for each new PDF where it
    goes (``out``) and its pages as ``[source, page counted from 0, turn]``, in the order they will have, and where its
    pictures go. A page keeps what it shows (the invisible text of the recognition too), a turn is added to the one it
    has; what a page could do by itself goes (``_quiet``). Every new PDF is written whole to a temporary name and put in
    place; nothing of the sources changes. Answer: ``{"ok": true, "outputs": [{"pages": n, "phash": "..."}]}``."""
    import pikepdf

    max_pages = int(request.get("max_pages") or 2000)
    render_pixels = int(request.get("render_pixels") or DEFAULT_RENDER_PIXELS)
    sources = [_open_for_pages(Path(path), max_pages) for path in request["sources"]]
    made: list[Path] = []
    results: list[dict[str, Any]] = []
    try:
        for output in request["outputs"]:
            wanted = output["pages"]
            if not 1 <= len(wanted) <= max_pages:
                raise Refused("too_many_pages")
            target = Path(output["out"])
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = _partial(target)
            new = pikepdf.new()
            try:
                for source, index, turn in wanted:
                    pdf = sources[int(source)]
                    if not 0 <= int(index) < len(pdf.pages) or int(turn) not in TURNS:
                        raise Refused("broken")
                    new.pages.append(pdf.pages[int(index)])
                    if int(turn):
                        new.pages[-1].rotate(int(turn), relative=True)
                    _quiet(new.pages[-1])
                new.save(str(partial))
            except BaseException as exc:
                with contextlib.suppress(OSError):
                    partial.unlink()
                if isinstance(exc, Refused | MemoryError) or not isinstance(exc, Exception):
                    raise
                raise Refused("broken") from exc
            finally:
                new.close()
            os.replace(partial, target)
            made.append(target)
            results.append(_draw_made(target, output, render_pixels))
    except BaseException:
        for path in made:
            with contextlib.suppress(OSError):
                path.unlink()
        raise
    finally:
        for pdf in sources:
            pdf.close()
    return {"ok": True, "outputs": results}


#: The width a page is drawn at to measure its ink: about 72 dots per inch for a sheet of A4, enough for a page number
#: of 8 points.
BLANK_WIDTH = 600
#: A dot is ink when it is this much darker than the paper (the median of the page): the grain of the paper and the
#: noise of the scanner are lighter than that. 60 finds writing down to grey 170 on white (a pale receipt, pencil);
#: strong show-through of the other side counts as ink then (a separator missed, never a page lost). Measured in
#: ``services/separators.py``.
INK_STEP = 60
#: The edge of the sheet that is not looked at (each side, a share of its width or height): the shadow of the edge.
EDGE = 0.015
#: A run of ink from the edge longer than this share of the row or column is on the sheet (a bar across the page, a
#: ruled line), not the scanner: the wedge beside a sheet slanted by 4 degrees is about 7 % of the width.
EDGE_RUN = 0.1


def _clear_from_the_edges(mask: bytearray, width: int, height: int) -> None:
    """Ink that reaches the edge of the picture in one short run is the scanner, not the sheet: the dark wedges beside a
    sheet that went in at a slant, a black lid, the shadow of the edge. Cleared along every row and every column from
    both ends until the first dot of paper, when the run is at most ``EDGE_RUN`` of its length; a longer run (a bar
    printed across the page, the lines of ruled paper) stays ink. The runs are found first and cleared afterwards, so
    that clearing the rows does not shorten the runs of the columns."""
    across, down = int(width * EDGE_RUN), int(height * EDGE_RUN)
    clear: list[tuple[int, int, int]] = []  # (start, step, count) in the flat mask
    for y in range(height):
        row = y * width
        x = 0
        while x < width and mask[row + x]:
            x += 1
        if 0 < x <= across:
            clear.append((row, 1, x))
        end = width - 1
        while end >= 0 and mask[row + end]:
            end -= 1
        if 0 < width - 1 - end <= across:
            clear.append((row + end + 1, 1, width - 1 - end))
    for x in range(width):
        y = 0
        while y < height and mask[y * width + x]:
            y += 1
        if 0 < y <= down:
            clear.append((x, width, y))
        end = height - 1
        while end >= 0 and mask[end * width + x]:
            end -= 1
        if 0 < height - 1 - end <= down:
            clear.append(((end + 1) * width + x, width, height - 1 - end))
    for start, step, count in clear:
        for k in range(count):
            mask[start + k * step] = 0


def ink_ppm(image: Any) -> int:
    """How much of a page is ink, in parts per million of its area, leaving out what is no writing on the sheet: the
    edges (``EDGE``) and what reaches them (``_clear_from_the_edges``), and dots that stand alone (a dot of ink counts
    only when at least two of its eight neighbours are ink too: a stroke of a letter has them, the grain of a scan and
    a speck of dust do not). An empty sheet comes to almost nothing, a page number to a few dozen."""
    from PIL import Image, ImageChops, ImageFilter

    grey = image.convert("L")
    width, height = grey.size
    histogram = grey.histogram()
    half, seen, paper = width * height / 2, 0, 255
    for level, count in enumerate(histogram):
        seen += count
        if seen >= half:
            paper = level
            break
    limit = paper - INK_STEP
    if limit <= 0:
        return 1_000_000  # a dark page: no empty sheet
    mask = grey.point(lambda value: 1 if value < limit else 0)
    raw = bytearray(mask.tobytes())
    _clear_from_the_edges(raw, width, height)
    mask = Image.frombytes("L", (width, height), bytes(raw))
    neighbours = mask.filter(ImageFilter.Kernel((3, 3), [1, 1, 1, 1, 0, 1, 1, 1, 1], scale=1))
    kept = ImageChops.darker(mask, neighbours.point(lambda value: 1 if value >= 2 else 0))
    left, top = round(width * EDGE), round(height * EDGE)
    inner = kept.crop((left, top, width - left, height - top))
    ink = inner.histogram()[1]
    area = max(1, inner.width * inner.height)
    return round(ink * 1_000_000 / area)


def blanks(request: dict[str, Any]) -> dict[str, Any]:
    """The ink of every page of a PDF (``ink_ppm``), to find the empty sheets between letters of a batch scan. The
    server decides what counts as empty. Answer: ``{"ok": true, "ink": [ppm, ...]}``."""
    max_pages = int(request.get("max_pages") or 2000)
    render_pixels = int(request.get("render_pixels") or DEFAULT_RENDER_PIXELS)
    width = int(request.get("width") or BLANK_WIDTH)
    document = _open_pdf(Path(request["pdf"]))
    try:
        if len(document) > max_pages:
            raise Refused("too_many_pages")
        ink: list[int] = []
        for number in range(len(document)):
            page = document[number]
            try:
                ink.append(ink_ppm(_drawn(page, width, render_pixels)))
            finally:
                page.close()
    except (Refused, MemoryError):
        raise
    except Exception as exc:
        raise Refused("broken") from exc
    finally:
        document.close()
    return {"ok": True, "ink": ink}


def main() -> int:
    real_out = sys.stdout
    sys.stdout = sys.stderr  # a library that prints must not break the answer
    try:
        request = json.loads(sys.stdin.read(65536))
        _stop_with_the_parent()
        # Tesseract uses one thread, and the allocator keeps few arenas: one document must not flood the machine, and
        # a memory limit counts what is reserved, not only what is used.
        os.environ["OMP_THREAD_LIMIT"] = "1"
        os.environ.setdefault("MALLOC_ARENA_MAX", "2")
        _limit_memory(int(request.get("memory_mb") or 0))
        op = request.get("op")
        operations = {"process": process, "render": render, "render_pages": render_pages, "recognize": recognize,
                      "assemble": assemble, "blanks": blanks}
        result = operations[op](request) if op in operations else {"ok": False, "error": "failed"}
    except Refused as exc:
        result = {"ok": False, "error": exc.code, "retry": False}
    except MemoryError:
        result = {"ok": False, "error": "too_large", "retry": False}
    except Exception as exc:  # noqa: BLE001 - never a traceback with paths in the answer
        print(f"worker failed: {type(exc).__name__}", file=sys.stderr)
        result = {"ok": False, "error": "failed", "retry": True}
    real_out.write("\n" + json.dumps(result) + "\n")
    real_out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
