"""Vaults and their members.

Every person has one vault of their own, made together with the account (``models._make_personal_vault``); the owner is
always a manager of it and cannot lose that. Shared vaults (a household, a business) are made by the operator; their
managers hand out the rights. A vault must always keep a manager.

Somebody who leaves a vault gets a ``vault_lost`` marker for the feed; the documents of the vault they still see
(through a share) follow with a newer number, so that a program drops the vault and keeps those.

When an account is deleted (``before_account_delete``), the documents of its own vault go where the operator chose: to
another person's own vault, to a shared vault, or for good. The links the person made end, the shares to them go.
"""

from __future__ import annotations

import logging
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .. import clock
from ..errors import error
from ..models import EDIT, MANAGE, READ, RIGHTS, TRASH, Account, Document, Link, Share, Vault, VaultMember, Version
from . import catalog, changes, jobs, rights

logger = logging.getLogger("nexpaper.vaults")

NAME_MAX = 80
ICONS = ("user", "home", "car", "sun", "folder", "briefcase")
MAX_VAULTS = 200
MAX_MEMBERS = 500
_RANK = {right: index for index, right in enumerate(RIGHTS)}

#: What happens to the documents of a person's own vault when the account is deleted.
TRANSFER_TO_USER = "transfer_to_user"
TRANSFER_TO_VAULT = "transfer_to_vault"
DELETE_DOCUMENTS = "delete_documents"
DOCUMENT_CHOICES = (TRANSFER_TO_USER, TRANSFER_TO_VAULT, DELETE_DOCUMENTS)


def clean_name(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 or unicodedata.category(char) == "Cf" for char in value):
        raise error("invalid_name", "A name cannot hold control or invisible characters.", 422)
    name = " ".join(value.split())
    if not name or len(name) > NAME_MAX:
        raise error("invalid_name", f"Use 1 to {NAME_MAX} characters.", 422)
    return name


@dataclass
class VaultView:
    vault: Vault
    right: str
    documents: int
    size: int
    members: list[tuple[VaultMember, Account]]
    #: What people see: a shared vault's own name; a personal vault is named after its person as they are called now.
    name: str


def listing(db: Session, uid: int) -> list[VaultView]:
    """The vaults ``uid`` is a member of, with what they hold (counted over the documents of the vault: a member sees
    all of them). The caller's own vault first, then the personal vaults of others, then the shared ones, each in the
    order they were made; the members of each with the owner first, then by right."""
    rows = db.execute(
        select(Vault, VaultMember.right).join(VaultMember, VaultMember.vault_id == Vault.id)
        .where(VaultMember.user_id == uid)
        .order_by(Vault.personal_of.is_not(uid) | Vault.personal_of.is_(None), Vault.personal_of.is_(None), Vault.id)
    ).all()
    ids = [vault.id for vault, _ in rows]
    counts = dict(db.execute(
        select(Document.vault_id, func.count()).where(Document.vault_id.in_(ids), Document.status != TRASH)
        .group_by(Document.vault_id)).all()) if ids else {}
    sizes = dict(db.execute(
        select(Document.vault_id, func.coalesce(func.sum(Version.size), 0))
        .join(Version, Version.document_id == Document.id)
        .where(Document.vault_id.in_(ids), Document.status != TRASH).group_by(Document.vault_id)).all()) if ids else {}
    members: dict[int, list[tuple[VaultMember, Account]]] = {vault_id: [] for vault_id in ids}
    if ids:
        for member, account in db.execute(
            select(VaultMember, Account).join(Account, Account.id == VaultMember.user_id)
            .where(VaultMember.vault_id.in_(ids), Account.blocked_at.is_(None)).order_by(Account.name)
        ):
            members[member.vault_id].append((member, account))
    personal = {vault.id: vault.personal_of for vault, _ in rows}
    for vault_id, found in members.items():
        found.sort(key=_member_order(personal.get(vault_id)))
    owners = {a.id: a for a in db.scalars(select(Account).where(
        Account.id.in_({v.personal_of for v, _ in rows if v.personal_of is not None})))}
    return [VaultView(vault, right, int(counts.get(vault.id, 0)), int(sizes.get(vault.id, 0)), members[vault.id],
                      (owners[vault.personal_of].display_name or owners[vault.personal_of].name)
                      if vault.personal_of in owners else vault.name)
            for vault, right in rows]


