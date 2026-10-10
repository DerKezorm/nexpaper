"""Sorting documents in over HTTP: the rules, a rule from a document in the inbox, and the e-invoice of a document.

* ``/rules``: the rules of the vaults the caller manages (a person manages their own vault). A device may use them too.
* ``/settings/rules``: the operator's rules for the whole server, from the operator's browser only (like every setting
  of the server).
* ``POST /documents/{id}/rule``: "Als Regel merken" in the inbox: the sender of the document and what the person chose.
* ``/documents/{id}/einvoice`` and ``.../versions/{n}/einvoice``: the data and the XML, for whoever may read the
  document (an API key that reads, too).
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request
from fastapi import Path as PathParam
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from ..deps import Account, DbSession, OperatorAccount, Reader
from ..errors import error
from ..models import MANAGE, Sender
from ..services import einvoices, filetypes, rights, storage
from ..services import rules as rules_service
from .files import _send, conditional, disposition, etag_of

router = APIRouter(prefix="/api/v1", tags=["sorting"])

ID = Annotated[int, PathParam(ge=1, le=2**31 - 1)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConditionIn(Strict):
    field: Literal["sender", "text", "kind", "source", "amount"]
    op: Literal["is", "contains", "over", "under"]
    #: For ``sender`` and ``text``: one of these words (compared as plain text, case and accents aside).
    values: list[StrictStr] | None = Field(default=None, max_length=rules_service.MAX_VALUES)
    #: For ``kind`` (its id), ``source`` (``upload``, ``camera``, ``mail``, ``folder``, ``share``, ``paperless``,
    #: ``api``) and ``amount`` (cents).
    value: StrictInt | StrictStr | None = None


class ActionIn(Strict):
    field: Literal["vault", "kind", "tag", "sender", "title"]
    #: A vault or kind id; a tag or sender name; a title pattern (``{sender}``, ``{kind}``, ``{date}``, ``{month}``,
    #: ``{year}``, ``{amount}``).
    value: StrictInt | StrictStr


class RuleIn(Strict):
    when: list[ConditionIn] = Field(min_length=1, max_length=rules_service.MAX_CONDITIONS)
    then: list[ActionIn] = Field(min_length=1, max_length=rules_service.MAX_ACTIONS)
    on: StrictBool = True


class VaultRuleIn(RuleIn):
    vault_id: int = Field(ge=1, le=2**31 - 1)


class RulePatch(Strict):
    when: list[ConditionIn] | None = Field(default=None, min_length=1, max_length=rules_service.MAX_CONDITIONS)
    then: list[ActionIn] | None = Field(default=None, min_length=1, max_length=rules_service.MAX_ACTIONS)
    on: StrictBool | None = None
    #: The place among the rules of its vault, counted from 1.
    position: int | None = Field(default=None, ge=1, le=10_000)


class RuleOut(BaseModel):
    id: int
    #: Empty for a rule of the whole server.
    vault_id: int | None
    position: int
    on: bool
    #: How often it applied to a document its maker may see.
    hits: int
    last_hit_at: datetime | None
    when: list[dict[str, Any]]
    then: list[dict[str, Any]]
    created_at: datetime


class RememberIn(Strict):
    """What the person chose for the document; the rule says: when the sender is this one, then these."""

    kind_id: int | None = Field(default=None, ge=1, le=2**31 - 1)
    vault_id: int | None = Field(default=None, ge=1, le=2**31 - 1)
    tags: list[StrictStr] | None = Field(default=None, max_length=10)


def _payload(items: list[ConditionIn] | list[ActionIn] | None) -> list[dict[str, Any]] | None:
    return None if items is None else [item.model_dump(exclude_none=True) for item in items]


def _out(rule: Any) -> RuleOut:
    return RuleOut(**rules_service.described(rule))


# --- The rules of vaults ------------------------------------------------------------------------------------------


@router.get("/rules", response_model=list[RuleOut], summary="The rules of the vaults the caller manages, in order")
def list_rules(account: Account, db: DbSession) -> list[RuleOut]:
    return [_out(r) for r in rules_service.visible(db, account.id) if r.vault_id is not None]


@router.post("/rules", response_model=RuleOut, status_code=201,
             summary="Add a rule to a vault the caller manages (it applies to documents that arrive there)")
def create_rule(payload: VaultRuleIn, account: Account, db: DbSession) -> RuleOut:
    return _out(rules_service.create(db, account.id, payload.vault_id, _payload(payload.when), _payload(payload.then),
                                     payload.on))


def _vault_rule(db: DbSession, uid: int, rule_id: int) -> None:
    from ..models import Rule

    rule = db.get(Rule, rule_id)
    if rule is None or rule.vault_id is None:
        raise error("not_found", "Not found.", 404)


@router.patch("/rules/{rule_id}", response_model=RuleOut, summary="Change, switch or move a rule of a vault")
def update_rule(rule_id: ID, payload: RulePatch, account: Account, db: DbSession) -> RuleOut:
    _vault_rule(db, account.id, rule_id)
    return _out(rules_service.update(db, account.id, rule_id, when=_payload(payload.when),
                                     then=_payload(payload.then), on=payload.on, position=payload.position))


@router.delete("/rules/{rule_id}", status_code=204, summary="Delete a rule of a vault")
def delete_rule(rule_id: ID, account: Account, db: DbSession) -> None:
    _vault_rule(db, account.id, rule_id)
    rules_service.delete(db, account.id, rule_id)


@router.post("/documents/{document_id}/rule", response_model=RuleOut, status_code=201,
             summary="Remember as a rule: documents from this sender get what was chosen for this one")
def remember(document_id: ID, payload: RememberIn, account: Account, db: DbSession) -> RuleOut:
    """The rule belongs to the vault the document arrived in and needs ``manage`` there; it moves documents only into a
    vault the caller may add to. The document must have a sender."""
    access = rights.require_document(db, account.id, document_id, rights.EDIT)
    document = access.document
    stored = document.suggest if isinstance(document.suggest, dict) else {}
    arrival = stored.get("_from") if isinstance(stored.get("_from"), int) else document.vault_id
    if rights.vault_right(db, account.id, arrival) != MANAGE:
        raise rights.forbidden()
    sender = db.get(Sender, document.sender_id) if document.sender_id else None
    if sender is None:
        raise error("rule_needs_sender", "Give the document a sender first.", 422)
    then: list[dict[str, Any]] = []
    if payload.vault_id is not None:
        then.append({"field": "vault", "value": payload.vault_id})
    if payload.kind_id is not None:
        then.append({"field": "kind", "value": payload.kind_id})
    for tag in payload.tags or []:
        then.append({"field": "tag", "value": tag})
    if not then:
        raise error("invalid_rule", "Choose what the rule sets.", 422)
    when = [{"field": "sender", "op": "is", "values": [sender.name]}]
    return _out(rules_service.create(db, account.id, arrival, when, then[: rules_service.MAX_ACTIONS]))


# --- The operator's rules -----------------------------------------------------------------------------------------


def _server_rule(db: DbSession, rule_id: int) -> None:
    from ..models import Rule

    rule = db.get(Rule, rule_id)
    if rule is None or rule.vault_id is not None:
        raise error("not_found", "Not found.", 404)


@router.get("/settings/rules", response_model=list[RuleOut], summary="The rules for the whole server, in order")
def server_rules(operator: OperatorAccount, db: DbSession) -> list[RuleOut]:
    return [_out(r) for r in rules_service.visible(db, operator.id) if r.vault_id is None]


@router.post("/settings/rules", response_model=RuleOut, status_code=201, summary="Add a rule for the whole server")
def create_server_rule(payload: RuleIn, operator: OperatorAccount, db: DbSession) -> RuleOut:
    return _out(rules_service.create(db, operator.id, None, _payload(payload.when), _payload(payload.then),
                                     payload.on))


@router.patch("/settings/rules/{rule_id}", response_model=RuleOut,
              summary="Change, switch or move a rule of the server")
def update_server_rule(rule_id: ID, payload: RulePatch, operator: OperatorAccount, db: DbSession) -> RuleOut:
    _server_rule(db, rule_id)
    return _out(rules_service.update(db, operator.id, rule_id, when=_payload(payload.when),
                                     then=_payload(payload.then), on=payload.on, position=payload.position))


@router.delete("/settings/rules/{rule_id}", status_code=204, summary="Delete a rule of the server")
def delete_server_rule(rule_id: ID, operator: OperatorAccount, db: DbSession) -> None:
    _server_rule(db, rule_id)
    rules_service.delete(db, operator.id, rule_id)


# --- E-invoices ---------------------------------------------------------------------------------------------------


class InvoiceLineOut(BaseModel):
    text: str
    quantity: str
    unit: str
    #: In cents.
    price: int | None
    total: int | None


class EInvoiceOut(BaseModel):
    #: The version that carries it (a later version, with pages turned, no longer carries the XML).
    version: int
    #: The original of that version is the XML itself (an XRechnung); else it was taken out of the PDF.
    xml_only: bool
    format: str
    number: str
    issued: Date | None
    due: Date | None
    seller: str
    seller_vat: str
    buyer: str
    #: The buyer's reference (the "Leitweg-ID" of German authorities).
    buyer_ref: str
    iban: str
    currency: str
    #: In cents, as the invoice states them.
    net: int | None
    tax: int | None
    gross: int | None
    payable: int | None
    credit_note: bool
    lines: list[InvoiceLineOut]


@router.get("/documents/{document_id}/einvoice", response_model=EInvoiceOut,
            summary="The data of the e-invoice a document carries (404 when it carries none)")
def einvoice(document_id: ID, account: Reader, db: DbSession) -> EInvoiceOut:
    row, number, xml_only = einvoices.detail(db, account.id, document_id)
    lines = [InvoiceLineOut(**line) for line in (row.lines or []) if isinstance(line, dict)
             and set(line) >= {"text", "quantity", "unit", "price", "total"}]
    return EInvoiceOut(
        version=number, xml_only=xml_only, format=row.format, number=row.number, issued=row.issued, due=row.due,
        seller=row.seller, seller_vat=row.seller_vat, buyer=row.buyer, buyer_ref=row.buyer_ref, iban=row.iban,
        currency=row.currency, net=row.net, tax=row.tax, gross=row.gross, payable=row.payable,
        credit_note=row.credit_note, lines=lines,
    )


@router.get("/documents/{document_id}/versions/{number}/einvoice",
            summary="The e-invoice of a version as XML: taken out of the PDF, or the XML that came")
def einvoice_xml(document_id: ID, number: ID, request: Request, account: Reader, db: DbSession) -> Response:
    document, version, data = einvoices.xml_of(db, account.id, document_id, number)
    if data is None:
        try:
            path = storage.safe_path(version.original_path)
        except storage.StorageError:
            raise error("not_found", "Not found.", 404) from None
        return _send(path, filetypes.MEDIA_TYPE[filetypes.XML], request,
                     etag_of("einvoice", document_id, version.n, version.sha256), document.title, ".xml", False)
    etag = etag_of("einvoice", document_id, version.n, version.sha256)
    cached = conditional(request, etag)
    if cached is not None:
        return cached
    return Response(content=data, media_type=filetypes.MEDIA_TYPE[filetypes.XML], headers={
        "Content-Disposition": disposition(document.title, ".xml", False), "ETag": etag,
        "Cache-Control": "private, no-cache"})
