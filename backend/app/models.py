"""The data model.

Everything lives in SQLite. The schema carries a version number (``db.SCHEMA_VERSION``); a change to a table here
comes with a migration step in ``db.MIGRATIONS`` and a new recorded schema in ``tests/schema/``.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    event,
    insert,
    select,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .names import clean_segment, folded


def utcnow() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator[datetime]):
    """SQLite forgets the time zone. Stored as UTC, read back as UTC with the zone attached."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)


OPERATOR = "operator"
MEMBER = "member"
ROLES = (OPERATOR, MEMBER)

SIGN_IN_PASSWORD = "password"
SIGN_IN_OIDC = "oidc"


class Account(Base):
    """A person. The first account is the operator; the others come by invitation or through OIDC.

    The operator manages accounts and does not read the documents in them."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Lower case, the name people sign in with. What people see is the display name, when there is one.
    name: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(80), default="")
    #: The version whose "What's new" the account has read or put away.
    whats_new_seen: Mapped[str] = mapped_column(String(32), default="")
    role: Mapped[str] = mapped_column(String(16), default=MEMBER)
    sign_in: Mapped[str] = mapped_column(String(16), default=SIGN_IN_PASSWORD)
    #: Argon2id. Empty for accounts that sign in through OIDC only.
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    #: When the address was confirmed by a link sent to it (or came from the provider); empty: one the operator typed.
    email_confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: The address came from a sign-in provider (``services/oidc_store.py``): it goes with the last link, and it is
    #: never confirmed by that alone (the mail intake counts only an address the person confirmed by a link).
    email_from_provider: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    #: The subject of the single provider before the list (1.0.1). Read once by the migration, then only written for
    #: the way back (``services/oidc_store.py``); it goes one version later.
    oidc_subject: Mapped[str] = mapped_column(String(255), default="")
    #: The interface language; empty: the browser's.
    language: Mapped[str] = mapped_column(String(16), default="")
    #: What the person chose for themselves (``routers/auth.py``, ``PROFILE``): only what it chose is kept.
    profile: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: Set when the operator blocked the account: no sign-in, sessions and tokens end at once.
    blocked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: The second factor (``services/totp.py``): the seed encrypted with the server secret, empty while off; the
    #: recovery codes as a JSON list of keyed hashes; the time step of the last code taken (no replay).
    totp_secret_enc: Mapped[str] = mapped_column(Text, default="")
    totp_recovery: Mapped[str] = mapped_column(Text, default="")
    totp_last_step: Mapped[int] = mapped_column(Integer, default=0)
    #: The profile picture (``services/avatars.py``): a square WebP drawn anew, loaded only when asked for.
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    avatar_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: Whether the account ever signed in: its very first sign-in is no "new device" (``services/notices.py``).
    signed_in_before: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    #: The user handle its passkeys carry (``services/passkeys.py``): random, the same for all of its passkeys, so a
    #: passkey names its account without its name or id. Hex; empty until the first passkey.
    passkey_handle: Mapped[str] = mapped_column(String(64), default="", server_default=text("''"))
    #: What the operator allows this person (on from the start; the operator takes single accounts out): the AI
    #: (``services/ai.py``). It comes on top of the operator's switch for the whole server and the person's own switch.
    ai_allowed: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    #: Not a column: whether the session that asks came in through a provider that checks the second factor itself
    #: (``AuthSession.second_factor_by_provider``), set by ``deps.require_account`` for ``totp.setup_required``.
    second_factor_by_provider: ClassVar[bool] = False


#: What a session may do (``deps.require_account``): everything; only set up the second factor right after signing in;
#: only confirm that the recovery codes are kept. The last two never become ``full`` themselves: a new session does.
STAGE_FULL = "full"
STAGE_SETUP = "setup"
STAGE_CODES = "codes"


def _session_uid() -> str:
    return secrets.token_hex(16)


class AuthSession(Base):
    """A browser session. Only the hash of the token is stored; the token itself lives in the cookie.

    ``uid`` names the session in the list of signed-in devices (never the token or its hash). ``remember``: the
    person ticked "stay signed in on this device", the session lasts until it was not used for ``session_days``;
    without, it ends with the browser and after twelve hours at the latest."""

    __tablename__ = "auth_sessions"
    __table_args__ = (Index("uq_auth_sessions_uid", "uid", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    uid: Mapped[str] = mapped_column(String(32), default=_session_uid, server_default=text("''"))
    remember: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    stage: Mapped[str] = mapped_column(String(8), default=STAGE_FULL, server_default=text("'full'"))
    #: The session came in through a provider whose entry checks the second factor itself: "require a second factor"
    #: does not send it to set one up (Bauplan 01); the same account signing in with its password still is.
    second_factor_by_provider: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))


class OidcProvider(Base):
    """A sign-in provider (OpenID Connect), one row each, the columns as the shared blueprint names them (Bauplan 01).
    Read and written only through ``services/oidc_store.py`` for the shared module ``vendor/nexoidc``.

    Not part of a numbered schema step: an addition (``db.ADDITIONS``) that 1.0.1 opens without knowing it, so that
    the way back to 1.0.1 stays open for one version."""

    __tablename__ = "oidc_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Part of the callback address ``/api/v1/oidc/<slug>/callback``; fixed once made.
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    #: The name on the sign-in button.
    label: Mapped[str] = mapped_column(String(64))
    #: Stored without blanks and without a slash at the end.
    issuer: Mapped[str] = mapped_column(String(500))
    client_id: Mapped[str] = mapped_column(String(255))
    #: Encrypted with the server secret under the context ``oidc-provider:<id>``; empty for a public client.
    client_secret_enc: Mapped[str] = mapped_column(Text, default="")
    scopes: Mapped[str] = mapped_column(String(500), default="openid profile email")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    #: "New people get an account": off from the start.
    auto_create: Mapped[bool] = mapped_column(Boolean, default=False)
    #: "The provider checks the second factor itself": on from the start (the migrated entry keeps 1.0.1's switch).
    trusts_second_factor: Mapped[bool] = mapped_column(Boolean, default=True)
    #: "" by hand, "authentik" made by the authentik button.
    managed: Mapped[str] = mapped_column(String(20), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    #: A callback path the provider knew before (only a migration sets it); "" is the standard one.
    redirect_path: Mapped[str] = mapped_column(String(300), default="")
    #: The redirect address the authentik button last registered at authentik for this entry, "" for none.
    registered_redirect: Mapped[str] = mapped_column(String(500), default="", server_default=text("''"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class OidcLink(Base):
    """One identity at one provider, bound to one account. Found only by ``(provider_id, subject)``, never by an
    address: ``email`` is for display."""

    __tablename__ = "oidc_links"
    __table_args__ = (
        UniqueConstraint("provider_id", "subject"),
        UniqueConstraint("provider_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("oidc_providers.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(255))
    account_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    #: The ``iss`` of the token that made the link (with Entra ``common`` the real tenant).
    issuer: Mapped[str] = mapped_column(String(500))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class Passkey(Base):
    """A passkey of an account (WebAuthn, ``services/passkeys.py``): signs in without password and code, and counts
    as a second factor. Only the public key is kept; ``sign_count`` is the authenticator's counter as last seen."""

    __tablename__ = "passkeys"
    __table_args__ = (
        Index("uq_passkeys_uid", "uid", unique=True),
        Index("uq_passkeys_credential", "credential_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(32))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class Invite(Base):
    """A link that brings somebody in with a new account. Only the hash of the token is stored; used once, then gone."""

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(255), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)


class PasswordReset(Base):
    """A link with which a person sets a new password (``services/resets.py``). Only the hash of the token is stored;
    used once, then gone. At most one per account: a new one replaces the one before."""

    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    #: The operator who sent it; empty when the person asked for it themselves ("Forgot your password?").
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)