def _member_order(owner: int | None) -> Callable[[tuple[VaultMember, Account]], tuple[bool, int, str]]:
    """The owner of a personal vault first, then by right (manage, edit, read), then by name."""
    def key(pair: tuple[VaultMember, Account]) -> tuple[bool, int, str]:
        member, account = pair
        return member.user_id != owner, -_RANK[member.right], (account.display_name or account.name).casefold()
    return key


def view(db: Session, uid: int, vault_id: int) -> VaultView:
    rights.require_vault(db, uid, vault_id)
    for item in listing(db, uid):
        if item.vault.id == vault_id:
            return item
    raise error("not_found", "Not found.", 404)


def create_shared(db: Session, operator: Account, name: str, icon: str) -> Vault:
    name = clean_name(name)
    if icon not in ICONS:
        raise error("invalid_icon", "No such icon.", 422)
    changes.write_lock(db)
    if (db.scalar(select(func.count()).select_from(Vault)) or 0) >= MAX_VAULTS:
        raise error("too_many_vaults", f"At most {MAX_VAULTS} vaults.", 409)
    from ..models import free_folder

    vault = Vault(name=name, folder=free_folder(db.connection(), name), icon=icon, created_by=operator.id)
    db.add(vault)
    db.flush()
    db.add(VaultMember(vault_id=vault.id, user_id=operator.id, right=MANAGE))
    db.commit()
    logger.info("Vault made vault_id=%s by=%s", vault.id, operator.name)
    return vault


def update_vault(db: Session, uid: int, vault_id: int, name: str | None, icon: str | None) -> Vault:
    changes.write_lock(db)
    vault, _right = rights.require_vault(db, uid, vault_id, MANAGE)
    if name is not None:
        if vault.personal_of is not None:
            raise error("personal_vault", "A personal vault keeps its person's name.", 409)
        vault.name = clean_name(name)
    if icon is not None:
        if icon not in ICONS:
            raise error("invalid_icon", "No such icon.", 422)
        vault.icon = icon
    db.commit()
    return vault


def delete_vault(db: Session, uid: int, vault_id: int, move_to: int | None) -> None:
    """A shared vault goes. Empty, or with its documents (the trash included) moved to another vault the caller may add
    to; the files follow in the background."""
    changes.write_lock(db)
    vault, _right = rights.require_vault(db, uid, vault_id, MANAGE)
    if vault.personal_of is not None:
        raise error("personal_vault", "A personal vault goes with its person.", 409)
    ids = list(db.scalars(select(Document.id).where(Document.vault_id == vault.id)))
    if ids:
        if move_to is None:
            raise error("vault_not_empty", "The vault still holds documents. Choose where they go.", 409)
        if move_to == vault.id:
            raise error("invalid_target", "Choose another vault.", 422)
        rights.require_vault(db, uid, move_to, EDIT)
    # The markers first, then the new numbers: a program drops the vault and then gets what it still sees.
    for member_id in db.scalars(select(VaultMember.user_id).where(VaultMember.vault_id == vault.id)):
        changes.tombstone(db, "vault_lost", vault_id=vault.id, user_id=member_id)
    if ids:
        assert move_to is not None
        db.execute(update(Document).where(Document.id.in_(ids)).values(vault_id=move_to))
        catalog.rehome(db, ids, move_to)
        changes.touch(db, ids)
        for document_id in ids:
            changes.record(db, document_id, changes.MOVED, user_id=uid, detail={"from": vault.id, "to": move_to})
            jobs.enqueue(db, jobs.RENAME, document_id)
    db.execute(delete(VaultMember).where(VaultMember.vault_id == vault.id))
    db.delete(vault)
    db.commit()
    logger.info("Vault deleted vault_id=%s moved=%s", vault_id, len(ids))


