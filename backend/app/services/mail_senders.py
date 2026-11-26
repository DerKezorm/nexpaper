"""The addresses a person forwards documents from to the mailbox (My account › Upload › "Per Mail").

An address counts only once the link mailed to it was opened, as with the address of the account: otherwise anybody
could name somebody else's address and have their mail land in the own inbox. The link holds a random token of which
only the SHA-256 is kept; it works once and for 24 hours. The confirmed address of the account counts as well.

Whoever sends a mail can write any address into ``From``: the address tells who a mail is probably from, not who it is
from. That is why nothing from the mailbox is filed by itself; it waits in the inbox (``SECURITY.md``).
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .. import clock
from ..models import Account, MailSender
from ..security import hash_token
from . import emails, settings_service

logger = logging.getLogger("nexpaper.intake")

HOURS = 24
#: Addresses one account may have, confirmed or waiting.
MAX_PER_ACCOUNT = 20
#: Links one account may ask for in a while.
PER_ACCOUNT = 5


def key_of(address: str) -> str:
    return address.strip().casefold()


def of_account(db: Session, account_id: int) -> list[MailSender]:
    """The person's addresses; one whose link ran out unopened is not among them (and goes)."""
    now = clock.now()
    db.execute(delete(MailSender).where(MailSender.user_id == account_id, MailSender.confirmed_at.is_(None),
                                        MailSender.expires_at < now))
    db.commit()
    return list(db.scalars(select(MailSender).where(MailSender.user_id == account_id).order_by(MailSender.id)))


def count(db: Session, account_id: int) -> int:
    return int(db.scalar(select(func.count()).select_from(MailSender).where(MailSender.user_id == account_id)) or 0)


def start(db: Session, account: Account, address: str) -> tuple[MailSender, str]:
    """A link for the address (a new one replaces a waiting one of the same address). The token is returned once."""
    token = secrets.token_urlsafe(32)
    key = key_of(address)
    row = db.scalar(select(MailSender).where(MailSender.user_id == account.id, MailSender.address_key == key))
    if row is None:
        row = MailSender(user_id=account.id, address=address.strip(), address_key=key, created_at=clock.now())
        db.add(row)
    row.token_hash = hash_token(token)
    row.expires_at = clock.now() + timedelta(hours=HOURS)
    db.commit()
    logger.info("Sender address link made name=%s", account.name)
    return row, token


def link_to(db: Session, token: str) -> str:
    base = settings_service.public_url(db)
    return f"{base}/absender/{token}" if base else ""


#: The letter "confirm the address" in German, English and French: subject, the words with ``{target}`` (the mailbox
#: of the intake, or nothing), the line before the link, the last words (``{hours}``).
CONFIRM_WORDS = {
    "de": ("Bestätige die Adresse, von der du Dokumente weiterleitest",
           "Das nexpaper-Konto {name} möchte von dieser Adresse aus Dokumente{target} weiterleiten.", " an {mailbox}",
           "Öffne diesen Link, um es zu bestätigen:",
           ("Der Link gilt einmal und {hours} Stunden lang. Hast du ihn nicht angefordert, beachte diese Mail nicht: "
            "Es ändert sich nichts.")),
    "en": ("Confirm the address you forward documents from",
           "The nexpaper account {name} wants to forward documents{target} from this address.", " to {mailbox}",
           "Open this link to confirm it:",
           "The link works once and for {hours} hours. If you did not ask for it, ignore this mail: nothing changes."),
    "fr": ("Confirmez l'adresse depuis laquelle vous transférez des documents",
           "Le compte nexpaper {name} souhaite transférer des documents{target} depuis cette adresse.", " à {mailbox}",
           "Ouvrez ce lien pour le confirmer :",
           ("Le lien fonctionne une seule fois et pendant {hours} heures. Si vous ne l'avez pas demandé, ignorez ce "
            "message : rien ne change.")),
}


def confirm_letter(to: str, link: str, *, name: str, hours: int, mailbox: str, language: str = "") -> Any:
    """The link that makes an address count as one the account forwards documents from, with nexpaper's logo, in
    ``language`` (the account's: German, English or French; else English). ``nexpost.MailError`` for an address the
    module refuses."""
    from . import post_store

    language = language if language in CONFIRM_WORDS else "en"
    subject, words, target, before, after = CONFIRM_WORDS[language]
    # Names go in as text in one pass, never by ``str.format`` on what a person chose (a name "{target}" stays a name).
    values = {"name": name, "target": target.replace("{mailbox}", mailbox) if mailbox else "", "hours": str(hours)}

    def fill(template: str) -> str:
        return re.sub(r"\{(name|target|hours)\}", lambda found: values[found.group(1)], template)

    text = f"{fill(words)}\n\n{before}\n{link}\n\n{fill(after)}\n"
    return post_store.plain(to, kind="sender_confirm", subject=subject, text=text, language=language, link=link)


def available(db: Session) -> bool:
    return emails.available(db)


def find(db: Session, token: str) -> tuple[MailSender, Account] | None:
    row = db.scalar(select(MailSender).where(MailSender.token_hash == hash_token(token)))
    if row is None or row.confirmed_at is not None or row.expires_at is None or row.expires_at <= clock.now():
        return None
    account = db.get(Account, row.user_id)
    if account is None or account.blocked_at is not None:
        return None
    return row, account


def confirm(db: Session, token: str) -> tuple[MailSender, Account] | None:
    """The address counts from now on; the link is used up in the same write (of two presses exactly one counts)."""
    found = find(db, token)
    if found is None:
        return None
    row, account = found
    done = db.execute(update(MailSender).where(MailSender.id == row.id, MailSender.confirmed_at.is_(None),
                                               MailSender.token_hash == row.token_hash)
                      .values(confirmed_at=clock.now(), token_hash="", expires_at=None))
    if int(done.rowcount or 0) != 1:  # type: ignore[attr-defined]
        db.rollback()
        return None
    db.commit()
    db.refresh(row)
    logger.info("Sender address confirmed name=%s", account.name)
    return row, account


def owners(db: Session, address: str, *, shut_out: bool = False) -> set[int]:
    """The accounts (not blocked) for which this address counts: a confirmed sender address, or the confirmed address
    of the account. ``shut_out``: the blocked and deleted ones instead (not yet removed for good), whose post waits
    for them (``intake_mail.held_for``)."""
    key = key_of(address)
    if not key:
        return set()
    out = Account.blocked_at.is_not(None) if shut_out else Account.blocked_at.is_(None)
    found = set(db.scalars(select(MailSender.user_id).join(Account, Account.id == MailSender.user_id)
                           .where(MailSender.address_key == key, MailSender.confirmed_at.is_not(None), out)))
    for account_id, email in db.execute(select(Account.id, Account.email).where(
            Account.email_confirmed_at.is_not(None), out, Account.email != "")):
        if key_of(email) == key:
            found.add(int(account_id))
    return found
