"""Exports: a ZIP of documents for the tax adviser or the own archive, packed in the background.

**What goes in.** The documents the person may see that match what was asked for: a period (the document's date), one
or more of the person's vaults, and the filters of the archive (the search, kind, sender, tag, owner). The rights are in
the query that finds them (``search.where`` with the person's scope and rights), at the moment the ZIP is packed, never
filtered afterwards. Documents in the trash and documents still being read are left out. Per document, as chosen: the
searchable PDF, the original as it came, the e-invoice as XML; and a list of all of them as CSV.

**How it looks inside.** Folders as on the disk: vault, year, sender; the file named by date and title
(``2026-10-06 Rechnung Heizungswartung.pdf``). Every part of a name goes through ``names.clean_segment``: no ``..``, no
separators, nothing a file system refuses; two files of the same name get ``(2)``. The list is UTF-8 with a byte order
mark (Excel reads it right), ``;`` between the fields, and a field a spreadsheet would take for a formula (``=``, ``+``,
``-``, ``@``, a tab or a return at its start) gets a ``'`` before it.

**Limits.** At most ``MAX_DOCUMENTS`` documents and ``MAX_BYTES`` in one ZIP, one export packing at a time per person
and a few waiting, and only when the disk has room. A ZIP is kept ``KEEP_DAYS`` days (longer while a link to it lasts)
and then removed with its links.

**A link for somebody without an account.** Like a link to a document (``services/sharing.py``): ``lnx_`` and 43 random
characters, found by its hash, the token sealed with the server's secret so that its maker can copy the address again,
ended by revoking it, by its date, by the operator's switch for links, with the export, and as soon as its maker no
longer sees every vault the documents in it came from (or is blocked or deleted). A wrong token answers 404 as every
other and counts on the brake of links.

**When it is ready** the person gets a notice like the other notices of nexpaper: a push to their devices and, with a
mail server and an address, a mail."""

from __future__ import annotations

import csv
import io
import logging
import secrets
import shutil
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import ColumnElement, and_, case, delete, func, select, update
from sqlalchemy.orm import Session

from .. import clock, private
from ..config import get_settings
from ..errors import error
from ..models import (
    PROCESSING,
    TRASH,
    Account,
    Document,
    DocumentDate,
    Export,
    ExportLink,
    Kind,
    Sender,
    Vault,
    VaultMember,
    Version,
)
from ..names import clean_segment
from ..security import decrypt_secret, encrypt_secret
from . import changes, einvoices, filetypes, jobs, rights, search, searchtext, sharing, storage

logger = logging.getLogger("nexpaper.exports")

MAX_DOCUMENTS = 20_000
MAX_BYTES = 20 * 1024**3
#: Exports a person may have waiting or being packed at once, and kept at all.
MAX_WAITING = 3
MAX_KEPT = 20
KEEP_DAYS = 7
#: What stays free on the disk besides the ZIP.
DISK_MARGIN = 512 * 1024 * 1024
LINK_PREFIX = "lnx_"
#: How many paths the preview shows.
SAMPLE = 6
QUEUED, PACKING, READY, FAILED = "queued", "packing", "ready", "failed"
#: Files that are packed already (PDFs, pictures) are stored as they are; text is packed.
PACKED_KINDS = (filetypes.PDF, filetypes.JPEG, filetypes.PNG, filetypes.HEIC, filetypes.TIFF,
                filetypes.WEBP, filetypes.AVIF)
CSV_NAME = {"de": "liste.csv", "en": "list.csv"}
CSV_HEADINGS = {
    "de": ("Datum", "Titel", "Absender", "Art", "Betrag", "Währung", "Rechnungsnummer", "Tresor", "Datei",
           "Fällig am", "Vertrag bis", "Kündigen bis", "Garantie bis", "Erledigt", "Aufbewahren bis"),
    "en": ("Date", "Title", "Sender", "Kind", "Amount", "Currency", "Invoice number", "Vault", "File",
           "Due", "Contract until", "Cancel by", "Warranty until", "Done", "Keep until"),
}
#: The deadlines in the list (F1): the columns of the dates, and the word for a deadline that is done.
DEADLINE_COLUMNS = ("due", "contract_end", "notice", "warranty_end")
DONE_WORD = {"de": {"due": "bezahlt", "contract_end": "gekündigt", "warranty_end": "erledigt"},
             "en": {"due": "paid", "contract_end": "cancelled", "warranty_end": "done"}}
