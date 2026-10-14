"""Senders, kinds and tags: the words documents are ordered by.

**Senders and tags belong to a vault.** One row per name and vault (``names.name_key`` decides when two names are the
same: case and Unicode folded). Nothing done in one vault can tell anything about another: a name that exists only in
somebody else's personal vault answers exactly like a name nobody uses. A document that moves takes its sender, tags
and kind along (the target vault's rows, made when missing). A row that no document uses any more goes.

A person sees the senders and tags of the vaults they are in and of the documents shared with them. The lists gather the
same name from several vaults into one entry (``group``), so that the archive filters by name across the vaults.
Renaming, merging (renaming to a name the vault has) and deleting act on one vault and need ``edit`` there.

**Kinds** are of two sorts. A short list comes with nexpaper, for the whole server, and only the operator changes it; a
kind that comes with nexpaper has a ``key``, so the interface can show its name in the person's language until the
operator renames it. On top of it every vault can make kinds of its own (anybody with ``edit`` there): they belong to
the vault like its senders and tags, a name used in another vault is no business of this one, and a person choosing a
kind for a document of the vault sees the server's and the vault's. Asking for a name the vault can already choose
answers with that kind. A document that moves to another vault takes a kind of its old vault along by name.

Every change to a sender, a tag or a kind that reaches documents gives them a new number for the feed and a line in
their history (which fields changed, never the names).
"""

from __future__ import annotations

import logging
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, case, delete, exists, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..errors import error
from ..models import EDIT, MANAGE, READ, TRASH, Document, DocumentTag, Kind, Sender, Share, Tag, VaultMember
from ..names import name_key
from . import changes, jobs, keeping, rights, settings_service

logger = logging.getLogger("nexpaper.catalog")

SENDER_MAX = 160
TAG_MAX = 40
KIND_MAX = 60
MAX_TAGS_PER_DOCUMENT = 30

#: The kinds that come with nexpaper: key, name (German, the first language of the interface), hue.
DEFAULT_KINDS: tuple[tuple[str, str, int], ...] = (
    ("invoice", "Rechnung", 28), ("contract", "Vertrag", 210), ("insurance", "Versicherung", 160),
    ("tax", "Steuer", 0), ("health", "Gesundheit", 340), ("bank", "Bank", 230), ("authority", "Behörde", 265),
    ("receipt", "Kaufbeleg", 45), ("school", "Schule", 110), ("other", "Sonstiges", 30),
)
#: The same kinds in English. A server set up in English names them so (``name_kinds_for``) while nobody has renamed
#: them: the names are what search (``art:``/``kind:``), rules and the export see, so they are names, not translations
#: of the moment.
KIND_NAMES_EN: dict[str, str] = {
    "invoice": "Invoice", "contract": "Contract", "insurance": "Insurance", "tax": "Tax", "health": "Health",
    "bank": "Bank", "authority": "Authorities", "receipt": "Receipt", "school": "School", "other": "Other",
}


def name_kinds_for(db: Session, language: str) -> None:
    """At the setup of a server: the kinds that come with nexpaper in the operator's language (German or English), as
    long as each still has the name it came with. A kind somebody renamed keeps that name."""
    if not language.lower().startswith("en"):
        return
    ensure_kinds(db)
    german = {key: name for key, name, _hue in DEFAULT_KINDS}
    for kind in db.scalars(select(Kind).where(Kind.vault_id.is_(None), Kind.key.in_(list(KIND_NAMES_EN)))):
        if kind.key and kind.name == german.get(kind.key):
            kind.name = KIND_NAMES_EN[kind.key]
            kind.name_key = name_key(kind.name)


def clean_word(value: str, limit: int, code: str) -> str:
    """A sender, tag or kind: spaces gathered, Unicode composed, no control or invisible characters, not empty, not too
    long."""
    if any(ord(char) < 32 or ord(char) == 127 or unicodedata.category(char) in ("Cf", "Cs") for char in value):
        raise error(code, "A name cannot hold control or invisible characters.", 422)
    word = unicodedata.normalize("NFC", " ".join(value.split()))
    if not word or len(word) > limit:
        raise error(code, f"Use 1 to {limit} characters.", 422)
    return word


