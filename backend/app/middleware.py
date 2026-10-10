"""Request id, timing and security headers for every request."""

from __future__ import annotations

import json
import logging
import re
import secrets
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from .services import limits, logs, pictures

logger = logging.getLogger("nexpaper.api")


def _database_busy(exc: BaseException) -> bool:
    """SQLite's "database is locked" (or "busy"), however deep in the chain of causes."""
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, sqlite3.OperationalError) and ("locked" in str(seen) or "busy" in str(seen)):
            return True
        # SQLAlchemy keeps the driver's error as ``orig`` (and as the cause, when it raised it itself).
        seen = getattr(seen, "orig", None) or seen.__cause__ or seen.__context__
    return False


#: Paths whose calls explain nothing but fill the log.
QUIET_PATHS = ("/api/v1/health", "/api/v1/logs")
SLOW_MS = 3000
#: What takes long by nature: backups grow with the diaries.
SLOW_EXPECTED = ("/api/v1/backups",)

#: The interface sets inline styles, hence 'unsafe-inline' for styles only. Scripts stay strict.
#: ``blob:`` for images: a picture is shown before it is uploaded. The service worker (``/sw.js``, Web Push) and the
#: manifest come from the site itself, said out loud: a ``worker-src 'none'`` here once broke Web Push in Nexview.
CSP = (
    b"default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
    b"connect-src 'self'; worker-src 'self'; manifest-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
    b"form-action 'self'; object-src 'none'"
)
SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"content-security-policy", CSP),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
    (b"x-frame-options", b"DENY"),
    # The camera for this site only: the scan page (``/kamera``) photographs documents. Nothing else, no other site.
    (b"permissions-policy", b"camera=(self), microphone=(), geolocation=()"),
)
#: The worker that finds the edges of a page in a photo (``/scanner/worker.js``): OpenCV runs there as WebAssembly,
#: and its bindings make functions at run time. The policy of a worker is the one its own script arrives with, so only
#: this worker gets ``'unsafe-eval'``: it sees pixels of the camera and nothing else, no page, no cookie, no answer of
#: the API. The page itself keeps the strict policy above.
SCANNER_WORKER = "/scanner/worker.js"
SCANNER_CSP = (
    b"default-src 'self'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; connect-src 'self'; img-src 'none'; "
    b"style-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'"
)


class RequestContextMiddleware:
    """Pure ASGI, so streaming responses and WebSockets are not buffered."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        request_id = secrets.token_hex(3)
        scope.setdefault("state", {})["request_id"] = request_id
        token = logs.bind_request(request_id)
        start = time.perf_counter()
        status = 0
        path = scope.get("path", "?")

        async def send_wrapper(message: dict) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = message.setdefault("headers", [])
                headers.append((b"x-request-id", request_id.encode("ascii")))
                # A response that brings its own policy keeps it; every other gets the app's.
                present = {name.lower() for name, _value in headers}
                if path == SCANNER_WORKER and b"content-security-policy" not in present:
                    headers.append((b"content-security-policy", SCANNER_CSP))
                    present.add(b"content-security-policy")
                headers.extend(header for header in SECURITY_HEADERS if header[0] not in present)
                # What the API answers is private: kept by no browser and no proxy, unless a route says otherwise
                # (the profile pictures, under addresses that change with them).
                if path.startswith("/api/") and b"cache-control" not in present:
                    headers.append((b"cache-control", b"no-store"))
            await send(message)

        method = scope.get("method", "WS")
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            duration = (time.perf_counter() - start) * 1000
            logger.exception("Unhandled error on %s %s after %dms", method, path, duration)
            raise
        else:
            if scope["type"] != "http":
                return
            duration = (time.perf_counter() - start) * 1000
            if status >= 500:
                logger.error("%s %s -> %s in %dms", method, path, status, duration)
            elif duration >= SLOW_MS and not path.startswith(QUIET_PATHS + SLOW_EXPECTED):
                logger.warning("Slow request: %s %s -> %s in %dms", method, path, status, duration)
            elif not path.startswith(QUIET_PATHS):
                logger.debug("%s %s -> %s in %dms", method, path, status, duration)
        finally:
            logs.unbind_request(token)


#: Methods that change something. They must name their browser tab (see ``GuardMiddleware``).
CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CLIENT_HEADER = b"x-nexpaper-client"
CLIENT_PATTERN = re.compile(rb"^[A-Za-z0-9_-]{8,64}$")
#: Largest body an ordinary request may carry.
MAX_BODY = 16 * 1024 * 1024
#: Where another limit holds, checked while streaming: a backup brought in from elsewhere, and every route that takes
#: a picture, whose decoder says the same number (``pictures.MAX_BYTES``).
LARGE_BODIES = {
    "/api/v1/backups/upload": 64 * 1024**3,
    "/api/v1/auth/avatar": pictures.MAX_BYTES,
}
#: The upload of documents: the browser's multipart request (a few files, each at most the operator's limit, read anew
#: for every request) and one piece of a piece-by-piece upload (``PUT /api/v1/uploads/<id>``).
UPLOAD_PIECE = re.compile(r"^/api/v1/uploads/[0-9a-f]{32}$")


def body_limit(method: str, path: str) -> int:
    if path in LARGE_BODIES:
        return LARGE_BODIES[path]
    if method == "POST" and path == "/api/v1/documents":
        return limits.request_limit()
    if method == "PUT" and UPLOAD_PIECE.match(path):
        return limits.MAX_PIECE + limits.MB
    return MAX_BODY


def _too_large(limit: int) -> tuple[dict, dict]:
    return _refuse(413, "too_large", "The request is too large.", max_mb=limit // (1024 * 1024))


class BodyTooLarge(Exception):
    pass


def _refuse(status: int, code: str, text: str, **values: object) -> tuple[dict, dict]:
    body = json.dumps({"detail": {"code": code, "message": text, **values}}).encode()
    start = {
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    }
    return start, {"type": "http.response.body", "body": body}


#: The start of a device token and of an API key (``services.devices.TOKEN_PREFIX``, ``services.apikeys.KEY_PREFIX``;
#: a test keeps the two in step).
TOKEN_STARTS = (b"npd_", b"npk_")


#: Routes a program calls without a browser and without a token yet: a device trades a pairing code, an app trades the
#: code of OAuth for its token. Neither reads a cookie, so a page on another site gains nothing by sending a browser
#: there; they need no tab header (a native app has no tab).
PROGRAM_PATHS = frozenset({"/api/v1/devices/pair", "/api/v1/oauth/token"})


def _carries_token(value: bytes) -> bool:
    return value[:7].lower() == b"bearer " and value[7:].startswith(TOKEN_STARTS)


def _is_browser(cookies: bytes) -> bool:
    """Whether the request carries a cookie of nexpaper (all start with ``nexpaper_``): the session, a sign-in step, the
    invitation or provider run. Such a request is a browser's, whatever else it says."""
    return b"nexpaper_" in cookies


