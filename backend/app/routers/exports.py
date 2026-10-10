"""Exports for the tax adviser (``services/exports.py``): a ZIP of the documents a person may see, packed in the
background, downloaded by its owner or handed out by a link to somebody without an account.

Every export belongs to the person who asked for it; for everybody else it does not exist (404). Making an export,
fetching its ZIP and making a link to it (or copying the address again) need a signed-in browser: an export holds the
documents of a whole period, so a lost phone must not hand them out (``403 browser_only`` for a device token). A device
may list, look at, delete and revoke; a program with an API key reaches none of it."""

from __future__ import annotations

import logging
from datetime import date as Date
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StrictBool, StrictInt

from ..db import SessionLocal
from ..deps import Account as Caller
from ..deps import BrowserAccount, DbSession, link_failed, link_guard, signed_in_viewer
from ..errors import error
from ..models import Account, Export, ExportLink
from ..services import brakes, exports, settings_service, sharing

logger = logging.getLogger("nexpaper.exports")

router = APIRouter(prefix="/api/v1", tags=["exports"])

ID = StrictInt | None


class ExportContentIn(BaseModel):
    #: The searchable PDFs, the originals as they came, the list as CSV, e-invoices as XML.
    pdf: StrictBool = True
    original: StrictBool = False
    csv: StrictBool = True
    xml: StrictBool = True


class ExportLinkIn(BaseModel):
    recipient: str = Field(max_length=sharing.RECIPIENT_MAX * 2)
    days: StrictInt = Field(ge=1, le=365)


class ExportIn(BaseModel):
    date_from: Date | None = None
    date_to: Date | None = None
    vault_ids: list[StrictInt] = Field(min_length=1, max_length=200)
    #: The filters of the archive, as ``GET /search`` takes them.
    q: str = Field(default="", max_length=500)
    kind_id: ID = None
    owner_id: ID = None
    sender: str | None = Field(default=None, min_length=1, max_length=160)
    tag: str | None = Field(default=None, min_length=1, max_length=40)
    status: Literal["inbox", "filed"] | None = None
    content: ExportContentIn = Field(default_factory=ExportContentIn)
    #: A link for somebody without an account, made at once (it works as soon as the ZIP is packed).
    link: ExportLinkIn | None = None


class ExportLinkOut(BaseModel):
    id: int
    recipient: str
    until: datetime
    opened_count: int
    last_opened_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None
    #: ``active``, ``expired``, ``revoked``, ``off`` (the operator switched links off), ``ended`` (the maker no
    #: longer sees every vault the documents came from).
    status: Literal["active", "expired", "revoked", "off", "ended"]


class ExportLinkMade(ExportLinkOut):
    token: str
    url: str


class ExportLinkAddress(BaseModel):
    url: str


class ExportOut(BaseModel):
    id: int
    #: ``queued``, ``packing``, ``ready`` or ``failed`` (with ``error``).
    state: Literal["queued", "packing", "ready", "failed"]
    documents: int
    #: The size of the ZIP, and the sum of the amounts in it (cents).
    size: int
    total: int
    error: str
    date_from: Date | None
    date_to: Date | None
    vault_ids: list[int]
    content: ExportContentIn
    created_at: datetime
    finished_at: datetime | None
    #: When the ZIP is removed (later while a link to it lasts).
    expires_at: datetime
    links: list[ExportLinkOut]


class ExportMade(ExportOut):
    #: The link asked for with it, with its token and address (shown once; copy it again with ``.../address``).
    link: ExportLinkMade | None = None


class ExportPreviewOut(BaseModel):
    documents: int
    #: The sum of the amounts (cents), in all and per currency (``{"EUR": 1234}``), and about how large the ZIP gets
    #: (bytes: the originals, once per kind of file chosen).
    total: int
    totals: dict[str, int]
    size: int
    #: The first paths in the ZIP, as they will be.
    sample: list[str]
    #: More than one ZIP takes (``max_documents``, ``max_bytes``).
    too_many: bool
    max_documents: int
    max_bytes: int


class PublicExport(BaseModel):
    #: The name the person who made it shows to others (never the sign-in name).
    shared_by: str
    recipient: str
    #: ``packing`` until the ZIP is there, then ``ready``.
    state: Literal["packing", "ready"]
    documents: int
    size: int
    until: datetime
    date_from: Date | None
    date_to: Date | None


def _language(request: Request, account: Account | None) -> str:
    chosen = (account.language if account and account.language else request.headers.get("x-nexpaper-language", ""))
    return "de" if chosen.split("-")[0].lower() == "de" else "en"