def _record(db: Session, uid: int | None, ids: Iterable[int], what: str) -> None:
    """A line in the history of every document a change to the catalog reached (the field, never the names)."""
    for document_id in ids:
        changes.record(db, document_id, changes.CHANGED, user_id=uid, detail={"fields": [what], "by": "catalog"})


def _reached(db: Session, uid: int | None, ids: list[int], what: str, *, rename: bool) -> None:
    changes.touch(db, ids)
    _record(db, uid, ids, what)
    if rename:
        for document_id in ids:
            jobs.enqueue(db, jobs.RENAME, document_id)


# --- Kinds ------------------------------------------------------------------------------------------------------------


def ensure_kinds(db: Session) -> None:
    """The kinds that come with nexpaper, once: the first call fills the list, later calls leave it alone, so that a
    kind the operator deleted stays deleted."""
    if settings_service.get(db, "kinds_seeded"):
        return
    changes.write_lock(db)
    if settings_service.get(db, "kinds_seeded"):
        db.rollback()
        return
    for position, (key, name, hue) in enumerate(DEFAULT_KINDS):
        db.execute(sqlite_insert(Kind).values(key=key, name=name, name_key=name_key(name), hue=hue, position=position)
                   .on_conflict_do_nothing())
    settings_service.save(db, {"kinds_seeded": True})


def in_scope(vault_id: int | None) -> ColumnElement[bool]:
    """The kinds a document of this vault may have: the server's and the vault's own (only the server's without one)."""
    if vault_id is None:
        return Kind.vault_id.is_(None)
    return or_(Kind.vault_id.is_(None), Kind.vault_id == vault_id)


def _first_of_each_name(rows: Iterable[Kind]) -> list[Kind]:
    """One kind per name: where the server's and a vault's share a name, the server's (it comes first in the rows)."""
    seen: set[str] = set()
    out: list[Kind] = []
    for row in rows:
        if row.name_key not in seen:
            seen.add(row.name_key)
            out.append(row)
    return out


def kinds(db: Session, uid: int, vault_id: int | None = None) -> list[Kind]:
    """The kinds ``uid`` can choose from: the server's and those of the vaults they are in. With ``vault_id``, the
    choice for a document of that vault: the server's and that vault's, one entry per name. A vault the caller is not in
    answers like one that does not exist."""
    ensure_kinds(db)
    if vault_id is not None:
        rights.require_vault(db, uid, vault_id, READ)
        return kinds_of(db, vault_id)
    member = select(VaultMember.vault_id).where(VaultMember.user_id == uid)
    return list(db.scalars(select(Kind).where(or_(Kind.vault_id.is_(None), Kind.vault_id.in_(member)))
                           .order_by(Kind.vault_id.is_not(None), Kind.vault_id, Kind.position, Kind.id)))


def kinds_of(db: Session, vault_id: int | None) -> list[Kind]:
    """The kinds a document of this vault may have, one entry per name (no right is looked at: for the server's own
    uses)."""
    ensure_kinds(db)
    return _first_of_each_name(db.scalars(select(Kind).where(in_scope(vault_id)).order_by(
        Kind.vault_id.is_not(None), Kind.position, Kind.id)))


def kind_in_scope(db: Session, kind_id: int, vault_id: int) -> Kind:
    """The kind, when a document of this vault may have it (the server's or the vault's own); else ``kind_unknown``,
    the same answer as for a kind that does not exist, so that nobody learns what other vaults hold."""
    ensure_kinds(db)
    kind = db.get(Kind, kind_id)
    if kind is None or (kind.vault_id is not None and kind.vault_id != vault_id):
        raise error("kind_unknown", "No such kind.", 422)
    return kind


def kind_called(db: Session, vault_id: int | None, key: str) -> Kind | None:
    """The kind of that name (``names.name_key``) a document of the vault may have: the server's first."""
    return db.scalar(select(Kind).where(in_scope(vault_id), Kind.name_key == key)
                     .order_by(Kind.vault_id.is_not(None), Kind.id).limit(1))


def _documents_of_kind(db: Session, kind_id: int) -> list[int]:
    return list(db.scalars(select(Document.id).where(Document.kind_id == kind_id)))


