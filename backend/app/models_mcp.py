"""Tables of the shared MCP module (``vendor/nexmcp``, mcp 1.1.0): AI tools (programs speaking MCP) with the data of
an account, by an MCP key made by hand or by a program that connected itself (OAuth) with the account's consent.

Everything here is new and starts empty; nothing of before is renamed or dropped. The tables are made by
``db._additions_mcp`` at every start without a new schema version, so 1.12.0 still opens the database (the way back
for one version) and leaves them alone. MCP keys and programs live in ``mcp_keys``, never in ``api_keys``: an older
nexpaper reads ``api_keys`` and would take a row there for an API key of ``/api/v1``. Their ids start at
``MCP_KEY_BASE``, so one number names one key of either table (the module's routes take a key by its number).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, UtcDateTime, utcnow

#: The first id of an MCP key; API keys (``api_keys``) count from 1 and never get there.
MCP_KEY_BASE = 1_000_000_000


class McpKey(Base):
    """An MCP key made by hand (``npm_``) or the key of a connected program (``client_id`` set; its access token
    ``npm_``, its refresh token ``npmr_``). Only the SHA-256 of a token is stored."""

    __tablename__ = "mcp_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    #: ``read`` or ``write``.
    level: Mapped[str] = mapped_column(String(8))
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    prefix: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    blocked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: The vaults the key is limited to; empty: every vault the account reaches, later ones too.
    vault_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    #: The extras that are on (nexpaper has none yet).
    extras: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: A connected program: its client, its refresh token, when it signed in and refreshed last.
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    refresh_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    signed_in_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    refreshed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class McpClient(Base):
    """A program that registered itself (RFC 7591, public clients only)."""

    __tablename__ = "mcp_clients"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    redirect_uris: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class McpCode(Base):
    """A code of the consent, taken once, valid ten minutes."""

    __tablename__ = "mcp_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64))
    account_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    redirect_uri: Mapped[str] = mapped_column(String(2048))
    challenge: Mapped[str] = mapped_column(String(200))
    level: Mapped[str] = mapped_column(String(8))
    vault_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    extras: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    resource: Mapped[str] = mapped_column(String(2048), default="")


class McpSpent(Base):
    """A refresh token or code already traded, to know a copy when it is brought again (the last 20 per program)."""

    __tablename__ = "mcp_spent"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    key_id: Mapped[int] = mapped_column(Integer, index=True)
    spent_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class McpToolRight(Base):
    """What a key may do with one tool, only where it differs from the default (allow, ask, deny)."""

    __tablename__ = "mcp_tool_rights"

    key_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tool: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(8))


class McpRequest(Base):
    """A call that waits for the account's yes (the right "ask"), with its arguments fixed, 24 hours."""

    __tablename__ = "mcp_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key_id: Mapped[int] = mapped_column(Integer)
    key_name: Mapped[str] = mapped_column(String(200), default="")
    tool: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[str] = mapped_column(Text)
    digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    decided_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(200), default="")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str] = mapped_column(String(500), default="")
    dangerous: Mapped[bool] = mapped_column(Boolean, default=False)


__all__ = ["MCP_KEY_BASE", "McpClient", "McpCode", "McpKey", "McpRequest", "McpSpent", "McpToolRight"]