#: The columns made here (a date, an amount, a currency, the day to keep until): taken as they are; every other one
#: came from a person.
MADE_HERE = (0, 4, 5, 14)
#: The start of a field a spreadsheet takes for a formula.
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
NO_DATE = {"de": "ohne Datum", "en": "undated"}
NO_SENDER = {"de": "ohne Absender", "en": "no sender"}
ORIGINAL = {"de": "Original", "en": "original"}


# --- What is asked for ----------------------------------------------------------------------------------------------


@dataclass
class Content:
    pdf: bool = True
    original: bool = False
    csv: bool = True
    xml: bool = True

    @property
    def any_file(self) -> bool:
        return self.pdf or self.original or self.xml


@dataclass
class Params:
    """What a person asks for: the period, the vaults, the filters of the archive, what goes in."""

    date_from: Date | None = None
    date_to: Date | None = None
    vault_ids: list[int] = field(default_factory=list)
    q: str = ""
    kind_id: int | None = None
    owner_id: int | None = None
    sender: str | None = None
    tag: str | None = None
    status: str | None = None
    content: Content = field(default_factory=Content)

    def stored(self) -> dict[str, Any]:
        return {
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "vault_ids": self.vault_ids, "q": self.q, "kind_id": self.kind_id, "owner_id": self.owner_id,
            "sender": self.sender, "tag": self.tag, "status": self.status,
            "content": {"pdf": self.content.pdf, "original": self.content.original, "csv": self.content.csv,
                        "xml": self.content.xml},
        }

    @classmethod
    def from_stored(cls, raw: Any) -> Params:
        data = raw if isinstance(raw, dict) else {}
        content = data.get("content") if isinstance(data.get("content"), dict) else {}

        def day(value: Any) -> Date | None:
            try:
                return Date.fromisoformat(value) if isinstance(value, str) else None
            except ValueError:
                return None

        def whole(value: Any) -> int | None:
            return value if type(value) is int else None

        return cls(
            date_from=day(data.get("date_from")), date_to=day(data.get("date_to")),
            vault_ids=[v for v in data.get("vault_ids") or [] if type(v) is int],
            q=str(data.get("q") or ""), kind_id=whole(data.get("kind_id")), owner_id=whole(data.get("owner_id")),
            sender=data.get("sender") if isinstance(data.get("sender"), str) else None,
            tag=data.get("tag") if isinstance(data.get("tag"), str) else None,
            status=data.get("status") if data.get("status") in ("inbox", "filed") else None,
            content=Content(pdf=content.get("pdf") is not False, original=content.get("original") is True,
                            csv=content.get("csv") is not False, xml=content.get("xml") is not False),
        )


def _query(raw: str) -> searchtext.Query:
    try:
        return searchtext.parse(raw)
    except searchtext.SearchError as exc:
        raise error(exc.code, "This search cannot be read.", 422) from exc


def check_params(db: Session, uid: int, params: Params) -> None:
    """The vaults must be ones the person is in (404 as for any vault they cannot see); a period that ends before it
    starts and an export with nothing in it are refused."""
    if not params.vault_ids:
        raise error("export_no_vault", "Choose at least one vault.", 422)
    if len(params.vault_ids) > 200:
        raise error("invalid_input", "The input is not valid.", 422)
    for vault_id in params.vault_ids:
        rights.require_vault(db, uid, vault_id)
    if params.date_from and params.date_to and params.date_from > params.date_to:
        raise error("export_period_invalid", "The period ends before it begins.", 422)
    if not params.content.any_file and not params.content.csv:
        raise error("export_empty_choice", "Choose at least one thing to put in.", 422)
    _query(params.q)


def where(db: Session, uid: int, params: Params) -> list[ColumnElement[bool]]:
    """The documents of the export, with the person's rights in the query: their scope in the index, their vaults and
    shares in the statement (``search.where``), the chosen vaults among the ones they are in."""
    query = _query(params.q)
    filters = search.Filters(kind_id=params.kind_id, sender=params.sender, tag=params.tag, owner_id=params.owner_id,
                             date_from=params.date_from, date_to=params.date_to, status=params.status)
    clauses = search.where(uid, query, filters, search.scope_of(db, uid) if query.has_text else [])
    clauses.append(Document.vault_id.in_(select(VaultMember.vault_id).where(
        VaultMember.user_id == uid, VaultMember.vault_id.in_(params.vault_ids))))
    clauses.append(Document.status.not_in((PROCESSING, TRASH)))
    return clauses


