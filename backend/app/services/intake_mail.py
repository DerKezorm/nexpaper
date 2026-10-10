"""The mailbox for documents: one IMAP mailbox per server, fetched every 5 minutes and on demand.

* **The operator's lock.** Nothing connects while the mailbox is switched off, not even a test. The password is sealed
  with the server's secret, never given back, and forgotten when server or port change without a new one (a stolen
  session must not be enough to send the stored password to a server of its own).
* **Where it connects.** The name is resolved once per connection and every address is checked (``outbound.py``): never
  link-local or the metadata of cloud machines, the own network only when the operator allowed it, and the connection
  goes to exactly the addresses checked. TLS from the first byte or STARTTLS; without TLS only to a server on the same
  machine (127.0.0.1). Every read and write waits a limited time, and the whole run has a deadline.
* **Whose it is.** The ``name+<account>@`` form of the mailbox's address (in To, Cc and the delivery headers), else a
  confirmed address the person forwards from (``services/mail_senders.py``). Anything else goes to the operator,
  marked unknown. A sender's address can be forged, so nothing is filed by itself: it all waits in an inbox.
* **What is taken.** PDF, pictures and e-invoices as XML, also inside forwarded mails (``message/rfc822``); the kind is
  read from the content. A mail larger than ``MAIL_MAX`` is left alone, at most ``MAX_ATTACHMENTS`` parts of a mail
  are taken, broken parts are passed over. The mail itself never becomes a document.
* **Exactly once.** Every part taken is noted (UIDVALIDITY, UID, number of the part) in the transaction of its document,
  and the last UID fetched is kept per mailbox. When the server gives the mailbox new UIDs, a part already taken from
  a mail of the same Message-ID is known again by its checksum. Afterwards the mail is marked read, moved to
  ``nexpaper`` or deleted, as the operator chose.
"""

from __future__ import annotations

import hashlib
import imaplib
import ipaddress
import json
import logging
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .. import clock
from ..db import SessionLocal
from ..models import IntakeItem
from ..security import decrypt_secret
from . import filetypes, intake, limits, mail_senders, outbound, settings_service, storage

logger = logging.getLogger("nexpaper.intake")

PASSWORD_CONTEXT = "operator:mail-intake"
SECURITIES = ("tls", "starttls", "none")
AFTER = ("read", "move", "delete")
#: The folder mails are moved to when the operator chose so.
MOVE_TO = "nexpaper"
#: Names that mean this machine: the only ones reached without TLS.
LOCAL_HOSTS = ("127.0.0.1", "::1", "localhost")

MB = limits.MB
#: The largest mail that is fetched (it is held in memory while its parts are read).
MAIL_MAX = 50 * MB
#: Parts taken from one mail at most, parts looked at at most, and how deep mails and parts may nest.
MAX_ATTACHMENTS = 20
MAX_PARTS = 300
MAX_NESTING = 8
#: An inline picture with a Content-ID is a logo in a signature unless it is at least this large.
INLINE_PICTURE_MIN = 20 * 1024
#: Mails handled in one run; the rest comes in the next one.
PER_RUN = 25
#: One read or write, making the connection, the whole run.
STEP_SECONDS = 30.0
CONNECT_SECONDS = 10.0
RUN_SECONDS = 300.0
#: Lines one answer may hold (a server that floods with untagged lines is cut off).
MAX_LINES = 10_000

#: For the tests: how names are resolved and which certificates are trusted.
resolver: Callable[[str, int], list[str]] = outbound.resolve
context: Callable[[], ssl.SSLContext] = ssl.create_default_context

_HOST = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                   r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?$")
_FOLDER = re.compile(r"^[\x20-\x7e]{1,200}$")
_UID = re.compile(rb"UID (\d+)")
_SIZE = re.compile(rb"RFC822\.SIZE (\d+)")

MESSAGES = {
    "mailbox_off": "The mailbox is switched off.",
    "mail_incomplete": "The mailbox is not set up completely.",
    "mail_host_invalid": "This is not the name of a mail server.",
    "mail_folder_invalid": "This is not the name of a folder.",
    "mail_plain_not_local": "Without TLS only a mail server on this machine (127.0.0.1) is reached.",
    "mail_address_refused": "This address is never reached.",
    "mail_address_private": "This mail server lies in the own network. Allow the own network first.",
    "mail_unreachable": "The server cannot reach the mail server.",
    "mail_tls_failed": "The secure connection to the mail server failed.",
    "mail_login_failed": "The mail server refused user or password.",
    "mail_folder_missing": "The mail server has no such folder.",
    "mail_timeout": "The mail server took too long.",
    "mail_protocol": "The mail server answered in a way nexpaper does not understand.",
    "mail_busy": "The mailbox is being fetched right now. Try again in a moment.",
}
STATUS = {"mailbox_off": 409, "mail_incomplete": 409, "mail_busy": 409, "mail_host_invalid": 422,
          "mail_folder_invalid": 422, "mail_plain_not_local": 422, "mail_address_refused": 422,
          "mail_address_private": 422}


class MailFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(MESSAGES.get(code, code))
        self.code = code
        self.status = STATUS.get(code, 502)


class MailBusy(MailFailure):
    def __init__(self) -> None:
        super().__init__("mail_busy")


# --- Checking what the operator typed ---------------------------------------------------------------------------------


def check_host(text: str) -> str:
    """A host name or an address, cleaned; ``MailFailure("mail_host_invalid")`` else."""
    host = (text or "").strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host:
        raise MailFailure("mail_host_invalid")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    if not _HOST.match(host):
        raise MailFailure("mail_host_invalid")
    return host.rstrip(".").lower()


def check_folder(text: str) -> str:
    folder = (text or "").strip()
    if not _FOLDER.match(folder):
        raise MailFailure("mail_folder_invalid")
    return folder


def pin(host: str, port: int, security: str, private: bool) -> list[str]:
    """The addresses of the server, each one checked: never link-local or a metadata service, without TLS only this
    machine, the own network only when the operator allowed it."""
    if security == "none" and host not in LOCAL_HOSTS:
        raise MailFailure("mail_plain_not_local")
    try:
        addresses = resolver(host, port)
    except outbound.Unreachable as exc:
        raise MailFailure("mail_unreachable") from exc
    if not addresses:
        raise MailFailure("mail_unreachable")
    for address in addresses:
        try:
            ip = outbound.ip_of(address)
        except ValueError as exc:
            raise MailFailure("mail_address_refused") from exc
        if outbound.never(ip):
            raise MailFailure("mail_address_refused")
        if security == "none" and not ip.is_loopback:
            raise MailFailure("mail_plain_not_local")
        if not private and not outbound.public(address):
            raise MailFailure("mail_address_private")
    return addresses


# --- The connection ---------------------------------------------------------------------------------------------------


class _Tls:
    """TLS for a connection: the socket is put under the deadline before its handshake begins (``held``), so a server
    that answers the handshake a byte at a time is cut off like any other."""

    def __init__(self, context: ssl.SSLContext, held: list[socket.socket]) -> None:
        self._context = context
        self._held = held

    def wrap_socket(self, sock: socket.socket, server_hostname: str | None = None, **_ignored: Any) -> ssl.SSLSocket:
        wrapped = self._context.wrap_socket(sock, server_hostname=server_hostname, do_handshake_on_connect=False)
        self._held.append(wrapped)
        wrapped.do_handshake()
        return wrapped


class _Client(imaplib.IMAP4):
    """imaplib's client, connected to the checked addresses only (tried in turn, never the name looked up again), with
    TLS from the first byte when asked. Every socket is under the deadline from the moment it exists (the greeting
    included), and an answer to one command may hold at most ``MAX_LINES`` lines and a mail's size in bytes."""

    def __init__(self, host: str, port: int, addresses: list[str], implicit_tls: bool, tls: _Tls,
                 held: list[socket.socket], largest: int) -> None:
        self._addresses = addresses
        self._implicit = implicit_tls
        self._tls = tls
        self._held = held
        self._largest = largest
        self._lines = 0
        self._bytes = 0
        super().__init__(host, port, STEP_SECONDS)

    def _create_socket(self, timeout: float | None) -> socket.socket:
        last: OSError | None = None
        for address in self._addresses:
            try:
                sock = socket.create_connection((address, self.port), CONNECT_SECONDS)
            except OSError as exc:
                last = exc
                continue
            self._held.append(sock)
            sock.settimeout(timeout)
            if self._implicit:
                return self._tls.wrap_socket(sock, server_hostname=self.host)
            return sock
        raise last or OSError("no address")

    def read(self, size: int) -> bytes:
        if size > self._largest:
            raise self.abort("an answer larger than a mail may be")
        return super().read(size)

    def _command(self, name: str, *args: Any) -> Any:
        self._lines = 0
        self._bytes = 0
        return super()._command(name, *args)

    def _append_untagged(self, typ: str, dat: Any) -> None:
        self._lines += 1
        if isinstance(dat, bytes):
            self._bytes += len(dat)
        elif isinstance(dat, tuple):
            self._bytes += sum(len(one) for one in dat if isinstance(one, bytes))
        if self._lines > MAX_LINES or self._bytes > self._largest + MB:
            raise self.abort("an answer longer than any command needs")
        super()._append_untagged(typ, dat)


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    security: str
    user: str
    password: str
    folder: str
    after: str
    private: bool
    address: str
    drop_unknown: bool
    auth_server: str = ""

    @property
    def box(self) -> str:
        """A name for the mailbox as it is set up (server, port, account, folder): what was taken and where fetching
        stands belong to this one."""
        text = f"{self.host}|{self.port}|{self.user}|{self.folder}".lower()
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def config(db: Any) -> Config:
    values = settings_service.get_all(db)
    if not values["mail_on"]:
        raise MailFailure("mailbox_off")
    security = values["mail_security"] if values["mail_security"] in SECURITIES else "tls"
    after = values["mail_after"] if values["mail_after"] in AFTER else "read"
    host = str(values["mail_host"] or "")
    user = str(values["mail_user"] or "")
    password = decrypt_secret(str(values["mail_password_enc"] or ""), PASSWORD_CONTEXT)
    if not (host and user and password):
        raise MailFailure("mail_incomplete")
    return Config(host=check_host(host), port=int(values["mail_port"] or 993), security=security, user=user,
                  password=password, folder=check_folder(str(values["mail_folder"] or "INBOX")), after=after,
                  private=bool(values["mail_private"]), address=str(values["mail_address"] or ""),
                  drop_unknown=bool(values["mail_drop_unknown"]),
                  auth_server=str(values["mail_auth_server"] or ""))


