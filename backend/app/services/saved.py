"""Saved searches ("Gemerkt" in the side bar, A1): a name and the known parts of the archive's address, for one person.

**What is kept** is the address of the archive's table, never what it found: the search, the vault, the filters (the
filter "Darf weg" and "Frist" too), the order and the size of a page, not the page itself. The parts are the ones of
``frontend/src/lib/archive.ts``; any other part, or a part with a value the archive does not know, is dropped when the
search is saved, and never run. At most ``MAX`` per person; their order is the person's (up, down).

**The number of hits** of each entry is the search of the archive (``services/search.py``: its rights, its words, its
filters, its time limit): it never counts a document the person may not see. An entry whose vault the person cannot see
(any more) shows a hint and no number, whether the vault is still there or not. Someone who switched deadlines off
gets the entry counted as the archive shows it to them, without the filter "Frist", and a hint saying so.

The numbers are kept for ``CACHE_SECONDS`` per person, search, vaults and state of the documents (the feed's counter):
any change to a document, a vault or a share of the person asks again.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date as Date
from urllib.parse import parse_qsl, urlencode

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import error
from ..models import Account, Counter, SavedSearch, Share, VaultMember
from . import changes, deadlines, rights, search, searchtext

#: The most saved searches a person keeps.
MAX = 30
NAME_MAX = 60
QUERY_MAX = 1200
#: How long the number of hits of an entry is kept (seconds).
CACHE_SECONDS = 20.0
#: How long counting all the entries of one list may take together (seconds). One brake of the search pays for the
#: whole list, so the list is bounded like one search: what is not counted by then shows no number this time and is
#: counted with the next list (what was counted is kept meanwhile).
BUDGET_SECONDS = search.MAX_SECONDS

ORDERS = ("-date", "date", "-title", "title", "-sender", "sender", "-amount", "amount")
SIZES = ("25", "50", "100")
DEADLINES = ("open", "overdue", "30", "done")


def _digits(value: str) -> bool:
    return value.isascii() and value.isdigit() and 0 < len(value) <= 10 and 0 < int(value) < 2**31


#: The parts of the archive's address a saved search keeps, each with what it may hold.
KNOWN = {
    "q": lambda v: 0 < len(v) <= searchtext.MAX_LENGTH,
    "vault": lambda v: v == "shared" or _digits(v),
    "kind": _digits,
    "sender": lambda v: 0 < len(v) <= 160,
    "tag": lambda v: 0 < len(v) <= 40,
    "owner": _digits,
    "year": lambda v: len(v) == 4 and v.isascii() and v.isdigit(),
    "deadline": lambda v: v in DEADLINES,
    "keep": lambda v: v == "expired",
    "all": lambda v: v == "1",
    "sort": lambda v: v in ORDERS,
    "n": lambda v: v in SIZES,
}


def clean_query(raw: str) -> str:
    """The known parts of an archive's address (``kind=3&q=strom``), each once, with a value the archive knows, sorted
    and encoded anew. Everything else is dropped. ``nothing_to_keep`` when no part is left."""
    try:
        pairs = parse_qsl(raw.lstrip("?"), keep_blank_values=False, max_num_fields=40)
    except ValueError as exc:
        raise error("invalid_saved_search", "This is not an address of the archive.", 422) from exc
    kept: dict[str, str] = {}
    for key, value in pairs:
        if key in KNOWN and key not in kept and "\x00" not in value and KNOWN[key](value):
            kept[key] = value
    if not kept:
        raise error("nothing_to_keep", "There is no search or filter to keep.", 422)
    out = urlencode(sorted(kept.items()))
    if len(out) > QUERY_MAX:
        raise error("invalid_saved_search", "This search is too long to keep.", 422)
    return out


def clean_name(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise error("invalid_name", "A name cannot hold control characters.", 422)
    name = " ".join(value.split())
    if not name or len(name) > NAME_MAX:
        raise error("invalid_name", f"Use 1 to {NAME_MAX} characters.", 422, max=NAME_MAX)
    return name


@dataclass
class Asked:
    """A saved address as the archive would ask the search: the words, the filters, and what stops it."""

    q: str
    filters: search.Filters
    #: The vault of the filter is not one the person sees (any more): no number.
    no_access: bool
    #: The address has the filter "Frist", which the person switched off: counted without it, as the archive shows it.
    deadlines_off: bool


def asked(db: Session, account: Account, query: str) -> Asked:
    """What ``query`` (a cleaned one) asks the search for, the way ``filtersOf`` in the archive does: what was filed."""
    parts = dict(parse_qsl(query, keep_blank_values=False))
    filters = search.Filters(status="filed", today=deadlines.today_of(account))
    no_access = False
    vault = parts.get("vault", "")
    if vault == "shared":
        filters.via_share = True
    elif vault:
        filters.vault_id = int(vault)
        # A vault the person is not in answers alike, whether it is still there or not.
        no_access = rights.vault_right(db, account.id, filters.vault_id) is None
    if parts.get("kind"):
        filters.kind_id = int(parts["kind"])
    if parts.get("sender"):
        filters.sender = parts["sender"]
    if parts.get("tag"):
        filters.tag = parts["tag"]
    if parts.get("owner"):
        filters.owner_id = int(parts["owner"])
    if parts.get("year"):
        year = int(parts["year"])
        if 1900 <= year <= 2200:
            filters.date_from, filters.date_to = Date(year, 1, 1), Date(year, 12, 31)
    deadlines_off = False
    if parts.get("deadline"):
        if deadlines.wanted(account):
            filters.deadline = 30 if parts["deadline"] == "30" else parts["deadline"]
        else:
            deadlines_off = True
    if parts.get("keep") == "expired":
        filters.keep = "expired"
    return Asked(q=parts.get("q", ""), filters=filters, no_access=no_access, deadlines_off=deadlines_off)


# --- Changing the list ------------------------------------------------------------------------------------------------


def _ordered(db: Session, uid: int) -> list[SavedSearch]:
    return list(db.scalars(select(SavedSearch).where(SavedSearch.user_id == uid)
                           .order_by(SavedSearch.position, SavedSearch.id)))


def entries(db: Session, uid: int) -> list[SavedSearch]:
    return _ordered(db, uid)


def _own(db: Session, uid: int, saved_id: int) -> SavedSearch:
    """The caller's entry; somebody else's answers like one that does not exist."""
    row = db.get(SavedSearch, saved_id)
    if row is None or row.user_id != uid:
        raise error("not_found", "Not found.", 404)
    return row


def create(db: Session, uid: int, name: str, query: str) -> SavedSearch:
    """A new entry at the end of the list. Two saves at the same moment cannot pass ``MAX`` together: the count and the
    insert are one moment under the write lock."""
    name = clean_name(name)
    query = clean_query(query)
    changes.write_lock(db)
    have = _ordered(db, uid)
    if len(have) >= MAX:
        raise error("too_many_saved", f"At most {MAX} saved searches.", 409, max=MAX)
    row = SavedSearch(user_id=uid, name=name, query=query, position=len(have), created_at=clock.now())
    for index, other in enumerate(have):
        other.position = index
    db.add(row)
    db.commit()
    return row


def rename(db: Session, uid: int, saved_id: int, name: str) -> SavedSearch:
    name = clean_name(name)
    changes.write_lock(db)
    row = _own(db, uid, saved_id)
    row.name = name
    db.commit()
    return row


def move(db: Session, uid: int, saved_id: int, by: int) -> list[SavedSearch]:
    """One place up (``by`` -1) or down (+1); the first stays first, the last last. The places are counted anew under
    the write lock, so that two moves at the same moment leave every entry once, in some order of the two."""
    changes.write_lock(db)
    row = _own(db, uid, saved_id)
    have = _ordered(db, uid)
    at = next(index for index, other in enumerate(have) if other.id == row.id)
    to = max(0, min(len(have) - 1, at + by))
    have.insert(to, have.pop(at))
    for index, other in enumerate(have):
        other.position = index
    db.commit()
    return have


def delete(db: Session, uid: int, saved_id: int) -> None:
    changes.write_lock(db)
    row = _own(db, uid, saved_id)
    db.delete(row)
    db.flush()
    for index, other in enumerate(_ordered(db, uid)):
        other.position = index
    db.commit()


# --- The numbers ------------------------------------------------------------------------------------------------------


@dataclass
class Counted:
    #: The number of hits; empty for an entry the person cannot run (a vault they cannot see, a search that failed).
    count: int | None
    #: ``ok``, ``no_access`` (the vault of the filter is not one they see) or ``failed`` (the search could not answer).
    state: str
    deadlines_off: bool


_lock = threading.Lock()
_cache: dict[tuple[object, ...], tuple[float, int]] = {}
#: The clock of the cache, to be replaced in a test.
monotonic = time.monotonic


def forget() -> None:
    """For the tests."""
    with _lock:
        _cache.clear()


def _state_of(db: Session, uid: int) -> tuple[object, ...]:
    """What the numbers of a person depend on besides their searches: the feed's counter (every change to a document
    takes a number), their vaults with their rights, and what is shared with them."""
    seq = db.scalar(select(Counter.value).where(Counter.name == changes.SEQ)) or 0
    vaults = tuple(db.execute(select(VaultMember.vault_id, VaultMember.right)
                              .where(VaultMember.user_id == uid).order_by(VaultMember.vault_id)).all())
    shared = tuple(db.execute(select(func.count(), func.sum(Share.document_id), func.max(Share.document_id))
                              .where(Share.user_id == uid)).one())
    return (int(seq), vaults, shared)


def needs_search(db: Session, account: Account, rows: list[SavedSearch]) -> bool:
    """Whether any number of ``rows`` has to be counted now (none is kept): the caller takes the search's brake then."""
    state = _state_of(db, account.id)
    now = monotonic()
    with _lock:
        for row in rows:
            kept = _cache.get(_key(account, row.query, state))
            if kept is None or now - kept[0] > CACHE_SECONDS:
                return True
    return False


