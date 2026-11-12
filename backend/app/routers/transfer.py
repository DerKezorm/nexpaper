"""The transfer code ("Überweisen", K1): what a bank transfer for a document can take, and the EPC QR code for it.

Both need no more than reading the document. The information is open to a signed-in browser, a device and a program
with a key that reads; the code is asked for with a body (the IBAN and the purpose never stand in an address, where a
proxy's log would keep them), by a browser or a device. Never through a link: there is no route for it under
``/api/v1/l/``. Nothing is stored.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, StrictInt

from ..deps import Account as Caller
from ..deps import DbSession, Reader
from ..services import transfer

router = APIRouter(prefix="/api/v1", tags=["transfer"])


class IbanOut(BaseModel):
    iban: str
    #: `einvoice`: from the data of the e-invoice; `text`: read from the text (compare it with the document).
    origin: Literal["einvoice", "text"]


class TransferOut(BaseModel):
    #: Enough for a code: at least one IBAN, an amount above 0, the euro, a recipient, no credit note.
    ready: bool
    #: What is missing: `iban`, `amount`, `currency`, `recipient`, `credit_note`.
    missing: list[str]
    recipient: str
    #: `einvoice` (the seller of the e-invoice) or `sender` (the document's sender); empty without a recipient.
    recipient_origin: Literal["einvoice", "sender"] | None
    #: The IBANs of the document, those of the e-invoice first.
    ibans: list[IbanOut]
    #: In cents: what the e-invoice says is to be paid (`einvoice`), else the amount of the document (`document`).
    amount: int | None
    amount_origin: Literal["einvoice", "document"] | None
    currency: str
    #: The invoice number as the purpose, empty when there is none.
    purpose: str
    purpose_origin: Literal["einvoice", "text"] | None
    #: The most characters of a purpose.
    purpose_max: int = transfer.PURPOSE_MAX


class CodeIn(BaseModel):
    #: One of the document's IBANs (`ibans`); any other answers `422 unknown_iban`.
    iban: str = Field(max_length=64)
    #: In cents, 1 to 99,999,999,999.
    amount: StrictInt = Field(ge=transfer.AMOUNT_MIN, le=transfer.AMOUNT_MAX)
    #: At most 140 characters: letters, digits, blanks, the umlauts and / - ? : ( ) . , ' +; may be empty.
    purpose: str = Field(default="", max_length=transfer.PURPOSE_MAX * 2)


@router.get("/documents/{document_id}/transfer", response_model=TransferOut,
            summary="What a bank transfer for a document can take, each with where it comes from")
def info(document_id: int, account: Reader, db: DbSession) -> TransferOut:
    found = transfer.info(db, account.id, document_id)
    return TransferOut(
        ready=found.ready, missing=found.missing, recipient=found.recipient,
        recipient_origin=found.recipient_origin,  # type: ignore[arg-type]
        ibans=[IbanOut(iban=iban, origin=origin) for iban, origin in found.ibans],  # type: ignore[arg-type]
        amount=found.amount, amount_origin=found.amount_origin,  # type: ignore[arg-type]
        currency=found.currency, purpose=found.purpose, purpose_origin=found.purpose_origin,  # type: ignore[arg-type]
    )


@router.post("/documents/{document_id}/transfer/code", response_class=Response,
             responses={200: {"content": {"image/svg+xml": {}}, "description": "The EPC QR code as SVG"}},
             summary="The EPC QR code (GiroCode) for one of the document's IBANs, an amount and a purpose, as SVG")
def code(document_id: int, payload: CodeIn, account: Caller, db: DbSession) -> Response:
    """`409 transfer_not_possible` (with `missing`) when the document gives no transfer: another currency, no
    recipient, a credit note, no IBAN. Nothing is stored; the answer is not kept by a cache."""
    svg = transfer.code(db, account.id, document_id, payload.iban, payload.amount, payload.purpose)
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})
