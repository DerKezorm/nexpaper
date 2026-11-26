"""Tables of the shared AI module (``vendor/nexki``, ki 0.1.0) beyond the settings of before: an account's own AI
service (the way "Jedes Konto selbst", K2) and the lines of "Was ging hinaus" (K5, 14 days, at most 200 per account).

Both new and empty on a database of 1.12.0; made by ``db._additions_ki`` at every start without a new schema version,
so 1.12.0 still opens the database. The operator's service stays where it was (``settings``: ``ai_provider``,
``ai_url``, ``ai_model``, ``ai_key_enc``), its key sealed in its old context: nothing wanders.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, UtcDateTime, utcnow


class AiOwnAccess(Base):
    """An account's own AI service (only used while the operator chose "Jedes Konto selbst"); its key sealed with the
    account's context (``account:<id>:ai``)."""

    __tablename__ = "ai_own_access"

    account_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    api: Mapped[str] = mapped_column(String(16), default="openai")
    url: Mapped[str] = mapped_column(String(255), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    key_enc: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class AiEvent(Base):
    """One line of "Was ging hinaus": a task a person started word for word (``sent``, sealed with the account's
    context), an automatic one without content."""

    __tablename__ = "ai_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    task: Mapped[str] = mapped_column(String(40))
    target: Mapped[str] = mapped_column(String(255), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    manual: Mapped[bool] = mapped_column(Boolean, default=False)
    chars: Mapped[int] = mapped_column(Integer, default=0)
    outcome: Mapped[str] = mapped_column(String(40), default="")
    sent: Mapped[str] = mapped_column(Text, default="")


__all__ = ["AiEvent", "AiOwnAccess"]