# --- What goes in, per document -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    """One file in the ZIP: where it goes, where it is on the disk, whether it is packed."""

    name: str
    source: Path
    stored: bool
    #: The bytes themselves, for a file that is not on the disk (the XML taken out of a ZUGFeRD PDF).
    data: bytes | None = None


def _kind(rel: str) -> str | None:
    return filetypes.KIND_OF_EXTENSION.get(Path(rel).suffix.lower())


def files_of(version: Version, content: Content) -> list[tuple[str, str, str]]:
    """``(what, relative path, extension)`` of one version: ``pdf``, ``original`` or ``xml``, each once."""
    out: list[tuple[str, str, str]] = []
    kind = _kind(version.original_path)
    original_ext = Path(version.original_path).suffix.lower()
    if kind == filetypes.XML:
        # An e-invoice that is XML only: it is its own file, under "XML" and under "originals".
        if content.xml or content.original:
            out.append(("xml", version.original_path, ".xml"))
        return out
    searchable = version.archive_path or (version.original_path if kind == filetypes.PDF else "")
    if content.pdf and searchable:
        out.append(("pdf", searchable, ".pdf"))
    if content.original and not (content.pdf and searchable == version.original_path):
        out.append(("original", version.original_path, original_ext))
    # The XML inside a ZUGFeRD or Factur-X PDF is not a file of its own: ``_pack`` adds it from the e-invoice.
    return out


class Names:
    """The names inside one ZIP: each once (``(2)`` for the second), compared without case."""

    def __init__(self) -> None:
        self.taken: set[str] = set()

    def free(self, folders: tuple[str, ...], stem: str, extension: str) -> str:
        counter = 1
        while True:
            name = stem if counter == 1 else f"{stem} ({counter})"
            path = "/".join((*folders, name + extension))
            if path.casefold() not in self.taken:
                self.taken.add(path.casefold())
                return path
            counter += 1


def folders_of(vault: Vault | None, document: Document, sender: Sender | None, language: str) -> tuple[str, ...]:
    year = str(document.date.year) if document.date else NO_DATE[language]
    return (
        clean_segment(vault.name if vault else "", "vault"),
        clean_segment(year, NO_DATE[language]),
        clean_segment(sender.name if sender else "", NO_SENDER[language]),
    )


def stem_of(document: Document, language: str) -> str:
    day = document.date.isoformat() if document.date else NO_DATE[language]
    return clean_segment(f"{day} {document.title}", day, 120)


def safe_cell(value: str) -> str:
    """A field of the list that a spreadsheet would take for a formula gets a ``'`` before it."""
    return "'" + value if value.startswith(FORMULA_START) else value


def amount_text(cents: int | None, language: str) -> str:
    if cents is None:
        return ""
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(cents), 100)
    return f"{sign}{whole}{',' if language == 'de' else '.'}{part:02d}"


# --- Finding them ---------------------------------------------------------------------------------------------------


@dataclass
class Found:
    document: Document
    version: Version | None
    vault: Vault | None
    sender: Sender | None
    kind: Kind | None


def matching(db: Session, uid: int, params: Params, limit: int) -> Iterator[Found]:
    """The documents of the export in the order of the ZIP (vault, date, id), with what their names are made of."""
    clauses = where(db, uid, params)
    after = 0
    seen = 0
    while seen < limit:
        rows = db.execute(
            select(Document, Version, Vault, Sender, Kind)
            .outerjoin(Version, (Version.document_id == Document.id) & (Version.n == Document.current_version))
            .outerjoin(Vault, Vault.id == Document.vault_id)
            .outerjoin(Sender, Sender.id == Document.sender_id)
            .outerjoin(Kind, Kind.id == Document.kind_id)
            .where(and_(*clauses), Document.id > after).order_by(Document.id).limit(min(500, limit - seen))
        ).all()
        if not rows:
            return
        for document, version, vault, sender, kind in rows:
            seen += 1
            yield Found(document, version, vault, sender, kind)
        after = rows[-1][0].id


@dataclass
class Preview:
    documents: int
    #: The sum of the amounts (cents), in all and per currency.
    total: int
    totals: dict[str, int]
    size: int
    sample: list[str]
    too_many: bool


