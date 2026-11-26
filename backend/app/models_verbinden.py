"""Tables of the shared module ``vendor/nexverbinden`` (verbinden 0.1.1): connections between nexpaper and other nex
apps (one per account and partner, both directions), the started ones, the codes of a consent, spent tokens and
revocations that wait for a partner. Their form is the module's template (``tests/nexverbinden/verbinden_partner.py``,
``SCHEMA``). All new and empty; made by ``db._additions_verbinden`` at every start without a new schema version, so
1.12.0 still opens the database. Nothing of nexpaper's own keys changes: an API key of before keeps working at
``/api/v1``.
"""

from __future__ import annotations

from sqlalchemy import Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class VbConnection(Base):
    __tablename__ = "vb_connections"
    __table_args__ = (UniqueConstraint("account_id", "partner"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer)
    partner: Mapped[str] = mapped_column(Text)
    partner_base: Mapped[str] = mapped_column(Text)
    partner_account: Mapped[str] = mapped_column(Text)
    uses: Mapped[str] = mapped_column(Text)
    grants: Mapped[str] = mapped_column(Text)
    areas_granted: Mapped[str | None] = mapped_column(Text, nullable=True)
    areas_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    held: Mapped[str] = mapped_column(Text)
    issued_access_hash: Mapped[str] = mapped_column(Text, unique=True)
    issued_refresh_hash: Mapped[str] = mapped_column(Text, unique=True)
    issued_access_expires: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)
    used_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    ok_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(Text)
    stale_since: Mapped[str | None] = mapped_column(Text, nullable=True)
    problem: Mapped[str | None] = mapped_column(Text, nullable=True)
    partner_version: Mapped[str] = mapped_column(Text, default="", server_default="")


class VbPending(Base):
    __tablename__ = "vb_pending"

    state_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    partner: Mapped[str | None] = mapped_column(Text, nullable=True)
    partner_base: Mapped[str | None] = mapped_column(Text, nullable=True)
    verifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    areas_granted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class VbCode(Base):
    __tablename__ = "vb_codes"

    code_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    partner: Mapped[str | None] = mapped_column(Text, nullable=True)
    partner_base: Mapped[str | None] = mapped_column(Text, nullable=True)
    redirect_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    challenge: Mapped[str | None] = mapped_column(Text, nullable=True)
    areas_granted: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class VbSpent(Base):
    __tablename__ = "vb_spent"

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    connection_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class VbWaiting(Base):
    __tablename__ = "vb_waiting"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    partner_base: Mapped[str | None] = mapped_column(Text, nullable=True)
    token: Mapped[str | None] = mapped_column(Text, nullable=True)
    since: Mapped[str | None] = mapped_column(Text, nullable=True)


class NextasksListUsed(Base):
    """nexpaper's own beside the module's (V19, a task from a document): the list in nextasks an account put a task in
    last, chosen first the next time. Made by ``db._additions_verbinden`` like the module's tables."""

    __tablename__ = "nextasks_lists_used"

    account_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    list_id: Mapped[str] = mapped_column(Text)


__all__ = ["NextasksListUsed", "VbCode", "VbConnection", "VbPending", "VbSpent", "VbWaiting"]
