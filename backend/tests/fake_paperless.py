"""A made-up Paperless-ngx for the tests of the import: a small HTTP server that answers the routes the import uses, with
documents, pages of lists, errors, slow and hostile answers as a test asks. Everything in it is invented (Stadtwerke
Lindenau, jule, tom); the token is made when the server starts."""

from __future__ import annotations

import json
import re
import secrets
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

#: The ports of this block's test helpers; another free one is taken when all are busy.
PORTS = range(18645, 18658)


@dataclass
class Doc:
    id: int
    title: str
    original: bytes
    archive: bytes | None = None
    content: str = ""
    created: str = "2026-03-14"
    correspondent: int | None = None
    document_type: int | None = None
    tags: list[int] = field(default_factory=list)
    owner: int | None = None
    notes: list[dict[str, Any]] = field(default_factory=list)
    custom_fields: list[dict[str, Any]] = field(default_factory=list)
    permissions: dict[str, Any] = field(default_factory=lambda: {"view": {"users": [], "groups": []},
                                                                 "change": {"users": [], "groups": []}})
    original_file_name: str = "scan.pdf"
    asn: int | None = None

    def detail(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "content": self.content, "created": self.created + "T00:00:00+01:00",
            "created_date": self.created, "correspondent": self.correspondent, "document_type": self.document_type,
            "storage_path": None, "tags": self.tags, "owner": self.owner, "notes": self.notes,
            "custom_fields": self.custom_fields, "permissions": self.permissions,
            "original_file_name": self.original_file_name,
            "archived_file_name": "archive.pdf" if self.archive is not None else None,
            "archive_serial_number": self.asn, "added": "2026-03-15T08:00:00Z",
        }


class Paperless:
    """What the server holds, and how it misbehaves. ``hooks`` maps a path (a regular expression) to a function that may
    answer instead: it gets the handler and returns True when it answered."""

    def __init__(self) -> None:
        self.token = secrets.token_hex(20)
        self.api_version = 7
        self.version = "2.14.7"
        self.documents: dict[int, Doc] = {}
        self.tags: dict[int, dict[str, Any]] = {}
        self.correspondents: dict[int, str] = {}
        self.types: dict[int, str] = {}
        self.users: dict[int, dict[str, Any]] = {}
        self.fields: dict[int, dict[str, Any]] = {}
        self.users_forbidden = False
        self.hooks: list[tuple[re.Pattern[str], Callable[[Handler], bool]]] = []
        self.requests: list[str] = []
        self.next_url = ""
        self.lock = threading.Lock()

    def hook(self, pattern: str, answer: Callable[[Handler], bool]) -> None:
        self.hooks.append((re.compile(pattern), answer))

    def add(self, doc: Doc) -> Doc:
        self.documents[doc.id] = doc
        return doc


class Handler(BaseHTTPRequestHandler):
    server: Server

    def log_message(self, *_args: Any) -> None:
        pass

    def send_json(self, data: Any, status: int = 200, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        paperless = self.server.paperless
        if paperless.api_version:
            self.send_header("X-Api-Version", str(paperless.api_version))
            self.send_header("X-Version", paperless.version)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, data: bytes, kind: str = "application/pdf") -> None:
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def page(self, items: list[dict[str, Any]], query: dict[str, list[str]]) -> None:
        size = int(query.get("page_size", ["25"])[0])
        number = int(query.get("page", ["1"])[0])
        chunk = items[(number - 1) * size : number * size]
        more = number * size < len(items)
        paperless = self.server.paperless
        following = paperless.next_url or f"http://{self.headers.get('Host')}{self.path}&page={number + 1}"
        self.send_json({"count": len(items), "next": following if more else None, "previous": None,
                        "all": [item.get("id") for item in items], "results": chunk})

    def do_GET(self) -> None:
        paperless = self.server.paperless
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        with paperless.lock:
            paperless.requests.append(self.path)
        for pattern, answer in paperless.hooks:
            if pattern.search(path) and answer(self):
                return
        if self.headers.get("Authorization") != f"Token {paperless.token}":
            self.send_json({"detail": "Invalid token."}, 401)
            return
        if path == "/api/documents/":
            docs = [paperless.documents[key] for key in sorted(paperless.documents)]
            wanted = (query.get("fields") or [""])[0].split(",")
            rows = [{k: v for k, v in d.detail().items() if not wanted[0] or k in wanted} for d in docs]
            self.page(rows, query)
            return
        found = re.fullmatch(r"/api/documents/(\d+)/", path)
        if found:
            doc = paperless.documents.get(int(found.group(1)))
            if doc is None:
                self.send_json({"detail": "Not found."}, 404)
                return
            shown = doc.detail()
            # As Paperless-ngx 2.14.7 answers: the permissions only with ``full_perms=true``, else whether one may change.
            if query.get("full_perms", ["false"])[0] != "true":
                shown.pop("permissions")
                shown["user_can_change"] = True
            self.send_json(shown)
            return
        found = re.fullmatch(r"/api/documents/(\d+)/download/", path)
        if found:
            doc = paperless.documents.get(int(found.group(1)))
            if doc is None:
                self.send_json({"detail": "Not found."}, 404)
                return
            original = query.get("original", ["false"])[0] == "true"
            self.send_bytes(doc.original if original or doc.archive is None else doc.archive)
            return
        lists: dict[str, list[dict[str, Any]]] = {
            "/api/tags/": [{"id": k, **v} for k, v in sorted(paperless.tags.items())],
            "/api/correspondents/": [{"id": k, "name": v} for k, v in sorted(paperless.correspondents.items())],
            "/api/document_types/": [{"id": k, "name": v} for k, v in sorted(paperless.types.items())],
            "/api/custom_fields/": [{"id": k, **v} for k, v in sorted(paperless.fields.items())],
            "/api/users/": [{"id": k, **v} for k, v in sorted(paperless.users.items())],
        }
        if path == "/api/users/" and paperless.users_forbidden:
            self.send_json({"detail": "You do not have permission."}, 403)
            return
        if path in lists:
            self.page(lists[path], query)
            return
        self.send_json({"detail": "Not found."}, 404)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, paperless: Paperless) -> None:
        self.paperless = paperless
        last: OSError | None = None
        for port in [*PORTS, 0]:
            try:
                super().__init__(("127.0.0.1", port), Handler)
                return
            except OSError as exc:
                last = exc
        raise RuntimeError("no free port") from last

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/"


def start(paperless: Paperless) -> Server:
    server = Server(paperless)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def stop(server: Server) -> None:
    server.shutdown()
    server.server_close()


def dribble(handler: Handler, seconds: float = 0.4, pieces: int = 30) -> bool:
    """An answer that comes a byte now and then: the deadline must end it."""
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("X-Api-Version", "7")
    handler.end_headers()
    try:
        for _ in range(pieces):
            handler.wfile.write(b" ")
            handler.wfile.flush()
            time.sleep(seconds)
    except OSError:
        pass
    return True


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
