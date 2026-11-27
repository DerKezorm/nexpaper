"""What another app has about one person (since 0.1.13, decisions V49 to V53): nexfolk's card "In den anderen Apps".

A purpose of the catalog with ``person=True`` (``events.about`` in nextime, ``tasks.about`` in nextasks,
``mails.about`` in nexmail, ``documents.about`` in nexpaper) is asked at one fixed place in the host,
``GET /api/connect/about/<purpose>?name=…&mail=…&phone=…``, with the token of the connection. The host's app answers
through its hook (``router(about=…)``) for the areas the connection was given; the module checks the question
(``person_from``), brakes it per connection (``AppConfig.about_per_minute``) and cuts the answer to its small form
(``cleaned``) on both sides:

``{"count": <how many>, "next": {"title", "at"} | null, "last": {"title", "at"} | null, "open": "/path" | null}``

Never contents: a title is at most 200 characters (none at all for a purpose with ``titles=False``, ``mails.about``),
``at`` an ISO date or moment, ``open`` a path in the host (the asking side puts the host's address in front). The
asking side calls ``about()``; it sends only what it names in ``Person``, the name, mail addresses and numbers of the
contact the account looks at (the card and the consent page say so, V53)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .catalog import Purpose
from .config import PREFIX, AppConfig
from .errors import Refused
from .model import AccountId

#: At most this many mail addresses and numbers of one person.
MOST = 10
MAX_MAIL = 254
MAX_PHONE = 40
MAX_NAME = 200
MAX_TITLE = 200
MAX_OPEN = 500
MAX_COUNT = 1_000_000
_PHONE = re.compile(r"[0-9+()./ \-]+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Person:
    """Who the asking side looks at: name, mail addresses, numbers (each may be empty, not all)."""

    name: str = ""
    mails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()


def person_from(pairs: Iterable[tuple[str, str]]) -> Person:
    """The person of a question (``name``, ``mail`` and ``phone`` given any number of times), or ``person_invalid``:
    nothing named, more than ``MOST`` addresses or numbers, one too long, a mail without ``@``, a number with letters,
    anything else in the question."""
    name, mails, phones = "", [], []
    for key, raw in pairs:
        value = raw.strip()
        if key == "name" and not name and len(value) <= MAX_NAME and not _CONTROL.search(value):
            name = value
        elif key == "mail" and 3 <= len(value) <= MAX_MAIL and "@" in value and not _CONTROL.search(value):
            mails.append(value.lower())
        elif key == "phone" and 0 < len(value) <= MAX_PHONE and _PHONE.fullmatch(value):
            phones.append(value)
        elif value or key not in ("name", "mail", "phone"):
            raise Refused("person_invalid")
    if (not name and not mails and not phones) or len(mails) > MOST or len(phones) > MOST:
        raise Refused("person_invalid")
    return Person(name=name, mails=tuple(dict.fromkeys(mails)), phones=tuple(dict.fromkeys(phones)))


def person_params(person: Person) -> dict[str, list[str]]:
    """The question for ``person``, as the host reads it."""
    found: dict[str, list[str]] = {}
    if person.name:
        found["name"] = [person.name]
    if person.mails:
        found["mail"] = list(person.mails)
    if person.phones:
        found["phone"] = list(person.phones)
    return found


def _moment(raw: Any, purpose: Purpose) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    at = raw.get("at")
    if not isinstance(at, str) or not 0 < len(at) <= 40:
        return None
    try:
        (date if len(at) == 10 else datetime).fromisoformat(at)
    except ValueError:
        return None
    title = raw.get("title")
    title = _CONTROL.sub(" ", title).strip()[:MAX_TITLE] if isinstance(title, str) and purpose.titles else ""
    return {"title": title, "at": at}


def _open(raw: Any) -> str | None:
    if not isinstance(raw, str) or not 1 <= len(raw) <= MAX_OPEN:
        return None
    if not raw.startswith("/") or raw.startswith("//") or "\\" in raw or _CONTROL.search(raw) or " " in raw:
        return None
    return raw


def cleaned(raw: Any, purpose: Purpose) -> dict[str, Any]:
    """The answer in its small form, whatever came (anything that does not fit is left out, never passed on)."""
    data = raw if isinstance(raw, dict) else {}
    count = data.get("count")
    count = count if isinstance(count, int) and not isinstance(count, bool) and 0 <= count <= MAX_COUNT else 0
    return {
        "count": count,
        "next": _moment(data.get("next"), purpose),
        "last": _moment(data.get("last"), purpose),
        "open": _open(data.get("open")),
    }


def about(
    store: Any, config: AppConfig, account_id: AccountId, partner: str, purpose: str, person: Person, now: datetime
) -> dict[str, Any] | None:
    """The asking side (nexfolk): what ``partner`` has about ``person`` for ``purpose``, its ``open`` with the
    partner's address in front; ``None`` when the partner answered with anything but its small form (it does not tell
    about people this way, or it brakes). Raises ``Refused`` like ``call``: ``not_connected``, ``unreachable``,
    ``refused``, ``resting``, ``partner_off``, and ``purpose_missing`` for a purpose this app does not use there."""
    from .connect import call

    if purpose not in config.catalog.uses(config.app_name, partner):
        raise Refused("purpose_missing")
    granted = config.catalog.purpose(partner, purpose)
    if not granted.person:
        raise Refused("purpose_missing")
    answer = call(
        store, config, account_id, partner, "GET", f"{PREFIX}/about/{purpose}", now, params=person_params(person)
    )
    if answer.status != 200 or not isinstance(answer.data, dict):
        return None
    found = cleaned(answer.data, granted)
    connection = store.connection(account_id, partner)
    if found["open"] and connection is not None:
        found["open"] = connection.partner_base + found["open"]
    return found