def _managers(db: Session, vault_id: int) -> int:
    return int(db.scalar(select(func.count()).select_from(VaultMember).where(
        VaultMember.vault_id == vault_id, VaultMember.right == MANAGE)) or 0)


def set_member(db: Session, uid: int, vault_id: int, user_id: int, right: str) -> VaultMember:
    """Gives a person a right in the vault, or changes it. Atomic: two managers changing the same member at the same
    moment leave one row."""
    if right not in RIGHTS:
        raise error("invalid_right", "No such right.", 422)
    changes.write_lock(db)
    vault, _mine = rights.require_vault(db, uid, vault_id, MANAGE)
    account = db.get(Account, user_id)
    if account is None or account.blocked_at is not None:
        raise error("not_found", "Not found.", 404)
    if vault.personal_of == user_id and right != MANAGE:
        raise error("owner_stays_manager", "The owner of a personal vault always manages it.", 409)
    member = db.get(VaultMember, (vault_id, user_id))
    if member is None:
        member = VaultMember(vault_id=vault_id, user_id=user_id, right=right)
        db.add(member)
    elif member.right != right:
        if member.right == MANAGE and _managers(db, vault_id) <= 1:
            raise error("last_manager", "A vault keeps at least one manager.", 409)
        member.right = right
    else:
        return member
    # The person's feed must fetch this vault's documents anew (their rights in them changed).
    changes.tombstone(db, "vault_refresh", vault_id=vault_id, user_id=user_id)
    db.commit()
    logger.info("Vault member set vault_id=%s member_id=%s right=%s", vault_id, user_id, right)
    return member


def remove_member(db: Session, uid: int, vault_id: int, user_id: int) -> None:
    changes.write_lock(db)
    vault, _mine = rights.require_vault(db, uid, vault_id, MANAGE)
    if vault.personal_of == user_id:
        raise error("owner_stays_manager", "The owner of a personal vault always manages it.", 409)
    member = db.get(VaultMember, (vault_id, user_id))
    if member is None:
        raise error("not_found", "Not found.", 404)
    if member.right == MANAGE and _managers(db, vault_id) <= 1:
        raise error("last_manager", "A vault keeps at least one manager.", 409)
    db.delete(member)
    _lost(db, vault_id, user_id)
    db.commit()
    logger.info("Vault member removed vault_id=%s member_id=%s", vault_id, user_id)


def _lost(db: Session, vault_id: int, user_id: int) -> None:
    """``user_id`` is out of the vault: the marker, then a new number for the documents of the vault they still see
    through a share (they would drop them with the vault and never get them back otherwise)."""
    changes.tombstone(db, "vault_lost", vault_id=vault_id, user_id=user_id)
    still = list(db.scalars(select(Document.id).where(
        Document.vault_id == vault_id, Document.id.in_(select(Share.document_id).where(Share.user_id == user_id)))))
    changes.touch(db, still)