def preview(db: Session, uid: int, params: Params, language: str) -> Preview:
    """How many documents, the sum of their amounts (per currency), about how large the ZIP gets, and the first paths
    in it. All counted in the database: the documents are not loaded, the files not looked at (the size is the one of
    the originals, once per kind of file chosen), and only the first few become paths."""
    check_params(db, uid, params)
    clauses = where(db, uid, params)
    current = (Version.document_id == Document.id) & (Version.n == Document.current_version)
    with changes.snapshot(db), search._bounded(db):
        count = int(db.scalar(select(func.count()).select_from(Document).where(and_(*clauses))) or 0)
        totals = {str(currency): int(amount or 0) for currency, amount in db.execute(
            select(Document.currency, func.sum(Document.amount)).where(and_(*clauses), Document.amount.is_not(None))
            .group_by(Document.currency).order_by(Document.currency)).all()}
        size = 0
        sample: list[str] = []
        if count <= MAX_DOCUMENTS:
            # As ``files_of`` takes them: a searchable copy beside the original counts as large as the original; a PDF
            # that is its own searchable copy is in the ZIP once, an e-invoice as XML once.
            content = params.content
            xml_file = func.lower(Version.original_path).like("%.xml")
            factor = case(
                (xml_file, int(content.xml or content.original)),
                (Version.archive_path != "", int(content.pdf) + int(content.original)),
                else_=int(content.pdf or content.original),
            )
            size = int(db.scalar(select(func.coalesce(func.sum(Version.size * factor), 0)).select_from(Document)
                                 .join(Version, current).where(and_(*clauses))) or 0)
            names = Names()
            first = db.execute(
                select(Document, Version, Vault, Sender, Kind).outerjoin(Version, current)
                .outerjoin(Vault, Vault.id == Document.vault_id).outerjoin(Sender, Sender.id == Document.sender_id)
                .outerjoin(Kind, Kind.id == Document.kind_id).where(and_(*clauses))
                .order_by(func.lower(Vault.name), func.coalesce(Document.date, "9999-12-31"), Document.id)
                .limit(SAMPLE)
            ).all()
            for document, version, vault, sender, kind in first:
                found = Found(document, version, vault, sender, kind)
                for what, _rel, extension in files_of(version, params.content) if version is not None else []:
                    if len(sample) < SAMPLE:
                        sample.append(_name(names, found, what, extension, language))
    if params.content.csv:
        sample.append(CSV_NAME[language])
    return Preview(documents=count, total=sum(totals.values()), totals=totals, size=size, sample=sample,
                   too_many=count > MAX_DOCUMENTS or size > MAX_BYTES)


def _order(found: Found) -> tuple[str, str, int]:
    vault = found.vault.name.casefold() if found.vault else ""
    return (vault, found.document.date.isoformat() if found.document.date else "9999", found.document.id)


def _name(names: Names, found: Found, what: str, extension: str, language: str) -> str:
    stem = stem_of(found.document, language)
    if what == "original":
        stem = f"{stem} ({ORIGINAL[language]})"
    return names.free(folders_of(found.vault, found.document, found.sender, language), stem, extension)


# --- Making one -----------------------------------------------------------------------------------------------------


def folder() -> Path:
    path = get_settings().data_dir / "exports"
    path.mkdir(parents=True, exist_ok=True)
    private.tighten(path)
    return path


def create(db: Session, uid: int, params: Params, language: str) -> Export:
    """An export, queued; packed by the job ``export``. Checked and written under the write lock, so a double click
    makes two at most up to the limit, never more."""
    check_params(db, uid, params)
    changes.write_lock(db)
    waiting = db.scalar(select(func.count()).select_from(Export).where(
        Export.user_id == uid, Export.state.in_((QUEUED, PACKING)))) or 0
    if waiting >= MAX_WAITING:
        raise error("export_busy", "Wait until your exports are packed.", 409, max=MAX_WAITING)
    kept = db.scalar(select(func.count()).select_from(Export).where(Export.user_id == uid)) or 0
    if kept >= MAX_KEPT:
        raise error("too_many_exports", "Delete an older export first.", 409, max=MAX_KEPT)
    now = clock.now()
    export = Export(user_id=uid, state=QUEUED, params=params.stored(), vault_ids=[],
                    language=language if language in CSV_NAME else "en", created_at=now,
                    expires_at=now + timedelta(days=KEEP_DAYS))
    db.add(export)
    db.flush()
    jobs.enqueue(db, jobs.EXPORT, export.id)
    db.commit()
    logger.info("Export queued export_id=%s", export.id)
    return export


def run_job(db: Session, export_id: int) -> None:
    """The job ``export``: the ZIP of one export, written to a temporary name and put in place when it is whole."""
    export = db.get(Export, export_id)
    if export is None or export.state not in (QUEUED, PACKING):
        db.rollback()
        return
    export.state = PACKING
    db.commit()
    try:
        _pack(db, export_id)
    except jobs.Interrupted:
        raise
    except PackError as exc:
        db.rollback()
        _failed(db, export_id, exc.code)
    except Exception as exc:
        db.rollback()
        _failed(db, export_id, "failed")
        logger.exception("An export could not be packed export_id=%s", export_id)
        raise jobs.GiveUp("failed") from exc


