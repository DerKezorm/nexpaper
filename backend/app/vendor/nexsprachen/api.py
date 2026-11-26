"""The routes of the card Server › General › Languages and of the language menus, in the form nexnotes has them under
``/api/locales``:

``GET    <prefix>``            the languages: built in and the operator's own (``code``, ``name``, ``keys``,
                              ``built_in``, ``own``); readable without signing in unless the app says otherwise
``GET    <prefix>/template``   the template to translate (the app's English texts with ``_meta``), as a file
``GET    <prefix>/{code}``     the texts of one of the operator's files, nothing else (no ``_meta``)
``PUT    <prefix>/{code}``     add or replace a language (operator); the body is the JSON file itself, at most 512 KB
``DELETE <prefix>/{code}``     remove one (operator)

The app mounts them with ``app.include_router(nexsprachen.api.router(operator=<its dependency>))``. ``operator`` is
the app's own check (401 without a session, 403 for a member). ``reader`` is None (anybody may read: the sign-in page
is shown in the chosen language too, and the texts are the same for everybody) or the app's dependency for reading.
``error(code, message, status, values)`` makes the app's own form of a refusal; by default an ``HTTPException`` with
``{"code", "message", …values}`` as ``detail`` (nexnotes' form). No refusal names a path, a file name or what the
parser said.

The only part of the module that needs FastAPI; the rest is the standard library."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import store
from .config import current
from .errors import CODES, LocaleError, SaveError

#: Lists and texts change with every upload; a browser asks again instead of keeping an old answer.
NO_CACHE = {"Cache-Control": "no-cache"}

MESSAGES = {
    "not_found": "Not found.",
    "locale_unusable": "This language file cannot be used.",
    "too_large": "The file is too large.",
    "locale_not_saved": "The language file could not be saved.",
}


class LanguageEntry(BaseModel):
    code: str
    name: str
    #: Texts in the operator's file (0 for a built-in language without one).
    keys: int
    built_in: bool = False
    #: The operator added a file (a further language, or one over a built-in language).
    own: bool = False


class LocaleEntry(BaseModel):
    code: str
    name: str
    keys: int


Refuse = Callable[[str, str, int, dict[str, Any]], Exception]


def _refuse(code: str, message: str, status: int, values: dict[str, Any]) -> Exception:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **values})


def router(
    *,
    operator: Callable[..., Any],
    reader: Callable[..., Any] | None = None,
    prefix: str = "/api/locales",
    error: Refuse | None = None,
    tags: list[str] | None = None,
) -> APIRouter:
    """The routes. ``operator``: the app's dependency for operators. ``reader``: None (anybody reads list, texts and
    template) or the app's dependency for reading. ``error(code, message, status, values)``: the app's own form of a
    refusal."""
    make = error or _refuse

    def refuse(code: str, values: dict[str, Any] | None = None, message: str | None = None) -> Exception:
        return make(code, message or MESSAGES[code], CODES[code], dict(values or {}))

    readers = [Depends(reader)] if reader is not None else []
    operators = [Depends(operator)]
    routes = APIRouter(prefix=prefix, tags=tags or ["locales"])

    @routes.get("", response_model=list[LanguageEntry], summary="The languages: built in and added",
                dependencies=readers)
    def list_languages(response: Response) -> list[store.Language]:
        response.headers.update(NO_CACHE)
        return store.languages()

    @routes.get("/template", summary="The template to translate", dependencies=readers, response_model=None)
    def download_template() -> Response:
        texts = store.template()
        if texts is None:
            raise refuse("not_found")
        return Response(
            content=json.dumps(texts, ensure_ascii=False, indent=2) + "\n",
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{current().app_name}-language-template.json"'},
        )

    @routes.get("/{code}", summary="The texts of one added language", dependencies=readers, response_model=None)
    def read_language(code: str) -> JSONResponse:
        try:
            texts = store.load(code)
        except FileNotFoundError as exc:
            raise refuse("not_found") from exc
        except LocaleError as exc:
            if exc.reason == "code":
                raise refuse("not_found") from exc
            raise refuse("locale_unusable") from exc
        except OSError as exc:
            raise refuse("locale_unusable") from exc
        return JSONResponse(texts, headers=NO_CACHE)

    @routes.put("/{code}", response_model=LocaleEntry, summary="Add or replace a language (operator)",
                dependencies=operators)
    async def upload_language(code: str, request: Request) -> store.Locale:
        """The body is the JSON file itself, at most 512 KB. Checked whole before anything is written."""
        limit = {"max_kb": store.MAX_BYTES // 1024, "max_mb": round(store.MAX_BYTES / 1024**2, 1)}
        if not store.valid_code(code):
            raise refuse("locale_unusable", {"reason": "code"}, _unusable("code"))
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > store.MAX_BYTES:
            raise refuse("too_large", limit)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > store.MAX_BYTES:
                raise refuse("too_large", limit)
        try:
            return store.save(code, bytes(raw))
        except LocaleError as exc:
            if exc.reason == "too_large":
                raise refuse("too_large", limit) from exc
            raise refuse("locale_unusable", {"reason": exc.reason}, _unusable(exc.reason)) from exc
        except SaveError as exc:
            raise refuse("locale_not_saved") from exc

    @routes.delete("/{code}", status_code=204, summary="Remove an added language (operator)", dependencies=operators)
    def remove_language(code: str) -> None:
        if not store.remove(code):
            raise refuse("not_found")

    return routes


def _unusable(reason: str) -> str:
    return f"This language file cannot be used: {LocaleError(reason)}."
