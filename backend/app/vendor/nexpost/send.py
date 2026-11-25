"""Sending one letter through the mail server, and what its refusals mean.

``smtplib``, synchronous, 15 seconds for every step. STARTTLS or TLS with the system's certificates, or the app's own
file of trusted certificates (``MailSettings.ca_file``); without encryption only where the operator chose it (the page
warns). The ``From`` is the sender name and address (``formataddr``), every header one line. The mail is text and
HTML; the logo rides along as ``cid:logo``.
"""

from __future__ import annotations

import re
import smtplib
import socket
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime, formataddr, make_msgid

from . import config
from .common import log
from .errors import MailError
from .letters import check_address, one_line
from .model import NONE, TLS, Letter, MailSettings

TIMEOUT = 15
#: An address in the server's sentence (``<kim@example.org>: Recipient address rejected``): never kept.
_ADDRESS_IN_TEXT = re.compile(r"<?[^\s<>@]+@[^\s<>@]+>?")


def message(settings: MailSettings, letter: Letter) -> EmailMessage:
    """The mail as it goes out."""
    cfg = config.current()
    sender = check_address(settings.sender)
    mail = EmailMessage()
    mail["From"] = formataddr((one_line(settings.sender_name or cfg.shown_name, 120), sender))
    mail["To"] = check_address(letter.to)
    mail["Subject"] = one_line(letter.subject)
    # The server's own time zone (``+0100``), not ``-0000`` ("zone unknown"), since 0.1.2.
    mail["Date"] = format_datetime(datetime.now().astimezone())
    mail["Message-ID"] = make_msgid(domain=sender.rpartition("@")[2] or None)
    mail["Auto-Submitted"] = "auto-generated"
    mail.set_content(letter.text)
    if letter.html:
        mail.add_alternative(letter.html, subtype="html")
        if cfg.logo:
            html_part = mail.get_payload()[-1]
            html_part.add_related(cfg.logo, maintype="image", subtype="png", cid="<logo>")
    return mail


def _context(settings: MailSettings) -> ssl.SSLContext:
    if settings.ca_file:
        return ssl.create_default_context(cafile=settings.ca_file)
    return ssl.create_default_context()


def _connect(settings: MailSettings) -> smtplib.SMTP:
    factory = config.smtp_factory()
    if factory is not None:
        return factory(settings, TIMEOUT, None)  # type: ignore[no-any-return]
    if settings.security == TLS:
        return smtplib.SMTP_SSL(settings.host, settings.port, timeout=TIMEOUT, context=_context(settings))
    server = smtplib.SMTP(settings.host, settings.port, timeout=TIMEOUT)
    if settings.security != NONE:
        try:
            server.starttls(context=_context(settings))
        except BaseException:
            server.close()
            raise
    return server


def _sentence(code: object, said: object) -> str:
    """The server's reply in one line, without any address in it (it ends up on the operator's page)."""
    words = said.decode("utf-8", "replace") if isinstance(said, bytes) else str(said)
    return one_line(f"{code} {_ADDRESS_IN_TEXT.sub('<address>', words)}", 300)


def _server_sentence(error: smtplib.SMTPResponseException) -> str:
    return _sentence(error.smtp_code, error.smtp_error)


def _login(server: smtplib.SMTP, settings: MailSettings) -> None:
    try:
        server.login(settings.user, settings.password)
    except (UnicodeError, ValueError) as error:
        # smtplib sends the login in ASCII: a password with an umlaut never reaches the server.
        raise MailError(
            "mail_auth_refused", "The user or password holds characters the mail server login cannot carry."
        ) from error


def deliver(settings: MailSettings, letter: Letter) -> None:
    """Send one letter now; ``MailError`` with a fixed code when it does not go out."""
    if not settings.configured:
        raise MailError("mail_off", "No mail server is set up.")
    mail = message(settings, letter)
    server = None
    try:
        server = _connect(settings)
        if settings.user:
            _login(server, settings)
        server.send_message(mail)
    except MailError:
        raise
    except smtplib.SMTPAuthenticationError as error:
        raise MailError(
            "mail_auth_refused",
            "The mail server refused the user or password.",
            detail=_server_sentence(error),
            smtp_code=error.smtp_code,
        ) from error
    except smtplib.SMTPRecipientsRefused as error:
        sentence, code = "", 0
        for code, said in error.recipients.values():
            sentence = _sentence(code, said)
        raise MailError(
            "mail_recipient_refused",
            "The mail server refused the recipient.",
            detail=sentence,
            smtp_code=int(code or 0),
        ) from error
    except smtplib.SMTPSenderRefused as error:
        raise MailError(
            "mail_sender_refused",
            "The mail server refused the sender.",
            detail=_server_sentence(error),
            smtp_code=error.smtp_code,
        ) from error
    except smtplib.SMTPResponseException as error:
        raise MailError(
            "mail_refused",
            "The mail server refused the mail.",
            detail=_server_sentence(error),
            smtp_code=error.smtp_code,
        ) from error
    except ssl.SSLError as error:
        raise MailError("mail_tls_failed", "The encrypted connection to the mail server failed.") from error
    except (
        TimeoutError,
        socket.gaierror,
        ConnectionError,
        smtplib.SMTPConnectError,
        smtplib.SMTPServerDisconnected,
    ) as error:
        raise MailError("mail_unreachable", "The mail server cannot be reached.") from error
    except (smtplib.SMTPException, OSError) as error:
        raise MailError("mail_failed", f"The mail did not go out ({error.__class__.__name__}).") from error
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:  # noqa: BLE001, S110 (a goodbye that fails changes nothing)
                pass
    log().info("Mail sent kind=%s", letter.kind or "-")
