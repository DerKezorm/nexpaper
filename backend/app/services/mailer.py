"""Mail through the operator's SMTP server.

Off until the operator enters a server: the link to copy is always enough. Two kinds go out here:

- The system mail about accounts (an invitation, a link for a new password, the link that confirms an address, the
  notices of a new sign-in, a new username, a changed address, a reset second factor, the test mail) is written by
  the shared post module (``vendor/nexpost``) in the language of the account (German, English, French) with the logo,
  and goes out through ``send_letter`` (``services/kontenpost.py`` decides when).
- nexpaper's own mail (reminders, deadlines, exports, upload requests, the addresses the intake takes documents
  from) stays English plain text, through ``send_message``.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from sqlalchemy.orm import Session

from ..security import decrypt_secret
from ..vendor.nexpost import Letter
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


def _language_of(db: Session, name: str = "") -> str:
    """The language of a system mail: the account's (by its name), else the first operator's, else English."""
    from . import kontenpost

    return kontenpost.language_for(db, kontenpost.account_named(db, name) if name else None)


def send_invite(db: Session, to: str, link: str, *, by: str, until: str = "", days: int = 0,
                language: str = "") -> None:
    """The invitation, at once, as the shared post module writes it (in the operator's language: the person invited
    has no account yet)."""
    from ..vendor import nexpost

    lang = language or _language_of(db)
    valid = nexpost.letters.validity(lang, days=days) if days else (until or "")
    try:
        letter = nexpost.letters.compose("invite", to, language=lang, values={"by": by, "valid": valid}, link=link)
    except nexpost.MailError as exc:
        raise MailError("invalid_email", "This is not a mail address.") from exc
    send_letter(db, letter)


def send_reset(db: Session, to: str, link: str, *, name: str, hours: int) -> None:
    """The link for a new password, at once (``resets.forgot_in_background`` hears a failure and drops the link), as
    the shared post module writes it, in the language of the account ``name``."""
    from ..vendor import nexkonten, nexpost

    mail = nexkonten.Mail(kind=nexkonten.MAIL_RESET, to=to, account_id=0, username=name, display_name="",
                          token="", hours=hours)
    try:
        letter = nexpost.letters.from_account_mail(mail, language=_language_of(db, name), link=link)
    except (nexpost.MailError, ValueError) as exc:
        raise MailError("invalid_email", "This is not a mail address.") from exc
    send_letter(db, letter)


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


def send_test(db: Session, to: str, language: str = "") -> None:
    """The operator's test mail, at once, as the shared post module writes it."""
    from ..vendor import nexpost

    try:
        letter = nexpost.letters.compose("test", to, language=language or _language_of(db), values={})
    except nexpost.MailError as exc:
        raise MailError("invalid_email", "This is not a mail address.") from exc
    send_letter(db, letter)


def send_letter(db: Session, letter: Letter) -> None:
    """A letter of the shared post module, at once: its sender name, its logo, its plain text beside the HTML.
    ``MailError`` with ``mail_off``, ``invalid_email`` or ``mail_failed``; the operator's page shows the last result."""
    from ..vendor import nexpost
    from .post_store import PostStore

    settings = PostStore(db).mail_settings()
    if not settings.configured:
        raise MailError("mail_off", "No mail server is set up.")
    try:
        nexpost.send.deliver(settings, letter)
    except nexpost.MailError as exc:
        # The reason goes to the log by its code only: an SMTP answer can quote the address or the credentials.
        logger.warning("Mail not sent host=%s code=%s", settings.host, exc.code)
        _note(db, ok=False, code=exc.code)
        if exc.code == "mail_address_invalid":
            raise MailError("invalid_email", "This is not a mail address.") from exc
        raise MailError("mail_failed", "The mail server did not take the mail.") from exc
    _note(db, ok=True)
    logger.info("Mail sent host=%s", settings.host)


def _note(db: Session, *, ok: bool, code: str = "") -> None:
    """The last result for the operator's page (``mail_last_*``); never stops a mail."""
    from ..models import utcnow

    now = utcnow().isoformat()
    try:
        if ok:
            settings_service.save(db, {"mail_last_ok_at": now})
        else:
            settings_service.save(db, {"mail_last_error": code, "mail_last_error_at": now})
    except Exception:  # noqa: BLE001 (a note about a mail never breaks the mail)
        db.rollback()


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
