"""Reminders of deadlines (F2): a push and a mail when a deadline comes near, and a mail on Mondays with the week.

**Who is reminded.** Everybody who may change the document: ``edit`` or ``manage`` in its vault, or a share with
``edit`` (the same as the deadlines page, ``deadlines.open_for``). Somebody who may only read gets nothing. A person can
mute single vaults (``reminder_mutes``) and what they reach through a share alone (``muted_shared``); the right and the
mutes are part of the query that runs right before anything is sent, so nothing goes out about a document the person
lost meanwhile. A share with ``edit`` counts because whoever shared it asked the person to look after the document: they
see its deadline on their page and may mark it paid; the same right reminds them.

**When.** The loop runs every ``TICK_SECONDS``; a person is due from ``HOUR`` o'clock in their own time zone
(``timezones.zone_of``), never before. Per deadline there are three stages, each with the day it belongs to:

* ``lead``: the deadline lies at most the person's lead ahead (pay 3, cancel 14, warranty 30 days from the start). Sent
  once while the day is still ahead, also when the deadline was entered late (a warranty entered 20 days before its end
  is reminded at once, not never).
* ``day``: on the day itself, when the person wants that (``same_day``). Missed (the server was off), it is sent up to
  ``CATCH_UP_DAYS`` days later, older not.
* ``later``: the day a person's "later" ends. Missed, up to ``CATCH_UP_DAYS`` days later as well.

What is done never reminds (``open_for`` leaves it out); while a "later" lasts, the person hears nothing of that
deadline. A contract whose last day to cancel passed is not reminded again (it was, before that day), only "later".

**Exactly once.** Every stage has a row in ``reminders_sent`` (deadline, person, stage, day) with a unique key, written
in one transaction under the write lock **before** anything is sent; only what the insert really added goes out. Two
runs at once (two processes, a restart in the middle) therefore send each reminder once. A message that fails on the
way is not tried again: better one missing than ten.

**The brake.** At most ``PER_DAY`` messages per person and day, the most urgent first; what is over that goes into one
message ("and 14 more") once a day. What is over the limit after that one went waits for the next day.

**The weekly mail** goes on Mondays from ``HOUR`` o'clock (missed: up to ``CATCH_UP_DAYS`` days later), and only when
something comes up: the deadlines of the week, what is overdue, how many documents may go (block F3; ``may_go_count``
asks it once it is there). It needs a mail server and a confirmed address, like a reminder by mail.

**What a message says**: the kind of deadline, its day and the title of the document ("Kündigen bis Mi, 30.09.:
Handyvertrag"), in the person's language. Never an amount, the text, notes or tags. A tap opens the document.
"""

from __future__ import annotations

import asyncio
import html
import importlib
import logging
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any

from sqlalchemy import ColumnElement, and_, delete, func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .. import clock
from ..errors import error
from ..models import (
    EDIT,
    INBOX,
    MANAGE,
    Account,
    DeadlineSnooze,
    Document,
    DocumentDate,
    ReminderMute,
    ReminderSent,
    ReminderSettings,
    Share,
    VaultMember,
)
from . import changes, deadlines, mailer, notices, push, settings_service, timezones, vaults

logger = logging.getLogger("nexpaper.reminders")

RHYTHMS = ("single", "weekly", "both")
#: The days ahead a person may choose, per kind of deadline (the mock's lists), and what they are from the start.
LEADS: dict[str, tuple[int, ...]] = {"due": (1, 3, 7, 14), "cancel": (7, 14, 30, 60), "warranty": (7, 14, 30, 60)}
DEFAULT_LEAD = {"due": 3, "cancel": 14, "warranty": 30}
#: The lead a deadline takes, by what it asks for: a contract that only ends takes the one of cancelling.
LEAD_OF = {"pay": "due", "cancel": "cancel", "ends": "cancel", "warranty": "warranty"}
#: From this hour of the person's day on.
HOUR = 8
#: How many days late a missed reminder still goes.
CATCH_UP_DAYS = 2
#: Messages per person and day, at most; the rest in one.
PER_DAY = 20
TICK_SECONDS = 900
#: Entries per list of the weekly mail.
LIST_MAX = 30
#: The title of a document in a message, at most.
TITLE_MAX = 120
#: The vaults a person may mute at once, at most (far above a household).
MUTED_MAX = 500

