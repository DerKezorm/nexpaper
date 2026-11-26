"""A message to a person in the background: a push to their devices and, with a mail server and a confirmed address, a
mail. The texts come in German, English and French and are chosen per device (push) and per account (mail); the
message names numbers and where to look, never the contents of a document.

Used for the notices that are about the whole server and not about one request: the check of the files found a
problem, the import from Paperless is done. (The notice of a ready export and of a new sign-in have their own words and
stay with their modules.)

The mail speaks the language of its recipient (``Store.recipient``: the account's, else the first operator's, else
English), in German, English or French (Bauplan E26, E57); a notice without words in that language mails in English.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select

from ..models import OPERATOR, Account
from . import notices

logger = logging.getLogger("nexpaper.tell")


@dataclass(frozen=True)
class Notice:
    #: ``{"de": (title, body), "en": (title, body)}``, and ``"fr"`` where a notice has French words (else English).
    texts: dict[str, tuple[str, str]]
    #: A path of nexpaper that a tap opens.
    url: str
    #: The same tag replaces an earlier message on the device.
    tag: str
    #: The mail in English; ``{where}`` is the full address of the page (or its name without a public address).
    mail_subject: str
    mail_body: str
    #: The mail in the other languages: ``{"de": (subject, body), "fr": (subject, body)}``, the body ending in
    #: ``{where}`` as the English one.
    mails: dict[str, tuple[str, str]] = field(default_factory=dict)


def operators() -> list[int]:
    from ..db import SessionLocal

    with SessionLocal() as db:
        return list(db.scalars(select(Account.id).where(Account.role == OPERATOR, Account.blocked_at.is_(None))))


def person(account_id: int, notice: Notice) -> None:
    """Tells one person, in the background."""
    notices.later(_send, account_id, notice)


def operator(notice: Notice) -> None:
    """Tells every operator, in the background."""
    for account_id in operators():
        person(account_id, notice)


def words(notice: Notice, language: str) -> tuple[str, str]:
    """Title and body in ``language``: French where the notice has it, else German or English as before."""
    if (language or "").split("-")[0].lower() == "fr" and "fr" in notice.texts:
        return notice.texts["fr"]
    return notice.texts[notices.language_of(language)]


def mail_words(notice: Notice, language: str) -> tuple[str, str, str]:
    """Subject, body and language of the mail in ``language`` (``de``, ``en``, ``fr``): the notice's words in it, else
    the English ones."""
    short = (language or "").split("-")[0].lower()
    if short in notice.mails:
        subject, body = notice.mails[short]
        return subject, body, short
    return notice.mail_subject, notice.mail_body, "en"


def _send(account_id: int, notice: Notice) -> None:
    from ..db import SessionLocal
    from ..vendor import nexpost
    from . import kontenpost, post_store, push, settings_service

    with SessionLocal() as db:
        account = db.get(Account, account_id)
        if account is None or account.blocked_at is not None:
            return
        account_language = account.language or ""
        mail_to = account.email if account.email and account.email_confirmed_at and post_store.configured(db) else ""
        base = settings_service.public_url(db)
        mail_language = kontenpost.language_for(db, account)

    def message_for(lang: str) -> push.Message:
        title, body = words(notice, lang or account_language)
        return push.Message(title=title, body=body, url=notice.url, desk=notice.url, tag=notice.tag)

    push.send_to_person(account_id, message_for)
    if not mail_to:
        return
    # ``{where}`` is put in as text, never by ``str.format``, and only its last place (every body ends with it): a body
    # holds names people chose (an upload request "Firma {GmbH}", a provider's label, a display name), and braces there
    # must neither break the mail nor be read as a format (``{where:>99999999}`` would make a mail of 100 MB), nor a
    # name "{where}" become an address.
    subject, body, language = mail_words(notice, mail_language)
    head, mark, tail = body.rpartition("{where}")
    where = f"{base}{notice.url}" if base else "nexpaper"
    # In the recipient's language, through the outbox of the shared post module with nexpaper's logo: out at once
    # (nudged), else again after 1, 5, 15 minutes …
    with SessionLocal() as db:
        try:
            post_store.queue(db, post_store.plain(mail_to, kind="notice", subject=subject,
                                                  text=head + where + tail if mark else body, language=language))
        except (nexpost.MailError, ValueError):  # an address the module refuses: the notice is pushed all the same
            logger.warning("A notice was not mailed tag=%s", notice.tag)