class PackError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _failed(db: Session, export_id: int, code: str) -> None:
    db.execute(update(Export).where(Export.id == export_id).values(state=FAILED, error=code[:40],
                                                                     finished_at=clock.now()))
    db.commit()
    logger.warning("An export failed export_id=%s error=%s", export_id, code)
    _tell(export_id)


def _pack(db: Session, export_id: int) -> None:
    export = db.get(Export, export_id)
    assert export is not None
    uid, language = export.user_id, export.language if export.language in CSV_NAME else "en"
    params = Params.from_stored(export.params)
    account = db.get(Account, uid)
    if account is None or account.blocked_at is not None:
        raise PackError("account")
    # The rights as they are now: a vault the person left since the export was asked for counts no more.
    params.vault_ids = [v for v in params.vault_ids if rights.vault_right(db, uid, v) is not None]
    if not params.vault_ids:
        raise PackError("nothing_found")
    with changes.snapshot(db):
        found = sorted(matching(db, uid, params, MAX_DOCUMENTS + 1), key=_order)
    if len(found) > MAX_DOCUMENTS:
        raise PackError("too_many_documents")
    if not found:
        raise PackError("nothing_found")
    names = Names()
    entries: list[Entry] = []
    rows: list[tuple[str, ...]] = []
    invoice_numbers = einvoices.numbers(db, [item.document.id for item in found])
    keep_until = dict(db.execute(select(DocumentDate.document_id, DocumentDate.date).where(
        DocumentDate.document_id.in_([item.document.id for item in found]), DocumentDate.kind == "keep_until")).all())
    terms = _terms(db, [item.document.id for item in found], language)
    vaults: set[int] = set()
    size = 0
    total = 0
    for item in found:
        document, version = item.document, item.version
        vaults.add(document.vault_id)
        total += document.amount or 0
        first = ""
        for what, rel, extension in files_of(version, params.content) if version is not None else []:
            try:
                source = storage.safe_path(rel)
            except storage.StorageError:
                continue
            if not source.is_file():
                continue
            name = _name(names, item, what, extension, language)
            entries.append(Entry(name, source, _kind(rel) in PACKED_KINDS))
            size += source.stat().st_size
            first = first or name
        if params.content.xml and version is not None and _kind(version.original_path) != filetypes.XML:
            # The e-invoice inside a ZUGFeRD or Factur-X PDF, as the XML it carried (the newest version that did).
            invoice = einvoices.latest(db, document.id)
            data = einvoices.embedded_xml(db, invoice.version_id) if invoice is not None else None
            if data:
                entries.append(Entry(_name(names, item, "xml", ".xml", language), Path(), False, data))
                size += len(data)
        rows.append((
            document.date.isoformat() if document.date else "", document.title,
            item.sender.name if item.sender else "", item.kind.name if item.kind else "",
            amount_text(document.amount, language), document.currency if document.amount is not None else "",
            invoice_numbers.get(document.id, ""), item.vault.name if item.vault else "", first,
            *terms.get(document.id, ("",) * (len(DEADLINE_COLUMNS) + 1)),
            keep_until[document.id].isoformat() if document.id in keep_until else "",
        ))
    if size > MAX_BYTES:
        raise PackError("too_large")
    try:
        free = shutil.disk_usage(folder()).free
    except OSError:
        free = size + DISK_MARGIN
    if free < size + DISK_MARGIN:
        raise PackError("disk_full")
    name = f"{export_id}-{secrets.token_hex(8)}.zip"
    target = folder() / name
    partial = target.with_suffix(".part")
    db.rollback()
    try:
        # A file dated before 1980 (a restore that reset the times) must not spoil the whole ZIP.
        with zipfile.ZipFile(partial, "w", allowZip64=True, strict_timestamps=False) as archive:
            for entry in entries:
                if jobs.stopping.is_set():
                    raise jobs.Interrupted
                if entry.data is not None:
                    archive.writestr(entry.name, entry.data, compress_type=zipfile.ZIP_DEFLATED)
                    continue
                archive.write(entry.source, entry.name,
                              compress_type=zipfile.ZIP_STORED if entry.stored else zipfile.ZIP_DEFLATED)
            if params.content.csv:
                archive.writestr(CSV_NAME[language], _csv(rows, language), compress_type=zipfile.ZIP_DEFLATED)
        private.tighten(partial)
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    db.expire_all()
    export = db.get(Export, export_id)
    if export is None:
        target.unlink(missing_ok=True)
        db.rollback()
        return
    now = clock.now()
    latest_link = db.scalar(select(func.max(ExportLink.until)).where(ExportLink.export_id == export_id,
                                                                     ExportLink.revoked_at.is_(None)))
    export.state, export.file, export.size, export.documents = READY, name, target.stat().st_size, len(found)
    export.total, export.vault_ids, export.finished_at, export.error = total, sorted(vaults), now, ""
    export.expires_at = max(now + timedelta(days=KEEP_DAYS), latest_link or now)
    db.commit()
    logger.info("Export packed export_id=%s documents=%s bytes=%s", export_id, len(found), export.size)
    _tell(export_id)