LEAD, DAY, LATER, WEEK, BATCH = "lead", "day", "later", "week", "batch"
SINGLE_STAGES = (LEAD, DAY, LATER)
TAG = "deadline"
DEADLINES_PATH = "/fristen"


# --- What a person chose ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Preferences:
    rhythm: str = "single"
    push: bool = True
    mail: bool = False
    lead: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_LEAD))
    same_day: bool = True
    muted_shared: bool = False

    @property
    def single(self) -> bool:
        return self.rhythm in ("single", "both")

    @property
    def weekly(self) -> bool:
        return self.rhythm in ("weekly", "both")


def preferences_of(db: Session, uid: int) -> Preferences:
    row = db.get(ReminderSettings, uid)
    if row is None:
        return Preferences()
    lead = {
        "due": row.lead_due if row.lead_due in LEADS["due"] else DEFAULT_LEAD["due"],
        "cancel": row.lead_cancel if row.lead_cancel in LEADS["cancel"] else DEFAULT_LEAD["cancel"],
        "warranty": row.lead_warranty if row.lead_warranty in LEADS["warranty"] else DEFAULT_LEAD["warranty"],
    }
    return Preferences(rhythm=row.rhythm if row.rhythm in RHYTHMS else "single", push=bool(row.push),
                       mail=bool(row.mail), lead=lead, same_day=bool(row.same_day),
                       muted_shared=bool(row.muted_shared))


def mail_problem(db: Session, account: Account) -> str | None:
    """Why a reminder cannot go by mail: no mail server, no address, an address not yet confirmed; None when it can."""
    if not mailer.configured(db):
        return "no_server"
    if not account.email:
        return "no_address"
    if account.email_confirmed_at is None:
        return "unconfirmed"
    return None


def editable_vaults(db: Session, uid: int) -> set[int]:
    return set(db.scalars(select(VaultMember.vault_id).where(VaultMember.user_id == uid,
                                                             VaultMember.right.in_((EDIT, MANAGE)))))


def muted_of(db: Session, uid: int) -> list[int]:
    return list(db.scalars(select(ReminderMute.vault_id).where(ReminderMute.user_id == uid)
                           .order_by(ReminderMute.vault_id)))


def shared_count(db: Session, uid: int) -> int:
    """Documents shared with the person with ``edit`` that lie in no vault where they may change things."""
    return int(db.scalar(
        select(func.count()).select_from(Share).join(Document, Document.id == Share.document_id)
        .where(Share.user_id == uid, Share.right == EDIT,
               Document.vault_id.not_in(select(VaultMember.vault_id).where(VaultMember.user_id == uid,
                                                                          VaultMember.right.in_((EDIT, MANAGE)))))
    ) or 0)


def zone_name(account: Account) -> str:
    profile = account.profile if isinstance(account.profile, dict) else {}
    name = profile.get("timezone")
    if timezones.valid_time_zone(name):
        return str(name)
    return str(datetime.now().astimezone().tzinfo or "")


def view(db: Session, account: Account) -> dict[str, Any]:
    """What Mein Konto, Erinnerungen shows: the choices, what the ways need, and the vaults (edit or manage: can be
    muted; read only: named, nothing to choose)."""
    prefs = preferences_of(db, account.id)
    muted = set(muted_of(db, account.id))
    mine: list[dict[str, Any]] = []
    read_only: list[dict[str, Any]] = []
    for item in vaults.listing(db, account.id):
        entry = {"id": item.vault.id, "name": item.name, "icon": item.vault.icon,
                 "personal": item.vault.personal_of == account.id,
                 "personal_of_other": item.vault.personal_of is not None and item.vault.personal_of != account.id}
        if item.right in (EDIT, MANAGE):
            others = sum(1 for member, person in item.members
                         if person.id != account.id and member.right in (EDIT, MANAGE))
            mine.append({**entry, "muted": item.vault.id in muted, "others": others})
        else:
            read_only.append(entry)
    return {
        "rhythm": prefs.rhythm,
        "push": prefs.push,
        "mail": prefs.mail,
        "lead": dict(prefs.lead),
        "same_day": prefs.same_day,
        "muted": sorted(muted),
        "muted_shared": prefs.muted_shared,
        "options": {key: list(values) for key, values in LEADS.items()},
        "hour": HOUR,
        "time_zone": zone_name(account),
        "push_devices": len(push.devices_of(db, account.id)),
        "mail_address": account.email if account.email_confirmed_at is not None else "",
        "mail_problem": mail_problem(db, account),
        "vaults": mine,
        "read_only": read_only,
        "shared": shared_count(db, account.id),
    }


