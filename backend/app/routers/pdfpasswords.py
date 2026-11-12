"""Protected PDFs (P1): opening one with its password, and the passwords a person keeps.

``POST /api/v1/documents/{id}/unlock`` takes the password of a PDF that waits in the inbox for one (``process_error``
``encrypted``): it needs ``edit`` on the document and a browser or a device (a key never reaches it). The run is made in
the request, the answer says only whether it opened and whether the password is kept now, never the password.

``/api/v1/pdf-passwords`` lists, renames and deletes the caller's own kept passwords (browser or device). A password is
never sent back, not even to the person who kept it; nobody else's is ever listed, counted or used, the operator's view
included (``services/pdf_passwords.py``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Path
from pydantic import BaseModel, ConfigDict, Field

from ..deps import Account as Caller
from ..deps import DbSession
from ..services import pdf_passwords
from .documents import _one
from .schemas import DocumentOut

router = APIRouter(prefix="/api/v1", tags=["pdf passwords"])

DOCUMENT = Annotated[int, Path(ge=1, le=2**31 - 1)]
ENTRY = Annotated[int, Path(ge=1, le=2**31 - 1)]


class UnlockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The password, as typed. Never stored unless `remember`, never sent back.
    password: str = Field(max_length=pdf_passwords.PASSWORD_MAX)
    #: Keep it, sealed, for the protected PDFs that come into the caller's inbox later (at most 10).
    remember: bool = False
    #: The name it is kept under ("Payslip"); needed with `remember`.
    name: str | None = Field(default=None, max_length=pdf_passwords.NAME_MAX * 4)


class UnlockOut(BaseModel):
    document: DocumentOut
    #: `kept` (kept now), `known` (the caller keeps this password already), or empty (not asked to keep it).
    kept: Literal["", "kept", "known"]


@router.post("/documents/{document_id}/unlock", response_model=UnlockOut,
             summary="Open the protected PDF of a document with its password; it is read again from the PDF opened")
def unlock(document_id: DOCUMENT, payload: UnlockIn, account: Caller, db: DbSession) -> UnlockOut:
    """`409 not_protected` when the document does not wait for a password, `422 wrong_pdf_password` when the password
    does not open it (the document stays as it was), `429 pdf_password_too_often` after 5 tries for one document or 20
    of the caller in an hour."""
    opened = pdf_passwords.open_with(db, account.id, document_id, payload.password, keep=payload.remember,
                                     name=payload.name)
    return UnlockOut(document=_one(db, account, opened.document.id), kept=opened.kept)  # type: ignore[arg-type]


class PdfPasswordOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    #: When it last opened a PDF; empty until it did.
    last_matched_at: datetime | None
    #: False when the server's secret changed since it was kept: it cannot be used any more (delete it, keep it anew).
    readable: bool


class PdfPasswordRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=pdf_passwords.NAME_MAX * 4)


def _out(entry: pdf_passwords.Listed) -> PdfPasswordOut:
    row = entry.row
    return PdfPasswordOut(id=row.id, name=row.name, created_at=row.created_at, last_matched_at=row.last_matched_at,
                          readable=entry.readable)


@router.get("/pdf-passwords", response_model=list[PdfPasswordOut],
            summary="The caller's kept PDF passwords: names and dates, never a password")
def list_kept(account: Caller, db: DbSession) -> list[PdfPasswordOut]:
    return [_out(entry) for entry in pdf_passwords.listed(db, account.id)]


@router.patch("/pdf-passwords/{entry_id}", response_model=PdfPasswordOut, summary="Rename a kept PDF password")
def rename_kept(entry_id: ENTRY, payload: PdfPasswordRename, account: Caller, db: DbSession) -> PdfPasswordOut:
    row = pdf_passwords.rename(db, account.id, entry_id, payload.name)
    found = next(entry for entry in pdf_passwords.listed(db, account.id) if entry.row.id == row.id)
    return _out(found)


@router.delete("/pdf-passwords/{entry_id}", status_code=204, summary="Delete a kept PDF password (for good)")
def delete_kept(entry_id: ENTRY, account: Caller, db: DbSession) -> None:
    pdf_passwords.delete(db, account.id, entry_id)