def _params(payload: ExportIn) -> exports.Params:
    return exports.Params(
        date_from=payload.date_from, date_to=payload.date_to, vault_ids=list(dict.fromkeys(payload.vault_ids)),
        q=payload.q, kind_id=payload.kind_id, owner_id=payload.owner_id, sender=payload.sender, tag=payload.tag,
        status=payload.status, content=exports.Content(**payload.content.model_dump()),
    )


def _link_out(db: DbSession, link: ExportLink, export: Export) -> ExportLinkOut:
    current = sharing.rules(db)
    return ExportLinkOut(
        id=link.id, recipient=link.recipient, until=exports.ends(link, current.max_days),
        opened_count=link.opened_count, last_opened_at=link.last_opened_at, created_at=link.created_at,
        revoked_at=link.revoked_at, status=exports.status_of(db, link, export, current),  # type: ignore[arg-type]
    )


def _out(db: DbSession, export: Export) -> ExportOut:
    params = exports.Params.from_stored(export.params)
    links = [_link_out(db, link, export) for link in db.query(ExportLink).filter(ExportLink.export_id == export.id)
             .order_by(ExportLink.id.desc())]
    return ExportOut(
        id=export.id, state=export.state, documents=export.documents, size=export.size,  # type: ignore[arg-type]
        total=export.total, error=export.error, date_from=params.date_from, date_to=params.date_to,
        vault_ids=params.vault_ids, content=ExportContentIn(**vars(params.content)), created_at=export.created_at,
        finished_at=export.finished_at, expires_at=export.expires_at, links=links,
    )


def _address(request: Request, db: DbSession, token: str) -> str:
    base = settings_service.public_url(db) or str(request.base_url).rstrip("/")
    return f"{base}/x/{token}"


@router.get("/exports/preview", response_model=ExportPreviewOut,
            summary="What an export would hold: how many documents, their sum, about how large, the first paths")
def preview(
    request: Request, account: Caller, db: DbSession,
    vault_ids: list[int] = Query(default=[], max_length=200, description="The vaults (one or more)"),
    date_from: Date | None = None, date_to: Date | None = None,
    q: str = Query(default="", max_length=500), kind_id: int | None = None, owner_id: int | None = None,
    sender: str | None = Query(default=None, min_length=1, max_length=160),
    tag: str | None = Query(default=None, min_length=1, max_length=40),
    status: Literal["inbox", "filed"] | None = None,
    pdf: bool = True, original: bool = False, csv: bool = True, xml: bool = True,
) -> ExportPreviewOut:
    if q.strip():
        # A search in it counts like one of the search itself.
        brakes.take("search", account.id)
    params = exports.Params(date_from=date_from, date_to=date_to, vault_ids=list(dict.fromkeys(vault_ids)), q=q,
                            kind_id=kind_id, owner_id=owner_id, sender=sender, tag=tag, status=status,
                            content=exports.Content(pdf=pdf, original=original, csv=csv, xml=xml))
    row = db.get(Account, account.id)
    found = exports.preview(db, account.id, params, _language(request, row))
    return ExportPreviewOut(documents=found.documents, total=found.total, totals=found.totals, size=found.size,
                            sample=found.sample,
                      too_many=found.too_many, max_documents=exports.MAX_DOCUMENTS, max_bytes=exports.MAX_BYTES)


@router.post("/exports", response_model=ExportMade, status_code=201,
             summary="Ask for an export: the ZIP is packed in the background, with a notice when it is ready")
def create(payload: ExportIn, request: Request, account: BrowserAccount, db: DbSession) -> ExportMade:
    row = db.get(Account, account.id)
    if payload.q.strip():
        brakes.take("search", account.id)
    if payload.link is not None:
        # Checked before anything is queued: a link that cannot be made makes no export either.
        current = sharing.rules(db)
        if not current.allowed:
            raise error("links_off", "The operator has switched links to the outside off.", 409)
        if payload.link.days > current.max_days:
            raise error("invalid_days", f"A link lasts 1 to {current.max_days} days.", 422,
                        max_days=current.max_days)
        exports.clean_recipient(payload.link.recipient)
    export = exports.create(db, account.id, _params(payload), _language(request, row))
    made = None
    if payload.link is not None:
        link, token = exports.create_link(db, account.id, export.id, payload.link.recipient, payload.link.days)
        made = ExportLinkMade(**_link_out(db, link, export).model_dump(), token=token,
                              url=_address(request, db, token))
    db.refresh(export)
    return ExportMade(**_out(db, export).model_dump(), link=made)