def save(db: Session, account: Account, change: dict[str, Any]) -> None:
    """Changes what the person sent, nothing else. Mail (and the weekly mail, which is a mail) can only be switched on
    when it can go (``mail_unavailable``); a vault can only be muted by somebody who may change things in it."""
    changes.write_lock(db)
    current = preferences_of(db, account.id)
    rhythm = change.get("rhythm", current.rhythm)
    mail = change.get("mail", current.mail)
    if rhythm not in RHYTHMS:
        raise error("bad_reminder", "This value is not one nexpaper offers.", 422, field="rhythm")
    lead = dict(current.lead)
    for key, value in (change.get("lead") or {}).items():
        if key not in LEADS or type(value) is not int or value not in LEADS[key]:
            raise error("bad_reminder", "This value is not one nexpaper offers.", 422, field=f"lead.{key}")
        lead[key] = value
    wants_mail = (mail and not current.mail) or (rhythm in ("weekly", "both") and current.rhythm == "single")
    if wants_mail and mail_problem(db, account) is not None:
        raise error("mail_unavailable", "Reminders by mail need a mail server and a confirmed address.", 409,
                    reason=mail_problem(db, account))
    row = db.get(ReminderSettings, account.id)
    if row is None:
        row = ReminderSettings(user_id=account.id)
        db.add(row)
    row.rhythm = rhythm
    row.push = bool(change.get("push", current.push))
    row.mail = bool(mail)
    row.lead_due, row.lead_cancel, row.lead_warranty = lead["due"], lead["cancel"], lead["warranty"]
    row.same_day = bool(change.get("same_day", current.same_day))
    row.muted_shared = bool(change.get("muted_shared", current.muted_shared))
    row.updated_at = clock.now()
    if "muted" in change:
        wanted = set(change["muted"] or [])
        if len(wanted) > MUTED_MAX or not wanted <= editable_vaults(db, account.id):
            # A vault the person may not change things in, or none at all: the same answer (no list of vaults).
            raise error("bad_reminder", "This value is not one nexpaper offers.", 422, field="muted")
        db.execute(delete(ReminderMute).where(ReminderMute.user_id == account.id,
                                              ReminderMute.vault_id.not_in(wanted)))
        for vault_id in sorted(wanted):
            db.execute(sqlite_insert(ReminderMute).values(user_id=account.id, vault_id=vault_id,
                                                          created_at=clock.now())
                       .on_conflict_do_nothing(index_elements=["user_id", "vault_id"]))
    db.commit()
    logger.info("Reminder choices changed fields=%s", ",".join(sorted(change)) or "nothing")


# --- What a message says ----------------------------------------------------------------------------------------------