def _failure(exc: BaseException, late: threading.Event) -> MailFailure:
    if isinstance(exc, MailFailure):
        return exc
    if late.is_set():
        return MailFailure("mail_timeout")
    if isinstance(exc, ssl.SSLError):
        return MailFailure("mail_tls_failed")
    if isinstance(exc, TimeoutError | socket.timeout):
        return MailFailure("mail_timeout")
    if isinstance(exc, imaplib.IMAP4.error | UnicodeError | ValueError):
        return MailFailure("mail_protocol")
    if isinstance(exc, OSError):
        return MailFailure("mail_unreachable")
    return MailFailure("mail_protocol")


def _quoted(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Box:
    client: _Client
    uidvalidity: int
    late: threading.Event

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(str(word).upper() for word in self.client.capabilities)

    def call(self, command: str, *args: str) -> list[Any]:
        """A UID command; its data, or ``MailFailure``."""
        try:
            kind, data = self.client.uid(command, *args)
        except Exception as exc:
            raise _failure(exc, self.late) from exc
        if kind != "OK":
            raise MailFailure("mail_protocol")
        return list(data or [])

    def uids(self, criteria: list[str]) -> list[int]:
        data = self.call("SEARCH", *criteria)
        found: set[int] = set()
        for line in data:
            if isinstance(line, bytes):
                found.update(int(word) for word in line.split() if word.isdigit())
        return sorted(found)


@contextmanager
def session(cfg: Config, readonly: bool) -> Iterator[Box]:
    """A connection to the mailbox, signed in, the folder selected; logged out afterwards. The whole of it has a
    deadline, from the first byte of the connection on: when it passes, every socket is cut and whatever waits fails."""
    addresses = pin(cfg.host, cfg.port, cfg.security, cfg.private)
    late = threading.Event()
    held: list[socket.socket] = []

    def cut() -> None:
        late.set()
        for sock in held:
            with suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    tls = _Tls(context(), held)
    timer = threading.Timer(RUN_SECONDS, cut)
    timer.daemon = True
    timer.start()
    try:
        try:
            client = _Client(cfg.host, cfg.port, addresses, cfg.security == "tls", tls, held, MAIL_MAX + 64 * 1024)
        except Exception as exc:
            raise _failure(exc, late) from exc
        try:
            if cfg.security == "starttls":
                # Without it nothing more is said: the password never goes out in the clear.
                try:
                    client.starttls(tls)  # type: ignore[arg-type]
                except (imaplib.IMAP4.abort, imaplib.IMAP4.error, ssl.SSLError, OSError) as exc:
                    raise (MailFailure("mail_timeout") if late.is_set() else MailFailure("mail_tls_failed")) from exc
            try:
                client.login(cfg.user, cfg.password)
            except imaplib.IMAP4.abort as exc:
                raise _failure(exc, late) from exc
            except (imaplib.IMAP4.error, UnicodeError) as exc:
                raise MailFailure("mail_login_failed") from exc
            try:
                kind, _data = client.select(_quoted(cfg.folder), readonly=readonly)
            except imaplib.IMAP4.abort as exc:
                raise _failure(exc, late) from exc
            except imaplib.IMAP4.error as exc:
                raise MailFailure("mail_folder_missing") from exc
            if kind != "OK":
                raise MailFailure("mail_folder_missing")
            _kind, validity = client.response("UIDVALIDITY")
            try:
                uidvalidity = int((validity or [b"0"])[-1] or 0)
            except (TypeError, ValueError):
                uidvalidity = 0
            yield Box(client, uidvalidity, late)
        except MailFailure:
            raise
        except Exception as exc:
            raise _failure(exc, late) from exc
        finally:
            try:
                client.logout()
            except Exception:  # noqa: BLE001 - leaving is tried, never required
                with suppress(Exception):
                    client.shutdown()
    finally:
        timer.cancel()


# --- What happens afterwards ------------------------------------------------------------------------------------------


def effective_after(after: str, capabilities: tuple[str, ...]) -> str:
    """What "afterwards" really does on this server. Deleting one mail needs UIDPLUS (a plain EXPUNGE would take every
    mail marked deleted with it, also ones nexpaper never touched); moving needs MOVE or UIDPLUS. Without them a mail
    is moved where it can be, else marked read."""
    if after == "delete":
        return "delete" if "UIDPLUS" in capabilities else "move" if "MOVE" in capabilities else "read"
    if after == "move":
        return "move" if "MOVE" in capabilities or "UIDPLUS" in capabilities else "read"
    return "read"


def _after(box: Box, cfg: Config, uid: int, made: list[bool]) -> None:
    """What happens to a mail that was taken whole: marked read, moved to ``nexpaper`` or deleted."""
    capabilities = box.capabilities
    action = effective_after(cfg.after, capabilities)
    number = str(uid)
    if action == "read":
        box.call("STORE", number, "+FLAGS", "(\\Seen)")
        return
    if action == "move":
        if not made[0]:
            with suppress(imaplib.IMAP4.error):
                box.client.create(_quoted(MOVE_TO))
            made[0] = True
        if "MOVE" in capabilities:
            box.call("MOVE", number, _quoted(MOVE_TO))
            return
        box.call("COPY", number, _quoted(MOVE_TO))
    box.call("STORE", number, "+FLAGS", "(\\Deleted)")
    box.call("EXPUNGE", number)


def _flag(box: Box, uid: int) -> None:
    """A mail nexpaper could not take whole: it stays where it is and is flagged, so that it stands out in the mail
    program."""
    with suppress(MailFailure):
        box.call("STORE", str(uid), "+FLAGS", "(\\Flagged)")


# --- Which mails ------------------------------------------------------------------------------------------------------


def _state(cfg: Config, box: Box, stored: Any) -> dict[str, Any]:
    """Where fetching stands for this mailbox: the last UID looked at, the mails to try again (``retry``, with their
    tries) and those left for the next day (``later``). A fresh start (a new mailbox, or new UIDs) takes the unread
    mails only (``backlog``): what was read before nexpaper came is history, not new post. Then everything after."""
    state = stored if isinstance(stored, dict) else {}
    if state.get("box") == cfg.box and state.get("uidvalidity") == box.uidvalidity:
        return {"box": cfg.box, "uidvalidity": box.uidvalidity, "last": int(state.get("last") or 0),
                "backlog": bool(state.get("backlog")),
                "retry": {str(k): int(v) for k, v in dict(state.get("retry") or {}).items()},
                "later": {str(k): str(v) for k, v in dict(state.get("later") or {}).items()}}
    return {"box": cfg.box, "uidvalidity": box.uidvalidity, "last": 0, "backlog": True, "retry": {}, "later": {}}


def _waiting(box: Box, state: dict[str, Any]) -> list[int]:
    start = f"{int(state['last']) + 1}:*"
    criteria = ["UNSEEN", "UID", start] if state["backlog"] else ["UID", start]
    return [uid for uid in box.uids(criteria) if uid > int(state["last"])]


def _due(state: dict[str, Any], today: str) -> list[int]:
    """Mails from before that are tried again now: those whose take failed, and those left for a day that has come."""
    again = {int(uid) for uid in state["retry"]}
    again |= {int(uid) for uid, day in state["later"].items() if day < today}
    return sorted(again)


# --- Checking a mail before it is taken apart -------------------------------------------------------------------------

#: Limits a mail must keep before it is even taken apart: a line of a header, the lines and bytes of all headers of one
#: block, the parts (header blocks), the parameters of a header, the length of a file name, the addresses named.
MAX_HEADER_LINE = 8 * 1024
#: Other headers (a long ``References`` of a thread of replies) may be longer.
MAX_OTHER_HEADER_LINE = 64 * 1024
MAX_HEADER_LINES = 500
MAX_HEADER_BLOCK = 256 * 1024
MAX_MIME_PARTS = 100
MAX_PARAMETERS = 100
MAX_NAME = 1024
MAX_ADDRESSES = 100
ADDRESS_HEADERS = (b"from", b"to", b"cc", b"bcc", b"reply-to", b"sender", b"delivered-to", b"x-original-to",
                   b"envelope-to", b"x-envelope-to", b"x-forwarded-to")
_NAME_PARAMETER = re.compile(rb"(?:file)?name\*?(?:\d+\*?)?\s*=\s*(\"(?:[^\"\\]|\\.)*\"|[^;]*)", re.IGNORECASE)


def _header_blocks(raw: bytes) -> Iterator[list[bytes]]:
    """The header blocks of a mail, read as plain lines without taking the mail apart: the head of the mail, and the
    head of every part (after a line that starts with ``--``). Each block as its logical lines (folded lines joined)."""
    lines = raw.split(b"\n")
    index, count = 0, len(lines)
    start_of_block = True
    while index < count:
        if start_of_block:
            block: list[bytes] = []
            while index < count:
                line = lines[index].rstrip(b"\r")
                index += 1
                if not line:
                    break
                if line[:1] in (b" ", b"\t") and block:
                    block[-1] = block[-1] + b" " + line.strip()
                else:
                    block.append(line)
            yield block
            start_of_block = False
            continue
        line = lines[index]
        index += 1
        if line.startswith(b"--") and len(line) < 200:
            following = lines[index].rstrip(b"\r") if index < count else b""
            if b":" in following[:80]:
                start_of_block = True


def too_elaborate(raw: bytes) -> bool:
    """Whether a mail is refused before it is taken apart, by a look at its bytes only: headers no mail program writes
    (an address or MIME header over 8 KB, any other over 64 KB, hundreds of lines), more than 100 parts, a header with
    more than 100 parameters, a file name over 1 KB, more than 100 addresses. Such a mail costs far more to take apart
    than its size."""
    for blocks, block in enumerate(_header_blocks(raw), start=1):
        if blocks > MAX_MIME_PARTS + 1 or len(block) > MAX_HEADER_LINES:
            return True
        if sum(len(line) for line in block) > MAX_HEADER_BLOCK:
            return True
        for line in block:
            name = line.split(b":", 1)[0].strip().lower()
            strict = name in ADDRESS_HEADERS or name.startswith(b"content-")
            if len(line) > (MAX_HEADER_LINE if strict else MAX_OTHER_HEADER_LINE):
                return True
            if name in (b"content-type", b"content-disposition"):
                if line.count(b";") > MAX_PARAMETERS:
                    return True
                if sum(len(value) for value in _NAME_PARAMETER.findall(line)) > MAX_NAME:
                    return True
            if blocks == 1 and name in ADDRESS_HEADERS and line.count(b"@") > MAX_ADDRESSES:
                return True
    return False


# --- Taking a mail apart, in a process of its own ---------------------------------------------------------------------

WORKER = Path(__file__).resolve().parent.parent / "mail_worker.py"
#: The time one mail may take to be taken apart, and the memory for it (MB) where the system can limit it.
WORKER_SECONDS = 20
WORKER_MEMORY_MB = 1024


@dataclass
class Parsed:
    ok: bool
    error: str = ""
    sender: str = ""
    recipients: list[str] = field(default_factory=list)
    subject: str = ""
    message_id: str = ""
    auth: list[str] = field(default_factory=list)
    parts: list[dict[str, Any]] = field(default_factory=list)
    over: int = 0


def take_apart(raw: bytes, folder: Path, max_file: int) -> Parsed:
    """The mail taken apart by the mail worker (``app/mail_worker.py``) in a process with a time and a memory limit; a
    mail that needs more, or that the cheap look already refuses, is ``too_elaborate``. The parts are written to
    ``folder``."""
    if too_elaborate(raw):
        return Parsed(False, error="too_elaborate")
    source = folder / "mail.eml"
    source.write_bytes(raw)
    request = {"source": str(source), "out": str(folder), "max_parts": MAX_ATTACHMENTS, "max_bytes": max_file,
               "inline_min": INLINE_PICTURE_MIN, "nesting": MAX_NESTING, "parts_limit": MAX_PARTS,
               "memory_mb": WORKER_MEMORY_MB, "cpu_seconds": max(1, int(WORKER_SECONDS))}
    from . import processing

    environment = {key: os.environ[key] for key in processing.KEEP_ENVIRONMENT if key in os.environ}
    options: dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {}
    process = subprocess.Popen(
        [sys.executable, "-I", str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=environment, cwd=str(folder), **options,
    )
    try:
        out, _err = process.communicate(json.dumps(request).encode("utf-8"), timeout=WORKER_SECONDS)
    except subprocess.TimeoutExpired:
        processing._kill(process)
        processing._reap(process)
        return Parsed(False, error="too_elaborate")
    except BaseException:
        processing._kill(process)
        raise
    finally:
        source.unlink(missing_ok=True)
    lines = [line for line in out.decode("utf-8", "replace").splitlines() if line.strip()]
    try:
        answer = json.loads(lines[-1]) if lines else None
    except ValueError:
        answer = None
    if process.returncode != 0 or not isinstance(answer, dict):
        # Killed by the memory limit, or ended without a word: as costly as a mail may be.
        return Parsed(False, error="too_elaborate")
    if not answer.get("ok"):
        return Parsed(False, error=str(answer.get("error") or "unreadable"))
    return Parsed(
        True, sender=str(answer.get("sender") or "")[:320],
        recipients=[str(one)[:320] for one in list(answer.get("recipients") or [])[:MAX_ADDRESSES]],
        subject=str(answer.get("subject") or "")[:200], message_id=str(answer.get("message_id") or "")[:1000],
        auth=[str(one)[:2000] for one in list(answer.get("auth") or [])[:5]],
        parts=[one for one in list(answer.get("parts") or []) if isinstance(one, dict)][:MAX_ATTACHMENTS],
        over=int(answer.get("over") or 0),
    )


# --- Whose a mail is -------------------------------------------------------------------------------------------------


def _authserv(value: str) -> tuple[str, str]:
    """The id of the server that wrote an ``Authentication-Results`` header, and the rest of it."""
    head, _semi, rest = value.partition(";")
    words = head.split()
    return (words[0].strip().lower().rstrip(".") if words else ""), rest.lower()


def failed_check(auth: list[str], mailbox: str, trusted: str = "") -> bool:
    """Whether the server that received the mail says the sender failed DMARC. Only headers written by the trusted
    server count (the name the operator set, else the domain of the mailbox's address, each with the names below it);
    anybody can write such a header into a mail they send, so all others are ignored. ``spf=fail`` alone does not count:
    a forwarded mail fails SPF and still passes DMARC."""
    name = (trusted or mailbox.rpartition("@")[2]).strip().lower().rstrip(".")
    if not name:
        return False
    for value in auth:
        server, rest = _authserv(value)
        if server != name and not server.endswith("." + name):
            continue
        if re.search(r"\bdmarc\s*=\s*fail\b", rest):
            return True
    return False


def assign(db: Any, sender: str, recipients: list[str], mailbox: str) -> tuple[int | None, bool]:
    """Whose a mail is: ``name+<account>@`` of the mailbox's address (its domain; the name is what stands up to the
    next ``+``; all such recipients must name the same account), else a confirmed sender address of exactly one person;
    else the operator's, marked unknown."""
    if "@" in mailbox:
        local, _at, domain = mailbox.strip().rpartition("@")
        prefix = local.casefold() + "+"
        named: set[str] = set()
        for recipient in recipients:
            r_local, _at2, r_domain = recipient.rpartition("@")
            if r_domain.casefold() == domain.casefold() and r_local.casefold().startswith(prefix):
                named.add(r_local[len(prefix):].split("+", 1)[0].casefold())
        if len(named) == 1:
            account = intake.account_named(db, next(iter(named)))
            if account is not None:
                return account.id, False
        if len(named) > 1:
            return intake.operator_id(db), True
    if sender:
        owners = mail_senders.owners(db, sender)
        if len(owners) == 1:
            return next(iter(owners)), False
    return intake.operator_id(db), True


# --- One mail ---------------------------------------------------------------------------------------------------------


@dataclass
class Taken:
    """What one mail gave: the parts that may be documents (``takeable``), documents made (``files``), parts known from
    before (``known``), parts that failed and may be tried again (``failed``), parts over the limits (``over``), whether
    it went to the operator as unknown, the person it belongs to and the bytes taken for them."""

    takeable: int = 0
    files: int = 0
    known: int = 0
    failed: int = 0
    over: int = 0
    unknown: bool = False
    owner: int | None = None
    bytes: int = 0
    error: str = ""
    dropped: bool = False
    deferred: bool = False

    @property
    def whole(self) -> bool:
        """Every part that may be a document was taken now or before, and none was over a limit."""
        return self.takeable > 0 and self.files + self.known == self.takeable and not self.failed and not self.over


def take_mail(raw: bytes, *, box: str, uidvalidity: int, uid: int, mailbox: str, drop_unknown: bool = False,
              budget: Callable[[int, int], bool] | None = None, auth_server: str = "") -> Taken:
    """The parts of one mail that are documents become documents of whoever the mail is for. ``budget(owner, bytes)``
    says whether the person may still receive that much today."""
    taken = Taken()
    with SessionLocal() as db:
        max_file = limits.current(db).max_file
    with tempfile.TemporaryDirectory(prefix="nexpaper-mail-") as folder:
        parsed = take_apart(raw, Path(folder), max_file)
        if not parsed.ok:
            taken.error = parsed.error
            return taken
        marker = hashlib.sha256(parsed.message_id.encode("utf-8", "replace")).hexdigest() if parsed.message_id else ""
        with SessionLocal() as db:
            if failed_check(parsed.auth, mailbox, auth_server):
                owner, unknown = intake.operator_id(db), True
            else:
                owner, unknown = assign(db, parsed.sender, parsed.recipients, mailbox)
        taken.unknown, taken.owner, taken.over = unknown, owner, parsed.over
        if owner is None:
            taken.error = "unreadable"
            return taken
        candidates: list[tuple[int, str, Path, str, str, int]] = []
        for part in parsed.parts:
            path = Path(str(part.get("path") or ""))
            if path.parent != Path(folder) or not path.is_file():
                continue
            with path.open("rb") as handle:
                head = handle.read(filetypes.HEAD)
            try:
                kind = filetypes.sniff(head).kind
            except filetypes.NotAccepted:
                continue
            candidates.append((int(part.get("number") or 0), str(part.get("name") or "")[:200], path, kind,
                               _sha256(path), path.stat().st_size))
        taken.takeable = len(candidates) + parsed.over
        if unknown and drop_unknown:
            taken.dropped = True
            return taken
        fresh = sum(size for *_rest, size in candidates)
        if budget is not None and candidates and not budget(owner, fresh):
            taken.deferred = True
            return taken
        for number, name, path, kind, sha256, size in candidates:
            key = f"{box}:{uidvalidity}:{uid}:{number}"
            _take_part(taken, key, name, path, kind, sha256, size, owner=owner, unknown=unknown, marker=marker,
                       sender=parsed.sender, subject=parsed.subject)
    return taken


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _take_part(taken: Taken, key: str, filename: str, path: Path, kind: str, sha256: str, size: int, *, owner: int,
               unknown: bool, marker: str, sender: str, subject: str) -> None:
    with SessionLocal() as db:
        known = db.scalar(select(IntakeItem.id).where(IntakeItem.source == intake.MAIL, IntakeItem.key == key))
        if known is None and marker:
            known = db.scalar(select(IntakeItem.id).where(IntakeItem.source == intake.MAIL,
                                                          IntakeItem.message == marker, IntakeItem.sha256 == sha256))
        if known is not None:
            taken.known += 1
            return
        temporary = storage.incoming_path("mail-")
        try:
            shutil.move(str(path), str(temporary))
            title = filetypes.title_from(filename) if filename else filetypes.plain_title(subject)
            intake.take(
                db, uid=owner, path=temporary, filename=filename or "document", kind=kind, sha256=sha256, size=size,
                source=intake.MAIL, title=title[:200],
                item={"key": key, "state": intake.DONE, "sha256": sha256, "size": size, "message": marker,
                      "unknown": unknown, "detail": {"from": sender[:255], "subject": subject, "file": filename}},
            )
        except Exception as exc:  # noqa: BLE001 - a part that fails must not stop the others; the mail is tried again
            temporary.unlink(missing_ok=True)
            logger.warning("Mailbox: a part could not be taken error=%s", type(exc).__name__)
            taken.failed += 1
            return
    taken.files += 1
    taken.bytes += size


# --- A run ------------------------------------------------------------------------------------------------------------

#: A mail whose take failed is tried this often in all, then it is flagged and left.
MAX_TRIES = 3
#: Bytes of mail fetched in one run, of documents taken in a day on the whole server and for one person.
RUN_BYTES = 250 * MB
DAY_BYTES = 2048 * MB
PERSON_DAY_BYTES = 500 * MB


@dataclass
class Result:
    mails: int = 0
    files: int = 0
    unknown: int = 0
    passed: int = 0
    skipped: int = 0
    flagged: int = 0
    deferred: int = 0
    dropped: int = 0
    more: bool = False
    after: str = ""


_lock = threading.Lock()


def _sizes(box: Box, uids: list[int]) -> dict[int, int]:
    data = box.call("FETCH", ",".join(str(uid) for uid in uids), "(UID RFC822.SIZE)")
    sizes: dict[int, int] = {}
    for line in data:
        text = line[0] if isinstance(line, tuple) else line
        if not isinstance(text, bytes):
            continue
        uid, size = _UID.search(text), _SIZE.search(text)
        if uid and size:
            sizes[int(uid.group(1))] = int(size.group(1))
    return sizes


def _body(box: Box, uid: int) -> bytes:
    data = box.call("FETCH", str(uid), "(BODY.PEEK[])")
    for line in data:
        if isinstance(line, tuple) and len(line) >= 2 and isinstance(line[1], bytes):
            return line[1]
    raise MailFailure("mail_protocol")


def _save_state(state: dict[str, Any]) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"mail_state": dict(state)})


