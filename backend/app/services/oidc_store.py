"""nexpaper's side of the shared sign-in module ``vendor/nexoidc``: the ``Store`` over its tables, the start-up
configuration, the migration from the single provider of 1.0.1 to the list, and the way back to 1.0.1.

The shared module runs the protocol, decides who an identity is and
keeps the provider list; it never sees a database. What is nexpaper's own lives here: accounts and their names, what an
invitation brings, the address an account takes from its provider (never confirmed by that alone: the mail intake
counts only an address the person confirmed), and the encryption of the client secrets with the server secret.

A ``SqlStore`` works inside one SQLAlchemy session, one request. The module commits when an outcome is settled and
rolls back when it refuses after a write (a consumed invitation comes back that way). Every commit that changed an
entry, a link or an account writes the way back in the same transaction (``before_commit``).
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import delete, event, func, select, update
from sqlalchemy.orm import Session

from .. import __version__
from ..config import get_settings
from ..db import SessionLocal
from ..models import MEMBER, SIGN_IN_OIDC, SIGN_IN_PASSWORD, Account, OidcLink, OidcProvider, utcnow
from ..models import Invite as InviteRow
from ..security import decrypt_secret, encrypt_secret
from ..vendor import nexoidc
from ..vendor.nexoidc import (
    LEGACY_SLUG,
    AccountState,
    Invite,
    Link,
    Provider,
    ProviderValues,
    migrate,
    secret_context,
)
from . import accounts, settings_service

logger = logging.getLogger("nexpaper.oidc")

APP_NAME = "nexpaper"
#: Where the API lies: the paths are ``/api/v1/oidc/<slug>/start`` and so on.
API_PREFIX = "/api/v1"
#: Where nexpaper's sign-in and account pages are, as the module sends the browser there.
LOGIN_PAGE = "/login"
ACCOUNT_PAGE = "/konto"
HOME = "/"
#: Longest account name (``accounts.NAME_PATTERN``).
NAME_MAX = 64
_NUMBERED = re.compile(r"^(.*?)(-\d+)$")


def _public_url() -> str:
    with SessionLocal() as db:
        return settings_service.public_url(db)


def _save_public_url(address: str) -> None:
    """The address the operator confirmed in the authentik card becomes the setting ``public_url``, at once and in a
    transaction of its own (module 1.0.10). nexpaper takes only ``scheme://host[:port]``: an address it would refuse in
    its own settings is not kept, and the module then answers ``public_url_needed``."""
    try:
        clean = settings_service.normalize_public_url(address)
    except ValueError:
        logger.warning("The address confirmed in the authentik card is not one nexpaper keeps")
        return
    with SessionLocal() as db:
        settings_service.save(db, {"public_url": clean})


def _server_secret() -> str:
    return get_settings().resolved_secret_key()


def configure() -> None:
    """Tell the module who it runs in; called once at start-up (and by the tests)."""
    nexoidc.configure(
        nexoidc.AppConfig(
            app_name=APP_NAME,
            server_secret=_server_secret,
            api_prefix=API_PREFIX,
            public_url=_public_url,
            save_public_url=_save_public_url,
            login_page=LOGIN_PAGE,
            account_page=ACCOUNT_PAGE,
            home=HOME,
            # Two instances on one host under different ports keep their attempt cookies apart.
            cookie_suffix=get_settings().cookie_name_suffix(),
        )
    )


def clean_name(raw: str) -> str:
    """An account name from what the provider suggests: lower case, nexpaper's characters, at most 64; a number at the
    end (``max-2``) survives the cut. Empty when nothing usable is left."""
    cleaned = re.sub(r"[^a-z0-9._-]", "-", raw.strip().lower()).strip("-._")
    if len(cleaned) > NAME_MAX:
        numbered = _NUMBERED.match(cleaned)
        suffix = numbered.group(2) if numbered else ""
        stem = numbered.group(1) if numbered else cleaned
        cleaned = stem[: NAME_MAX - len(suffix)].rstrip("-._") + suffix
    return cleaned if accounts.NAME_PATTERN.match(cleaned) else ""


def has_links(db: Session, account_id: int) -> bool:
    return db.scalar(select(OidcLink.id).where(OidcLink.account_id == account_id).limit(1)) is not None


def follows_provider(account: Account) -> bool:
    """An account that signs in through a provider only: its address is the provider's and follows it. Every other
    account is only offered the provider's address (account page), never given it."""
    return account.sign_in == SIGN_IN_OIDC and not account.password_hash