WEEKDAYS = {"de": ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"), "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")}
MONTHS = {"en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")}
WORDS: dict[str, dict[str, str]] = {
    "de": {
        "pay": "Zahlen bis {day}", "cancel": "Kündigen bis {day}", "ends": "Vertrag endet {day}",
        "warranty": "Garantie bis {day}",
        "short_pay": "Zahlen", "short_cancel": "Kündigen", "short_ends": "Kündigen", "short_warranty": "Garantie",
        "days": "Noch {n} Tage.", "tomorrow": "Morgen.", "today": "Heute.", "yesterday": "Seit gestern.",
        "since": "Seit {n} Tagen.",
        "renews": " Danach verlängert sich der Vertrag bis {date}.",
        "ends_renews": " Ohne Kündigung verlängert er sich bis {date}.",
        "more_one": "Und eine weitere Frist", "more": "Und {n} weitere Fristen",
        "more_body": "Mehr als {limit} an einem Tag. Alle stehen auf der Seite Fristen.",
        "test_title": "Testnachricht von nexpaper",
        "test_body": "So kommen deine Erinnerungen an. Tippen öffnet die Seite Fristen.",
        "open": "Öffnen: {link}",
        "single_why": "Diese Mail kommt, weil du unter Mein Konto, Erinnerungen die Erinnerung per Mail eingeschaltet "
                      "hast.",
        "week_subject": "Diese Woche: {n} {fristen}", "week_none": "Diese Woche: keine Fristen",
        "frist": "Frist", "fristen": "Fristen", "overdue_part": ", {n} überfällig",
        "hello": "Guten Morgen {name}, das steht diese Woche an:",
        "overdue": "Überfällig", "week": "Diese Woche", "nothing": "nichts", "may_go": "Darf weg",
        "may_go_one": "Bei einem Dokument ist die Aufbewahrungszeit um.",
        "may_go_many": "Bei {n} Dokumenten ist die Aufbewahrungszeit um.",
        "and_more": "und {n} weitere",
        "all": "Alle Fristen in nexpaper öffnen",
        "week_why": "Diese Mail kommt, weil du unter Mein Konto, Erinnerungen die Wochenübersicht eingeschaltet hast.",
    },
    "en": {
        "pay": "Pay by {day}", "cancel": "Cancel by {day}", "ends": "Contract ends {day}",
        "warranty": "Warranty until {day}",
        "short_pay": "Pay", "short_cancel": "Cancel", "short_ends": "Cancel", "short_warranty": "Warranty",
        "days": "{n} days to go.", "tomorrow": "Tomorrow.", "today": "Today.", "yesterday": "Since yesterday.",
        "since": "For {n} days now.",
        "renews": " After that the contract renews until {date}.",
        "ends_renews": " Unless cancelled it renews until {date}.",
        "more_one": "And one more deadline", "more": "And {n} more deadlines",
        "more_body": "More than {limit} in one day. All of them are on the deadlines page.",
        "test_title": "Test message from nexpaper",
        "test_body": "This is how your reminders arrive. A tap opens the deadlines.",
        "open": "Open: {link}",
        "single_why": "This mail comes because you switched on reminders by mail under My account, Reminders.",
        "week_subject": "This week: {n} {fristen}", "week_none": "This week: no deadlines",
        "frist": "deadline", "fristen": "deadlines", "overdue_part": ", {n} overdue",
        "hello": "Good morning {name}, this is what comes up this week:",
        "overdue": "Overdue", "week": "This week", "nothing": "nothing", "may_go": "May go",
        "may_go_one": "The keeping time of one document is over.",
        "may_go_many": "The keeping time of {n} documents is over.",
        "and_more": "and {n} more",
        "all": "Open all deadlines in nexpaper",
        "week_why": "This mail comes because you switched on the weekly overview under My account, Reminders.",
    },
}


def short_day(day: Date, lang: str) -> str:
    """"Mi, 30.09." or "Wed, Sep 30"."""
    weekday = WEEKDAYS[lang][day.weekday()]
    if lang == "de":
        return f"{weekday}, {day.day:02d}.{day.month:02d}."
    return f"{weekday}, {MONTHS['en'][day.month - 1]} {day.day}"


def long_date(day: Date, lang: str) -> str:
    if lang == "de":
        return f"{day.day:02d}.{day.month:02d}.{day.year}"
    return f"{MONTHS['en'][day.month - 1]} {day.day}, {day.year}"


def clean_title(title: str) -> str:
    """The title of a document as a message names it: one line, no control characters, not too long."""
    text = " ".join("".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in title or "").split())
    return text if len(text) <= TITLE_MAX else text[: TITLE_MAX - 1].rstrip() + "…"


def place_of(document: Document) -> str:
    """Where a tap leads: the document with the deadline (in the inbox while it waits there)."""
    return f"/eingang/{document.id}" if document.status == INBOX else f"/dokument/{document.id}"


