"""Who may do what with which vault and which document.

Three rights in a vault, each including the ones before it: **read** (look, search, download, write notes), **edit**
(add, file, change fields, move, delete to the trash), **manage** (also share, give rights, delete the vault). A
document is seen by the members of its vault and by the people it was shared with one by one (a share gives ``read``
or ``edit``, never ``manage``).

**Nothing leaks.** A vault or a document somebody may not see answers exactly like one that does not exist (404). The
rights are in the query that fetches the rows, so that no list is filtered afterwards and no count includes what the
caller may not see. Nobody sees the personal vault of somebody else, the operator included, unless it was shared.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import ColumnElement, Select, or_, select
from sqlalchemy.orm import Session

from ..errors import error
from ..models import EDIT, MANAGE, READ, RIGHTS, Document, Share, Vault, VaultMember

__all__ = ["EDIT", "MANAGE", "READ", "Access", "at_least", "member_vault_ids", "require_document", "require_vault",
           "vault_right", "visible_clause"]

_RANK = {right: index for index, right in enumerate(RIGHTS)}


def at_least(right: str | None, need: str) -> bool:
    return right is not None and _RANK[right] >= _RANK[need]


def forbidden() -> Exception:
    return error("forbidden", "Your right here does not allow this.", 403)


def member_vault_ids(uid: int) -> Select[tuple[int]]:
    """The vaults ``uid`` is a member of, as a subquery."""
    return select(VaultMember.vault_id).where(VaultMember.user_id == uid)


def visible_clause(uid: int) -> ColumnElement[bool]:
    """``Document`` rows ``uid`` may see: in a vault they are a member of, or shared with them."""
    return or_(
        Document.vault_id.in_(member_vault_ids(uid)),
        Document.id.in_(select(Share.document_id).where(Share.user_id == uid)),
    )


def editable_clause(uid: int) -> ColumnElement[bool]:
    """``Document`` rows ``uid`` may change: edit or manage in the vault, or a share with ``edit``."""
    return or_(
        Document.vault_id.in_(
            select(VaultMember.vault_id).where(VaultMember.user_id == uid, VaultMember.right.in_((EDIT, MANAGE)))
        ),
        Document.id.in_(select(Share.document_id).where(Share.user_id == uid, Share.right == EDIT)),
    )


def vault_right(db: Session, uid: int, vault_id: int) -> str | None:
    return db.scalar(select(VaultMember.right).where(VaultMember.vault_id == vault_id, VaultMember.user_id == uid))


def require_vault(db: Session, uid: int, vault_id: int, need: str = READ) -> tuple[Vault, str]:
    """The vault and the caller's right in it. 404 when the caller may not even see it, 403 when they see it but may
    not do this."""
    row = db.execute(
        select(Vault, VaultMember.right).join(VaultMember, VaultMember.vault_id == Vault.id)
        .where(Vault.id == vault_id, VaultMember.user_id == uid)
    ).first()
    if row is None:
        raise error("not_found", "Not found.", 404)
    vault, right = row
    if not at_least(right, need):
        raise forbidden()
    return vault, right


@dataclass(frozen=True)
class Access:
    """What ``uid`` may do with one document."""

    document: Document
    vault: str | None
    share: str | None
    uid: int

    @property
    def right(self) -> str:
        best = [r for r in (self.vault, self.share) if r is not None]
        return max(best, key=lambda r: _RANK[r])

    @property
    def can_edit(self) -> bool:
        return at_least(self.right, EDIT)

    @property
    def can_share(self) -> bool:
        """Sharing and links: managers of the vault, and the person the document belongs to."""
        return self.vault == MANAGE or self.document.owner_id == self.uid


def access_to(db: Session, uid: int, document_id: int) -> Access | None:
    row = db.execute(
        select(Document, VaultMember.right, Share.right)
        .outerjoin(VaultMember, (VaultMember.vault_id == Document.vault_id) & (VaultMember.user_id == uid))
        .outerjoin(Share, (Share.document_id == Document.id) & (Share.user_id == uid))
        .where(Document.id == document_id)
    ).first()
    if row is None:
        return None
    document, vault_right_, share_right = row
    if vault_right_ is None and share_right is None:
        return None
    return Access(document=document, vault=vault_right_, share=share_right, uid=uid)


def require_document(db: Session, uid: int, document_id: int, need: str = READ) -> Access:
    """The document with what the caller may do with it; 404 when they may not see it, 403 when they see it but not
    enough."""
    access = access_to(db, uid, document_id)
    if access is None:
        raise error("not_found", "Not found.", 404)
    if not at_least(access.right, need):
        raise forbidden()
    return access
