"""What is left of nexpaper's own mailer since the shared post module 1.1.0: one name, no SMTP.

Every system mail goes through the module (``vendor/nexpost``: the letters, their sender, logo and language, the
connection to the server, the outbox, the result on the operator's page; ``services/kontenpost.py``). This file keeps
the name the test "Bestand" knows and catches the mail of "Forgot your password?" at (it cannot change outside its
block ``AFTER_THE_CHANGE``, Bauplan E47):

- ``send_reset(db, to, link, *, name, hours)``: the link for a new password, at once, through
  ``kontenpost.send_reset``. The route of "Forgot your password?" calls it here, so that a stand-in set here takes it.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import kontenpost


def send_reset(db: Session, to: str, link: str, *, name: str, hours: int) -> None:
    """The link for a new password, at once, as the shared post module writes it (``kontenpost.send_reset``)."""
    kontenpost.send_reset(db, to, link, name=name, hours=hours)
