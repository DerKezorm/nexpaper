"""Receiving files: the browser's upload (multipart), and what both ways of uploading end in.

**Streaming.** The body of the request is read piece by piece and each file is written to the disk while it arrives,
under a temporary name inside ``dokumente/`` (``storage.incoming_path``): nothing larger than one piece is ever held
in memory. The size is counted as it comes, the SHA-256 is made as it comes, and the kind is read from the first bytes
(``services/filetypes.py``) before more than a few kilobytes were written, so a file that is not welcome stops at once
and the rest of its body is read and thrown away. One file that is too large or of the wrong kind does not stop the
others in the same request: each file has its own result.

**Where it goes.** ``resolve_vault``: the vault the caller names, else the vault they chose as the place for their
uploads, else their own; always one they may add to (``edit`` or ``manage``). The caller owns what they upload.

**The same file.** ``accept`` asks whether the person already has this very file (``services/similar.py``, which sees
only what the person may see) and tells the new document so; a file somebody else keeps where the person cannot look
is not mentioned by anything."""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote_to_bytes

from python_multipart.multipart import MultipartParseError, MultipartParser, parse_options_header
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import error
from ..models import EDIT, Account, Document, Vault
from . import documents, filetypes, limits, rights, similar, storage

logger = logging.getLogger("nexpaper.uploads")

#: The biggest text field of the form that is read (anything past it is dropped).
FIELD_MAX = 2048
#: How many parts a request may have in all (files and fields): a form of a few files and a few fields never comes near.
MAX_PARTS = 50
_PARAMETER = re.compile(r'\s*;\s*([^=;\s]+)\s*=\s*("(?:[^"\\]|\\.)*"|[^;]*)')


class FormTooBig(Exception):
    """More parts than a form of files may have: the request is turned away at once, not read to its end."""

    def __init__(self, code: str, text: str, status: int) -> None:
        super().__init__(text)
        self.code, self.text, self.status = code, text, status


