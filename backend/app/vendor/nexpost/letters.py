"""Mails as letters: the texts in German, English and French, plain text and HTML with the app's logo, the language
of the recipient, and headers without line breaks.

Every value that goes into a header (subject, sender name, a name in the subject) loses line breaks and control
characters first (``one_line``): a name with a line break can neither add a header nor break the mail. Every value
that goes into HTML is escaped.

Since 1.0.0 the mail "New sign-in" names the browser on its system **and the moment** in the person's time zone
(``moment``), never a network address, and carries the button "See signed-in devices" when the app gives the address
of its page Security as ``link``. An invitation into a space has a second wording for somebody who has an account
already (``member``).
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from datetime import UTC, datetime, timedelta, tzinfo
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import config
from .errors import MailError
from .model import Letter

LANGUAGES = ("de", "en", "fr")
TEXTS = Path(__file__).resolve().parent / "texts"
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_PART = r"[^@\s<>,;\x00-\x1f\x7f-\x9f\"]+"
_ADDRESS = re.compile(rf"{_PART}@{_PART}\.{_PART}")
#: Kinds that carry a link (a button in HTML, a line of its own in text).
WITH_LINK = ("invite", "reset", "confirm_email")
#: What a browser's User-Agent may name in a mail, the first that fits (order matters: Edge and Opera say Chrome too,
#: Chrome says Safari). Nothing else of the header ever reaches a mail.
BROWSERS = (
    ("Edg/", "Edge"),
    ("EdgiOS/", "Edge"),
    ("OPR/", "Opera"),
    ("SamsungBrowser/", "Samsung Internet"),
    ("Vivaldi/", "Vivaldi"),
    ("Firefox/", "Firefox"),
    ("FxiOS/", "Firefox"),
    ("CriOS/", "Chrome"),
    ("Chrome/", "Chrome"),
    ("Safari/", "Safari"),
)
SYSTEMS = (
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Android", "Android"),
    ("CrOS", "ChromeOS"),
    ("Windows", "Windows"),
    ("Macintosh", "macOS"),
    ("Mac OS X", "macOS"),
    ("Linux", "Linux"),
)


def one_line(value: object, limit: int = 200) -> str:
    """A value for a header or a subject: no line break, no control or format character, blanks as one."""
    text = "".join(" " if char in "\r\n\t" else char for char in str(value or ""))
    text = "".join(char for char in text if unicodedata.category(char) not in ("Cc", "Cf"))
    return " ".join(text.split())[:limit]


def check_address(address: str) -> str:
    """A recipient or sender address in one line, or ``mail_address_invalid``."""
    text = (address or "").strip()
    if not text or len(text) > 254 or not _ADDRESS.fullmatch(text):
        raise MailError("mail_address_invalid", "This is not an email address.")
    return text


def language_for(account_language: str = "", operator_language: str = "") -> str:
    """The language of a mail: the account's, else the operator's, else English (``de-AT`` counts as ``de``)."""
    for candidate in (account_language, operator_language):
        short = (candidate or "").strip().lower()[:2]
        if short in LANGUAGES:
            return short
    return "en"


@lru_cache(maxsize=8)
def texts(language: str) -> dict[str, object]:
    return dict(json.loads((TEXTS / f"mail.{language}.json").read_text(encoding="utf-8")))


def _text(language: str, path: str) -> str:
    node: object = texts(language)
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return ""
        node = node[part]
    return node if isinstance(node, str) else ""


def _fill(template: str, values: dict[str, str]) -> str:
    return _PLACEHOLDER.sub(lambda match: values.get(match.group(1), ""), template)


def validity(language: str, *, hours: int = 0, days: int = 0) -> str:
    """``1 Stunde``, ``24 hours``, ``7 jours``."""
    if days:
        return _fill(_text(language, "days_one" if days == 1 else "days_other"), {"count": str(days)})
    return _fill(_text(language, "hours_one" if hours == 1 else "hours_other"), {"count": str(hours)})


def _html(language: str, heading: str, paragraphs: list[str], link: str, action: str, footer: str) -> str:
    logo = (
        '<img src="cid:logo" alt="" width="40" height="40" style="display:block;margin:0 0 16px 0">'
        if (config.current().logo)
        else ""
    )
    body = "".join(f'<p style="margin:0 0 14px 0">{html.escape(text)}</p>' for text in paragraphs if text)
    button = ""
    if link:
        button = (
            f'<p style="margin:20px 0"><a href="{html.escape(link, quote=True)}" style="display:inline-block;'
            'padding:10px 18px;border-radius:8px;background:#1f2937;color:#ffffff;text-decoration:none">'
            f"{html.escape(action)}</a></p>"
            f'<p style="margin:0 0 14px 0;font-size:12px;color:#6b7280;word-break:break-all">{html.escape(link)}</p>'
        )
    return (
        f'<!doctype html><html lang="{language}"><body style="margin:0;padding:24px;background:#f3f4f6;'
        'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:15px;color:#111827">'
        '<table role="presentation" width="100%" style="max-width:560px;margin:0 auto;background:#ffffff;'
        'border-radius:12px"><tr><td style="padding:28px">'
        f'{logo}<h1 style="font-size:18px;margin:0 0 16px 0">{html.escape(heading)}</h1>{body}{button}'
        f'<p style="margin:24px 0 0 0;font-size:12px;color:#6b7280">{html.escape(footer)}</p>'
        "</td></tr></table></body></html>"
    )


def describe_browser(agent: str, language: str) -> str:
    """"Firefox on Linux" from a raw User-Agent: only the names above, never a word of the header itself (a header
    is anybody's text: "please confirm at https://..." must not reach a mail)."""
    text = (agent or "")[:512]
    browser = next((name for mark, name in BROWSERS if mark in text), "")
    system = next((name for mark, name in SYSTEMS if mark in text), "")
    language = language if language in LANGUAGES else "en"
    if not browser or not system:
        return browser or system or _text(language, "browser_unknown")
    return _fill(_text(language, "browser_on"), {"browser": browser, "system": system})


#: Since 0.1.2: kinds with a wording of their own when a value is given (``invite`` with ``space``: the space, place or
#: book the person is invited into).
VARIANTS = {"invite": ("space", "invite_space")}
#: Since 1.0.0: a wording of a wording when another value is given (``invite_space`` with ``member``: the person has an
#: account already and joins with it, nextasks and nexlore). ``member`` without ``space`` changes nothing.
MEMBER_VARIANTS = {"invite_space": ("member", "invite_space_member")}


def _zone(time_zone: str | tzinfo | None) -> tzinfo | None:
    """The zone a moment is told in: a ``tzinfo`` as given, an IANA name (``Europe/Berlin``) where the system knows
    it, ``UTC``; anything else (empty, unknown, no time zone data on the machine) None: the server's own."""
    if isinstance(time_zone, tzinfo):
        return time_zone
    name = (time_zone or "").strip()
    if name.upper() in ("UTC", "ETC/UTC", "Z"):
        return UTC
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def _offset(local: datetime) -> str:
    """``UTC``, ``UTC+1``, ``UTC-3``, ``UTC+5:30``: the offset of a moment, the same words in every language."""
    minutes = int((local.utcoffset() or timedelta(0)).total_seconds() // 60)
    if minutes == 0:
        return "UTC"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{'+' if minutes > 0 else '-'}{hours}" + (f":{rest:02d}" if rest else "")


def moment(language: str, at: datetime | None = None, time_zone: str | tzinfo | None = None) -> str:
    """Since 1.0.0: a moment as a mail tells it, in the person's time zone and language: ``25.11.2026 um 14:05 Uhr
    (UTC+1)``, ``2026-11-25 at 14:05 (UTC+1)``, ``25/11/2026 à 14:05 (UTC+1)``. ``at`` default now; a naive time
    counts as UTC (the way the apps store it). ``time_zone`` the person's (a name or a ``tzinfo``); without one, or
    one the machine does not know, the server's own (the zone of the ``Date`` header)."""
    language = language if language in LANGUAGES else "en"
    when = at or datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    zone = _zone(time_zone)
    local = when.astimezone(zone) if zone is not None else when.astimezone()
    day = _fill(_text(language, "date"), {"d": f"{local.day:02d}", "m": f"{local.month:02d}", "y": str(local.year)})
    return _fill(
        _text(language, "moment"),
        {"day": day, "time": f"{local.hour:02d}:{local.minute:02d}", "zone": _offset(local)},
    )


def compose(kind: str, to: str, *, language: str, values: dict[str, object], link: str = "") -> Letter:
    """A letter of one of the module's kinds (``invite``, ``reset``, ``confirm_email``, ``email_changed``,
    ``email_removed``, ``username_changed``, ``factor_reset``, ``new_sign_in``, ``test``). ``values`` fills the
    texts: ``name``, ``username``, ``by``, ``hint``, ``where``, ``valid`` (``validity``); ``app`` comes from the
    configuration. Since 0.1.2 an invitation takes ``space`` too, the name of a space, place or address book the person
    is invited into ("Alex invites you to Family in nextasks"); without it the letter is the one of 0.1.1. Since 1.0.0
    ``member`` (any non-empty value) with ``space``: the person has an account and joins with it; ``new_sign_in``
    takes ``when`` (``moment``), now in the server's zone when it is missing, and ``link`` becomes its button "See
    signed-in devices" (the app's page Security)."""
    recipient = check_address(to)
    language = language if language in LANGUAGES else "en"
    if not _text(language, f"{kind}.subject"):
        raise ValueError(f"no mail of the kind {kind!r}")
    filled = {key: one_line(value) for key, value in values.items()}
    filled["app"] = one_line(config.current().shown_name)
    if kind == "new_sign_in" and not filled.get("when"):
        filled["when"] = moment(language)
    wording = kind
    if kind in VARIANTS and filled.get(VARIANTS[kind][0]):
        wording = VARIANTS[kind][1]
    if wording in MEMBER_VARIANTS and filled.get(MEMBER_VARIANTS[wording][0]):
        wording = MEMBER_VARIANTS[wording][1]
    subject = one_line(_fill(_text(language, f"{wording}.subject"), filled))
    greeting = _fill(_text(language, "greeting"), filled) if filled.get("name") else ""
    body = _fill(_text(language, f"{wording}.body"), filled)
    action = _fill(_text(language, f"{wording}.action"), filled)
    footer = _fill(_text(language, "footer"), filled)
    lines = [line for line in (greeting, body) if line]
    text = "\n\n".join([*lines, *([link] if link else []), footer]) + "\n"
    markup = _html(language, subject, lines, link if kind in WITH_LINK or link else "", action, footer)
    return Letter(recipient, subject, text, markup, kind)


def from_account_mail(
    mail: object,
    *,
    language: str,
    link: str = "",
    by: str = "",
    where: str = "",
    days: int = 0,
    space: str = "",
    member: bool = False,
    time_zone: str | tzinfo | None = None,
) -> Letter:
    """A letter for a ``Mail`` of nexkonten (read by its fields, the modules import nothing from each other):
    ``kind``, ``to``, ``username``, ``display_name``, ``hours``, ``new_hint``, since 1.0.0 ``at`` (when a new sign-in
    happened; missing: now). ``link`` the app built from the token, for ``new_sign_in`` (since 1.0.0) the address of
    the app's page Security (the button "See signed-in devices"); ``days`` for an invitation; ``where`` the raw
    User-Agent of a new sign-in (the module names the browser and the system from it, nothing else, never an
    address); ``space`` (since 0.1.2) the space an invitation leads into; ``member`` (since 1.0.0) with ``space``: the
    person has an account and joins with it; ``time_zone`` (since 1.0.0) the person's, for the moment of a new sign-in
    (without: the server's)."""
    kind = str(getattr(mail, "kind", ""))
    if kind == "email_changed" and not getattr(mail, "new_hint", ""):
        kind = "email_removed"
    hours = int(getattr(mail, "hours", 0) or 0)
    values: dict[str, object] = {
        "name": getattr(mail, "display_name", "") or getattr(mail, "username", ""),
        "username": getattr(mail, "username", ""),
        "hint": getattr(mail, "new_hint", ""),
        "by": by,
        "space": space,
        "member": "yes" if member else "",
        "where": describe_browser(where, language) if kind == "new_sign_in" else "",
        "when": moment(language, getattr(mail, "at", None), time_zone) if kind == "new_sign_in" else "",
        "valid": validity(language if language in LANGUAGES else "en", hours=hours, days=days) if hours or days else "",
    }
    return compose(kind, str(getattr(mail, "to", "")), language=language, values=values, link=link)
