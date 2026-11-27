"""What nexpaper has about one person for nexfolk (verbinden 0.1.13, purpose ``documents.about``): the card "In den
anderen Apps" in a contact of nexfolk asks with the token of the connection.

The rule: a document counts when it is from the person, that is its sender's name is the person's name (case folded
like every sender name) or the mail it came in with was sent from one of the person's addresses; only documents in
the inbox or filed (not being read in, not in the trash), only in the vaults the connection was given that the account
is still a member of. The answer is the module's small form: how many, the newest one (title and the document's date),
and where to open them in nexpaper; never contents, never a full address (the module puts nexpaper's in front).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from sqlalchemy import ColumnElement, false, func, or_, select

from ..models import FILED, INBOX, Document, IntakeItem, Sender
from ..names import name_key
from . import rights

#: Where a mail import writes the address it came from (``IntakeItem.detail``, ``services/intake_mail.py``).
_MAIL = "mail"


def _from_person(person: Any) -> ColumnElement[bool]:
    """Documents whose sender is ``person``: by the sender's name, or by the address of the mail they came in with."""
    found: list[ColumnElement[bool]] = []
    if person.name:
        found.append(Document.sender_id.in_(select(Sender.id).where(Sender.key == name_key(person.name))))
    if person.mails:
        sent_from = func.lower(func.trim(func.json_extract(IntakeItem.detail, "$.from")))
        found.append(Document.id.in_(
            select(IntakeItem.document_id).where(IntakeItem.source == _MAIL, IntakeItem.document_id.is_not(None),
                                                 sent_from.in_([mail.lower() for mail in person.mails]))))
    return or_(*found) if found else false()


def about(data: Any, caller: Any, purpose: str, person: Any) -> dict[str, Any]:
    """The module's hook ``router(about=…)``: ``data`` is nexpaper's ``VerbindenStore`` of the request."""
    nothing: dict[str, Any] = {"count": 0, "next": None, "last": None, "open": None}
    if purpose != "documents.about":
        return nothing
    db = data.db
    uid = int(str(caller.account_id))
    clauses = [Document.status.in_((INBOX, FILED)), Document.vault_id.in_(rights.member_vault_ids(uid)),
               _from_person(person)]
    if caller.areas is not None:
        given = {int(str(area)) for area in caller.areas if str(area).isdigit()}
        if not given:
            return nothing
        clauses.append(Document.vault_id.in_(given))
    count = int(db.scalar(select(func.count()).select_from(Document).where(*clauses)) or 0)
    if not count:
        return nothing
    newest = db.scalars(
        select(Document).where(*clauses)
        .order_by(Document.date.is_(None), Document.date.desc(), Document.added_at.desc(), Document.id.desc()).limit(1)
    ).first()
    if newest is None:
        return nothing
    at = (newest.date or newest.added_at.date()).isoformat()
    names = db.scalars(select(Sender.name).join(Document, Document.sender_id == Sender.id).where(*clauses)
                       .group_by(Sender.key).limit(2)).all()
    unsent = db.scalar(select(func.count()).select_from(Document).where(*clauses, Document.sender_id.is_(None)))
    # One sender for all of them: the archive with that sender; else the newest document.
    if len(names) == 1 and not unsent:
        where = "/?sender=" + quote(names[0], safe="")
    else:
        where = f"/dokument/{newest.id}"
    return {"count": count, "next": None, "last": {"title": newest.title, "at": at}, "open": where}


__all__ = ["about"]
