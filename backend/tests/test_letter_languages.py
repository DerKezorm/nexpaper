"""nexpaper's own letters speak the language of their recipient (Bauplan E26, E57): the notices to the operators and to
a person (a failed backup or restore, the check of the files, a removed sign-in link, a full storage, an upload request,
the import from Paperless), the mail of an export and the link that confirms a forwarding address, each in German,
English and French. The language is the one ``Store.recipient`` names (the account's, else the first operator's, else
English); a notice without words in a language mails in English as before."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app import clock
from app.db import SessionLocal
from app.models import Account, Export
from app.routers import oidc
from app.services import (
    backup_hooks,
    exports,
    filecheck,
    mail_senders,
    paperless,
    push,
    quota,
    tell,
    upload_requests,
)
from app.vendor.nexpost import testing

from .conftest import make_account
from .test_emails import PUBLIC, mail_on

LANGUAGES = ("de", "en", "fr")


def _filecheck() -> tell.Notice:
    caught: list[tell.Notice] = []
    keep = tell.operator
    tell.operator = caught.append  # type: ignore[assignment]
    try:
        filecheck._tell_operators(2, 5)
    finally:
        tell.operator = keep  # type: ignore[assignment]
    (notice,) = caught
    return notice


#: Every notice of nexpaper, and a word its mail says in each language (subject, body).
NOTICES: dict[str, tuple[Callable[[], tell.Notice], dict[str, tuple[str, str]]]] = {
    "backup_failed": (backup_hooks.backup_failed_notice, {
        "de": ("geplante Sicherung gescheitert", "versucht es in einer Stunde"),
        "en": ("a scheduled backup failed", "tries again in an hour"),
        "fr": ("échec d'une sauvegarde planifiée", "réessaiera dans une heure"),
    }),
    "restore_failed": (backup_hooks.restore_failed_notice, {
        "de": ("Wiederherstellen einer Sicherung gescheitert", "mit den Daten von vorher weiter"),
        "en": ("the restore of a backup failed", "went on with the data it had"),
        "fr": ("échec de la restauration", "continue avec les données d'avant"),
    }),
    "files": (_filecheck, {
        "de": ("Dateien fehlen", "5 Dokumente mit fehlenden oder veränderten Dateien"),
        "en": ("files are missing", "5 documents with missing or changed files"),
        "fr": ("des fichiers manquent", "5 documents avec des fichiers manquants ou modifiés"),
    }),
    "unlinked": (lambda: oidc._unlinked_notice("Pocket ID", "boss"), {
        "de": ("Verknüpfung deines Kontos",
               "boss hat die Verknüpfung deines nexpaper-Kontos mit dem Anmeldeanbieter Pocket ID gelöst"),
        "en": ("a sign-in link of your account was removed",
               "boss removed the link of your nexpaper account to the sign-in provider Pocket ID"),
        "fr": ("une liaison de votre compte",
               "boss a supprimé la liaison de votre compte nexpaper avec le fournisseur de connexion Pocket ID"),
    }),
    "storage_full": (lambda: quota.notice(3), {
        "de": ("Speicher voll", "3 Dokumente warten"),
        "en": ("storage full", "3 documents are waiting"),
        "fr": ("stockage plein", "3 documents attendent"),
    }),
    "upload_request": (lambda: upload_requests.request_notice(7, "Steuer 2026", 4), {
        "de": ("Upload-Bitte", "Über deine Upload-Bitte „Steuer 2026“ sind Dateien angekommen: 4 bis jetzt."),
        "en": ("upload request", "Files arrived through your upload request \"Steuer 2026\": 4 so far."),
        "fr": ("demande de dépôt", "par votre demande de dépôt « Steuer 2026 » : 4 jusqu'ici."),
    }),
    "paperless": (lambda: paperless.import_notice(6, 2), {
        "de": ("Import aus Paperless", "6 Dokumente aus Paperless liegen jetzt in nexpaper für dich, 2 davon warten"),
        "en": ("the import from Paperless", "6 documents from Paperless are now in nexpaper for you, 2 of them"),
        "fr": ("reprise depuis Paperless", "6 documents de Paperless sont maintenant dans nexpaper pour vous, dont 2"),
    }),
}


@pytest.mark.parametrize("name", sorted(NOTICES))
def test_every_notice_mails_in_german_english_and_french(name: str) -> None:
    make, expected = NOTICES[name]
    notice = make()
    said: dict[str, tuple[str, str]] = {}
    for language in LANGUAGES:
        subject, body, spoken = tell.mail_words(notice, language)
        assert spoken == language, (name, language)
        word_subject, word_body = expected[language]
        assert word_subject.lower() in subject.lower(), (name, language, subject)
        assert word_body in body, (name, language, body)
        assert body.endswith("{where}\n"), "the place comes last, as in the English words"
        assert "–" not in subject + body and "—" not in subject + body
        said[language] = (subject, body)
    assert len({subject for subject, _ in said.values()}) == 3, "three languages, three subjects"
    assert len({body for _, body in said.values()}) == 3
    # The push speaks the three languages as well.
    assert {tell.words(notice, language)[0] for language in LANGUAGES} == {notice.texts[code][0] for code in LANGUAGES}
    assert len({notice.texts[code] for code in LANGUAGES}) == 3


def test_a_language_without_words_mails_in_english() -> None:
    notice = quota.notice(2)
    assert tell.mail_words(notice, "nl") == (notice.mail_subject, notice.mail_body, "en")
    assert tell.mail_words(notice, "de-AT")[2] == "de"


def confirmed(name: str, language: str) -> Account:
    account = make_account(name)
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None
        row.language, row.email, row.email_confirmed_at = language, f"{name}@example.com", clock.now()
        db.commit()
    return account


@pytest.mark.parametrize(("language", "subject", "words"), [
    ("de", "nexpaper: Speicher voll", "Der Speicher deines Kontos ist voll: 3 Dokumente warten"),
    ("en", "nexpaper: storage full", "The storage of your account is full: 3 documents are waiting"),
    ("fr", "nexpaper : stockage plein", "Le stockage de votre compte est plein : 3 documents attendent"),
])
def test_a_notice_reaches_the_mailbox_in_the_language_of_its_account(
    operator: Account, monkeypatch: pytest.MonkeyPatch, language: str, subject: str, words: str
) -> None:
    mail_on()
    account = confirmed("jule", language)
    monkeypatch.setattr(push, "send_to_person", lambda account_id, make_message: None)
    with testing.catch_mail() as caught:
        tell._send(account.id, quota.notice(3))
    (letter,) = caught.queued
    assert letter.to == "jule@example.com" and letter.subject == subject and letter.kind == "notice"
    assert words in letter.text and letter.text.endswith(f"{PUBLIC}{quota.PATH}\n")
    assert ("Content-Language", language) in letter.headers


def test_an_account_without_a_language_hears_in_the_language_of_the_first_operator(
    operator: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    mail_on()
    with SessionLocal() as db:
        first = db.scalar(select(Account).where(Account.id == operator.id))
        assert first is not None
        first.language = "fr"
        db.commit()
    account = confirmed("jule", "")
    monkeypatch.setattr(push, "send_to_person", lambda account_id, make_message: None)
    with testing.catch_mail() as caught:
        tell._send(account.id, backup_hooks.backup_failed_notice())
    (letter,) = caught.queued
    assert letter.subject == "nexpaper : échec d'une sauvegarde planifiée"
    assert ("Content-Language", "fr") in letter.headers


def export_of(account: Account, state: str, count: int) -> int:
    with SessionLocal() as db:
        row = Export(user_id=account.id, state=state, documents=count,
                     expires_at=clock.now() + timedelta(days=exports.KEEP_DAYS))
        db.add(row)
        db.commit()
        return row.id


@pytest.mark.parametrize(("language", "ready", "failed"), [
    ("de", ("Dein nexpaper-Export ist fertig", "Das ZIP mit 4 Dokumenten, das du angefordert hast, ist fertig."),
     ("Dein nexpaper-Export ist gescheitert", "Das angeforderte ZIP ließ sich nicht packen.")),
    ("en", ("Your nexpaper export is ready", "The ZIP with 4 documents you asked for is ready."),
     ("Your nexpaper export failed", "The ZIP you asked for could not be packed.")),
    ("fr", ("Votre exportation nexpaper est prête", "Le ZIP avec 4 documents que vous avez demandé est prêt."),
     ("Votre exportation nexpaper a échoué", "Le ZIP demandé n'a pas pu être préparé.")),
])
def test_the_mail_of_an_export_speaks_the_language_of_its_account(
    operator: Account, monkeypatch: pytest.MonkeyPatch, language: str, ready: tuple[str, str],
    failed: tuple[str, str]
) -> None:
    mail_on()
    account = confirmed("jule", language)
    pushed: list[str] = []

    def capture(account_id: int, message_for: Any) -> push.Result:
        pushed.append(message_for("").title)
        return push.Result()

    monkeypatch.setattr(push, "send_to_person", capture)
    with testing.catch_mail() as caught:
        exports._send(export_of(account, exports.READY, 4))
        exports._send(export_of(account, "failed", 0))
    first, second = caught.queued
    assert (first.subject, second.subject) == (ready[0], failed[0])
    assert ready[1] in first.text and failed[1] in second.text
    assert f"{PUBLIC}{exports.EXPORTS_PATH}" in first.text and str(exports.KEEP_DAYS) in first.text
    assert all(("Content-Language", language) in letter.headers for letter in (first, second))
    assert pushed == [exports.TEXTS[language]["ready"][0], exports.TEXTS[language]["failed"][0]]


@pytest.mark.parametrize(("language", "subject", "words", "last"), [
    ("de", "Bestätige die Adresse, von der du Dokumente weiterleitest",
     "Das nexpaper-Konto jule möchte von dieser Adresse aus Dokumente an paper@example.com weiterleiten.",
     "Der Link gilt einmal und 24 Stunden lang."),
    ("en", "Confirm the address you forward documents from",
     "The nexpaper account jule wants to forward documents to paper@example.com from this address.",
     "The link works once and for 24 hours."),
    ("fr", "Confirmez l'adresse depuis laquelle vous transférez des documents",
     "Le compte nexpaper jule souhaite transférer des documents à paper@example.com depuis cette adresse.",
     "Le lien fonctionne une seule fois et pendant 24 heures."),
])
def test_the_link_for_a_forwarding_address_speaks_the_language_of_the_account(
    language: str, subject: str, words: str, last: str
) -> None:
    link = f"{PUBLIC}/absender/abc"
    letter = mail_senders.confirm_letter("jule.privat@example.com", link, name="jule", hours=24,
                                         mailbox="paper@example.com", language=language)
    assert letter.subject == subject and words in letter.text and last in letter.text and link in letter.text
    assert ("Content-Language", language) in letter.headers
    assert letter.kind == "sender_confirm"


def test_the_link_for_a_forwarding_address_keeps_names_as_they_are() -> None:
    letter = mail_senders.confirm_letter("a@example.com", f"{PUBLIC}/absender/abc", name="{target}{hours}", hours=24,
                                         mailbox="", language="de")
    assert "Das nexpaper-Konto {target}{hours} möchte von dieser Adresse aus Dokumente weiterleiten." in letter.text


def test_the_route_sends_the_link_in_the_language_of_the_account(client: Any, operator: Account) -> None:
    mail_on()
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None
        row.language = "fr"
        db.commit()
    with testing.catch_mail() as caught:
        answer = client.post("/api/v1/me/mail-senders", json={"address": "tester.privat@example.com"})
    assert answer.status_code == 201, answer.text
    (letter,) = caught.sent
    assert letter.subject == "Confirmez l'adresse depuis laquelle vous transférez des documents"
