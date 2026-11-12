"""The mail worker: takes one mail apart in a process of its own and reports what it found.

Run as ``python -I app/mail_worker.py`` by ``services/intake_mail.py``, one process for one mail. Taking a mail apart
can cost far more than its size (a header of quotes, a file name of ten thousand encoded words, thousands of
parameters): the server gives this process a time limit (it is killed when it is reached) and, where the system
allows it, a memory limit. It has no database, no settings and no secret, only the path of the mail, a folder for the
parts and the limits. Nothing from ``app`` is imported: this file stands alone (the standard library).

Input: one JSON object on standard input. Output: one JSON object on the last line of standard output:
``{"ok": true, "sender", "recipients", "subject", "message_id", "auth", "parts": [{"name", "path", "size"}], "over"}``
or ``{"ok": false, "error": code}``.

With ``"op": "text"`` (asked only for a mail that brought nothing to take, belongs to a person for sure and when the
operator switched it on) it reads the text of the mail instead and sets it as a PDF (``mail_sheet.py``):
``{"ok": true, "empty": false, "pdf", "texts", "pages", "cut", "html", "subject", "date"}`` (the text of the pages is
written to the file ``texts`` names). Plain text is taken as it is; HTML is made text here with ``html.parser``, which
only reads the markup: nothing is drawn, nothing is fetched (no picture, font or style sheet, no ``cid:``), no script
runs.
"""

from __future__ import annotations

import codecs
import contextlib
import email
import email.header
import email.policy
import email.utils
import html.parser
import importlib.util
import json
import os
import re
import sys
import threading
import time
from email.message import Message
from pathlib import Path
from typing import Any

RECIPIENT_HEADERS = ("To", "Cc", "Delivered-To", "X-Original-To", "Envelope-To", "X-Envelope-To", "X-Forwarded-To")
#: Addresses read from one mail at most, and the ``Authentication-Results`` headers handed back.
MAX_ADDRESSES = 100
MAX_AUTH = 5
AUTH_CHARS = 2000


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


def _be_modest(cpu_seconds: int) -> None:
    """The lowest priority, and at most ``cpu_seconds`` of computing (where the system has ``setrlimit``): a stream of
    mails that each take long does not hold a core away from the server."""
    with contextlib.suppress(AttributeError, OSError):
        os.nice(19)
    if cpu_seconds <= 0:
        return
    try:
        import resource
    except ImportError:  # Windows has neither
        return
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))


def _stop_with_the_parent() -> None:
    parent = os.getppid()

    def watch() -> None:
        while True:
            time.sleep(2)
            if os.getppid() != parent:
                os._exit(3)

    threading.Thread(target=watch, daemon=True).start()


def clean(text: str, limit: int) -> str:
    return " ".join("".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in text).split())[:limit]


def header(message: Message, name: str) -> str:
    try:
        value = message.get(name)
    except Exception:  # noqa: BLE001 - a broken header is no header
        return ""
    return "" if value is None else str(value)