def set_members(db: Session, uid: int, vault_id: int, wanted: list[tuple[int, str]]) -> None:
    """Who is in the vault with which right, all at once: one write, so that a refusal (the owner of a personal vault,
    the last manager, somebody unknown) leaves the vault as it was."""
    if len(wanted) > MAX_MEMBERS:
        raise error("too_many_members", f"At most {MAX_MEMBERS} members.", 422)
    target: dict[int, str] = {}
    for user_id, right in wanted:
        if right not in RIGHTS:
            raise error("invalid_right", "No such right.", 422)
        if user_id in target:
            raise error("invalid_input", "A person is named twice.", 422)
        target[user_id] = right
    changes.write_lock(db)
    vault, _mine = rights.require_vault(db, uid, vault_id, MANAGE)
    current = dict(db.execute(select(VaultMember.user_id, VaultMember.right)
                              .where(VaultMember.vault_id == vault_id)).all())
    if vault.personal_of is not None and target.get(vault.personal_of) != MANAGE:
        raise error("owner_stays_manager", "The owner of a personal vault always manages it.", 409)
    if MANAGE not in target.values():
        raise error("last_manager", "A vault keeps at least one manager.", 409)
    added = [u for u in target if u not in current or current[u] != target[u]]
    if added:
        usable = set(db.scalars(select(Account.id).where(Account.id.in_(added), Account.blocked_at.is_(None))))
        if any(u not in usable for u in added if u not in current):
            raise error("not_found", "Not found.", 404)
    removed = [u for u in current if u not in target]
    if not added and not removed:
        db.rollback()
        return
    for user_id in added:
        member = db.get(VaultMember, (vault_id, user_id))
        if member is None:
            db.add(VaultMember(vault_id=vault_id, user_id=user_id, right=target[user_id]))
        else:
            member.right = target[user_id]
        changes.tombstone(db, "vault_refresh", vault_id=vault_id, user_id=user_id)
    for user_id in removed:
        db.execute(delete(VaultMember).where(VaultMember.vault_id == vault_id, VaultMember.user_id == user_id))
        _lost(db, vault_id, user_id)
    db.commit()
    logger.info("Vault members set vault_id=%s changed=%s removed=%s", vault_id, len(added), len(removed))


def leave(db: Session, uid: int, vault_id: int) -> None:
    """Somebody gives up their own place in a shared vault."""
    changes.write_lock(db)
    vault, _mine = rights.require_vault(db, uid, vault_id)
    if vault.personal_of == uid:
        raise error("owner_stays_manager", "The owner of a personal vault always manages it.", 409)
    remove_member_unchecked(db, vault_id, uid)


def remove_member_unchecked(db: Session, vault_id: int, user_id: int) -> None:
    member = db.get(VaultMember, (vault_id, user_id))
    if member is None:
        return
    if member.right == MANAGE and _managers(db, vault_id) <= 1:
        raise error("last_manager", "A vault keeps at least one manager.", 409)
    db.delete(member)
    _lost(db, vault_id, user_id)
    db.commit()


@dataclass
class Leaving:
    """What deleting an account would take along, for the operator's dialog: how many documents its own vault holds
    (the trash included), the shared vaults it is the only manager of (the deletion is refused while there are), and
    where the operator would see the documents afterwards: the people whose own vault the operator is in (themselves
    included) and the shared vaults they are in."""

    documents: int
    sole_manager_of: list[Vault]
    heirs_you_see: list[int]
    vaults_you_see: list[int]


def leaving(db: Session, account_id: int, operator_id: int) -> Leaving:
    own = db.scalar(select(Vault.id).where(Vault.personal_of == account_id))
    held = int(db.scalar(select(func.count()).select_from(Document).where(Document.vault_id == own)) or 0) if own else 0
    mine = select(VaultMember.vault_id).where(VaultMember.user_id == operator_id)
    heirs = list(db.scalars(select(Vault.personal_of).where(Vault.personal_of.is_not(None), Vault.id.in_(mine))))
    shared = list(db.scalars(select(Vault.id).where(Vault.personal_of.is_(None), Vault.id.in_(mine))))
    return Leaving(held, _sole_manager_of(db, account_id, own), heirs, shared)


def _sole_manager_of(db: Session, account_id: int, own: int | None) -> list[Vault]:
    found = []
    for vault_id in db.scalars(select(VaultMember.vault_id).where(
            VaultMember.user_id == account_id, VaultMember.right == MANAGE)):
        if vault_id != own and _managers(db, vault_id) <= 1:
            vault = db.get(Vault, vault_id)
            if vault is not None:
                found.append(vault)
    return found


