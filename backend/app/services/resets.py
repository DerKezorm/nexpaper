"""Setting a new password by a link: what is nexpaper's own beside the shared account module.

The links themselves (made, mailed, used) are the module's (``vendor/nexkonten/resets.py``, routes in
``routers/resets.py``, the emergency command ``app/reset_link.py``): the operator cannot set a password for anybody;
a person gets a link and sets their own, sent by the operator or asked for on the sign-in page ("Forgot your
password?") where a mail server is set up and the account has an address that counts.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import mailer, settings_service


def available(db: Session) -> bool:
    """"Forgot your password?" is offered: mail works, the public address is known (the link comes from nothing
    else) and signing in with a password is on."""
    return bool(
        mailer.configured(db) and settings_service.public_url(db) and settings_service.get(db, "password_login")
    )