class GuardMiddleware:
    """Two walls in front of every route, including routes still to come.

    * **A change must name its tab** in ``X-Nexpaper-Client``. A page on another site can make a browser
      send a form, but not a request with a header of its own (that needs CORS, which nexpaper does not allow): so
      the header is the wall against cross-site requests too. A program with ``Authorization: Bearer npd_...`` (or
      ``npk_...``) and no cookie of ours needs no tab: it speaks for a token, not for a cookie.
    * **A body has a size limit** before anything reads it: the declared length is checked first, and a body sent
      without one is counted while it arrives.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        # A request with one of our tokens in ``Authorization`` and no cookie of ours is a program's, judged by the
        # token alone (``deps.require_account``). Any other ``Authorization`` header (Basic, a made-up token) does not
        # stand in for the tab header, and neither does a token next to a cookie: a made-up one would take the wall
        # away from a request the cookie answers (log out, sign-in steps, accepting an invitation).
        exempt = (_carries_token(headers.get(b"authorization", b"")) and not _is_browser(headers.get(b"cookie", b""))
                  ) or scope["path"] in PROGRAM_PATHS
        if scope.get("method") in CHANGING and not exempt and not CLIENT_PATTERN.match(headers.get(CLIENT_HEADER, b"")):
            for message in _refuse(400, "client_required", "Changes need the header X-Nexpaper-Client."):
                await send(message)
            return
        limit = body_limit(scope.get("method", "GET"), scope["path"])
        declared = headers.get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > limit):
            for message in _too_large(limit):
                await send(message)
            return
        received = 0
        overflow = False

        async def counting_receive() -> dict:
            nonlocal received, overflow
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    overflow = True
                    raise BodyTooLarge
            return message

        started = False

        async def tracking_send(message: dict) -> None:
            nonlocal started
            # The framework turns the aborted read into an answer of its own (400); the caller gets the true one.
            if overflow:
                if message["type"] == "http.response.start" and not started:
                    started = True
                    for refusal in _too_large(limit):
                        await send(refusal)
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except BodyTooLarge:
            if not started:
                for message in _too_large(limit):
                    await send(message)


async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or "-"
    if _database_busy(exc):
        # The database stayed busy past the wait (SQLite's busy timeout): a moment later it works. The browser gets
        # something to say and to retry instead of "went wrong".
        return JSONResponse(
            status_code=503,
            content={"detail": {"code": "busy", "message": "nexpaper is busy. Try again in a moment.",
                                "request_id": request_id}},
            headers={"X-Request-Id": request_id, "Retry-After": "2"},
        )
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "code": "internal_error",
                "message": f"Something went wrong on the server. Request id: {request_id}",
                "request_id": request_id,
            }
        },
        headers={"X-Request-Id": request_id},
    )
