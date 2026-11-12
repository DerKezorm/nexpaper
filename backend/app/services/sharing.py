"""Giving a document to somebody: to a person of this server (a share), or to somebody without an account (a link).

**Shares.** One document, one person, ``read`` or ``edit``. Only the managers of the vault and the person the document
belongs to may share. Somebody who is a member of the vault already needs no share. A share ends when it is removed,
with the document, or with the person.

**Links.** ``lnk_`` and 43 random characters. The token is found by its SHA-256 and kept sealed with the server's secret
(``security.encrypt_secret``), so that its maker and the vault's managers can copy the address again
(``address``); the database alone tells nobody a token. A link shows one document, works until its end date (at most
the operator's number of days, counted again when the operator lowers it), counts how often it was opened, and ends at
once when it is revoked, when the operator switches links off (for all of them, at once), when the document is in the
trash, or when the person who made it may no longer share it (taken out of the vault, blocked, deleted). A token that
does not exist or no longer works answers exactly like any other wrong one (404), and wrong ones count against the
sender on a brake of their own (``deps.link_guard``), apart from the one of the sign-in.

**Further documents (N2).** A link may show up to ``MAX_ALSO`` further documents beside its own, chosen one by one when
it is made, among those that go with its document (``services/related.py``) and that its maker may share by a link of
their own. Nothing comes in later by itself. A further document is shown only while the link works **and** it is out of
the trash, its maker may still share it, and the pair is still set (``also_live``); it leaves the link for good when the
pair is undone, when it is deleted for good, or when somebody who may see its links takes it out (``take_out``). Every
path of a further document checks the token and that the document belongs to the link in one query (``check_also``),
and answers anything else like a wrong token.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, delete, exists, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased

from .. import clock
from ..errors import error
from ..models import (
    EDIT,
    MANAGE,
    READ,
    TRASH,
    Account,
    Document,
    Event,
    Link,
    LinkDocument,
    Related,
    Share,
    VaultMember,
)
from ..security import decrypt_secret, encrypt_secret
from . import changes, rights, settings_service

logger = logging.getLogger("nexpaper.sharing")

LINK_PREFIX = "lnk_"
RECIPIENT_MAX = 100
MAX_LINKS_PER_DOCUMENT = 20
#: The choices for the longest a link may last, in days (the operator picks one).
MAX_DAYS_CHOICES = (7, 14, 30, 90)
#: A link opened again within this time adds to the counter but not to the history again.
OPEN_EVENT_EVERY = timedelta(minutes=10)
#: The further documents one link may show beside its own (N2).
MAX_ALSO = 10
#: The history of a further document: shown with a link of another document, and no longer; of the link's own document:
#: one of its further documents left it (``reason``: ``unlinked``, ``taken_out``, ``purged``; ``revoked`` at the
#: further documents when the link is revoked).
ALSO_SHOWN, ALSO_LEFT, ALSO_GONE = "link_also_shown", "link_also_left", "link_also_gone"


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --- Shares -----------------------------------------------------------------------------------------------------------


def shares_of(db: Session, uid: int, document_id: int) -> list[tuple[Share, Account]]:
    """Who a document is shared with: for those who may share it (the managers of the vault and the owner), like its
    links; a reader or somebody it was shared with does not learn who else has it (403)."""
    if not rights.require_document(db, uid, document_id).can_share:
        raise rights.forbidden()
    return list(db.execute(select(Share, Account).join(Account, Account.id == Share.user_id)
                           .where(Share.document_id == document_id).order_by(Account.name)))


def set_share(db: Session, uid: int, document_id: int, user_id: int, right: str) -> Share:
    if right not in (READ, EDIT):
        raise error("invalid_right", "A share gives read or edit.", 422)
    changes.write_lock(db)
    access = rights.require_document(db, uid, document_id)
    if not access.can_share:
        raise rights.forbidden()
    if user_id == uid:
        raise error("invalid_target", "You cannot share with yourself.", 409)
    account = db.get(Account, user_id)
    if account is None or account.blocked_at is not None:
        raise error("not_found", "Not found.", 404)
    if db.get(VaultMember, (access.document.vault_id, user_id)) is not None:
        raise error("already_in_vault", "This person is in the vault already.", 409)
    if access.document.status == TRASH:
        raise error("in_trash", "Restore the document first.", 409)
    existing = db.get(Share, (document_id, user_id))
    if existing is not None and existing.right == right:
        db.rollback()
        return existing
    db.execute(
        sqlite_insert(Share).values(document_id=document_id, user_id=user_id, right=right, created_by=uid,
                                    created_at=clock.now())
        .on_conflict_do_update(index_elements=["document_id", "user_id"], set_={"right": right})
    )
    access.document.change_seq = changes.next_seq(db)
    changes.record(db, document_id, changes.SHARE_CHANGED if existing else changes.SHARED, user_id=uid,
                   detail={"to": user_id, "right": right})
    db.commit()
    # Read again: the upsert went around the session, which still holds the row as it was.
    return db.get(Share, (document_id, user_id), populate_existing=True)  # type: ignore[return-value]


def remove_share(db: Session, uid: int, document_id: int, user_id: int) -> None:
    changes.write_lock(db)
    access = rights.require_document(db, uid, document_id)
    # The person it was shared with may give it back; otherwise it is for whoever may share.
    if not access.can_share and user_id != uid:
        raise rights.forbidden()
    share = db.get(Share, (document_id, user_id))
    if share is None:
        raise error("not_found", "Not found.", 404)
    db.delete(share)
    access.document.change_seq = changes.next_seq(db)
    changes.tombstone(db, "gone", document_id=document_id, user_id=user_id)
    changes.record(db, document_id, changes.UNSHARED, user_id=uid, detail={"to": user_id})
    db.commit()


# --- Links ------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LinkRules:
    allowed: bool
    max_days: int


def rules(db: Session) -> LinkRules:
    return LinkRules(bool(settings_service.get(db, "links_allowed")),
                     int(settings_service.get(db, "link_max_days") or 30))


def _sealed_with(token_hash: str) -> str:
    """What the sealed token is bound to: its own row (a sealed value moved to another link does not open)."""
    return "link:" + token_hash


def maker_may_share(document: Any = Document) -> ColumnElement[bool]:
    """In a query over ``Link`` joined with ``Document`` (or an alias of it, ``document``): the person who made the link
    still exists, is not blocked and may still share that document (a manager of its vault, or its owner who still sees
    it). A link lives only as long as the right of the person who made it, and so does every further document it
    shows."""
    member = exists().where(VaultMember.vault_id == document.vault_id, VaultMember.user_id == Link.created_by)
    manager = exists().where(VaultMember.vault_id == document.vault_id, VaultMember.user_id == Link.created_by,
                             VaultMember.right == MANAGE)
    shared = exists().where(Share.document_id == document.id, Share.user_id == Link.created_by)
    return and_(
        Link.created_by.is_not(None),
        exists().where(Account.id == Link.created_by, Account.blocked_at.is_(None)),
        or_(manager, and_(document.owner_id == Link.created_by, or_(member, shared))),
    )


def live(now: datetime, max_days: int) -> ColumnElement[bool]:
    """A link that works right now (the operator's switch aside): not revoked, before its end, not older than the
    longest the operator allows now (a lowered limit shortens the links there are), its document out of the trash, and
    its maker still allowed to share."""
    return and_(
        Link.revoked_at.is_(None), Link.until > now, Link.created_at > now - timedelta(days=max_days),
        Document.status != TRASH, maker_may_share(),
    )


def ends(link: Link, max_days: int) -> datetime:
    """When the link stops by itself: its own end, or earlier when the operator's limit is shorter now."""
    return min(link.until, link.created_at + timedelta(days=max_days))


def status_of(link: Link, current: LinkRules, maker_ok: bool) -> str:
    if link.revoked_at is not None:
        return "revoked"
    if not current.allowed:
        return "off"
    if ends(link, current.max_days) <= clock.now():
        return "expired"
    return "active" if maker_ok else "ended"


def may_copy(access: rights.Access, link: Link) -> bool:
    """Who may copy a link's address again: the person who made it, and the managers of the vault."""
    return link.revoked_at is None and (link.created_by == access.uid or access.vault == MANAGE)


def links_of(db: Session, uid: int, document_id: int) -> list[tuple[Link, bool, bool]]:
    """The links of a document, newest first: each with whether its maker may still share it and whether the caller may
    copy its address."""
    access = rights.require_document(db, uid, document_id)
    if not access.can_share:
        raise rights.forbidden()
    rows = db.execute(
        select(Link, maker_may_share()).join(Document, Document.id == Link.document_id)
        .where(Link.document_id == document_id).order_by(Link.id.desc())
    ).all()
    return [(link, bool(ok), may_copy(access, link)) for link, ok in rows]


def create_link(
    db: Session, uid: int, document_id: int, recipient: str, days: int, allow_download: bool,
    also: Sequence[int] = (),
) -> tuple[Link, str]:
    """A new link; ``also`` are further documents it shows (``MAX_ALSO`` at most), each checked like the document
    itself (see ``_check_also``). One that does not pass refuses the whole call; checked and written under the write
    lock, in one transaction."""
    name = " ".join(recipient.split())
    if not name or len(name) > RECIPIENT_MAX or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise error("invalid_recipient", f"Say who the link is for (1 to {RECIPIENT_MAX} characters).", 422)
    wanted = list(dict.fromkeys(also))
    if len(wanted) > MAX_ALSO:
        raise error("invalid_also", f"A link shows at most {MAX_ALSO} further documents.", 422, max=MAX_ALSO)
    changes.write_lock(db)
    access = rights.require_document(db, uid, document_id)
    if not access.can_share:
        raise rights.forbidden()
    current = rules(db)
    if not current.allowed:
        raise error("links_off", "The operator has switched links to the outside off.", 409)
    if not 1 <= days <= current.max_days:
        raise error("invalid_days", f"A link lasts 1 to {current.max_days} days.", 422, max_days=current.max_days)
    if access.document.status == TRASH:
        raise error("in_trash", "Restore the document first.", 409)
    now = clock.now()
    open_ones = db.scalar(select(func.count()).select_from(Link).join(Document, Document.id == Link.document_id).where(
        Link.document_id == document_id, live(now, current.max_days))) or 0
    if open_ones >= MAX_LINKS_PER_DOCUMENT:
        raise error("too_many_links", f"At most {MAX_LINKS_PER_DOCUMENT} open links on a document.", 409)
    others = _check_also(db, uid, access.document, wanted)
    token = LINK_PREFIX + secrets.token_urlsafe(32)
    hashed = digest(token)
    link = Link(document_id=document_id, recipient=name, token_hash=hashed,
                token_enc=encrypt_secret(token, _sealed_with(hashed)), until=now + timedelta(days=days),
                allow_download=allow_download, created_by=uid, created_at=now)
    db.add(link)
    db.flush()
    access.document.change_seq = changes.next_seq(db)
    detail: dict[str, object] = {"days": days}
    if others:
        detail["also"] = len(others)
    changes.record(db, document_id, changes.LINK_CREATED, user_id=uid, detail=detail)
    # Numbered within the link, in the order chosen: what the page and the paths name (never the server's own numbers).
    for number, other in enumerate(others, 1):
        db.add(LinkDocument(link_id=link.id, document_id=other.id, number=number, created_at=now))
        other.change_seq = changes.next_seq(db)
        changes.record(db, other.id, ALSO_SHOWN, user_id=uid, detail={"document": document_id, "days": days})
    db.commit()
    logger.info("Link made document_id=%s days=%s also=%s", document_id, days, len(others))
    return link, token


def _check_also(db: Session, uid: int, document: Document, wanted: list[int]) -> list[Document]:
    """The further documents of a new link, each one: goes with ``document`` (a pair, ``services/related.py``), seen by
    the caller, out of the trash, and the caller may share it by a link of its own (the same right as for the document
    itself). One that fails any of these refuses the whole call with the same answer, whatever the reason: nobody
    learns this way whether a document exists, goes with another, or is in the trash."""
    if not wanted:
        return []
    refused = error("invalid_also", "One of the further documents cannot be shown with this link.", 422)
    if document.id in wanted:
        raise refused
    pairs = {low if high == document.id else high for low, high in db.execute(
        select(Related.low_id, Related.high_id).where(or_(
            and_(Related.low_id == document.id, Related.high_id.in_(wanted)),
            and_(Related.high_id == document.id, Related.low_id.in_(wanted)))))}
    found = []
    for other_id in wanted:
        access = rights.access_to(db, uid, other_id)
        if (other_id not in pairs or access is None or not access.can_share
                or access.document.status == TRASH):
            raise refused
        found.append(access.document)
    return found


def address(db: Session, uid: int, document_id: int, link_id: int) -> str:
    """The token of a link again, for its maker and the managers of the vault: 404 for everybody else, as for a link
    that does not exist. The history says that it was copied (never the token)."""
    changes.write_lock(db)
    access = rights.access_to(db, uid, document_id)
    link = db.scalar(select(Link).where(Link.id == link_id, Link.document_id == document_id))
    if access is None or link is None or not access.can_share or not may_copy(access, link):
        raise error("not_found", "Not found.", 404)
    token = decrypt_secret(link.token_enc, _sealed_with(link.token_hash))
    if not token or digest(token) != link.token_hash:
        # Sealed with a secret.key that is not the one now (a backup restored without it): the link still works, but
        # its address cannot be shown again.
        raise error("link_unreadable", "This address cannot be shown again. Make a new link.", 409)
    _say_copied(db, uid, document_id, link.id)
    db.commit()
    return token


def _say_copied(db: Session, uid: int, document_id: int, link_id: int) -> None:
    """``link_copied`` in the history, at most once in ten minutes for the same person and link (as ``link_opened``):
    clicking again and again must not push the real changes out of sight."""
    since = clock.now() - OPEN_EVENT_EVERY
    recent = db.scalars(select(Event.detail).where(
        Event.document_id == document_id, Event.action == changes.LINK_COPIED, Event.user_id == uid,
        Event.at > since))
    if any(isinstance(detail, dict) and detail.get("link") == link_id for detail in recent):
        return
    changes.record(db, document_id, changes.LINK_COPIED, user_id=uid, detail={"link": link_id})


def revoke_link(db: Session, uid: int, document_id: int, link_id: int) -> None:
    changes.write_lock(db)
    access = rights.require_document(db, uid, document_id)
    link = db.scalar(select(Link).where(Link.id == link_id, Link.document_id == document_id))
    if link is None:
        raise error("not_found", "Not found.", 404)
    if not access.can_share and link.created_by != uid:
        raise rights.forbidden()
    if link.revoked_at is None:
        link.revoked_at = clock.now()
        access.document.change_seq = changes.next_seq(db)
        changes.record(db, document_id, changes.LINK_REVOKED, user_id=uid)
        # The further documents it showed say so too (the rows stay with the link, which shows nothing now).
        for other in db.scalars(select(Document).join(LinkDocument, LinkDocument.document_id == Document.id)
                                .where(LinkDocument.link_id == link.id)):
            other.change_seq = changes.next_seq(db)
            changes.record(db, other.id, ALSO_LEFT, user_id=uid, detail={"document": document_id, "reason": "revoked"})
    db.commit()


def my_links(db: Session, uid: int) -> list[tuple[Link, Document]]:
    """The open links the caller made, on documents they still see."""
    current = rules(db)
    return list(db.execute(
        select(Link, Document).join(Document, Document.id == Link.document_id)
        .where(Link.created_by == uid, live(clock.now(), current.max_days), rights.visible_clause(uid))
        .order_by(Link.until)
    ))


@dataclass(frozen=True)
class Overview:
    open_links: int
    people: int
    next_end: object | None


def overview(db: Session) -> Overview:
    """For the operator: how many links are open and whose, never what they point at."""
    current = rules(db)
    if not current.allowed:
        return Overview(0, 0, None)
    found = db.scalars(select(Link).join(Document, Document.id == Link.document_id)
                       .where(live(clock.now(), current.max_days))).all()
    if not found:
        return Overview(0, 0, None)
    return Overview(len(found), len({r.created_by for r in found}), min(ends(r, current.max_days) for r in found))


# --- The page behind a link ----------------------------------------------------------------------------------------


def open_link(db: Session, token: str, viewer: int | None = None) -> tuple[Link, Document] | None:
    """The link and its document for a token that works right now, else None. Opening counts: the counter goes up, and
    the history of the document says so (at most once in ten minutes for the same link). Not when ``viewer`` (a
    signed-in person) may see the document anyway: the person who made the link looking at it is no opening."""
    # A wrong token never takes the write lock: a flood of guesses must not hold up the people who write.
    found = check_link(db, token)
    if found is None:
        return None
    if viewer is not None and rights.access_to(db, viewer, found[1].id) is not None:
        return found
    changes.write_lock(db)
    db.expire_all()
    # Looked at again under the lock: the link may have been revoked in between.
    found = check_link(db, token)
    if found is None:
        db.rollback()
        return None
    link, document = found
    now = clock.now()
    say_so = link.last_opened_at is None or now - link.last_opened_at >= OPEN_EVENT_EVERY
    db.execute(update(Link).where(Link.id == link.id).values(opened_count=Link.opened_count + 1, last_opened_at=now))
    if say_so:
        changes.record(db, document.id, changes.LINK_OPENED, by_link=link.recipient)
        document.change_seq = changes.next_seq(db)
    db.commit()
    db.refresh(link)
    return link, document


def check_link(db: Session, token: str) -> tuple[Link, Document] | None:
    """The same test without counting: for the file behind the page. Everything is in the query: the switch, the end,
    the trash, the right of the person who made it."""
    if not token.startswith(LINK_PREFIX) or len(token) > 100:
        return None
    current = rules(db)
    if not current.allowed:
        return None
    row = db.execute(
        select(Link, Document).join(Document, Document.id == Link.document_id)
        .where(Link.token_hash == digest(token), live(clock.now(), current.max_days))
    ).first()
    return None if row is None else (row[0], row[1])


# --- Further documents of a link (N2) ------------------------------------------------------------------------------


def _pair_with_own(document: Any) -> ColumnElement[bool]:
    """The further document (``document``, an alias) and the link's own document still go with each other."""
    return exists().where(or_(
        and_(Related.low_id == Link.document_id, Related.high_id == document.id),
        and_(Related.low_id == document.id, Related.high_id == Link.document_id),
    ))


def also_live(document: Any) -> ColumnElement[bool]:
    """In a query over ``Link`` and ``LinkDocument`` with ``document`` (an alias of ``Document``) as the further
    document: it is shown now (the link itself aside). Out of the trash, the person who made the link may still share
    it, and it still goes with the link's own document. Its row is taken out when the pair is undone; the last test
    holds even if a row were left behind."""
    return and_(document.status != TRASH, maker_may_share(document), _pair_with_own(document))


@dataclass(frozen=True)
class Also:
    item: LinkDocument
    document: Document


def shown_also(db: Session, link: Link) -> list[Also]:
    """The further documents a link that works shows now, in the order they were chosen."""
    other = aliased(Document)
    rows = db.execute(
        select(LinkDocument, other).join(other, other.id == LinkDocument.document_id)
        .join(Link, Link.id == LinkDocument.link_id)
        .where(LinkDocument.link_id == link.id, also_live(other)).order_by(LinkDocument.number)
    ).all()
    return [Also(item, document) for item, document in rows]


def also_counts(db: Session, link_ids: list[int]) -> dict[int, int]:
    """How many further documents each of these links shows (would show, while it works): for "shows N more"."""
    if not link_ids:
        return {}
    other = aliased(Document)
    return {int(k): int(v) for k, v in db.execute(
        select(LinkDocument.link_id, func.count()).join(Link, Link.id == LinkDocument.link_id)
        .join(other, other.id == LinkDocument.document_id)
        .where(LinkDocument.link_id.in_(link_ids), also_live(other)).group_by(LinkDocument.link_id)).all()}


def check_also(db: Session, token: str, number: int) -> tuple[Link, Document, Document] | None:
    """For every path of a further document behind a link: the link, its own document and the further one, for a token
    that works right now **and** a further document that belongs to it (by its ``number`` within the link) and is shown
    now, in one query. Anything else is None, and the route answers it as a wrong token."""
    if not token.startswith(LINK_PREFIX) or len(token) > 100:
        return None
    current = rules(db)
    if not current.allowed:
        return None
    other = aliased(Document)
    row = db.execute(
        select(Link, Document, other).join(Document, Document.id == Link.document_id)
        .join(LinkDocument, LinkDocument.link_id == Link.id).join(other, other.id == LinkDocument.document_id)
        .where(Link.token_hash == digest(token), live(clock.now(), current.max_days), LinkDocument.number == number,
               also_live(other))
    ).first()
    return None if row is None else (row[0], row[1], row[2])


def also_link_counts(db: Session, document_ids: list[int]) -> dict[int, int]:
    """Per document, how many links that work now show it as a further document: for ``link_count`` (the sign "link to
    the outside" in the archive), so that nobody has a document open to the outside without seeing it there."""
    if not document_ids:
        return {}
    current = rules(db)
    if not current.allowed:
        return {}
    other = aliased(Document)
    return {int(k): int(v) for k, v in db.execute(
        select(LinkDocument.document_id, func.count()).join(Link, Link.id == LinkDocument.link_id)
        .join(Document, Document.id == Link.document_id).join(other, other.id == LinkDocument.document_id)
        .where(LinkDocument.document_id.in_(document_ids), live(clock.now(), current.max_days), also_live(other))
        .group_by(LinkDocument.document_id)).all()}


@dataclass(frozen=True)
class Through:
    """A link of another document that shows this one: to whom, until when, and the other document when the caller
    may see it (else None: "through another document")."""

    item: LinkDocument
    link: Link
    until: datetime
    own: Document | None


def shown_through(db: Session, uid: int, document_id: int) -> list[Through]:
    """The links of other documents that show this one now, for whoever may see the links of this document (the
    managers of its vault and its owner; 403 for others, 404 for one they cannot see)."""
    access = rights.require_document(db, uid, document_id)
    if not access.can_share:
        raise rights.forbidden()
    current = rules(db)
    if not current.allowed:
        return []
    other = aliased(Document)
    rows = db.execute(
        select(LinkDocument, Link, Document).join(Link, Link.id == LinkDocument.link_id)
        .join(Document, Document.id == Link.document_id).join(other, other.id == LinkDocument.document_id)
        .where(LinkDocument.document_id == document_id, live(clock.now(), current.max_days), also_live(other))
        .order_by(Link.until, LinkDocument.id)
    ).all()
    seen = set(db.scalars(select(Document.id).where(
        Document.id.in_({own.id for _i, _l, own in rows}), rights.visible_clause(uid)))) if rows else set()
    return [Through(item, link, ends(link, current.max_days), own if own.id in seen else None)
            for item, link, own in rows]


def take_out(db: Session, uid: int, document_id: int, item_id: int) -> None:
    """Takes this document out of a link of another document (it can only be shown again by a new link). For whoever
    may see the links of this document; the link stays and shows the rest. Both documents get a line in their history.
    A row that is not there (taken out already, or of another document) is 404.

    ``item_id`` is the row's own number (``ShownThrough.id``), not the number within the link: it is only ever shown
    to a signed-in person who may see the links of this document, and the row names one link of one document at once,
    which the number within a link alone would not (every link starts at 1). Nobody without an account meets it."""
    changes.write_lock(db)
    access = rights.require_document(db, uid, document_id)
    if not access.can_share:
        raise rights.forbidden()
    row = db.execute(select(LinkDocument, Link).join(Link, Link.id == LinkDocument.link_id)
                     .where(LinkDocument.id == item_id, LinkDocument.document_id == document_id)).first()
    if row is None:
        raise error("not_found", "Not found.", 404)
    item, link = row
    db.execute(delete(LinkDocument).where(LinkDocument.id == item.id))
    _say_left(db, uid, link.document_id, document_id, "taken_out")
    db.commit()
    logger.info("A further document was taken out of a link link_id=%s document_id=%s", link.id, document_id)


def _say_left(db: Session, uid: int | None, own_id: int, other_id: int, reason: str) -> None:
    """The lines in the history of both documents when a further document leaves a link."""
    for document_id, action, partner in ((other_id, ALSO_LEFT, own_id), (own_id, ALSO_GONE, other_id)):
        document = db.get(Document, document_id)
        if document is None:
            continue
        document.change_seq = changes.next_seq(db)
        changes.record(db, document_id, action, user_id=uid, detail={"document": partner, "reason": reason})


def pair_undone(db: Session, uid: int | None, a: int, b: int) -> int:
    """``related.unlink``: each of the two leaves the links of the other (in the caller's transaction, under the write
    lock). Returns how many rows went."""
    rows = db.execute(select(LinkDocument.id, Link.document_id, LinkDocument.document_id)
                      .join(Link, Link.id == LinkDocument.link_id).where(or_(
                          and_(Link.document_id == a, LinkDocument.document_id == b),
                          and_(Link.document_id == b, LinkDocument.document_id == a)))).all()
    if not rows:
        return 0
    db.execute(delete(LinkDocument).where(LinkDocument.id.in_([r[0] for r in rows])))
    for _item, own_id, other_id in rows:
        _say_left(db, uid, own_id, other_id, "unlinked")
    return len(rows)


def document_purged(db: Session, document_id: int) -> None:
    """``documents.delete_for_good``: a document deleted for good leaves every link that showed it (the link's own
    document says so in its history), and its own links take their further documents with them. In the caller's
    transaction, before the document's row goes."""
    rows = db.execute(select(LinkDocument.id, Link.document_id).join(Link, Link.id == LinkDocument.link_id)
                      .where(LinkDocument.document_id == document_id)).all()
    for _item, own_id in rows:
        own = db.get(Document, own_id)
        # Not the link's own document when it goes in the same transaction (the trash emptied in one portion).
        if own is not None and own_id != document_id and own not in db.deleted:
            own.change_seq = changes.next_seq(db)
            changes.record(db, own_id, ALSO_GONE, detail={"document": document_id, "reason": "purged"})
    db.execute(delete(LinkDocument).where(or_(
        LinkDocument.document_id == document_id,
        LinkDocument.link_id.in_(select(Link.id).where(Link.document_id == document_id)))))
