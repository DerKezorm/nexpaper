"""The mail address of an account: what is nexpaper's own beside the shared account module.

Changing, confirming and removing the address is the module's (``profiles.change_email``, ``confirm_email``,
``remove_email``; routes in ``routers/emails.py`` and ``PUT /api/v1/me/profile``): with a mail server the new address
waits for the link mailed to it, without one it counts at once. nexpaper keeps two answers about it
(``services/konten_store.py``): the address **counts** (signing in, "Forgot your password?") and it is **proven** by a
link (``email_confirmed_at``): only a proven address lets mail into a vault through the intake.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import post_store, settings_service


def available(db: Session) -> bool:
    """A link can be sent: a mail server is set up and the public address is known (the link comes from nothing
    else)."""
    return bool(post_store.configured(db) and settings_service.public_url(db))