def _remember(ok: bool, code: str, result: Result) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"mail_last": {
            "at": clock.now().isoformat(), "ok": ok, "code": code, "mails": result.mails, "files": result.files,
            "unknown": result.unknown, "skipped": result.skipped, "flagged": result.flagged,
            "deferred": result.deferred}})


class Budget:
    """The bytes of the day: on the whole server and per person, kept in the settings (``mail_budget``)."""

    def __init__(self, today: str) -> None:
        with SessionLocal() as db:
            stored = settings_service.get(db, "mail_budget")
        stored = stored if isinstance(stored, dict) and stored.get("day") == today else {}
        self.today = today
        self.total = int(stored.get("bytes") or 0)
        self.people = {str(k): int(v) for k, v in dict(stored.get("people") or {}).items()}

    def day_left(self, size: int) -> bool:
        return self.total + size <= DAY_BYTES

    def person_left(self, owner: int, size: int) -> bool:
        return self.people.get(str(owner), 0) + size <= PERSON_DAY_BYTES

    def spend(self, owner: int | None, size: int) -> None:
        self.total += size
        if owner is not None:
            self.people[str(owner)] = self.people.get(str(owner), 0) + size
        with SessionLocal() as db:
            settings_service.save(db, {"mail_budget": {"day": self.today, "bytes": self.total, "people": self.people}})


