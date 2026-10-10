"""Error answers with a code.

The backend does not translate, it names. Every error carries a code; the frontend builds the sentence from
``errors.byCode`` in its language files. The English text is the fallback for anyone using the API directly.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

#: Every "not found" says the same: something one may not read must answer exactly like something that is not there,
#: and a route-specific text would tell the two apart.
NOT_FOUND = "Not found."


def detail(code: str, text: str, **values: Any) -> dict[str, Any]:
    if code == "not_found":
        text = NOT_FOUND
    return {"code": code, "message": text, **values}


def error(code: str, text: str, status_code: int = 400, **values: Any) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail(code, text, **values))