def _terms(db: Session, ids: list[int], language: str) -> dict[int, tuple[str, ...]]:
    """Per document the cells of its deadlines: due, contract end, last day to cancel, warranty, and what is done (the
    word and the day, ``bezahlt 2026-09-29``)."""
    from ..models import DocumentDate

    cells: dict[int, dict[str, str]] = {}
    done: dict[int, list[str]] = {}
    words = DONE_WORD.get(language, DONE_WORD["en"])
    for start in range(0, len(ids), 500):
        for row in db.scalars(select(DocumentDate).where(DocumentDate.document_id.in_(ids[start:start + 500]),
                                                         DocumentDate.kind.in_(tuple(words)))
                              .order_by(DocumentDate.document_id, DocumentDate.kind)):
            mine = cells.setdefault(row.document_id, {})
            mine[row.kind] = row.date.isoformat()
            if row.notice_date is not None:
                mine["notice"] = row.notice_date.isoformat()
            if row.done_at is not None:
                done.setdefault(row.document_id, []).append(f"{words[row.kind]} {row.done_at.date().isoformat()}")
    return {i: (*(c.get(k, "") for k in DEADLINE_COLUMNS), ", ".join(done.get(i, []))) for i, c in cells.items()}


def _csv(rows: list[tuple[str, ...]], language: str) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_HEADINGS[language])
    for row in rows:
        # The amount (made here, a number) stays as it is; every text that came from a person is made safe.
        writer.writerow([cell if index in MADE_HERE else safe_cell(cell) for index, cell in enumerate(row)])
    return "﻿".encode() + out.getvalue().encode("utf-8")


# --- Reading, deleting, cleaning up ---------------------------------------------------------------------------------


def of(db: Session, uid: int) -> list[Export]:
    return list(db.scalars(select(Export).where(Export.user_id == uid).order_by(Export.id.desc())))


def own(db: Session, uid: int, export_id: int) -> Export:
    """One export of the caller; everybody else's is 404 like one that does not exist."""
    export = db.get(Export, export_id)
    if export is None or export.user_id != uid:
        raise error("not_found", "Not found.", 404)
    return export


def sees_all(db: Session, uid: int, export: Export) -> bool:
    """Whether the person still sees every vault the documents in the ZIP came from (and is not blocked)."""
    account = db.get(Account, uid)
    if account is None or account.blocked_at is not None:
        return False
    wanted = {v for v in export.vault_ids or [] if type(v) is int}
    have = set(db.scalars(select(VaultMember.vault_id).where(VaultMember.user_id == uid,
                                                              VaultMember.vault_id.in_(wanted))))
    return wanted <= have


def file_of(db: Session, uid: int, export_id: int) -> tuple[Path, Export]:
    export = own(db, uid, export_id)
    if export.state != READY or not export.file:
        raise error("export_not_ready", "The export is not packed yet.", 409)
    if not sees_all(db, uid, export):
        raise error("export_outdated", "You no longer see everything in this export. Make a new one.", 409)
    path = folder() / export.file
    if not path.is_file():
        raise error("not_found", "Not found.", 404)
    return path, export


def remove(db: Session, uid: int, export_id: int) -> None:
    changes.write_lock(db)
    export = own(db, uid, export_id)
    name = export.file
    db.delete(export)
    db.commit()
    if name:
        (folder() / name).unlink(missing_ok=True)
    logger.info("Export deleted export_id=%s", export_id)


