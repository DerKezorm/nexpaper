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
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, and_, exists, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .. import clock
from ..errors import error
from ..models import EDIT, MANAGE, READ, TRASH, Account, Document, Event, Link, Share, VaultMember
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


def maker_may_share() -> ColumnElement[bool]:
    """In a query over ``Link`` joined with ``Document``: the person who made the link still exists, is not blocked and
    may still share the document (a manager of its vault, or its owner who still sees it). A link lives only as long as
    the right of the person who made it."""
    member = exists().where(VaultMember.vault_id == Document.vault_id, VaultMember.user_id == Link.created_by)
    manager = exists().where(VaultMember.vault_id == Document.vault_id, VaultMember.user_id == Link.created_by,
                             VaultMember.right == MANAGE)
    shared = exists().where(Share.document_id == Document.id, Share.user_id == Link.created_by)
    return and_(
        Link.created_by.is_not(None),
        exists().where(Account.id == Link.created_by, Account.blocked_at.is_(None)),
        or_(manager, and_(Document.owner_id == Link.created_by, or_(member, shared))),
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
) -> tuple[Link, str]:
    name = " ".join(recipient.split())
    if not name or len(name) > RECIPIENT_MAX or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise error("invalid_recipient", f"Say who the link is for (1 to {RECIPIENT_MAX} characters).", 422)
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
    token = LINK_PREFIX + secrets.token_urlsafe(32)
    hashed = digest(token)
    link = Link(document_id=document_id, recipient=name, token_hash=hashed,
                token_enc=encrypt_secret(token, _sealed_with(hashed)), until=now + timedelta(days=days),
                allow_download=allow_download, created_by=uid, created_at=now)
    db.add(link)
    access.document.change_seq = changes.next_seq(db)
    changes.record(db, document_id, changes.LINK_CREATED, user_id=uid, detail={"days": days})
    db.commit()
    logger.info("Link made document_id=%s days=%s", document_id, days)
    return link, token


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
