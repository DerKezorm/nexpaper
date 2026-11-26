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

The description of the interface (``/openapi.json``) stays an app's own where it had one: ``operation_ids`` and
``summaries`` (by the module's name of a route: ``list``, ``template``, ``read``, ``upload``, ``remove``) and
``schema_names`` (``LanguageEntry`` for the list's entries, ``LocaleEntry`` for the answer of an upload) give the names
the app's routes had before (nexpaper: ``list_locales_api_v1_locales_get``, ``LocaleEntry``). One name for both schemas
makes one schema (the list's, the upload answering only its three fields). Without them the names every app had
before the module stand (E53): ``list_locales_<path>_get`` …, the list's summary „Languages the operator added“, one
schema ``LocaleEntry``. A schema name may be a dotted place and name (``app.routers.locales.LocaleEntry``) for an app
whose old name FastAPI had written long (``app__routers__locales__LocaleEntry``). An app
that mounts the routes under two prefixes gives ``operation_ids`` to one of them and the same ``schema_names`` to
both.

The only part of the module that needs FastAPI; the rest is the standard library."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, create_model

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


#: The module's names of its routes, for ``operation_ids`` and ``summaries``.
ROUTES = ("list", "template", "read", "upload", "remove")
#: The module's names of its schemas, for ``schema_names``: the entries of the list and the answer of an upload.
SCHEMAS = ("LanguageEntry", "LocaleEntry")
#: Since E53 the names every app had before the module (nexnotes' eigenbau in all eight): the functions are named as
#: there (``list_locales`` …, so FastAPI's operationIds stay), the list's summary is the old one, and both schemas are
#: one ``LocaleEntry`` (the list's with ``built_in`` and ``own``, which are not required).
SUMMARIES = {
    "list": "Languages the operator added",
    "template": "The template to translate",
    "read": "The texts of one added language",
    "upload": "Add or replace a language (operator)",
    "remove": "Remove an added language (operator)",
}
DEFAULT_SCHEMA = "LocaleEntry"

#: One class per name and form, so that a router mounted twice (two prefixes) gives one schema, not two.
_models: dict[tuple[str, bool], type[BaseModel]] = {}


def _model(target: str, full: bool) -> type[BaseModel]:
    """The schema under ``target``: with ``built_in`` and ``own`` (``full``, the list's) or the three fields only.
    ``target`` is a name (``LocaleEntry``) or a dotted place and name (``app.routers.locales.LocaleEntry``): the class
    then lives there for FastAPI, which writes it ``app__routers__locales__LocaleEntry`` where two classes of the app
    share the name, as it did before."""
    found = _models.get((target, full))
    if found is None:
        place, _, name = target.rpartition(".")
        fields: dict[str, Any] = {"code": (str, ...), "name": (str, ...), "keys": (int, ...)}
        if full:
            fields |= {"built_in": (bool, False), "own": (bool, False)}
        found = create_model(name, __module__=place or __name__, **fields)
        _models[(target, full)] = found
    return found


def _checked(given: dict[str, str] | None, known: tuple[str, ...], what: str) -> dict[str, str]:
    given = dict(given or {})
    unknown = sorted(set(given) - set(known))
    if unknown:
        raise ValueError(f"unknown {what}: {', '.join(unknown)} (known: {', '.join(known)})")
    return given


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
    operation_ids: dict[str, str] | None = None,
    summaries: dict[str, str] | None = None,
    schema_names: dict[str, str] | None = None,
) -> APIRouter:
    """The routes. ``operator``: the app's dependency for operators. ``reader``: None (anybody reads list, texts and
    template) or the app's dependency for reading. ``error(code, message, status, values)``: the app's own form of a
    refusal. ``operation_ids``, ``summaries`` (keys from ``ROUTES``) and ``schema_names`` (keys from ``SCHEMAS``): the
    names an app's description of the interface had before; a key the module does not know is a mistake."""
    make = error or _refuse
    ids = _checked(operation_ids, ROUTES, "route")
    said = SUMMARIES | _checked(summaries, ROUTES, "route")
    names = _checked(schema_names, SCHEMAS, "schema")
    listed_name = names.get("LanguageEntry", DEFAULT_SCHEMA)
    uploaded_name = names.get("LocaleEntry", DEFAULT_SCHEMA)
    listed = _model(listed_name, True)
    uploaded = listed if uploaded_name == listed_name else _model(uploaded_name, False)

    def refuse(code: str, values: dict[str, Any] | None = None, message: str | None = None) -> Exception:
        return make(code, message or MESSAGES[code], CODES[code], dict(values or {}))

    readers = [Depends(reader)] if reader is not None else []
    operators = [Depends(operator)]
    routes = APIRouter(prefix=prefix, tags=tags or ["locales"])

    @routes.get("", response_model=list[listed], summary=said["list"], dependencies=readers,
                operation_id=ids.get("list"))
    def list_locales(response: Response) -> list[store.Language]:
        response.headers.update(NO_CACHE)
        return store.languages()

    @routes.get("/template", summary=said["template"], dependencies=readers, response_model=None,
                operation_id=ids.get("template"))
    def download_template() -> Response:
        texts = store.template()
        if texts is None:
            raise refuse("not_found")
        return Response(
            content=json.dumps(texts, ensure_ascii=False, indent=2) + "\n",
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{current().app_name}-language-template.json"'},
        )

    @routes.get("/{code}", summary=said["read"], dependencies=readers, response_model=None,
                operation_id=ids.get("read"))
    def read_locale(code: str) -> JSONResponse:
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

    @routes.put("/{code}", response_model=uploaded, summary=said["upload"], dependencies=operators,
                operation_id=ids.get("upload"), response_model_exclude_unset=True)
    async def upload_locale(code: str, request: Request) -> store.Locale:
        """The body is the JSON file itself, at most 512 KB."""
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

    @routes.delete("/{code}", status_code=204, summary=said["remove"], dependencies=operators,
                   operation_id=ids.get("remove"))
    def delete_locale(code: str) -> None:
        if not store.remove(code):
            raise refuse("not_found")

    return routes


def _unusable(reason: str) -> str:
    return f"This language file cannot be used: {LocaleError(reason)}."
