"""Rules: what nexpaper fills in by itself when a document arrives.

A rule has **conditions** (all must hold) and **what follows**, and rules are tried in their order: for a field, the
first rule that sets it wins; tags add up. A rule that applied counts a hit, once per document.

* Conditions: the sender is or contains, the text contains, the kind is, the source is, the amount is over or under.
  A condition on a text names up to ``MAX_VALUES`` words, one of which must be found.
* What follows: the vault, the kind, a tag, the sender, the title (a pattern with ``{sender}``, ``{kind}``,
  ``{date}``, ``{month}``, ``{year}``, ``{amount}``, also in German: ``{absender}``, ``{art}``, ``{datum}``,
  ``{monat}``, ``{jahr}``, ``{betrag}``).

**Whose rules.** A rule belongs to one vault and applies to the documents that arrive there; the people who manage the
vault make and change them (for their own vault every person does). A rule without a vault applies to every document
on the server; only the operator makes those (the operator is the one who sets the server up for everybody). A rule
that moves documents names a vault its maker may add to, and it moves a document only into a vault where the person
the document belongs to may add documents too: otherwise that part of the rule is left out and the document stays
where its person wanted it. A rule for the whole server never touches a document in the personal vault of somebody
else (no kind, tag, sender, title or move: ``applying``), and a rule never moves a document out of a vault its maker
cannot see. It counts a hit only for a document its maker may see: the counter tells nobody what is in a document
they cannot open.

**Safe to match.** The words of a rule are compared as plain text (case and accents folded, Unicode normalised), never
as a pattern a person wrote: no regular expression, so nothing can make the comparison take long. The text a rule
looks at is the first ``TEXT_CHARS`` characters of the document. A rule has at most ``MAX_CONDITIONS`` conditions and
``MAX_ACTIONS`` parts that follow, each word at most ``VALUE_MAX`` characters; a vault has at most ``MAX_PER_VAULT``
rules and the server ``MAX_RULES``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date as Date
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import error
from ..models import EDIT, MANAGE, OPERATOR, Account, Kind, Rule, Vault, VaultMember
from ..names import name_key
from . import catalog, rights

MAX_RULES = 500
MAX_PER_VAULT = 100
MAX_CONDITIONS = 5
MAX_ACTIONS = 8
MAX_VALUES = 5
VALUE_MAX = 100
PATTERN_MAX = 120
TEXT_CHARS = 200_000
AMOUNT_LIMIT = 10**12

SOURCES = ("upload", "camera", "mail", "folder", "share", "paperless", "api")
CONDITIONS = {
    "sender": ("is", "contains"),
    "text": ("contains",),
    "kind": ("is",),
    "source": ("is",),
    "amount": ("over", "under"),
}
ACTIONS = ("vault", "kind", "tag", "sender", "title")
PLACEHOLDERS = {
    "sender": "sender", "absender": "sender", "kind": "kind", "art": "kind", "date": "date", "datum": "date",
    "month": "month", "monat": "month", "year": "year", "jahr": "year", "amount": "amount", "betrag": "amount",
}
_PLACEHOLDER = re.compile(r"\{([a-z]{1,10})\}")
MONTH_NAMES = {
    "de": ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November",
           "Dezember"),
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"),
}


def compare_form(value: str) -> str:
    """How a word of a rule and a text are compared: Unicode normalised, accents gone, case folded, spaces joined."""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(value.casefold().split())


def _word(value: Any, limit: int = VALUE_MAX) -> str:
    if not isinstance(value, str):
        raise error("invalid_rule", "A rule holds words, numbers and names only.", 422)
    if any(unicodedata.category(char) in ("Cc", "Cf") for char in value):
        raise error("invalid_rule", "A rule cannot hold control characters.", 422)
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > limit:
        raise error("invalid_rule", f"Use 1 to {limit} characters.", 422, limit=limit)
    return cleaned


def _whole(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or abs(value) > AMOUNT_LIMIT:
        raise error("invalid_rule", "This is no amount.", 422)
    return value


# --- Checking what a person sends -----------------------------------------------------------------------------------


def _kind_for_rule(db: Session, kind_id: int, vault_id: int | None) -> int:
    """The kind a rule may name: one of the server's, and for a rule of a vault one of that vault's. A rule for the
    whole server names the server's kinds only (a kind of a vault is that vault's business)."""
    kind = db.get(Kind, kind_id)
    catalog.ensure_kinds(db)
    if kind is None or (kind.vault_id is not None and kind.vault_id != vault_id):
        raise error("kind_unknown", "No such kind.", 422)
    return kind.id


def clean_when(db: Session, raw: Any, vault_id: int | None = None) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_CONDITIONS:
        raise error("invalid_rule", f"A rule has 1 to {MAX_CONDITIONS} conditions.", 422)
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise error("invalid_rule", "A condition names a field, a comparison and a value.", 422)
        name, op = item.get("field"), item.get("op")
        if name not in CONDITIONS or op not in CONDITIONS[name]:
            raise error("invalid_rule", "There is no such condition.", 422)
        if name in ("sender", "text"):
            values = item.get("values")
            if not isinstance(values, list) or not 1 <= len(values) <= MAX_VALUES:
                raise error("invalid_rule", f"A condition names 1 to {MAX_VALUES} words.", 422)
            out.append({"field": name, "op": op, "values": [_word(v) for v in values]})
        elif name == "kind":
            out.append({"field": name, "op": op, "value": _kind_for_rule(db, _whole(item.get("value")), vault_id)})
        elif name == "source":
            if item.get("value") not in SOURCES:
                raise error("invalid_rule", "There is no such source.", 422)
            out.append({"field": name, "op": op, "value": item["value"]})
        else:
            out.append({"field": name, "op": op, "value": _whole(item.get("value"))})
    return out


def clean_then(db: Session, uid: int, raw: Any, vault_id: int | None = None) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_ACTIONS:
        raise error("invalid_rule", f"A rule does 1 to {MAX_ACTIONS} things.", 422)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or item.get("field") not in ACTIONS:
            raise error("invalid_rule", "A rule sets the vault, the kind, a tag, the sender or the title.", 422)
        name = item["field"]
        if name != "tag" and name in seen:
            raise error("invalid_rule", "A rule sets each field once.", 422)
        seen.add(name)
        value = item.get("value")
        if name == "vault":
            # Only into a vault its maker may add documents to.
            target = _whole(value)
            rights.require_vault(db, uid, target, EDIT)
            out.append({"field": name, "value": target})
        elif name == "kind":
            out.append({"field": name, "value": _kind_for_rule(db, _whole(value), vault_id)})
        elif name == "tag":
            out.append({"field": name, "value": catalog.clean_word(_word(value, catalog.TAG_MAX), catalog.TAG_MAX,
                                                                   "invalid_tag")})
        elif name == "sender":
            out.append({"field": name, "value": catalog.clean_word(_word(value, catalog.SENDER_MAX),
                                                                   catalog.SENDER_MAX, "invalid_sender")})
        else:
            pattern = _word(value, PATTERN_MAX)
            for found in _PLACEHOLDER.findall(pattern):
                if found not in PLACEHOLDERS:
                    raise error("invalid_rule", "The title knows {sender}, {kind}, {date}, {month}, {year} and "
                                "{amount}.", 422)
            out.append({"field": name, "value": pattern})
    return out


# --- Who may do what ------------------------------------------------------------------------------------------------


def _is_operator(db: Session, uid: int) -> bool:
    return db.scalar(select(Account.role).where(Account.id == uid)) == OPERATOR


def _may_manage(db: Session, uid: int, vault_id: int | None) -> bool:
    if vault_id is None:
        return _is_operator(db, uid)
    return rights.vault_right(db, uid, vault_id) == MANAGE


def visible(db: Session, uid: int) -> list[Rule]:
    """The rules the caller may change: of the vaults they manage, and the server's when they are the operator. In
    their order (the server's first, then per vault)."""
    managed = select(VaultMember.vault_id).where(VaultMember.user_id == uid, VaultMember.right == MANAGE)
    clause = Rule.vault_id.in_(managed)
    if _is_operator(db, uid):
        clause = or_(clause, Rule.vault_id.is_(None))
    return list(db.scalars(select(Rule).where(clause).order_by(Rule.vault_id.is_not(None), Rule.vault_id,
                                                               Rule.position, Rule.id)))


def _own(db: Session, uid: int, rule_id: int) -> Rule:
    """A rule the caller may change; any other answers like one that does not exist."""
    rule = db.get(Rule, rule_id)
    if rule is None or not _may_manage(db, uid, rule.vault_id):
        raise error("not_found", "Not found.", 404)
    return rule


def create(db: Session, uid: int, vault_id: int | None, when: Any, then: Any, on: bool = True) -> Rule:
    from . import changes

    changes.write_lock(db)
    if vault_id is not None:
        rights.require_vault(db, uid, vault_id, MANAGE)
    elif not _is_operator(db, uid):
        raise error("forbidden", "Only the operator makes rules for the whole server.", 403)
    conditions = clean_when(db, when, vault_id)
    actions = clean_then(db, uid, then, vault_id)
    total = db.scalar(select(func.count()).select_from(Rule)) or 0
    here = db.scalar(select(func.count()).select_from(Rule).where(
        Rule.vault_id.is_(None) if vault_id is None else Rule.vault_id == vault_id)) or 0
    if total >= MAX_RULES or here >= MAX_PER_VAULT:
        raise error("too_many_rules", "There are as many rules as there may be. Delete one first.", 409)
    last = db.scalar(select(func.max(Rule.position)).where(
        Rule.vault_id.is_(None) if vault_id is None else Rule.vault_id == vault_id))
    rule = Rule(vault_id=vault_id, created_by=uid, position=(last or 0) + 1, on=on, hits=0, when=conditions,
                then=actions, created_at=clock.now())
    db.add(rule)
    db.commit()
    return rule


def update(db: Session, uid: int, rule_id: int, *, when: Any = None, then: Any = None, on: bool | None = None,
           position: int | None = None) -> Rule:
    from . import changes

    changes.write_lock(db)
    rule = _own(db, uid, rule_id)
    if when is not None:
        rule.when = clean_when(db, when, rule.vault_id)
    if then is not None:
        rule.then = clean_then(db, uid, then, rule.vault_id)
    if on is not None:
        rule.on = on
    if position is not None:
        _move(db, rule, position)
    db.commit()
    return rule


def _move(db: Session, rule: Rule, position: int) -> None:
    """To place ``position`` (counted from 1) among the rules of its vault; the others close up."""
    siblings = list(db.scalars(select(Rule).where(
        Rule.vault_id.is_(None) if rule.vault_id is None else Rule.vault_id == rule.vault_id)
        .order_by(Rule.position, Rule.id)))
    siblings.remove(rule)
    siblings.insert(max(0, min(position - 1, len(siblings))), rule)
    for index, item in enumerate(siblings, start=1):
        item.position = index


def delete(db: Session, uid: int, rule_id: int) -> None:
    from . import changes

    changes.write_lock(db)
    db.delete(_own(db, uid, rule_id))
    db.commit()


# --- Applying -------------------------------------------------------------------------------------------------------


@dataclass
class Subject:
    """What a rule looks at: the document as it would be proposed so far."""

    sender: str
    text: str
    kind_id: int | None
    source: str
    amount: int | None
    #: Filled once: the text in its compared form.
    _folded: str = field(default="", repr=False)

    def folded_text(self) -> str:
        if not self._folded:
            self._folded = compare_form(self.text[:TEXT_CHARS])
        return self._folded


def holds(condition: dict[str, Any], subject: Subject) -> bool:
    name, op = condition.get("field"), condition.get("op")
    if name == "sender":
        mine = compare_form(subject.sender)
        if not mine:
            return False
        words = [compare_form(v) for v in condition.get("values") or [] if isinstance(v, str)]
        return any(mine == w for w in words) if op == "is" else any(w and w in mine for w in words)
    if name == "text":
        words = [compare_form(v) for v in condition.get("values") or [] if isinstance(v, str)]
        return any(w and w in subject.folded_text() for w in words)
    if name == "kind":
        return subject.kind_id is not None and subject.kind_id == condition.get("value")
    if name == "source":
        return subject.source == condition.get("value")
    if name == "amount":
        value = condition.get("value")
        if subject.amount is None or not isinstance(value, int):
            return False
        return subject.amount > value if op == "over" else subject.amount < value
    return False


def matches(rule: Rule, subject: Subject) -> bool:
    conditions = rule.when if isinstance(rule.when, list) else []
    return bool(conditions) and all(isinstance(c, dict) and holds(c, subject) for c in conditions)


def applying(db: Session, arrival_vault_id: int) -> list[Rule]:
    """The rules that are on for a document that arrived in this vault: the server's first, then the vault's. **A rule
    for the whole server never reaches into the personal vault of somebody else** (not for a kind, a tag, a sender or
    a title, let alone a move): what lands there is nobody's business but its person's. The operator's own personal
    vault is the one exception, for the rules the operator made."""
    found = list(db.scalars(select(Rule).where(Rule.on.is_(True), or_(Rule.vault_id.is_(None),
                                                                     Rule.vault_id == arrival_vault_id))
                            .order_by(Rule.vault_id.is_not(None), Rule.position, Rule.id)))
    personal_of = db.scalar(select(Vault.personal_of).where(Vault.id == arrival_vault_id))
    if personal_of is None:
        return found
    return [rule for rule in found if rule.vault_id is not None or rule.created_by == personal_of]


@dataclass
class Outcome:
    """What the rules set: per field the value, and the rules that applied."""

    vault_id: int | None = None
    kind_id: int | None = None
    sender: str | None = None
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    applied: list[int] = field(default_factory=list)


def _may_move(db: Session, rule: Rule, owner_id: int | None, arrival_vault_id: int, target: int) -> bool:
    """Whether a rule may move a document that arrived in ``arrival_vault_id`` to ``target``: the person the document
    belongs to may add to the target, and the rule's maker may see the vault it arrived in and still add to the
    target. A rule never takes a document from a vault its maker cannot see (the operator's rules leave the vaults of
    other people alone)."""
    if owner_id is None or db.get(Vault, target) is None:
        return False
    if not rights.at_least(rights.vault_right(db, owner_id, target), EDIT):
        return False
    maker = rule.created_by
    if maker is None or rights.vault_right(db, maker, arrival_vault_id) is None:
        return False
    return rights.at_least(rights.vault_right(db, maker, target), EDIT)


def _kind_applies(db: Session, kind_id: int, rule_vault_id: int | None) -> bool:
    """A kind that still exists and that the rule may set: one of the server's, or of the vault the rule belongs to (a
    rule of the whole server sets the server's only, whatever stands in it)."""
    kind = db.get(Kind, kind_id)
    return kind is not None and (kind.vault_id is None or kind.vault_id == rule_vault_id)


def evaluate(db: Session, rules: list[Rule], subject: Subject, owner_id: int | None,
             arrival_vault_id: int) -> Outcome:
    """Every rule in order against ``subject``: the first to set a field wins. A move the rule may not make
    (``_may_move``) is left out, as is any part that names what is gone (a deleted kind or vault)."""
    out = Outcome()
    for rule in rules:
        if not matches(rule, subject):
            continue
        out.applied.append(rule.id)
        for action in rule.then if isinstance(rule.then, list) else []:
            if not isinstance(action, dict):
                continue
            name, value = action.get("field"), action.get("value")
            if name == "vault" and out.vault_id is None and isinstance(value, int):
                if _may_move(db, rule, owner_id, arrival_vault_id, value):
                    out.vault_id = value
            elif name == "kind" and out.kind_id is None and isinstance(value, int) and _kind_applies(
                    db, value, rule.vault_id):
                out.kind_id = value
            elif name == "sender" and out.sender is None and isinstance(value, str):
                out.sender = value
            elif name == "title" and out.title is None and isinstance(value, str):
                out.title = value
            elif name == "tag" and isinstance(value, str) and name_key(value) not in {name_key(t) for t in out.tags}:
                out.tags.append(value)
    return out


def count_hits(db: Session, rule_ids: list[int], document_id: int) -> None:
    """One hit for each rule that applied to a document, counted only when the rule's maker may see the document: the
    counter of a rule tells its maker nothing about documents they cannot see (the operator's rule for the whole server
    and a text in somebody's own vault)."""
    if not rule_ids:
        return
    now = clock.now()
    for rule in db.scalars(select(Rule).where(Rule.id.in_(rule_ids))):
        if rule.created_by is None or rights.access_to(db, rule.created_by, document_id) is None:
            continue
        rule.hits += 1
        rule.last_hit_at = now


def render_title(pattern: str, *, sender: str, kind: str, day: Date | None, amount: int | None, currency: str,
                 language: str) -> str:
    """A title from a pattern: each known placeholder replaced by its value (empty when there is none), nothing else
    touched; the result cleaned and cut to a title's length."""
    names = MONTH_NAMES.get(language, MONTH_NAMES["en"])

    def value(match: re.Match[str]) -> str:
        what = PLACEHOLDERS.get(match.group(1))
        if what == "sender":
            return sender
        if what == "kind":
            return kind
        if what == "date":
            return (day.strftime("%d.%m.%Y") if language == "de" else day.isoformat()) if day else ""
        if what == "month":
            return names[day.month - 1] if day else ""
        if what == "year":
            return str(day.year) if day else ""
        if what == "amount":
            if amount is None:
                return ""
            whole, part = divmod(abs(amount), 100)
            sign = "-" if amount < 0 else ""
            return (f"{sign}{whole:,}".replace(",", ".") + f",{part:02d} {currency}" if language == "de"
                    else f"{currency} {sign}{whole:,}.{part:02d}").strip()
        return match.group(0)

    return " ".join(_PLACEHOLDER.sub(value, pattern).split())[:200]


def repoint_kind(db: Session, old_id: int, new_id: int) -> None:
    """After two kinds were merged: the rules that named the old one name the other. The caller commits."""

    def moved(parts: Any) -> tuple[list[Any], bool]:
        out: list[Any] = []
        changed = False
        for part in parts if isinstance(parts, list) else []:
            if isinstance(part, dict) and part.get("field") == "kind" and part.get("value") == old_id:
                part = {**part, "value": new_id}
                changed = True
            out.append(part)
        return out, changed

    for rule in db.scalars(select(Rule)):
        when, when_changed = moved(rule.when)
        then, then_changed = moved(rule.then)
        # New lists, not changes inside the old ones: a JSON column does not notice those.
        if when_changed:
            rule.when = when
        if then_changed:
            rule.then = then


def described(rule: Rule) -> dict[str, Any]:
    return {"id": rule.id, "vault_id": rule.vault_id, "position": rule.position, "on": rule.on, "hits": rule.hits,
            "last_hit_at": rule.last_hit_at, "when": rule.when, "then": rule.then, "created_at": rule.created_at}


__all__ = ["Outcome", "Subject", "applying", "compare_form", "count_hits", "create", "delete", "evaluate", "holds",
           "matches", "render_title", "repoint_kind", "update", "visible"]