def words_for(deadline: deadlines.Deadline, today: Date, lang: str) -> tuple[str, str]:
    """The title and the sentence of a reminder: kind, day and title of the document; never an amount or contents."""
    words = WORDS[lang]
    worked = deadline.worked
    title = f"{words[worked.what].format(day=short_day(worked.date, lang))}: {clean_title(deadline.document.title)}"
    days = (worked.date - today).days
    if days > 1:
        body = words["days"].format(n=days)
    elif days == 1:
        body = words["tomorrow"]
    elif days == 0:
        body = words["today"]
    elif days == -1:
        body = words["yesterday"]
    else:
        body = words["since"].format(n=-days)
    if worked.renews_to is not None and worked.what == "cancel":
        body += words["renews"].format(date=long_date(worked.renews_to, lang))
    elif worked.renews_to is not None and worked.what == "ends" and worked.missed is None:
        body += words["ends_renews"].format(date=long_date(worked.renews_to, lang))
    return title, body


# --- The ways --------------------------------------------------------------------------------------------------------


def language_of(account: Account, device_lang: str = "") -> str:
    """The person's language: the one of the account, else the one the device signed up in."""
    return notices.language_of(account.language or device_lang)


@dataclass
class Out:
    """One message for one person: the push in each device's language, and a mail when it goes by mail."""

    texts: dict[str, tuple[str, str]]
    url: str
    tag: str
    mail: EmailMessage | None = None


def _push(account: Account, out: Out) -> push.Result:
    def message_for(lang: str) -> push.Message:
        title, body = out.texts[language_of(account, lang)]
        return push.Message(title=title, body=body, url=out.url, desk=out.url, tag=out.tag)

    return push.send_to_person(account.id, message_for)


def _mail(to: str, subject: str, text: str, markup: str | None = None) -> EmailMessage:
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = " ".join(subject.split())
    message.set_content(text)
    if markup is not None:
        message.add_alternative(markup, subtype="html")
    return message


def _single_mail(to: str, base: str, title: str, body: str, url: str, lang: str) -> EmailMessage:
    words = WORDS[lang]
    lines = [title, body, ""]
    if base:
        lines += [words["open"].format(link=f"{base}{url}"), ""]
    lines.append(words["single_why"])
    return _mail(to, title, "\n".join(lines) + "\n")


def _deliver(db_factory: Any, account: Account, outs: list[Out], *, by_push: bool) -> None:
    for out in outs:
        if by_push and out.texts:
            try:
                _push(account, out)
            except Exception:  # one message must never stop the others
                logger.exception("A reminder was not pushed")
        if out.mail is not None:
            with db_factory() as db:
                try:
                    mailer.send_message(db, out.mail)
                except mailer.MailError:
                    logger.warning("A reminder was not mailed tag=%s", out.tag)


# --- Which reminders are due ------------------------------------------------------------------------------------------


@dataclass
class Due:
    deadline: deadlines.Deadline
    #: The rows that say it went: (stage, day). The message goes when the insert adds at least one of them.
    keys: list[tuple[str, Date]]


def mute_clauses(uid: int, prefs: Preferences) -> list[ColumnElement[bool]]:
    """No muted vault; with ``muted_shared``, only documents in a vault where the person may change things."""
    clauses: list[ColumnElement[bool]] = [
        Document.vault_id.not_in(select(ReminderMute.vault_id).where(ReminderMute.user_id == uid)),
    ]
    if prefs.muted_shared:
        clauses.append(Document.vault_id.in_(select(VaultMember.vault_id).where(
            VaultMember.user_id == uid, VaultMember.right.in_((EDIT, MANAGE)))))
    return clauses


def due_singles(db: Session, uid: int, prefs: Preferences, today: Date) -> list[Due]:
    """The reminders of one person that are due today, the most urgent first; each with every stage it covers."""
    catch_up = today - timedelta(days=CATCH_UP_DAYS)
    ahead = today + timedelta(days=max(prefs.lead.values()))
    ended = select(DeadlineSnooze.date_id).where(DeadlineSnooze.user_id == uid, DeadlineSnooze.until <= today,
                                                 DeadlineSnooze.until >= catch_up)
    when = deadlines.act_by(today)
    found = deadlines.open_for(db, uid, today, where=[
        *mute_clauses(uid, prefs),
        or_(and_(when >= catch_up, when <= ahead), DocumentDate.id.in_(ended)),
    ])
    snoozes = dict(db.execute(select(DeadlineSnooze.date_id, DeadlineSnooze.until).where(
        DeadlineSnooze.user_id == uid, DeadlineSnooze.date_id.in_([d.row.id for d in found]))).all()) if found else {}
    out: list[Due] = []
    for deadline in found:
        worked = deadline.worked
        until = snoozes.get(deadline.row.id)
        if until is not None and until > today:
            continue  # "later" lasts
        keys: list[tuple[str, Date]] = []
        if until is not None and catch_up <= until <= today:
            keys.append((LATER, until))
        if not (worked.what == "ends" and worked.missed is not None):
            day = worked.date
            if day - timedelta(days=prefs.lead[LEAD_OF[worked.what]]) <= today < day:
                keys.append((LEAD, day))
            if prefs.same_day and day <= today <= day + timedelta(days=CATCH_UP_DAYS):
                keys.append((DAY, day))
        if keys:
            out.append(Due(deadline, keys))
    return out