def addresses(message: Message, names: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for name in names:
        try:
            values = message.get_all(name) or []
        except Exception:  # noqa: BLE001, S112 - a header that cannot be read names nobody
            continue
        try:
            pairs = email.utils.getaddresses([str(value) for value in values])
        except Exception:  # noqa: BLE001, S112
            continue
        found.extend(address.strip() for _name, address in pairs if "@" in address)
        if len(found) >= MAX_ADDRESSES:
            break
    return found[:MAX_ADDRESSES]


def filename(part: Message) -> str:
    name: str | None
    try:
        name = part.get_filename()
    except Exception:  # noqa: BLE001
        name = None
    if not name:
        try:
            raw = part.get_param("name")
            name = email.utils.collapse_rfc2231_value(raw) if raw else None  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            name = None
    if name and "=?" in name:
        with contextlib.suppress(Exception):
            name = str(email.header.make_header(email.header.decode_header(name)))
    if not name:
        return ""
    return clean(str(name).replace("\\", "/").rsplit("/", 1)[-1], 200)


def wanted(part: Message, ctype: str, inline_min: int) -> int | None:
    """Whether a leaf may be a document: None when not, else the smallest size it must have."""
    try:
        disposition = part.get_content_disposition()
    except Exception:  # noqa: BLE001
        disposition = None
    if disposition == "attachment":
        return 0
    if ctype.startswith("text/") and ctype != "text/xml":
        return None
    if ctype.startswith("image/") and header(part, "Content-ID"):
        # A logo in a signature, unless it is large.
        return inline_min
    if filename(part) or ctype in ("application/pdf", "application/xml", "text/xml", "image/jpeg", "image/png",
                                   "image/tiff", "image/heic", "image/webp", "image/avif"):
        return 0
    return None


def leaves(message: Message, nesting: int, parts_limit: int, inline_min: int) -> list[tuple[str, bytes]]:
    """The parts of a mail that may be documents, in the order they stand (forwarded mails looked into, at most
    ``nesting`` deep, ``parts_limit`` parts looked at); broken parts are passed over."""
    found: list[tuple[str, bytes]] = []
    budget = [parts_limit]

    def visit(part: Message, depth: int) -> None:
        if budget[0] <= 0 or depth > nesting:
            return
        budget[0] -= 1
        try:
            ctype = part.get_content_type()
        except Exception:  # noqa: BLE001
            return
        if part.is_multipart():
            try:
                children = part.get_payload()
            except Exception:  # noqa: BLE001
                return
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, Message):
                        visit(child, depth + 1)
            return
        if ctype == "message/rfc822":
            with contextlib.suppress(Exception):
                inner = part.get_payload(decode=True)
                if isinstance(inner, bytes) and inner:
                    visit(email.message_from_bytes(inner, policy=email.policy.default), depth + 1)
            return
        least = wanted(part, ctype, inline_min)
        if least is None:
            return
        try:
            data = part.get_payload(decode=True)
        except Exception:  # noqa: BLE001
            return
        if not isinstance(data, bytes) or not data or len(data) < least:
            return
        found.append((filename(part), data))

    try:
        visit(message, 0)
    except RecursionError:
        pass
    return found


def take_apart(request: dict[str, Any]) -> dict[str, Any]:
    raw = Path(request["source"]).read_bytes()
    out = Path(request["out"])
    message = email.message_from_bytes(raw, policy=email.policy.default)
    del raw
    froms = addresses(message, ("From",))
    auth: list[str] = []
    with contextlib.suppress(Exception):
        auth = [str(value)[:AUTH_CHARS] for value in (message.get_all("Authentication-Results") or [])[:MAX_AUTH]]
    parts = leaves(message, int(request["nesting"]), int(request["parts_limit"]), int(request["inline_min"]))
    taken: list[dict[str, Any]] = []
    over = 0
    for number, (name, data) in enumerate(parts):
        if number >= int(request["max_parts"]) or len(data) > int(request["max_bytes"]):
            over += 1
            continue
        path = out / f"part-{number}"
        path.write_bytes(data)
        taken.append({"number": number, "name": name, "path": str(path), "size": len(data)})
    return {
        "ok": True, "sender": froms[0] if froms else "", "recipients": addresses(message, RECIPIENT_HEADERS),
        "subject": clean(header(message, "Subject"), 200), "message_id": header(message, "Message-ID").strip()[:1000],
        "auth": auth, "parts": taken, "over": over,
    }


# --- The text of a mail ----------------------------------------------------------------------------------------------

#: The text a document is made of, at most (UTF-8 bytes); more is cut and the document says so.
TEXT_MAX = 200 * 1024
#: The bytes of one text part that are read at most (HTML may be many times the text it carries).
SOURCE_MAX = 4 * 1024 * 1024
#: Less than this many letters, digits and signs is no text worth a document (pictures only, a short signature).
TEXT_MIN = 20
#: How long a link's address may be to be written after it.
LINK_MAX = 500
#: The head fields as they are shown.
FROM_MAX, TO_MAX, SUBJECT_MAX = 300, 400, 200
_CHARSET = re.compile(r"^[A-Za-z0-9_.:+-]{1,40}$")
#: Characters that change the direction of text or hide themselves: a subject could show another text than it holds.
INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068"
                                   "\u2069\u061c\ufeff"), None)


