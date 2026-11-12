"""The readable copy of a mail's text: a plain A4 PDF with a head (from, to, subject, date) and the text below it.

Set **in the mail worker's process** (``app/mail_worker.py`` loads this file by its path), like the reading of the mail:
everything that is set came from outside. It takes the fonts, the widths and the writing of the PDF from the readable
copy of e-invoices (``einvoice_sheet.py``, loaded by its path as well): the two standard fonts every PDF reader has, no
library, no font file. A character those fonts do not have becomes ``?`` in the PDF; the text of the document (what is
searched) keeps it.

``write`` answers the pages and, for every page, the lines of the text that begin on it: that is the text the document
keeps, so what is searched is exactly what is shown, line for line.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _sibling(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"nexpaper_{name}", Path(__file__).resolve().parent / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sheet = _sibling("einvoice_sheet")

#: More pages than this are not set; the text stops there and the last line says so.
MAX_PAGES = 200
#: A word longer than this is broken before the lines are made (a link, a line of dashes): breaking one by width is
#: slow for a very long one.
WORD = 60
BODY_SIZE = 10
BODY_LEAD = 13
HEAD_SIZE = 10
HEAD_LEAD = 14
LABEL_ROOM = 70
#: Lines of one head field at most (a long list of recipients).
HEAD_ROWS = 4

LABELS = {
    "de": {
        "from": "Von", "to": "An", "subject": "Betreff", "date": "Datum", "no_subject": "Mail ohne Betreff",
        "forwarded": "Weitergeleitete Mail",
        "cut": "Der Text der Mail war länger und ist hier gekürzt.",
        "footer": "Text einer Mail, von nexpaper als PDF gesetzt.", "page": "Seite {n} von {of}",
    },
    "en": {
        "from": "From", "to": "To", "subject": "Subject", "date": "Date", "no_subject": "Mail without a subject",
        "forwarded": "Forwarded mail",
        "cut": "The text of the mail was longer and is cut here.",
        "footer": "The text of a mail, set as a PDF by nexpaper.", "page": "Page {n} of {of}",
    },
}


def words_of(language: str) -> dict[str, str]:
    return LABELS.get(language, LABELS["en"])


def _short_words(line: str) -> str:
    return " ".join(word if len(word) <= WORD else " ".join(word[i:i + WORD] for i in range(0, len(word), WORD))
                    for word in line.split())


def head_lines(head: dict[str, str], language: str) -> list[str]:
    """The head as lines of text, as the document keeps it (and as it stands on the first page)."""
    words = words_of(language)
    return [f"{words[key]}: {head[key]}" for key in ("from", "to", "subject", "date") if head.get(key)]


def write(head: dict[str, str], body: str, target: Path, language: str = "de", cut: bool = False) -> dict[str, Any]:
    """The PDF of a mail's text at ``target``. ``head``: ``from``, ``to``, ``subject``, ``date`` as they are shown (made
    plain by the caller). ``cut``: the text was cut before it came here; the last line says so. Answer: ``pages``,
    ``texts`` (the text of every page) and ``cut`` (also when the pages ran out)."""
    words = words_of(language)
    pages = sheet._Pages()
    texts: list[list[str]] = [[]]
    title = head.get("subject") or words["no_subject"]
    for line in sheet.wrap(_short_words(title), sheet.RIGHT - sheet.LEFT, 15, True)[:3]:
        pages.text(sheet.LEFT, pages.y, line, 15, True)
        pages.y -= 20
    pages.y -= 6
    for key in ("from", "to", "subject", "date"):
        value = head.get(key) or ""
        if not value:
            continue
        rows = sheet.wrap(_short_words(value), sheet.RIGHT - sheet.LEFT - LABEL_ROOM, HEAD_SIZE)
        if len(rows) > HEAD_ROWS:
            rows = [*rows[:HEAD_ROWS - 1], rows[HEAD_ROWS - 1] + " ..."]
        pages.text(sheet.LEFT, pages.y, words[key], HEAD_SIZE, True)
        for row in rows:
            pages.text(sheet.LEFT + LABEL_ROOM, pages.y, row, HEAD_SIZE)
            pages.y -= HEAD_LEAD
    texts[0].extend(head_lines(head, language))
    texts[0].append("")
    pages.y -= 4
    pages.rule(pages.y)
    pages.y -= 18
    room = sheet.RIGHT - sheet.LEFT
    stopped = False
    for line in body.split("\n"):
        if not line.strip():
            if pages.y - BODY_LEAD // 2 >= sheet.BOTTOM:
                pages.y -= BODY_LEAD // 2
            texts[-1].append(line)
            continue
        rows = sheet.wrap(_short_words(line), room, BODY_SIZE)
        started = False
        for row in rows:
            # One line is kept free on the last page that may be added, for the line that says the text is cut.
            spare = BODY_LEAD + 6 if len(pages.pages) >= MAX_PAGES else 0
            if pages.y - spare < sheet.BOTTOM:
                if len(pages.pages) >= MAX_PAGES:
                    stopped = True
                    break
                pages.pages.append([])
                texts.append([])
                pages.y = sheet.TOP
            if not started:
                texts[-1].append(line)
                started = True
            pages.text(sheet.LEFT, pages.y, row, BODY_SIZE)
            pages.y -= BODY_LEAD
        if stopped:
            break
    if stopped or cut:
        if pages.y - BODY_LEAD < sheet.BOTTOM and len(pages.pages) < MAX_PAGES:
            pages.pages.append([])
            texts.append([])
            pages.y = sheet.TOP
        pages.y -= 6
        pages.text(sheet.LEFT, pages.y, words["cut"], BODY_SIZE, True)
        texts[-1].extend(["", words["cut"]])
    count = len(pages.pages)
    for number, page in enumerate(pages.pages, start=1):
        page.append(b"BT /F1 8 Tf 0.4 g %d %d Td (" % (sheet.LEFT, sheet.BOTTOM - 30) + sheet._escape(words["footer"])
                    + b") Tj ET")
        label = words["page"].format(n=number, of=count)
        page.append(b"BT /F1 8 Tf 0.4 g %.2f %d Td (" % (sheet.RIGHT - sheet.width(label, 8), sheet.BOTTOM - 30)
                    + sheet._escape(label) + b") Tj ET")
    sheet._save(pages.pages, target)
    return {"pages": count, "texts": ["\n".join(lines).strip("\n") for lines in texts], "cut": stopped or cut}


__all__ = ["LABELS", "MAX_PAGES", "head_lines", "words_of", "write"]