def decode_header(raw: bytes) -> str:
    """A header as text: the bytes a browser sends are UTF-8; where they are not, Latin-1 (which has no wrong bytes)."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def disposition(raw: bytes) -> tuple[str, str | None]:
    """``(name, filename)`` of a ``Content-Disposition: form-data`` header; the filename is None for a part that is no
    file. ``filename*=UTF-8''...`` (RFC 5987) wins over ``filename=``. Any character is taken, in the bytes the browser
    sent them: nothing here is encoded to Latin-1, which many names (``€``, ``U+202F`` in macOS screenshots, emoji) are
    not in."""
    text = decode_header(raw)
    values: dict[str, str] = {}
    for key, value in _PARAMETER.findall(text):
        value = value.strip()
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = re.sub(r"\\(.)", r"\1", value[1:-1])
        values[key.lower()] = value
    extended = values.get("filename*")
    filename = values.get("filename")
    if extended and "'" in extended:
        charset, _language, encoded = extended.split("'", 2)
        try:
            filename = unquote_to_bytes(encoded).decode(charset or "utf-8")
        except (LookupError, UnicodeDecodeError):
            pass
    return values.get("name", ""), filename


@dataclass
class Received:
    """One file of a request, after it was written. ``problem``: ``(status, code, message)`` when it was not taken."""

    filename: str
    path: Path | None = None
    size: int = 0
    sha256: str = ""
    kind: str = ""
    problem: tuple[int, str, str] | None = None


@dataclass
class _Part:
    name: str = ""
    filename: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    received: Received | None = None
    handle: Any = None
    digest: Any = None
    head: bytearray = field(default_factory=bytearray)
    decided: bool = False


class FormReader:
    """The callbacks of the multipart parser for one request."""

    def __init__(self, max_file: int, max_files: int) -> None:
        self.max_file = max_file
        self.max_files = max_files
        self.files: list[Received] = []
        self.fields: dict[str, str] = {}
        self.parts = 0
        self.ended = False
        self._part = _Part()
        self._header_name = b""
        self._header_value = b""

    # -- headers
    def on_part_begin(self) -> None:
        self._part = _Part()

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]

    def on_header_end(self) -> None:
        self._part.headers[self._header_name.decode("latin-1").lower()] = self._header_value
        self._header_name = b""
        self._header_value = b""

    def on_headers_finished(self) -> None:
        part = self._part
        self.parts += 1
        if self.parts > MAX_PARTS:
            raise FormTooBig("too_many_parts", f"At most {MAX_PARTS} parts in one request.", 400)
        raw = part.headers.get("content-disposition", b"")
        try:
            part.name, part.filename = disposition(raw)
        except Exception:  # noqa: BLE001 - a header that cannot be taken apart spoils this part, nothing else
            part.name, part.filename = "", ""
            received = Received(filename="")
            received.problem = (400, "invalid_input", "The header of this file is not valid.")
            part.received = received
            self.files.append(received)
            return
        if part.filename is None:
            return
        if len(self.files) >= self.max_files:
            raise FormTooBig("too_many_files", f"At most {self.max_files} files in one request.", 413)
        received = Received(filename=part.filename[:255])
        part.received = received
        self.files.append(received)
        part.digest = hashlib.sha256()

    # -- body
    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        part = self._part
        chunk = data[start:end]
        if part.filename is None:
            if part.name:
                self.fields[part.name] = (self.fields.get(part.name, "") + chunk.decode("utf-8", "replace"))[:FIELD_MAX]
            return
        received = part.received
        assert received is not None
        if received.problem is not None:
            return  # said no already: the rest of this file is read and dropped
        received.size += len(chunk)
        if received.size > self.max_file:
            received.problem = (413, "too_large",
                                f"The file is larger than the limit of {self.max_file // limits.MB} MB.")
            self._discard(part)
            return
        if not part.decided:
            part.head += chunk
            if len(part.head) >= filetypes.HEAD:
                self._decide(part)
            return
        self._write(part, chunk)

    def _decide(self, part: _Part) -> None:
        """The first bytes are here: what kind of file is it? A file that is not welcome is not written any further."""
        received = part.received
        assert received is not None
        try:
            found = filetypes.sniff(bytes(part.head))
        except filetypes.NotAccepted as exc:
            received.problem = (415, exc.reason, exc.text)
            self._discard(part)
            return
        received.kind = found.kind
        part.decided = True
        path = storage.incoming_path("up-")
        try:
            part.handle = path.open("wb")
        except OSError:
            received.problem = (507, "disk_full", "The server cannot store the file.")
            return
        received.path = path
        # What was held back until the kind was known goes to the disk now.
        self._write(part, bytes(part.head))
        part.head = bytearray()

    def _write(self, part: _Part, chunk: bytes) -> None:
        received = part.received
        assert received is not None
        try:
            part.handle.write(chunk)
        except OSError:
            received.problem = (507, "disk_full", "The server cannot store the file.")
            self._discard(part)
            return
        part.digest.update(chunk)

    def _discard(self, part: _Part) -> None:
        if part.handle is not None:
            try:
                part.handle.close()
            except OSError:
                pass
            part.handle = None
        received = part.received
        if received is not None and received.path is not None:
            received.path.unlink(missing_ok=True)
            received.path = None
        part.head = bytearray()

    def on_end(self) -> None:
        self.ended = True

    def on_part_end(self) -> None:
        part = self._part
        received = part.received
        if part.filename is None or received is None:
            return
        if received.problem is None and not part.decided:
            # A short file: the whole of it is the first bytes.
            if received.size == 0:
                received.problem = (422, "empty_file", "The file is empty.")
            else:
                self._decide(part)
        if part.handle is not None:
            try:
                part.handle.close()
            except OSError:
                received.problem = received.problem or (507, "disk_full", "The server cannot store the file.")
            part.handle = None
        if received.problem is not None:
            self._discard(part)
            return
        received.sha256 = part.digest.hexdigest()

    def cleanup(self) -> None:
        """Whatever was written and not handed on (an error in the middle of the body)."""
        if self._part.handle is not None:
            self._discard(self._part)
        for received in self.files:
            if received.path is not None:
                received.path.unlink(missing_ok=True)
                received.path = None


async def read_form(stream: AsyncIterator[bytes], content_type: str, max_file: int, max_files: int) -> FormReader:
    """Reads a ``multipart/form-data`` body. The files are on the disk when this returns (``Received.path``); the caller
    owns them from then on. Errors of the form itself are the interface's 400."""
    kind, options = parse_options_header(content_type)
    boundary = options.get(b"boundary")
    if kind.lower() != b"multipart/form-data" or not boundary:
        raise error("invalid_input", "Send the files as multipart/form-data.", 400)
    reader = FormReader(max_file, max_files)
    callbacks = {
        "on_part_begin": reader.on_part_begin, "on_header_field": reader.on_header_field,
        "on_header_value": reader.on_header_value, "on_header_end": reader.on_header_end,
        "on_headers_finished": reader.on_headers_finished, "on_part_data": reader.on_part_data,
        "on_part_end": reader.on_part_end, "on_end": reader.on_end,
    }
    parser = MultipartParser(boundary, callbacks)  # type: ignore[arg-type]
    try:
        async for chunk in stream:
            parser.write(chunk)
        parser.finalize()
    except FormTooBig as exc:
        reader.cleanup()
        raise error(exc.code, exc.text, exc.status) from exc
    except MultipartParseError as exc:
        reader.cleanup()
        raise error("invalid_input", "The form is not valid.", 400) from exc
    except BaseException:
        reader.cleanup()
        raise
    if not reader.ended:
        # The body stopped before the closing boundary: nothing in it can be trusted to be whole.
        reader.cleanup()
        raise error("invalid_input", "The form is not valid.", 400)
    return reader


