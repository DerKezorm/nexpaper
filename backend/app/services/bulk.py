"""Many documents changed at once from the archive's table ("Auswählen", A1): a tag added or taken away, a kind, another
vault, the trash.

Every document goes through the very function a single change uses (``documents.change_fields``, ``move_changed``,
``trash_changed``), one after the other, each under the write lock with its own check of the caller's right, its own
line in the history and its own number in the feed. Nothing is built anew here; this module only says what happened.

**Counted honestly.** The answer names every document: changed, or skipped with a reason. ``forbidden`` is both a
document the caller may only read and one they may not see or that does not exist, so that the answer never tells the
two apart (a single change answers 403 or 404; many at once do not). ``in_trash``: it is in the trash (taking it to the
trash again is ``unchanged``). ``kind_elsewhere``: the kind is one of another vault than the document's (a vault's kind
is only for the documents of that vault; the server's kinds go everywhere). ``unchanged``: it was so already.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..errors import error
from ..models import Kind
from . import catalog, documents, rights

logger = logging.getLogger("nexpaper.bulk")

#: The most documents one call takes.
MAX_BULK = 500
ACTIONS = ("add_tag", "remove_tag", "kind", "move", "trash")

FORBIDDEN = "forbidden"
IN_TRASH = "in_trash"
KIND_ELSEWHERE = "kind_elsewhere"
UNCHANGED = "unchanged"


@dataclass
class Outcome:
    changed: list[int] = field(default_factory=list)
    #: (document, reason) of every document that was left as it was.
    skipped: list[tuple[int, str]] = field(default_factory=list)


def _reason(exc: HTTPException) -> str:
    code = exc.detail.get("code", "") if isinstance(exc.detail, dict) else ""
    if code in ("not_found", "forbidden"):
        # A document the caller may only read and one they may not see answer alike here.
        return FORBIDDEN
    if code == "kind_unknown":
        return KIND_ELSEWHERE
    return str(code) or "failed"


def _known_kind(db: Session, uid: int, kind_id: int) -> None:
    """The kind exists and the caller may know it (the server's, or one of a vault they are in); else ``kind_unknown``
    for the whole call, as for a kind that does not exist."""
    catalog.ensure_kinds(db)
    found = db.scalar(select(Kind.id).where(Kind.id == kind_id, or_(
        Kind.vault_id.is_(None), Kind.vault_id.in_(rights.member_vault_ids(uid)))))
    db.rollback()
    if found is None:
        raise error("kind_unknown", "No such kind.", 422)


def change(db: Session, uid: int, ids: list[int], action: str, *, tag: str | None = None, kind_id: int | None = None,
           vault_id: int | None = None) -> Outcome:
    """Does ``action`` to every document of ``ids`` (each once, in the order given) that the caller may change. What
    the action needs is checked first, for the whole call: the tag's name, a kind the caller may know, a vault where
    they may change things (404 or 403 as for a single move)."""
    if action not in ACTIONS:
        raise error("invalid_action", "No such action.", 422)
    if len(ids) > MAX_BULK:
        raise error("too_many", f"At most {MAX_BULK} documents at once.", 422, max=MAX_BULK)
    one: Callable[[int], bool]
    if action in ("add_tag", "remove_tag"):
        if tag is None:
            raise error("invalid_input", "Name the tag.", 422, fields=["tag"])
        name = catalog.clean_word(tag, catalog.TAG_MAX, "invalid_tag")
        key = "add_tags" if action == "add_tag" else "remove_tags"
        one = lambda document_id: bool(documents.change_fields(db, uid, document_id, {key: [name]})[1])
    elif action == "kind":
        if kind_id is None:
            raise error("invalid_input", "Name the kind.", 422, fields=["kind_id"])
        _known_kind(db, uid, kind_id)
        one = lambda document_id: bool(documents.change_fields(db, uid, document_id, {"kind_id": kind_id})[1])
    elif action == "move":
        if vault_id is None:
            raise error("invalid_input", "Name the vault.", 422, fields=["vault_id"])
        rights.require_vault(db, uid, vault_id, rights.EDIT)
        db.rollback()
        one = lambda document_id: documents.move_changed(db, uid, document_id, vault_id)[1]
    else:
        one = lambda document_id: documents.trash_changed(db, uid, document_id)[1]
    outcome = Outcome()
    for document_id in dict.fromkeys(ids):
        try:
            if not 1 <= document_id < 2**31:
                raise error("not_found", "Not found.", 404)
            if one(document_id):
                outcome.changed.append(document_id)
            else:
                outcome.skipped.append((document_id, UNCHANGED))
        except HTTPException as exc:
            # One refusal does not stop the others; what it began is not kept.
            db.rollback()
            outcome.skipped.append((document_id, _reason(exc)))
    logger.info("Documents changed in bulk action=%s by=%s changed=%s skipped=%s", action, uid, len(outcome.changed),
                len(outcome.skipped))
    return outcome


__all__ = ["ACTIONS", "FORBIDDEN", "IN_TRASH", "KIND_ELSEWHERE", "MAX_BULK", "UNCHANGED", "Outcome", "change"]
