"""Documents: reading, changing fields, moving between vaults, the trash, notes.

Every change runs under the write lock (``changes.write_lock``): the right is checked and the change written in one
moment, so a person who loses a right a moment before cannot still write, and two changes to one document never mix.
Every change takes a number (``Document.change_seq``) and leaves a line in the history (``Event``). Fields that appear
in a file name (sender, kind, date, vault) queue a ``rename`` job in the same transaction.

Making a document from a file: ``create`` (bytes in memory, for the tests and small things) and ``create_from_file`` (a
file that was streamed to the disk, which every upload ends in).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date as Date
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, exists, func, select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import error
from ..models import (
    DATE_KINDS,
    EDIT,
    FILED,
    INBOX,
    MANAGE,
    PROCESSING,
    READ,
    TRASH,
    Account,
    Document,
    DocumentDate,
    DocumentTag,
    Kind,
    Link,
    Note,
    Sender,
    Share,
    Tag,
    Vault,
    VaultMember,
    Version,
)
from ..names import name_key
from . import catalog, changes, filecheck, filetypes, jobs, keeping, rights, storage

logger = logging.getLogger("nexpaper.documents")

TRASH_DAYS = 30
TITLE_MAX = 200
NOTE_MAX = 5000
AMOUNT_LIMIT = 10**12
DATE_MIN, DATE_MAX = Date(1900, 1, 1), Date(2200, 12, 31)
SOURCES = ("upload", "camera", "mail", "folder", "share", "paperless", "api")
#: The statuses a person may set by hand: filing a document or putting it back in the inbox.
SETTABLE = (INBOX, FILED)


#: Characters that turn the direction of text around: taken out of every title (a note keeps them, it is prose).
BIDI_CONTROLS = filetypes.BIDI_CONTROLS


def clean_title(value: str) -> str:
    value = value.translate(BIDI_CONTROLS)
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise error("invalid_title", "A title cannot hold control characters.", 422)
    title = " ".join(value.split())
    if not title or len(title) > TITLE_MAX:
        raise error("invalid_title", f"Use 1 to {TITLE_MAX} characters.", 422)
    return title


def check_date(value: Date | None, field: str = "date") -> Date | None:
    """The date, or ``invalid_date`` naming the ``field`` it came in (``date``, or ``dates[n]`` for the n-th term)."""
    if value is not None and not (DATE_MIN <= value <= DATE_MAX):
        raise error("invalid_date", "This date is out of range.", 422, field=field)
    return value


def check_amount(value: int | None) -> int | None:
    if value is not None and abs(value) > AMOUNT_LIMIT:
        raise error("invalid_amount", "This amount is out of range.", 422)
    return value


# --- Reading ----------------------------------------------------------------------------------------------------------


@dataclass
class Row:
    """A document with everything its answer shows, loaded for a whole page at once."""

    document: Document
    owner: Account | None
    sender: Sender | None
    kind: Kind | None
    tags: list[str]
    dates: list[tuple[str, Date]]
    right: str
    via_share: bool
    can_share: bool
    notes: int
    #: The document this one repeats or looks like, when the caller may see it (else nothing).
    duplicate: Document | None = None
    #: A split at blank separator pages is proposed (``services/separators.py``).
    split: bool = False
    #: People it is shared with and links that work now; only for a caller who may share it (else nothing).
    share_count: int | None = None
    link_count: int | None = None
    #: The format of its e-invoice, when it carries one (``services/einvoices.py``); empty else.
    einvoice: str = ""
    #: Its ``keep_until`` was set by a person, not worked out from the kind (``services/keeping.py``).
    keep_by_hand: bool = False


def rows(db: Session, uid: int, documents: list[Document]) -> list[Row]:
    """The answers for a list of documents the caller may see: rights, names and tags fetched in a few queries, not one
    per document."""
    if not documents:
        return []
    ids = [d.id for d in documents]
    members = dict(db.execute(select(VaultMember.vault_id, VaultMember.right).where(VaultMember.user_id == uid)).all())
    shares = dict(db.execute(select(Share.document_id, Share.right).where(
        Share.user_id == uid, Share.document_id.in_(ids))).all())
    owners = {a.id: a for a in db.scalars(select(Account).where(
        Account.id.in_({d.owner_id for d in documents if d.owner_id})))}
    senders = {s.id: s for s in db.scalars(select(Sender).where(
        Sender.id.in_({d.sender_id for d in documents if d.sender_id})))}
    kind_ids = {d.kind_id for d in documents if d.kind_id}
    kind_rows = {k.id: k for k in db.scalars(select(Kind).where(Kind.id.in_(kind_ids)))}
    tags: dict[int, list[str]] = {i: [] for i in ids}
    for document_id, name in db.execute(
        select(DocumentTag.document_id, Tag.name).join(Tag, Tag.id == DocumentTag.tag_id)
        .where(DocumentTag.document_id.in_(ids)).order_by(func.lower(Tag.name))
    ):
        tags[document_id].append(name)
    dates: dict[int, list[tuple[str, Date]]] = {i: [] for i in ids}
    by_hand: set[int] = set()
    for row in db.scalars(select(DocumentDate).where(DocumentDate.document_id.in_(ids)).order_by(DocumentDate.date)):
        dates[row.document_id].append((row.kind, row.date))
        if row.kind == keeping.KEEP and row.manual:
            by_hand.add(row.document_id)
    notes = dict(db.execute(select(Note.document_id, func.count()).where(Note.document_id.in_(ids))
                            .group_by(Note.document_id)).all())
    wanted = {d.duplicate_of for d in documents if d.duplicate_of}
    twins = {t.id: t for t in db.scalars(select(Document).where(
        Document.id.in_(wanted), Document.status != TRASH, rights.visible_clause(uid)))} if wanted else {}
    from . import separators

    split = separators.suggested(db, documents)
    accesses = {d.id: rights.Access(document=d, vault=members.get(d.vault_id), share=shares.get(d.id), uid=uid)
                for d in documents}
    shared_counts, link_counts = _sharing_counts(db, [i for i, a in accesses.items() if a.can_share])
    from . import einvoices

    invoices = einvoices.formats(db, ids)
    out = []
    for document in documents:
        access = accesses[document.id]
        out.append(Row(
            document=document, owner=owners.get(document.owner_id) if document.owner_id else None,
            sender=senders.get(document.sender_id) if document.sender_id else None,
            kind=kind_rows.get(document.kind_id) if document.kind_id else None, tags=tags[document.id],
            dates=dates[document.id], right=access.right, via_share=access.vault is None,
            can_share=access.can_share, notes=int(notes.get(document.id, 0)),
            duplicate=twins.get(document.duplicate_of) if document.duplicate_of else None,
            split=document.id in split,
            share_count=shared_counts.get(document.id, 0) if access.can_share else None,
            link_count=link_counts.get(document.id, 0) if access.can_share else None,
            einvoice=invoices.get(document.id, ""), keep_by_hand=document.id in by_hand,
        ))
    return out


def _sharing_counts(db: Session, ids: list[int]) -> tuple[dict[int, int], dict[int, int]]:
    """For the documents the caller may share (the same right as ``/shares`` and ``/links``): how many people each is
    shared with, and how many of its links work right now. Two grouped counts for a whole page."""
    if not ids:
        return {}, {}
    from . import sharing

    people = dict(db.execute(select(Share.document_id, func.count()).where(Share.document_id.in_(ids))
                             .group_by(Share.document_id)).all())
    current = sharing.rules(db)
    links: dict[int, int] = {}
    if current.allowed:
        links = dict(db.execute(
            select(Link.document_id, func.count()).join(Document, Document.id == Link.document_id)
            .where(Link.document_id.in_(ids), sharing.live(clock.now(), current.max_days))
            .group_by(Link.document_id)).all())
    return {k: int(v) for k, v in people.items()}, {k: int(v) for k, v in links.items()}


def one(db: Session, uid: int, document_id: int, need: str = READ) -> tuple[rights.Access, Row]:
    access = rights.require_document(db, uid, document_id, need)
    return access, rows(db, uid, [access.document])[0]


def listing(
    db: Session, uid: int, *, vault_id: int | None, status: str | None, after: int, limit: int,
    via_share: bool | None = None, sender: str | None = None, tag: str | None = None,
) -> list[Document]:
    """Documents the caller may see, by id, ``limit`` of them after the id ``after``. A vault the caller is not in is
    simply empty, like one that does not exist. ``via_share``: only those the caller sees through a share alone (true)
    or only those of their vaults (false). ``sender`` and ``tag`` filter by name across the vaults (the same name in
    two vaults is two rows, one filter)."""
    query = select(Document).where(rights.visible_clause(uid), Document.id > after)
    if vault_id is not None:
        query = query.where(Document.vault_id == vault_id)
    if via_share is not None:
        in_vault = Document.vault_id.in_(rights.member_vault_ids(uid))
        query = query.where(~in_vault if via_share else in_vault)
    if sender is not None:
        query = query.where(Document.sender_id.in_(select(Sender.id).where(Sender.key == name_key(sender.strip()))))
    if tag is not None:
        query = query.where(exists().where(
            DocumentTag.document_id == Document.id, DocumentTag.tag_id == Tag.id, Tag.key == name_key(tag.strip())))
    if status is not None:
        query = query.where(Document.status == status)
    else:
        query = query.where(Document.status != TRASH)
    return list(db.scalars(query.order_by(Document.id).limit(limit)))


# --- Making -----------------------------------------------------------------------------------------------------------


def create(
    db: Session, *, vault_id: int, owner_id: int | None, title: str, sender: str | None = None,
    kind_id: int | None = None,
    date: Date | None = None, amount: int | None = None, status: str = FILED, source: str = "upload",
    content: bytes | None = None, extension: str = ".pdf", pages: int = 1, tags: list[str] | None = None,
    dates: list[tuple[str, Date]] | None = None, created_by: int | None = None,
) -> Document:
    """A document, with its file when ``content`` is given. The file is written first to a name that cannot clash and
    put in place without overwriting; the rows follow, so a failure leaves at worst a file the check of files finds."""
    if status not in (PROCESSING, INBOX, FILED):
        raise ValueError("status")
    if source not in SOURCES:
        raise ValueError("source")
    changes.write_lock(db)
    vault = db.get(Vault, vault_id)
    if vault is None:
        raise error("not_found", "Not found.", 404)
    document = Document(
        vault_id=vault_id, owner_id=owner_id, title=clean_title(title), date=check_date(date),
        amount=check_amount(amount), status=status, source=source, added_at=clock.now(), pages=pages if content else 0,
        change_seq=changes.next_seq(db),
    )
    if sender:
        document.sender_id = catalog.sender_named(db, vault_id, owner_id, sender).id
    if kind_id is not None:
        document.kind_id = catalog.kind_in_scope(db, kind_id, vault_id).id
    db.add(document)
    db.flush()
    for tag in catalog.tags_named(db, vault_id, owner_id, tags or []):
        db.add(DocumentTag(document_id=document.id, tag_id=tag.id))
    _set_dates(db, document, dates or [])
    keeping.refresh(db, [document.id])
    changes.record(db, document.id, changes.CREATED, user_id=created_by or owner_id, detail={"source": source})
    if content is not None:
        import hashlib

        extension = extension.lower() if extension.lower() in filetypes.KIND_OF_EXTENSION else ".pdf"
        db.flush()
        parts = storage.parts_for(db, document)
        name = parts.stem + extension
        counter = 1
        while storage.name_taken(db, parts.folders, name, set()):
            counter += 1
            name = f"{parts.stem} ({counter}){extension}"
        rel = "/".join((*parts.folders, name))
        storage.write_new(rel, content)
        db.add(Version(document_id=document.id, n=1, original_path=rel, sha256=hashlib.sha256(content).hexdigest(),
                       size=len(content), pages=pages, created_by=owner_id, created_at=clock.now(),
                       note=source))
    db.commit()
    return document


def create_from_file(
    db: Session, *, vault_id: int, owner_id: int | None, title: str, source: str, path: Path, kind: str, sha256: str,
    size: int, same_as: int | None = None, created_by: int | None = None,
    also: Callable[[Session, Document], None] | None = None, detail: dict[str, Any] | None = None,
) -> Document:
    """A document made of a file that is complete on the disk (``path``, any place on the disk; it is moved, so it is
    gone from there afterwards). It stands as ``processing`` and a job to read it is queued in the same transaction; the
    file is read by the worker (``services/processing.py``). ``same_as``: the document that has the very same file,
    which the person may see (found by the caller, who knows who is looking). The file is put in place first, without
    overwriting; the rows follow, and when they fail the file goes again. ``also`` adds rows of the caller to the same
    transaction (the intake folder and the mailbox note what they took, so that a restart never takes it twice).
    ``detail``: more for the history entry of the creation (it names the ``source`` itself)."""
    if source not in SOURCES:
        raise ValueError("source")
    extension = filetypes.EXTENSION[kind]
    changes.write_lock(db)
    vault = db.get(Vault, vault_id)
    if vault is None:
        path.unlink(missing_ok=True)
        raise error("not_found", "Not found.", 404)
    document = Document(
        vault_id=vault_id, owner_id=owner_id, title=clean_title(title), status=PROCESSING, source=source,
        added_at=clock.now(), pages=0, change_seq=changes.next_seq(db),
        duplicate_of=same_as, duplicate_kind="same" if same_as else "",
    )
    db.add(document)
    db.flush()
    changes.record(db, document.id, changes.CREATED, user_id=created_by or owner_id,
                   detail={**(detail or {}), "source": source})
    parts = storage.parts_for(db, document)
    rel = "/".join((*parts.folders, storage.free_name(db, parts.folders, parts.stem + extension)))
    placed = storage.adopt(path, rel)
    try:
        db.add(Version(document_id=document.id, n=1, original_path=rel, sha256=sha256, size=size, pages=0,
                       created_by=owner_id, created_at=clock.now(), note=source))
        jobs.enqueue(db, jobs.PROCESS, document.id)
        if also is not None:
            also(db, document)
        db.commit()
    except Exception:
        db.rollback()
        placed.unlink(missing_ok=True)
        raise
    return document


def _set_dates(db: Session, document: Document, dates: list[tuple[str, Date]],
               manual: dict[str, bool | None] | None = None) -> bool:
    """Replaces the dated terms of a document; True when something changed. ``keep_until`` is set by hand when it is
    sent, unless ``manual`` says how it was meant (``keeping.take``); left out, it is worked out from the kind."""
    wanted: dict[str, Date] = {}
    for index, (kind, day) in enumerate(dates):
        if kind not in DATE_KINDS:
            raise error("invalid_date_kind", "No such kind of date.", 422, field=f"dates[{index}]")
        wanted[kind] = check_date(day, f"dates[{index}]")  # type: ignore[assignment]
    kept = keeping.take(db, document, wanted.pop(keeping.KEEP, None), (manual or {}).get(keeping.KEEP))
    current = {row.kind: row for row in db.scalars(select(DocumentDate).where(
        DocumentDate.document_id == document.id, DocumentDate.kind != keeping.KEEP))}
    if {k: r.date for k, r in current.items()} == wanted:
        return kept
    for kind, row in current.items():
        if kind not in wanted:
            db.delete(row)
    for kind, day in wanted.items():
        if kind in current:
            current[kind].date = day
        else:
            db.add(DocumentDate(document_id=document.id, kind=kind, date=day))
    return True


# --- Changing ---------------------------------------------------------------------------------------------------------


def update_fields(db: Session, uid: int, document_id: int, patch: dict[str, Any]) -> Document:
    """Changes the fields named in ``patch`` (only those). Returns the document; the history records which fields
    changed, never their values."""
    changes.write_lock(db)
    access = rights.require_document(db, uid, document_id, EDIT)
    document = access.document
    if document.status == TRASH:
        raise error("in_trash", "Restore the document first.", 409)
    changed: list[str] = []
    rename = False
    if "title" in patch:
        title = clean_title(patch["title"])
        if title != document.title:
            document.title = title
            changed.append("title")
    old_sender = document.sender_id
    old_tags: set[int] = set()
    if "sender" in patch:
        name = patch["sender"]
        new_id = catalog.sender_named(db, document.vault_id, uid, name).id if name else None
        if new_id != document.sender_id:
            document.sender_id = new_id
            changed.append("sender")
            rename = True
    if "kind_id" in patch:
        new_kind = (catalog.kind_in_scope(db, patch["kind_id"], document.vault_id).id
                    if patch["kind_id"] is not None else None)
        if new_kind != document.kind_id:
            document.kind_id = new_kind
            changed.append("kind")
            rename = True
    if "date" in patch:
        day = check_date(patch["date"])
        if day != document.date:
            document.date = day
            changed.append("date")
            rename = True
    if "amount" in patch:
        amount = check_amount(patch["amount"])
        if amount != document.amount:
            document.amount = amount
            changed.append("amount")
    if "status" in patch:
        if patch["status"] not in SETTABLE:
            raise error("invalid_status", "A document can be put in the inbox or filed.", 422)
        if document.status == PROCESSING:
            raise error("still_processing", "The document is still being read.", 409)
        if patch["status"] != document.status:
            document.status = patch["status"]
            changed.append("status")
    if "tags" in patch:
        wanted = {t.id for t in catalog.tags_named(db, document.vault_id, uid, patch["tags"])}
        have = set(db.scalars(select(DocumentTag.tag_id).where(DocumentTag.document_id == document.id)))
        old_tags = have - wanted
        if wanted != have:
            db.execute(delete(DocumentTag).where(DocumentTag.document_id == document.id,
                                                 DocumentTag.tag_id.not_in(wanted)))
            for tag_id in wanted - have:
                db.add(DocumentTag(document_id=document.id, tag_id=tag_id))
            changed.append("tags")
    if "dates" in patch and _set_dates(db, document, [(d["kind"], d["date"]) for d in patch["dates"]],
                                       {d["kind"]: d.get("manual") for d in patch["dates"]}):
        changed.append("dates")
    # Worked out from the kind again (another kind, another date, filed now, or taken back from a person): unless the
    # terms changed anyway, a field of its own in the history.
    worked_out = {"kind", "date", "status", "dates"} & set(changed) and keeping.refresh(db, [document.id])
    if worked_out and "dates" not in changed:
        changed.append(keeping.KEEP)
    if not changed:
        db.rollback()
        return document
    document.change_seq = changes.next_seq(db)
    _theirs(document, changed)
    detail: dict[str, Any] = {"fields": changed}
    if "status" in changed:
        # Where it went (filed, or back to the inbox): the history says "filed" instead of "changed the status".
        detail["status"] = document.status
    changes.record(db, document.id, changes.CHANGED, user_id=uid, detail=detail)
    if rename:
        jobs.enqueue(db, jobs.RENAME, document.id)
    catalog.prune(db, [old_sender] if old_sender != document.sender_id else [], old_tags)
    db.commit()
    return document


def _theirs(document: Document, fields: list[str]) -> None:
    """A field a person changed while the document waits is theirs: nothing proposed later touches it
    (``services/sorting.py``)."""
    if document.status in (PROCESSING, INBOX):
        from . import sorting

        sorting.mark_person(document, fields)


def move(db: Session, uid: int, document_id: int, target_vault_id: int) -> Document:
    """To another vault: the caller needs ``edit`` in both (through the vault, a share is not enough to take a document
    out of the place it is kept)."""
    changes.write_lock(db)
    access = rights.require_document(db, uid, document_id, EDIT)
    document = access.document
    if not rights.at_least(access.vault, EDIT):
        raise rights.forbidden()
    if document.status == TRASH:
        raise error("in_trash", "Restore the document first.", 409)
    rights.require_vault(db, uid, target_vault_id, EDIT)
    if target_vault_id == document.vault_id:
        db.rollback()
        return document
    source = document.vault_id
    document.vault_id = target_vault_id
    _theirs(document, ["vault"])
    # Sender and tags are the vault's own: the document takes the target vault's of the same names.
    catalog.rehome(db, [document.id], target_vault_id)
    # The members of the old vault who cannot see it in the new one lose it; the feed finds out which by looking.
    changes.tombstone(db, "gone", document_id=document.id, vault_id=source)
    document.change_seq = changes.next_seq(db)
    changes.record(db, document.id, changes.MOVED, user_id=uid, detail={"from": source, "to": target_vault_id})
    jobs.enqueue(db, jobs.RENAME, document.id)
    db.commit()
    return document


def trash(db: Session, uid: int, document_id: int) -> Document:
    changes.write_lock(db)
    access = rights.require_document(db, uid, document_id, EDIT)
    document = access.document
    if document.status == TRASH:
        db.rollback()
        return document
    document.trashed_status = document.status if document.status in (INBOX, FILED) else FILED
    document.status = TRASH
    document.trashed_at = clock.now()
    document.change_seq = changes.next_seq(db)
    changes.record(db, document.id, changes.TRASHED, user_id=uid)
    # Links stop with the trash (checked when one is opened); nothing else changes.
    db.commit()
    return document


def restore(db: Session, uid: int, document_id: int) -> Document:
    changes.write_lock(db)
    access = rights.require_document(db, uid, document_id, EDIT)
    document = access.document
    if document.status != TRASH:
        db.rollback()
        return document
    document.status = document.trashed_status or FILED
    document.trashed_at = None
    document.trashed_status = ""
    document.change_seq = changes.next_seq(db)
    changes.record(db, document.id, changes.RESTORED, user_id=uid)
    filecheck.recheck_soon(db, document)
    db.commit()
    return document


def purge(db: Session, uid: int, document_id: int) -> None:
    """A document in the trash deleted for good before its days are over: by a manager of its vault, or by the person it
    belongs to while they may change it. Nothing of it stays (no history either), so it is said in the log."""
    changes.write_lock(db)
    access = rights.require_document(db, uid, document_id, EDIT)
    document = access.document
    if access.vault != MANAGE and document.owner_id != uid:
        raise rights.forbidden()
    if document.status != TRASH:
        raise error("not_in_trash", "Put the document in the trash first.", 409)
    vault_id = document.vault_id
    delete_for_good(db, document)
    db.commit()
    logger.info("Document deleted for good document_id=%s vault_id=%s by=%s", document_id, vault_id, uid)


def purge_expired(db: Session) -> int:
    """Deletes for good what has been in the trash for ``TRASH_DAYS`` days: rows now, files in the background (a job
    queued in the same transaction, so a restart in between loses nothing). Returns how many documents went."""
    cutoff = clock.now() - timedelta(days=TRASH_DAYS)
    gone = 0
    while True:
        changes.write_lock(db)
        batch = list(db.scalars(select(Document).where(Document.status == TRASH, Document.trashed_at <= cutoff)
                                .order_by(Document.id).limit(50)))
        if not batch:
            db.rollback()
            return gone
        for document in batch:
            delete_for_good(db, document)
            gone += 1
        db.commit()
        logger.info("Trash emptied documents=%s", len(batch))


def delete_for_good(db: Session, document: Document) -> None:
    """The rows of a document now (in the caller's transaction, under the write lock), its files in the background (a
    job in the same transaction, so a restart in between loses nothing). Whoever saw it gets a ``gone`` marker."""
    paths = []
    for version in db.scalars(select(Version).where(Version.document_id == document.id)):
        paths.extend(p for p in (version.original_path, version.archive_path) if p)
    changes.tombstone(db, "gone", document_id=document.id, vault_id=document.vault_id)
    for user_id in db.scalars(select(Share.user_id).where(Share.document_id == document.id)):
        changes.tombstone(db, "gone", document_id=document.id, user_id=user_id)
    # The pictures kept in the cache go with it (they would be made again from the file, which is gone).
    jobs.enqueue(db, jobs.DELETE_FILES, document.id, {"paths": paths, "cache_of": document.id})
    sender_id = document.sender_id
    tag_ids = list(db.scalars(select(DocumentTag.tag_id).where(DocumentTag.document_id == document.id)))
    db.delete(document)
    catalog.prune(db, [sender_id], tag_ids)


# --- Notes ------------------------------------------------------------------------------------------------------------


def clean_note(value: str) -> str:
    text = value.replace("\r\n", "\n").strip()
    if any((ord(char) < 32 and char not in "\n\t") or ord(char) == 127 for char in text):
        raise error("invalid_note", "A note cannot hold control characters.", 422)
    if not text or len(text) > NOTE_MAX:
        raise error("invalid_note", f"Use 1 to {NOTE_MAX} characters.", 422)
    return text


def notes_of(db: Session, uid: int, document_id: int) -> list[tuple[Note, Account | None]]:
    rights.require_document(db, uid, document_id)
    return [(n, db.get(Account, n.user_id) if n.user_id else None)
            for n in db.scalars(select(Note).where(Note.document_id == document_id).order_by(Note.id))]


def add_note(db: Session, uid: int, document_id: int, text: str) -> Note:
    """Everybody who sees a document may write a note on it; they are shown to everybody who sees the document."""
    text = clean_note(text)
    changes.write_lock(db)
    access = rights.require_document(db, uid, document_id)
    if access.document.status == TRASH:
        raise error("in_trash", "Restore the document first.", 409)
    note = Note(document_id=document_id, user_id=uid, text=text, created_at=clock.now())
    db.add(note)
    access.document.change_seq = changes.next_seq(db)
    db.flush()
    changes.record(db, document_id, changes.NOTE_ADDED, user_id=uid, detail={"note": note.id})
    db.commit()
    return note


def _own_note(
    db: Session, uid: int, document_id: int, note_id: int, *, manager_may: bool,
) -> tuple[Note, rights.Access]:
    access = rights.require_document(db, uid, document_id)
    note = db.scalar(select(Note).where(Note.id == note_id, Note.document_id == document_id))
    if note is None:
        raise error("not_found", "Not found.", 404)
    if note.user_id != uid and not (manager_may and access.vault == MANAGE):
        raise rights.forbidden()
    return note, access


def edit_note(db: Session, uid: int, document_id: int, note_id: int, text: str) -> Note:
    text = clean_note(text)
    changes.write_lock(db)
    note, access = _own_note(db, uid, document_id, note_id, manager_may=False)
    if note.text == text:
        db.rollback()
        return note
    note.text = text
    note.updated_at = clock.now()
    access.document.change_seq = changes.next_seq(db)
    changes.record(db, document_id, changes.NOTE_CHANGED, user_id=uid, detail={"note": note.id})
    db.commit()
    return note


def delete_note(db: Session, uid: int, document_id: int, note_id: int) -> None:
    changes.write_lock(db)
    note, access = _own_note(db, uid, document_id, note_id, manager_may=True)
    changes.record(db, document_id, changes.NOTE_DELETED, user_id=uid, detail={"note": note.id})
    db.delete(note)
    access.document.change_seq = changes.next_seq(db)
    db.commit()


def count_in_vault(db: Session, vault_id: int) -> int:
    return int(db.scalar(select(func.count()).select_from(Document).where(Document.vault_id == vault_id)) or 0)

