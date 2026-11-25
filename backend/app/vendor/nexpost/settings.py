"""The mail server's settings as the operator types them: checked, the older values understood, a warning where the
password would cross the network in the clear.

Older versions wrote the encryption as ``ssl`` / ``keine`` (one app) or ``tls`` / ``none`` (the others); both are
read. A sender name left empty means the app's name. The password field is never shown: empty keeps the stored one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import config
from .errors import MailError
from .letters import check_address, one_line
from .model import NONE, SECURITY, STARTTLS, TLS, MailSettings, MailStatus, Store

#: Values of older versions.
OLDER_SECURITY = {"ssl": TLS, "keine": NONE, "starttls": STARTTLS, "tls": TLS, "none": NONE, "": STARTTLS}
#: ``Checked.warnings``.
WARNING_UNENCRYPTED = "unencrypted"


def security_of(raw: str) -> str:
    value = OLDER_SECURITY.get((raw or "").strip().lower())
    if value is None:
        raise MailError("mail_settings_invalid", "Encryption must be starttls, tls or none.")
    return value


@dataclass(frozen=True)
class Checked:
    settings: MailSettings
    warnings: list[str] = field(default_factory=list)


def check(
    *,
    host: str,
    port: int | str,
    security: str,
    user: str = "",
    sender: str = "",
    sender_name: str = "",
    ca_file: str = "",
    password_given: bool = False,
) -> Checked:
    """What the operator typed, checked. An empty server turns mail off (allowed). ``password_given``: a password is
    stored or comes with this request (for the warning)."""
    name = one_line(host, 253)
    try:
        number = int(port)
    except (TypeError, ValueError) as error:
        raise MailError("mail_settings_invalid", "The port must be a number.") from error
    if not 1 <= number <= 65535:
        raise MailError("mail_settings_invalid", "The port must be between 1 and 65535.")
    mode = security_of(security)
    address = check_address(sender) if sender.strip() else ""
    if name and not address:
        raise MailError("mail_settings_invalid", "A mail server needs a sender address.")
    settings = MailSettings(
        host=name,
        port=number,
        security=mode,
        user=one_line(user, 254),
        sender=address,
        sender_name=one_line(sender_name, 120),
        ca_file=one_line(ca_file, 400),
    )
    warnings = [WARNING_UNENCRYPTED] if name and mode == NONE and (user.strip() or password_given) else []
    return Checked(settings, warnings)


def save(store: Store, checked: Checked, password: str | None) -> None:
    """Store what ``check`` gave; ``password`` None keeps the stored one."""
    store.save_mail_settings(checked.settings, password)
    store.commit()


def view(store: Store) -> dict[str, object]:
    """What the settings page shows: never the password, only whether one is stored; the warning; the last result."""
    settings = store.mail_settings()
    status: MailStatus = store.mail_status()
    return {
        "host": settings.host,
        "port": settings.port,
        "security": settings.security,
        "user": settings.user,
        "password_set": bool(settings.password),
        "sender": settings.sender,
        "sender_name": settings.sender_name,
        "sender_name_default": config.current().shown_name,
        "ca_file": settings.ca_file,
        "configured": settings.configured,
        "warnings": [WARNING_UNENCRYPTED]
        if settings.configured and settings.security == NONE and (settings.user or settings.password)
        else [],
        "last_ok_at": status.last_ok_at.isoformat() if status.last_ok_at else None,
        "last_error": status.last_error,
        "last_error_at": status.last_error_at.isoformat() if status.last_error_at else None,
    }


__all__ = ["SECURITY", "WARNING_UNENCRYPTED", "Checked", "check", "save", "security_of", "view"]
