"""nexpaper's side of the shared post module ``vendor/nexpost`` (bauplaene/post 1.1.0): the ``Store`` over the
operator's settings (``smtp_*`` as 1.12.0 kept them, the password sealed as before) and the table ``mail_outbox``, the
worker that sends what waits, and the few helpers every sender of nexpaper uses. **Every** system mail goes through
the module; nexpaper's own mailer is gone.

- Mails about an account (``services/kontenpost.py``) and nexpaper's own letters (reminders, deadlines, the weekly
  mail, exports, notices to the operators, the confirmation of a sender address) are written in the language of the
  account with nexpaper's logo.
- What somebody waits for in the request (an invitation, a link for a new password, a confirmation link, the test of
  the reminders, the confirmation of a sender) goes out at once (``send_now``, ``nexpost.outbox.deliver_now``); the
  rest goes into the outbox (``queue``, ``nexpost.outbox.queue``), which is nudged right after the commit and sent
  again after 1, 5, 15, 60 and 180 minutes when the server does not take it, then given up.
- The routes of before answer with the codes their clients know (``app_code``: ``mail_off``, ``invalid_email``,
  ``mail_failed``); the page Server › Mail (``/api/v1/server/mail``) answers with the module's.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, event, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Account, utcnow
from ..models_accounts import MailOutbox
from ..security import decrypt_secret, encrypt_secret
from ..vendor import nexpost
from ..vendor.nexpost import Letter, MailSettings, MailStatus, OutboxItem, Recipient
from . import settings_service

logger = logging.getLogger("nexpaper.mail")

#: Mails that went out or were given up stay this long for the operator's page, then go.
KEEP_DAYS = 14


#: The logo in every system mail (``cid:logo``): nexpaper' mail logo, the same as in its reports.
LOGO = Path(__file__).resolve().parents[1] / "assets" / "mail-logo.png"


def _logo() -> bytes | None:
    return LOGO.read_bytes() if LOGO.is_file() else None


def configure() -> None:
    """The module set up for nexpaper: its name, its logo (``cid:logo`` in every mail) and its round of the outbox,
    which ``nexpost.outbox.queue`` nudges right after the commit (not where nexpaper runs without background work: the
    tests; there a mail waits for the minute loop or a test's own ``run_due``)."""
    from ..config import get_settings

    runner = None if get_settings().disable_background else run_due
    nexpost.configure(nexpost.AppConfig(app_name="nexpaper", display_name="nexpaper", logo=_logo(),
                                        logger_name="nexpaper.mail", outbox_runner=runner))


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

    def _keyed(self, key: str) -> int | None:
        return self.db.scalar(select(MailOutbox.id).where(MailOutbox.letter_key == key))

    def add_to_outbox(self, letter: Letter, now: datetime) -> int:
        """The whole letter as JSON (``nexpost.letter_data``: its headers too), its key beside it; a key the outbox
        holds already (waiting, sent or given up) adds nothing, the answer is that row."""
        if letter.key:
            held = self._keyed(letter.key)
            if held is not None:
                return held
        row = MailOutbox(letter=json.dumps(nexpost.model.letter_data(letter)), created_at=now, next_at=now,
                         letter_key=letter.key or None)
        try:
            # Two requests with the same key at once: the unique index lets one in, the other takes its row.
            with self.db.begin_nested():
                self.db.add(row)
                self.db.flush()
        except IntegrityError:
            held = self._keyed(letter.key) if letter.key else None
            if held is None:
                raise
            return held
        return row.id

    @staticmethod
    def _item(row: MailOutbox) -> OutboxItem:
        return OutboxItem(
            id=row.id,
            # Rows of before 1.1.0 hold the letter without headers and key; ``letter_from`` reads both forms.
            letter=nexpost.model.letter_from(json.loads(row.letter)),
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

    # Since post 1.1.0.

    def waiting(self) -> int:
        """Mails neither sent nor given up."""
        return int(self.db.scalar(select(func.count()).select_from(MailOutbox)
                                  .where(MailOutbox.sent_at.is_(None), MailOutbox.next_at.is_not(None))) or 0)

    def on_commit(self, callback: Callable[[], None]) -> None:
        """Once, after the next commit of this session; a rollback drops it. The listeners stay on the session
        (removing one while SQLAlchemy runs its listeners breaks the commit); what they call waits in the session's
        ``info``."""
        pending: list[Callable[[], None]] = self.db.info.setdefault("nexpost_after_commit", [])
        if not self.db.info.get("nexpost_listening"):
            event.listen(self.db, "after_commit", _committed)
            event.listen(self.db, "after_soft_rollback", _rolled_back)
            self.db.info["nexpost_listening"] = True
        pending.append(callback)

    def recipient(self, account: object) -> Recipient | None:
        """Where nexpaper mails an account: its address once confirmed, in its language (else the first operator's,
        else English), with its name and the time zone its browser reported."""
        from . import kontenpost, timezones

        row = account if isinstance(account, Account) else (
            self.db.get(Account, int(account)) if str(account).isdigit() else None)  # type: ignore[call-overload]
        if row is None or row.blocked_at is not None or not (row.email or "").strip() or row.email_confirmed_at is None:
            return None
        zone = timezones.zone_of(row)
        return Recipient(row.email.strip(), kontenpost.language_for(self.db, row), row.display_name or row.name,
                         getattr(zone, "key", "") or "")


def _committed(session: Session) -> None:
    pending = session.info.get("nexpost_after_commit") or []
    session.info["nexpost_after_commit"] = []
    for callback in pending:
        callback()


def _rolled_back(session: Session, previous: Any) -> None:
    if not getattr(previous, "nested", False):  # a savepoint's rollback leaves the transaction alive
        session.info["nexpost_after_commit"] = []


# --- What every sender of nexpaper uses -----------------------------------------------------------------------------


def configured(db: Session) -> bool:
    """A mail server and a sender: mail can go out (what ``mailer.configured`` said before)."""
    return PostStore(db).mail_settings().configured


def store_of(db: Session) -> PostStore:
    return PostStore(db)


#: The codes nexpaper's routes of before answered for a mail that did not go (their clients know these three).
APP_CODES = {"mail_off": "mail_off", "mail_address_invalid": "invalid_email"}


def app_code(problem: nexpost.MailError) -> str:
    """The code a route of before answers for ``problem``: ``mail_off``, ``invalid_email``, else ``mail_failed``."""
    return APP_CODES.get(problem.code, "mail_failed")


def send_now(db: Session, letter: Letter) -> None:
    """At once through the mail server, the result on the operator's page (``nexpost.outbox.deliver_now``, which
    commits). ``nexpost.MailError`` with the reason; the reason goes to the log by its code only (an answer of the
    server can quote the address or the credentials)."""
    store = PostStore(db)
    host = store.mail_settings().host
    try:
        nexpost.outbox.deliver_now(store, letter)
    except nexpost.MailError as problem:
        logger.warning("Mail not sent host=%s code=%s kind=%s", host, problem.code, letter.kind or "-")
        raise
    logger.info("Mail sent host=%s kind=%s", host, letter.kind or "-")


def test_mail(db: Session, to: str, *, language: str = "") -> None:
    """The operator's test mail of the shared post module (nexpaper's logo, the same in every app), at once, in
    ``language`` (else the operator's); ``nexpost.MailError`` with the reason, its code in the log."""
    from . import kontenpost

    store = PostStore(db)
    host = store.mail_settings().host
    try:
        nexpost.outbox.test_mail(store, to, language=language or kontenpost.language_for(db, None))
    except nexpost.MailError as problem:
        logger.warning("Mail not sent host=%s code=%s kind=test", host, problem.code)
        raise
    logger.info("Mail sent host=%s kind=test", host)


def plain(to: str | Recipient, *, kind: str, subject: str, text: str, language: str = "", link: str = "",
          key: str = "") -> Letter:
    """A letter of nexpaper written as plain text (its words as before the module): the text goes out as it is, and the
    HTML beside it carries the same paragraphs in the module's frame with nexpaper's logo (a link as its button).
    ``nexpost.MailError`` ``mail_address_invalid`` for an address the module refuses."""
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip() and (not link or part.strip() != link)]
    return nexpost.app_letters.write(to, kind=kind, subject=subject, language=language, paragraphs=paragraphs,
                                     text=text, link=link, key=key)


def queue(db: Session, letter: Letter) -> None:
    """Into the outbox and committed with what the session holds; out right after (nudged) or within a minute."""
    nexpost.outbox.queue(PostStore(db), letter)
    db.commit()


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


configure()
