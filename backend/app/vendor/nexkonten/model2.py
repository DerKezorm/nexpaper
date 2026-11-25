"""The data and the stores of part 2 (since 0.3.0): second factor, passkeys, sessions, profile pictures.

Separate protocols beside ``model.Store``, so that an app of 0.2.1 keeps working: an app takes the parts it uses, and
usually one store object of the app answers all of them. Secrets reach these stores in plain text and are sealed by the
app with its own key and context (``set_totp(account, seed)``, ``totp_seed(account)``): the authenticator apps set up
under the older version keep working, whatever the app's sealing looks like.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .model import AccountId

#: ``Session.kind``: a browser, a sign-in waiting for its second factor, a paired device (iPhone, iPad).
KIND_BROWSER = "browser"
KIND_WAITING = "waiting"
KIND_DEVICE = "device"

#: ``Session.stage``: a full session; one that can only set up a second factor (required by the app); one that shows
#: the new recovery codes once before it becomes full.
STAGE_FULL = "full"
STAGE_SETUP = "setup"
STAGE_CODES = "codes"


@dataclass(frozen=True)
class Session:
    """One way in, as the session list shows it. ``uid`` is the public handle (never the token)."""

    uid: str
    account_id: AccountId
    kind: str
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime | None = None
    remember: bool = True
    stage: str = STAGE_FULL
    provider_checked: bool = False
    label: str = ""
    address: str = ""


@dataclass(frozen=True)
class Passkey:
    """One passkey of an account: ``credential_id`` and ``public_key`` as the browser gave them."""

    uid: str
    account_id: AccountId
    credential_id: bytes
    public_key: bytes
    sign_count: int
    name: str
    created_at: datetime
    last_used_at: datetime | None = None


class FactorStore(Protocol):
    """The second factor of an account, over the app's columns (``totp_secret_enc``, ``totp_recovery``,
    ``totp_last_step``; nexmail ``totp_geheimnis``, ``wiederherstellungscode``)."""

    def totp_seed(self, account_id: AccountId) -> str | None:
        """The opened seed of a **confirmed** TOTP (base32), None without one. An unconfirmed seed of an older version
        is no factor."""
        ...

    def set_totp(self, account_id: AccountId, seed: str | None) -> None:
        """Seal and store a confirmed seed (None takes it away, with the last step)."""
        ...

    def claim_step(self, account_id: AccountId, step: int) -> bool:
        """Keep ``step`` as the last used time step with one statement that succeeds only when the stored one is
        smaller: two requests with one code never both get through."""
        ...

    def recovery_hashes(self, account_id: AccountId) -> list[str]:
        """The stored forms of the account's unused recovery codes."""
        ...

    def set_recovery(self, account_id: AccountId, hashes: list[str]) -> None:
        """Replace the list (new codes, or none)."""
        ...

    def claim_recovery(self, account_id: AccountId, stored: str) -> bool:
        """Use one stored form up with one statement; False when another request was faster."""
        ...

    def recovery_key(self) -> bytes:
        """The app's key for the stored form of recovery codes (derived from its server secret, ``h1:`` form)."""
        ...

    def factor_required(self) -> bool:
        """The operator's switch "second factor for everybody" (off by default; an installation keeps its own)."""
        ...

    # Since 0.3.3: the seed of an authenticator that is set up halfway waits in the store, sealed, so that a restart
    # between the QR code and the first code loses nothing. A store without these two keeps it in memory as before;
    # the contract tests ask for them.

    def pending_totp(self, account_id: AccountId) -> tuple[str, datetime] | None:
        """The opened seed that waits for its first code and until when it waits; None without one. Never a factor:
        ``totp_seed`` does not answer it."""
        ...

    def set_pending_totp(self, account_id: AccountId, seed: str | None, until: datetime | None) -> None:
        """Seal and keep the waiting seed (in another context than a confirmed one), None takes it away."""
        ...


class PasskeyStore(Protocol):
    """Passkeys over the app's table (``passkeys`` in nexdiary and nexpaper)."""

    def passkeys_allowed(self) -> bool:
        """The operator's switch "passkeys allowed" (on by default)."""
        ...

    def passkeys_of(self, account_id: AccountId) -> list[Passkey]: ...

    def find_passkey(self, credential_id: bytes) -> Passkey | None: ...

    def add_passkey(self, passkey: Passkey) -> None:
        """Insert; the credential id is unique in the table."""
        ...

    def claim_counter(self, uid: str, old: int, new: int) -> bool:
        """Write the new sign count only where the old one still stands (one statement)."""
        ...

    def remove_passkey(self, account_id: AccountId, uid: str) -> bool: ...

    def remove_passkeys(self, account_id: AccountId) -> int: ...

    def user_handle(self, account_id: AccountId) -> bytes:
        """The account's random user handle for passkeys, made and kept at its first passkey."""
        ...


class SessionStore(Protocol):
    """Sessions over the app's table (``auth_sessions``; nexmail ``sitzung``), token kept as SHA-256 hex."""

    def add_session(self, session: Session, token_hash: str) -> None: ...

    def session_by_hash(self, token_hash: str) -> Session | None: ...

    def touch_session(self, uid: str, last_seen_at: datetime, expires_at: datetime) -> None: ...

    def set_stage(self, uid: str, stage: str) -> None: ...

    def sessions_of(self, account_id: AccountId) -> list[Session]:
        """Browsers and paired devices of the account, for "Where am I signed in"."""
        ...

    def end_session(self, account_id: AccountId, uid: str) -> bool: ...

    def end_everywhere(self, account_id: AccountId, keep_uid: str | None) -> int:
        """End every browser session, waiting sign-in and paired device of the account but ``keep_uid``. Calendar and
        address book programs, API keys and passkeys stay."""
        ...

    def device_key(self, account_id: AccountId) -> str:
        """The account's random key for "known browser" marks, made at first use; a new one makes old marks
        worthless (new password, block, delete)."""
        ...

    def renew_device_key(self, account_id: AccountId) -> None: ...


class PictureStore(Protocol):
    """Profile pictures over the app's columns (``avatar``, ``avatar_at``; nexmail ``profilbild``,
    ``profilbild_am``)."""

    def picture_of(self, account_id: AccountId) -> tuple[bytes, datetime] | None:
        """The stored WebP and when it was set; None without one."""
        ...

    def set_picture(self, account_id: AccountId, data: bytes, at: datetime, source: str) -> None:
        """Store a picture the person set (``source`` ``"own"``) or one from a provider (``"provider"``)."""
        ...

    def remove_picture(self, account_id: AccountId) -> None: ...