def address_taken(db: Session, email: str, own_id: int) -> bool:
    """Whether another account has this address already: nexpaper never gives one address to two accounts."""
    return (
        db.scalar(
            select(Account.id).where(func.lower(Account.email) == email.strip().lower(), Account.id != own_id).limit(1)
        )
        is not None
    )


def take_address(db: Session, account: Account, email: str | None) -> bool:
    """The provider's address becomes the account's, marked as from the provider (it goes with the last link) and
    **not confirmed**: a provider may send an address the person never showed to be theirs (authentik lets everybody
    change their own, Entra sends no ``email_verified``), and a confirmed address decides whose vault a mail to the
    intake reaches. The person confirms it by the link nexpaper sends, as any other address. False when there is none,
    it is no address, or another account has it."""
    clean = (email or "").strip()[:255]
    if not clean or not accounts.EMAIL_PATTERN.match(clean) or address_taken(db, clean, account.id):
        return False
    if clean.lower() == (account.email or "").strip().lower():
        # The same address it has: a confirmation of it by the person stays.
        return True
    account.email = clean
    account.email_from_provider = True
    account.email_confirmed_at = None
    return True


class SqlStore:
    """``nexoidc.Store`` over ``oidc_providers`` and ``oidc_links``, inside one session."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Providers -------------------------------------------------------------------------------------------------

    def _provider(self, row: OidcProvider | None) -> Provider | None:
        if row is None:
            return None
        return Provider(
            id=row.id,
            slug=row.slug,
            label=row.label,
            issuer=row.issuer,
            client_id=row.client_id,
            client_secret=decrypt_secret(row.client_secret_enc, secret_context(row.id)),
            scopes=row.scopes,
            enabled=row.enabled,
            auto_create=row.auto_create,
            trusts_second_factor=row.trusts_second_factor,
            managed=row.managed,
            position=row.position,
            redirect_path=row.redirect_path,
            created_at=row.created_at,
            registered_redirect=row.registered_redirect or "",
        )

    def list_providers(self) -> list[Provider]:
        rows = self.db.scalars(select(OidcProvider).order_by(OidcProvider.position, OidcProvider.id))
        return [provider for provider in (self._provider(row) for row in rows) if provider is not None]

    def get_provider(self, provider_id: int) -> Provider | None:
        return self._provider(self.db.get(OidcProvider, provider_id))

    def provider_by_slug(self, slug: str) -> Provider | None:
        return self._provider(self.db.scalar(select(OidcProvider).where(OidcProvider.slug == slug)))

    @staticmethod
    def _apply(row: OidcProvider, values: ProviderValues) -> None:
        row.slug, row.label, row.issuer, row.client_id = values.slug, values.label, values.issuer, values.client_id
        row.scopes, row.enabled, row.auto_create = values.scopes, values.enabled, values.auto_create
        row.trusts_second_factor, row.managed, row.position = (
            values.trusts_second_factor,
            values.managed,
            values.position,
        )
        row.redirect_path = values.redirect_path
        # None keeps what the authentik button registered last; only the button writes it.
        if values.registered_redirect is not None:
            row.registered_redirect = values.registered_redirect

    def insert_provider(self, values: ProviderValues) -> Provider:
        row = OidcProvider()
        self._apply(row, values)
        if values.registered_redirect is None:
            row.registered_redirect = ""
        self.db.add(row)
        self.db.flush()
        row.client_secret_enc = encrypt_secret(values.client_secret or "", secret_context(row.id))
        self.db.flush()
        _changed(self.db)
        provider = self._provider(row)
        assert provider is not None
        return provider

    def update_provider(self, provider_id: int, values: ProviderValues) -> Provider:
        row = self.db.get(OidcProvider, provider_id)
        assert row is not None
        self._apply(row, values)
        if values.client_secret is not None:
            row.client_secret_enc = encrypt_secret(values.client_secret, secret_context(row.id))
        self.db.flush()
        _changed(self.db)
        provider = self._provider(row)
        assert provider is not None
        return provider

    def delete_provider(self, provider_id: int) -> None:
        # Foreign keys are on (db.py), the links would go anyway; said here so that nothing depends on a pragma.
        self.drop_links(provider_id)  # marks the way back (``_changed``)
        self.db.execute(delete(OidcProvider).where(OidcProvider.id == provider_id))

    # --- Links -----------------------------------------------------------------------------------------------------

    @staticmethod
    def _link(row: OidcLink) -> Link:
        return Link(row.provider_id, row.subject, row.account_id, row.issuer, row.email, row.created_at,
                    row.last_used_at)

    def find_link(self, provider_id: int, subject: str) -> Link | None:
        row = self.db.scalar(select(OidcLink).where(OidcLink.provider_id == provider_id, OidcLink.subject == subject))
        return self._link(row) if row else None

    def links_of_provider(self, provider_id: int) -> list[Link]:
        rows = self.db.scalars(select(OidcLink).where(OidcLink.provider_id == provider_id).order_by(OidcLink.id))
        return [self._link(row) for row in rows]

    def links_of_account(self, account_id: int) -> list[Link]:
        rows = self.db.scalars(select(OidcLink).where(OidcLink.account_id == account_id).order_by(OidcLink.id))
        return [self._link(row) for row in rows]

    def add_link(self, link: Link) -> None:
        self.db.add(OidcLink(provider_id=link.provider_id, subject=link.subject, account_id=link.account_id,
                             issuer=link.issuer, email=link.email))
        self.db.flush()
        _changed(self.db)
        self._address(link.account_id, link.email)

    def remove_link(self, provider_id: int, account_id: int) -> bool:
        result = self.db.execute(
            delete(OidcLink).where(OidcLink.provider_id == provider_id, OidcLink.account_id == account_id)
        )
        removed = bool(result.rowcount)  # type: ignore[attr-defined]
        if removed:
            _changed(self.db)
            self._forget_provider_address(account_id)
        return removed

    def drop_links(self, provider_id: int) -> int:
        holders = set(self.db.scalars(select(OidcLink.account_id).where(OidcLink.provider_id == provider_id)))
        result = self.db.execute(delete(OidcLink).where(OidcLink.provider_id == provider_id))
        _changed(self.db)
        for account_id in holders:
            self._forget_provider_address(account_id)
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    def _forget_provider_address(self, account_id: int) -> None:
        """No link left for the account: an address that came from a provider goes too; one of its own (confirmed by
        a link, from the invitation, typed by the operator) stays, and so does every address while another link
        holds."""
        if has_links(self.db, account_id):
            return
        account = self.db.get(Account, account_id)
        if account is not None and account.email_from_provider:
            account.email = ""
            account.email_confirmed_at = None
            account.email_from_provider = False

    def touch_link(self, provider_id: int, subject: str, email: str | None) -> None:
        self.db.execute(
            update(OidcLink)
            .where(OidcLink.provider_id == provider_id, OidcLink.subject == subject)
            .values(last_used_at=utcnow(), email=email)
        )
        account_id = self.db.scalar(
            select(OidcLink.account_id).where(OidcLink.provider_id == provider_id, OidcLink.subject == subject)
        )
        if account_id is not None:
            self._address(account_id, email)

    def _address(self, account_id: int, email: str | None) -> None:
        """What the provider says about the address: an account through the provider only follows it (unconfirmed),
        as long as its address is the provider's or none; one it has from elsewhere (the invitation, confirmed by its
        owner) stays, and the provider's is offered on the account page, as to every other account."""
        if not email:
            return
        account = self.db.get(Account, account_id)
        if account is None or not follows_provider(account):
            return
        if account.email and not account.email_from_provider:
            return
        take_address(self.db, account, email)

    # --- Accounts --------------------------------------------------------------------------------------------------

    def account_state(self, account_id: int) -> AccountState | None:
        row = self.db.get(Account, account_id)
        if row is None:
            return None
        from . import totp

        return AccountState(
            id=row.id,
            name=row.name,
            blocked=row.blocked_at is not None,
            has_password=row.sign_in == SIGN_IN_PASSWORD and bool(row.password_hash),
            # A code from an app or a passkey: either is asked after a provider that is not trusted with it.
            has_second_factor=totp.has_second_factor(self.db, row),
        )

    def clean_name(self, raw: str) -> str:
        return clean_name(raw)

    def name_taken(self, name: str) -> bool:
        return accounts.by_name(self.db, name) is not None

    def create_account(self, name: str, *, invite: Invite | None, email: str | None) -> int:
        row = Account(name=name, role=MEMBER, sign_in=SIGN_IN_OIDC, whats_new_seen=__version__)
        self.db.add(row)
        # A name or a link another return wrote a moment ago fails here (unique), and the module takes it from there.
        self.db.flush()
        invited = invite.rights if invite is not None and isinstance(invite.rights, InviteRow) else None
        if invited is not None and invited.email and not address_taken(self.db, invited.email, row.id):
            # The address the operator made the invitation for, as with a password (unconfirmed, the person's own).
            row.email = invited.email.strip()[:255]
        else:
            take_address(self.db, row, email)
        _changed(self.db)
        logger.info("Account created name=%s role=%s sign_in=oidc", row.name, MEMBER)
        return row.id

    # --- Invitations -----------------------------------------------------------------------------------------------

    def find_invite(self, key: str) -> Invite | None:
        row = accounts.find_invite(self.db, key)
        # nexpaper's invitations bring membership and, when the operator named one, an address; the row travels as
        # its "rights".
        return Invite(key=key, id=row.id, rights=row) if row is not None else None

    def consume_invite(self, invite: Invite) -> bool:
        row = invite.rights
        return isinstance(row, InviteRow) and accounts.consume(self.db, row)

    def accept_invite(self, account_id: int, invite: Invite) -> None:
        """A known identity came through an invitation (module 1.0.8): what it brings comes on top, never instead.
        nexpaper's invitations bring membership, which the account has, and the address they were made for, which an
        account without one takes (unconfirmed, like any typed address)."""
        row = self.db.get(Account, account_id)
        invited = invite.rights if isinstance(invite.rights, InviteRow) else None
        if row is None or invited is None or not invited.email or row.email:
            return
        if not address_taken(self.db, invited.email, row.id):
            row.email = invited.email.strip()[:255]
            row.email_from_provider = False
            row.email_confirmed_at = None
            _changed(self.db)

    # --- Transaction -----------------------------------------------------------------------------------------------

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()


