"""Sorting a document in: the fields of a new document proposed, each with where the proposal came from.

When the worker has read a new document (``processing.FINISHERS``, under the write lock, before the document goes to
the inbox), nexpaper fills in its fields from what it knows, and notes per field where it came from
(``Document.suggest``): ``einvoice``, ``rule``, ``last_time``, ``text``, ``ai``, ``default``. The first that knows a
field wins, in this order:

1. **The e-invoice** (``services/einvoices.py``): exact data, nothing beats it.
2. **The rules** (``services/rules.py``), the person's own and the operator's.
3. **As last time**: a filed document of the same person with the same IBAN, VAT id, customer number or letterhead
   (``last_time``), its sender, kind and tags. Only documents the person may see are looked at, and the rights are in
   the query that finds them.
4. **From the text** (``services/textfacts.py``): the date, the due date and the amount.
5. **The AI** (``services/ai_proposals.py``), later, as a job of its own: title, sender, kind, date and amount, where
   nothing above knew them.

These are proposals only: the document waits in the inbox, and it is filed when a person says so. A field the person
changed (``documents.update_fields``) is theirs (``person``) and nothing proposed later touches it. The history notes
which fields were proposed from where, never their values.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date as Date
from typing import Any

from sqlalchemy import Integer, bindparam, column, delete, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from .. import clock
from ..models import (
    FILED,
    PROCESSING,
    Account,
    Document,
    DocumentDate,
    DocumentTag,
    EInvoice,
    Kind,
    Sender,
    Tag,
    Vault,
    Version,
    VersionText,
)
from . import catalog, changes, documents, einvoices, rights, rules, searchtext, textfacts

logger = logging.getLogger("nexpaper.sorting")

EINVOICE, RULE, LAST_TIME, TEXT, AI = "einvoice", "rule", "last_time", "text", "ai"
DEFAULT, PERSON = "default", "person"
#: The order in which the origins are asked for a field: the first that knows it wins.
PRIORITY = (EINVOICE, RULE, LAST_TIME, TEXT, AI)
FIELDS = ("title", "sender", "kind", "date", "amount", "dates", "tags", "vault")
PROPOSED = "proposed"
#: Earlier documents a sign of the sender is looked up in, the newest first.
LOOK_BACK = 25
#: The words in front of a customer number.
_CUSTOMER = re.compile(
    r"(?:kundennummer|kunden-nr\.?|kundennr\.?|kd\.?-?nr\.?|vertragskonto|vertragsnummer|mitgliedsnummer|"
    r"versicherungsnummer|customer[ \t]+(?:no\.?|number|id)|account[ \t]+(?:no\.?|number))"
    r"[ \t]{0,5}:?[ \t]{0,5}(?:\r?\n[ \t]{0,5})?"
    r"([A-Za-z0-9][A-Za-z0-9./ -]{2,24}[A-Za-z0-9])", re.IGNORECASE)
_IBAN = re.compile(r"\b([A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,4})?)\b")
_VAT = re.compile(r"\b((?:DE|AT|ATU|CH|NL|FR|BE|LU|IT|ES|PL|DK|SE|FI|IE|CZ)\s?[A-Z0-9]{8,12})\b")


# --- As last time -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Sign:
    """Something that tells a sender: an IBAN, a VAT id, a customer number, a letterhead."""

    kind: str
    value: str


def signs_of(text: str, invoice: EInvoice | None = None) -> list[Sign]:
    """The signs of a sender in a text (and its e-invoice), the surest first."""
    head = text[:20_000]
    found: list[Sign] = []
    ibans = [invoice.iban] if invoice is not None and invoice.iban else []
    ibans += [match.group(1) for match in _IBAN.finditer(head)]
    from ..einvoice_reader import clean_iban

    for raw in ibans:
        iban = clean_iban(raw)
        if iban and Sign("iban", iban) not in found:
            found.append(Sign("iban", iban))
    vats = [invoice.seller_vat] if invoice is not None and invoice.seller_vat else []
    vats += [match.group(1) for match in _VAT.finditer(head)]
    for raw in vats:
        vat = re.sub(r"\s+", "", raw).upper()
        if sum(char.isdigit() for char in vat) >= 8 and Sign("vat", vat) not in found:
            found.append(Sign("vat", vat))
    for match in _CUSTOMER.finditer(head):
        number = " ".join(match.group(1).split())
        if sum(char.isdigit() for char in number) >= 3 and Sign("customer", number) not in found:
            found.append(Sign("customer", number))
    first = next((line.strip() for line in head.split("\n") if line.strip()), "")
    if len(first) >= 10 and len(first.split()) >= 2:
        found.append(Sign("head", " ".join(first.split())[:120]))
    return found[:8]


def _compact(value: str) -> str:
    return "".join(rules.compare_form(value).split())


def _carries(text: str, sign: Sign) -> bool:
    """Whether a text carries the sign: spaces aside for the numbers, the first line for the letterhead."""
    if sign.kind == "head":
        first = next((line.strip() for line in text.split("\n") if line.strip()), "")
        return rules.compare_form(first)[:120] == rules.compare_form(sign.value)
    return _compact(sign.value) in _compact(text[:40_000])


@dataclass
class Previous:
    sender: str
    kind_id: int | None
    tags: list[str]


def last_time(db: Session, document: Document, text: str, invoice: EInvoice | None) -> Previous | None:
    """The sender, kind and tags of the newest filed document of the same person that carries the same sign of its
    sender, among the documents the person may see. Nothing without an owner or a sign."""
    if document.owner_id is None:
        return None
    signs = signs_of(text, invoice)
    if not signs:
        return None
    base = (
        select(Document.id, Document.sender_id, Document.kind_id, VersionText.text)
        .join(Version, (Version.document_id == Document.id) & (Version.n == Document.current_version))
        .join(VersionText, VersionText.version_id == Version.id)
        .where(Document.status == FILED, Document.sender_id.is_not(None), Document.id != document.id,
               rights.visible_clause(document.owner_id))
    )
    for sign in signs:
        parts = searchtext.tokens(sign.value)[:12]
        if not parts:
            continue
        expression = "{text} : " + searchtext.fts_string(parts, False)
        lookup = sql_text("SELECT rowid FROM doc_fts WHERE doc_fts MATCH :expr").bindparams(
            bindparam("expr", value=expression)).columns(column("rowid", Integer))
        rows = db.execute(base.where(Document.id.in_(lookup)).order_by(Document.added_at.desc(), Document.id.desc())
                          .limit(LOOK_BACK)).all()
        for _document_id, sender_id, kind_id, body in rows:
            if not _carries((body or "").replace("\f", "\n"), sign):
                continue
            sender = db.get(Sender, sender_id)
            if sender is None:
                continue
            tags = list(db.scalars(select(Tag.name).join(DocumentTag, DocumentTag.tag_id == Tag.id)
                                   .where(DocumentTag.document_id == _document_id).order_by(Tag.name)))
            return Previous(sender=sender.name, kind_id=kind_id, tags=tags[:10])
    return None


# --- Proposing ----------------------------------------------------------------------------------------------------


@dataclass
class Proposal:
    """Per field the value and where it came from."""

    values: dict[str, Any] = field(default_factory=dict)
    origins: dict[str, str] = field(default_factory=dict)

    def offer(self, name: str, origin: str, value: Any) -> None:
        if value is None or value == "" or value == []:
            return
        if name not in self.values:
            self.values[name] = value
            self.origins[name] = origin


def _kind_named(db: Session, vault_id: int | None, key: str = "", name: str = "") -> int | None:
    """A kind a document of the vault may have: by the key of one that comes with nexpaper, or by its name (the server's
    kinds first, then the vault's own). Never a kind of another vault."""
    if key:
        found = db.scalar(select(Kind.id).where(Kind.key == key, Kind.vault_id.is_(None)))
        if found:
            return found
    if name:
        wanted = rules.compare_form(name)
        for kind_id, kind_name in db.execute(select(Kind.id, Kind.name).where(catalog.in_scope(vault_id))
                                             .order_by(Kind.vault_id.is_not(None), Kind.position, Kind.id)):
            if rules.compare_form(kind_name) == wanted:
                return kind_id
    return None


def _usable_kind(db: Session, kind_id: int | None, vault_id: int, *, bring_from: int | None = None) -> int | None:
    """``kind_id`` when a document of ``vault_id`` may have that kind; else the kind of the same name there; else, when
    the kind is of the vault ``bring_from`` (a rule of that vault moved the document away), a kind of that name made in
    ``vault_id``; else nothing. A proposal never names a kind of a vault the document is not in."""
    if not kind_id:
        return None
    kind = db.get(Kind, kind_id)
    if kind is None:
        return None
    if kind.vault_id is None or kind.vault_id == vault_id:
        return kind.id
    found = catalog.kind_called(db, vault_id, kind.name_key)
    if found is not None:
        return found.id
    if bring_from is not None and kind.vault_id == bring_from:
        return catalog.kind_in_vault(db, vault_id, kind.created_by, kind.name, kind.hue).id
    return None


def _language(db: Session, document: Document) -> str:
    owner = db.get(Account, document.owner_id) if document.owner_id else None
    return "en" if owner is not None and (owner.language or "").lower().startswith("en") else "de"


def _default_vault(db: Session, document: Document) -> bool:
    """Whether the document lies where its person's uploads go by default."""
    from ..routers.auth import profile_of

    owner = db.get(Account, document.owner_id) if document.owner_id else None
    if owner is None:
        return False
    chosen = profile_of(owner.profile)["default_vault"]
    if chosen is not None:
        return chosen == document.vault_id
    vault = db.get(Vault, document.vault_id)
    return vault is not None and vault.personal_of == owner.id


INVOICE_TITLE = {"de": ("Rechnung", "Gutschrift"), "en": ("Invoice", "Credit note")}


def propose(db: Session, document: Document, text: str, *, invoice: EInvoice | None = None,
            ai: dict[str, Any] | None = None, today: Date | None = None, later: bool = False) -> list[str]:
    """Works out every field of ``document`` anew from what is known and writes the proposals that changed, in the
    caller's transaction (the caller holds the write lock). Fields the person set stay as they are. Returns the fields
    that changed."""
    stored = document.suggest if isinstance(document.suggest, dict) else {}
    origins_before = {k: v for k, v in stored.items() if isinstance(k, str) and not k.startswith("_")
                      and isinstance(v, str)}
    human = {name for name, origin in origins_before.items() if origin == PERSON}
    arrival = stored.get("_from") if isinstance(stored.get("_from"), int) else document.vault_id
    counted = [r for r in stored.get("_rules", []) if isinstance(r, int)] if isinstance(stored.get("_rules"), list) \
        else []
    ai = ai if ai is not None else (stored.get("_ai") if isinstance(stored.get("_ai"), dict) else None)
    language = _language(db, document)
    proposal = Proposal()

    # 1. The e-invoice.
    if invoice is not None:
        words = INVOICE_TITLE[language]
        heading = words[1] if invoice.credit_note else words[0]
        proposal.offer("title", EINVOICE, f"{heading} {invoice.number}".strip() if invoice.number else "")
        proposal.offer("sender", EINVOICE, invoice.seller)
        proposal.offer("kind", EINVOICE, _kind_named(db, None, key="invoice"))
        proposal.offer("date", EINVOICE, invoice.issued)
        proposal.offer("amount", EINVOICE, einvoices.amount_of(invoice))
        proposal.offer("currency", EINVOICE, invoice.currency)
        proposal.offer("dates", EINVOICE, invoice.due)
    previous = last_time(db, document, text, invoice)
    facts = textfacts.read(text, today or clock.now().date())
    ai_values = _ai_values(db, ai, arrival)

    def vault_now() -> int:
        """The vault the document will be in: where a rule moves it (unless a person put it there), else where it is."""
        if "vault" in proposal.values and "vault" not in human:
            return int(proposal.values["vault"])
        return document.vault_id

    def offer_kind(origin: str, kind_id: int | None) -> None:
        proposal.offer("kind", origin, _usable_kind(db, kind_id, vault_now(), bring_from=arrival if origin == RULE
                                                    else None))

    # 2. The rules, against the document as it would be without them.
    def best(name: str) -> Any:
        if name in proposal.values:
            return proposal.values[name]
        if name == "sender" and previous is not None:
            return previous.sender
        if name == "kind" and previous is not None and previous.kind_id:
            return previous.kind_id
        if name == "amount" and facts.amount is not None:
            return facts.amount
        return ai_values.get(name)

    subject = rules.Subject(sender=str(best("sender") or ""), text=text, kind_id=best("kind"),
                            source=document.source, amount=best("amount"))
    outcome = rules.evaluate(db, rules.applying(db, arrival), subject, document.owner_id, arrival)
    proposal.offer("vault", RULE, outcome.vault_id)
    proposal.offer("sender", RULE, outcome.sender)
    offer_kind(RULE, outcome.kind_id)
    rule_title = outcome.title

    # 3. As last time.
    if previous is not None:
        proposal.offer("sender", LAST_TIME, previous.sender)
        offer_kind(LAST_TIME, previous.kind_id)
    tags = list(outcome.tags)
    tag_origin = RULE if tags else LAST_TIME
    if previous is not None:
        keys = {rules.compare_form(t) for t in tags}
        tags += [t for t in previous.tags if rules.compare_form(t) not in keys]
    proposal.offer("tags", tag_origin, tags[:catalog.MAX_TAGS_PER_DOCUMENT])

    # 4. From the text.
    proposal.offer("date", TEXT, facts.date)
    proposal.offer("amount", TEXT, facts.amount)
    if facts.amount is not None and "currency" not in proposal.values:
        proposal.offer("currency", TEXT, facts.currency)
    proposal.offer("dates", TEXT, facts.due)

    # 5. The AI.
    for name in ("title", "sender", "date", "amount"):
        proposal.offer(name, AI, ai_values.get(name))
    if isinstance(ai, dict) and isinstance(ai.get("kind"), str) and ai["kind"]:
        proposal.offer("kind", AI, _kind_named(db, vault_now(), name=ai["kind"]))

    # The title of a rule is a pattern of the other fields: made last, with what the fields will be.
    if rule_title:
        kind_row = db.get(Kind, proposal.values.get("kind")) if proposal.values.get("kind") else None
        rendered = rules.render_title(rule_title, sender=str(proposal.values.get("sender") or ""),
                                      kind=kind_row.name if kind_row else "", day=proposal.values.get("date"),
                                      amount=proposal.values.get("amount"),
                                      currency=str(proposal.values.get("currency") or "EUR"), language=language)
        if rendered:
            proposal.values["title"], proposal.origins["title"] = rendered, RULE
    changed = _apply(db, document, proposal, human)
    origins = {name: origin for name, origin in origins_before.items() if origin == PERSON}
    for name in FIELDS:
        if name in human:
            continue
        if name in proposal.origins:
            origins[name] = proposal.origins[name]
        elif name == "vault" and _default_vault(db, document):
            origins[name] = DEFAULT
    fresh = [r for r in outcome.applied if r not in counted]
    rules.count_hits(db, fresh, document.id)
    kept: dict[str, Any] = dict(origins)
    kept["_from"] = arrival
    kept["_rules"] = sorted(set(counted) | set(outcome.applied))[:50]
    if ai is not None:
        kept["_ai"] = ai
    if kept != stored:
        document.suggest = kept
    if changed:
        detail = {"fields": sorted(changed),
                  "from": {name: origins[name] for name in sorted(origins) if name in changed}}
        if later:
            # Written after the line that says the document was read (``recorded``), in the same transaction.
            db.info.setdefault(PENDING, {})[document.id] = detail
        else:
            changes.record(db, document.id, PROPOSED, detail=detail)
    return changed


PENDING = "sorting_proposed"


def recorded(db: Session, document_id: int) -> None:
    """The history line of the proposals made while the document was being read, after the line of the reading."""
    detail = db.info.get(PENDING, {}).pop(document_id, None)
    if detail is not None:
        changes.record(db, document_id, PROPOSED, detail=detail)


def _ai_values(db: Session, ai: dict[str, Any] | None, vault_id: int) -> dict[str, Any]:
    """What the AI proposed, as field values (it was checked when it came: ``ai_proposals.check``). Its kind is one the
    vault the document arrived in can choose."""
    if not ai:
        return {}
    out: dict[str, Any] = {}
    for name in ("title", "sender"):
        if isinstance(ai.get(name), str) and ai[name]:
            out[name] = ai[name]
    if isinstance(ai.get("kind"), str) and ai["kind"]:
        out["kind"] = _kind_named(db, vault_id, name=ai["kind"])
    if isinstance(ai.get("date"), str):
        try:
            out["date"] = Date.fromisoformat(ai["date"])
        except ValueError:
            pass
    if isinstance(ai.get("amount"), int) and not isinstance(ai.get("amount"), bool):
        out["amount"] = ai["amount"]
    return out


def _apply(db: Session, document: Document, proposal: Proposal, human: set[str]) -> list[str]:
    """Writes the proposed values the person did not set; the fields that changed."""
    changed: list[str] = []
    values = proposal.values
    if "vault" in values and "vault" not in human and values["vault"] != document.vault_id:
        source = document.vault_id
        document.vault_id = values["vault"]
        catalog.rehome(db, [document.id], document.vault_id)
        changes.tombstone(db, "gone", document_id=document.id, vault_id=source)
        changes.record(db, document.id, changes.MOVED, detail={"from": source, "to": document.vault_id, "by": "rule"})
        changed.append("vault")
    if "title" in values and "title" not in human:
        try:
            title = documents.clean_title(str(values["title"]))
        except Exception:  # noqa: BLE001 - a proposal that is no title is left out
            title = ""
        if title and title != document.title:
            document.title = title
            changed.append("title")
    if "sender" in values and "sender" not in human:
        try:
            sender_id = catalog.sender_named(db, document.vault_id, document.owner_id, str(values["sender"])).id
        except Exception:  # noqa: BLE001 - a name that is none is left out
            sender_id = None
        if sender_id is not None and sender_id != document.sender_id:
            old = document.sender_id
            document.sender_id = sender_id
            catalog.prune(db, [old] if old else [], [])
            changed.append("sender")
    if "kind" in values and "kind" not in human and values["kind"] != document.kind_id and db.get(Kind, values["kind"]):
        document.kind_id = values["kind"]
        changed.append("kind")
    if "date" in values and "date" not in human and values["date"] != document.date and _in_range(values["date"]):
        document.date = values["date"]
        changed.append("date")
    amount_ok = "amount" in values and abs(values["amount"]) <= documents.AMOUNT_LIMIT
    if amount_ok and "amount" not in human and values["amount"] != document.amount:
        document.amount = values["amount"]
        currency = str(values.get("currency") or "")
        if re.fullmatch(r"[A-Z]{3}", currency):
            document.currency = currency
        changed.append("amount")
    if "dates" in values and "dates" not in human and _in_range(values["dates"]):
        row = db.scalar(select(DocumentDate).where(DocumentDate.document_id == document.id,
                                                   DocumentDate.kind == "due"))
        if row is None:
            db.add(DocumentDate(document_id=document.id, kind="due", date=values["dates"]))
            changed.append("dates")
        elif row.date != values["dates"]:
            row.date = values["dates"]
            changed.append("dates")
    if "tags" in values and "tags" not in human:
        try:
            wanted = {t.id for t in catalog.tags_named(db, document.vault_id, document.owner_id, values["tags"])}
        except Exception:  # noqa: BLE001 - a word that is no tag leaves the tags as they are
            wanted = set()
        have = set(db.scalars(select(DocumentTag.tag_id).where(DocumentTag.document_id == document.id)))
        if wanted and wanted != have:
            db.execute(delete(DocumentTag).where(DocumentTag.document_id == document.id,
                                                 DocumentTag.tag_id.not_in(wanted)))
            for tag_id in wanted - have:
                db.add(DocumentTag(document_id=document.id, tag_id=tag_id))
            catalog.prune(db, [], have - wanted)
            changed.append("tags")
    if {"kind", "date"} & set(changed):
        # A proposal of the AI for a document in the inbox: its keeping time follows the kind (while it is being read
        # nothing is worked out yet, ``processing`` does it once the status is set).
        from . import keeping

        keeping.refresh(db, [document.id])
    if changed:
        document.change_seq = changes.next_seq(db)
        if {"vault", "sender", "kind", "date"} & set(changed):
            from . import jobs

            jobs.enqueue(db, jobs.RENAME, document.id)
    return changed


def _in_range(value: Any) -> bool:
    return isinstance(value, Date) and documents.DATE_MIN <= value <= documents.DATE_MAX


def mark_person(document: Document, fields: list[str]) -> None:
    """The fields a person changed are theirs from now on (``person``)."""
    names = {"kind": "kind", "title": "title", "sender": "sender", "date": "date", "amount": "amount",
             "dates": "dates", "tags": "tags", "vault": "vault"}
    mine = [names[f] for f in fields if f in names]
    if not mine:
        return
    stored = dict(document.suggest) if isinstance(document.suggest, dict) else {}
    for name in mine:
        stored[name] = PERSON
    document.suggest = stored


# --- The finisher -------------------------------------------------------------------------------------------------


def finish(db: Session, document: Document, version: Version, data: dict[str, Any]) -> None:
    """``processing.FINISHERS``: keeps the e-invoice the worker found and, for a new document on its way to the inbox,
    proposes its fields and asks the AI when it may (a job of its own, after this transaction)."""
    invoice = einvoices.keep(db, document, version, data)
    if document.status != PROCESSING or version.note == "paperless":
        return
    texts = data.get("texts")
    text = "\n".join(t for t in texts if isinstance(t, str)) if isinstance(texts, list) else ""
    db.flush()
    try:
        propose(db, document, text, invoice=invoice, later=True)
    except Exception as exc:  # noqa: BLE001 - proposals are a help: a document is never kept from the inbox by them
        logger.warning("Proposals for a document failed document_id=%s error=%s", document.id, type(exc).__name__)
    from . import ai_proposals

    ai_proposals.queue_if_allowed(db, document)


__all__ = ["PRIORITY", "Proposal", "finish", "last_time", "propose", "signs_of"]