def before_account_delete(
    db: Session, account_id: int, *, choice: str | None = None, target_user: int | None = None,
    target_vault: int | None = None, by: int | None = None, account_name: str = "",
) -> int:
    """Called before an account is deleted, in the same transaction, under the write lock (a document uploaded or
    changed at the same moment comes before or after, never in between). The documents of the person's own vault, the
    trash included, go where ``choice`` says: ``transfer_to_user`` (into ``target_user``'s own vault, who becomes their
    owner), ``transfer_to_vault`` (into the shared vault ``target_vault``) or ``delete_documents`` (for good, the files
    in the background). Without a choice, a vault with documents refuses (409, with the number). The links the person
    made end, the shares to them go, and so does their vault. Shared vaults the person manages alone refuse too.

    The operator may choose themselves as the heir, or a vault they are in (a decision of the project): it is done in
    the open, the dialog says who sees the documents afterwards, and every document says in its history that it was
    taken over when this account was deleted, and by whom. Returns how many documents there were."""
    changes.write_lock(db)
    own = db.scalar(select(Vault).where(Vault.personal_of == account_id))
    ids = list(db.scalars(select(Document.id).where(Document.vault_id == own.id))) if own is not None else []
    if ids and choice is None:
        raise error("personal_vault_not_empty", "This person's own vault still holds documents. Choose where they go.",
                    409, documents=len(ids))
    if choice is not None and choice not in DOCUMENT_CHOICES:
        raise error("invalid_input", "No such choice.", 422)
    if _sole_manager_of(db, account_id, own.id if own is not None else None):
        raise error("last_manager", "This person is the only manager of a shared vault.", 409)
    destination: int | None = None
    new_owner: int | None = None
    if ids and choice == TRANSFER_TO_USER:
        heir = db.get(Account, target_user) if target_user else None
        if heir is None or heir.id == account_id or heir.blocked_at is not None:
            raise error("invalid_target", "Choose another person.", 422)
        destination = db.scalar(select(Vault.id).where(Vault.personal_of == heir.id))
        new_owner = heir.id
    elif ids and choice == TRANSFER_TO_VAULT:
        place = db.get(Vault, target_vault) if target_vault else None
        if place is None or place.personal_of is not None:
            raise error("invalid_target", "Choose a shared vault.", 422)
        destination = place.id
    now = clock.now()
    # The links the person made end at once, wherever they point.
    for link in db.scalars(select(Link).where(Link.created_by == account_id, Link.revoked_at.is_(None))):
        link.revoked_at = now
        changes.record(db, link.document_id, changes.LINK_REVOKED, user_id=by, detail={"reason": "account_deleted"})
    db.execute(delete(Share).where(Share.user_id == account_id))
    if own is not None:
        # Whoever else was in the vault loses it (the marker first, the documents' new numbers after).
        for member_id in db.scalars(select(VaultMember.user_id).where(
                VaultMember.vault_id == own.id, VaultMember.user_id != account_id)):
            changes.tombstone(db, "vault_lost", vault_id=own.id, user_id=member_id)
        if ids and destination is not None:
            values: dict[str, object] = {"vault_id": destination}
            if new_owner is not None:
                values["owner_id"] = new_owner
                # The heir is a manager of the vault now: a share to them on these documents says nothing any more.
                db.execute(delete(Share).where(Share.user_id == new_owner, Share.document_id.in_(ids)))
            db.execute(update(Document).where(Document.id.in_(ids)).values(**values)
                       .execution_options(synchronize_session=False))
            catalog.rehome(db, ids, destination)
            changes.touch(db, ids)
            for document_id in ids:
                changes.record(db, document_id, changes.TAKEN_OVER, user_id=by,
                               detail={"from": own.id, "to": destination, "account": account_name[:100]})
                jobs.enqueue(db, jobs.RENAME, document_id)
        elif ids:
            from . import documents

            for document in list(db.scalars(select(Document).where(Document.id.in_(ids)))):
                documents.delete_for_good(db, document)
        db.flush()
        db.execute(delete(VaultMember).where(VaultMember.vault_id == own.id))
        db.delete(own)
        db.flush()
    return len(ids)


def can_add_to(db: Session, uid: int, vault_id: int) -> bool:
    return rights.at_least(rights.vault_right(db, uid, vault_id), EDIT)


__all__ = ["READ"]
