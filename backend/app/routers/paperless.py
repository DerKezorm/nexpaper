"""Settings, Import: taking documents over from Paperless-ngx (``services/paperless.py``). The operator only, from a
browser: the token of Paperless sees everything there, and the run puts documents into the vaults of other people.

The token is written sealed and never read back: the answer only says whether one is kept."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictBool, StrictInt
from sqlalchemy import select

from ..deps import DbSession, OperatorAccount
from ..models import Account, Vault
from ..services import paperless

logger = logging.getLogger("nexpaper.paperless")

router = APIRouter(prefix="/api/v1", tags=["paperless"])


class PaperlessRunOut(BaseModel):
    #: ``idle`` (never started), ``queued``, ``running``, ``paused`` (stopped by the operator, can go on), ``done``,
    #: ``failed`` (with ``error``; can go on).
    state: Literal["idle", "queued", "running", "paused", "done", "failed"]
    #: The documents in Paperless, and how many of them are here (from this run and the ones before).
    total: int
    done: int
    #: Taken and skipped in this run; the reasons of the skipped ones with their number.
    taken: int
    skipped: int
    reasons: dict[str, int]
    error: str
    #: The operator asked it to stop; it stops after the document it is at.
    stop: bool
    started_at: str | None
    finished_at: str | None


class PaperlessOut(BaseModel):
    url: str
    token_set: bool
    #: Paperless may lie in the own network.
    private: bool
    #: What was chosen at the last start: each document into the own vault of its person, or all into ``vault_id``.
    where: Literal["owner", "vault"]
    vault_id: int | None
    #: How the last start sorted: as Paperless did (its inbox into the inbox, the rest filed) or all into the inbox.
    sort: Literal["paperless", "inbox"] = "paperless"
    run: PaperlessRunOut


class PaperlessSkippedItem(BaseModel):
    #: The number of the document in Paperless; nothing else of it (no title, no text) is given.
    paperless_id: int
    #: Why it was not taken (``file_missing``, ``too_large``, ``unsupported_type`` ...).
    reason: str


class PaperlessSkippedOut(BaseModel):
    #: The first ones (lowest number first), at most 50.
    items: list[PaperlessSkippedItem]
    total: int
    #: How many more there are than listed.
    more: int


class PaperlessIn(BaseModel):
    url: str | None = Field(default=None, max_length=255)
    #: Empty removes the token; left out keeps it (unless the address changes).
    token: str | None = Field(default=None, max_length=200)
    private: StrictBool | None = None


class PaperlessOwnerOut(BaseModel):
    #: The number of the owner in Paperless; empty for documents without an owner.
    paperless_id: int | None
    #: The name in Paperless; empty when the token may not list the users.
    name: str
    documents: int
    #: The person proposed here: the one of the same name, else the operator.
    user_id: int
    #: Whether a person of the same name was found (else the proposal is the operator).
    matched: bool


class ImportPersonOut(BaseModel):
    id: int
    name: str
    display_name: str


class PaperlessVaultChoice(BaseModel):
    id: int
    name: str
    #: The operator's own vault (the others are shared vaults).
    own: bool


class PaperlessCheckOut(BaseModel):
    version: str
    api_version: int
    documents: int
    tags: int
    correspondents: int
    document_types: int
    custom_fields: int
    #: Document types in use that become new kinds here.
    new_kinds: list[str]
    owners: list[PaperlessOwnerOut]
    #: The token may not list the users of Paperless: owners are known by their number only.
    users_hidden: bool
    #: Documents of this Paperless that are here already (a second run leaves them).
    already: int
    #: Documents Paperless still has in its inbox (carrying an inbox tag).
    inbox_documents: int = 0
    people: list[ImportPersonOut]
    vaults: list[PaperlessVaultChoice]


class ImportOwnerIn(BaseModel):
    paperless_id: StrictInt | None = None
    user_id: StrictInt


class ImportStartIn(BaseModel):
    where: Literal["owner", "vault"] = "owner"
    vault_id: StrictInt | None = None
    #: ``paperless``: what Paperless had in its inbox waits in the inbox, the rest is filed. ``inbox``: all waits there.
    sort: Literal["paperless", "inbox"] = "paperless"
    people: list[ImportOwnerIn] = Field(default_factory=list, max_length=5000)
    #: Go on with what was chosen at the last start (``where``, ``vault_id`` and ``people`` are not looked at).
    resume: StrictBool = False


def _out(db: DbSession) -> PaperlessOut:
    view = paperless.view(db)
    return PaperlessOut(**{**view, "run": PaperlessRunOut(**view["run"])})


@router.get("/settings/paperless", response_model=PaperlessOut,
            summary="The Paperless-ngx server documents are taken from, and where the import stands")
def read(_operator: OperatorAccount, db: DbSession) -> PaperlessOut:
    return _out(db)


@router.get("/settings/paperless/skipped", response_model=PaperlessSkippedOut,
            summary="The documents of the import that were skipped: their number in Paperless and the reason")
def skipped(_operator: OperatorAccount, db: DbSession) -> PaperlessSkippedOut:
    return PaperlessSkippedOut(**paperless.skipped(db))


@router.put("/settings/paperless", response_model=PaperlessOut, summary="Change the address, token or switch")
def save(payload: PaperlessIn, _operator: OperatorAccount, db: DbSession) -> PaperlessOut:
    sent = payload.model_dump(exclude_unset=True)
    try:
        paperless.save(db, url=sent.get("url"), token=sent.get("token"), private=sent.get("private"))
    except paperless.Failure as exc:
        raise exc.http() from exc
    return _out(db)


@router.delete("/settings/paperless", response_model=PaperlessOut,
               summary="Remove the connection (what was taken stays)")
def forget(_operator: OperatorAccount, db: DbSession) -> PaperlessOut:
    try:
        paperless.forget(db)
    except paperless.Failure as exc:
        raise exc.http() from exc
    return _out(db)


@router.post("/settings/paperless/check", response_model=PaperlessCheckOut,
             summary="Connect and look: what Paperless holds and how it would come over (nothing is written)")
def check(operator: OperatorAccount, db: DbSession) -> PaperlessCheckOut:
    try:
        found = paperless.check(db, operator.id)
    except paperless.Failure as exc:
        raise exc.http() from exc
    people = [ImportPersonOut(id=a.id, name=a.name, display_name=a.display_name or a.name)
              for a in db.scalars(select(Account).where(Account.blocked_at.is_(None)).order_by(Account.name))]
    choices = select(Vault).where(Vault.personal_of.is_(None) | (Vault.personal_of == operator.id))
    vaults = [PaperlessVaultChoice(id=v.id, name=v.name, own=v.personal_of == operator.id)
              for v in db.scalars(choices.order_by(Vault.personal_of.is_(None), Vault.id))]
    owners = [PaperlessOwnerOut(**owner) for owner in found["owners"]]
    return PaperlessCheckOut(**{**found, "owners": owners}, people=people, vaults=vaults)


@router.post("/settings/paperless/start", response_model=PaperlessOut, status_code=202,
             summary="Start the import (or go on with one that stopped): it runs in the background")
def start(payload: ImportStartIn, operator: OperatorAccount, db: DbSession) -> PaperlessOut:
    try:
        if payload.resume:
            paperless.resume(db, operator)
        else:
            paperless.start(db, operator, where=payload.where, vault_id=payload.vault_id,
                            people=[(p.paperless_id, p.user_id) for p in payload.people], sort=payload.sort)
    except paperless.Failure as exc:
        raise exc.http() from exc
    return _out(db)


@router.post("/settings/paperless/stop", response_model=PaperlessOut,
             summary="Stop the import after the document it is at; starting again goes on from there")
def stop(_operator: OperatorAccount, db: DbSession) -> PaperlessOut:
    paperless.stop(db)
    return _out(db)