# --- The migration from the single provider of 1.0.1 ------------------------

#: The settings of the single provider before the list. They stay for one version (the way back), then go.
LEGACY_KEYS = ("oidc_issuer", "oidc_client_id", "oidc_client_secret_enc", "oidc_provider_name", "oidc_auto_create")
#: 1.0.1's switch "the provider checks a second factor". It decides ``trusts_second_factor`` of the migrated entry, and
#: the way back writes it so that 1.0.1 behaves as the entry does.
LEGACY_SECOND_FACTOR = "oidc_second_factor_by_provider"
#: What the way back last wrote into that switch: a switch 1.0.1 changed since is taken over at the next start.
WRITTEN_SECOND_FACTOR = "oidc_legacy_second_factor"
#: Set once the settings were looked at: an operator who later removes every entry must not get the old one back.
MIGRATED = "oidc_list_migrated"
#: What the old settings and the old column said when the way back was last written (``migrate.fingerprint``).
FINGERPRINT = "oidc_legacy_fingerprint"
#: The issuer 1.0.1 knows, as it wrote it, or ``migrate.CLOSED`` (``migrate.way_back``): stored, never read here.
ANCHOR = "oidc_legacy_anchor"
#: How nexpaper 1.0.1 behaved after the provider, from the start: it asked the code of its own second factor,
#: unless the operator had turned the switch on.
TRUSTED_BEFORE = False
#: The marker of the old authentik button: 1.0.1's button named the provider "authentik", the form never did.
BUTTON_LABEL = "authentik"


