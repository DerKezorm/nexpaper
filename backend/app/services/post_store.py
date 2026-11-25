"""nexpaper's side of the shared post module ``vendor/nexpost``: the ``Store`` over the operator's settings
(``smtp_*`` as 1.12.0 kept them, the password sealed as before) and the table ``mail_outbox``, and the worker that
sends what waits.

System mail about an account (``services/kontenpost.py``): notices (a new sign-in, a new username, a changed address,
a reset second factor) go into the outbox with the request that causes it and out within a minute (``run_due``, from
the minute loop in ``main``). Mails somebody waits for (an invitation, a link for a new password, a confirmation link,
a link for a new password asked for on the sign-in page) go out at once, as in 1.12.0, and only when the server does
not take them do they wait in the outbox. A mail that does not go out is tried again after 1, 5, 15, 60 and 180
minutes, then given up. nexpaper's own mail (reminders, deadlines, exports, upload requests, the addresses of the
intake) goes through ``services/mailer.py`` as before.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..models import utcnow
from ..models_accounts import MailOutbox
from ..security import decrypt_secret, encrypt_secret
from ..vendor import nexpost
from ..vendor.nexpost import Letter, MailSettings, MailStatus, OutboxItem
from . import settings_service

logger = logging.getLogger("nexpaper.mail")

#: Mails that went out or were given up stay this long for the operator's page, then go.
KEEP_DAYS = 14


#: The logo in every system mail (``cid:logo``): nexpaper' mail logo, the same as in its reports.
LOGO = Path(__file__).resolve().parents[1] / "assets" / "mail-logo.png"


def _logo() -> bytes | None:
    return LOGO.read_bytes() if LOGO.is_file() else None


def configure() -> None:
    nexpost.configure(nexpost.AppConfig(app_name="nexpaper", display_name="nexpaper", logo=_logo(),
                                        logger_name="nexpaper.mail"))


configure()


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _moment(text: object) -> datetime | None:
    try:
        return _aware(datetime.fromisoformat(str(text))) if text else None
    except ValueError:
        return None


class PostStore:
    """``nexpost.Store`` over ``settings`` and ``mail_outbox``, inside one session."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def mail_settings(self) -> MailSettings:
        values = settings_service.get_all(self.db)
        return MailSettings(
            host=str(values["smtp_host"] or ""),
            port=int(values["smtp_port"] or 587),
            security=nexpost.settings.security_of(str(values["smtp_security"] or "starttls")),
            user=str(values["smtp_user"] or ""),
            password=decrypt_secret(str(values["smtp_password_enc"] or "")),
            sender=str(values["smtp_from"] or ""),
            sender_name=str(values.get("smtp_sender_name") or ""),
        )

    def save_mail_settings(self, settings: MailSettings, password: str | None) -> None:
        changes: dict[str, object] = {
            "smtp_host": settings.host,
            "smtp_port": settings.port,
            "smtp_security": settings.security,
            "smtp_user": settings.user,
            "smtp_from": settings.sender,
            "smtp_sender_name": settings.sender_name,
        }
        if password is not None:
            changes["smtp_password_enc"] = encrypt_secret(password) if password else ""
        settings_service.save(self.db, changes, commit=False)

    def add_to_outbox(self, letter: Letter, now: datetime) -> int:
        row = MailOutbox(letter=json.dumps(letter.__dict__), created_at=now, next_at=now)
        self.db.add(row)
        self.db.flush()
        return row.id

    @staticmethod
    def _item(row: MailOutbox) -> OutboxItem:
        return OutboxItem(
            id=row.id,
            letter=Letter(**json.loads(row.letter)),
            created_at=_aware(row.created_at) or utcnow(),
            next_at=_aware(row.next_at) or utcnow(),
            attempts=row.attempts,
            error=row.error,
        )

    def due(self, now: datetime, limit: int) -> list[OutboxItem]:
        rows = self.db.scalars(
            select(MailOutbox)
            .where(MailOutbox.sent_at.is_(None), MailOutbox.next_at.is_not(None), MailOutbox.next_at <= now)
            .order_by(MailOutbox.created_at, MailOutbox.id)
            .limit(limit)
        )
        return [self._item(row) for row in rows]

    def claim(self, item_id: int | str, now: datetime, until: datetime) -> bool:
        result = self.db.execute(
            update(MailOutbox)
            .where(MailOutbox.id == int(item_id), MailOutbox.sent_at.is_(None), MailOutbox.next_at.is_not(None),
                   MailOutbox.next_at <= now)
            .values(next_at=until)
        )
        return int(result.rowcount or 0) == 1

    def mark_sent(self, item_id: int | str) -> None:
        self.db.execute(update(MailOutbox).where(MailOutbox.id == int(item_id)).values(sent_at=utcnow(), next_at=None))

    def mark_failed(self, item_id: int | str, attempts: int, next_at: datetime | None, error: str) -> None:
        self.db.execute(
            update(MailOutbox).where(MailOutbox.id == int(item_id))
            .values(attempts=attempts, next_at=next_at, error=error[:500])
        )

    def note_result(self, status: MailStatus) -> None:
        settings_service.save(self.db, {
            "mail_last_ok_at": status.last_ok_at.isoformat() if status.last_ok_at else "",
            "mail_last_error": status.last_error or "",
            "mail_last_error_at": status.last_error_at.isoformat() if status.last_error_at else "",
        }, commit=False)

    def mail_status(self) -> MailStatus:
        values = settings_service.get_all(self.db)
        return MailStatus(
            last_ok_at=_moment(values.get("mail_last_ok_at")),
            last_error=str(values.get("mail_last_error") or ""),
            last_error_at=_moment(values.get("mail_last_error_at")),
        )

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()


@contextmanager
def own_store() -> Iterator[PostStore]:
    from ..db import SessionLocal

    with SessionLocal() as db:
        yield PostStore(db)


def run_due() -> int:
    """What the minute loop calls: send what is due, and forget what went out or was given up long ago."""
    with own_store() as store:
        sent = nexpost.outbox.run_once(store)
        limit = utcnow() - timedelta(days=KEEP_DAYS)
        store.db.execute(delete(MailOutbox).where(MailOutbox.created_at < limit, MailOutbox.next_at.is_(None)))
        store.commit()
    return sent