def sweep(db: Session) -> int:
    """Exports whose time is up go with their file and links; files without an export too (a stop while packing)."""
    now = clock.now()
    gone = list(db.scalars(select(Export).where(Export.expires_at <= now)))
    names = [export.file for export in gone if export.file]
    if gone:
        db.execute(delete(Export).where(Export.id.in_([export.id for export in gone])))
    db.commit()
    for name in names:
        (folder() / name).unlink(missing_ok=True)
    kept = set(db.scalars(select(Export.file).where(Export.file != "")))
    packing = {export_id for (export_id,) in db.execute(select(Export.id).where(Export.state == PACKING))}
    db.rollback()
    for path in folder().iterdir():
        # An export being packed writes its file and then names it in the database: neither is touched meanwhile.
        prefix = path.name.split("-", 1)[0]
        busy = prefix.isdigit() and int(prefix) in packing
        if path.is_file() and path.name not in kept and not busy:
            path.unlink(missing_ok=True)
    if gone:
        logger.info("Exports removed count=%s", len(gone))
    return len(gone)


# --- Links ----------------------------------------------------------------------------------------------------------


def _sealed_with(token_hash: str) -> str:
    return "export-link:" + token_hash


def live(now: datetime, max_days: int) -> ColumnElement[bool]:
    """A link that works right now (the operator's switch and the maker's vaults aside): not revoked, before its end,
    not older than the longest the operator allows now, its maker the owner of the export and not blocked."""
    return and_(
        ExportLink.revoked_at.is_(None), ExportLink.until > now,
        ExportLink.created_at > now - timedelta(days=max_days),
        ExportLink.created_by == Export.user_id,
        Export.user_id.in_(select(Account.id).where(Account.blocked_at.is_(None))),
    )


def ends(link: ExportLink, max_days: int) -> datetime:
    return min(link.until, link.created_at + timedelta(days=max_days))


def status_of(db: Session, link: ExportLink, export: Export, current: sharing.LinkRules) -> str:
    if link.revoked_at is not None:
        return "revoked"
    if not current.allowed:
        return "off"
    if ends(link, current.max_days) <= clock.now():
        return "expired"
    if export.state == READY and not sees_all(db, export.user_id, export):
        return "ended"
    return "active"


def links_of(db: Session, uid: int, export_id: int) -> list[ExportLink]:
    own(db, uid, export_id)
    return list(db.scalars(select(ExportLink).where(ExportLink.export_id == export_id).order_by(ExportLink.id.desc())))


def clean_recipient(recipient: str) -> str:
    name = " ".join(recipient.split())
    if not name or len(name) > sharing.RECIPIENT_MAX or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise error("invalid_recipient", f"Say who the link is for (1 to {sharing.RECIPIENT_MAX} characters).", 422)
    return name


def create_link(db: Session, uid: int, export_id: int, recipient: str, days: int) -> tuple[ExportLink, str]:
    name = clean_recipient(recipient)
    changes.write_lock(db)
    export = own(db, uid, export_id)
    current = sharing.rules(db)
    if not current.allowed:
        raise error("links_off", "The operator has switched links to the outside off.", 409)
    if not 1 <= days <= current.max_days:
        raise error("invalid_days", f"A link lasts 1 to {current.max_days} days.", 422, max_days=current.max_days)
    if export.state == FAILED:
        raise error("export_failed", "This export could not be packed.", 409)
    now = clock.now()
    open_ones = db.scalar(select(func.count()).select_from(ExportLink).join(Export, Export.id == ExportLink.export_id)
                          .where(ExportLink.export_id == export_id, live(now, current.max_days))) or 0
    if open_ones >= sharing.MAX_LINKS_PER_DOCUMENT:
        raise error("too_many_links", f"At most {sharing.MAX_LINKS_PER_DOCUMENT} open links.", 409)
    token = LINK_PREFIX + secrets.token_urlsafe(32)
    hashed = sharing.digest(token)
    link = ExportLink(export_id=export_id, recipient=name, token_hash=hashed,
                      token_enc=encrypt_secret(token, _sealed_with(hashed)), until=now + timedelta(days=days),
                      created_by=uid, created_at=now)
    db.add(link)
    # The ZIP stays as long as the link lasts.
    export.expires_at = max(export.expires_at, link.until)
    db.commit()
    logger.info("Export link made export_id=%s days=%s", export_id, days)
    return link, token


def address(db: Session, uid: int, export_id: int, link_id: int) -> str:
    own(db, uid, export_id)
    link = db.scalar(select(ExportLink).where(ExportLink.id == link_id, ExportLink.export_id == export_id))
    if link is None or link.revoked_at is not None or link.created_by != uid:
        raise error("not_found", "Not found.", 404)
    token = decrypt_secret(link.token_enc, _sealed_with(link.token_hash))
    if not token or sharing.digest(token) != link.token_hash:
        raise error("link_unreadable", "This address cannot be shown again. Make a new link.", 409)
    return token


