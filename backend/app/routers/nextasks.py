"""A task in nextasks from a document (Bauplan V19, nexpaper the guest of nextasks; a draft in its smallest form).

Only for a signed-in browser (a device or a key makes no connections and uses none). Over the connection made by a
click under Mein Konto › Verbindungen; the work is in ``services/task_from_document.py``.

| Method | Path | |
|---|---|---|
| GET | ``/api/v1/nextasks`` | ``{"usable"}``: the button on the document's page stands only while it holds |
| GET | ``/api/v1/nextasks/lists`` | the lists in nextasks and the one used last (``last_list_id``) |
| POST | ``/api/v1/documents/{id}/nextasks`` | ``{"list_id"}`` → the task (201), or the document's one before (200) |

Errors: 409 ``nextasks_not_connected``, ``nextasks_disconnected`` (ended, resting or switched off in nextasks: the card
says which), ``nextasks_declined`` with ``reason`` (nextasks said no, e.g. a list gone); 502 ``nextasks_unreachable``.
Reading the document is enough, as for pinning; one the person may not see answers 404.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..deps import BrowserAccount, DbSession
from ..errors import error
from ..services import documents
from ..services import task_from_document as tasks
from .pages import document_pages

router = APIRouter(prefix="/api/v1", tags=["nextasks"])

PROBLEMS = {
    409: {"description": "`nextasks_not_connected`, `nextasks_disconnected`, `nextasks_declined` (with `reason`)"},
    502: {"description": "`nextasks_unreachable`"},
}


class NextasksStateOut(BaseModel):
    #: A connection with nextasks made by a click holds and may make tasks.
    usable: bool


class NextasksListOut(BaseModel):
    id: str
    name: str
    space_name: str


class NextasksListsOut(BaseModel):
    lists: list[NextasksListOut]
    #: The list this account put a task in last, if nextasks still has it.
    last_list_id: str | None = None


class NextasksTaskIn(BaseModel):
    list_id: str = Field(min_length=1, max_length=64)


class NextasksTaskOut(BaseModel):
    task_id: str
    title: str
    #: The task in nextasks' web app; null when nextasks has no public address.
    link: str | None = None
    #: False: the document had a task in nextasks already, this is that one (wherever it lies now).
    created: bool


def _answer(problem: tasks.Problem) -> Exception:
    return error(problem.code, problem.message, problem.status, **problem.values)


@router.get("/nextasks", response_model=NextasksStateOut, summary="Whether a task can go to nextasks (a draft)")
def state(account: BrowserAccount, db: DbSession) -> NextasksStateOut:
    return NextasksStateOut(usable=tasks.usable(db, account.id))


@router.get("/nextasks/lists", response_model=NextasksListsOut, responses=PROBLEMS,
            summary="The lists in nextasks, through the connection")
def lists(account: BrowserAccount, db: DbSession) -> NextasksListsOut:
    try:
        found, last = tasks.lists(db, account.id)
    except tasks.Problem as problem:
        raise _answer(problem) from None
    return NextasksListsOut(lists=[NextasksListOut(id=item.id, name=item.name, space_name=item.space_name)
                                   for item in found], last_list_id=last)


@router.post("/documents/{document_id}/nextasks", response_model=NextasksTaskOut, status_code=201,
             responses={**PROBLEMS, 200: {"model": NextasksTaskOut}},
             summary="A task in nextasks from the document, with its page as the link back")
def make(document_id: int, payload: NextasksTaskIn, request: Request, account: BrowserAccount,
         db: DbSession) -> JSONResponse:
    _access, row = documents.one(db, account.id, document_id)
    page = document_pages(db, request)(row.document.id, row.document.status)
    try:
        made = tasks.make(db, account.id, row.document.id, row.document.title, page, payload.list_id)
    except tasks.Problem as problem:
        raise _answer(problem) from None
    out = NextasksTaskOut(task_id=made.task_id, title=made.title, link=made.link, created=made.created)
    return JSONResponse(out.model_dump(), status_code=201 if made.created else 200)