@router.get("/exports", response_model=list[ExportOut], summary="The caller's exports, newest first")
def listing(account: Caller, db: DbSession) -> list[ExportOut]:
    return [_out(db, export) for export in exports.of(db, account.id)]


@router.get("/exports/{export_id}", response_model=ExportOut, summary="One export of the caller")
def one(export_id: int, account: Caller, db: DbSession) -> ExportOut:
    return _out(db, exports.own(db, account.id, export_id))


@router.get("/exports/{export_id}/file", summary="The ZIP of an export of the caller")
def download(export_id: int, account: BrowserAccount, db: DbSession) -> FileResponse:
    path, export = exports.file_of(db, account.id, export_id)
    return FileResponse(path, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{_file_name(export)}"', "Cache-Control": "private, no-store",
    })


def _file_name(export: Export) -> str:
    return f"nexpaper-export-{export.created_at.date().isoformat()}-{export.id}.zip"


@router.delete("/exports/{export_id}", status_code=204, summary="Delete an export: the ZIP and its links go")
def remove(export_id: int, account: Caller, db: DbSession) -> None:
    exports.remove(db, account.id, export_id)


@router.get("/exports/{export_id}/links", response_model=list[ExportLinkOut], summary="The links of an export")
def links(export_id: int, account: Caller, db: DbSession) -> list[ExportLinkOut]:
    export = exports.own(db, account.id, export_id)
    return [_link_out(db, link, export) for link in exports.links_of(db, account.id, export_id)]


@router.post("/exports/{export_id}/links", response_model=ExportLinkMade, status_code=201,
             summary="Make a link to an export for somebody without an account")
def create_link(
    export_id: int, payload: ExportLinkIn, request: Request, account: BrowserAccount, db: DbSession,
) -> ExportLinkMade:
    link, token = exports.create_link(db, account.id, export_id, payload.recipient, payload.days)
    export = exports.own(db, account.id, export_id)
    return ExportLinkMade(**_link_out(db, link, export).model_dump(), token=token, url=_address(request, db, token))


@router.post("/exports/{export_id}/links/{link_id}/address", response_model=ExportLinkAddress,
             summary="The address of a link to an export again, to copy")
def link_address(
    export_id: int, link_id: int, request: Request, account: BrowserAccount, db: DbSession,
) -> ExportLinkAddress:
    return ExportLinkAddress(url=_address(request, db, exports.address(db, account.id, export_id, link_id)))


@router.delete("/exports/{export_id}/links/{link_id}", status_code=204, summary="Revoke a link to an export")
def revoke_link(export_id: int, link_id: int, account: Caller, db: DbSession) -> None:
    exports.revoke_link(db, account.id, export_id, link_id)


# --- Behind a link (no sign-in; the token is the key) -----------------------------------------------------------------


def _not_found(request: Request) -> Exception:
    link_failed(request)
    return error("not_found", "Not found.", 404)


@router.get("/x/{token}", response_model=PublicExport, summary="What a link to an export shows (no sign-in)")
def open_link(token: str, request: Request) -> PublicExport:
    link_guard(request)
    viewer = signed_in_viewer(request)
    with SessionLocal() as db:
        found = exports.open_link(db, token, viewer)
        if found is None:
            raise _not_found(request)
        link, export = found
        maker = db.get(Account, export.user_id)
        params = exports.Params.from_stored(export.params)
        return PublicExport(
            shared_by=maker.display_name if maker else "", recipient=link.recipient,
            state="ready" if export.state == exports.READY else "packing", documents=export.documents,
            size=export.size, until=exports.ends(link, sharing.rules(db).max_days), date_from=params.date_from,
            date_to=params.date_to,
        )


@router.get("/x/{token}/file", summary="The ZIP behind a link to an export (no sign-in)")
def public_file(token: str, request: Request) -> FileResponse:
    link_guard(request)
    with SessionLocal() as db:
        found = exports.check_link(db, token)
        if found is None:
            raise _not_found(request)
        _link, export = found
        if export.state != exports.READY or not export.file:
            raise error("export_not_ready", "The export is not packed yet.", 409)
        path = exports.folder() / export.file
        name = _file_name(export)
    if not path.is_file():
        raise error("not_found", "Not found.", 404)
    return FileResponse(path, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "private, no-store",
        "X-Robots-Tag": "noindex",
    })