def _legacy(values: dict[str, object]) -> migrate.Legacy:
    label = str(values.get("oidc_provider_name") or "")
    return migrate.Legacy(
        issuer=str(values.get("oidc_issuer") or ""),
        client_id=str(values.get("oidc_client_id") or ""),
        # Sealed without a context in 1.0.1; the entry seals it anew under its own (``secret_context``).
        client_secret=decrypt_secret(str(values.get("oidc_client_secret_enc") or "")),
        label=label,
        auto_create=bool(values.get("oidc_auto_create")),
        set_up_by_button=label == BUTTON_LABEL,
    )


def trusted_before(values: dict[str, object]) -> bool:
    """How 1.0.1 behaves after its provider today: without a code when its switch is on (the switch decides the migrated
    entry)."""
    return bool(values.get(LEGACY_SECOND_FACTOR, TRUSTED_BEFORE))


def read_legacy(db: Session) -> tuple[migrate.Legacy, list[tuple[int, str]]]:
    """The old settings and the old column, read the one way the migration, the fingerprint and ``resync`` read them
    (the secret opened, as the module wants it for the fingerprint)."""
    subjects = [
        (account_id, subject)
        for account_id, subject in db.execute(
            select(Account.id, Account.oidc_subject).where(Account.oidc_subject != "").order_by(Account.id)
        )
    ]
    return _legacy(settings_service.get_all(db)), subjects