def _kind_taken(db: Session, key: str, vault_id: int | None, but: int | None = None) -> bool:
    """Whether the name is taken where ``vault_id`` lives: among the server's kinds, and for a vault among its own too.
    A name used in another vault is no business of this one."""
    query = select(func.count()).select_from(Kind).where(in_scope(vault_id), Kind.name_key == key)
    if but is not None:
        query = query.where(Kind.id != but)
    return bool(db.scalar(query))


def create_kind(db: Session, uid: int | None, name: str, hue: int, vault_id: int | None = None) -> tuple[Kind, bool]:
    """A kind for the whole server (``vault_id`` empty; the caller has checked that it is the operator) or for a vault
    (``edit`` there). The kind and whether it is new: a name the vault can already choose (its own, or one of the
    server's) answers with that kind, so that asking twice, or two people at once, make one."""
    ensure_kinds(db)
    name = clean_word(name, KIND_MAX, "invalid_name")
    changes.write_lock(db)
    if vault_id is not None:
        rights.require_vault(db, uid or 0, vault_id, EDIT)
    found = kind_called(db, vault_id, name_key(name))
    if found is not None:
        if vault_id is None:
            raise error("name_taken", "A kind of this name exists.", 409)
        db.rollback()
        return found, False
    position = int(db.scalar(select(func.coalesce(func.max(Kind.position), -1) + 1).where(
        Kind.vault_id.is_(None) if vault_id is None else Kind.vault_id == vault_id)) or 0)
    kind = Kind(key="", name=name, name_key=name_key(name), hue=hue % 360, position=position, vault_id=vault_id,
                created_by=uid)
    db.add(kind)
    db.commit()
    return kind, True


def kind_in_vault(db: Session, vault_id: int, uid: int | None, name: str, hue: int) -> Kind:
    """The kind of that name for documents of the vault, made when there is none: what a document brings along when it
    comes to a vault (a move, an import). The caller holds the write lock and has checked the right to add there."""
    name = clean_word(name, KIND_MAX, "invalid_name")
    found = kind_called(db, vault_id, name_key(name))
    if found is None:
        position = int(db.scalar(select(func.coalesce(func.max(Kind.position), -1) + 1).where(
            Kind.vault_id == vault_id)) or 0)
        found = Kind(key="", name=name, name_key=name_key(name), hue=hue % 360, position=position, vault_id=vault_id,
                     created_by=uid)
        db.add(found)
        db.flush()
    return found


def _kind_to_change(db: Session, uid: int, kind_id: int) -> Kind:
    """The kind the caller may change: a vault's own with ``edit`` in the vault (a vault they are not in answers like a
    kind that does not exist); one of the server's only the operator (the router has checked that)."""
    kind = db.get(Kind, kind_id)
    if kind is None:
        raise error("not_found", "Not found.", 404)
    if kind.vault_id is not None:
        rights.require_vault(db, uid, kind.vault_id, EDIT)
    return kind


def update_kind(db: Session, uid: int, kind_id: int, name: str | None, hue: int | None, position: int | None) -> Kind:
    ensure_kinds(db)
    changes.write_lock(db)
    kind = _kind_to_change(db, uid, kind_id)
    renamed = False
    if name is not None:
        name = clean_word(name, KIND_MAX, "invalid_name")
        if name != kind.name:
            if _kind_taken(db, name_key(name), kind.vault_id, but=kind.id):
                raise error("name_taken", "A kind of this name exists.", 409)
            kind.name = name
            kind.name_key = name_key(name)
            renamed = True
    if hue is not None:
        kind.hue = hue % 360
    if position is not None:
        kind.position = position
    if renamed:
        _reached(db, uid, _documents_of_kind(db, kind.id), "kind", rename=True)
    db.commit()
    return kind


