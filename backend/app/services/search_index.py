"""Keeping the search index right: every change to a document reaches it in the transaction that makes the change.

**What goes in.** For each document one entry in the word index ``doc_fts`` and one in the trigram index ``doc_tri``
(rowid = document id): its title, the name of its sender, the text of its current version (``version_texts``), its
notes and its tags, and its **scope**: the token of its vault (``v12v``) and one for each person it is shared with
(``u7u``). A search asks the index only for entries in the scope of the caller (``services/search.py``): the index never
reads the entries of documents the caller cannot see, so neither the answer nor the time it takes depends on them. The
rights themselves stay in the query too. Moving a document or sharing it changes its scope (both take a change number,
see below); a person who joins or leaves a vault changes nothing in the index, only the tokens the search asks for.

**When.** Every change to a document takes a number (``changes.next_seq``), the same number the change feed is built
on. The first number a transaction takes is kept on the session (``SEQ_KEY``); right before the transaction commits,
the documents that got a number in it are looked at here (``_before_commit``), still under the write lock and in the
same transaction: a search never sees a document whose index lags behind its fields. A document deleted for good loses
its entries by a trigger (``models.SEARCH_STATEMENTS``).

**Only what changed is written.** Each entry keeps a digest of what went in (``SearchEntry``). A change the index does
not hold (a date, an amount, a right) costs a comparison, no writing.

**Many at once.** A transaction that touched more than ``SYNC_LIMIT`` documents (a sender renamed that is on thousands
of them) does not index them while it holds the lock: a job ``index`` does it right after, in short transactions of
``BATCH`` documents. Until then a search finds those documents by what they were. The same job builds the index of
a database that comes from a version without one (the migration queues it).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, delete, event, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..models import (
    FTS_TABLE,
    TRI_TABLE,
    Document,
    DocumentTag,
    Note,
    SearchEntry,
    Sender,
    Share,
    Tag,
    Version,
    VersionText,
)
from . import searchtext

logger = logging.getLogger("nexpaper.search")

#: Set on a session by ``changes.next_seqs``: the first change number the open transaction took.
SEQ_KEY = "search_from"
#: More documents than this in one transaction are indexed by the job, not under the lock of the change.
SYNC_LIMIT = 200
#: Documents per transaction of the job.
BATCH = 200
#: The job's kind (``services/jobs.py``).
JOB = "index"
#: Between the parts of what the digest is made of.
SEPARATOR = chr(31)


@dataclass
class Fields:
    title: str
    sender: str
    text: str
    notes: str
    tags: str
    text_digest: str
    #: ``v<vault>v`` and ``u<person>u`` for each person it is shared with.
    scope: str = ""

    def digest(self) -> str:
        joined = SEPARATOR.join((self.title, self.sender, self.text_digest, self.notes, self.tags, self.scope))
        return hashlib.sha1(joined.encode("utf-8"), usedforsecurity=False).hexdigest()


def text_digest(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8"), usedforsecurity=False).hexdigest()


def vault_token(vault_id: int) -> str:
    return f"v{int(vault_id)}v"


def person_token(user_id: int) -> str:
    return f"u{int(user_id)}u"


def gather(db: Session, ids: list[int], with_text: bool = True) -> dict[int, Fields]:
    """What the index holds for these documents, in a few queries for all of them."""
    if not ids:
        return {}
    rows = db.execute(
        select(Document.id, Document.vault_id, Document.title, Sender.name, VersionText.digest,
               VersionText.text if with_text else func.length(VersionText.text))
        .outerjoin(Sender, Sender.id == Document.sender_id)
        .outerjoin(Version, (Version.document_id == Document.id) & (Version.n == Document.current_version))
        .outerjoin(VersionText, VersionText.version_id == Version.id)
        .where(Document.id.in_(ids))
    ).all()
    notes: dict[int, list[str]] = {}
    for document_id, body in db.execute(select(Note.document_id, Note.text).where(Note.document_id.in_(ids))
                                        .order_by(Note.id)):
        notes.setdefault(document_id, []).append(body)
    tags: dict[int, list[str]] = {}
    named = select(DocumentTag.document_id, Tag.name).join(Tag, Tag.id == DocumentTag.tag_id)
    for document_id, name in db.execute(named.where(DocumentTag.document_id.in_(ids)).order_by(Tag.name)):
        tags.setdefault(document_id, []).append(name)
    shared: dict[int, list[int]] = {}
    for document_id, user_id in db.execute(select(Share.document_id, Share.user_id).where(Share.document_id.in_(ids))
                                           .order_by(Share.user_id)):
        shared.setdefault(document_id, []).append(user_id)
    out = {}
    for document_id, vault_id, title, sender, digest, body in rows:
        out[document_id] = Fields(
            title=title or "", sender=sender or "", text=(body if with_text and body else "").replace("\f", "\n"),
            notes="\n".join(notes.get(document_id, [])), tags=" ".join(tags.get(document_id, [])),
            text_digest=digest or "",
            scope=" ".join([vault_token(vault_id), *(person_token(u) for u in shared.get(document_id, []))]),
        )
    return out


def _write(db: Session, document_id: int, fields: Fields) -> None:
    values = {
        "id": document_id, "title": searchtext.for_index(fields.title), "sender": searchtext.for_index(fields.sender),
        "text": searchtext.for_index(fields.text), "notes": searchtext.for_index(fields.notes),
        "tags": searchtext.for_index(fields.tags), "scope": fields.scope,
    }
    for table in (FTS_TABLE, TRI_TABLE):
        db.execute(text(f"DELETE FROM {table} WHERE rowid = :id"), {"id": document_id})  # noqa: S608 - constant name
        db.execute(text(f"INSERT INTO {table} (rowid, title, sender, text, notes, tags, scope) "  # noqa: S608
                        "VALUES (:id, :title, :sender, :text, :notes, :tags, :scope)"), values)


def refresh(db: Session, ids: Iterable[int]) -> int:
    """Brings the entries of these documents up to date (a document that is gone is skipped: the trigger took its
    entries). Returns how many entries were written anew. The caller holds the write lock and commits."""
    wanted = sorted(set(ids))
    written = 0
    for start in range(0, len(wanted), BATCH):
        chunk = wanted[start : start + BATCH]
        stored = dict(db.execute(select(SearchEntry.document_id, SearchEntry.digest)
                                 .where(SearchEntry.document_id.in_(chunk))).all())
        seqs = dict(db.execute(select(Document.id, Document.change_seq).where(Document.id.in_(chunk))).all())
        # The digest is made from the text's own digest: the text itself is fetched only for the entries to write.
        light = gather(db, chunk, with_text=False)
        stale = [i for i, fields in light.items() if stored.get(i) != fields.digest()]
        full = gather(db, stale) if stale else {}
        for document_id, fields in full.items():
            _write(db, document_id, fields)
            written += 1
        for document_id, fields in light.items():
            entry = {"seq": seqs[document_id], "digest": fields.digest()}
            db.execute(sqlite_insert(SearchEntry).values(document_id=document_id, **entry)
                       .on_conflict_do_update(index_elements=["document_id"], set_=entry))
    return written


def stale_ids(db: Session, limit: int) -> list[int]:
    """Documents whose entry is missing or older than their last change."""
    return list(db.scalars(
        select(Document.id).outerjoin(SearchEntry, SearchEntry.document_id == Document.id)
        .where((SearchEntry.document_id.is_(None)) | (SearchEntry.seq != Document.change_seq))
        .order_by(Document.id).limit(limit)
    ))


def run_job(db: Session) -> int:
    """The job ``index``: every document whose entry lags behind, ``BATCH`` per transaction. Returns how many entries
    were written anew."""
    from . import changes

    written = 0
    while True:
        changes.write_lock(db)
        ids = stale_ids(db, BATCH)
        if not ids:
            db.rollback()
            break
        written += refresh(db, ids)
        db.commit()
    if written:
        logger.info("Search index brought up to date entries=%s", written)
    return written


def queue_if_stale(db: Session) -> None:
    """At the start: a job when any document has no current entry (a database from before the index, a stop in
    between)."""
    from . import jobs

    if stale_ids(db, 1):
        jobs.enqueue(db, JOB, 0)
        db.commit()


def _before_commit(session: Session) -> None:
    first = session.info.pop(SEQ_KEY, None)
    if first is None:
        return
    session.flush()
    ids = list(session.scalars(select(Document.id).where(Document.change_seq >= first)))
    if not ids:
        return
    if len(ids) > SYNC_LIMIT:
        from . import jobs

        jobs.enqueue(session, JOB, 0)
        return
    refresh(session, ids)


def _forget(session: Session, *_args: Any) -> None:
    session.info.pop(SEQ_KEY, None)


event.listen(Session, "before_commit", _before_commit)
event.listen(Session, "after_rollback", _forget)
event.listen(Session, "after_soft_rollback", _forget)


@event.listens_for(Engine, "connect")
def _functions(dbapi_connection: Any, _record: Any) -> None:
    """``nx_fold`` for the check of a word found in the middle (``services/search.py``): as the index compares."""
    create = getattr(dbapi_connection, "create_function", None)
    if create is not None:
        create("nx_fold", 1, lambda value: searchtext.fold(value) if isinstance(value, str) else value,
               deterministic=True)


def remove(db: Session, document_id: int) -> None:
    """Drops a document's entries (the trigger does it when the row goes; this is for tests and repairs)."""
    for table in (FTS_TABLE, TRI_TABLE):
        db.execute(text(f"DELETE FROM {table} WHERE rowid = :id"), {"id": document_id})  # noqa: S608
    db.execute(delete(SearchEntry).where(SearchEntry.document_id == document_id))


__all__ = ["BATCH", "JOB", "SEQ_KEY", "SYNC_LIMIT", "Fields", "gather", "queue_if_stale", "refresh", "remove",
           "run_job", "stale_ids", "text_digest"]