def _claim(db: Session, uid: int, date_id: int | None, keys: list[tuple[str, Date]], today: Date) -> bool:
    """Writes the rows; whether at least one of them is new (then the message is this run's to send)."""
    added = False
    for stage, day in keys:
        statement = sqlite_insert(ReminderSent).values(user_id=uid, date_id=date_id, stage=stage, day=day,
                                                       sent_day=today, sent_at=clock.now())
        if date_id is None:
            statement = statement.on_conflict_do_nothing(index_elements=["user_id", "stage", "day"],
                                                         index_where=ReminderSent.date_id.is_(None))
        else:
            statement = statement.on_conflict_do_nothing(index_elements=["date_id", "user_id", "stage", "day"],
                                                         index_where=ReminderSent.date_id.is_not(None))
        if db.execute(statement).rowcount:  # type: ignore[attr-defined]
            added = True
    return added


def _is_claimed(db: Session, uid: int, keys: list[tuple[str, Date]], date_id: int) -> bool:
    return all(db.scalar(select(func.count()).select_from(ReminderSent).where(
        ReminderSent.date_id == date_id, ReminderSent.user_id == uid, ReminderSent.stage == stage,
        ReminderSent.day == day)) for stage, day in keys)


def sent_today(db: Session, uid: int, today: Date) -> int:
    """Messages about single deadlines the person got today (by the deadlines they named)."""
    return int(db.scalar(select(func.count(func.distinct(ReminderSent.date_id))).where(
        ReminderSent.user_id == uid, ReminderSent.sent_day == today, ReminderSent.stage.in_(SINGLE_STAGES),
        ReminderSent.date_id.is_not(None))) or 0)


def may_go_count(db: Session, uid: int) -> int:
    """How many documents of the person may go (their keeping time is over): block F3's ``keeping.may_go_count``
    once it is there; 0 until then."""
    try:
        keeping = importlib.import_module(f"{__package__}.keeping")
    except ModuleNotFoundError:
        return 0
    count = getattr(keeping, "may_go_count", None)
    return int(count(db, uid)) if callable(count) else 0


# --- The weekly mail --------------------------------------------------------------------------------------------------


@dataclass
class Week:
    overdue: list[deadlines.Deadline]
    week: list[deadlines.Deadline]
    may_go: int

    @property
    def empty(self) -> bool:
        return not self.overdue and not self.week and not self.may_go


def week_of(db: Session, uid: int, prefs: Preferences, today: Date) -> Week:
    """What comes up from today to six days on, what is overdue (open, the muted vaults left out), what may go."""
    found = deadlines.open_for(db, uid, today, until=today + timedelta(days=6), where=mute_clauses(uid, prefs))
    return Week(overdue=[d for d in found if d.worked.date < today], week=[d for d in found if d.worked.date >= today],
                may_go=may_go_count(db, uid))


