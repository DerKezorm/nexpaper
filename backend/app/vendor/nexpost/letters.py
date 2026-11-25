"""Mails as letters: the texts in German, English and French, plain text and HTML with the app's logo, the language
of the recipient, and headers without line breaks.

Every value that goes into a header (subject, sender name, a name in the subject) loses line breaks and control
characters first (``one_line``): a name with a line break can neither add a header nor break the mail. Every value
that goes into HTML is escaped.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

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


def compose(kind: str, to: str, *, language: str, values: dict[str, object], link: str = "") -> Letter:
    """A letter of one of the module's kinds (``invite``, ``reset``, ``confirm_email``, ``email_changed``,
    ``email_removed``, ``username_changed``, ``factor_reset``, ``new_sign_in``, ``test``). ``values`` fills the
    texts: ``name``, ``username``, ``by``, ``hint``, ``where``, ``valid`` (``validity``); ``app`` comes from the
    configuration."""
    recipient = check_address(to)
    language = language if language in LANGUAGES else "en"
    if not _text(language, f"{kind}.subject"):
        raise ValueError(f"no mail of the kind {kind!r}")
    filled = {key: one_line(value) for key, value in values.items()}
    filled["app"] = one_line(config.current().shown_name)
    subject = one_line(_fill(_text(language, f"{kind}.subject"), filled))
    greeting = _fill(_text(language, "greeting"), filled) if filled.get("name") else ""
    body = _fill(_text(language, f"{kind}.body"), filled)
    action = _fill(_text(language, f"{kind}.action"), filled)
    footer = _fill(_text(language, "footer"), filled)
    lines = [line for line in (greeting, body) if line]
    text = "\n\n".join([*lines, *([link] if link else []), footer]) + "\n"
    markup = _html(language, subject, lines, link if kind in WITH_LINK or link else "", action, footer)
    return Letter(recipient, subject, text, markup, kind)


def from_account_mail(
    mail: object, *, language: str, link: str = "", by: str = "", where: str = "", days: int = 0
) -> Letter:
    """A letter for a ``Mail`` of nexkonten (read by its fields, the modules import nothing from each other):
    ``kind``, ``to``, ``username``, ``display_name``, ``hours``, ``new_hint``. ``link`` the app built from the token;
    ``days`` for an invitation; ``where`` the raw User-Agent of a new sign-in (the module names the browser and the
    system from it, nothing else)."""
    kind = str(getattr(mail, "kind", ""))
    if kind == "email_changed" and not getattr(mail, "new_hint", ""):
        kind = "email_removed"
    hours = int(getattr(mail, "hours", 0) or 0)
    values: dict[str, object] = {
        "name": getattr(mail, "display_name", "") or getattr(mail, "username", ""),
        "username": getattr(mail, "username", ""),
        "hint": getattr(mail, "new_hint", ""),
        "by": by,
        "where": describe_browser(where, language) if kind == "new_sign_in" else "",
        "valid": validity(language if language in LANGUAGES else "en", hours=hours, days=days) if hours or days else "",
    }
    return compose(kind, str(getattr(mail, "to", "")), language=language, values=values, link=link)
