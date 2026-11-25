"""nexkonten: accounts, setup, invitation, signing in with a password, profile and a forgotten password, the same in
every nex app.

This package is vendored unchanged into ``backend/app/vendor/nexkonten/``. A test in the app compares the files with
the checksums in ``MANIFEST.json``, so a change is made in the module's source, never in the copy.

What lives here:

- ``config``: what the app tells the module about itself (``configure(AppConfig(...))``);
- ``model``: accounts, invitations, links, mails, and the ``Store`` the app implements over its database;
- ``names``: display name, username and address: rules, suggestion, numbering;
- ``visible``: what a display name shows, and the key under which look-alike names are equal;
- ``login``: "Username or email" and the password;
- ``setup``: the first account with the setup code;
- ``invites``: what the operator gives, the form and accepting an invitation;
- ``profiles``: changing username, display name and address, the confirmation link;
- ``resets``: a forgotten password, by mail or by a link from the operator;
- ``pictures``: a provider's picture, fetched with care;
- since 0.3.0: ``factor`` (time-based code, recovery codes, the waiting sign-in), ``passkeys`` (imported on its own,
  it needs ``webauthn``), ``sessions`` (list, everywhere, stay signed in, known browser), ``brake`` (in memory, the
  sender behind a proxy), ``avatars`` (upload, deliver, who sees), with their stores in ``model2``.

Only httpx and Pillow are needed (for a provider's picture); nothing from an app is imported.
"""

from __future__ import annotations

from . import (
    avatars,
    brake,
    common,
    factor,
    invites,
    login,
    model2,
    names,
    pictures,
    profiles,
    resets,
    sessions,
    setup,
    visible,
)
from .config import AppConfig, configure, current, use_transport
from .errors import CODES, AccountError, PictureRefused
from .model import (
    ACCESS_API_KEY,
    ACCESS_CALENDAR,
    ACCESS_CONTACTS,
    ACCESS_DEVICE,
    ACCESS_KINDS,
    ACCESS_PASSKEY,
    EMAIL_OWN,
    EMAIL_PROVIDER,
    EVENT_CREATED,
    EVENT_EMAIL_CHANGED,
    EVENT_EMAIL_PROVEN,
    EVENT_JOINED,
    EVENT_PASSWORD_SET,
    EVENT_RENAMED,
    MAIL_CONFIRM_EMAIL,
    MAIL_EMAIL_CHANGED,
    MAIL_FACTOR_RESET,
    MAIL_NEW_SIGN_IN,
    MAIL_RESET,
    MAIL_USERNAME_CHANGED,
    NEXT_PASSKEY,
    NEXT_SECOND_FACTOR,
    NEXT_SECOND_FACTOR_SETUP,
    NEXT_SESSION,
    NEXT_SHOW_CODES,
    NEXT_SIGN_IN,
    PICTURE_NONE,
    PICTURE_OWN,
    PICTURE_PROVIDER,
    RESET_OPERATOR,
    RESET_SELF,
    RESET_SERVER,
    SECOND_FACTOR_ACTIVE,
    SECOND_FACTOR_NONE,
    SECOND_FACTOR_PASSKEY,
    SECOND_FACTOR_REQUIRED,
    Access,
    Account,
    AccountId,
    EmailChange,
    Event,
    Invite,
    Mail,
    NewAccount,
    Picture,
    Reset,
    Store,
    Taken,
)

__version__ = "0.3.10"

__all__ = [
    "ACCESS_API_KEY",
    "ACCESS_CALENDAR",
    "ACCESS_CONTACTS",
    "ACCESS_DEVICE",
    "ACCESS_KINDS",
    "ACCESS_PASSKEY",
    "CODES",
    "EMAIL_OWN",
    "EMAIL_PROVIDER",
    "EVENT_CREATED",
    "EVENT_EMAIL_CHANGED",
    "EVENT_EMAIL_PROVEN",
    "EVENT_JOINED",
    "EVENT_PASSWORD_SET",
    "EVENT_RENAMED",
    "MAIL_CONFIRM_EMAIL",
    "MAIL_EMAIL_CHANGED",
    "MAIL_FACTOR_RESET",
    "MAIL_NEW_SIGN_IN",
    "MAIL_RESET",
    "MAIL_USERNAME_CHANGED",
    "NEXT_PASSKEY",
    "NEXT_SECOND_FACTOR",
    "NEXT_SECOND_FACTOR_SETUP",
    "NEXT_SESSION",
    "NEXT_SHOW_CODES",
    "NEXT_SIGN_IN",
    "PICTURE_NONE",
    "PICTURE_OWN",
    "PICTURE_PROVIDER",
    "RESET_OPERATOR",
    "RESET_SELF",
    "RESET_SERVER",
    "SECOND_FACTOR_ACTIVE",
    "SECOND_FACTOR_NONE",
    "SECOND_FACTOR_PASSKEY",
    "SECOND_FACTOR_REQUIRED",
    "Access",
    "Account",
    "AccountError",
    "AccountId",
    "AppConfig",
    "EmailChange",
    "Event",
    "Invite",
    "Mail",
    "NewAccount",
    "Picture",
    "PictureRefused",
    "Reset",
    "Store",
    "Taken",
    "__version__",
    "avatars",
    "brake",
    "common",
    "configure",
    "current",
    "factor",
    "invites",
    "login",
    "model2",
    "names",
    "pictures",
    "profiles",
    "resets",
    "sessions",
    "setup",
    "use_transport",
    "visible",
]