# --- Where it goes, and what it ends in -------------------------------------------------------------------------------


def personal_vault(db: Session, uid: int) -> int:
    found = db.scalar(select(Vault.id).where(Vault.personal_of == uid))
    if found is None:
        raise error("not_found", "Not found.", 404)
    return int(found)


def resolve_vault(db: Session, uid: int, vault_id: int | None) -> int:
    """The vault a file of ``uid`` goes to. Named: it must be one they may add to (404 when they cannot even see it, 403
    when they may only read there). Not named: their own choice (Account, Uploads) if they may still add there, else
    their own vault."""
    if vault_id is not None:
        rights.require_vault(db, uid, vault_id, EDIT)
        return vault_id
    account = db.get(Account, uid)
    profile = account.profile if account is not None and isinstance(account.profile, dict) else {}
    chosen = profile.get("default_vault")
    if type(chosen) is int and rights.at_least(rights.vault_right(db, uid, chosen), EDIT):
        return chosen
    return personal_vault(db, uid)


def accept(
    db: Session, *, uid: int, vault_id: int, filename: str, path: Path, kind: str, sha256: str, size: int, source: str,
    title: str | None = None, also: Callable[[Session, Document], None] | None = None,
    detail: dict[str, Any] | None = None,
) -> tuple[Document, Document | None]:
    """A complete file on the disk becomes a document of ``uid`` in ``vault_id``. Returns it, and the document the
    person already has with this very file (if they may see one). The file is moved: ``path`` is gone afterwards.
    ``title``: a title other than the one the file name gives; ``also``: rows of the caller for the same transaction;
    ``detail``: more for the history entry of the creation."""
    twin = similar.same_file(db, uid, sha256)
    document = documents.create_from_file(
        db, vault_id=vault_id, owner_id=uid, title=title or filetypes.title_from(filename), source=source, path=path,
        kind=kind, sha256=sha256, size=size, same_as=twin.id if twin else None, created_by=uid, also=also,
        detail=detail,
    )
    return document, twin
