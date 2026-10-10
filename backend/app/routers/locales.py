"""The operator's own languages, for the language menu.

Readable without signing in: the sign-in page is shown in the chosen language too, and the texts are the same for
everybody.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..deps import OperatorAccount
from ..errors import detail, error
from ..services import locales

router = APIRouter(prefix="/api/v1/locales", tags=["locales"])


class LocaleEntry(BaseModel):
    code: str
    name: str
    keys: int


@router.get("", response_model=list[LocaleEntry], summary="Languages the operator added")
def list_locales() -> list[locales.Locale]:
    return locales.available()


@router.get("/{code}", summary="The texts of one added language", response_model=None)
def read_locale(code: str) -> dict[str, Any] | JSONResponse:
    if not locales.valid_code(code):
        return JSONResponse(status_code=404, content={"detail": detail("not_found", "Not found.")})
    try:
        return locales.load(code)
    except FileNotFoundError:
        return JSONResponse(status_code=404, content={"detail": detail("not_found", "Not found.")})
    except (locales.LocaleError, OSError):
        return JSONResponse(
            status_code=422, content={"detail": detail("locale_unusable", "This language file cannot be used.")}
        )


@router.put("/{code}", response_model=LocaleEntry, summary="Add or replace a language (operator)")
async def upload_locale(code: str, request: Request, _operator: OperatorAccount) -> locales.Locale:
    """The body is the JSON file itself, at most 512 KB."""
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > locales.MAX_BYTES:
            raise error("too_large", "The file is too large.", 413)
    try:
        return locales.save(code, bytes(raw))
    except locales.LocaleError as exc:
        raise error("locale_unusable", f"This language file cannot be used: {exc}.", 422) from exc


@router.delete("/{code}", status_code=204, summary="Remove an added language (operator)")
def delete_locale(code: str, _operator: OperatorAccount) -> None:
    if not locales.remove(code):
        raise error("not_found", "Not found.", 404)
