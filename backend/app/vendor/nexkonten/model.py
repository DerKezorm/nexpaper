"""The data the module works with, and the ``Store`` the app implements over its own database.

The tables and their columns are the app's (``users.username`` in one app, ``benutzer.benutzername`` in another).
The module never sees a database; it calls the ``Store`` methods below and the app answers them with SQLAlchemy,
sqlite3 or whatever it uses. All methods are synchronous: every app runs its database synchronously.

A ``Store`` works inside one transaction of the app. The module calls ``commit()`` once an outcome is settled and
``rollback()`` when it refuses after having written (a consumed invitation or link comes back that way). The app
opens the store per request and closes it afterwards.

Passwords and link tokens reach the store in plain text and leave it never: the store hashes a password with the
app's own hasher and keeps only a hash of a token (as it does today, so that links made by the older version of
the app keep working).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

#: An account's key as the app has it: a number in most apps, a string in others. The module only passes it on.
AccountId = int | str

#: ``Account.email_source``: where the address came from, independent of whether it counts. ``EMAIL_OWN`` is what a
#: person or the operator typed (setup, invitation, profile, a confirmation link); ``EMAIL_PROVIDER`` an address the
#: account follows at its sign-in provider until the person sets one of their own. An app may keep more values of its
#: own (an address taken over from a provider by the person, say); the module only compares with these two.
EMAIL_OWN = ""
EMAIL_PROVIDER = "provider"

#: ``Account.picture``: whether the account has a picture, and whose. A picture the person set (or one of an older
#: version) is ``PICTURE_OWN`` and is never replaced by a provider's.
PICTURE_NONE = ""
PICTURE_OWN = "own"
PICTURE_PROVIDER = "provider"

#: ``Store.second_factor``: the account has no second factor and the app asks none; has one; must set one up before
#: anything else (an app or a role that requires it).
SECOND_FACTOR_NONE = "none"
SECOND_FACTOR_ACTIVE = "active"
SECOND_FACTOR_REQUIRED = "required"
#: Since 0.3.2: the operator asks a second factor of everybody and the account's is a passkey (no authenticator app):
#: after the password or the provider the passkey is the second step.
SECOND_FACTOR_PASSKEY = "passkey"

#: ``common.next_step``: what the app starts after setup, an invitation, a new password, a sign-in. ``NEXT_SESSION``: a
#: full session; ``NEXT_SECOND_FACTOR``: ask the code of the second factor first; ``NEXT_SECOND_FACTOR_SETUP``: a
#: session that can do nothing but set up a second factor (the app requires one); ``NEXT_SIGN_IN``: no session, to
#: the sign-in page (a blocked account).
NEXT_SESSION = "session"
NEXT_SECOND_FACTOR = "second_factor"
NEXT_SECOND_FACTOR_SETUP = "second_factor_setup"
NEXT_SIGN_IN = "sign_in"
#: Since 0.3.2: ``NEXT_PASSKEY`` the second step is a passkey (``factor.finish_waiting_by_passkey``);
#: ``NEXT_SHOW_CODES`` a second factor was just set up at sign-in: show the recovery codes once, then the session.
NEXT_PASSKEY = "passkey"
NEXT_SHOW_CODES = "show_codes"

#: ``Reset.origin``: who made a link for a new password. A person on the sign-in page, an operator under Accounts, or
#: the emergency command on the server (no operator signed in).
RESET_SELF = "self"
RESET_OPERATOR = "operator"
RESET_SERVER = "server"


@dataclass(frozen=True)
class Account:
    """One account as the module needs it.

    ``username`` is stored as it was written: an older version may have names with capitals, of one letter or with
    characters the rules no longer allow, and they keep working until changed. ``email`` is the address in effect
    ("" for none). Two separate answers about it: ``email_confirmed`` says it **counts** (signing in, a forgotten
    password, the app's notices), ``email_proven`` that somebody opened a link mailed there (where an app sends things
    that must reach the right person, such as an inbox of its own). ``pending_email`` waits for its confirmation link.
    ``blocked`` is true for a blocked and for a deleted account (finders return both).
    """

    id: AccountId
    username: str
    display_name: str = ""
    email: str = ""
    email_confirmed: bool = True
    email_source: str = EMAIL_OWN
    email_proven: bool = False
    pending_email: str = ""
    #: Signs in with a password of its own (False: through a provider only).
    has_password: bool = True
    blocked: bool = False
    operator: bool = False
    picture: str = PICTURE_NONE
    #: The language the account chose (``de``, ``en-GB``), "" for the browser's. Kept at the account, part of the
    #: profile; mails to the account go out in it.
    language: str = ""
    #: Since 0.3.3: an address a provider named for an account with a password, only offered ("Use the address from
    #: <provider>?" in the profile, ``profiles.take_offered_email``); "" for none. Never counts, never signs in.
    offered_email: str = ""
    #: Since 0.3.4: the name of the provider that offered it (its label, as on its button: "Pocket ID"), for "Use the
    #: address from <provider>?"; "" when the store does not keep it (the app then names its provider itself).
    offered_email_provider: str = ""
    #: Since 0.3.4: the address the person said "No, thanks" to; it is never offered again, only another one is.
    declined_email: str = ""
    #: Since 0.3.10: when the password was set last (setup, invitation, a link, a change), for "Last changed on …" in
    #: the box Password under Security in every app. None: not known (a password of an older version that kept no
    #: date, or no password at all); the page then says so.
    password_changed_at: datetime | None = None


@dataclass(frozen=True)
class NewAccount:
    """What the module writes for a new account. ``password`` is plain text, "" for none (the store hashes it).
    ``invite`` is the invitation that was consumed for it: the store gives the account its rights (role, spaces,
    teams; the module never looks inside ``invite.rights``). Without one the account is the operator (``operator``)
    or a plain member."""

    username: str
    display_name: str
    email: str
    email_confirmed: bool
    password: str
    language: str = ""
    operator: bool = False
    invite: Invite | None = None
    email_proven: bool = False


@dataclass(frozen=True)
class Invite:
    """An invitation as the app knows it. ``key`` is the token of the link. ``email`` and ``display_name`` are what
    the operator gave; ``username`` is set only for an invitation of an older version that fixed the name (the form
    shows it as the suggestion). ``expires_at`` lets the module tell "expired" from "not valid". ``rights`` is the
    app's own description of what the invitation grants, passed through untouched. ``reusable``: an invitation into a
    space that several people may follow (it is not used up by one)."""

    key: str
    id: int | str = ""
    email: str = ""
    display_name: str = ""
    username: str = ""
    expires_at: datetime | None = None
    rights: object = None
    reusable: bool = False


@dataclass(frozen=True)
class EmailChange:
    """An address waiting for its confirmation link."""

    id: int | str
    account_id: AccountId
    address: str
    expires_at: datetime


@dataclass(frozen=True)
class Reset:
    """An open link to set a new password. ``origin`` is ``RESET_SELF``, ``RESET_OPERATOR`` or ``RESET_SERVER``;
    ``created_by`` the operator who made it (None for the other two)."""

    id: int | str
    account_id: AccountId
    expires_at: datetime
    created_by: AccountId | None = None
    origin: str = RESET_SELF


#: Since 0.3.10: ``Access.kind``, the same names in every app (``ACCESS_KINDS``; ``ACCESS_KINDS`` in ``konten.ts``
#: with their words): a paired app (iPhone, iPad), a calendar program with its own password (CalDAV), an address book
#: program with its own password (CardDAV, nexfolk), an API key, a passkey.
ACCESS_DEVICE = "device"
ACCESS_CALENDAR = "calendar"
ACCESS_CONTACTS = "contacts"
ACCESS_API_KEY = "api_key"
ACCESS_PASSKEY = "passkey"
ACCESS_KINDS = (ACCESS_DEVICE, ACCESS_CALENDAR, ACCESS_CONTACTS, ACCESS_API_KEY, ACCESS_PASSKEY)


@dataclass(frozen=True)
class Access:
    """A way into the account that a new password does not end: a paired device, a calendar or address book program
    with its own password, an API key, a passkey. For "These devices still have access" with "Disconnect all".
    ``kind`` is one of ``ACCESS_KINDS`` (since 0.3.10; the contract tests check it)."""

    id: int | str
    kind: str
    label: str
    last_used_at: datetime | None = None


@dataclass(frozen=True)
class Picture:
    """A picture read and written anew by the module: ``content_type`` is ``image/png`` or ``image/jpeg``. The app
    passes ``data`` through its own picture handling (cropping, its own format) like an upload."""

    data: bytes
    content_type: str
    width: int
    height: int


#: ``Mail.kind``: what the app sends. The module never sends a mail: it says what to send, the app builds the link
#: from its public address and the token, and sends it with its own mailer and templates (best in the background, so
#: that the time of an answer tells nobody whether there was anything to send).
MAIL_RESET = "reset"
MAIL_CONFIRM_EMAIL = "confirm_email"
MAIL_USERNAME_CHANGED = "username_changed"
#: To the old address after a change or removal: ``to`` is the old address, ``new_hint`` the new one shortened
#: (``m***@example.com``), "" when the address was taken away.
MAIL_EMAIL_CHANGED = "email_changed"
#: Since 0.3.0: the operator took every second factor of the account away; a browser signed in for the first time.
MAIL_FACTOR_RESET = "factor_reset"
MAIL_NEW_SIGN_IN = "new_sign_in"


@dataclass(frozen=True)
class Mail:
    """A mail the app is to send. ``token`` is the plain token of a link (``MAIL_RESET``: the page that sets a new
    password; ``MAIL_CONFIRM_EMAIL``: the page that confirms ``to``), "" for a plain notice. ``hours``: how long the
    link holds. ``at`` (since 1.0.0): when it happened, for the mail "New sign-in" (the moment it names, in the
    person's time zone, ``nexpost.letters.from_account_mail``); None elsewhere."""

    kind: str
    to: str
    account_id: AccountId
    username: str
    display_name: str = ""
    token: str = ""
    hours: int = 0
    new_hint: str = ""
    at: datetime | None = None


#: ``Event.kind``: what the store hears after a commit (``Store.notify``).
EVENT_CREATED = "created"
EVENT_JOINED = "joined"
EVENT_RENAMED = "renamed"
EVENT_EMAIL_CHANGED = "email_changed"
EVENT_PASSWORD_SET = "password_set"
#: Since 0.3.10: an address that counted already was proven by its link (``profiles.prove_email``); ``new`` is it.
EVENT_EMAIL_PROVEN = "email_proven"


@dataclass(frozen=True)
class Event:
    """Something the module settled and committed: the app may follow up (join spaces of an invitation, wake people
    waiting for the account, tell a calendar). ``old`` and ``new`` for a rename or a changed address."""

    kind: str
    account_id: AccountId
    invite: Invite | None = None
    old: str = ""
    new: str = ""
    details: dict[str, object] = field(default_factory=dict)


class Taken(Exception):
    """Raised by the store when the database refuses a write because another account holds the value: ``what`` is
    ``"username"``, ``"email"`` or ``"display_name"``. The module rolls back and answers with the matching code."""

    def __init__(self, what: str) -> None:
        super().__init__(f"{what} taken")
        self.what = what


class Store(Protocol):
    """Implemented by the app over its own tables."""

    # --- Accounts ------------------------------------------------------------------------------------------------
    def count_accounts(self) -> int:
        """Every account there is, blocked and deleted ones included (setup is only for a server without any)."""
        ...

    def get_account(self, account_id: AccountId) -> Account | None: ...

    def set_offered_email(self, account_id: AccountId, address: str, provider: str = "") -> None:
        """Since 0.3.3: keep the address a provider offers an account with a password (``Account.offered_email``),
        "" takes the offer away. Since 0.3.4 with the provider's name (``Account.offered_email_provider``; a store of
        0.3.3 without the parameter keeps working, the name is then lost). A store without it offers nothing; the
        contract tests ask for it."""
        ...

    def set_declined_email(self, account_id: AccountId, address: str) -> None:
        """Since 0.3.4: keep the address the person said "No, thanks" to (``Account.declined_email``), for good: it is
        not offered again. A store without it offers the same address again at the next sign-in; the contract tests
        ask for it."""
        ...

    def find_by_username(self, username: str) -> list[Account]:
        """Every account whose **current** username equals this one without regard to case (normally none or one),
        blocked and deleted accounts included."""
        ...

    def find_by_email(self, address: str) -> list[Account]:
        """Every account whose address in effect equals this one without regard to case, confirmed or not, blocked
        and deleted ones included. An older version may have given one address to several accounts: they all come
        back, and the module lets none of them be found by it."""
        ...

    def name_reserved(self, username: str, except_id: AccountId | None) -> bool:
        """Whether a username is held although no account has it now: a former name of another account than
        ``except_id``, or the name of an account deleted for good. Names stay reserved for ever (nobody inherits
        another's mail, versions, mentions, calendars)."""
        ...

    def find_by_former_name(self, username: str) -> list[Account]:
        """The accounts that once had this username (without regard to case): for the things in the background that
        still know the old name (calendar and address book programs, an inbox folder), never for signing in."""
        ...

    def display_name_taken(self, display_name: str, except_id: AccountId | None) -> bool:
        """Whether another account than ``except_id`` has this display name, compared as ``names.display_key`` (NFKC,
        without regard to case). Display names are unique in every app."""
        ...

    def add_account(self, new: NewAccount) -> AccountId:
        """Insert. Raises ``Taken("username")`` when the database refuses the name (a unique index on the name in
        lower case), ``Taken("email")`` or ``Taken("display_name")`` likewise. Nothing committed here."""
        ...

    def set_username(self, account_id: AccountId, username: str) -> None:
        """Raises ``Taken("username")`` when the database refuses it: two changes at the same moment to the same
        name must not both get through. The old name becomes a former name of the account (``name_reserved``,
        ``find_by_former_name``). The store may change what hangs on the name in the app (history, mentions, folders)
        in the same transaction. Sessions, devices, keys and links stay (they hang on the id)."""
        ...

    def set_display_name(self, account_id: AccountId, display_name: str) -> None: ...

    def set_email(self, account_id: AccountId, address: str, *, confirmed: bool, proven: bool, source: str) -> None:
        """The address in effect and its two answers; "" takes it away. May raise ``Taken("email")``."""
        ...

    def set_language(self, account_id: AccountId, language: str) -> None:
        """The account's language ("" for the browser's)."""
        ...

    # --- Passwords, failures, sessions ---------------------------------------------------------------------------
    def check_password(self, account_id: AccountId | None, password: str) -> bool:
        """Whether the password is the account's. None, or an account without a password: as long as a real check
        and False, so that the time of an answer tells nobody which accounts exist."""
        ...

    def set_password(self, account_id: AccountId, password: str) -> None:
        """Hash and store a new password; the account signs in with a password from now on (a provider stays
        linked), a lock after failed attempts is lifted. Since 0.3.10 the store keeps the moment too
        (``Account.password_changed_at``), also for the first password of ``add_account``."""
        ...

    def is_locked(self, account_id: AccountId) -> bool:
        """Locked after too many wrong passwords, **for a while only** (``LOCK_MINUTES`` by default, the app's own
        time where it has one): a stranger must not lock an account for good. An app without a lock answers False."""
        ...

    def note_failure(self, account_id: AccountId | None) -> None:
        """A wrong password for this account: counted at the account (whatever was typed, name or address), locked
        after the app's limit. ``None``: an attempt that named no account; the store writes as much as for a known one
        (a row of failed attempts, a touched counter), so that both answers take the same time. The module commits
        after either."""
        ...

    def note_success(self, account_id: AccountId) -> None:
        """The account signed in (after its second factor, where it has one): the count of failures starts anew."""
        ...

    def end_sessions(self, account_id: AccountId) -> None:
        """After a new password from a link: end every **browser** session and every sign-in that waits for its
        second factor, and make every "known browser" mark of the account worthless (``login.authenticate``'s
        ``known_browser``). Paired devices, calendar and address book programs, API keys and passkeys stay
        (``list_access``)."""
        ...

    def list_access(self, account_id: AccountId) -> list[Access]:
        """What still has access after ``end_sessions``: for "These devices still have access"."""
        ...

    def revoke_access(self, account_id: AccountId) -> int:
        """"Disconnect all": every device, program password, API key and passkey of the account; the number."""
        ...

    def second_factor(self, account_id: AccountId) -> str:
        """``SECOND_FACTOR_NONE``, ``_ACTIVE`` or ``_REQUIRED`` (the app requires one and the account has none)."""
        ...

    # --- Pictures ------------------------------------------------------------------------------------------------
    def set_provider_picture(self, account_id: AccountId, picture: Picture) -> bool:
        """Store a provider's picture, only while the account has no picture at all (one statement with that
        condition, so that a picture the person sets meanwhile is never replaced). False when it had one."""
        ...

    # --- Invitations ---------------------------------------------------------------------------------------------
    def find_invite(self, key: str) -> Invite | None:
        """The invitation of a link, also when it ran out (``expires_at`` says so); None when unknown, used, or its
        inviter is no longer allowed to invite."""
        ...

    def consume_invite(self, invite: Invite) -> bool:
        """Use the invitation up with one statement that must hit exactly one row; False when somebody else was
        faster (two people with the same link at the same moment: only one gets an account). A reusable invitation
        answers True and stays."""
        ...

    def accept_invite(self, account_id: AccountId, invite: Invite) -> None:
        """Give an existing account the rights of the invitation in addition to its own (join a space with the
        signed-in account). Adds, never takes away."""
        ...

    # --- Address changes -----------------------------------------------------------------------------------------
    def start_email_change(self, account_id: AccountId, address: str, token: str, expires_at: datetime) -> None:
        """An address waiting for its link; one of the account waiting before goes. Only a hash of ``token``."""
        ...

    def find_email_change(self, token: str) -> EmailChange | None:
        """The change of a link, also when it ran out; None when unknown or used."""
        ...

    def consume_email_change(self, change: EmailChange) -> bool:
        """Use it up with one statement that must hit exactly one row."""
        ...

    def drop_email_change(self, account_id: AccountId) -> None:
        """Withdraw what waits for the account."""
        ...

    # --- Links for a new password --------------------------------------------------------------------------------
    def start_reset(
        self,
        account_id: AccountId,
        token: str,
        expires_at: datetime,
        *,
        created_by: AccountId | None,
        origin: str,
    ) -> None:
        """A new link; one of the account open before goes. Only a hash of ``token``. ``origin`` is kept with it."""
        ...

    def find_reset(self, token: str) -> Reset | None:
        """The link, also when it ran out; None when unknown or used."""
        ...

    def consume_reset(self, reset: Reset) -> bool:
        """Use it up with one statement that must hit exactly one row."""
        ...

    def drop_resets(self, account_id: AccountId, *, origin: str | None = None) -> None:
        """Every open link of the account goes (a mail that could not be sent leaves none behind); with ``origin``
        only the links of that origin (the account's address changed: links a person asked for to the old one go)."""
        ...

    # --- Setup ---------------------------------------------------------------------------------------------------
    def claim_setup(self) -> bool:
        """Mark the server as set up, with one statement that succeeds once in the life of the database (a unique row,
        say): two setups at the same moment, also in two processes, never both make an operator. False when another
        was first. Nothing committed here."""
        ...

    # --- After a commit ------------------------------------------------------------------------------------------
    def notify(self, event: Event) -> None:
        """Called after the commit of what ``event`` describes. Whatever the app does here (best in a worker), it
        cannot undo the outcome; a failure is logged by the module and changes nothing."""
        ...

    # --- Transaction ---------------------------------------------------------------------------------------------
    def commit(self) -> None: ...

    def rollback(self) -> None: ...
