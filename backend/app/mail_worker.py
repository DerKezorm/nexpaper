"""The mail worker: takes one mail apart in a process of its own and reports what it found.

Run as ``python -I app/mail_worker.py`` by ``services/intake_mail.py``, one process for one mail. Taking a mail apart
can cost far more than its size (a header of quotes, a file name of ten thousand encoded words, thousands of
parameters): the server gives this process a time limit (it is killed when it is reached) and, where the system
allows it, a memory limit. It has no database, no settings and no secret, only the path of the mail, a folder for the
parts and the limits. Nothing from ``app`` is imported: this file stands alone (the standard library).

Input: one JSON object on standard input. Output: one JSON object on the last line of standard output:
``{"ok": true, "sender", "recipients", "subject", "message_id", "auth", "parts": [{"name", "path", "size"}], "over"}``
or ``{"ok": false, "error": code}``.
"""

from __future__ import annotations

import contextlib
import email
import email.header
import email.policy
import email.utils
import json
import os
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


def main() -> int:
    real_out = sys.stdout
    sys.stdout = sys.stderr
    try:
        request = json.loads(sys.stdin.read(65536))
        _stop_with_the_parent()
        _limit_memory(int(request.get("memory_mb") or 0))
        _be_modest(int(request.get("cpu_seconds") or 0))
        result = take_apart(request)
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