def revoke_link(db: Session, uid: int, export_id: int, link_id: int) -> None:
    changes.write_lock(db)
    own(db, uid, export_id)
    link = db.scalar(select(ExportLink).where(ExportLink.id == link_id, ExportLink.export_id == export_id))
    if link is None:
        raise error("not_found", "Not found.", 404)
    if link.revoked_at is None:
        link.revoked_at = clock.now()
    db.commit()


def check_link(db: Session, token: str) -> tuple[ExportLink, Export] | None:
    """The link and its export for a token that works right now, else None. Everything but the maker's vaults is in
    the query; those are looked at after (a ZIP packed before the maker left a vault must not go out)."""
    if not token.startswith(LINK_PREFIX) or len(token) > 100:
        return None
    current = sharing.rules(db)
    if not current.allowed:
        return None
    row = db.execute(
        select(ExportLink, Export).join(Export, Export.id == ExportLink.export_id)
        .where(ExportLink.token_hash == sharing.digest(token), live(clock.now(), current.max_days),
               Export.state != FAILED)
    ).first()
    if row is None:
        return None
    link, export = row
    if export.state == READY and not sees_all(db, export.user_id, export):
        return None
    return link, export


def open_link(db: Session, token: str, viewer: int | None) -> tuple[ExportLink, Export] | None:
    """As ``check_link``, and the opening counts (not for the maker looking at it)."""
    found = check_link(db, token)
    if found is None:
        return None
    link, export = found
    # The maker looking does not count, and neither does the page asking while the ZIP is still being packed.
    if (viewer is not None and viewer == export.user_id) or export.state != READY:
        return found
    db.execute(update(ExportLink).where(ExportLink.id == link.id).values(
        opened_count=ExportLink.opened_count + 1, last_opened_at=clock.now()))
    db.commit()
    db.refresh(link)
    return link, export


# --- The notice -----------------------------------------------------------------------------------------------------

TEXTS = {
    "de": {"ready": ("Export fertig", "Dein ZIP mit {count} Dokumenten liegt bereit."),
           "failed": ("Export fehlgeschlagen", "Das ZIP konnte nicht gepackt werden.")},
    "en": {"ready": ("Export ready", "Your ZIP with {count} documents is ready."),
           "failed": ("Export failed", "The ZIP could not be packed.")},
}
#: Where a tap leads: the archive, which opens the exports.
EXPORTS_PATH = "/?export=1"


def _tell(export_id: int) -> None:
    from . import notices

    notices.later(_send, export_id)


def _send(export_id: int) -> None:
    from email.message import EmailMessage

    from ..db import SessionLocal
    from . import mailer, notices, push

    with SessionLocal() as db:
        export = db.get(Export, export_id)
        account = db.get(Account, export.user_id) if export is not None else None
        if export is None or account is None:
            return
        state, count, uid = export.state, export.documents, account.id
        mail_to = account.email if account.email and account.email_confirmed_at and mailer.configured(db) else ""
        base = sharing_base(db)
        language = notices.language_of(account.language)
    what = "ready" if state == READY else "failed"

    def message_for(lang: str) -> Any:
        title, body = TEXTS[notices.language_of(lang or language)][what]
        return push.Message(title=title, body=body.format(count=count), url=EXPORTS_PATH, desk=EXPORTS_PATH,
                            tag=f"export-{export_id}")

    push.send_to_person(uid, message_for)
    if mail_to:
        message = EmailMessage()
        message["To"] = mail_to
        message["Subject"] = "Your nexpaper export is ready" if what == "ready" else "Your nexpaper export failed"
        where = f"{base}{EXPORTS_PATH}" if base else "nexpaper, Archive, Export"
        message.set_content(
            (f"The ZIP with {count} documents you asked for is ready.\n\nDownload it here: {where}\n"
             f"It is kept for {KEEP_DAYS} days.\n") if what == "ready"
            else f"The ZIP you asked for could not be packed. Try again in nexpaper: {where}\n"
        )
        with SessionLocal() as db:
            try:
                mailer.send_message(db, message)
            except mailer.MailError:
                logger.warning("Export notice not mailed export_id=%s", export_id)


def sharing_base(db: Session) -> str:
    from . import settings_service

    return settings_service.public_url(db)


__all__ = ["Content", "Params", "create", "preview", "run_job", "sweep"]