def _provider_address_unconfirmed(db: Session) -> int:
    """1.0.1 took a provider's address as confirmed when the provider said ``email_verified``. From now on only the
    person confirms an address: such an address stays,
    unconfirmed, until the person opens the link nexpaper sends."""
    result = db.execute(
        update(Account)
        .where(Account.email_from_provider.is_(True), Account.email_confirmed_at.is_not(None))
        .values(email_confirmed_at=None)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def migrate_settings(*, backup: bool = True) -> Provider | None:
    """At every start. The first time: the provider of 1.0.1 becomes the entry ``oidc`` with a link per stored subject,
    ``/api/v1/oidc/callback`` keeps signing in, a backup goes first. Every later start takes over what 1.0.1 changed on
    the way back (``take_over_way_back``). Always, the way back is written again with its fingerprint."""
    with SessionLocal() as db:
        if settings_service.get(db, MIGRATED):
            take_over_way_back(db, backup=backup)
            return None
        legacy, subjects = read_legacy(db)
        values = settings_service.get_all(db)
        plan = migrate.plan(legacy, subjects, trusts_second_factor=trusted_before(values))
        has_entries = bool(db.scalar(select(func.count()).select_from(OidcProvider)))
    if plan is not None and not has_entries and backup:
        from . import backups

        backups.create(kind=backups.UPDATE, note="before the sign-in provider list")
    with SessionLocal() as db:
        if settings_service.get(db, MIGRATED):
            return None
        legacy, _subjects = read_legacy(db)
        unconfirmed = _provider_address_unconfirmed(db)
        if unconfirmed:
            logger.warning("OIDC: %d addresses from the provider wait for their owner's confirmation now", unconfirmed)
        # The anchor first: ``apply`` commits, and the way back written in that commit must see it.
        settings_service.save(db, {ANCHOR: migrate.anchor_of(legacy), MIGRATED: True}, commit=False)
        entry = None
        if plan is not None and not has_entries:
            entry = migrate.apply(SqlStore(db), plan)
        # Written whatever happened, with the fingerprint (also "no provider"): a provider 1.0.1 sets up later is taken
        # over at the next start, not thrown away; a subject the migration left out goes from the old column too.
        keep_way_back(db)
        db.commit()
        return entry


def _take_over_switch(db: Session) -> None:
    """1.0.1 changed its switch "the provider checks a second factor" since the way back wrote it: the entry ``oidc``
    follows, as 1.0.1 behaved meanwhile (only while the way back is open, as for the other settings)."""
    values = settings_service.get_all(db)
    written = values.get(WRITTEN_SECOND_FACTOR)
    now = bool(values.get(LEGACY_SECOND_FACTOR))
    if written is None or bool(written) == now:
        return
    store = SqlStore(db)
    entry = store.provider_by_slug(LEGACY_SLUG)
    anchor = str(values.get(ANCHOR) or "")
    if entry is None or not anchor or anchor == migrate.CLOSED or entry.trusts_second_factor == now:
        return
    store.update_provider(entry.id, nexoidc.providers.values_of(entry, trusts_second_factor=now))
    logger.warning("OIDC: 1.0.1 changed whether the provider checks the second factor; the entry oidc follows (%s)",
                   "on" if now else "off")


def take_over_way_back(db: Session, *, backup: bool = True) -> migrate.Resync:
    """The rest of every start after the first one: what 1.0.1 changed in the old settings and the old column since
    the way back was last written is taken over (``migrate.resync``), then the way back is written again with the
    fingerprint of what stands there, always, also with no provider at all. A start that changed nothing changes
    nothing. A backup goes first when there is something to take over."""
    legacy, subjects = read_legacy(db)
    values = settings_service.get_all(db)
    previous = str(values.get(FINGERPRINT) or "") or None
    switch_changed = values.get(WRITTEN_SECOND_FACTOR) is not None and bool(
        values.get(WRITTEN_SECOND_FACTOR)) != bool(values.get(LEGACY_SECOND_FACTOR))
    if backup and (migrate.changes_since(previous, legacy, subjects).any or switch_changed):
        from . import backups

        backups.create(kind=backups.UPDATE, note="before taking over what 1.0.1 changed")
    _take_over_switch(db)
    done = migrate.resync(
        SqlStore(db),
        legacy,
        subjects,
        previous=previous,
        trusts_second_factor=trusted_before(values),
        anchor=str(values.get(ANCHOR) or "") or None,
        keep_anchor=lambda value: settings_service.save(db, {ANCHOR: value}, commit=False),
    )
    keep_way_back(db)
    db.commit()
    return done


# --- The way back (one version): the settings and the column of 1.0.1 follow the list -------------------------------

#: The marker in ``Session.info``: an entry, a link or an account changed in this transaction.
_WAY_BACK = "nexpaper_oidc_way_back"


def _changed(db: Session) -> None:
    db.info[_WAY_BACK] = True


def way_back_changed(db: Session) -> None:
    """For a way that changes accounts or links around the store (deleting an account): the way back and the
    fingerprint follow in the same commit, or the next start would take the missing subject for a change 1.0.1 made."""
    db.flush()
    keep_way_back(db)


@event.listens_for(Session, "before_commit")
def _write_way_back(session: Session) -> None:
    if session.info.pop(_WAY_BACK, False):
        keep_way_back(session)


@event.listens_for(Session, "after_rollback")
def _forget_way_back(session: Session) -> None:
    session.info.pop(_WAY_BACK, None)


def _sealed(secret: str, old: dict[str, object]) -> str:
    """The secret for the old settings, sealed without a context as 1.0.1 reads it; a secret that did not change keeps
    its sealing (sealing again would change the settings on every write)."""
    sealed = str(old.get("oidc_client_secret_enc") or "")
    if decrypt_secret(sealed) != secret or (secret and not sealed):
        sealed = encrypt_secret(secret) if secret else ""
    return sealed


def keep_way_back(db: Session) -> None:
    """Writes the settings and the column 1.0.1 reads from the list (``migrate.way_back``: the entry ``oidc`` and the
    stored anchor decide, one rule for every app), so that 1.0.1 started on this database finds what the list holds,
    never more. nexpaper writes it in the form of 1.0.1, the issuer letter by letter as the anchor holds it, stores the
    anchor that comes back, then the fingerprint of what stands there.

    1.0.1's switch "the provider checks a second factor" follows the entry: on exactly when the entry trusts the
    provider with the second factor and the way back shows it in full (rule 1 of ``way_back``), so that 1.0.1 asks no
    code where the entry asks none. An entry that does not trust the provider is rule 2 (no client: 1.0.1 lets nobody
    in through it, never with less than the entry asks); while the way back is closed, or without the entry, the switch
    is off (1.0.1's default)."""
    db.flush()
    values = settings_service.get_all(db)
    if not values.get(MIGRATED):
        return  # the old settings and the column are still the migration's input
    store = SqlStore(db)
    entry = store.provider_by_slug(LEGACY_SLUG)
    links = [(link.account_id, link.subject) for link in store.links_of_provider(entry.id)] if entry else []
    mirror = migrate.way_back(entry, links, str(values.get(ANCHOR) or "") or None)
    shown = mirror.legacy
    current = {key: values.get(key) for key in LEGACY_KEYS}
    legacy = {
        "oidc_issuer": shown.issuer,
        "oidc_client_id": shown.client_id,
        "oidc_client_secret_enc": _sealed(shown.client_secret, current),
        "oidc_provider_name": shown.label,
        "oidc_auto_create": bool(shown.auto_create),
    }
    trusted = bool(entry is not None and shown.client_id and entry.trusts_second_factor)
    changes: dict[str, object] = {key: value for key, value in legacy.items() if current.get(key) != value}
    if bool(values.get(LEGACY_SECOND_FACTOR)) != trusted:
        changes[LEGACY_SECOND_FACTOR] = trusted
    if values.get(WRITTEN_SECOND_FACTOR) != trusted:
        changes[WRITTEN_SECOND_FACTOR] = trusted
    if values.get(ANCHOR) != mirror.anchor:
        changes[ANCHOR] = mirror.anchor
    for row in db.scalars(select(Account)):
        subject = mirror.subjects.get(row.id, "")
        if row.oidc_subject != subject:
            row.oidc_subject = subject
    db.flush()
    stamp = migrate.fingerprint(
        _legacy({**current, **legacy}),
        [(row.id, row.oidc_subject) for row in db.scalars(select(Account).order_by(Account.id)) if row.oidc_subject],
    )
    if values.get(FINGERPRINT) != stamp:
        changes[FINGERPRINT] = stamp
    if changes:
        settings_service.save(db, changes, commit=False)
    db.flush()


__all__ = [
    "MIGRATED",
    "SqlStore",
    "clean_name",
    "configure",
    "follows_provider",
    "keep_way_back",
    "migrate_settings",
    "read_legacy",
    "take_address",
    "take_over_way_back",
    "way_back_changed",
]