def delete_kind(db: Session, uid: int, kind_id: int, force: bool = False) -> None:
    """The kind goes; its documents are left without a kind (their files are renamed to match). While documents use a
    kind of a vault, a manager of the vault may delete it, anybody else with ``edit`` only with ``force`` (else 409
    with the number, for the interface to ask)."""
    ensure_kinds(db)
    changes.write_lock(db)
    kind = _kind_to_change(db, uid, kind_id)
    ids = _documents_of_kind(db, kind.id)
    if kind.vault_id is not None and ids and not force and rights.vault_right(db, uid, kind.vault_id) != MANAGE:
        raise error("in_use", "Documents still have this kind. Confirm to take it off them.", 409, documents=len(ids))
    db.execute(update(Document).where(Document.kind_id == kind.id).values(kind_id=None))
    # Without a kind there is no keeping time to work out: a worked-out keep_until goes (one set by hand stays).
    keeping.refresh(db, ids)
    _reached(db, uid, ids, "kind", rename=True)
    db.delete(kind)
    db.commit()


# --- Senders and tags: rows of a vault --------------------------------------------------------------------------------


def sender_named(db: Session, vault_id: int, uid: int | None, name: str) -> Sender:
    """The vault's sender of that name, made if the vault has none yet. The caller holds the write lock."""
    name = clean_word(name, SENDER_MAX, "invalid_sender")
    key = name_key(name)
    found = db.scalar(select(Sender).where(Sender.vault_id == vault_id, Sender.key == key))
    if found is None:
        found = Sender(vault_id=vault_id, name=name, key=key, created_by=uid)
        db.add(found)
        db.flush()
    return found


def check_tags(names: list[str]) -> None:
    """Raises what ``tags_named`` would raise for these names, without touching the database."""
    if len(names) > MAX_TAGS_PER_DOCUMENT:
        raise error("too_many_tags", f"At most {MAX_TAGS_PER_DOCUMENT} tags on a document.", 422)
    for raw in names:
        clean_word(raw, TAG_MAX, "invalid_tag")


def tags_named(db: Session, vault_id: int, uid: int | None, names: list[str]) -> list[Tag]:
    """The vault's tags of those names (duplicates gathered), made if missing. The caller holds the write lock."""
    if len(names) > MAX_TAGS_PER_DOCUMENT:
        raise error("too_many_tags", f"At most {MAX_TAGS_PER_DOCUMENT} tags on a document.", 422)
    found: dict[str, Tag] = {}
    for raw in names:
        name = clean_word(raw, TAG_MAX, "invalid_tag")
        key = name_key(name)
        if key in found:
            continue
        tag = db.scalar(select(Tag).where(Tag.vault_id == vault_id, Tag.key == key))
        if tag is None:
            tag = Tag(vault_id=vault_id, name=name, key=key, created_by=uid)
            db.add(tag)
            db.flush()
        found[key] = tag
    return list(found.values())


def prune(db: Session, sender_ids: Iterable[int | None] = (), tag_ids: Iterable[int | None] = ()) -> None:
    """Of the senders and tags named, the ones no document uses any more go."""
    senders = {i for i in sender_ids if i}
    tags = {i for i in tag_ids if i}
    db.flush()
    if senders:
        db.execute(delete(Sender).where(Sender.id.in_(senders), ~exists().where(Document.sender_id == Sender.id))
                   .execution_options(synchronize_session=False))
    if tags:
        db.execute(delete(Tag).where(Tag.id.in_(tags), ~exists().where(DocumentTag.tag_id == Tag.id))
                   .execution_options(synchronize_session=False))


