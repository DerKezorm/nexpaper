"""Invitation mail through the operator's SMTP server.

Off until the operator enters a server: the link to copy is always enough. The mail
is English like everything nexpaper sends out; it names who invites and carries the link. The notice of a
new sign-in (``services/notices.py``) goes the same way.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from sqlalchemy.orm import Session

from ..security import decrypt_secret
from . import settings_service

logger = logging.getLogger("nexpaper.mail")

TIMEOUT = 15
SECURITY = ("starttls", "tls", "none")


class MailError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def configured(db: Session) -> bool:
    values = settings_service.get_all(db)
    return bool(values["smtp_host"] and values["smtp_from"])


def _send(db: Session, message: EmailMessage) -> None:
    values = settings_service.get_all(db)
    if not (values["smtp_host"] and values["smtp_from"]):
        raise MailError("mail_off", "No mail server is set up.")
    host = str(values["smtp_host"])
    port = int(values["smtp_port"])
    security = str(values["smtp_security"])
    message["From"] = str(values["smtp_from"])
    message["Message-ID"] = make_msgid(domain=str(values["smtp_from"]).rpartition("@")[2] or None)
    # smtplib adds no Date, and some providers (iCloud, Outlook, Gmail) drop a mail without one in silence.
    if "Date" not in message:
        message["Date"] = formatdate(localtime=True)
    context = ssl.create_default_context()
    try:
        if security == "tls":
            server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=TIMEOUT)
        with server:
            if security == "starttls":
                server.starttls(context=context)
            user = str(values["smtp_user"])
            if user:
                server.login(user, decrypt_secret(str(values["smtp_password_enc"])))
            server.send_message(message)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        # The reason goes to the log by its kind only: an SMTP answer can quote the address or the credentials.
        logger.warning("Mail not sent host=%s reason=%s", host, type(exc).__name__)
        raise MailError("mail_failed", "The mail server did not take the mail.") from exc
    logger.info("Mail sent host=%s", host)


def send_invite(db: Session, to: str, link: str, *, by: str, until: str = "") -> None:
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = f"{by} invites you to nexpaper"
    runs = f"until {until}" if until else "for a few days"
    message.set_content(
        f"{by} invites you to nexpaper, a place for the household's papers.\n\n"
        f"Open this link to accept:\n{link}\n\n"
        f"The link works once, {runs}. If you did not expect this mail, ignore it.\n"
    )
    _send(db, message)


def send_reset(db: Session, to: str, link: str, *, name: str, hours: int) -> None:
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = "Set a new password for nexpaper"
    message.set_content(
        f"A link was asked for to set a new password for your nexpaper account {name}.\n\n"
        f"Open it to choose the new password:\n{link}\n\n"
        f"The link works once and for {hours} hours. If you did not ask for it, ignore this mail: your password "
        "stays as it is.\n"
    )
    _send(db, message)


def send_confirm(db: Session, to: str, link: str, *, name: str, hours: int) -> None:
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = "Confirm your mail address for nexpaper"
    message.set_content(
        f"This address was given for the nexpaper account {name}.\n\n"
        f"Open this link to confirm it:\n{link}\n\n"
        f"The link works once and for {hours} hours. If you did not ask for it, ignore this mail: nothing "
        "changes.\n"
    )
    _send(db, message)


def send_changed(db: Session, to: str, *, name: str, new_hint: str) -> None:
    """Tells the old address that the account has a new one now (the old one may be the only sign of a takeover)."""
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = "The mail address of your nexpaper account changed"
    message.set_content(
        f"The mail address of your nexpaper account {name} is now {new_hint}. Notices and links to set a new password "
        "go there from now on.\n\n"
        "If this was you, there is nothing to do. If it was not, sign in, change your password and tell the operator.\n"
    )
    _send(db, message)


def send_removed(db: Session, to: str, *, name: str) -> None:
    """Tells the old address that the account has no mail address any more."""
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = "The mail address of your nexpaper account was removed"
    message.set_content(
        f"The mail address of your nexpaper account {name} was removed. Notices and links to set a new password will "
        "not be mailed any more.\n\n"
        "If this was you, there is nothing to do. If it was not, sign in, change your password and tell the operator.\n"
    )
    _send(db, message)


def send_test(db: Session, to: str) -> None:
    message = EmailMessage()
    message["To"] = formataddr(("", to))
    message["Subject"] = "nexpaper test mail"
    message.set_content("The mail server in nexpaper works.\n")
    _send(db, message)


def send_message(db: Session, message: EmailMessage) -> None:
    """A mail written elsewhere (the notice of a new sign-in), through the same server."""
    _send(db, message)


def send_sender_confirm(db: Session, to: str, link: str, *, name: str, hours: int, mailbox: str) -> None:
    """The link that makes an address count as one the account forwards documents from (``mail_senders.py``)."""
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = "Confirm the address you forward documents from"
    target = f" to {mailbox}" if mailbox else ""
    message.set_content(
        f"The nexpaper account {name} wants to forward documents{target} from this address.\n\n"
        f"Open this link to confirm it:\n{link}\n\n"
        f"The link works once and for {hours} hours. If you did not ask for it, ignore this mail: nothing "
        "changes.\n"
    )
    _send(db, message)