def week_mail(account: Account, week: Week, lang: str, base: str, today: Date) -> EmailMessage:
    words = WORDS[lang]
    count = len(week.week)
    subject = words["week_none"] if not count else words["week_subject"].format(
        n=count, fristen=words["frist"] if count == 1 else words["fristen"])
    if week.overdue:
        subject += words["overdue_part"].format(n=len(week.overdue))
    name = account.display_name or account.name

    def line(deadline: deadlines.Deadline) -> str:
        what = words[f"short_{deadline.worked.what}"]
        return f"{short_day(deadline.worked.date, lang)} · {what}: {clean_title(deadline.document.title)}"

    def lines(items: list[deadlines.Deadline]) -> list[str]:
        shown = [line(d) for d in items[:LIST_MAX]]
        if len(items) > LIST_MAX:
            shown.append(words["and_more"].format(n=len(items) - LIST_MAX))
        return shown

    sections: list[tuple[str, list[str], bool]] = []
    if week.overdue:
        sections.append((words["overdue"], lines(week.overdue), True))
    sections.append((words["week"], lines(week.week) or [words["nothing"]], False))
    if week.may_go:
        sections.append((words["may_go"], [words["may_go_one"] if week.may_go == 1
                                           else words["may_go_many"].format(n=week.may_go)], False))
    link = f"{base}{DEADLINES_PATH}" if base else ""
    text = [words["hello"].format(name=name), ""]
    for head, entries, _warn in sections:
        text += [head.upper(), *entries, ""]
    text += [f"{words['all']}: {link}" if link else words["all"], "", words["week_why"]]
    esc = html.escape
    parts = [f"<p>{esc(words['hello'].format(name=name))}</p>"]
    for head, entries, warn in sections:
        colour = "#b4532a" if warn else "#7a6f66"
        parts.append(f'<p style="margin:16px 0 4px;font-size:12px;font-weight:bold;letter-spacing:.05em;'
                     f'text-transform:uppercase;color:{colour}">{esc(head)}</p>')
        parts.append('<ul style="margin:0;padding-left:18px">'
                     + "".join(f"<li>{esc(entry)}</li>" for entry in entries) + "</ul>")
    if link:
        parts.append(f'<p style="margin-top:18px"><a href="{esc(link, quote=True)}" style="color:#9a6a3a;'
                     f'font-weight:bold">{esc(words["all"])}</a></p>')
    else:
        parts.append(f'<p style="margin-top:18px;font-weight:bold;color:#9a6a3a">{esc(words["all"])}</p>')
    parts.append(f'<p style="font-size:12px;color:#7a6f66">{esc(words["week_why"])}</p>')
    markup = ('<!doctype html><html><body style="font-family:Figtree,Arial,sans-serif;font-size:14px;color:#1c1814">'
              + "".join(parts) + "</body></html>")
    return _mail(account.email, subject, "\n".join(text) + "\n", markup)


# --- One run ----------------------------------------------------------------------------------------------------------


@dataclass
class Summary:
    people: int = 0
    messages: int = 0
    gathered: int = 0
    weekly: int = 0


def _person(uid: int, now: datetime, summary: Summary) -> None:
    from ..db import SessionLocal

    outs: list[Out] = []
    with SessionLocal() as db:
        account = db.get(Account, uid)
        if account is None or account.blocked_at is not None:
            return
        local = now.astimezone(timezones.zone_of(account))
        if local.hour < HOUR:
            return
        today = local.date()
        prefs = preferences_of(db, uid)
        problem = mail_problem(db, account)
        by_push = prefs.push and push.has_devices(db, uid)
        by_mail = prefs.mail and problem is None
        base = settings_service.public_url(db)
        device_lang = next((device.lang for device in push.devices_of(db, uid)), "") if not account.language else ""
        lang = language_of(account, device_lang)
        changes.write_lock(db)
        if prefs.single and (by_push or by_mail):
            outs += _singles(db, account, prefs, today, base, lang, by_mail, summary)
        if prefs.weekly and problem is None:
            monday = today - timedelta(days=today.weekday())
            if today <= monday + timedelta(days=CATCH_UP_DAYS) and _claim(db, uid, None, [(WEEK, monday)], today):
                week = week_of(db, uid, prefs, today)
                if not week.empty:
                    outs.append(Out(texts={}, url=DEADLINES_PATH, tag=f"{TAG}-week",
                                    mail=week_mail(account, week, lang, base, today)))
                    summary.weekly += 1
        db.commit()
        db.expunge(account)
    summary.people += 1
    _deliver(SessionLocal, account, outs, by_push=by_push)