def rehome(db: Session, document_ids: Iterable[int], vault_id: int) -> None:
    """After documents came to ``vault_id``: their sender and tags become the rows of that vault of the same names (made
    when missing); rows left without a document go. The caller holds the write lock."""
    ids = sorted(set(document_ids))
    if not ids:
        return
    db.flush()
    old_senders: set[int] = set()
    old_tags: set[int] = set()
    senders: dict[int, int] = {}
    for document_id, sender_id, name, created_by in db.execute(
        select(Document.id, Sender.id, Sender.name, Sender.created_by)
        .join(Sender, Sender.id == Document.sender_id).where(Document.id.in_(ids), Sender.vault_id != vault_id)
    ).all():
        if sender_id not in senders:
            senders[sender_id] = sender_named(db, vault_id, created_by, name).id
        db.execute(update(Document).where(Document.id == document_id).values(sender_id=senders[sender_id])
                   .execution_options(synchronize_session=False))
        old_senders.add(sender_id)
    tags: dict[int, int] = {}
    for document_id, tag_id, name, created_by in db.execute(
        select(DocumentTag.document_id, Tag.id, Tag.name, Tag.created_by).join(Tag, Tag.id == DocumentTag.tag_id)
        .where(DocumentTag.document_id.in_(ids), Tag.vault_id != vault_id)
    ).all():
        if tag_id not in tags:
            tags[tag_id] = tags_named(db, vault_id, created_by, [name])[0].id
        db.execute(sqlite_insert(DocumentTag).values(document_id=document_id, tag_id=tags[tag_id])
                   .on_conflict_do_nothing())
        db.execute(delete(DocumentTag).where(DocumentTag.document_id == document_id, DocumentTag.tag_id == tag_id))
        old_tags.add(tag_id)
    # A kind of the vault they left becomes the kind of the same name here (the server's, or made when missing). The
    # old vault keeps its kind: a kind is a choice of the vault, not a mark that goes with a document.
    kinds_moved: dict[int, int] = {}
    for document_id, kind_id, name, hue, created_by in db.execute(
        select(Document.id, Kind.id, Kind.name, Kind.hue, Kind.created_by).join(Kind, Kind.id == Document.kind_id)
        .where(Document.id.in_(ids), Kind.vault_id.is_not(None), Kind.vault_id != vault_id)
    ).all():
        if kind_id not in kinds_moved:
            kinds_moved[kind_id] = kind_in_vault(db, vault_id, created_by, name, hue).id
        db.execute(update(Document).where(Document.id == document_id).values(kind_id=kinds_moved[kind_id])
                   .execution_options(synchronize_session=False))
    # The documents in the session read their sender and kind anew.
    for document in db.scalars(select(Document).where(Document.id.in_(ids))):
        db.refresh(document, ["sender_id", "kind_id"])
    # Another kind of the same name may keep its documents for another time.
    keeping.refresh(db, ids)
    prune(db, old_senders, old_tags)


@dataclass
class Group:
    """One name as a person sees it: the rows of that name in the vaults they reach."""

    name: str
    key: str
    items: list[tuple[int, int]] = field(default_factory=list)


def _group(rows: Iterable[Sender | Tag]) -> list[Group]:
    groups: dict[str, Group] = {}
    for row in rows:
        group = groups.setdefault(row.key, Group(name=row.name, key=row.key))
        group.items.append((row.id, row.vault_id))
    return sorted(groups.values(), key=lambda g: (g.key, g.name))


def _shared_with(uid: int) -> object:
    return select(Share.document_id).where(Share.user_id == uid)


def visible_senders(db: Session, uid: int, vault_id: int | None = None) -> list[Group]:
    """The senders of the vaults ``uid`` is in and of the documents shared with them, gathered by name."""
    member = select(VaultMember.vault_id).where(VaultMember.user_id == uid)
    shared = select(Document.sender_id).where(Document.id.in_(_shared_with(uid)), Document.sender_id.is_not(None))
    query = select(Sender).where(Sender.vault_id.in_(member) | Sender.id.in_(shared))
    if vault_id is not None:
        query = query.where(Sender.vault_id == vault_id)
    return _group(db.scalars(query.order_by(Sender.key, Sender.id)))


def visible_tags(db: Session, uid: int, vault_id: int | None = None) -> list[Group]:
    member = select(VaultMember.vault_id).where(VaultMember.user_id == uid)
    shared = select(DocumentTag.tag_id).where(DocumentTag.document_id.in_(_shared_with(uid)))
    query = select(Tag).where(Tag.vault_id.in_(member) | Tag.id.in_(shared))
    if vault_id is not None:
        query = query.where(Tag.vault_id == vault_id)
    return _group(db.scalars(query.order_by(Tag.key, Tag.id)))


def _in_vault(db: Session, uid: int, row: Sender | Tag | None) -> None:
    """The row exists and the caller may change its vault: 404 when they are not in it (as for a vault they do not see),
    403 with ``read`` only."""
    if row is None:
        raise error("not_found", "Not found.", 404)
    rights.require_vault(db, uid, row.vault_id, EDIT)


def _merge_needs_manage(db: Session, uid: int, vault_id: int, message: str) -> None:
    """A rename onto a name the vault already has joins the two. Only a manager may do that; anybody else with ``edit``
    gets the answer for a name that is taken."""
    if rights.vault_right(db, uid, vault_id) != MANAGE:
        raise error("name_taken", message, 409)


