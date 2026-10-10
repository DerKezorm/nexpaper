"""A small IMAP server for the tests, in this process: enough of IMAP4rev1 for nexpaper's mailbox (CAPABILITY, STARTTLS,
LOGIN, SELECT, EXAMINE, UID SEARCH, UID FETCH, UID STORE, UID COPY, UID MOVE, UID EXPUNGE, EXPUNGE, CREATE, LOGOUT).

It holds folders of made-up mails in memory, can speak TLS from the first byte or after STARTTLS with a certificate made
for the test run, and can be told to misbehave (stall, refuse the login, claim a huge literal)."""

from __future__ import annotations

import datetime
import ipaddress
import re
import socket
import socketserver
import ssl
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

#: The ports of this block's test helpers; another free one is taken when all are busy.
PORTS = range(18645, 18658)


def make_certificate(folder: Path) -> tuple[Path, Path]:
    """A self-signed certificate for 127.0.0.1 and localhost, made for this run (never a key in the repository)."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                                                    x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = folder / "imap-cert.pem", folder / "imap-key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return cert_path, key_path


@dataclass
class Mail:
    uid: int
    data: bytes
    flags: set[str] = field(default_factory=set)


@dataclass
class Folder:
    validity: int = 1000
    next_uid: int = 1
    mails: list[Mail] = field(default_factory=list)

    def add(self, data: bytes, flags: set[str] | None = None) -> int:
        uid = self.next_uid
        self.next_uid += 1
        self.mails.append(Mail(uid, data, set(flags or ())))
        return uid


class Store:
    """What the server holds and how it behaves; the tests change it between runs."""

    def __init__(self) -> None:
        self.user = "paper@example.com"
        self.password = ""
        self.folders: dict[str, Folder] = {"INBOX": Folder()}
        self.lock = threading.Lock()
        self.capabilities = ["IMAP4rev1", "UIDPLUS", "MOVE"]
        #: Seconds to wait before the greeting (a server that hangs).
        self.stall = 0.0
        #: A literal the server claims for every body, larger than what it sends (a server that lies).
        self.huge_literal = 0
        self.logins: list[str] = []
        self.commands: list[str] = []
        self.connections = 0

    def inbox(self) -> Folder:
        return self.folders["INBOX"]


_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|(\S+)')


def _words(text: str) -> list[str]:
    out = []
    for quoted, plain in _TOKEN.findall(text):
        out.append(re.sub(r"\\(.)", r"\1", quoted) if quoted or plain == "" else plain)
    return out


def _uid_set(spec: str, folder: Folder) -> list[Mail]:
    highest = max((mail.uid for mail in folder.mails), default=0)
    wanted: set[int] = set()
    for piece in spec.split(","):
        if ":" in piece:
            low, high = piece.split(":", 1)
            a = highest if low == "*" else int(low)
            b = highest if high == "*" else int(high)
            if a > b:
                a, b = b, a
            # "n:*" always names the last mail, even when its UID is lower than n (RFC 3501).
            wanted.update(range(a, b + 1))
            if high == "*" and folder.mails:
                wanted.add(highest)
        elif piece == "*":
            wanted.add(highest)
        elif piece:
            wanted.add(int(piece))
    return [mail for mail in folder.mails if mail.uid in wanted]


class Handler(socketserver.StreamRequestHandler):
    server: Server

    def setup(self) -> None:
        if self.server.implicit_tls:
            self.request = self.server.tls.wrap_socket(self.request, server_side=True)
        super().setup()
        self.selected: Folder | None = None
        self.readonly = False
        self.tls_on = self.server.implicit_tls

    def send(self, text: str | bytes) -> None:
        self.wfile.write(text if isinstance(text, bytes) else text.encode("utf-8"))
        self.wfile.flush()

    def caps(self) -> str:
        found = list(self.server.store.capabilities)
        if self.server.starttls and not self.tls_on:
            found.append("STARTTLS")
        return " ".join(found)

    def handle(self) -> None:
        store = self.server.store
        with store.lock:
            store.connections += 1
        if store.stall:
            time.sleep(store.stall)
        self.send(f"* OK [CAPABILITY {self.caps()}] test server ready\r\n")
        while True:
            try:
                line = self.rfile.readline(1_000_000)
            except (OSError, ssl.SSLError):
                return
            if not line:
                return
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            tag, _, rest = text.partition(" ")
            command, _, args = rest.partition(" ")
            command = command.upper()
            with store.lock:
                store.commands.append(command if command != "UID" else "UID " + args.split(" ", 1)[0].upper())
            try:
                if not self.dispatch(tag, command, args):
                    return
            except (OSError, ssl.SSLError):
                return
            except Exception as exc:  # noqa: BLE001 - a broken command is a BAD, as on a real server
                self.send(f"{tag} BAD {type(exc).__name__}\r\n")

    def dispatch(self, tag: str, command: str, args: str) -> bool:
        store = self.server.store
        if command == "CAPABILITY":
            self.send(f"* CAPABILITY {self.caps()}\r\n{tag} OK done\r\n")
        elif command == "STARTTLS":
            self.send(f"{tag} OK begin TLS\r\n")
            self.request = self.server.tls.wrap_socket(self.request, server_side=True)
            self.rfile = self.request.makefile("rb")
            self.wfile = self.request.makefile("wb")
            self.tls_on = True
        elif command == "LOGIN":
            words = _words(args)
            with store.lock:
                store.logins.append(words[0] if words else "")
            if len(words) == 2 and words[0] == store.user and words[1] == store.password:
                self.send(f"{tag} OK logged in\r\n")
            else:
                self.send(f"{tag} NO [AUTHENTICATIONFAILED] wrong\r\n")
        elif command in ("SELECT", "EXAMINE"):
            name = _words(args)[0]
            folder = store.folders.get(name)
            if folder is None:
                self.send(f"{tag} NO no such folder\r\n")
            else:
                self.selected, self.readonly = folder, command == "EXAMINE"
                self.send(f"* {len(folder.mails)} EXISTS\r\n* 0 RECENT\r\n* OK [UIDVALIDITY {folder.validity}] ok\r\n"
                          f"* OK [UIDNEXT {folder.next_uid}] ok\r\n{tag} OK [READ-WRITE] done\r\n")
        elif command == "CREATE":
            name = _words(args)[0]
            with store.lock:
                if name in store.folders:
                    self.send(f"{tag} NO [ALREADYEXISTS] there\r\n")
                else:
                    store.folders[name] = Folder(validity=2000)
                    self.send(f"{tag} OK created\r\n")
        elif command == "UID":
            self.uid(tag, args)
        elif command == "EXPUNGE":
            self.expunge(tag, None)
        elif command == "NOOP":
            self.send(f"{tag} OK done\r\n")
        elif command == "LOGOUT":
            self.send(f"* BYE bye\r\n{tag} OK done\r\n")
            return False
        else:
            self.send(f"{tag} BAD unknown\r\n")
        return True

    def number(self, mail: Mail) -> int:
        assert self.selected is not None
        return self.selected.mails.index(mail) + 1

    def uid(self, tag: str, args: str) -> None:
        store = self.server.store
        folder = self.selected
        assert folder is not None
        sub, _, rest = args.partition(" ")
        sub = sub.upper()
        with store.lock:
            if sub == "SEARCH":
                words = rest.upper().split()
                found = list(folder.mails)
                index = 0
                while index < len(words):
                    word = words[index]
                    if word == "UNSEEN":
                        found = [m for m in found if "\\Seen" not in m.flags]
                    elif word == "UID":
                        index += 1
                        chosen = {m.uid for m in _uid_set(words[index], folder)}
                        found = [m for m in found if m.uid in chosen]
                    index += 1
                self.send(f"* SEARCH {' '.join(str(m.uid) for m in found)}\r\n{tag} OK done\r\n")
            elif sub == "FETCH":
                spec, _, what = rest.partition(" ")
                for mail in _uid_set(spec, folder):
                    if "BODY.PEEK[]" in what.upper():
                        claimed = store.huge_literal or len(mail.data)
                        self.send(f"* {self.number(mail)} FETCH (UID {mail.uid} BODY[] {{{claimed}}}\r\n".encode()
                                  + mail.data + b")\r\n")
                    else:
                        self.send(f"* {self.number(mail)} FETCH (UID {mail.uid} RFC822.SIZE {len(mail.data)})\r\n")
                self.send(f"{tag} OK done\r\n")
            elif sub == "STORE":
                spec, _, change = rest.partition(" ")
                flags = set(re.findall(r"\\\w+", change))
                for mail in _uid_set(spec, folder):
                    mail.flags |= flags
                    self.send(f"* {self.number(mail)} FETCH (UID {mail.uid} FLAGS ({' '.join(sorted(mail.flags))}))\r\n")
                self.send(f"{tag} OK done\r\n")
            elif sub in ("COPY", "MOVE"):
                spec, _, target = rest.partition(" ")
                name = _words(target)[0]
                if name not in store.folders:
                    self.send(f"{tag} NO [TRYCREATE] no such folder\r\n")
                    return
                for mail in _uid_set(spec, folder):
                    store.folders[name].add(mail.data)
                    if sub == "MOVE":
                        folder.mails.remove(mail)
                self.send(f"{tag} OK done\r\n")
            elif sub == "EXPUNGE":
                self._expunge({m.uid for m in _uid_set(rest.strip(), folder)})
                self.send(f"{tag} OK done\r\n")
            else:
                self.send(f"{tag} BAD unknown\r\n")

    def _expunge(self, only: set[int] | None) -> None:
        folder = self.selected
        assert folder is not None
        folder.mails = [m for m in folder.mails if not ("\\Deleted" in m.flags and (only is None or m.uid in only))]

    def expunge(self, tag: str, only: set[int] | None) -> None:
        with self.server.store.lock:
            self._expunge(only)
        self.send(f"{tag} OK done\r\n")


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, store: Store, tls: ssl.SSLContext, implicit_tls: bool, starttls: bool) -> None:
        self.store, self.tls, self.implicit_tls, self.starttls = store, tls, implicit_tls, starttls
        last: OSError | None = None
        for port in [*PORTS, 0]:
            try:
                super().__init__(("127.0.0.1", port), Handler)
                break
            except OSError as exc:
                last = exc
        else:  # pragma: no cover
            raise last or OSError("no port")

    @property
    def port(self) -> int:
        return int(self.server_address[1])


def start(store: Store, cert: tuple[Path, Path], implicit_tls: bool = True, starttls: bool = False) -> Server:
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(str(cert[0]), str(cert[1]))
    server = Server(store, tls, implicit_tls, starttls)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server


def stop(server: Server) -> None:
    server.shutdown()
    server.server_close()


def refused_port() -> tuple[socket.socket, int]:
    """A port where nobody listens, held for the caller: bound but not listening, so a connection is refused, and no
    other process (another test run on this machine) can start a server there meanwhile. Closing a listener and
    hoping the port stays empty was not enough: a parallel run with the same ports took it in between."""
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    return holder, int(holder.getsockname()[1])


def silent_port() -> tuple[socket.socket, int]:
    """A port that accepts and never says a word (a server that hangs before its greeting)."""
    listener = socket.socket()
    for port in [*PORTS, 0]:
        try:
            listener.bind(("127.0.0.1", port))
            break
        except OSError:
            continue
    listener.listen(5)
    return listener, int(listener.getsockname()[1])
