"""A task in nextasks from a document (Bauplan V19, the pair nexpaper → nextasks; a draft in its smallest form).

nexpaper is the guest here: over a connection made by a click (verbinden, ``tasks.read`` and ``tasks.write``) it reads
the person's lists in nextasks (``GET /api/v1/lists``) and makes a task there (``POST /api/v1/tasks``) with the
document's title and its page as the link back. The task's ``external_ref`` names the document, so the same document
a second time finds the task made first (nextasks answers it with 200) instead of making another one. The list used
last is remembered per account (``nextasks_lists_used``) and chosen first next time.

The module gives the address and a fresh access (``nexverbinden.access``); nexpaper asks with the module's own rules
for an address (``nexverbinden.reach``: no own host, own network only with the operator's switch, no redirect, a time
limit) and tells the module how it went (``nexverbinden.reached``), so the card of nextasks shows "Nicht erreichbar"
or "Getrennt" as it does for the module's own calls. A 401 is asked once more with an access renewed on the spot
(``access(force=True)``); only a second 401 means the connection was ended in nextasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models_verbinden import NextasksListUsed
from ..vendor import nexverbinden
from .verbinden_store import CONFIG, VerbindenStore

PARTNER = "nextasks"

#: The states of a connection in which the button stands on the document's page: it holds, or nextasks is only away
#: for now (the person learns it when trying). Ended, resting or switched off: no button, the card says why.
USABLE = ("connected", "unreachable")

#: nexverbinden's refusals of ``access`` and how nexpaper names them at its own routes.
REFUSED = {
    "not_connected": ("nextasks_not_connected", 409, "nexpaper is not connected with nextasks."),
    "unreachable": ("nextasks_unreachable", 502, "nextasks cannot be reached right now."),
    "refused": ("nextasks_disconnected", 409, "The connection with nextasks was ended in nextasks."),
    "resting": ("nextasks_disconnected", 409, "The connection with nextasks rests until it is renewed."),
    "partner_off": ("nextasks_disconnected", 409, "The operator of nextasks switched connections off."),
}

#: The partner's codes that end or pause the connection (the card changes), besides a second 401.
ENDING = ("account_resting", "connections_off")


class Problem(Exception):
    def __init__(self, code: str, status: int, message: str, **values: Any) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message
        self.values = values


@dataclass(frozen=True)
class Made:
    task_id: str
    title: str
    #: The task in nextasks' web app (null when its operator set no public address).
    link: str | None
    #: False: the document had its task already, this is that one.
    created: bool


def _now() -> datetime:
    return datetime.now(UTC)


def usable(db: Session, account_id: int) -> bool:
    """A connection with nextasks made by a click that may make tasks and holds (the button on the document's page)."""
    connection = VerbindenStore(db).connection(account_id, PARTNER)
    return connection is not None and "tasks.write" in connection.uses and connection.state in USABLE


def _refused(code: str) -> Problem:
    ours, status, message = REFUSED.get(code, REFUSED["refused"])
    return Problem(ours, status, message)


def _access(store: VerbindenStore, account_id: int, *, force: bool = False, failed: str | None = None) -> Any:
    try:
        found = nexverbinden.access(store, CONFIG, account_id, PARTNER, _now(), force=force, failed=failed)
    except nexverbinden.Refused as refusal:
        store.commit()
        raise _refused(refusal.code) from None
    # A renewed access is the connection's from now on, whatever the request brings.
    store.commit()
    return found


def _ask(store: VerbindenStore, account_id: int, method: str, path: str, **sent: Any) -> Any:
    """One request of nexpaper's own to nextasks over the connection; the answer (any status below 500) or a
    ``Problem``. The card learns how it went."""

    def once(access: Any) -> Any:
        return nexverbinden.reach.ask(
            access.base, method, path, local_allowed=store.local_allowed(), agent=CONFIG.user_agent,
            seconds=CONFIG.seconds, connect_seconds=CONFIG.connect_seconds, limit=CONFIG.max_answer,
            bearer=access.token, **sent,
        )

    def told(problem: str | None) -> None:
        nexverbinden.reached(store, account_id, PARTNER, _now(), problem=problem)
        store.commit()

    try:
        first = _access(store, account_id)
        answer = once(first)
        if answer.status == 401 and answer.code != "account_resting":
            # An access can end before its time (nextasks restarted with other keys, a clock): once more, renewed;
            # only where the refused token is still the one held (verbinden 0.2.1, BS1: another request may have
            # renewed it meanwhile).
            answer = once(_access(store, account_id, force=True, failed=first.token))
    except nexverbinden.reach.Unreachable:
        told("unreachable")
        raise _refused("unreachable") from None
    if answer.status == 401:
        told(answer.code if answer.code in ENDING else "token_invalid")
        raise _refused("resting" if answer.code == "account_resting" else "refused")
    if answer.status == 403 and answer.code in ENDING:
        told(answer.code)
        raise _refused("partner_off" if answer.code == "connections_off" else "resting")
    told(None)
    return answer


def _declined(answer: Any) -> Problem:
    """nextasks answered, but no: a list gone, a purpose not given, a field it does not take."""
    reason = answer.code or str(answer.status)
    return Problem("nextasks_declined", 409, "nextasks did not take the task.", reason=reason)


@dataclass(frozen=True)
class TaskList:
    id: str
    name: str
    space_name: str


def lists(db: Session, account_id: int) -> tuple[list[TaskList], str | None]:
    """The person's lists in nextasks (in the order of nextasks' sidebar) and the one used last, if it is still
    there."""
    answer = _ask(VerbindenStore(db), account_id, "GET", "/api/v1/lists")
    if answer.status != 200 or not isinstance(answer.data, dict) or not isinstance(answer.data.get("lists"), list):
        raise _declined(answer)
    found = [
        TaskList(id=str(item["id"]), name=str(item.get("name") or ""), space_name=str(item.get("space_name") or ""))
        for item in answer.data["lists"]
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("writable", True) is not False
    ]
    row = db.get(NextasksListUsed, account_id)
    last = row.list_id if row is not None and any(item.id == row.list_id for item in found) else None
    return found, last


def external_ref(document_id: int) -> str:
    """The task's key in nextasks: one task per document and nextasks account."""
    return f"nexpaper:document:{document_id}"


def make(db: Session, account_id: int, document_id: int, title: str, page: str, list_id: str) -> Made:
    """The task of the document in ``list_id`` (or the one made before, wherever it lies)."""
    # A document without a title (one still waiting for it) is named by its number, as the archive shows it.
    body = {"title": title.strip()[:500] or f"nexpaper #{document_id}", "url": page, "list_id": list_id,
            "external_ref": external_ref(document_id)}
    answer = _ask(VerbindenStore(db), account_id, "POST", "/api/v1/tasks", body=body)
    data = answer.data
    if answer.status not in (200, 201) or not isinstance(data, dict) or not isinstance(data.get("id"), str):
        raise _declined(answer)
    row = db.get(NextasksListUsed, account_id)
    if row is None:
        db.add(NextasksListUsed(account_id=account_id, list_id=list_id))
    else:
        row.list_id = list_id
    db.commit()
    link = answer.data.get("link")
    return Made(task_id=answer.data["id"], title=str(answer.data.get("title") or title),
                link=link if isinstance(link, str) and link.startswith(("https://", "http://")) else None,
                created=answer.status == 201)


def forget(db: Session, account_id: int) -> None:
    """The account is gone for good: its remembered list goes too."""
    db.query(NextasksListUsed).filter(NextasksListUsed.account_id == account_id).delete()
    db.commit()


__all__ = ["PARTNER", "Made", "Problem", "TaskList", "external_ref", "forget", "lists", "make", "usable"]