def rename_sender(db: Session, uid: int, sender_id: int, name: str) -> Sender:
    """Within the sender's vault. A name the vault has already merges the two (the documents go to the older row)."""
    name = clean_word(name, SENDER_MAX, "invalid_sender")
    changes.write_lock(db)
    sender = db.get(Sender, sender_id)
    _in_vault(db, uid, sender)
    assert sender is not None
    ids = list(db.scalars(select(Document.id).where(Document.sender_id == sender.id)))
    other = db.scalar(select(Sender).where(Sender.vault_id == sender.vault_id, Sender.key == name_key(name),
                                           Sender.id != sender.id))
    if other is not None:
        # Renaming onto a name the vault has is a merge, and a merge is the manager's (as ``merge_sender``).
        _merge_needs_manage(db, uid, sender.vault_id, "A sender of this name exists.")
        db.execute(update(Document).where(Document.sender_id == sender.id).values(sender_id=other.id))
        _reached(db, uid, ids, "sender", rename=True)
        db.delete(sender)
        db.commit()
        return other
    if name == sender.name:
        db.rollback()
        return sender
    sender.name = name
    sender.key = name_key(name)
    _reached(db, uid, ids, "sender", rename=True)
    db.commit()
    return sender


def delete_sender(db: Session, uid: int, sender_id: int, force: bool = False) -> None:
    """The sender goes from its vault; its documents are left without one (their files are renamed to match). While
    documents use it, only a manager of the vault may do so: anybody else with ``edit`` gets 409 ``in_use`` with the
    number, and 403 with ``force``, which is no way round the right."""
    changes.write_lock(db)
    sender = db.get(Sender, sender_id)
    _in_vault(db, uid, sender)
    assert sender is not None
    ids = list(db.scalars(select(Document.id).where(Document.sender_id == sender.id)))
    if ids and rights.vault_right(db, uid, sender.vault_id) != MANAGE:
        # Taking a sender off documents others keep is the manager's; ``force`` does not stand in for the right.
        if force:
            raise rights.forbidden()
        raise error("in_use", "Documents still have this sender. A manager of the vault can take it off them.", 409,
                    documents=len(ids))
    db.execute(update(Document).where(Document.sender_id == sender.id).values(sender_id=None))
    _reached(db, uid, ids, "sender", rename=True)
    db.delete(sender)
    db.commit()


def rename_tag(db: Session, uid: int, tag_id: int, name: str) -> Tag:
    name = clean_word(name, TAG_MAX, "invalid_tag")
    changes.write_lock(db)
    tag = db.get(Tag, tag_id)
    _in_vault(db, uid, tag)
    assert tag is not None
    ids = list(db.scalars(select(DocumentTag.document_id).where(DocumentTag.tag_id == tag.id)))
    other = db.scalar(select(Tag).where(Tag.vault_id == tag.vault_id, Tag.key == name_key(name), Tag.id != tag.id))
    if other is not None:
        _merge_needs_manage(db, uid, tag.vault_id, "A tag of this name exists.")
        for document_id in ids:
            db.execute(sqlite_insert(DocumentTag).values(document_id=document_id, tag_id=other.id)
                       .on_conflict_do_nothing())
        db.execute(delete(DocumentTag).where(DocumentTag.tag_id == tag.id))
        _reached(db, uid, ids, "tags", rename=False)
        db.delete(tag)
        db.commit()
        return other
    if name == tag.name:
        db.rollback()
        return tag
    tag.name = name
    tag.key = name_key(name)
    _reached(db, uid, ids, "tags", rename=False)
    db.commit()
    return tag


def delete_tag(db: Session, uid: int, tag_id: int) -> None:
    """The tag goes from its vault, and with it from every document there that carried it."""
    changes.write_lock(db)
    tag = db.get(Tag, tag_id)
    _in_vault(db, uid, tag)
    assert tag is not None
    ids = list(db.scalars(select(DocumentTag.document_id).where(DocumentTag.tag_id == tag.id)))
    db.execute(delete(DocumentTag).where(DocumentTag.tag_id == tag.id))
    _reached(db, uid, ids, "tags", rename=False)
    db.delete(tag)
    db.commit()


