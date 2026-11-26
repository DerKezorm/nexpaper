"""The reference service: a stand-in AI provider for the tests, never a real one and never a real key. It speaks the
OpenAI form (``/chat/completions``, ``/models``) and the Messages form (``/messages``, ``/models`` with
``display_name``), each with the peculiarities the module has to deal with, chosen by the model's name:

Models (by name): ``plain`` answers ``Done: <the first words>``; ``thinking`` is a newer OpenAI model, it turns down
``max_tokens`` (naming ``max_completion_tokens``) and ``temperature`` and spends 4,000 on thoughts, so less room gives
an empty answer cut at the length; ``no-think`` is a local model that cannot think and turns ``reasoning_effort`` down
the way Ollama does ("does not support thinking"); ``spend`` always stops at the length with nothing written;
``empty`` answers with nothing; ``fenced`` wraps its answer in a code fence; ``tools`` answers with a tool call;
``fail`` is 500 with its own words; ``busy`` is 429; ``slow`` sends its head, then a byte now and then (only as a real
server: ``serve``); ``huge`` is an answer of 3 MB; ``redirect`` is 307 to ``redirect_to``.

Two faces: ``transport()`` is an ``httpx`` transport (for names on the internet, which the tests resolve to a public
address), ``serve()`` a real server on 127.0.0.1 (sockets, deadline, proxy and redirect as in production). Every
request is kept in ``seen`` (method, path, headers, body, where it came in) for the tests to look at.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx

MODELS = ("plain", "thinking", "no-think", "spend", "empty", "fenced", "tools", "fail", "busy", "slow", "huge",
          "redirect")


@dataclass
class Seen:
    method: str
    path: str
    headers: dict[str, str]
    body: Any
    via: str


@dataclass
class Reply:
    status: int
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    drip: bool = False


def _json(status: int, data: Any) -> Reply:
    return Reply(status, json.dumps(data).encode(), {"content-type": "application/json"})


def _refuse(message: str) -> Reply:
    return _json(400, {"error": {"message": message, "type": "invalid_request_error"}})


class ReferenceService:
    def __init__(self, key: str = "") -> None:
        #: The key the service wants (none: it takes every request, as Ollama does).
        self.key = key
        self.seen: list[Seen] = []
        #: Where the model ``redirect`` sends a request.
        self.redirect_to = "http://192.168.1.1/"
        #: The base address of the real server (``serve``), "" before.
        self.base = ""
        self._server: ThreadingHTTPServer | None = None
        self._lock = threading.Lock()

    # --- What it answers ------------------------------------------------------------------------------------------

    def reply(self, method: str, path: str, headers: dict[str, str], raw: bytes, via: str) -> Reply:
        headers = {name.lower(): value for name, value in headers.items()}
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = None
        with self._lock:
            self.seen.append(Seen(method, path, headers, body, via))
        messages_form = path.endswith("/messages") or any(name.endswith("-version") for name in headers)
        if self.key:
            given = headers.get("x-api-key", "") if messages_form else headers.get("authorization", "")
            if given not in (self.key, f"Bearer {self.key}"):
                return _json(401, {"error": {"message": "invalid key"}})
        if method == "GET" and path.endswith("/models"):
            if messages_form:
                return _json(200, {"data": [{"id": name, "display_name": name.title(), "type": "model"}
                                            for name in MODELS]})
            return _json(200, {"object": "list", "data": [{"id": name, "object": "model"} for name in MODELS]})
        if method != "POST" or not (path.endswith("/chat/completions") or path.endswith("/messages")):
            return _json(404, {"error": {"message": "no such route"}})
        if not isinstance(body, dict):
            return _refuse("not JSON")
        return self._answer(body, messages_form)

    def _answer(self, body: dict[str, Any], messages_form: bool) -> Reply:
        model = str(body.get("model") or "")
        if model == "redirect":
            return Reply(307, b"", {"location": self.redirect_to})
        if model == "fail":
            return _json(500, {"error": {"message": "The service broke down over model fail."}})
        if model == "busy":
            return _json(429, {"error": {"message": "slow down"}})
        if model == "huge":
            # A well-formed answer, only too large: read without a limit it would work.
            big = {"choices": [{"index": 0, "message": {"role": "assistant", "content": "x" * (3 * 1024 * 1024)},
                                "finish_reason": "stop"}]}
            return _json(200, big)
        if model == "slow":
            return Reply(200, b'{"choices": []}' + b" " * 400, {"content-type": "application/json"}, drip=True)
        if model == "thinking" and not messages_form:
            if "max_tokens" in body:
                return _refuse("Unsupported parameter: 'max_tokens' is not supported with this model. Use "
                               "'max_completion_tokens' instead.")
            if "temperature" in body:
                return _refuse("Unsupported value: 'temperature' does not support 0.3 with this model.")
        if model == "no-think" and "reasoning_effort" in body:
            return _refuse('"no-think" does not support thinking')
        user = ""
        for message in body.get("messages") or []:
            if isinstance(message, dict) and message.get("role") == "user":
                user = str(message.get("content") or "")
        words = " ".join(user.split()[:6])
        text, stop = f"Done: {words}", False
        if model == "thinking":
            room = int(body.get("max_completion_tokens") or 0)
            if room < 4_000 + 10:
                text, stop = "", True
        if model == "spend":
            text, stop = "", True
        if model == "empty":
            text = ""
        if model == "fenced":
            text = f"```markdown\n{text}\n```"
        if messages_form:
            content: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
            if model == "tools" and body.get("tools"):
                content = [{"type": "tool_use", "id": "call-1", "name": "find_notes", "input": {"q": "x"}}]
            return _json(200, {"type": "message", "content": content,
                               "stop_reason": "max_tokens" if stop else "end_turn"})
        message: dict[str, Any] = {"role": "assistant", "content": text}
        if model == "tools" and body.get("tools"):
            message = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call-1", "type": "function", "function": {"name": "find_notes", "arguments": '{"q": "x"}'}}]}
        return _json(200, {"choices": [{"index": 0, "message": message,
                                        "finish_reason": "length" if stop else "stop"}]})

    # --- As an httpx transport ------------------------------------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            raw = request.read()
            found = self.reply(request.method, request.url.path, dict(request.headers), raw,
                               f"{request.url.host}:{request.url.port or 443}")
            return httpx.Response(found.status, headers=found.headers, content=found.body)

        return httpx.MockTransport(handle)

    # --- As a real server on 127.0.0.1 ----------------------------------------------------------------------------

    def serve(self) -> str:
        """Starts a server on 127.0.0.1 and returns its base address (``http://127.0.0.1:<port>/v1/``)."""
        service = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # quiet
                return None

            def _do(self) -> None:
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length) if length else b""
                found = service.reply(self.command, self.path.split("?")[0], dict(self.headers.items()), raw,
                                      f"{self.client_address[0]}")
                self.send_response(found.status)
                for name, value in found.headers.items():
                    self.send_header(name, value)
                self.send_header("content-length", str(len(found.body)))
                self.end_headers()
                try:
                    if found.drip:
                        for index in range(len(found.body)):
                            self.wfile.write(found.body[index:index + 1])
                            self.wfile.flush()
                            time.sleep(0.2)
                    else:
                        self.wfile.write(found.body)
                except (BrokenPipeError, ConnectionResetError):
                    return

            do_GET = _do  # noqa: N815 (http.server's names)
            do_POST = _do  # noqa: N815

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self._server.server_address[1]}/v1/"
        return self.base

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


class Recorder:
    """A server that only counts what reaches it: a proxy from the environment, or the target of a redirect."""

    def __init__(self) -> None:
        self.hits: list[str] = []
        recorder = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                return None

            def _do(self) -> None:
                recorder.hits.append(f"{self.command} {self.path}")
                self.send_response(200)
                self.send_header("content-length", "2")
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            do_GET = _do  # noqa: N815
            do_POST = _do  # noqa: N815
            do_CONNECT = _do  # noqa: N815

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self.address = f"http://127.0.0.1:{self._server.server_address[1]}/"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
