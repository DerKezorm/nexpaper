"""The request and the account a line belongs to: ``[<request> u:<account>]`` in every line written while a request
runs. The app's middleware binds a request number (``bind_request``), its sign-in sets who acts (``set_actor``); so the
log says who did what, and a click on a number on the page shows every line of that request.

The context is a *mutable* dict in the ContextVar: FastAPI runs sync dependencies in a thread pool with a copy of the
context, and a value set there would be gone afterwards. The dict is shared."""

from __future__ import annotations

import secrets
from contextvars import ContextVar, Token

_context: ContextVar[dict[str, str | None] | None] = ContextVar("nexlog_context", default=None)


def new_request_id() -> str:
    """Six hex characters, as nexnotes numbers its requests (nexmail had eight; both read the same)."""
    return secrets.token_hex(3)


def bind_request(request_id: str) -> Token:
    return _context.set({"rid": request_id, "actor": None})


def unbind_request(token: Token) -> None:
    _context.reset(token)


def set_actor(name: str | None) -> None:
    """Who acts in this request (the account's username); no-op outside a request."""
    data = _context.get()
    if data is not None:
        data["actor"] = name


def current_request_id() -> str | None:
    data = _context.get()
    return data.get("rid") if data else None


def current_actor() -> str | None:
    data = _context.get()
    return data.get("actor") if data else None


def ctx_text() -> str:
    """What stands between the brackets: ``<request>``, ``<request> u:<account>``, ``u:<account>`` or ``-``."""
    data = _context.get() or {}
    parts = [value for value in (data.get("rid"),) if value]
    actor = data.get("actor")
    if actor:
        # One word that never closes the bracket: a space would split it into a second request number.
        parts.append("u:" + "_".join(str(actor).replace("]", ")").split()))
    return " ".join(parts) or "-"
