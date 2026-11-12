"""Upload requests (U1), the side of the person who asks: make one, list the own ones, copy an address again, revoke
one; the operator sees how many are open and whose number, never an address or a name.

Each person makes requests for their own inbox only. A browser or a device makes them (``Account``); an API key never
does (``require_account`` turns it away). Somebody else's request answers 404 as one that does not exist, the
operator's look included. The stranger's side is ``routers/request_page.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field, StrictInt

from ..deps import Account as Caller
from ..deps import DbSession, OperatorAccount
from ..models import UploadRequest
from ..services import upload_requests

router = APIRouter(prefix="/api/v1", tags=["upload requests"])

REQUEST_ID = Annotated[int, Path(ge=1, le=2**31 - 1)]


class RequestRules(BaseModel):
    #: The operator's switch.
    allowed: bool
    #: The server has a public address (a request needs one; without it the dialog says what is missing).
    public_url_set: bool
    #: The longest a request may last, in days (as a link).
    max_days: int
    #: The most files a request may take, and how many it takes from the start.
    max_files: int
    default_files: int
    #: The most open requests a person may have.
    max_open: int


class RequestOut(BaseModel):
    id: int
    #: Whom the files are expected from.
    name: str
    until: datetime
    max_files: int
    #: Files that came through it so far.
    received: int
    last_used_at: datetime | None
    created_at: datetime
    #: ``active``; ``expired``; ``used`` (all files are there); ``off`` (the operator's switch); ``ended`` (the public
    #: address changed since it was made).
    status: Literal["active", "expired", "used", "off", "ended"]


class RequestCreated(RequestOut):
    #: The address to give out (``<public address>/u/<token>``).
    url: str


class RequestIn(BaseModel):
    name: str = Field(max_length=upload_requests.NAME_MAX * 2)
    days: StrictInt = Field(ge=1, le=365)
    max_files: StrictInt = Field(default=upload_requests.DEFAULT_FILES, ge=1, le=upload_requests.MAX_FILES)


class RequestAddress(BaseModel):
    url: str


class RequestsOverview(BaseModel):
    open_requests: int
    people: int


def _out(row: UploadRequest, current: upload_requests.Rules) -> RequestOut:
    return RequestOut(id=row.id, name=row.name, until=upload_requests.ends(row, current.max_days),
                      max_files=row.max_files, received=min(row.received, row.max_files), last_used_at=row.last_used_at,
                      created_at=row.created_at,
                      status=upload_requests.status_of(row, current))  # type: ignore[arg-type]


def _url(current: upload_requests.Rules, token: str) -> str:
    return f"{current.address}/u/{token}"


@router.get("/upload-requests/rules", response_model=RequestRules,
            summary="Whether upload requests are on, and what one may be")
def rules(_account: Caller, db: DbSession) -> RequestRules:
    current = upload_requests.rules(db)
    return RequestRules(allowed=current.allowed, public_url_set=bool(current.address), max_days=current.max_days,
                        max_files=upload_requests.MAX_FILES, default_files=upload_requests.DEFAULT_FILES,
                        max_open=upload_requests.MAX_OPEN)


@router.get("/upload-requests", response_model=list[RequestOut], summary="The caller's own upload requests")
def mine(account: Caller, db: DbSession) -> list[RequestOut]:
    current = upload_requests.rules(db)
    return [_out(row, current) for row in upload_requests.mine(db, account.id)]


@router.post("/upload-requests", response_model=RequestCreated, status_code=201,
             summary="Ask somebody without an account for files: an address that puts them into the own inbox")
def create(payload: RequestIn, account: Caller, db: DbSession) -> RequestCreated:
    row, token = upload_requests.create(db, account.id, payload.name, payload.days, payload.max_files)
    current = upload_requests.rules(db)
    return RequestCreated(**_out(row, current).model_dump(), url=_url(current, token))


@router.post("/upload-requests/{request_id}/address", response_model=RequestAddress,
             summary="The address of an own upload request again, to copy")
def address(request_id: REQUEST_ID, account: Caller, db: DbSession) -> RequestAddress:
    token = upload_requests.token_of(db, account.id, request_id)
    return RequestAddress(url=_url(upload_requests.rules(db), token))


@router.delete("/upload-requests/{request_id}", status_code=204,
               summary="Revoke an own upload request: it takes nothing from now on")
def revoke(request_id: REQUEST_ID, account: Caller, db: DbSession) -> None:
    upload_requests.revoke(db, account.id, request_id)


@router.get("/upload-requests/overview", response_model=RequestsOverview,
            summary="For the operator: how many upload requests take files, and of how many people")
def overview(_operator: OperatorAccount, db: DbSession) -> RequestsOverview:
    found = upload_requests.overview(db)
    return RequestsOverview(open_requests=found.open_requests, people=found.people)