def _control(char: str) -> bool:
    code = ord(char)
    return code < 32 or 127 <= code < 160


def plain(value: str, limit: int) -> str:
    """A head field as it may be shown: on one line, no control or direction characters, at most ``limit``."""
    text = "".join(" " if _control(char) else char for char in value.translate(INVISIBLE))
    return " ".join(text.split())[:limit]


def tidy(text: str) -> str:
    """The text of a mail made plain: lines ended by ``\\n``, tabs as spaces, no control or direction characters, at
    most one empty line between paragraphs, no empty lines at the start or the end."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ").replace("\f", "\n").replace("\v", "\n")
    text = "".join(char for char in text.translate(INVISIBLE) if char == "\n" or not _control(char))
    lines: list[str] = []
    for line in text.split("\n"):
        line = line.rstrip()
        if not line and (not lines or not lines[-1]):
            continue
        lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def decoded(part: Message) -> str:
    """The text of a part in its own character set; one that is unknown, wrong or not one for text gives way to UTF-8,
    then to Latin-1 (which reads every byte). Never more than ``SOURCE_MAX`` bytes."""
    try:
        data = part.get_payload(decode=True)
    except Exception:  # noqa: BLE001 - a part that cannot be decoded has no text
        return ""
    if not isinstance(data, bytes):
        return ""
    data = data[:SOURCE_MAX]
    try:
        declared = part.get_content_charset() or "us-ascii"
    except Exception:  # noqa: BLE001
        declared = "us-ascii"
    names: list[str] = []
    for name in (declared, "utf-8", "cp1252"):
        if not _CHARSET.match(name):
            continue
        try:
            info = codecs.lookup(name)
        except LookupError:
            continue
        if getattr(info, "_is_text_encoding", True) and info.name not in names:
            names.append(info.name)
    for name in names:
        try:
            return data.decode(name)
        except Exception:  # noqa: BLE001, S112 - the next one is tried
            continue
    return data.decode(names[0], "replace") if names else data.decode("latin-1")


class _Enough(Exception):
    """As much text as a document may hold was found: the rest of the HTML is not read."""


class HtmlText(html.parser.HTMLParser):
    """The text of an HTML mail, read from its markup only: blocks and line breaks become new lines, a link becomes its
    text and, when that is not its address already, the address in brackets. Script, style, title and the like are
    left out, and so is every picture (its address, also ``cid:``, is never looked at). Nothing is loaded, nothing
    runs: ``html.parser`` only cuts the text into tags and words."""

    SKIP = frozenset({"script", "style", "title", "template", "svg", "math", "noscript", "object", "select",
                      "textarea"})
    BLOCK = frozenset({"p", "div", "tr", "ul", "ol", "dl", "dt", "dd", "table", "blockquote", "pre", "section",
                       "article", "header", "footer", "address", "form", "fieldset", "center", "h1", "h2", "h3", "h4",
                       "h5", "h6", "hr", "body", "main", "nav", "aside", "figure", "figcaption", "caption"})
    VOID = frozenset({"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source", "track",
                      "wbr", "param"})

    def __init__(self, limit: int) -> None:
        super().__init__(convert_charrefs=True)
        self.limit = limit
        self.size = 0
        self.out: list[str] = []
        self.skip = 0
        self.pre = 0
        self.link: tuple[str, int] | None = None

    def put(self, text: str) -> None:
        self.out.append(text)
        self.size += len(text)
        if self.size > self.limit:
            raise _Enough

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self.skip += 1
            return
        if tag == "body":
            # A "title" or "noscript" left open in the head must not swallow the mail.
            self.skip = 0
        if self.skip:
            return
        if tag == "br":
            self.put("\n")
        elif tag == "li":
            self.put("\n- ")
        elif tag in ("td", "th"):
            self.put("  ")
        elif tag == "pre":
            self.pre += 1
            self.put("\n")
        elif tag in self.BLOCK:
            self.put("\n")
        elif tag == "a":
            href = next((value or "" for name, value in attrs if name == "href"), "")
            href = plain(href, LINK_MAX + 1)
            wanted = href.lower().startswith(("http://", "https://", "mailto:")) and len(href) <= LINK_MAX
            self.link = (href, len(self.out)) if wanted else None

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.VOID or tag not in self.SKIP:
            self.handle_starttag(tag, attrs)
            if tag not in self.VOID:
                self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "pre":
            self.pre = max(0, self.pre - 1)
            self.put("\n")
        elif tag in self.BLOCK:
            self.put("\n")
        elif tag == "a" and self.link is not None:
            href, start = self.link
            self.link = None
            shown = "".join(self.out[start:])
            address = href[7:] if href.lower().startswith("mailto:") else href
            if address and address not in shown:
                self.put(f" ({address})")

    def handle_data(self, data: str) -> None:
        if self.skip or not data:
            return
        if self.pre:
            self.put(data)
            return
        words = " ".join(data.split())
        lead = " " if data[:1].isspace() else ""
        tail = " " if data[-1:].isspace() and words else ""
        self.put(lead + words + tail)

    def text(self) -> str:
        lines = "".join(self.out).replace(" ", " ").split("\n")
        return "\n".join(" ".join(line.split()) for line in lines)


def html_text(source: str, limit: int) -> str:
    reader = HtmlText(limit)
    try:
        reader.feed(source)
        reader.close()
    except _Enough:
        pass
    return reader.text()


def _disposition(part: Message) -> str | None:
    try:
        return part.get_content_disposition()
    except Exception:  # noqa: BLE001
        return None


def _inner(part: Message) -> Message | None:
    """The mail inside a ``message/rfc822`` part: parsed already (the usual case), else from its bytes."""
    payload = part.get_payload()
    if isinstance(payload, list):
        return payload[0] if payload and isinstance(payload[0], Message) else None
    data = part.get_payload(decode=True)
    if isinstance(data, bytes) and data:
        return email.message_from_bytes(data, policy=email.policy.default)
    return None


def body_text(message: Message, nesting: int, parts_limit: int, limit: int, words: dict[str, str]) -> tuple[str, bool]:
    """The text of a mail as people read it: of each ``multipart/alternative`` the plain text, else the HTML; the text
    parts that are not attachments in the order they stand; a forwarded mail (``message/rfc822``) with a short head of
    its own, its text after it (forwarding is how documents come, its text is the content). Whether HTML was read."""
    pieces: list[str] = []
    budget = [parts_limit]
    size = [0]
    from_html = [False]

    def add(text: str) -> None:
        if size[0] <= limit:
            pieces.append(text)
            size[0] += len(text)

    def visit(part: Message, depth: int) -> None:
        if budget[0] <= 0 or depth > nesting or size[0] > limit:
            return
        budget[0] -= 1
        try:
            ctype = part.get_content_type()
        except Exception:  # noqa: BLE001
            return
        if ctype == "message/rfc822":
            with contextlib.suppress(Exception):
                forwarded = _inner(part)
                if forwarded is not None:
                    head = [f"{words['forwarded']}:"]
                    for key, name in (("from", "From"), ("to", "To"), ("subject", "Subject"), ("date", "Date")):
                        value = plain(header(forwarded, name), SUBJECT_MAX)
                        if value:
                            head.append(f"{words[key]}: {value}")
                    add("\n\n" + "\n".join(head) + "\n\n")
                    visit(forwarded, depth + 1)
            return
        if part.is_multipart():
            try:
                children = [child for child in (part.get_payload() or []) if isinstance(child, Message)]
            except Exception:  # noqa: BLE001
                return
            if ctype == "multipart/alternative":
                texts = [c for c in children
                         if c.get_content_type() == "text/plain" and _disposition(c) != "attachment"]
                others = [c for c in children if c.get_content_type() != "text/plain"]
                chosen = texts[:1] or [c for c in others if c.get_content_type() == "text/html"][:1] or others[:1]
                children = chosen
            for child in children:
                visit(child, depth + 1)
            return
        if _disposition(part) == "attachment":
            return
        if ctype == "text/plain":
            add("\n" + decoded(part) + "\n")
        elif ctype == "text/html":
            from_html[0] = True
            add("\n" + html_text(decoded(part), limit + 1) + "\n")

    try:
        visit(message, 0)
    except RecursionError:
        pass
    return "".join(pieces), from_html[0]


def cut_to(text: str, limit: int) -> tuple[str, bool]:
    """At most ``limit`` bytes of UTF-8, cut at a whole character (and at the end of a line, when one is near)."""
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text, False
    shorter = data[:limit].decode("utf-8", "ignore")
    line_end = shorter.rfind("\n")
    if line_end > len(shorter) - 2000:
        shorter = shorter[:line_end]
    return shorter.rstrip(), True


def _sibling(name: str) -> Any:
    """A module beside this file, loaded by its path (``-I`` puts no folder of the app on the path)."""
    spec = importlib.util.spec_from_file_location(f"nexpaper_{name}", Path(__file__).resolve().parent / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mail_date(message: Message) -> tuple[str, str]:
    """The date of the mail: as a day (``YYYY-MM-DD``, empty when there is none that makes sense) and as shown."""
    raw = header(message, "Date")
    try:
        when = email.utils.parsedate_to_datetime(raw) if raw else None
    except Exception:  # noqa: BLE001 - a date that cannot be read is no date
        when = None
    if when is None or not 1970 <= when.year <= 2100:
        return "", ""
    offset = when.strftime("%z")
    shown = when.strftime("%Y-%m-%d %H:%M") + (f" {offset[:3]}:{offset[3:]}" if offset else "")
    return when.date().isoformat(), shown


def read_text(request: dict[str, Any]) -> dict[str, Any]:
    raw = Path(request["source"]).read_bytes()
    out = Path(request["out"])
    message = email.message_from_bytes(raw, policy=email.policy.default)
    del raw
    language = "en" if str(request.get("language") or "") == "en" else "de"
    mail_sheet = _sibling("mail_sheet")
    words = mail_sheet.words_of(language)
    limit = int(request.get("text_max") or TEXT_MAX)
    body, from_html = body_text(message, int(request["nesting"]), int(request["parts_limit"]), limit * 2, words)
    body = tidy(body)
    if sum(1 for char in body if not char.isspace()) < TEXT_MIN:
        return {"ok": True, "empty": True}
    body, cut = cut_to(body, limit)
    day, shown = mail_date(message)
    subject = plain(header(message, "Subject"), SUBJECT_MAX)
    head = {"from": plain(header(message, "From"), FROM_MAX), "to": plain(header(message, "To"), TO_MAX),
            "subject": subject, "date": shown}
    pdf = out / "mail.pdf"
    made = mail_sheet.write(head, body, pdf, language, cut)
    texts = out / "texts.json"
    texts.write_text(json.dumps(made["texts"], ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "empty": False, "pdf": str(pdf), "texts": str(texts), "pages": made["pages"],
            "cut": made["cut"], "html": from_html, "subject": subject, "day": day}


def main() -> int:
    real_out = sys.stdout
    sys.stdout = sys.stderr
    try:
        request = json.loads(sys.stdin.read(65536))
        _stop_with_the_parent()
        _limit_memory(int(request.get("memory_mb") or 0))
        _be_modest(int(request.get("cpu_seconds") or 0))
        result = read_text(request) if request.get("op") == "text" else take_apart(request)
    except MemoryError:
        result = {"ok": False, "error": "too_elaborate"}
    except Exception as exc:  # noqa: BLE001 - never a traceback with paths in the answer
        print(f"mail worker failed: {type(exc).__name__}", file=sys.stderr)
        result = {"ok": False, "error": "unreadable"}
    real_out.write("\n" + json.dumps(result) + "\n")
    real_out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