class EmailConfirmation(Base):
    """A new mail address waiting for the link sent to it (``services/emails.py``). Only the hash of the token is
    stored; used once, then gone. At most one per account: a new one replaces the one before."""

    __tablename__ = "email_confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    address: Mapped[str] = mapped_column(String(255))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)


class ApiKey(Base):
    """A key an account made for programs (``/api/v1``). Only the SHA-256 is stored.

    ``scope`` is what the key may do: ``read`` now, ``upload`` with the phone block."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    scope: Mapped[str] = mapped_column(String(8))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    blocked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class Device(Base):
    """A device or app paired with an account (``services/devices.py``): it speaks for the account with a token in
    ``Authorization: Bearer``, next to the session cookie of a browser. Only the SHA-256 of the token is stored.
    Revoking sets ``revoked_at``; the row stays for the list."""

    __tablename__ = "devices"
    __table_args__ = (Index("uq_devices_uid", "uid", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(32), default=_session_uid)
    account_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: How it was paired: ``token`` (made in the browser), ``qr`` (a code shown in the browser), ``app:<client>`` (an
    #: app through OAuth 2 with PKCE). Last column: the step that brought it adds it at the end.
    via: Mapped[str] = mapped_column(String(40), default="token", server_default=text("'token'"))


# --- Web Push ----------------------------------------------------------------------------------------


class PushDevice(Base):
    """A browser or an app on the home screen that gets notices (``services/push.py``). What the browser handed
    over (the address at its push service and the two keys) and the name of the device are sealed with the server
    secret: the address is a key in itself, whoever has it may send to the device. ``endpoint_key`` is a keyed
    hash of the address, so that the same browser signing up twice stays one device."""

    __tablename__ = "push_devices"
    __table_args__ = (
        UniqueConstraint("uid", name="uq_push_devices_uid"),
        UniqueConstraint("user_id", "endpoint_key", name="uq_push_devices_user_endpoint"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(32))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint_key: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    #: The last message the push service took for this device.
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


# --- Vaults and documents ---------------------------------------------------------------------------------------------

#: What a member may do in a vault: look (``read``), add and change (``edit``), also share, give rights and delete
#: (``manage``). Each includes the ones before it.
READ = "read"
EDIT = "edit"
MANAGE = "manage"
RIGHTS = (READ, EDIT, MANAGE)

#: Where a document stands: being read in (``processing``, from the next block), waiting in the inbox, filed, or in the
#: trash for 30 days.
PROCESSING = "processing"
INBOX = "inbox"
FILED = "filed"
TRASH = "trash"
STATUSES = (PROCESSING, INBOX, FILED, TRASH)

#: What a date on a document stands for. Reminders will read only this table.
DATE_KINDS = ("due", "contract_end", "warranty_end", "keep_until")


class Counter(Base):
    """Named counters. ``change_seq`` is the one every change to a document takes its number from: it only goes up,
    and a number is taken inside the transaction that makes the change, so numbers appear in the order the changes
    become visible (SQLite lets one writer at a time through)."""

    __tablename__ = "counters"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class Vault(Base):
    """A place for documents. Every person has one of their own (``personal_of``), made together with the account;
    shared ones (a household, a business) are made by the operator. ``folder`` is the name on the disk, made once and
    never changed, so that renaming a vault moves no file."""

    __tablename__ = "vaults"
    __table_args__ = (
        # One personal vault per person: the database holds it, not a check before the insert.
        Index("uq_vaults_personal", "personal_of", unique=True),
        Index("uq_vaults_folder", text("lower(folder)"), unique=True),
        # Ids go out (to apps that keep a copy): one that was used once is never given again.
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    folder: Mapped[str] = mapped_column(String(64))
    icon: Mapped[str] = mapped_column(String(16), default="folder")
    #: The person whose own vault this is. A person cannot be deleted while their vault holds documents.
    personal_of: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class VaultMember(Base):
    __tablename__ = "vault_members"

    vault_id: Mapped[int] = mapped_column(ForeignKey("vaults.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    right: Mapped[str] = mapped_column(String(8))


class Sender(Base):
    """Who a document is from. One row per name and vault: a vault's senders are its own, so that nothing done in one
    vault tells anything about another (``services/catalog.py``). ``key`` is the name as it compares
    (``names.name_key``: case and Unicode folded), unique within the vault."""

    __tablename__ = "senders"
    __table_args__ = (Index("uq_senders_key", "vault_id", "key", unique=True), {"sqlite_autoincrement": True})

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vault_id: Mapped[int] = mapped_column(ForeignKey("vaults.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(160))
    key: Mapped[str] = mapped_column(String(400))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class Kind(Base):
    """The kind of a document (invoice, contract ...). Two sorts: the ones that come with nexpaper and the operator
    keeps (``vault_id`` empty, for the whole server), and the ones a vault makes for itself (``vault_id``), like its
    senders and tags: nothing done in one vault tells anything about another. ``key`` names the ones that come with
    nexpaper, so that the interface can show them in its own language until they are renamed. A document has a kind of
    the server or of its own vault."""

    __tablename__ = "kinds"
    __table_args__ = (
        # One name once for the whole server, and once in each vault (a name of a vault may repeat one of the server's
        # only when the operator renames a kind afterwards; the lists show the server's then).
        Index("uq_kinds_server", "name_key", unique=True, sqlite_where=text("vault_id IS NULL")),
        Index("uq_kinds_vault", "vault_id", "name_key", unique=True, sqlite_where=text("vault_id IS NOT NULL")),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(32), default="")
    name: Mapped[str] = mapped_column(String(60))
    #: The name as it compares (``names.name_key``), unique within the server's kinds and within a vault.
    name_key: Mapped[str] = mapped_column(String(160))
    hue: Mapped[int] = mapped_column(Integer, default=30)
    position: Mapped[int] = mapped_column(Integer, default=0)
    vault_id: Mapped[int | None] = mapped_column(ForeignKey("vaults.id", ondelete="CASCADE"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    #: How many years documents of this kind are kept (``services/keeping.py``); empty: no keeping time. The kinds that
    #: come with nexpaper have none.
    keep_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The last decision about the documents already there was "for new ones only": a time set then did not reach
    #: them, a time taken away then left their worked-out dates as set by hand.
    keep_new_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))


class Tag(Base):
    """A free word on documents, like a sender one row per name and vault (``key`` as with ``Sender``)."""

    __tablename__ = "tags"
    __table_args__ = (Index("uq_tags_key", "vault_id", "key", unique=True), {"sqlite_autoincrement": True})

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vault_id: Mapped[int] = mapped_column(ForeignKey("vaults.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(40))
    key: Mapped[str] = mapped_column(String(120))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_vault_status", "vault_id", "status"),
        Index("ix_documents_change_seq", "change_seq"),
        Index("ix_documents_trashed", "trashed_at"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vault_id: Mapped[int] = mapped_column(ForeignKey("vaults.id", ondelete="RESTRICT"))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("senders.id", ondelete="SET NULL"), nullable=True)
    kind_id: Mapped[int | None] = mapped_column(ForeignKey("kinds.id", ondelete="SET NULL"), nullable=True)
    date: Mapped[Any] = mapped_column(Date, nullable=True)
    #: In cents. A whole number: money is never a float here.
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default=text("'EUR'"))
    status: Mapped[str] = mapped_column(String(12), default=FILED)
    source: Mapped[str] = mapped_column(String(16), default="upload")
    added_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    #: Where each proposed field came from (rule, AI, e-invoice ...), as long as the document waits in the inbox.
    suggest: Mapped[Any] = mapped_column(JSON, nullable=True)
    trashed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: Where the document stood before it went to the trash, so that restoring puts it back there.
    trashed_status: Mapped[str] = mapped_column(String(12), default="", server_default=text("''"))
    #: The number of the last change (``Counter`` ``change_seq``), for ``GET /api/v1/changes``.
    change_seq: Mapped[int] = mapped_column(Integer, default=0)
    #: A document that has the same file (``same``) or looks the same (``similar``) as this one and that the owner may
    #: see, found when the file was read in. No foreign key: the answers show it only to somebody who may see it too.
    duplicate_of: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duplicate_kind: Mapped[str] = mapped_column(String(8), default="", server_default=text("''"))
    #: Why reading the file failed (``encrypted``, ``broken``, ``too_many_pages``, ``too_large``, ``timeout``,
    #: ``failed``); empty while all is well. The document waits in the inbox then, and a person may try again.
    process_error: Mapped[str] = mapped_column(String(24), default="", server_default=text("''"))
    #: What the check of the files (``services/filecheck.py``) found: empty while all is well, ``changed`` when a file
    #: no longer has its checksum, ``missing`` when one is gone from the disk. Not a change of the document: no number.
    files_state: Mapped[str] = mapped_column(String(8), default="", server_default=text("''"))


class DocumentDate(Base):
    __tablename__ = "document_dates"
    __table_args__ = (UniqueConstraint("document_id", "kind", name="uq_document_dates_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    date: Mapped[Any] = mapped_column(Date)
    # Deadlines (F1, ``services/deadlines.py``). A contract (``contract_end``) may know its notice period and how many
    # months it renews by; ``notice_date`` is the last day to cancel worked out from them (kept with the row, so the
    # search and the deadlines page compare it in SQL). Any deadline may be done (paid, cancelled, claimed): who and
    # when. ``renewed_from`` is the end the contract was last renewed from by itself: never twice from the same end.
    notice_n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notice_unit: Mapped[str | None] = mapped_column(String(8), nullable=True)
    renew_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notice_date: Mapped[Any] = mapped_column(Date, nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    done_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    renewed_from: Mapped[Any] = mapped_column(Date, nullable=True)
    #: The end of a contract as a person last set it (or the term changed): the renewal counts from here in whole terms,
    #: so a contract to the 30th does not drift to the end of the month after a February.
    renew_anchor: Mapped[Any] = mapped_column(Date, nullable=True)
    #: Set by a person, not worked out from the kind (only ``keep_until`` is ever worked out): a change of the kind, the
    #: date or the vault leaves it as it is (``services/keeping.py``).
    manual: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))


class DocumentTag(Base):
    __tablename__ = "document_tags"

    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True)


class Version(Base):
    """A version of a document: the file as it came (never overwritten) and, from the reading block on, the searchable
    copy beside it. The paths are relative to ``dokumente/``."""

    __tablename__ = "versions"
    __table_args__ = (
        UniqueConstraint("document_id", "n", name="uq_versions_n"),
        Index("uq_versions_original", text("lower(original_path)"), unique=True),
        Index("ix_versions_sha256", "sha256"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    n: Mapped[int] = mapped_column(Integer)
    original_path: Mapped[str] = mapped_column(String(600))
    archive_path: Mapped[str] = mapped_column(String(600), default="", server_default=text("''"))
    sha256: Mapped[str] = mapped_column(String(64), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    note: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"))
    #: A fingerprint of how the first page looks (256 hex digits, ``app/worker.py``), to find the same sheet
    #: scanned again; empty until the file was read.
    phash: Mapped[str] = mapped_column(String(256), default="", server_default=text("''"))
    #: The checksum of the searchable copy as it was put in place (empty: none made, or not noted yet; the check of the
    #: files notes it the first time it sees the file).
    archive_sha256: Mapped[str] = mapped_column(String(64), default="", server_default=text("''"))


class Upload(Base):
    """A file that comes in pieces: announced with its size and checksum, received in order, then made a document. The
    id belongs to the account that made it (anybody else's answers 404). Gone 24 hours after the last piece."""

    __tablename__ = "uploads"
    __table_args__ = (Index("ix_uploads_user", "user_id", "state"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    vault_id: Mapped[int] = mapped_column(ForeignKey("vaults.id", ondelete="CASCADE"))
    #: The name the file had, cleaned, only a proposal for the title.
    filename: Mapped[str] = mapped_column(String(200), default="")
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    received: Mapped[int] = mapped_column(Integer, default=0)
    #: ``upload`` (a browser) or ``api`` (a device or a program).
    source: Mapped[str] = mapped_column(String(8), default="upload")
    #: ``open`` (receiving), ``finishing`` (being made a document), ``done`` (the document is ``document_id``).
    state: Mapped[str] = mapped_column(String(10), default="open")
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    #: The API key that started it (a scanner, the iPhone shortcut): such a key sees and goes on with only its own
    #: uploads. Empty for a browser or a device. Last column: the phone block's step adds it at the end.
    api_key_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: A new version of this document, not a document of its own (the page tools, B5). Last column: the step of the
    #: page tools adds it at the end.
    target_document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class Share(Base):
    """One document given to one person who is not (or not with this right) in its vault."""

    __tablename__ = "shares"

    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    right: Mapped[str] = mapped_column(String(8))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Link(Base):
    """A link to one document for somebody without an account. The token is found by its hash (``token_hash``) and kept
    sealed with the server's secret (``token_enc``), so that the person who made it can copy the address again; the
    database alone tells nobody a token. ``revoked_at`` ends it at once, ``until`` by itself, and the operator's switch
    ends all of them."""

    __tablename__ = "links"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    recipient: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_enc: Mapped[str] = mapped_column(String(400), default="", server_default=text("''"))
    until: Mapped[datetime] = mapped_column(UtcDateTime)
    allow_download: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    opened_count: Mapped[int] = mapped_column(Integer, default=0)
    last_opened_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class Event(Base):
    """The history of a document: who did what when. Never the contents, only which fields changed."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_document", "document_id", "id"), {"sqlite_autoincrement": True})

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    #: The person; empty when it was done through a link (``by_link``: whom it was made for) or by the system.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    by_link: Mapped[str] = mapped_column(String(100), default="", server_default=text("''"))
    at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    action: Mapped[str] = mapped_column(String(24))
    detail: Mapped[Any] = mapped_column(JSON, nullable=True)


class Tombstone(Base):
    """What a program that follows ``GET /api/v1/changes`` cannot see from a document row: a document that is gone for
    somebody (moved away, deleted for good, a share ended) and a vault whose rights changed. ``seq`` comes from the same
    counter as ``Document.change_seq``. Holds no contents, only numbers."""

    __tablename__ = "tombstones"
    __table_args__ = (Index("ix_tombstones_vault", "vault_id"), Index("ix_tombstones_user", "user_id"),
                      Index("ix_tombstones_at", "at"))

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    #: ``gone`` (a document), ``vault_lost`` and ``vault_refresh`` (a vault: fetch its documents anew).
    kind: Mapped[str] = mapped_column(String(16))
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vault_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Whom it concerns; empty: every member of ``vault_id``.
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Job(Base):
    """Work for the background: renaming files after a change of fields, removing files of a document gone for good. The
    reading of documents joins them in the next block. At most one job of a kind is waiting for a document."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_state", "state", "id"),
        Index("uq_jobs_waiting", "kind", "ref", unique=True, sqlite_where=text("state = 'queued'")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    #: What the job is about (a document), to find it and to keep two of a kind from waiting for the same.
    ref: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[Any] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String(8), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    error: Mapped[str] = mapped_column(String(300), default="", server_default=text("''"))


class Pairing(Base):
    """A code that pairs a device once (``services/pairing.py``): shown as a QR code under My account (``kind = qr``),
    or handed to an app at the end of OAuth 2 with PKCE (``kind = oauth``). Only the SHA-256 of the code is stored. A
    code is used at most once (``used_at``, set in the same write that checks it) and runs out after a few minutes."""

    __tablename__ = "pairings"
    __table_args__ = (Index("ix_pairings_account", "account_id", "kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(8))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: The device the code became (for the browser that waits to hear of it).
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    #: OAuth only: the app, where the code goes back to, the PKCE challenge (S256) and the name the device will carry.
    client_id: Mapped[str] = mapped_column(String(64), default="", server_default=text("''"))
    redirect_uri: Mapped[str] = mapped_column(String(300), default="", server_default=text("''"))
    challenge: Mapped[str] = mapped_column(String(128), default="", server_default=text("''"))
    device_name: Mapped[str] = mapped_column(String(80), default="", server_default=text("''"))


class VersionText(Base):
    """The text of a version, page by page (B3): what a PDF carried and what the recognition read. The pages are kept
    in one text, separated by a form feed (``\\f``). A version whose file was not read yet has no row."""

    __tablename__ = "version_texts"

    version_id: Mapped[int] = mapped_column(ForeignKey("versions.id", ondelete="CASCADE"), primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    pages: Mapped[int] = mapped_column(Integer, default=0)
    #: Pages whose text came from the recognition (the others carried text of their own, or none was found).
    ocr_pages: Mapped[int] = mapped_column(Integer, default=0)
    #: The languages the recognition used (``deu+eng``); empty when nothing was recognised.
    languages: Mapped[str] = mapped_column(String(64), default="")
    #: SHA-1 of ``text``: the search index compares it instead of the text.
    digest: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class SearchEntry(Base):
    """What the search index holds for a document: the change it was made for (``Document.change_seq``) and a digest
    of what went in, so that a change of something the index does not hold (a right, the date) costs no new entry. The
    entries themselves are in ``doc_fts`` and ``doc_tri`` (rowid = document id), made by
    ``services/search_index.py``."""

    __tablename__ = "search_entries"

    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    digest: Mapped[str] = mapped_column(String(40), default="")


#: The word index, rowid = document id. Contentless: it holds no second copy of anything (the text is in
#: ``version_texts``, the rest in the tables of its own), and an entry is dropped by its rowid (``contentless_delete``,
#: SQLite 3.43). Case and accents do not count.
FTS_TABLE = "doc_fts"
#: Parts of words, as trigrams: a word found in the middle (``werke`` in ``Stadtwerke``). What it covers was decided by
#: the measurement in ``docs/search.md``.
#: Both carry a column ``scope``: who may find the entry (``v<vault>v`` for its vault, ``u<person>u`` for each person it
#: is shared with), so that a search reads only the entries of what the caller may see (``services/search.py``).
TRI_TABLE = "doc_tri"
SEARCH_STATEMENTS = (
    (
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5(title, sender, text, notes, tags, scope, "
        "tokenize = 'unicode61 remove_diacritics 2', content = '', contentless_delete = 1)"
    ),
    (
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {TRI_TABLE} USING fts5(title, sender, text, notes, tags, scope, "
        "tokenize = 'trigram remove_diacritics 1', content = '', contentless_delete = 1)"
    ),
    # A document deleted for good leaves no entry behind.
    (
        "CREATE TRIGGER IF NOT EXISTS documents_search_gone AFTER DELETE ON documents BEGIN "
        "DELETE FROM doc_fts WHERE rowid = old.id; DELETE FROM doc_tri WHERE rowid = old.id; END"
    ),
)


@event.listens_for(Base.metadata, "after_create")
def _search_tables(_target: Any, connection: Any, **_kw: Any) -> None:
    """``create_all`` makes the tables SQLAlchemy has no type for, too: a new database and a recorded schema hold the
    same as a migrated one."""
    for statement in SEARCH_STATEMENTS:
        connection.exec_driver_sql(statement)


def _free_folder(connection: Any, name: str) -> str:
    """A folder name no vault has (the disk may not tell ``Haushalt`` from ``haushalt``). Called with the write lock
    held (inside a flush), so two vaults made at the same moment cannot pick the same."""
    base = clean_segment(name, "vault")
    taken = {folded(row[0]) for row in connection.execute(select(Vault.__table__.c.folder))}
    candidate, counter = base, 1
    while folded(candidate) in taken:
        counter += 1
        suffix = f" {counter}"
        candidate = base[: 48 - len(suffix)].rstrip(" .") + suffix
    return candidate


def free_folder(connection: Any, name: str) -> str:
    return _free_folder(connection, name)


@event.listens_for(Account, "after_insert")
def _make_personal_vault(_mapper: Any, connection: Any, account: Account) -> None:
    """Every person has exactly one vault of their own, made in the same write as the account: by an invitation, through
    the provider, for the first account, and in a test that writes the row straight in. The unique index on
    ``personal_of`` is what keeps it at one."""
    label = account.display_name or account.name
    result = connection.execute(
        insert(Vault.__table__).values(
            name=label, folder=_free_folder(connection, label), icon="user", personal_of=account.id,
            created_at=utcnow(), created_by=account.id,
        )
    )
    connection.execute(
        insert(VaultMember.__table__).values(vault_id=result.inserted_primary_key[0], user_id=account.id, right=MANAGE)
    )


__all__ = [
    "DATE_KINDS",
    "EDIT",
    "FILED",
    "INBOX",
    "MANAGE",
    "MEMBER",
    "OPERATOR",
    "PROCESSING",
    "READ",
    "RIGHTS",
    "ROLES",
    "SIGN_IN_OIDC",
    "SIGN_IN_PASSWORD",
    "STAGE_CODES",
    "STAGE_FULL",
    "STAGE_SETUP",
    "STATUSES",
    "TRASH",
    "Account",
    "ApiKey",
    "AuthSession",
    "Base",
    "Counter",
    "Device",
    "Document",
    "DocumentDate",
    "DocumentTag",
    "EmailConfirmation",
    "Event",
    "Invite",
    "Job",
    "Kind",
    "Link",
    "Note",
    "Pairing",
    "Passkey",
    "PasswordReset",
    "PushDevice",
    "SearchEntry",
    "Sender",
    "Setting",
    "Share",
    "Tag",
    "Tombstone",
    "Vault",
    "VaultMember",
    "Version",
    "VersionText",
    "free_folder",
    "utcnow",
]


# --- Inputs: the intake folder and the mailbox (block B8) ------------------------------------------------------------


class IntakeItem(Base):
    """A file that came in through the intake folder or the mailbox, and the document it became.

    The row is written in the same transaction as the document, so a restart in between never takes a file twice:
    ``folder`` rows stand ``taken`` until the file is gone from the folder (``done`` then); ``mail`` rows name the
    mail (UIDVALIDITY, UID and the number of the part) and are ``done`` at once. ``detail`` says where it came from
    (the sender's address and the subject of a mail, the subfolder and the name of a file); ``unknown`` marks what went
    to the operator because nobody could be told from it."""

    __tablename__ = "intake_items"
    __table_args__ = (
        Index("ix_intake_items_document", "document_id"),
        Index("uq_intake_items_mail", "key", unique=True, sqlite_where=text("source = 'mail'")),
        Index("uq_intake_items_taken", "source", "key", unique=True, sqlite_where=text("state = 'taken'")),
        Index("ix_intake_items_message", "message"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    #: ``folder`` or ``mail``.
    source: Mapped[str] = mapped_column(String(8))
    #: ``folder``: the path of the file inside the intake folder; ``mail``: ``<uidvalidity>:<uid>:<part>``.
    key: Mapped[str] = mapped_column(String(600))
    #: ``taken`` (the document is there, the file may still stand in the folder) or ``done``.
    state: Mapped[str] = mapped_column(String(8), default="done")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    #: The time of the last change of the file in the folder (nanoseconds), to know it again after a restart.
    mtime_ns: Mapped[int] = mapped_column(Integer, default=0)
    #: A mail: the SHA-256 of its Message-ID, so that the same mail is not taken again when the server gives its
    #: mailbox new UIDs (a new UIDVALIDITY).
    message: Mapped[str] = mapped_column(String(64), default="")
    unknown: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[Any] = mapped_column(JSON, nullable=True)
    at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class MailSender(Base):
    """An address a person forwards documents from to the mailbox (My account, Upload). It counts once the link mailed
    to it was opened (``confirmed_at``); until then only the hash of the link's token is kept, for 24 hours."""

    __tablename__ = "mail_senders"
    __table_args__ = (
        Index("uq_mail_senders_user_key", "user_id", "address_key", unique=True),
        Index("ix_mail_senders_key", "address_key"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    address: Mapped[str] = mapped_column(String(255))
    #: The address as it compares (case folded).
    address_key: Mapped[str] = mapped_column(String(255))
    token_hash: Mapped[str] = mapped_column(String(64), default="")
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


__all__ += ["IntakeItem", "MailSender"]


# --- Paperless import and export for the tax adviser (block B9) ------------------------------------------------------


class PaperlessItem(Base):
    """A document of a Paperless-ngx server and what became of it here (``services/paperless.py``): ``done`` with the
    document it became (written in the same transaction as the document, so a restart never takes it twice), or
    ``skipped`` with the reason (tried again at the next run). ``origin`` names the Paperless server (a hash of its
    address), so that the numbers of two servers never mix."""

    __tablename__ = "paperless_items"
    __table_args__ = (
        Index("uq_paperless_items_origin", "origin", "paperless_id", unique=True),
        Index("ix_paperless_items_document", "document_id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    origin: Mapped[str] = mapped_column(String(64))
    paperless_id: Mapped[int] = mapped_column(Integer)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    #: ``done`` or ``skipped``.
    state: Mapped[str] = mapped_column(String(8))
    #: Why it was skipped (``file_missing``, ``too_large``, ``unsupported_type`` ...); empty when done.
    reason: Mapped[str] = mapped_column(String(32), default="")
    #: The document waits in the inbox once it was read (it carried an inbox tag in Paperless); else it is filed.
    inbox: Mapped[bool] = mapped_column(Boolean, default=False)
    at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Export(Base):
    """A ZIP of documents a person asked for (``services/exports.py``): packed in the background, kept for a few days
    (longer while a link to it lasts), then removed with its file. ``params`` is what was asked for; ``vault_ids`` the
    vaults the packed documents came from (a link lives only while its maker still sees all of them)."""

    __tablename__ = "exports"
    __table_args__ = (Index("ix_exports_user", "user_id", "state"), {"sqlite_autoincrement": True})

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    #: ``queued``, ``packing``, ``ready`` or ``failed``.
    state: Mapped[str] = mapped_column(String(10), default="queued")
    params: Mapped[Any] = mapped_column(JSON, nullable=True)
    vault_ids: Mapped[Any] = mapped_column(JSON, nullable=True)
    #: The language of the list inside (its headings), ``de`` or ``en``.
    language: Mapped[str] = mapped_column(String(8), default="en")
    documents: Mapped[int] = mapped_column(Integer, default=0)
    #: The size of the ZIP.
    size: Mapped[int] = mapped_column(Integer, default=0)
    #: The sum of the amounts of the documents packed, in cents.
    total: Mapped[int] = mapped_column(Integer, default=0)
    #: The name of the file in ``<data>/exports``; empty until it is packed.
    file: Mapped[str] = mapped_column(String(80), default="")
    error: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)


class ExportLink(Base):
    """A link to an export for somebody without an account (the tax adviser), like ``Link`` for a document: found by the
    hash of its token, the token sealed with the server's secret so that its maker can copy the address again; it ends
    when revoked, at ``until``, with the operator's switch for links, with the export, or when its maker may no longer
    see what is in it."""

    __tablename__ = "export_links"
    __table_args__ = (Index("ix_export_links_export", "export_id"), {"sqlite_autoincrement": True})

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    export_id: Mapped[int] = mapped_column(ForeignKey("exports.id", ondelete="CASCADE"))
    recipient: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_enc: Mapped[str] = mapped_column(String(400), default="")
    until: Mapped[datetime] = mapped_column(UtcDateTime)
    opened_count: Mapped[int] = mapped_column(Integer, default=0)
    last_opened_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


__all__ += ["Export", "ExportLink", "PaperlessItem"]


# --- Page tools: versions and blank separator pages (block B5) -------------------------------------------------------


class VersionInfo(Base):
    """What a version is beyond its file (the page tools, ``services/pagetools.py``): how it came about (``origin``:
    ``pages``, ``merged``, ``split``, ``restored``, ``uploaded``), from which version (``from_n``), whether it is read
    yet (``state``: ``ready``, ``processing``, ``failed`` with ``error``), and the blank pages found in it
    (``blanks``: the pages counted from 1, null while nobody looked) that a split may drop. A version without a row is
    an ordinary ready one. ``detail`` holds numbers and ids only, never contents."""

    __tablename__ = "version_info"
    __table_args__ = (Index("ix_version_info_document", "document_id", "state"),)

    version_id: Mapped[int] = mapped_column(ForeignKey("versions.id", ondelete="CASCADE"), primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    origin: Mapped[str] = mapped_column(String(12), default="")
    from_n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(String(12), default="ready")
    error: Mapped[str] = mapped_column(String(24), default="")
    detail: Mapped[Any] = mapped_column(JSON, nullable=True)
    blanks: Mapped[Any] = mapped_column(JSON, nullable=True)
    #: A person said "keep it as one document": the proposal to split is not made again for this version.
    split_dismissed: Mapped[bool] = mapped_column(Boolean, default=False)


__all__ += ["VersionInfo"]
class Rule(Base):
    """What nexpaper fills in by itself when a document arrives (``services/rules.py``): conditions (``when``, all must
    hold) and what follows (``then``), in the order of ``position``. A rule belongs to one vault (made by somebody who
    manages it, for the documents that arrive there) or, without a vault, to the whole server (the operator's). The
    texts in a rule are compared as plain text, never as a pattern."""

    __tablename__ = "rules"
    __table_args__ = (Index("ix_rules_vault", "vault_id", "position"), {"sqlite_autoincrement": True})

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vault_id: Mapped[int | None] = mapped_column(ForeignKey("vaults.id", ondelete="CASCADE"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    on: Mapped[bool] = mapped_column(Boolean, default=True)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    last_hit_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: ``[{"field": "sender", "op": "is", "values": ["Stadtwerke Lindenau"]}, ...]``
    when: Mapped[Any] = mapped_column(JSON)
    #: ``[{"field": "vault", "value": 3}, {"field": "tag", "value": "strom"}, ...]``
    then: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class EInvoice(Base):
    """The data of an e-invoice (``services/einvoices.py``), read from the version that carries it: the XML inside a
    ZUGFeRD or Factur-X PDF, or an XRechnung that came as XML. A later version of the document (pages turned, joined)
    no longer carries the XML; the data stay with the version that did. ``xml`` holds the XML taken out of a PDF (empty
    when the original itself is the XML)."""

    __tablename__ = "einvoices"

    version_id: Mapped[int] = mapped_column(ForeignKey("versions.id", ondelete="CASCADE"), primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    #: ``ZUGFeRD (EN 16931)``, ``Factur-X (BASIC)``, ``XRechnung (UBL)``, ``XRechnung (CII)``, ``UBL``, ``CII``.
    format: Mapped[str] = mapped_column(String(40))
    number: Mapped[str] = mapped_column(String(100), default="")
    issued: Mapped[Any] = mapped_column(Date, nullable=True)
    due: Mapped[Any] = mapped_column(Date, nullable=True)
    seller: Mapped[str] = mapped_column(String(200), default="")
    seller_vat: Mapped[str] = mapped_column(String(40), default="")
    buyer: Mapped[str] = mapped_column(String(200), default="")
    #: The buyer's reference (for German authorities the "Leitweg-ID").
    buyer_ref: Mapped[str] = mapped_column(String(100), default="")
    iban: Mapped[str] = mapped_column(String(40), default="")
    currency: Mapped[str] = mapped_column(String(3), default="")
    #: In cents, as the invoice states them; empty where it does not.
    net: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tax: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gross: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payable: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credit_note: Mapped[bool] = mapped_column(Boolean, default=False)
    #: ``[{"text", "quantity", "unit", "price", "total"}, ...]``, at most 200.
    lines: Mapped[Any] = mapped_column(JSON, nullable=True)
    xml: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


__all__ += ["EInvoice", "Rule"]


class DeadlineSnooze(Base):
    """"Later" on a deadline, for one person: until that day nobody reminds them of it (the others in the vault are
    reminded as before). Gone with the date or the person."""

    __tablename__ = "deadline_snoozes"
    __table_args__ = (UniqueConstraint("date_id", "user_id", name="uq_deadline_snoozes"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date_id: Mapped[int] = mapped_column(ForeignKey("document_dates.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    until: Mapped[Any] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


__all__ += ["DeadlineSnooze"]
