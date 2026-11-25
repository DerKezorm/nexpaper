"""Tables the shared account module (``vendor/nexkonten``) and the shared post module (``vendor/nexpost``) need beyond
the accounts of 1.12.0.

Everything here is new and starts empty on a database of 1.12.0; nothing of before is renamed or dropped. The tables
are made by ``db._additions_konten`` at every start without a new schema version, so 1.12.0 still opens the database
(the way back for one version) and leaves them alone.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, UtcDateTime, utcnow


class FormerName(Base):
    """A username an account had before, or the name of an account deleted for good (``account_id`` None): nobody
    else takes it, ever (the draft: "Alte Benutzernamen für immer reserviert"). The intake folder and the plus address
    of an account answer to these names too (``services/intake.py``, ``services/intake_folder.py``)."""

    __tablename__ = "former_names"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
                                                   index=True)
    name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class SetupClaim(Base):
    """The setup, once per database: one row with id 1; a second setup fails at the primary key, also from another
    process."""

    __tablename__ = "setup_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class FailedUnknown(Base):
    """Wrong sign-ins that named no account, one counter row: written as costly as a failure at an account, so that
    the time of an answer tells nobody which names exist."""

    __tablename__ = "failed_unknown"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class MailOutbox(Base):
    """System mail waiting to go out (``vendor/nexpost``): the letter as JSON, tries and the next one, the last error.
    A mail that went out or was given up stays a while for the operator's page (``services/post_store.py``).
    nexpaper's own mail (reminders, deadlines, exports, upload requests) goes through ``services/mailer.py``."""

    __tablename__ = "mail_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    letter: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    next_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    error: Mapped[str] = mapped_column(String(500), default="")
