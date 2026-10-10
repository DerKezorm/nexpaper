"""What changed, in order: the numbers, the history of a document, and the feed for programs that follow along.

**The numbers.** ``next_seq`` takes the next one from the counter ``change_seq`` inside the transaction that makes the
change. SQLite lets one writer at a time through, and a writer that has taken a number holds the lock until it commits,
so a number becomes visible only after every smaller one: a program that has read up to ``n`` has missed nothing below
it, however many writes run at the same time.

**The feed** (``GET /api/v1/changes?since=n``) lists, in the order of the numbers, the documents the caller may see
whose number is greater than ``n``, and, as small markers without contents, what disappeared for the caller: a document
(moved away, deleted for good, a share ended) and a vault whose rights changed. Both are read in one read transaction
(``snapshot``), so a write that lands between the two reads is in neither and comes on the next page with its number.
A program that starts (``since=0``) gets no markers: it has nothing to drop.

**Markers are kept for 90 days** (``prune_markers``). A program whose number is older than the oldest marker kept may
have missed one and has to start again from 0: the feed answers ``410 sync_from_start``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .. import clock
from ..errors import error
from ..models import Counter, Document, Event, Tombstone, VaultMember
from . import rights, search_index

logger = logging.getLogger("nexpaper.changes")

SEQ = "change_seq"
#: The highest number of a marker that was removed (``prune_markers``): a cursor below it starts again.
PRUNED = "markers_pruned"
MARKER_DAYS = 90
# What the history says. Names are English, the interface translates them.
CREATED, CHANGED, MOVED = "created", "changed", "moved"
SHARED, SHARE_CHANGED, UNSHARED = "shared", "share_changed", "unshared"
LINK_CREATED, LINK_OPENED, LINK_REVOKED = "link_created", "link_opened", "link_revoked"
TRASHED, RESTORED = "trashed", "restored"
NOTE_ADDED, NOTE_CHANGED, NOTE_DELETED = "note_added", "note_changed", "note_deleted"
LINK_COPIED = "link_copied"
#: A document that came to another vault when the account of its owner was deleted (by the operator, who chose where).
TAKEN_OVER = "taken_over"


def write_lock(db: Session) -> None:
    """Takes SQLite's write lock now instead of at the first statement that writes: what a route checks and what it then
    writes belong to one moment, whatever else runs at the same time. A second writer waits here (``busy_timeout``)."""
    raw = db.connection().connection.driver_connection
    if raw is not None and not raw.in_transaction:
        raw.execute("BEGIN IMMEDIATE")


@contextmanager
def snapshot(db: Session) -> Iterator[None]:
    """One read transaction for everything read inside: every query sees the database as it stood at the first one,
    whatever commits in between (WAL keeps the snapshot). Ends without writing anything."""
    raw = db.connection().connection.driver_connection
    began = raw is not None and not raw.in_transaction
    if began:
        raw.execute("BEGIN")
    try:
        yield
    finally:
        if began and raw.in_transaction:
            raw.execute("ROLLBACK")


def next_seqs(db: Session, count: int) -> int:
    """``count`` numbers in a row; returns the first."""
    if count < 1:
        raise ValueError("count")
    statement = (
        sqlite_insert(Counter).values(name=SEQ, value=count)
        .on_conflict_do_update(index_elements=["name"], set_={"value": Counter.value + count})
        .returning(Counter.value)
    )
    last = int(db.execute(statement).scalar_one())
    first = last - count + 1
    # The search index looks at the documents that took a number in this transaction right before it commits
    # (``services/search_index.py``).
    db.info.setdefault(search_index.SEQ_KEY, first)
    return first


def next_seq(db: Session) -> int:
    return next_seqs(db, 1)


def touch(db: Session, document_ids: list[int] | set[int]) -> None:
    """Gives each of the documents a number of its own: a change to something shown with them (a sender's name, a kind),
    or a right that now reaches them."""
    ids = sorted(set(document_ids))
    if not ids:
        return
    first = next_seqs(db, len(ids))
    for offset, document_id in enumerate(ids):
        db.execute(update(Document).where(Document.id == document_id).values(change_seq=first + offset))


def tombstone(db: Session, kind: str, *, document_id: int | None = None, vault_id: int | None = None,
              user_id: int | None = None) -> None:
    db.add(Tombstone(seq=next_seq(db), kind=kind, document_id=document_id, vault_id=vault_id, user_id=user_id,
                     at=clock.now()))


def record(db: Session, document_id: int, action: str, *, user_id: int | None = None, by_link: str = "",
           detail: dict[str, Any] | None = None) -> None:
    """One line in the history of a document. ``detail`` never holds contents, only which fields changed or ids."""
    db.add(Event(document_id=document_id, user_id=user_id, by_link=by_link[:100], at=clock.now(), action=action,
                 detail=detail))


@dataclass
class Item:
    seq: int
    type: str
    document: Document | None = None
    document_id: int | None = None
    vault_id: int | None = None


@dataclass
class Page:
    items: list[Item]
    next: int
    more: bool


def pruned_below(db: Session) -> int:
    return int(db.scalar(select(Counter.value).where(Counter.name == PRUNED)) or 0)


def prune_markers(db: Session) -> int:
    """Removes the markers older than ``MARKER_DAYS`` and remembers the highest number removed. Returns how many."""
    cutoff = clock.now() - timedelta(days=MARKER_DAYS)
    write_lock(db)
    highest = db.scalar(select(func.max(Tombstone.seq)).where(Tombstone.at < cutoff))
    if highest is None:
        db.rollback()
        return 0
    result = db.execute(delete(Tombstone).where(Tombstone.at < cutoff))
    db.execute(
        sqlite_insert(Counter).values(name=PRUNED, value=int(highest))
        .on_conflict_do_update(index_elements=["name"], set_={"value": func.max(Counter.value, int(highest))})
    )
    db.commit()
    count = int(getattr(result, "rowcount", 0) or 0)
    logger.info("Old change markers removed count=%s", count)
    return count


def feed(db: Session, uid: int, since: int, limit: int) -> Page:
    """The changes after ``since`` that concern ``uid``, at most ``limit``, oldest first. ``next`` is the number to ask
    for after this page. Call it inside ``snapshot``: the two parts are read in one statement each, and a page takes
    from both the smallest numbers, so a document that changes between two pages shows up on the later one with its new
    number, never twice."""
    if since > 0 and since < pruned_below(db):
        raise error("sync_from_start", "This number is older than the changes the server keeps. Start again from 0.",
                    410)
    visible = rights.visible_clause(uid)
    documents = list(db.scalars(
        select(Document).where(Document.change_seq > since, visible).order_by(Document.change_seq).limit(limit + 1)
    ))
    mine = select(VaultMember.vault_id).where(VaultMember.user_id == uid)
    member_now = rights.member_vault_ids(uid)
    seen = (
        select(Document.id).where(Document.id == Tombstone.document_id, visible).exists()
    )
    # A program that starts from 0 holds nothing it would have to drop.
    markers = [] if since == 0 else list(db.scalars(
        select(Tombstone).where(
            Tombstone.seq > since,
            (
                (Tombstone.kind == "gone")
                & ((Tombstone.user_id == uid) | (Tombstone.user_id.is_(None) & Tombstone.vault_id.in_(mine)))
                & ~seen
            )
            | ((Tombstone.kind == "vault_lost") & (Tombstone.user_id == uid) & ~Tombstone.vault_id.in_(member_now))
            | ((Tombstone.kind == "vault_refresh") & (Tombstone.user_id == uid) & Tombstone.vault_id.in_(member_now)),
        ).order_by(Tombstone.seq).limit(limit + 1)
    ))
    merged: list[Item] = [Item(seq=d.change_seq, type="document", document=d) for d in documents]
    for marker in markers:
        if marker.kind == "gone":
            merged.append(Item(seq=marker.seq, type="gone", document_id=marker.document_id))
        else:
            merged.append(Item(seq=marker.seq, type=marker.kind, vault_id=marker.vault_id))
    merged.sort(key=lambda item: item.seq)
    more = len(merged) > limit
    merged = merged[:limit]
    return Page(items=merged, next=merged[-1].seq if merged else since, more=more)


def history(db: Session, document_id: int, limit: int = 500) -> list[Event]:
    newest_first = select(Event).where(Event.document_id == document_id).order_by(Event.id.desc()).limit(limit)
    return list(db.scalars(newest_first))