def fetch() -> Result:
    """One run: the mails that came since the last one, and those to be tried again (``PER_RUN`` of them at most, and
    ``RUN_BYTES``). ``MailBusy`` while a run is going on, ``MailFailure`` when the mailbox cannot be used (said in the
    log and kept for the settings)."""
    if not _lock.acquire(blocking=False):
        raise MailBusy
    try:
        return _fetch()
    finally:
        _lock.release()


def _still_on() -> bool:
    with SessionLocal() as db:
        return bool(settings_service.get(db, "mail_on"))


def _fetch() -> Result:
    result = Result()
    with SessionLocal() as db:
        cfg = config(db)
        stored = settings_service.get(db, "mail_state")
    today = clock.now().date().isoformat()
    budget = Budget(today)
    try:
        with session(cfg, readonly=False) as box:
            result.after = effective_after(cfg.after, box.capabilities)
            state = _state(cfg, box, stored)
            fresh = _waiting(box, state)
            if not fresh and state["backlog"]:
                # The unread mails of a fresh start are done: from here on, everything after the newest mail.
                state["last"] = max([state["last"], *box.uids(["ALL"])])
                state["backlog"] = False
            waiting = sorted(set(_due(state, today)) | set(fresh))
            result.more = len(waiting) > PER_RUN
            batch = waiting[:PER_RUN]
            sizes = _sizes(box, batch) if batch else {}
            for gone in [uid for uid in batch if uid not in sizes]:
                # Tried again, but no longer in the mailbox (moved or deleted by somebody else).
                state["retry"].pop(str(gone), None)
                state["later"].pop(str(gone), None)
            made = [False]
            fetched = 0
            for uid in [uid for uid in batch if uid in sizes]:
                if box.late.is_set() or not _still_on():
                    result.more = True
                    break
                size = sizes[uid]
                if (fetched and fetched + size > RUN_BYTES) or not budget.day_left(min(size, MAIL_MAX)):
                    result.more = True
                    break
                _one(box, cfg, state, uid, size, today, budget, result, made)
                fetched += size
            _save_state(state)
    except MailFailure as exc:
        _remember(False, exc.code, result)
        logger.warning("Mailbox: fetching failed reason=%s", exc.code)
        raise
    _remember(True, "", result)
    if result.mails or result.passed or result.skipped or result.flagged or result.deferred or result.dropped:
        logger.info("Mailbox: %s mail(s), %s attachment(s) taken unknown=%s passed=%s skipped=%s flagged=%s "
                    "deferred=%s dropped=%s", result.mails, result.files, result.unknown, result.passed, result.skipped,
                    result.flagged, result.deferred, result.dropped)
    return result