# --- Order: the lists with how many documents use each entry, and merging --------------------------------------------

ORDER_WHAT = ("senders", "tags", "kinds")
ORDER_MAX = 500


def _like(text: str) -> str:
    """``text`` as the middle of a LIKE pattern (a backslash escapes)."""
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def entries(db: Session, uid: int, what: str, *, vault_id: int | None = None, q: str = "", order: str = "name",
            limit: int = 200, offset: int = 0) -> tuple[list[dict[str, object]], int]:
    """The senders, tags or kinds of the vaults ``uid`` is in (and, for kinds, the server's), one row each, with the
    number of documents that use it. **Only the vaults the caller is in are looked at**, so that a name in somebody
    else's vault is neither listed nor counted, and a ``vault_id`` the caller is not in answers like an empty one.

    ``documents`` counts what is not in the trash, ``in_trash`` what is. ``can_change`` says whether the caller may
    rename, merge and delete the entry: ``manage`` in its vault (``None`` for a kind of the server, which is the
    operator's). A kind of the server is counted over the documents of the caller's vaults only."""
    if what not in ORDER_WHAT:
        raise error("not_found", "Not found.", 404)
    limit = max(1, min(limit, ORDER_MAX))
    member = select(VaultMember.vault_id.label("vault_id"), VaultMember.right.label("right")).where(
        VaultMember.user_id == uid).subquery()
    live = func.sum(case((Document.status != TRASH, 1), else_=0))
    gone = func.sum(case((Document.status == TRASH, 1), else_=0))
    if what == "senders":
        model: type[Sender | Tag | Kind] = Sender
        counts = (select(Document.sender_id.label("ref"), live.label("live"), gone.label("gone"))
                  .where(Document.sender_id.is_not(None)).group_by(Document.sender_id).subquery())
    elif what == "tags":
        model = Tag
        counts = (select(DocumentTag.tag_id.label("ref"), live.label("live"), gone.label("gone"))
                  .join(Document, Document.id == DocumentTag.document_id).group_by(DocumentTag.tag_id).subquery())
    else:
        model = Kind
        counts = (select(Document.kind_id.label("ref"), live.label("live"), gone.label("gone"))
                  .where(Document.kind_id.is_not(None), Document.vault_id.in_(select(member.c.vault_id)))
                  .group_by(Document.kind_id).subquery())
    documents = func.coalesce(counts.c.live, 0)
    query = select(model, member.c.right, documents.label("documents"),
                   func.coalesce(counts.c.gone, 0).label("in_trash"))
    if what == "kinds":
        ensure_kinds(db)
        query = query.outerjoin(member, member.c.vault_id == Kind.vault_id).where(
            or_(Kind.vault_id.is_(None), member.c.vault_id.is_not(None)))
        if vault_id is not None:
            query = query.where(Kind.vault_id == vault_id)
    else:
        query = query.join(member, member.c.vault_id == model.vault_id)  # type: ignore[union-attr]
        if vault_id is not None:
            query = query.where(model.vault_id == vault_id)  # type: ignore[union-attr]
    query = query.outerjoin(counts, counts.c.ref == model.id)
    sort_name = model.name_key if what == "kinds" else model.key  # type: ignore[union-attr]
    wanted = name_key(q.strip())[:SENDER_MAX] if q.strip() else ""
    if wanted:
        query = query.where(sort_name.like(_like(wanted), escape="\\"))
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    if order == "documents":
        ordering = [documents.desc(), sort_name, model.id]
    elif what == "kinds":
        ordering = [model.vault_id.is_not(None), model.position, model.id]  # type: ignore[union-attr]
    else:
        ordering = [sort_name, model.id]
    rows = db.execute(query.order_by(*ordering).limit(limit).offset(max(0, offset))).all()
    out: list[dict[str, object]] = []
    for row, right, count, trashed in rows:
        item: dict[str, object] = {"id": row.id, "name": row.name, "vault_id": row.vault_id, "right": right,
                                   "documents": int(count), "in_trash": int(trashed),
                                   "can_change": (right == MANAGE) if row.vault_id is not None else None}
        if what == "kinds":
            item.update(key=row.key, hue=row.hue, position=row.position, keep_years=row.keep_years,
                        keep_new_only=row.keep_new_only)
        out.append(item)
    return out, total


