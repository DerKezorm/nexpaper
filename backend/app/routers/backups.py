"""Storage and backups over HTTP, operator only (from the browser, from the operators' networks: ``require_operator``):
the routes of the shared module ``sicherung``.

- ``/api/v1/server/storage``: the module's own ways (the card "Speicher", the schedule with its time, the list, check,
  download, restore, delete, upload; the settings page uses these);
- ``/api/v1/backups``: the ways nexpaper had before the module, in their old shapes and with the old password header
  ``x-nexpaper-password`` (the list as an array of flat entries, the check flat with ``usable``), so scripts and older
  pages keep working.

``GET /api/v1/storage`` and ``/api/v1/storage/files/…`` stay nexpaper's own (``routers/storage.py``).

Download, restore, delete and upload ask for the operator's password again (``confirm_operator``: an account from a
provider confirms with a fresh sign-in there; wrong tries count like a sign-in).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..db import SessionLocal
from ..deps import OperatorAccount, confirm_operator
from ..errors import error
from ..services import backups  # noqa: F401  (configures the module before its routes are used)
from ..vendor.nexsicherung import routes

#: The password for an upload on the old way: the body is the archive itself, so the password comes in a header, as
#: base64 of its UTF-8 (a header carries no umlauts).
PASSWORD_HEADER = "x-nexpaper-password"


def _confirm(request: Request, account: Any, password: str) -> None:
    with SessionLocal() as db:
        confirm_operator(request, db, account, password)


def _error(code: str, text: str, status: int) -> Exception:
    return error(code, text, status)


router = APIRouter()
router.include_router(routes.router(operator=OperatorAccount, confirm=_confirm, error=_error,
                                    prefix="/api/v1/server/storage"))
router.include_router(routes.legacy_router(prefix="/api/v1/backups", password_header=PASSWORD_HEADER,
                                           operator=OperatorAccount, confirm=_confirm, error=_error))