def _singles(db: Session, account: Account, prefs: Preferences, today: Date, base: str, lang: str, by_mail: bool,
             summary: Summary) -> list[Out]:
    uid = account.id
    due = due_singles(db, uid, prefs, today)
    room = max(0, PER_DAY - sent_today(db, uid, today))
    outs: list[Out] = []
    rest: list[Due] = []
    for item in due:
        if room <= 0:
            rest.append(item)
            continue
        if not _claim(db, uid, item.deadline.row.id, item.keys, today):
            continue
        room -= 1
        texts = {code: words_for(item.deadline, today, code) for code in WORDS}
        url = place_of(item.deadline.document)
        title, body = texts[lang]
        outs.append(Out(texts=texts, url=url, tag=f"{TAG}-{item.deadline.row.id}",
                        mail=_single_mail(account.email, base, title, body, url, lang) if by_mail else None))
        summary.messages += 1
    rest = [item for item in rest if not _is_claimed(db, uid, item.keys, item.deadline.row.id)]
    if rest and _claim(db, uid, None, [(BATCH, today)], today):
        gathered = sum(1 for item in rest if _claim(db, uid, item.deadline.row.id, item.keys, today))
        texts = {code: (WORDS[code]["more_one"] if gathered == 1 else WORDS[code]["more"].format(n=gathered),
                        WORDS[code]["more_body"].format(limit=PER_DAY)) for code in WORDS}
        title, body = texts[lang]
        outs.append(Out(texts=texts, url=DEADLINES_PATH, tag=f"{TAG}-more",
                        mail=_single_mail(account.email, base, title, body, DEADLINES_PATH, lang) if by_mail
                        else None))
        summary.gathered += gathered
    return outs


def run_once(now: datetime | None = None) -> Summary:
    """One look at every person: what is due goes out, once."""
    from ..db import SessionLocal

    now = now or clock.now()
    summary = Summary()
    with SessionLocal() as db:
        people = list(db.scalars(select(Account.id).where(Account.blocked_at.is_(None)).order_by(Account.id)))
    for uid in people:
        try:
            _person(uid, now, summary)
        except Exception:
            logger.exception("Reminders of one person failed")
    if summary.messages or summary.gathered or summary.weekly:
        logger.info("Reminders sent messages=%s gathered=%s weekly=%s", summary.messages, summary.gathered,
                    summary.weekly)
    return summary


async def run_forever(stop: asyncio.Event) -> None:
    """The loop beside the others: every ``TICK_SECONDS``."""
    while not stop.is_set():
        try:
            await asyncio.to_thread(run_once)
        except Exception:
            logger.exception("Reminders failed")
        try:
            await asyncio.wait_for(stop.wait(), TICK_SECONDS)
            return
        except TimeoutError:
            continue


# --- The test message -------------------------------------------------------------------------------------------------


def send_test(db: Session, account: Account) -> dict[str, Any]:
    """A message on every way the person switched on: push to the devices, a mail when reminders or the weekly mail go
    by mail. ``reminders_no_way`` when there is none."""
    prefs = preferences_of(db, account.id)
    by_push = prefs.push and prefs.single and push.has_devices(db, account.id)
    by_mail = (prefs.mail and prefs.single or prefs.weekly) and mail_problem(db, account) is None
    if not by_push and not by_mail:
        raise error("reminders_no_way", "No way is switched on that reaches you.", 409)
    lang = language_of(account, next((device.lang for device in push.devices_of(db, account.id)), ""))
    texts = {code: (WORDS[code]["test_title"], WORDS[code]["test_body"]) for code in WORDS}
    result = _push(account, Out(texts=texts, url=DEADLINES_PATH, tag=f"{TAG}-test")) if by_push else push.Result()
    mailed = False
    if by_mail:
        title, body = texts[lang]
        try:
            mailer.send_message(db, _single_mail(account.email, settings_service.public_url(db), title, body,
                                                 DEADLINES_PATH, lang))
            mailed = True
        except mailer.MailError:
            logger.warning("The test reminder was not mailed")
    return {"push": result.as_dict(), "mail": mailed, "by_push": by_push, "by_mail": by_mail}


__all__ = [
    "BATCH", "CATCH_UP_DAYS", "DAY", "HOUR", "LATER", "LEAD", "LEADS", "PER_DAY", "WEEK", "Due", "Preferences",
    "Summary", "due_singles", "may_go_count", "preferences_of", "run_forever", "run_once", "save", "send_test",
    "view", "week_mail", "week_of", "words_for",
]