def _to_manage(db: Session, uid: int, row: Sender | Tag | None) -> None:
    """The row exists and the caller manages its vault: 404 when they are not in it, 403 with less than ``manage``."""
    if row is None:
        raise error("not_found", "Not found.", 404)
    rights.require_vault(db, uid, row.vault_id, MANAGE)


def _target(db: Session, uid: int, model: type[Sender | Tag], source: Sender | Tag, into_id: int) -> Sender | Tag:
    """The entry to merge into, in the same vault as the source. An entry in a vault the caller is not in answers like
    one that does not exist; one in another vault of theirs is refused plainly."""
    if into_id == source.id:
        raise error("merge_same", "Choose another entry to merge into.", 422)
    target = db.get(model, into_id)
    if target is None or rights.vault_right(db, uid, target.vault_id) is None:
        raise error("not_found", "Not found.", 404)
    if target.vault_id != source.vault_id:
        raise error("merge_other_vault", "Entries merge within one vault.", 422)
    return target


def merge_sender(db: Session, uid: int, sender_id: int, into_id: int) -> Sender:
    """All documents of the sender go to another sender of the same vault, and the sender goes. ``manage`` there."""
    changes.write_lock(db)
    source = db.get(Sender, sender_id)
    _to_manage(db, uid, source)
    assert source is not None
    target = _target(db, uid, Sender, source, into_id)
    ids = list(db.scalars(select(Document.id).where(Document.sender_id == source.id)))
    db.execute(update(Document).where(Document.sender_id == source.id).values(sender_id=target.id))
    _reached(db, uid, ids, "sender", rename=True)
    db.delete(source)
    db.commit()
    return target  # type: ignore[return-value]


def merge_tag(db: Session, uid: int, tag_id: int, into_id: int) -> Tag:
    """The same for a tag: every document that carried it carries the other one, once."""
    changes.write_lock(db)
    source = db.get(Tag, tag_id)
    _to_manage(db, uid, source)
    assert source is not None
    target = _target(db, uid, Tag, source, into_id)
    ids = list(db.scalars(select(DocumentTag.document_id).where(DocumentTag.tag_id == source.id)))
    for document_id in ids:
        db.execute(sqlite_insert(DocumentTag).values(document_id=document_id, tag_id=target.id)
                   .on_conflict_do_nothing())
    db.execute(delete(DocumentTag).where(DocumentTag.tag_id == source.id))
    _reached(db, uid, ids, "tags", rename=False)
    db.delete(source)
    db.commit()
    return target  # type: ignore[return-value]


def merge_kind(db: Session, uid: int, kind_id: int, into_id: int) -> Kind:
    """The documents of the kind go to another kind they may have, and the kind goes. A kind of a vault merges into one
    of the server's or of the same vault (``manage`` there); a kind of the server only into another of the server's
    (the router has checked that the caller is the operator). Rules that named the kind name the other one."""
    ensure_kinds(db)
    changes.write_lock(db)
    source = db.get(Kind, kind_id)
    if source is None:
        raise error("not_found", "Not found.", 404)
    if source.vault_id is not None:
        rights.require_vault(db, uid, source.vault_id, MANAGE)
    if into_id == source.id:
        raise error("merge_same", "Choose another entry to merge into.", 422)
    target = db.get(Kind, into_id)
    if target is None or (target.vault_id is not None and rights.vault_right(db, uid, target.vault_id) is None):
        raise error("not_found", "Not found.", 404)
    if (source.vault_id is None and target.vault_id is not None) or (
            target.vault_id is not None and target.vault_id != source.vault_id):
        raise error("merge_other_vault", "Entries merge within one vault.", 422)
    from . import rules  # here and not at the top: the rules read the catalog

    ids = _documents_of_kind(db, source.id)
    db.execute(update(Document).where(Document.kind_id == source.id).values(kind_id=target.id))
    keeping.refresh(db, ids)
    rules.repoint_kind(db, source.id, target.id)
    _reached(db, uid, ids, "kind", rename=True)
    db.delete(source)
    db.commit()
    return target
