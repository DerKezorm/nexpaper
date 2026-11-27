"""nexpaper's side of the shared account module ``vendor/nexkonten``: the ``Store`` over its tables.

The module runs setup, invitations, signing in with a password, the profile, a forgotten password, the second factor,
passkeys and sessions the same in every nex app; it never sees a database and asks through a ``Store``, which is this
one, over ``users``, ``invites``, ``password_resets``, ``email_confirmations``, ``auth_sessions``, ``devices``,
``api_keys``, ``passkeys`` and the tables of ``models_accounts``. One instance works inside one SQLAlchemy session (one
request); the module commits when an outcome is settled and rolls back when it refuses after a write.

⚠️ **The columns keep their names.** ``users.name`` is the module's ``username`` (and the field ``name`` of every
route). Two answers about the address, without a break for 1.12.0:

- ``email_counts`` (new) says the address **counts**: signing in with it, "Forgot your password?", notices. Every
  address of 1.12.0 counts.
- ``email_confirmed_at`` stays what it was: the address is **proven** by a link. Only a proven address decides whose
  vault a mail to the intake reaches (``services/mail_senders.py``), and reminders, deadlines and exports go only to
  one; an address that only counts never pulls post into a vault.

A waiting address stays in ``email_confirmations`` (one per account, the hash of the token as in 1.12.0, so its links
keep working).
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..models import (
    MEMBER,
    OPERATOR,
    SIGN_IN_OIDC,
    SIGN_IN_PASSWORD,
    Account,
    ApiKey,
    AuthSession,
    Device,
    EmailConfirmation,
    OidcProvider,
    Pairing,
    PasswordReset,
    utcnow,
)
from ..models import Invite as InviteRow
from ..models import Passkey as PasskeyRow
from ..models_accounts import FailedUnknown, FormerName, SetupClaim
from ..security import (
    LOCK_MINUTES,
    MAX_FAILURES,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hash_token,
    server_key,
    verify_password,
)
from ..vendor import nexkonten, nexwasneu
from ..vendor.nexkonten import (
    Access,
    AccountId,
    EmailChange,
    Event,
    Invite,
    NewAccount,
    Picture,
    Reset,
    Taken,
    names,
)
from ..vendor.nexkonten import Account as KontoAccount
from ..vendor.nexkonten.model2 import KIND_BROWSER, KIND_DEVICE, KIND_WAITING, STAGE_FULL
from ..vendor.nexkonten.model2 import Passkey as PasskeyData
from ..vendor.nexkonten.model2 import Session as SessionData
from ..vendor.nexkonten.model3 import SignInSettings

logger = logging.getLogger("nexpaper.auth")

PROVIDER = "provider"
#: The operator's switches of part 2: "Require a second factor of everybody" was nexpaper's ``two_factor_required``
#: already; "Passkeys allowed" is new and on from the start.
SWITCH_FACTOR_REQUIRED = "two_factor_required"
SWITCH_PASSKEYS = "passkeys_allowed"
#: The authenticator being set up is sealed apart from a confirmed one.
PENDING_TOTP_CONTEXT = "totp-pending"
#: A paired device in the list "These devices still have access": its uid with this in front.
DEVICE_UID = "device-"
#: The stage of an ``auth_sessions`` row that waits for the second step of a sign-in (the shared module's kind
#: ``waiting``): ``deps.require_account`` never takes it for a session.
STAGE_WAITING = "waiting"

#: The codes nexpaper answered with before the module, for scripts, the iPhone app and pages of 1.12.0 (the module's
#: own names stay inside; ``AccountError.public_code`` answers with these). The page maps them back.
OLD_CODES = {
    "username_invalid": "invalid_account_name",
    "username_taken": "name_taken",
    "email_invalid": "invalid_email",
    "fresh_sign_in_needed": "sign_in_again",
}


def configure() -> None:
    """The module knows nexpaper's name, log and codes from now on. At import and by the tests. The emergency hammer
    ``NEXPAPER_SECOND_FACTOR_OFF`` is read by the module from the environment (``<APP>_SECOND_FACTOR_OFF``)."""
    nexkonten.configure(
        nexkonten.AppConfig(
            app_name="nexpaper",
            # The setting, not only the environment: NEXPAPER_SETUP_TOKEN may stand in a .env file.
            setup_token=lambda: get_settings().setup_token,
            logger_name="nexpaper.auth",
            error_codes=OLD_CODES,
        )
    )


configure()


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def same(one: str | None, other: str | None) -> bool:
    return bool(one) and bool(other) and str(one).strip().casefold() == str(other).strip().casefold()


def counts(row: Account) -> bool:
    """The address counts (signing in, a forgotten password, notices)."""
    return bool((row.email or "").strip()) and bool(row.email_counts)


def proven(row: Account) -> bool:
    """Somebody opened a link mailed to the address (or followed an invitation mailed to it)."""
    return bool((row.email or "").strip()) and row.email_confirmed_at is not None


def pending_of(db: Session, account_id: int) -> str:
    """The address that waits for its link while the link holds, else ""."""
    row = db.scalar(select(EmailConfirmation).where(EmailConfirmation.account_id == account_id))
    return row.address if row is not None and _aware(row.expires_at) > utcnow() else ""


def oldest_name(db: Session, row: Account) -> str:
    """The first username the account ever had: the bridge for apps that keep the name as the key of a connection
    (nexpaper-ios up to 1.3): it stays the same across renames, and a former name never goes to anybody else."""
    first = db.scalar(select(FormerName.name).where(FormerName.account_id == row.id).order_by(FormerName.id).limit(1))
    return first or row.name


def former_names(db: Session, account_id: int) -> list[str]:
    """Every name the account had before, oldest first."""
    return list(db.scalars(select(FormerName.name).where(FormerName.account_id == account_id).order_by(FormerName.id)))


def by_any_name(db: Session, name: str) -> Account | None:
    """The account a name means for things in the background (the intake folder, the plus address): the current
    name, else a former one of an account that still exists. A former name of a deleted account finds nobody."""
    wanted = (name or "").strip().lower()
    if not wanted:
        return None
    row = db.scalar(select(Account).where(func.lower(Account.name) == wanted))
    if row is not None:
        return row
    account_id = db.scalar(
        select(FormerName.account_id).where(func.lower(FormerName.name) == wanted, FormerName.account_id.is_not(None))
        .order_by(FormerName.id.desc()).limit(1)
    )
    return db.get(Account, account_id) if account_id is not None else None


def names_by_account(db: Session) -> dict[int, list[str]]:
    """Per account its former names (the intake folder answers to them too)."""
    found: dict[int, list[str]] = {}
    for account_id, name in db.execute(
        select(FormerName.account_id, FormerName.name).where(FormerName.account_id.is_not(None)).order_by(FormerName.id)
    ):
        found.setdefault(int(account_id), []).append(name)
    return found


def _dummy_hash() -> str:
    """What ``check_password`` verifies against when there is no account or no password: the answer takes as long
    as for a wrong password and tells nobody which names or addresses exist."""
    from . import accounts

    return accounts._dummy_hash()


def device_label(row: Device) -> str:
    """A paired device in the lists of signed-in devices: its name, and the model where it says more (geraete 0.1.0,
    ``nexgeraete.describe``)."""
    if row.model and row.model != row.name:
        return f"{row.name} ({row.model})"
    return row.name


def blocked_since(row: Account) -> datetime | None:
    """When the operator blocked the account. A deletion blocks an account that was not blocked at the same moment
    (``set_deleted``): that mark belongs to the deletion, not to a block."""
    if row.blocked_at is None or (row.deleted_at is not None and _aware(row.blocked_at) == _aware(row.deleted_at)):
        return None
    return _aware(row.blocked_at)


def theme_of(row: Account) -> str:
    """Light, dark or system as the account chose it (``profile.mode``, kept at the account since 1.0.0), "" while it
    never chose."""
    profile = row.profile if isinstance(row.profile, dict) else {}
    mode = profile.get("mode")
    return mode if isinstance(mode, str) and mode in nexkonten.profiles.THEMES else ""


#: Whether the provider's picture is fetched in a thread of its own. Tests switch this off and do not wait.
PICTURE_IN_THREAD = True


class KontenStore:
    """``nexkonten.Store`` and the stores of part 2 over nexpaper's tables, inside one session."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Accounts ------------------------------------------------------------------------------------------------
    def _row(self, account_id: AccountId | None) -> Account | None:
        if account_id is None:
            return None
        try:
            return self.db.get(Account, int(account_id))
        except (TypeError, ValueError):
            return None

    def _account(self, row: Account) -> KontoAccount:
        if row.avatar_at is None:
            picture = nexkonten.PICTURE_NONE
        else:
            picture = nexkonten.PICTURE_PROVIDER if row.avatar_source == PROVIDER else nexkonten.PICTURE_OWN
        offered = self.offered(row)
        return KontoAccount(
            id=row.id,
            username=row.name,
            display_name=row.display_name or "",
            email=(row.email or "").strip(),
            email_confirmed=counts(row) if (row.email or "").strip() else True,
            email_proven=proven(row),
            email_source=(nexkonten.EMAIL_PROVIDER if row.email and row.email_from_provider
                          else nexkonten.EMAIL_OWN),
            pending_email=pending_of(self.db, row.id),
            has_password=row.sign_in == SIGN_IN_PASSWORD and bool(row.password_hash),
            blocked=row.blocked_at is not None,
            operator=row.role == OPERATOR,
            picture=picture,
            language=row.language or "",
            offered_email=offered,
            offered_email_provider=(row.offered_email_provider or "") if offered else "",
            declined_email=row.declined_email or "",
            password_changed_at=_aware(row.password_changed_at) if row.password_changed_at else None,
            blocked_at=blocked_since(row),
            deleted_at=_aware(row.deleted_at) if row.deleted_at else None,
            theme=theme_of(row),
            storage_limit=row.storage_limit,
            rights=frozenset({nexkonten.config.FEATURE_AI} if row.ai_allowed else ()),
        )

    @staticmethod
    def offered(row: Account) -> str:
        """The provider's address on offer: not the own one, not one the account declined."""
        offer = row.offered_email or ""
        if not offer or same(row.email, offer) or same(row.declined_email, offer):
            return ""
        return offer

    def set_offered_email(self, account_id: AccountId, address: str, provider: str = "") -> None:
        row = self._row(account_id)
        if row is None:
            return
        row.offered_email = address
        row.offered_email_provider = provider[:80] if address else ""
        self.db.flush()

    def set_declined_email(self, account_id: AccountId, address: str) -> None:
        row = self._row(account_id)
        if row is not None:
            row.declined_email = address
            self.db.flush()

    def count_accounts(self) -> int:
        return int(self.db.scalar(select(func.count()).select_from(Account)) or 0)

    def get_account(self, account_id: AccountId) -> KontoAccount | None:
        row = self._row(account_id)
        return self._account(row) if row is not None else None

    def find_by_username(self, username: str) -> list[KontoAccount]:
        wanted = (username or "").strip().lower()
        if not wanted:
            return []
        rows = self.db.scalars(select(Account).where(func.lower(Account.name) == wanted))
        return [self._account(row) for row in rows]

    def find_by_email(self, address: str) -> list[KontoAccount]:
        wanted = (address or "").strip().lower()
        if not wanted:
            return []
        rows = self.db.scalars(select(Account).where(func.lower(func.trim(Account.email)) == wanted))
        return [self._account(row) for row in rows]

    def name_reserved(self, username: str, except_id: AccountId | None) -> bool:
        query = select(FormerName.id).where(func.lower(FormerName.name) == (username or "").strip().lower())
        if except_id is not None:
            query = query.where(or_(FormerName.account_id.is_(None), FormerName.account_id != int(except_id)))
        return self.db.scalar(query.limit(1)) is not None

    def find_by_former_name(self, username: str) -> list[KontoAccount]:
        ids = set(
            self.db.scalars(
                select(FormerName.account_id).where(
                    func.lower(FormerName.name) == (username or "").strip().lower(), FormerName.account_id.is_not(None)
                )
            )
        )
        return [account for account in (self.get_account(i) for i in ids) if account is not None]

    def display_name_taken(self, display_name: str, except_id: AccountId | None) -> bool:
        wanted = names.display_key(display_name)
        if not wanted:
            return False
        rows = self.db.execute(select(Account.id, Account.display_name).where(Account.display_name != ""))
        other = int(except_id) if except_id is not None else None
        return any(row.id != other and names.display_key(row.display_name) == wanted for row in rows)

    def _flush(self) -> None:
        """Writes what waits; a unique index that refuses becomes ``Taken``."""
        try:
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            raise Taken("email" if "email" in str(exc.orig) else "username") from exc

    def add_account(self, new: NewAccount) -> AccountId:
        """A new account; its own vault comes in the same write (``models._make_personal_vault``)."""
        if new.display_name and self.display_name_taken(new.display_name, None):
            raise Taken("display_name")
        if self.find_by_username(new.username):
            raise Taken("username")
        from . import settings_service

        address = (new.email or "").strip()
        now = utcnow()
        row = Account(
            name=new.username,
            display_name=new.display_name,
            email=address,
            email_counts=bool(new.email_confirmed) if address else True,
            email_confirmed_at=now if address and new.email_proven else None,
            email_from_provider=False,
            role=OPERATOR if new.operator else MEMBER,
            sign_in=SIGN_IN_PASSWORD if new.password else SIGN_IN_OIDC,
            password_hash=hash_password(new.password) if new.password else "",
            password_changed_at=now if new.password else None,
            language=new.language or "",
            whats_new_seen=nexwasneu.seen_for_new_account(),
            # The limit new accounts start with (Bauplan E44, Server › General › Limits).
            storage_limit=settings_service.new_account_storage_limit(self.db),
            # Light, dark or system where nexpaper keeps it (``profile.mode``): a new account starts with ``system``
            # (Bauplan E45); only accounts of before have none and take a value once (``profiles.adopt_theme``).
            profile={"mode": new.theme},
        )
        self.db.add(row)
        self._flush()
        logger.info("Account created name=%s role=%s sign_in=%s", row.name, row.role, row.sign_in)
        return row.id

    def set_username(self, account_id: AccountId, username: str) -> None:
        """The new name; the old one becomes a former name of the account, reserved for good. The intake folder and
        the plus address of the old name keep reaching the account (``by_any_name``); the folder on the disk of its
        vault never moves (``Vault.folder``)."""
        row = self._row(account_id)
        if row is None:
            return
        old = row.name
        if any(other.id != row.id for other in self.find_by_username(username)):
            raise Taken("username")
        row.name = username
        self._flush()
        if old.lower() != username.lower():
            self.db.add(FormerName(account_id=row.id, name=old))
            self.db.flush()

    def set_display_name(self, account_id: AccountId, display_name: str) -> None:
        if display_name and self.display_name_taken(display_name, account_id):
            raise Taken("display_name")
        row = self._row(account_id)
        if row is not None:
            row.display_name = display_name
            self.db.flush()

    def set_email(self, account_id: AccountId, address: str, *, confirmed: bool, proven: bool, source: str) -> None:
        """``email_counts`` says whether it counts, ``email_confirmed_at`` whether it is proven (a proof of the same
        address keeps its time); the source is the provider's or the person's own."""
        row = self._row(account_id)
        if row is None:
            return
        keep = row.email_confirmed_at if same(row.email, address) and proven else None
        row.email = address
        row.email_counts = bool(confirmed) if address else True
        row.email_confirmed_at = (keep or utcnow()) if address and proven else None
        row.email_from_provider = bool(address) and source == nexkonten.EMAIL_PROVIDER
        if address and same(row.offered_email, address):
            row.offered_email = ""
            row.offered_email_provider = ""
        self._flush()

    def set_language(self, account_id: AccountId, language: str) -> None:
        row = self._row(account_id)
        if row is not None:
            row.language = language
            self.db.flush()

    # --- Passwords, failures, sessions ---------------------------------------------------------------------------
    def check_password(self, account_id: AccountId | None, password: str) -> bool:
        row = self._row(account_id)
        if row is None or row.sign_in != SIGN_IN_PASSWORD or not row.password_hash:
            verify_password(password or "", _dummy_hash())
            return False
        return verify_password(password or "", row.password_hash)

    def set_password(self, account_id: AccountId, password: str) -> None:
        row = self._row(account_id)
        if row is None:
            return
        row.password_hash = hash_password(password)
        row.sign_in = SIGN_IN_PASSWORD
        row.failed_logins = 0
        row.locked_until = None
        row.password_changed_at = utcnow()
        self.db.flush()

    def is_locked(self, account_id: AccountId) -> bool:
        row = self._row(account_id)
        return bool(row and row.locked_until is not None and _aware(row.locked_until) > clock.now())

    def note_failure(self, account_id: AccountId | None) -> None:
        """A wrong password at the account; after ``MAX_FAILURES`` locked for ``LOCK_MINUTES``. Without an account the
        same work on the counter row: as costly, the time tells nothing."""
        row = self._row(account_id)
        if row is None:
            counted = self.db.execute(update(FailedUnknown).where(FailedUnknown.id == 1)
                                      .values(count=FailedUnknown.count + 1))
            if not counted.rowcount:  # type: ignore[attr-defined]
                self.db.add(FailedUnknown(id=1, count=1))
            self.db.flush()
            return
        row.failed_logins = (row.failed_logins or 0) + 1
        if row.failed_logins >= MAX_FAILURES:
            row.locked_until = clock.now() + timedelta(minutes=LOCK_MINUTES)
            row.failed_logins = 0
            logger.warning("Account locked after %s failures name=%s minutes=%s", MAX_FAILURES, row.name, LOCK_MINUTES)
        else:
            logger.warning("Check failed name=%s (%s of %s before lockout)", row.name, row.failed_logins, MAX_FAILURES)
        self.db.flush()

    def note_success(self, account_id: AccountId) -> None:
        row = self._row(account_id)
        if row is not None:
            row.failed_logins = 0
            row.locked_until = None
            self.db.flush()

    def end_sessions(self, account_id: AccountId) -> None:
        """A new password from a link: every browser session (of every stage) and every sign-in waiting for its code
        ends, and no browser counts as known any more. Paired devices, API keys and passkeys stay (they are listed)."""
        from ..vendor.nexkonten import factor
        from . import totp

        self.db.execute(delete(AuthSession).where(AuthSession.account_id == int(account_id)))
        totp.forget_account(int(account_id))
        factor.drop_waiting(int(account_id))
        self.renew_device_key(account_id)

    def list_access(self, account_id: AccountId) -> list[Access]:
        devices = self.db.scalars(
            select(Device).where(Device.account_id == int(account_id), Device.revoked_at.is_(None))
            .order_by(Device.created_at)
        )
        found = [Access(f"{DEVICE_UID}{row.uid}", "device", device_label(row), row.last_used_at) for row in devices]
        keys = self.db.scalars(
            select(ApiKey).where(ApiKey.account_id == int(account_id), ApiKey.blocked_at.is_(None))
            .order_by(ApiKey.created_at)
        )
        found += [Access(f"key-{row.id}", "api_key", row.name or row.prefix, row.last_used_at) for row in keys]
        found += [Access(key.uid, "passkey", key.name, key.last_used_at) for key in self.passkeys_of(account_id)]
        return found

    def revoke_access(self, account_id: AccountId) -> int:
        """"Disconnect all": every paired device is revoked (it stays in the list of devices as revoked, as nexpaper
        always did), every API key and passkey goes, a pairing code nobody used yet too."""
        gone = int(self.db.execute(
            update(Device).where(Device.account_id == int(account_id), Device.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        ).rowcount or 0)  # type: ignore[attr-defined]
        gone += int(self.db.execute(delete(ApiKey).where(ApiKey.account_id == int(account_id))).rowcount or 0)  # type: ignore[attr-defined]
        gone += self.remove_passkeys(account_id)
        self.db.execute(delete(Pairing).where(Pairing.account_id == int(account_id)))
        return gone

    def second_factor(self, account_id: AccountId) -> str:
        row = self._row(account_id)
        if row is None or nexkonten.factor.switched_off():
            return nexkonten.SECOND_FACTOR_NONE
        if row.totp_secret_enc:
            # Also a seed that does not open any more: the second factor fails closed.
            return nexkonten.SECOND_FACTOR_ACTIVE
        return nexkonten.factor.state(self, account_id)

    def provider_checks_factor(self, account_id: AccountId) -> bool:
        """The module's hook (konten 0.3.10): an account through a provider only brings the provider's second factor,
        "Require a second factor" asks it none of its own here (as in 1.12.0, ``totp.provider_only``). A session through
        a provider whose entry checks it is the sign-in's (``provider_checked``, ``totp.provider_checks``)."""
        from . import totp

        row = self._row(account_id)
        return row is not None and totp.provider_only(row)

    # --- Pictures ------------------------------------------------------------------------------------------------
    def set_provider_picture(self, account_id: AccountId, picture: Picture) -> bool:
        """Through nexpaper's own picture handling like an upload, and only while the account has none (one statement
        with that condition)."""
        from . import avatars

        try:
            webp = avatars.make(picture.data)
        except (avatars.AvatarError, ValueError):
            return False
        result = self.db.execute(
            update(Account)
            .where(Account.id == int(account_id), Account.avatar_at.is_(None))
            .values(avatar=webp, avatar_at=utcnow(), avatar_source=PROVIDER)
        )
        self._refresh(account_id)
        return int(result.rowcount or 0) == 1  # type: ignore[attr-defined]

    def _refresh(self, account_id: AccountId) -> None:
        row = self.db.get(Account, int(account_id))
        if row is not None:
            self.db.expire(row)

    # --- Invitations ---------------------------------------------------------------------------------------------
    def find_invite(self, key: str) -> Invite | None:
        """The invitation of a link, also when it ran out (``expires_at`` says so); None when unknown or used."""
        if not key:
            return None
        row = self.db.scalar(select(InviteRow).where(InviteRow.token_hash == hash_token(key)))
        if row is None:
            return None
        return Invite(
            key=key,
            id=row.id,
            email=(row.email or "").strip(),
            display_name=row.display_name or "",
            username="",
            expires_at=_aware(row.expires_at),
            rights=row,
        )

    def consume_invite(self, invite: Invite) -> bool:
        return int(self.db.execute(delete(InviteRow).where(InviteRow.id == int(invite.id))).rowcount or 0) == 1  # type: ignore[attr-defined]

    def accept_invite(self, account_id: AccountId, invite: Invite) -> None:
        """nexpaper's invitations bring nothing beyond the account (no spaces): an account that has one already gets
        nothing more from following it."""
        del account_id, invite

    # --- Address changes (``email_confirmations`` of 1.12.0) ------------------------------------------------------
    def start_email_change(self, account_id: AccountId, address: str, token: str, expires_at: datetime) -> None:
        self.db.execute(delete(EmailConfirmation).where(EmailConfirmation.account_id == int(account_id)))
        self.db.add(EmailConfirmation(account_id=int(account_id), address=address, token_hash=hash_token(token),
                                      expires_at=expires_at))
        self.db.flush()

    def find_email_change(self, token: str) -> EmailChange | None:
        if not token:
            return None
        row = self.db.scalar(select(EmailConfirmation).where(EmailConfirmation.token_hash == hash_token(token)))
        if row is None:
            return None
        return EmailChange(id=row.id, account_id=row.account_id, address=row.address,
                           expires_at=_aware(row.expires_at))

    def consume_email_change(self, change: EmailChange) -> bool:
        gone = self.db.execute(delete(EmailConfirmation).where(EmailConfirmation.id == int(change.id)))
        return int(gone.rowcount or 0) == 1  # type: ignore[attr-defined]

    def drop_email_change(self, account_id: AccountId) -> None:
        self.db.execute(delete(EmailConfirmation).where(EmailConfirmation.account_id == int(account_id)))
        self.db.flush()

    # --- Links for a new password --------------------------------------------------------------------------------
    def start_reset(
        self, account_id: AccountId, token: str, expires_at: datetime, *, created_by: AccountId | None, origin: str
    ) -> None:
        # One open link per account: an earlier one stops counting (as in 1.12.0).
        self.db.execute(delete(PasswordReset).where(PasswordReset.account_id == int(account_id)))
        self.db.add(
            PasswordReset(
                token_hash=hash_token(token),
                account_id=int(account_id),
                created_by=int(created_by) if created_by is not None else None,
                expires_at=expires_at,
                origin=origin,
            )
        )
        self.db.flush()

    def find_reset(self, token: str) -> Reset | None:
        if not token:
            return None
        row = self.db.scalar(select(PasswordReset).where(PasswordReset.token_hash == hash_token(token)))
        if row is None:
            return None
        return Reset(id=row.id, account_id=row.account_id, expires_at=_aware(row.expires_at),
                     created_by=row.created_by, origin=row.origin or nexkonten.RESET_SELF)

    def consume_reset(self, reset: Reset) -> bool:
        return int(self.db.execute(delete(PasswordReset).where(PasswordReset.id == int(reset.id))).rowcount or 0) == 1  # type: ignore[attr-defined]

    def drop_resets(self, account_id: AccountId, *, origin: str | None = None) -> None:
        conditions = [PasswordReset.account_id == int(account_id)]
        if origin is not None:
            conditions.append(PasswordReset.origin == origin)
        self.db.execute(delete(PasswordReset).where(*conditions))

    def claim_setup(self) -> bool:
        try:
            self.db.add(SetupClaim(id=1))
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            return False
        return True

    # --- After the commit ----------------------------------------------------------------------------------------
    def notify(self, event: Event) -> None:
        """What follows a settled outcome. A new username: its intake folder is made at once (the old one is still
        read). A password set through a link leaves the list "These devices still have access" for the next sign-in."""
        if event.kind == nexkonten.EVENT_PASSWORD_SET:
            origin = str(event.details.get("origin") or nexkonten.RESET_SELF)
            row = self._row(event.account_id)
            if row is not None:
                row.new_password_origin = origin
                self.db.commit()
        elif event.kind == nexkonten.EVENT_RENAMED:
            logger.info("Username changed old=%s new=%s", event.details.get("old", ""), event.details.get("new", ""))
            from . import intake_folder

            intake_folder.renamed(str(event.details.get("new") or ""))

    # === Part 2: second factor, passkeys, sessions, pictures ========================================================

    # --- Second factor -------------------------------------------------------------------------------------------
    def totp_seed(self, account_id: AccountId) -> str | None:
        """The seed of the account's authenticator, opened; sealed as in 1.12.0 (``totp.seal_seed``), so that every
        authenticator app set up before keeps working."""
        from . import totp

        row = self._row(account_id)
        if row is None or not row.totp_secret_enc:
            return None
        try:
            return totp.open_seed(row.totp_secret_enc)
        except totp.SeedUnreadable:
            logger.error("Second factor seed unreadable name=%s (secret.key changed?)", row.name)
            return None

    def set_totp(self, account_id: AccountId, seed: str | None) -> None:
        from . import totp

        row = self._row(account_id)
        if row is None:
            return
        if seed:
            row.totp_secret_enc = totp.seal_seed(seed)
        else:
            row.totp_secret_enc = ""
            row.totp_last_step = 0
        self.db.flush()

    def pending_totp(self, account_id: AccountId) -> tuple[str, datetime] | None:
        row = self._row(account_id)
        if row is None or not row.totp_pending or row.totp_pending_until is None:
            return None
        seed = decrypt_secret(row.totp_pending, PENDING_TOTP_CONTEXT)
        return (seed, _aware(row.totp_pending_until)) if seed else None

    def set_pending_totp(self, account_id: AccountId, seed: str | None, until: datetime | None) -> None:
        row = self._row(account_id)
        if row is None:
            return
        row.totp_pending = encrypt_secret(seed, PENDING_TOTP_CONTEXT) if seed and until else ""
        row.totp_pending_until = until if seed and until else None
        self.db.flush()

    def claim_step(self, account_id: AccountId, step: int) -> bool:
        result = self.db.execute(
            update(Account).where(Account.id == int(account_id), Account.totp_last_step < step)
            .values(totp_last_step=step)
        )
        self._refresh(account_id)
        return int(result.rowcount or 0) == 1  # type: ignore[attr-defined]

    def recovery_hashes(self, account_id: AccountId) -> list[str]:
        from . import totp

        row = self._row(account_id)
        return totp.load_recovery(row.totp_recovery) if row is not None else []

    def set_recovery(self, account_id: AccountId, hashes: list[str]) -> None:
        row = self._row(account_id)
        if row is not None:
            row.totp_recovery = json.dumps(list(hashes)) if hashes else ""
            self.db.flush()

    def claim_recovery(self, account_id: AccountId, stored: str) -> bool:
        """The code goes with one statement that only succeeds against the list it was read from: two requests with
        the same code at once, one of them wins."""
        row = self._row(account_id)
        if row is None:
            return False
        before = row.totp_recovery or ""
        hashes = self.recovery_hashes(account_id)
        if stored not in hashes:
            return False
        remaining = [entry for entry in hashes if entry != stored]
        result = self.db.execute(
            update(Account).where(Account.id == int(account_id), Account.totp_recovery == before)
            .values(totp_recovery=json.dumps(remaining))
        )
        self._refresh(account_id)
        return int(result.rowcount or 0) == 1  # type: ignore[attr-defined]

    def recovery_key(self) -> bytes:
        """The key ``totp.hash_recovery`` made the ``h1:`` codes of 1.12.0 with: they keep working unchanged."""
        return hashlib.sha256(b"nexpaper-recovery-codes:" + server_key()).digest()

    def factor_required(self) -> bool:
        from . import settings_service

        return bool(settings_service.get(self.db, SWITCH_FACTOR_REQUIRED))

    # --- Passkeys ------------------------------------------------------------------------------------------------
    def passkeys_allowed(self) -> bool:
        from . import settings_service

        return bool(settings_service.get(self.db, SWITCH_PASSKEYS))

    @staticmethod
    def _passkey(row: PasskeyRow) -> PasskeyData:
        return PasskeyData(
            uid=row.uid,
            account_id=row.user_id,
            credential_id=bytes(row.credential_id),
            public_key=bytes(row.public_key),
            sign_count=row.sign_count,
            name=row.name,
            created_at=_aware(row.created_at),
            last_used_at=_aware(row.last_used_at) if row.last_used_at else None,
        )

    def passkeys_of(self, account_id: AccountId) -> list[PasskeyData]:
        rows = self.db.scalars(
            select(PasskeyRow).where(PasskeyRow.user_id == int(account_id)).order_by(PasskeyRow.created_at)
        )
        return [self._passkey(row) for row in rows]

    def find_passkey(self, credential_id: bytes) -> PasskeyData | None:
        row = self.db.scalar(select(PasskeyRow).where(PasskeyRow.credential_id == credential_id))
        return self._passkey(row) if row is not None else None

    def add_passkey(self, passkey: PasskeyData) -> None:
        self.db.add(
            PasskeyRow(
                uid=str(passkey.uid)[:32],
                user_id=int(passkey.account_id),
                credential_id=passkey.credential_id,
                public_key=passkey.public_key,
                sign_count=passkey.sign_count,
                name=(passkey.name or "Passkey")[:64],
                created_at=passkey.created_at,
            )
        )
        self.db.flush()

    def claim_counter(self, uid: str, old: int, new: int) -> bool:
        result = self.db.execute(
            update(PasskeyRow).where(PasskeyRow.uid == uid, PasskeyRow.sign_count == old)
            .values(sign_count=new, last_used_at=utcnow())
        )
        return int(result.rowcount or 0) == 1  # type: ignore[attr-defined]

    def remove_passkey(self, account_id: AccountId, uid: str) -> bool:
        result = self.db.execute(
            delete(PasskeyRow).where(PasskeyRow.user_id == int(account_id), PasskeyRow.uid == uid)
        )
        return int(result.rowcount or 0) == 1  # type: ignore[attr-defined]

    def remove_passkeys(self, account_id: AccountId) -> int:
        return int(self.db.execute(delete(PasskeyRow).where(PasskeyRow.user_id == int(account_id))).rowcount or 0)  # type: ignore[attr-defined]

    def user_handle(self, account_id: AccountId) -> bytes:
        """The handle of 1.12.0: hex in the column, its bytes in every passkey made then."""
        row = self._row(account_id)
        if row is None:
            raise LookupError(account_id)
        if not row.passkey_handle:
            row.passkey_handle = secrets.token_hex(32)
            self.db.flush()
        return bytes.fromhex(row.passkey_handle)

    # --- Sessions ------------------------------------------------------------------------------------------------
    @staticmethod
    def _session(row: AuthSession) -> SessionData:
        return SessionData(
            uid=row.uid or f"s{row.id}",
            account_id=row.account_id,
            kind=KIND_WAITING if row.stage == STAGE_WAITING else KIND_BROWSER,
            created_at=_aware(row.created_at),
            expires_at=_aware(row.expires_at),
            last_seen_at=_aware(row.last_seen_at) if row.last_seen_at else None,
            remember=bool(row.remember),
            stage=STAGE_FULL if row.stage == STAGE_WAITING else (row.stage or STAGE_FULL),
            provider_checked=bool(row.second_factor_by_provider),
            label=row.user_agent or "",
            address=row.ip or "",
        )

    @staticmethod
    def _device(row: Device) -> SessionData:
        created = _aware(row.created_at)
        return SessionData(
            uid=row.uid,
            account_id=row.account_id,
            kind=KIND_DEVICE,
            created_at=created,
            expires_at=created + timedelta(days=36500),
            last_seen_at=_aware(row.last_used_at) if row.last_used_at else None,
            label=device_label(row),
        )

    def add_session(self, session: SessionData, token_hash: str) -> None:
        """A browser session (``auth_sessions``), a sign-in waiting for its second step (an ``auth_sessions`` row of
        the stage ``waiting``, which no route takes for a session), or a paired device (``devices``, as nexpaper's own
        pairing makes them: the same SHA-256 of the token)."""
        if session.kind == KIND_DEVICE:
            self.db.add(
                Device(
                    uid=str(session.uid)[:32],
                    account_id=int(session.account_id),
                    name=(session.label or "Device")[:80],
                    token_hash=token_hash,
                    prefix="npd_",
                    created_at=session.created_at,
                    last_used_at=session.last_seen_at,
                )
            )
            self.db.flush()
            return
        self.db.add(
            AuthSession(
                token_hash=token_hash,
                uid=str(session.uid)[:32],
                account_id=int(session.account_id),
                created_at=session.created_at,
                expires_at=session.expires_at,
                last_seen_at=session.last_seen_at or session.created_at,
                ip=session.address[:64],
                user_agent=session.label[:255],
                second_factor_by_provider=session.provider_checked,
                remember=session.remember,
                stage=STAGE_WAITING if session.kind == KIND_WAITING else session.stage,
            )
        )
        self.db.flush()

    def session_by_hash(self, token_hash: str) -> SessionData | None:
        row = self.db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
        if row is not None:
            return self._session(row)
        device = self.db.scalar(select(Device).where(Device.token_hash == token_hash, Device.revoked_at.is_(None)))
        return self._device(device) if device is not None else None

    def _by_uid(self, uid: str) -> AuthSession | None:
        if uid.startswith("s") and uid[1:].isdigit():
            return self.db.get(AuthSession, int(uid[1:]))
        return self.db.scalar(select(AuthSession).where(AuthSession.uid == uid))

    def touch_session(self, uid: str, last_seen_at: datetime, expires_at: datetime) -> None:
        row = self._by_uid(uid)
        if row is not None:
            row.last_seen_at = last_seen_at
            row.expires_at = expires_at
            self.db.flush()
            return
        device = self.db.scalar(select(Device).where(Device.uid == uid))
        if device is not None:
            device.last_used_at = last_seen_at
            self.db.flush()

    def set_stage(self, uid: str, stage: str) -> None:
        row = self._by_uid(uid)
        if row is not None:
            row.stage = stage
            self.db.flush()

    def sessions_of(self, account_id: AccountId) -> list[SessionData]:
        now = utcnow()
        rows = self.db.scalars(
            select(AuthSession).where(AuthSession.account_id == int(account_id), AuthSession.expires_at > now,
                                      AuthSession.stage != STAGE_WAITING)
        )
        devices = self.db.scalars(
            select(Device).where(Device.account_id == int(account_id), Device.revoked_at.is_(None))
        )
        return [self._session(row) for row in rows] + [self._device(row) for row in devices]

    def end_session(self, account_id: AccountId, uid: str) -> bool:
        """A browser session, or a paired device (revoked: it stays in the list of devices as nexpaper keeps them)."""
        row = self._by_uid(uid)
        if row is not None:
            if row.account_id != int(account_id):
                return False
            self.db.delete(row)
            self.db.flush()
            return True
        result = self.db.execute(
            update(Device).where(Device.uid == uid, Device.account_id == int(account_id), Device.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        return int(result.rowcount or 0) == 1  # type: ignore[attr-defined]

    def end_everywhere(self, account_id: AccountId, keep_uid: str | None) -> int:
        """Browsers, waiting sign-ins and paired devices (as "sign out everywhere" of 1.12.0); API keys and passkeys
        stay."""
        from ..vendor.nexkonten import factor
        from . import totp

        keep = self._by_uid(keep_uid) if keep_uid else None
        statement = delete(AuthSession).where(AuthSession.account_id == int(account_id))
        if keep is not None:
            statement = statement.where(AuthSession.id != keep.id)
        gone = int(self.db.execute(statement).rowcount or 0)  # type: ignore[attr-defined]
        gone += int(self.db.execute(
            update(Device).where(Device.account_id == int(account_id), Device.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        ).rowcount or 0)  # type: ignore[attr-defined]
        totp.forget_account(int(account_id))
        factor.drop_waiting(int(account_id))
        return gone

    def device_key(self, account_id: AccountId) -> str:
        row = self._row(account_id)
        if row is None:
            raise LookupError(account_id)
        if not row.device_key:
            row.device_key = secrets.token_hex(32)
            self.db.flush()
        return row.device_key

    def renew_device_key(self, account_id: AccountId) -> None:
        row = self._row(account_id)
        if row is not None:
            row.device_key = secrets.token_hex(32)
            self.db.flush()

    # --- Pictures (part 2) ---------------------------------------------------------------------------------------
    def picture_of(self, account_id: AccountId) -> tuple[bytes, datetime] | None:
        row = self._row(account_id)
        if row is None or row.avatar_at is None or not row.avatar:
            return None
        return bytes(row.avatar), _aware(row.avatar_at)

    def set_picture(self, account_id: AccountId, data: bytes, at: datetime, source: str) -> None:
        row = self._row(account_id)
        if row is not None:
            row.avatar = data
            row.avatar_at = at
            row.avatar_source = PROVIDER if source == PROVIDER else ""
            self.db.flush()

    def remove_picture(self, account_id: AccountId) -> None:
        row = self._row(account_id)
        if row is not None:
            row.avatar = None
            row.avatar_at = None
            row.avatar_source = ""
            self.db.flush()

    # === konten 1.1.0: the operator's functions, the theme, the sign-in switches ====================================

    # --- ManageStore ---------------------------------------------------------------------------------------------
    def active_operators(self) -> int:
        return int(self.db.scalar(
            select(func.count()).select_from(Account)
            .where(Account.role == OPERATOR, Account.blocked_at.is_(None), Account.deleted_at.is_(None))
        ) or 0)

    def set_operator(self, account_id: AccountId, operator: bool) -> None:
        row = self._row(account_id)
        if row is not None:
            row.role = OPERATOR if operator else MEMBER
            self.db.flush()

    def set_blocked(self, account_id: AccountId, at: datetime | None) -> None:
        row = self._row(account_id)
        if row is None:
            return
        row.blocked_at = at
        if at is None:
            row.failed_logins = 0
            row.locked_until = None
        self.db.flush()

    def set_deleted(self, account_id: AccountId, at: datetime | None) -> None:
        """Deleted at ``at``: blocked at the same moment unless it was blocked before (so every wall that asks
        ``blocked_at`` keeps it out, and 1.12.0 sees it blocked). Brought back: that mark goes with the deletion, a
        block of before stays; the documents' handover chosen at the deletion is forgotten. (The links for a new
        password end with the deletion through the module, ``manage.remove``.)"""
        row = self._row(account_id)
        if row is None:
            return
        if at is not None:
            row.deleted_at = at
            if row.blocked_at is None:
                row.blocked_at = at
        else:
            if row.deleted_at is not None and row.blocked_at is not None \
                    and _aware(row.blocked_at) == _aware(row.deleted_at):
                row.blocked_at = None
            row.deleted_at = None
            row.leaving = None
        self.db.flush()

    def shut_out(self, account_id: AccountId) -> None:
        """What blocking ends: every browser session and sign-in that waits, a pairing code not used yet, the upload
        requests of the account, and the key of known browsers. Paired devices rest (konten 1.1.5, geraete G26): they
        stay, are refused while the account is out (``geraete_store.is_out``) and work again once it is back; deleting
        for good takes them (``purge_account``). API keys stay and are refused while the account is blocked or deleted
        (``schluessel_store.out``), as its providers and its links are (``blocked_at``)."""
        from . import upload_requests

        uid = int(account_id)
        self.end_sessions(uid)
        self.db.execute(delete(Pairing).where(Pairing.account_id == uid))
        upload_requests.end_for(self.db, uid)
        self.db.flush()

    def on_shut_out(self, account: KontoAccount) -> None:
        """konten 1.1.0 (Bauplan E38), after the commit of a block or of a deletion of an account that was not blocked.
        In nexpaper an account is out exactly while ``blocked_at`` is set (a deletion sets it too, ``set_deleted``), and
        everything that runs for an account in the background reads that row each time, so nothing more is needed here:
        no push goes out (``push.reaches``; the devices stay signed up), the intake folder leaves the person's folder
        alone (its files wait there), the mailbox of the intake files nothing for the person (a mail for it goes to the
        operator, marked unknown, as before), and reminders, the weekly mail, exports, notices
        and the AI's proposals wait (``reminders``, ``exports``, ``tell``, ``ai_proposals``). At the end of the 30 days
        the devices go with the account (``purge_account``)."""
        logger.info("Account out, its pushes and its intake wait account=%s", account.id)

    def on_back(self, account: KontoAccount) -> None:
        """konten 1.1.0 (Bauplan E38), after unblocking or bringing back an account that was not blocked before: the
        same row says it is in again, so its pushes, its intake folder and the rest run again at their next turn."""
        logger.info("Account back, its pushes and its intake run again account=%s", account.id)

    def deleted_before(self, moment: datetime) -> list[AccountId]:
        return list(self.db.scalars(
            select(Account.id).where(Account.deleted_at.is_not(None), Account.deleted_at <= moment).order_by(Account.id)
        ))

    def purge_account(self, account_id: AccountId) -> None:
        """What deleting an account did in nexpaper before the module, now at the end of its 30 days: the documents of
        its own vault go where the operator chose at the deletion (``leaving``; ``vaults.before_account_delete``, its
        links end, its shares go, so does its vault), the name stays reserved for good, and the database takes what
        hangs on the account with it (sessions, passkeys, keys, devices, links to providers)."""
        from . import oidc_store, totp, vaults

        row = self._row(account_id)
        if row is None:
            return
        chosen = row.leaving if isinstance(row.leaving, dict) else {}
        vaults.before_account_delete(
            self.db, row.id, choice=chosen.get("documents"), target_user=chosen.get("target_user_id"),
            target_vault=chosen.get("target_vault_id"), by=chosen.get("by"), account_name=row.name,
        )
        self.db.add(FormerName(account_id=None, name=row.name))
        self.db.delete(row)
        oidc_store.way_back_changed(self.db)
        self.db.flush()
        totp.forget_account(int(account_id))

    def set_storage_limit(self, account_id: AccountId, limit: int | None) -> None:
        row = self._row(account_id)
        if row is not None:
            row.storage_limit = limit
            self.db.flush()

    def set_right(self, account_id: AccountId, right: str, allowed: bool) -> None:
        row = self._row(account_id)
        if row is not None and right == nexkonten.config.FEATURE_AI:
            row.ai_allowed = bool(allowed)
            self.db.flush()

    # --- ThemeStore ----------------------------------------------------------------------------------------------
    def set_theme(self, account_id: AccountId, theme: str) -> None:
        """In ``profile.mode``, where nexpaper kept light and dark at the account since 1.0.0 (1.12.0 reads it too)."""
        row = self._row(account_id)
        if row is not None:
            profile = dict(row.profile) if isinstance(row.profile, dict) else {}
            profile["mode"] = theme
            row.profile = profile
            self.db.flush()

    # --- SignInStore ---------------------------------------------------------------------------------------------
    def sign_in_settings(self) -> SignInSettings:
        from . import settings_service

        return SignInSettings(
            password_login=bool(settings_service.get(self.db, "password_login")),
            factor_required=bool(settings_service.get(self.db, SWITCH_FACTOR_REQUIRED)),
            passkeys_allowed=bool(settings_service.get(self.db, SWITCH_PASSKEYS)),
        )

    def save_sign_in_settings(self, settings: SignInSettings) -> None:
        from . import settings_service

        settings_service.save(self.db, {
            "password_login": settings.password_login,
            SWITCH_FACTOR_REQUIRED: settings.factor_required,
            SWITCH_PASSKEYS: settings.passkeys_allowed,
        }, commit=False)

    def active_providers(self) -> int:
        return int(self.db.scalar(
            select(func.count()).select_from(OidcProvider).where(OidcProvider.enabled.is_(True))
        ) or 0)

    # --- Transaction ---------------------------------------------------------------------------------------------
    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()


@contextmanager
def own_store() -> Iterator[KontenStore]:
    """A store with a session of its own, for work after the answer (a forgotten password, a provider's picture)."""
    from ..db import SessionLocal

    with SessionLocal() as db:
        yield KontenStore(db)


def provider_picture(account_id: int, address: str, issuer: str) -> None:
    """The provider's picture for an account without one, in a thread of its own (a fetch takes up to five seconds).
    Whatever fails, the account stays without a picture; the sign-in went through long before."""

    def work() -> None:
        with own_store() as store:
            nexkonten.pictures.take_provider_picture(store, account_id, address, issuer)

    if PICTURE_IN_THREAD:
        threading.Thread(target=work, name="nexpaper-provider-picture", daemon=True).start()
    else:
        work()