def _one(box: Box, cfg: Config, state: dict[str, Any], uid: int, size: int, today: str, budget: Budget,
         result: Result, made: list[bool]) -> None:
    """One mail. Where fetching stands is written before it is taken apart: a mail that brings the server down is
    tried ``MAX_TRIES`` times in all, never for ever."""
    key = str(uid)
    tries = state["retry"].get(key, 0) + 1
    state["last"] = max(int(state["last"]), uid)
    state["later"].pop(key, None)
    if tries > MAX_TRIES:
        state["retry"].pop(key, None)
        _flag(box, uid)
        result.flagged += 1
        logger.warning("Mailbox: a mail could not be taken after %s tries and was flagged", MAX_TRIES)
        _save_state(state)
        return
    state["retry"][key] = tries
    _save_state(state)
    if size > MAIL_MAX:
        state["retry"].pop(key, None)
        _flag(box, uid)
        result.passed += 1
        result.flagged += 1
        logger.warning("Mailbox: a mail larger than %s MB was left alone and flagged", MAIL_MAX // MB)
        return
    taken = take_mail(_body(box, uid), box=cfg.box, uidvalidity=box.uidvalidity, uid=uid, mailbox=cfg.address,
                      drop_unknown=cfg.drop_unknown, budget=lambda owner, wanted: budget.person_left(owner, wanted),
                      auth_server=cfg.auth_server)
    if taken.error == "too_elaborate":
        state["retry"].pop(key, None)
        result.skipped += 1
        logger.warning("Mailbox: a mail was skipped, taking it apart costs too much")
        return
    if taken.error:
        state["retry"].pop(key, None)
        result.passed += 1
        return
    if taken.deferred:
        state["retry"].pop(key, None)
        state["later"][key] = today
        result.deferred += 1
        logger.warning("Mailbox: a mail waits for the next day, the daily amount of its person is reached")
        return
    if taken.dropped:
        state["retry"].pop(key, None)
        result.dropped += 1
        return
    budget.spend(taken.owner, taken.bytes)
    result.files += taken.files
    result.passed += taken.over
    if taken.files or taken.known:
        result.mails += 1
        result.unknown += 1 if taken.unknown else 0
    if taken.failed:
        # Left where it is; the next run tries the parts that are still missing.
        return
    state["retry"].pop(key, None)
    if taken.whole:
        try:
            _after(box, cfg, uid, made)
        except MailFailure as exc:
            logger.warning("Mailbox: what comes after taking a mail failed reason=%s", exc.code)
    elif taken.over:
        _flag(box, uid)
        result.flagged += 1


@dataclass
class Probe:
    mails: int
    #: What "afterwards" really does on this server (``effective_after``).
    after: str


def probe() -> Probe:
    """The connection test: signed in, the folder looked at (read only); how many mails are new, and what "afterwards"
    can do on this server."""
    if not _lock.acquire(blocking=False):
        raise MailBusy
    try:
        with SessionLocal() as db:
            cfg = config(db)
            stored = settings_service.get(db, "mail_state")
        with session(cfg, readonly=True) as box:
            count = len(_waiting(box, _state(cfg, box, stored)))
            after = effective_after(cfg.after, box.capabilities)
        logger.info("Mailbox: connection test passed")
        return Probe(count, after)
    except MailFailure as exc:
        logger.info("Mailbox: connection test failed reason=%s", exc.code)
        raise
    finally:
        _lock.release()