def _key(account: Account, query: str, state: tuple[object, ...]) -> tuple[object, ...]:
    return (account.id, query, deadlines.today_of(account), deadlines.wanted(account), state)


def counts(db: Session, account: Account, rows: list[SavedSearch]) -> dict[int, Counted]:
    """The number of hits of every entry, from the cache where it is fresh, else counted by the search, as long as the
    time for the whole list lasts (``BUDGET_SECONDS``); an entry it did not reach is ``failed`` this time."""
    state = _state_of(db, account.id)
    out: dict[int, Counted] = {}
    began = monotonic()
    for row in rows:
        ask = asked(db, account, row.query)
        if ask.no_access:
            out[row.id] = Counted(count=None, state="no_access", deadlines_off=ask.deadlines_off)
            continue
        key = _key(account, row.query, state)
        now = monotonic()
        with _lock:
            kept = _cache.get(key)
        if kept is not None and now - kept[0] <= CACHE_SECONDS:
            out[row.id] = Counted(count=kept[1], state="ok", deadlines_off=ask.deadlines_off)
            continue
        if now - began > BUDGET_SECONDS:
            out[row.id] = Counted(count=None, state="failed", deadlines_off=ask.deadlines_off)
            continue
        try:
            number = search.counted(db, account.id, ask.q, ask.filters)
        except HTTPException:
            db.rollback()
            out[row.id] = Counted(count=None, state="failed", deadlines_off=ask.deadlines_off)
            continue
        with _lock:
            if len(_cache) > 5000:
                _cache.clear()
            _cache[key] = (now, number)
        out[row.id] = Counted(count=number, state="ok", deadlines_off=ask.deadlines_off)
    return out


__all__ = ["CACHE_SECONDS", "KNOWN", "MAX", "Asked", "Counted", "asked", "clean_name", "clean_query", "counts",
           "create", "delete", "entries", "forget", "move", "needs_search", "rename"]
