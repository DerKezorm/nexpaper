"""Since 1.1.0: the letters of the app itself ("Brief der App"): reports, notifications, reminders, deadlines, notices
to the operators, invitations into spaces, everything an app mailed through a mailer of its own until now (nextasks'
reports and events, nexpaper's deadlines and notices, nexdiary's and nexlore's notices, nexfolk's birthdays). They go
the way the module's own letters go: one outbox, again after 1, 5, 15, 60 and 180 minutes, at once after queuing
(``outbox.queue`` nudges), the app's logo, the language of the account, every header in one line.

The app writes the words (its templates, in the language ``Store.recipient`` names); the module makes the mail:

    to = nexpost.app_letters.recipient(store, account_id)        # None: no address the app mails at
    if to:
        letter = nexpost.app_letters.write(
            to, kind="deadline", subject=..., paragraphs=[...], link=..., action=..., key=f"deadline:{id}:{day}"
        )
        nexpost.outbox.queue(store, letter)                       # or outbox.deliver_now for an answer in the request

Three forms of the body, the app picks:

- ``paragraphs`` (and ``link``/``action``): the module's frame, the same as its own letters (logo, heading, button,
  footer); text and HTML from the same words.
- ``body_html`` beside ``paragraphs``: the app's own HTML (a table of deadlines, a list of tasks) inside the module's
  frame; the app escapes what it puts in.
- ``html``: the app's whole document (nextasks' reports keep their look); ``cid:logo`` in it shows the app's logo.

``text`` replaces the plain text the module would make from ``paragraphs`` (an app's own text template).
``unsubscribe``: the address that ends this kind of mail with one click (RFC 8058: ``List-Unsubscribe`` and
``List-Unsubscribe-Post``), and a link in the footer of the frame. ``unsubscribe_page`` (since E33): the app's page
that asks before it ends anything; the link in the footer and in the text leads there instead (a link checker that
opens every link of a mail must not unsubscribe anybody), the header keeps the one-click address. ``key``: the app's
name for this one mail (``daily:42:2026-11-25``); the outbox takes a letter with a key it holds already only once.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from . import config
from .letters import _html, _text, check_address, language_for, one_line
from .model import Letter, Recipient, Store

#: A kind of the app: lower-case letters, digits, ``_ . : -``; at most 32 (the outbox tables keep it short).
_KIND = re.compile(r"[a-z][a-z0-9_.:-]{0,31}")


def recipient(store: Store, account: object) -> Recipient | None:
    """Where a letter to this account goes (``Store.recipient``): address, language, name, time zone; None when the
    app has no address to mail it at."""
    find = getattr(store, "recipient", None)
    if not callable(find):
        raise RuntimeError("the app's Store has no recipient(account) (nexpost 1.1.0)")
    found = find(account)
    return found if isinstance(found, Recipient) else None


def write(
    to: str | Recipient,
    *,
    kind: str,
    subject: str,
    language: str = "",
    paragraphs: Sequence[str] = (),
    text: str = "",
    body_html: str = "",
    html: str = "",
    link: str = "",
    action: str = "",
    heading: str = "",
    greeting: bool = False,
    footer: str | None = None,
    unsubscribe: str = "",
    unsubscribe_page: str = "",
    key: str = "",
) -> Letter:
    """A letter of the app. ``to`` an address or a ``Recipient`` (its address, its language when ``language`` is not
    given, its name for ``greeting``). ``subject`` in one line; ``heading`` above the paragraphs (default the
    subject); ``footer`` the last line (default "This mail comes from <app>." in the letter's language, "" for
    none). ``ValueError`` for a letter without words, a wrong ``kind``, or both ``html`` and ``body_html``;
    ``MailError`` ``mail_address_invalid`` for a wrong address."""
    if not _KIND.fullmatch(kind):
        raise ValueError(f"kind {kind!r}: lower-case letters, digits, _ . : - (at most 32)")
    if html and body_html:
        raise ValueError("either the app's whole document (html) or its part in the module's frame (body_html)")
    if not (text.strip() or any(part.strip() for part in paragraphs) or html.strip()):
        raise ValueError("a letter needs words: text, paragraphs or html")
    address = to.address if isinstance(to, Recipient) else to
    name = to.name if isinstance(to, Recipient) else ""
    given = language or (to.language if isinstance(to, Recipient) else "")
    words = language_for(given)
    recipient_address = check_address(address)
    values = {"app": one_line(config.current().shown_name), "name": one_line(name)}
    title = one_line(subject)
    if not title:
        raise ValueError("a letter needs a subject")
    hello = _text(words, "greeting").replace("{{name}}", values["name"]) if greeting and name else ""
    closing = _text(words, "footer").replace("{{app}}", values["app"]) if footer is None else footer
    lines = [line for line in (hello, *paragraphs) if line]
    # The link a person follows: the app's page that asks first, else the one-click address (as before E33).
    shown = unsubscribe_page or unsubscribe
    stop = _text(words, "unsubscribe") if shown else ""
    if not text:
        text = (
            "\n\n".join(
                [
                    *lines,
                    *([f"{action}:\n{link}" if action else link] if link else []),
                    *([closing] if closing else []),
                    *([f"{stop}: {shown}"] if shown else []),
                ]
            )
            + "\n"
        )
    if not html:
        html = _html(
            words,
            heading or title,
            lines,
            link,
            action or link,
            closing,
            body_html=body_html,
            unsubscribe=(stop, shown),
        )
    headers: list[tuple[str, str]] = [("Content-Language", (given or words).strip().lower()[:8] or words)]
    if unsubscribe:
        headers += [
            ("List-Unsubscribe", f"<{one_line(unsubscribe, 900)}>"),
            ("List-Unsubscribe-Post", "List-Unsubscribe=One-Click"),
        ]
    return Letter(recipient_address, title, text, html, kind, headers=tuple(headers), key=one_line(key, 120))
